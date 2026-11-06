import dataclasses
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from artifactory import harness
from artifactory.acceptance import load_acceptance
from artifactory.goproxy import build_goproxy
from artifactory.harness import RoundResult, export_kits, prepare_trial, run_trial
from artifactory.pyindex import build_pyindex, download_wheels, standard_wheels
from artifactory.result import CheckResult, TrialResult
from artifactory.sandbox import allowlist, egress_ruleset, sandbox_command

ROOT = Path(__file__).resolve().parents[2]
GO_TEST_DIR = ROOT / "tests" / "acceptance" / "go-url-shortener"
GO_TEST = load_acceptance(GO_TEST_DIR)
SAMPLES = ROOT / "samples" / "go"


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    p = tmp_path_factory.mktemp("proxy")
    build_goproxy([SAMPLES / m for m in GO_TEST.modules], p)
    return p


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def fake_agent(script: str) -> list[str]:
    return ["/bin/sh", "-c", script]


def test_opencode_argv_uses_private_server_and_auto():
    argv = harness.opencode_command("build it")
    assert argv[0].endswith("opencode") and argv[1] == "run"
    assert "--standalone" in argv
    assert "--auto" in argv
    i = argv.index("--format")
    assert argv[i + 1] == "json"
    i = argv.index("--model")
    assert argv[i + 1] == "agentbox/ornith-1.5-q4"
    assert argv[-1] == "build it"


def test_sandbox_blocks_write_outside_project(tmp_path, proxy):
    tag = uuid.uuid4().hex
    real_home_file = Path.home() / f"artifactory-sandbox-probe-{tag}"
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    host_file = host_dir / "x"
    tmp_file = Path("/tmp") / f"artifactory-sandbox-probe-{tag}"
    visible_file = proxy / f"probe-{tag}"  # a host path the sandbox can see (read-only)
    script = (
        f"ls {proxy} > /dev/null; echo seen=$? > status; "
        f"echo x > {visible_file}; echo visible=$? >> status; "
        f"echo x > {real_home_file}; echo home=$? >> status; "
        f"echo x > {host_file}; echo host=$? >> status; "
        f"echo x > {tmp_file}; echo tmp=$? >> status; "
        "echo x > inside.txt; echo project=$? >> status"
    )
    try:
        result = run_trial(GO_TEST, "# index", tmp_path / "trial-1", None, proxy,
                           opencode_argv=fake_agent(script))
        assert not real_home_file.exists()
        assert not host_file.exists()
        assert not visible_file.exists()
        assert not tmp_file.exists()  # sandbox /tmp is private
        status = (tmp_path / "trial-1" / "project" / "status").read_text().split()
        assert "home=0" not in status and any(s.startswith("home=") for s in status)
        assert "host=0" not in status and any(s.startswith("host=") for s in status)
        assert "seen=0" in status
        assert "visible=0" not in status and any(s.startswith("visible=") for s in status)
        assert "project=0" in status
        assert (tmp_path / "trial-1" / "project" / "inside.txt").read_text() == "x\n"
        assert result.reason is None
    finally:
        real_home_file.unlink(missing_ok=True)
        tmp_file.unlink(missing_ok=True)
        visible_file.unlink(missing_ok=True)


def test_agent_output_is_recorded_under_repo_results(proxy):
    """Transcript and stderr reach their files even where pasta's SELinux domain cannot write (user_home_t)."""
    trial_dir = ROOT / "results" / f"_pytest-{uuid.uuid4().hex}" / "trial-1"
    try:
        run_trial(GO_TEST, "# index", trial_dir, None, proxy,
                  opencode_argv=fake_agent('echo \'{"type":"text"}\'; echo oops >&2'))
        assert (trial_dir / "transcript.jsonl").read_text() == '{"type":"text"}\n'
        assert "oops" in (trial_dir / "opencode.log").read_text()
        assert (trial_dir / "checker.log").stat().st_size > 0 or (trial_dir / "checker.json").is_file()
    finally:
        subprocess.run(["chmod", "-R", "u+w", str(trial_dir.parent)], check=False)
        shutil.rmtree(trial_dir.parent, ignore_errors=True)


def test_trial_home_has_only_minimal_opencode_config(tmp_path, proxy):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, proxy)
    cfg = json.loads((trial.home / ".config" / "opencode" / "opencode.jsonc").read_text())
    assert set(cfg["provider"]) == {"agentbox"}
    agentbox = cfg["provider"]["agentbox"]
    assert set(agentbox["models"]) == {"ornith-1.5-q4"}
    assert agentbox["options"]["baseURL"] == "http://192.168.50.174:8080/v1"
    for key in ("instructions", "plugin", "mcp", "agent", "command", "skills"):
        assert key not in cfg
    names = {p.name.lower() for p in trial.home.rglob("*")}
    for banned in ("agents.md", "claude.md", "skills", "skill", "plugins", "plugin", "agents", "agent",
                   "commands", "command"):
        assert banned not in names
    assert (trial.project / "MODULES.md").read_text() == "# index"
    assert git("status", "--porcelain", cwd=trial.project) == ""


def test_git_insteadof_points_at_mirror(tmp_path):
    mirrors = tmp_path / "mirrors"
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    (src / "f").write_text("x")
    git("add", "f", cwd=src)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=src)
    git("clone", "-q", "--mirror", str(src), str(mirrors / "CrashKit.git"), cwd=tmp_path)
    expected = git("ls-remote", str(mirrors / "CrashKit.git"), cwd=tmp_path)

    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", mirrors, None)
    cmd = harness.agent_command(trial, ["git", "ls-remote", "git@repo.billbert.co:yalt/CrashKit.git"])
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_sandbox_cannot_reach_host_loopback(tmp_path):
    """Host services on localhost (MCP servers, agent daemons) must be out of reach; the LAN stays reachable."""
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
        probe = ("import socket,sys\n"
                 "try:\n"
                 f"    socket.create_connection(('127.0.0.1', {port}), timeout=3); print('reached')\n"
                 "except OSError: print('blocked')\n")
        cmd = harness.agent_command(trial, ["/usr/bin/python3", "-c", probe])
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "blocked"


EGRESS_PROBE = """\
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
start = time.monotonic()
try:
    socket.create_connection((host, port), timeout=10).close(); print("reached")
except OSError as e: print(type(e).__name__, f"{time.monotonic() - start:.2f}")
"""
FAST_REFUSAL = ("ConnectionRefusedError", "PermissionError")  # tcp reset / EPERM from the output chain
MODEL_HOST, MODEL_PORT = "192.168.50.174", 8080


def _sandbox_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def _probe(cmd_for, host, port):
    r = _sandbox_run(cmd_for(["/usr/bin/python3", "-c", EGRESS_PROBE, host, str(port)]))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _host_reaches(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close()
        return True
    except OSError:
        return False


def _require_host_reaches(host, port):
    """Positive control: a blocked probe only means something if the host itself gets through."""
    if not _host_reaches(host, port):
        pytest.skip(f"{host}:{port} is not reachable from this host either")


def _assert_refused_fast(out):
    name, _, seconds = out.partition(" ")
    assert name in FAST_REFUSAL, out
    assert float(seconds) < 2, out  # rejected by the chain, not left to time out


@pytest.fixture
def agent_trial(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTIFACTORY_SANDBOX_ALLOW", raising=False)
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    return trial, lambda argv: harness.agent_command(trial, argv)


@pytest.mark.parametrize("host,port", [("1.1.1.1", 443), ("8.8.8.8", 53), (MODEL_HOST, 22),
                                       ("2606:4700:4700::1111", 443)])
def test_sandbox_egress_refuses_other_destinations(agent_trial, host, port):
    _require_host_reaches(host, port)
    _, cmd_for = agent_trial
    _assert_refused_fast(_probe(cmd_for, host, port))


def test_sandbox_egress_refuses_udp(agent_trial):
    _, cmd_for = agent_trial
    udp = ("import socket\n"
           "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
           "try: s.sendto(b'x', ('1.1.1.1', 53)); print('sent')\n"
           "except OSError as e: print(type(e).__name__)\n")
    r = _sandbox_run(cmd_for(["/usr/bin/python3", "-c", udp]))
    assert r.stdout.strip() == "PermissionError", r.stdout + r.stderr


def test_sandboxed_process_cannot_lift_the_rules(agent_trial):
    _require_host_reaches("1.1.1.1", 443)
    _, cmd_for = agent_trial
    script = ("nft flush ruleset; echo nft=$?; ip route add default dev lo; echo route=$?; "
              "/usr/bin/python3 -c \"$0\" 1.1.1.1 443")
    r = _sandbox_run(cmd_for(["/bin/sh", "-c", script, EGRESS_PROBE]))
    lines = r.stdout.strip().splitlines()
    assert "nft=0" not in lines and "route=0" not in lines, r.stdout + r.stderr
    _assert_refused_fast(lines[-1])


def test_sandbox_has_no_host_resolver(agent_trial):
    """Only shows the systemd-resolved socket is not bound in; the egress chain is tested above."""
    _, cmd_for = agent_trial
    dns = ("import socket\n"
           "try: socket.getaddrinfo('example.com', 443); print('resolved')\n"
           "except OSError: print('no resolver')\n")
    r = _sandbox_run(cmd_for(["/usr/bin/python3", "-c", dns]))
    assert r.stdout.strip() == "no resolver", r.stderr


def test_sandbox_egress_reaches_model_server(agent_trial):
    _require_host_reaches(MODEL_HOST, MODEL_PORT)
    _, cmd_for = agent_trial
    assert _probe(cmd_for, MODEL_HOST, MODEL_PORT) == "reached"


def test_allowed_ipv6_endpoint_connects(tmp_path):
    host, port = "2606:4700:4700::1111", 443
    _require_host_reaches(host, port)
    cmd = sandbox_command(tmp_path, tmp_path, [], ["/usr/bin/python3", "-c", EGRESS_PROBE, host, str(port)],
                          {"PATH": "/usr/bin"}, allow=[(host, port)])
    assert _sandbox_run(cmd).stdout.strip() == "reached"


def test_checker_sandbox_ignores_allow_env_and_has_no_network(tmp_path, monkeypatch, proxy):
    _require_host_reaches(MODEL_HOST, MODEL_PORT)
    monkeypatch.setenv("ARTIFACTORY_SANDBOX_ALLOW", f"{MODEL_HOST}:{MODEL_PORT},1.1.1.1:443")
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, proxy)
    cmd = harness.checker_command(trial, GO_TEST_DIR, "go", GO_TEST.fixture, tmp_path / "out.json", "main", False)
    ruleset = next(a for a in cmd if a.startswith("table inet sandbox_egress"))
    assert "daddr" not in ruleset, ruleset
    # The same command line with the checker's argv swapped for a probe: the model server is refused.
    probe = ["/usr/bin/python3", "-c", EGRESS_PROBE, MODEL_HOST, str(MODEL_PORT)]
    (trial.dir / "checker-home").mkdir()  # run_checker makes it before running the checker
    r = _sandbox_run(cmd[:cmd.index("--chdir") + 3] + probe)
    _assert_refused_fast(r.stdout.strip() or r.stderr)
    # The agent sandbox does take the extra endpoints.
    agent_rules = next(a for a in harness.agent_command(trial, ["true"]) if a.startswith("table inet"))
    assert "ip daddr 1.1.1.1 tcp dport 443 accept" in agent_rules


def test_sandbox_allowlist_env_adds_endpoints(monkeypatch):
    monkeypatch.setenv("ARTIFACTORY_SANDBOX_ALLOW", "10.0.0.5:5555, [fd00::1]:443")
    assert allowlist([("192.168.50.174", 8080)]) == [("192.168.50.174", 8080), ("10.0.0.5", 5555), ("fd00::1", 443)]
    rules = egress_ruleset(allowlist())
    assert "ip daddr 10.0.0.5 tcp dport 5555 accept" in rules
    assert "ip6 daddr fd00::1 tcp dport 443 accept" in rules
    for bad in ("nuget.org:443", "[fe80::1%eth0]:443", "10.0.0.5:0"):
        monkeypatch.setenv("ARTIFACTORY_SANDBOX_ALLOW", bad)
        with pytest.raises(ValueError):
            allowlist()


def test_model_endpoints_resolve_hostnames_on_the_host(monkeypatch):
    assert harness.model_endpoints("http://192.168.50.174:8080/v1") == [("192.168.50.174", 8080)]
    assert set(harness.model_endpoints("http://localhost:9000/v1")) <= {("127.0.0.1", 9000), ("::1", 9000)}
    assert harness.model_endpoints("http://localhost/v1")[0][1] == 80
    fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 8080)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::7", 8080, 0, 0))]
    monkeypatch.setattr(harness.socket, "getaddrinfo", lambda *a, **k: fake)
    assert harness.model_endpoints("http://llama.lan:8080/v1") == [("10.1.2.3", 8080), ("fd00::7", 8080)]


def test_model_endpoints_unresolvable_host_names_llama_url(monkeypatch):
    def fail(*a, **k):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(harness.socket, "getaddrinfo", fail)
    with pytest.raises(RuntimeError, match="LLAMA_URL 'http://nowhere.invalid:8080/v1'"):
        harness.model_endpoints("http://nowhere.invalid:8080/v1")


@pytest.mark.godot
def test_godot_build_restores_offline_inside_the_sandbox(tmp_path, monkeypatch):
    """dotnet build needs no internet: Godot.NET.Sdk and its packages come from the host NuGet cache."""
    monkeypatch.delenv("ARTIFACTORY_SANDBOX_ALLOW", raising=False)
    if not harness.NUGET_PACKAGES.is_dir():
        pytest.skip(f"{harness.NUGET_PACKAGES} is missing")
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    for f in (Path(__file__).parent / "data" / "godot" / "base").iterdir():
        shutil.copy(f, trial.project / f.name)
    r = subprocess.run(harness.agent_command(trial, ["dotnet", "build", "TrialGame.csproj", "-nodeReuse:false"]),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_trial_timeout_still_checks(tmp_path, proxy):
    test = dataclasses.replace(GO_TEST, time_limit_s=3)
    trial_dir = tmp_path / "trial-1"
    # A detached grandchild must die with the sandbox, not outlive the kill.
    script = "(setsid sh -c 'sleep 5; touch late') & sleep 600"
    start = time.monotonic()
    result = run_trial(test, "# index", trial_dir, None, proxy, opencode_argv=fake_agent(script),
                       test_dir=GO_TEST_DIR)
    assert time.monotonic() - start < 300
    assert result.reason == "timeout"
    assert not result.passed
    names = {c.name for c in result.checks}
    assert {"build", "tests", "service_works", "modules_installed"} <= names
    saved = json.loads((trial_dir / "checker.json").read_text())
    assert saved["reason"] == "timeout" and saved["trial"] == "trial-1"
    time.sleep(max(0.0, 7 - (time.monotonic() - start)))
    assert not (trial_dir / "project" / "late").exists()


def _trial(passed: bool, k: int) -> TrialResult:
    return TrialResult("t", f"trial-{k}", [CheckResult("build", passed, "")], None)


def test_round_bar_is_four_of_five():
    four = RoundResult("t", 1, [_trial(True, k) for k in range(4)] + [_trial(False, 4)])
    assert four.passes == 4 and four.met_bar
    three = RoundResult("t", 1, [_trial(True, k) for k in range(3)] + [_trial(False, k) for k in (3, 4)])
    assert three.passes == 3 and not three.met_bar
    timed_out = TrialResult("t", "trial-5", [CheckResult("build", True, "")], "timeout")
    assert not RoundResult("t", 1, [_trial(True, k) for k in range(3)] + [timed_out]).met_bar


def test_bar_does_not_apply_below_five_trials():
    three = RoundResult("t", 1, [_trial(True, k) for k in range(3)])
    assert three.passes == 3 and three.met_bar is None
    assert json.loads(three.to_json())["met_bar"] is None
    assert RoundResult("t", 1, [_trial(True, k) for k in range(4)]).met_bar is None


def test_every_kit_url_form_resolves_to_mirrors(tmp_path):
    cfg = tmp_path / "gitconfig"
    cfg.write_text(harness._gitconfig(tmp_path / "mirrors"))
    for form in harness.KIT_REMOTE_FORMS:
        out = subprocess.run(["git", "ls-remote", "--get-url", f"{form}PoolKit.git"],
                             env={"GIT_CONFIG_GLOBAL": str(cfg), "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, cwd=tmp_path).stdout.strip()
        assert out == f"file://{tmp_path / 'mirrors'}/PoolKit.git"


DROP_EVENT = ('{"type":"error","sessionID":"ses_1","error":{"type":"unknown","message":'
              '"Transport: ECONNRESET: The socket connection was closed unexpectedly."}}')


def test_resume_command_continues_the_session():
    argv = harness.opencode_command("build it")
    resumed = harness.resume_command(argv, "ses_1")
    assert resumed[:-3] == argv[:-1]
    assert resumed[-3:] == ["--session", "ses_1", harness.RESUME_PROMPT]
    assert harness.resume_command(argv, None) == argv


def test_model_drop_reads_only_this_attempt(tmp_path):
    transcript, log = tmp_path / "transcript.jsonl", tmp_path / "opencode.log"
    transcript.write_text('{"type":"step_start","sessionID":"ses_1"}\n' + DROP_EVENT + "\n")
    log.write_text("")
    assert harness._model_drop(transcript, 0, log, 0) == (
        "ses_1", "Transport: ECONNRESET: The socket connection was closed unexpectedly.")
    at = transcript.stat().st_size
    with open(transcript, "a") as f:
        f.write('{"type":"text","sessionID":"ses_1"}\n')
    assert harness._model_drop(transcript, at, log, 0) is None
    # A run that never started a session: only the standalone server's failure shows, in the log.
    log.write_text("Couldn't get any nameserver address\nError: Standalone server exited before reporting readiness\n")
    assert harness._model_drop(transcript, transcript.stat().st_size, log, 0) == (
        None, "Standalone server exited before reporting readiness")


def test_dropped_connection_is_resumed(tmp_path, proxy, monkeypatch):
    monkeypatch.setattr(harness, "RESUME_PAUSE_S", 0)
    trial_dir = tmp_path / "trial-1"
    script = (f'if [ "$1" = --session ]; then echo \'{{"type":"text","sessionID":"\'$2\'"}}\'; touch "resumed-$2"; '
              f"else echo '{{\"type\":\"step_start\",\"sessionID\":\"ses_1\"}}'; echo '{DROP_EVENT}'; fi")
    result = run_trial(GO_TEST, "# index", trial_dir, None, proxy,
                       opencode_argv=[*fake_agent(script), "agent", "the prompt"], test_dir=GO_TEST_DIR)
    assert result.resumes == 1
    assert result.reason is None
    assert (trial_dir / "project" / "resumed-ses_1").exists()
    lines = (trial_dir / "transcript.jsonl").read_text().splitlines()
    assert len(lines) == 3 and "ECONNRESET" in lines[1]
    assert json.loads((trial_dir / "checker.json").read_text())["resumes"] == 1


def test_repeated_drops_are_an_infrastructure_failure(tmp_path, proxy, monkeypatch):
    monkeypatch.setattr(harness, "RESUME_PAUSE_S", 0)
    trial_dir = tmp_path / "trial-1"
    script = f"echo '{DROP_EVENT}'"
    result = run_trial(GO_TEST, "# index", trial_dir, None, proxy,
                       opencode_argv=[*fake_agent(script), "agent", "the prompt"], test_dir=GO_TEST_DIR)
    assert result.resumes == harness.MAX_RESUMES
    assert result.reason.startswith("infrastructure: model connection dropped after 3 resumes")
    assert not result.passed
    rnd = RoundResult("t", 1, [result, _trial(True, 2)])
    assert rnd.infrastructure_failures == 1
    assert json.loads(rnd.to_json())["infrastructure_failures"] == 1


GOLDEN = ROOT / "internal" / "index" / "testdata"
GODOT_TEST = load_acceptance(ROOT / "tests" / "acceptance" / "godot-capsule-room")


@pytest.fixture(scope="module")
def cli(tmp_path_factory):
    return harness.build_cli(tmp_path_factory.mktemp("cli"))


def test_render_index_matches_golden(cli):
    out = harness.render_index(cli, "go", f"dir:{SAMPLES}", sorted(d.name for d in SAMPLES.iterdir() if (d / "go.mod").is_file()))
    assert out == (GOLDEN / "go.golden.md").read_text()


def test_render_index_raises_with_cli_stderr(cli):
    with pytest.raises(RuntimeError, match="artifactory"):
        harness.render_index(cli, "go", "dir:/nonexistent-provider-root", ["nope"])


def test_render_index_godot_matches_golden(cli):
    mirrors = harness.RESULTS / "mirrors"
    if not all((mirrors / f"{m}.git").is_dir() for m in GODOT_TEST.modules):
        pytest.skip("results/mirrors lacks the godot kits; run `artifactory mirror`")
    out = harness.render_index(cli, "godot-csharp", f"dir:{mirrors}", GODOT_TEST.modules)
    assert out == (GOLDEN / "godot-csharp.golden.md").read_text()


def _product_mirrors(tmp_path, modules=None):
    """Local bare mirror stand-ins for the godot test's kits (no network)."""
    mirrors = tmp_path / "mirrors"
    for name in modules or GODOT_TEST.modules:
        src = tmp_path / "src" / name
        src.mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=src)
        (src / "README.md").write_text(name)
        (src / "module.yaml").write_text(
            f"name: {name}\necosystem: godot-csharp\nversion: 0.1.0\nsummary: stand-in\n"
            f"replaces:\n  - something\ninstall: git submodule add git@repo.billbert.co:artifactory/{name}.git addons/{name}\n"
            f"entry:\n  - {name}.Instance\nliveness: \"[{name}] live\"\ndocs: README.md\nexample: README.md\ntest: none\n")
        git("add", "-A", cwd=src)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=src)
        git("tag", "v0.1.0", cwd=src)
        git("clone", "-q", "--mirror", str(src), str(mirrors / f"{name}.git"), cwd=tmp_path)
    return mirrors


def test_prepare_trial_product_mode(cli, tmp_path):
    mirrors = _product_mirrors(tmp_path)
    trial = prepare_trial(GODOT_TEST, "", tmp_path / "trial-1", mirrors, None, cli=cli)
    cfg = (trial.project / "artifactory.yaml").read_text()
    assert f"provider: dir:{mirrors.resolve()}" in cfg
    assert "ecosystem: godot-csharp" in cfg and "version" not in cfg
    assert (trial.bin / "artifactory").is_file()
    modules_md = (trial.project / "MODULES.md").read_text()
    assert f"artifactory install {GODOT_TEST.modules[0]}" in modules_md
    assert git("status", "--porcelain", cwd=trial.project) == ""
    assert "artifactory.yaml" in git("ls-files", cwd=trial.project)


def test_default_prepare_trial_has_no_cli(tmp_path):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    assert not (trial.bin / "artifactory").exists()
    assert not (trial.project / "artifactory.yaml").exists()


def test_round_json_records_product(tmp_path):
    assert json.loads(RoundResult("t", 1, product=True).to_json())["product"] is True
    assert json.loads(RoundResult("t", 1).to_json())["product"] is False


@pytest.mark.godot
def test_product_install_uses_mirror_without_network(cli, tmp_path):
    real = harness.RESULTS / "mirrors"
    if not all((real / f"{m}.git").is_dir() for m in GODOT_TEST.modules):
        pytest.skip("results/mirrors lacks the godot kits; run `artifactory mirror`")
    # Copies, tagged v0.1.0 (the catalog reads the latest semver tag; the shared mirrors may predate tags).
    mirrors = tmp_path / "mirrors"
    for m in GODOT_TEST.modules:
        shutil.copytree(real / f"{m}.git", mirrors / f"{m}.git")
        git("--git-dir", str(mirrors / f"{m}.git"), "tag", "-f", "v0.1.0", "main", cwd=tmp_path)
    trial = prepare_trial(GODOT_TEST, "", tmp_path / "trial-1", mirrors, None, cli=cli)
    cmd = harness.agent_command(trial, ["artifactory", "install", "CursorKit"])
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (trial.project / "addons" / "CursorKit").is_dir()


def test_failing_arc_gate_does_not_fail_a_trial():
    gate = CheckResult("arc_gate", False, "1 error(s)", gating=False)
    r = TrialResult("t", "trial-1", [CheckResult("build", True, ""), gate])
    assert r.passed
    assert json.loads(r.to_json())["checks"][1]["gating"] is False
    assert not TrialResult("t", "trial-1", [CheckResult("build", False, "")]).passed


def test_denial_counter_counts_recorded_transcript(tmp_path):
    t = tmp_path / "transcript.jsonl"
    reason = "addons/CursorKit/Cursor.cs is inside installed module CursorKit; do not edit it."
    t.write_text(json.dumps({"type": "tool_use", "state": {"error": reason}}) + "\n"
                 + json.dumps({"type": "text", "text": "ok"}) + "\n")
    assert harness.count_denials(t) == 1
    assert harness.count_denials(tmp_path / "missing.jsonl") == 0


def test_arc_hook_liveness_follows_session_state(tmp_path):
    assert harness.arc_hook_live(tmp_path) is False
    (tmp_path / ".arch" / "cache").mkdir(parents=True)
    assert harness.arc_hook_live(tmp_path) is False
    (tmp_path / ".arch" / "cache" / "hook-ses_1.json").write_text("{}")
    assert harness.arc_hook_live(tmp_path) is True


def test_trial_json_records_hook_liveness():
    r = TrialResult("t", "trial-1", arc_denials=0, arc_hook_live=False)
    data = json.loads(r.to_json())
    assert data["arc_hook_live"] is False and data["arc_denials"] == 0
    assert json.loads(TrialResult("t", "trial-1").to_json())["arc_hook_live"] is None


def test_round_json_records_arc():
    assert json.loads(RoundResult("t", 1, product=True, arc=True).to_json())["arc"] is True
    assert json.loads(RoundResult("t", 1).to_json())["arc"] is False


def test_arc_requires_product(tmp_path):
    with pytest.raises(ValueError, match="--product"):
        harness.run_round(ROOT / "tests" / "acceptance" / "godot-capsule-room", 1, arc=True,
                          results_root=tmp_path)
    with pytest.raises(ValueError, match="--product"):
        prepare_trial(GODOT_TEST, "", tmp_path / "t", None, None, arc=tmp_path / "arc")


@pytest.mark.godot
def test_arc_trial_installs_registry_plugin_and_registers_modules(cli, tmp_path):
    src = os.environ.get("ARC_SRC")
    real = harness.RESULTS / "mirrors"
    if not src or not Path(src).is_dir():
        pytest.skip("ARC_SRC is not set")
    if not all((real / f"{m}.git").is_dir() for m in GODOT_TEST.modules):
        pytest.skip("results/mirrors lacks the godot kits; run `artifactory mirror`")
    arc = harness.build_arc(tmp_path / "arcbuild", Path(src))
    mirrors = tmp_path / "mirrors"
    for m in GODOT_TEST.modules:
        shutil.copytree(real / f"{m}.git", mirrors / f"{m}.git")
        git("--git-dir", str(mirrors / f"{m}.git"), "tag", "-f", "v0.1.0", "main", cwd=tmp_path)
    trial = prepare_trial(GODOT_TEST, "", tmp_path / "trial-1", mirrors, None, cli=cli, arc=arc)
    project = trial.project
    assert "id: game" in (project / ".arch" / "registry.yaml").read_text()
    assert (project / ".opencode" / "plugins" / "arc.js").is_file()
    assert not (project / ".git" / "hooks" / "pre-commit").exists()
    assert trial.base_commit == git("rev-parse", "HEAD", cwd=project).strip()
    assert git("status", "--porcelain", cwd=project) == ""

    def sandboxed(*argv):
        return subprocess.run(harness.agent_command(trial, list(argv)), capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=300)
    r = sandboxed("artifactory", "install", "CursorKit")
    assert r.returncode == 0, r.stdout + r.stderr
    r = sandboxed("arc", "module", "list")
    assert "CursorKit" in r.stdout, r.stdout + r.stderr
    r = sandboxed("arc", "validate")
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.godot
def test_arc_gate_check_reports_findings_without_gating(cli, tmp_path):
    from artifactory.checks.godot import _check_arc_gate
    src = os.environ.get("ARC_SRC")
    real = harness.RESULTS / "mirrors"
    if not src or not Path(src).is_dir():
        pytest.skip("ARC_SRC is not set")
    if not all((real / f"{m}.git").is_dir() for m in GODOT_TEST.modules):
        pytest.skip("results/mirrors lacks the godot kits; run `artifactory mirror`")
    arc = harness.build_arc(tmp_path / "arcbuild", Path(src))
    mirrors = tmp_path / "mirrors"
    for m in GODOT_TEST.modules:
        shutil.copytree(real / f"{m}.git", mirrors / f"{m}.git")
        git("--git-dir", str(mirrors / f"{m}.git"), "tag", "-f", "v0.1.0", "main", cwd=tmp_path)
    trial = prepare_trial(GODOT_TEST, "", tmp_path / "trial-1", mirrors, None, cli=cli, arc=arc)
    old = os.environ["PATH"]
    os.environ["PATH"] = f"{trial.bin}:{old}"
    try:
        clean_copy = tmp_path / "clean-copy"  # the checker never snapshots into the trial itself
        shutil.copytree(trial.project, clean_copy, symlinks=True)
        clean = _check_arc_gate(clean_copy, trial.base_commit)
        # Uncommitted work: a file over the registry's file_lines limit (1000) is a size finding.
        (trial.project / "Big.cs").write_text("// x\n" * 1100)
        copy = tmp_path / "copy"  # the checker works on a disposable copy
        shutil.copytree(trial.project, copy, symlinks=True)
        after = _check_arc_gate(copy, trial.base_commit)
    finally:
        os.environ["PATH"] = old
    assert clean.name == "arc_gate" and clean.passed and not clean.gating, clean
    assert not after.gating and not after.passed and "Big.cs" in after.detail, after
    assert git("status", "--porcelain", cwd=trial.project) != ""  # the trial project itself is untouched


# --- bd in roadmap trials ---------------------------------------------------

LANTERN = load_acceptance(ROOT / "tests" / "acceptance" / "godot-lantern-keep")
SAMPLE_ROADMAP = Path(__file__).parent / "data" / "sample-roadmap.jsonl"
needs_bd = pytest.mark.skipif(not harness.BD_FALLBACK.is_file() and shutil.which("bd") is None,
                              reason="bd is not installed")


def test_bd_env_values(tmp_path):
    assert harness.bd_env("ornith", tmp_path) == {
        "DO_NOT_TRACK": "1", "BEADS_ACTOR": "ornith", "HOME": str(tmp_path)}


@needs_bd
def test_bd_binary_is_the_real_elf_not_the_node_wrapper():
    b = harness.bd_binary()
    assert b.is_file() and b.read_bytes()[:4] == b"\x7fELF"


def test_bd_binary_missing_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "BD_FALLBACK", tmp_path / "nope")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="bd"):
        harness.bd_binary()


@needs_bd
def test_bd_roadmap_trial_init_is_clean_and_import_keeps_ids_and_deps(tmp_path):
    test_dir = tmp_path / "t"
    (test_dir / "roadmaps").mkdir(parents=True)
    shutil.copy2(SAMPLE_ROADMAP, test_dir / "roadmaps" / "frontier.jsonl")
    shutil.copy2(LANTERN.dir / "arc-registry.yaml", test_dir / "arc-registry.yaml")
    test = dataclasses.replace(LANTERN, dir=test_dir)
    home_before = {p for p in Path.home().glob(".beads*")}
    trial = prepare_trial(test, "", tmp_path / "trial-1", None, None, roadmap="frontier")
    assert git("status", "--porcelain", cwd=trial.project) == ""
    assert trial.env["DO_NOT_TRACK"] == "1" and trial.env["BEADS_ACTOR"] == "ornith"
    assert trial.env["HOME"] == str(trial.home)
    assert (trial.bin / "bd").is_file()
    r = harness.bd_run(trial.project, trial.env, "export")
    rows = [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]
    ids = {x["id"] for x in rows}
    assert ids == {"bdw-aq5", "bdw-be8"}
    ui = next(x for x in rows if x["id"] == "bdw-be8")
    assert [d["depends_on_id"] for d in ui["dependencies"]] == ["bdw-aq5"]
    assert {p for p in Path.home().glob(".beads*")} == home_before


@needs_bd
def test_ornith_roadmap_trial_starts_with_no_beads(tmp_path):
    trial = prepare_trial(LANTERN, "", tmp_path / "trial-1", None, None, roadmap="ornith")
    assert git("status", "--porcelain", cwd=trial.project) == ""
    r = harness.bd_run(trial.project, trial.env, "list", "--json")
    assert json.loads(r.stdout) in ([], None)


@needs_bd
def test_host_side_bd_call_stays_inside_its_home(tmp_path):
    project, home = tmp_path / "p", tmp_path / "h"
    project.mkdir(), home.mkdir()
    git("init", "-q", "-b", "main", cwd=project)
    real = Path.home() / ".beads"
    before = real.stat().st_mtime if real.exists() else None
    r = harness.bd_run(project, harness.bd_env("test", home), "init", "--stealth", "--non-interactive")
    assert r.returncode == 0, r.stderr
    assert (real.stat().st_mtime if real.exists() else None) == before


def test_prepare_trial_none_roadmap_has_no_bd(tmp_path):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    assert not (trial.bin / "bd").exists() and "DO_NOT_TRACK" not in trial.env


def test_bd_run_refuses_env_without_home(tmp_path):
    with pytest.raises(ValueError, match="HOME"):
        harness.bd_run(tmp_path, {"DO_NOT_TRACK": "1", "BEADS_ACTOR": "test"}, "list")


def test_bd_binary_reads_only_the_magic(monkeypatch, tmp_path):
    fake = tmp_path / "pkg" / "bd"
    fake.parent.mkdir()
    fake.write_bytes(b"\x7fELF" + b"\0" * 64)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent))
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("bd_binary read the whole file"))
    assert harness.bd_binary() == fake.resolve()


# --- roadmap conditions and the bead loop -----------------------------------

# A fake agent: the prompt arrives as $1. Bead sessions append the bead id to order.txt and run
# the script under `on_bead` with $id set; stall sessions run `on_stall`; any other prompt `on_other`.
def bead_agent(on_bead="bd close $id >/dev/null", on_stall="", on_other="") -> list[str]:
    script = ('case "$1" in\n'
              '"Work bead "*) id=$(echo "$1" | cut -d" " -f3); id=${id%.}; echo "$id" >> order.txt\n'
              f'{on_bead}\n;;\n'
              f'"Some beads are unfinished."*)\necho stall >> order.txt\n{on_stall}\n;;\n'
              f'*)\n{on_other}\n;;\nesac\n')
    return ["/bin/sh", "-c", script, "sh"]


@pytest.fixture(scope="module")
def bd_template(tmp_path_factory):
    """One ornith trial with bd initialised (bd init takes ~15 s); tests run on copies of it."""
    if not harness.BD_FALLBACK.is_file() and shutil.which("bd") is None:
        pytest.skip("bd is not installed")
    return prepare_trial(LANTERN, "", tmp_path_factory.mktemp("bdtpl") / "trial-1", None, None, roadmap="ornith")


def clone_trial(t: harness.Trial, dest: Path) -> harness.Trial:
    shutil.copytree(t.dir, dest, symlinks=True)
    old, new = str(t.dir), str(dest)
    move = lambda p: Path(str(p).replace(old, new))  # noqa: E731
    return harness.Trial(dest, move(t.project), move(t.home), move(t.bin), None, None,
                         {k: v.replace(old, new) for k, v in t.env.items()}, [move(p) for p in t.ro_binds])


def bd(trial, *args) -> str:
    r = harness.bd_run(trial.project, trial.env, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def new_bead(trial, title, after=None, priority=2) -> str:
    bid = bd(trial, "q", title, "-p", str(priority))
    if after:
        bd(trial, "dep", "add", bid, after)
    return bid


def states(trial) -> dict:
    return {x["id"]: x["status"] for x in json.loads(bd(trial, "list", "--all", "--limit", "0", "--json"))}


def order(trial) -> list[str]:
    f = trial.project / "order.txt"
    return f.read_text().split() if f.exists() else []


def run(trial, agent, limit, roadmap="frontier", test=LANTERN):
    test = dataclasses.replace(test, time_limit_s=limit)
    start = time.monotonic()
    r = harness.run_agent(trial, test, agent, roadmap)
    timed_out, outcome = r.timed_out, r.outcome
    return timed_out, outcome, time.monotonic() - start


@pytest.fixture
def bead_trial(bd_template, tmp_path):
    return clone_trial(bd_template, tmp_path / "trial-1")


def test_bead_loop_follows_dependencies_and_stops_when_all_closed(bead_trial):
    t = bead_trial
    c = new_bead(t, "third")
    a = new_bead(t, "first")
    b = new_bead(t, "second", after=a)
    bd(t, "dep", "add", c, b)
    timed_out, out, _ = run(t, bead_agent(), 120)
    assert order(t) == [a, b, c]
    assert not timed_out
    assert set(states(t).values()) == {"closed"}
    assert (out.beads, out.closed, out.blocked, out.sessions, out.stall_sessions) == (3, 3, 0, 3, 0)
    assert not out.loop_stalled and not out.roadmap_failed
    assert sorted(p.name for p in t.dir.glob("transcript*")) == [f"transcript-{n}.jsonl" for n in (1, 2, 3)]
    final = [json.loads(line) for line in (t.dir / "beads-final.jsonl").read_text().splitlines()]
    assert {x["status"] for x in final} == {"closed"}


def test_unclosed_bead_is_retried_once_then_blocked_with_a_note(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "QUICK_SESSION_S", 0)  # these quick sessions are not a dead server
    t = bead_trial
    a = new_bead(t, "stubborn", priority=1)
    b = new_bead(t, "easy", priority=2)
    # The stubborn bead is claimed and left in progress; it must be reset and retried, then blocked.
    agent = bead_agent(on_bead=f'if [ "$id" = {a} ]; then bd update $id --claim >/dev/null; else bd close $id >/dev/null; fi',
                       on_stall=f"bd show {a} --json > stall-saw.json; bd close {a} >/dev/null")
    timed_out, out, _ = run(t, agent, 120)
    assert order(t) == [a, a, b, "stall"]
    saw = json.loads((t.project / "stall-saw.json").read_text())[0]
    assert saw["status"] == "blocked" and "not closed" in saw["notes"]
    assert (out.sessions, out.stall_sessions, out.closed) == (4, 1, 2) and not timed_out


def test_only_blocked_beads_left_runs_stall_sessions_until_time_is_up(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "QUICK_SESSION_S", 0.5)
    t = bead_trial
    a = new_bead(t, "stuck")
    bd(t, "update", a, "--status", "blocked")
    timed_out, out, elapsed = run(t, bead_agent(on_stall="sleep 1"), 10)
    assert out.stall_sessions >= 2 and out.sessions == out.stall_sessions
    assert not out.loop_stalled
    assert set(order(t)) == {"stall"}
    assert elapsed >= 10 - 1  # the loop used the time, it did not stop early


def test_stall_session_closing_a_blocker_returns_to_the_ready_loop(bead_trial):
    t = bead_trial
    a = new_bead(t, "blocker")
    b = new_bead(t, "after", after=a)
    bd(t, "update", a, "--status", "blocked")
    timed_out, out, _ = run(t, bead_agent(on_stall=f"bd close {a} >/dev/null"), 120)
    assert order(t) == ["stall", b]
    assert set(states(t).values()) == {"closed"} and not timed_out
    assert (out.sessions, out.stall_sessions, out.closed) == (2, 1, 2)


def test_bead_loop_never_exceeds_the_time_limit_and_reports_timeout(bead_trial):
    t = bead_trial
    new_bead(t, "slow")
    timed_out, out, elapsed = run(t, bead_agent(on_bead="sleep 600"), 4)
    assert timed_out and out.sessions == 1
    assert elapsed < 4 + 8  # the session limit is the time left; only bd bookkeeping follows it
    assert out.blocked == 0  # a bead killed at the deadline is not counted as a failure


def test_no_timeout_when_the_last_session_finished_in_time(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "QUICK_SESSION_S", 0)
    t = bead_trial
    new_bead(t, "done")
    timed_out, out, _ = run(t, bead_agent(), 60)
    assert not timed_out and out.closed == 1


def test_instant_exit_agent_sets_loop_stalled(bead_trial):
    t = bead_trial
    for k in range(3):
        new_bead(t, f"b{k}")
    timed_out, out, elapsed = run(t, bead_agent(on_bead=":"), 300)
    assert out.loop_stalled and not timed_out
    assert out.sessions == 3 and elapsed < 120


def test_ornith_writing_phase_writes_beads_then_builds(bead_trial):
    t = bead_trial
    writer = 'grep -q "Lantern" BRIEF.md && a=$(bd q first) && b=$(bd q second) && bd dep add $b $a >/dev/null'
    timed_out, out, _ = run(t, bead_agent(on_other=writer), 120, roadmap="ornith")
    assert not timed_out and not out.roadmap_failed
    assert (out.beads, out.closed, out.sessions) == (2, 2, 2)
    assert len((t.dir / "roadmap.jsonl").read_text().splitlines()) == 2
    assert (t.dir / "transcript-1.jsonl").exists() and (t.dir / "transcript-3.jsonl").exists()
    assert not (t.project / "BRIEF.md").exists()  # bead sessions never see the brief
    assert git("status", "--porcelain", cwd=t.project).strip() in ("", "?? order.txt")


def test_ornith_with_no_beads_falls_back_to_one_brief_session(bead_trial):
    t = bead_trial
    agent = bead_agent(on_other='case "$1" in *"Lantern"*) echo brief >> order.txt;; *) echo writer >> order.txt;; esac')
    timed_out, out, _ = run(t, agent, 120, roadmap="ornith")
    assert out.roadmap_failed and out.beads == 0 and out.sessions == 1
    assert order(t) == ["writer", "brief"]
    assert (t.dir / "roadmap.jsonl").read_text() == ""


def test_writing_phase_is_capped(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "WRITING_LIMIT_S", 2)
    t = bead_trial
    timed_out, out, elapsed = run(t, bead_agent(on_other='case "$1" in *"Lantern"*) ;; *) sleep 600;; esac'), 60,
                                  roadmap="ornith")
    assert out.roadmap_failed and not timed_out  # the writer was cut at its cap, not at the deadline
    assert elapsed < 30


def test_none_mode_runs_one_session_into_transcript_jsonl(tmp_path):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    r = harness.run_agent(trial, GO_TEST, fake_agent("echo '{}'; touch ran"), "none")
    timed_out, outcome = r.timed_out, r.outcome
    assert not timed_out and outcome is None
    assert (trial.project / "ran").exists()
    assert [p.name for p in trial.dir.glob("transcript*")] == ["transcript.jsonl"]
    assert (trial.dir / "opencode.log").exists()


def test_bead_session_is_resumed_after_a_dropped_connection(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "RESUME_PAUSE_S", 0)
    t = bead_trial
    a = new_bead(t, "first")
    # The bead session drops; its resume (same session, RESUME_PROMPT) closes the bead.
    on_bead = (f"echo $id > current; echo '{{\"type\":\"step_start\",\"sessionID\":\"ses_1\"}}'; "
               f"echo '{DROP_EVENT}'")
    on_other = 'if [ "$1" = --session ]; then bd close "$(cat current)" >/dev/null; fi'
    agent = bead_agent(on_bead=on_bead, on_other=on_other)
    r = harness.run_agent(t, dataclasses.replace(LANTERN, time_limit_s=120), agent, "frontier")
    assert r.resumes == 1 and r.dropped is None and not r.timed_out
    assert r.outcome.sessions == 1 and r.outcome.closed == 1
    assert states(t) == {a: "closed"}
    assert "ECONNRESET" in (t.dir / "transcript-1.jsonl").read_text()


def test_a_bead_session_that_stays_dropped_ends_the_loop(bead_trial, monkeypatch):
    monkeypatch.setattr(harness, "RESUME_PAUSE_S", 0)
    t = bead_trial
    new_bead(t, "first")
    new_bead(t, "second")
    agent = bead_agent(on_bead=f"echo '{DROP_EVENT}'", on_other=f"echo '{DROP_EVENT}'")
    r = harness.run_agent(t, dataclasses.replace(LANTERN, time_limit_s=300), agent, "frontier")
    assert r.resumes == harness.MAX_RESUMES and r.dropped.resumes == harness.MAX_RESUMES
    assert r.outcome.sessions == 1


def test_trial_json_records_roadmap_only_when_set():
    assert "roadmap" not in json.loads(TrialResult("t", "trial-1").to_json())
    r = TrialResult("t", "trial-1", roadmap={"beads": 2, "loop_stalled": False})
    assert json.loads(r.to_json())["roadmap"] == {"beads": 2, "loop_stalled": False}


def test_arc_denials_sum_over_all_transcripts(tmp_path):
    for n in (1, 2):
        (tmp_path / f"transcript-{n}.jsonl").write_text(f"x {harness.DENIAL_MARK}\n")
    assert harness.trial_denials(tmp_path) == 2


def test_round_roadmap_needs_product_and_arc(tmp_path):
    lantern = ROOT / "tests" / "acceptance" / "godot-lantern-keep"
    for kw in ({}, {"product": True}):
        with pytest.raises(ValueError, match="--product and --arc"):
            harness.run_round(lantern, 1, roadmap="ornith", results_root=tmp_path, **kw)
    with pytest.raises(ValueError, match="roadmap"):
        harness.run_round(lantern, 1, roadmap="bogus", results_root=tmp_path)


def test_round_dir_and_json_carry_roadmap(tmp_path):
    assert harness.round_dir(tmp_path, "t", 3, False, "none") == tmp_path / "t" / "round-3"
    assert harness.round_dir(tmp_path, "t", 3, False, "ornith") == tmp_path / "t" / "round-3-ornith"
    assert json.loads(RoundResult("t", 1, roadmap="frontier").to_json())["roadmap"] == "frontier"
    assert json.loads(RoundResult("t", 1).to_json())["roadmap"] == "none"


def test_round_time_limit_overrides_test_yaml_and_is_recorded(tmp_path, monkeypatch):
    seen = []
    def fake_trial(test, *a, **k):
        seen.append(test.time_limit_s)
        return TrialResult(test.name, "trial", reason="timeout")
    monkeypatch.setattr(harness, "run_trial", fake_trial)
    monkeypatch.setattr(harness, "build_cli", lambda root: root / "artifactory")
    monkeypatch.setattr(harness, "render_index", lambda *a: "# index")
    for m in GODOT_TEST.modules:
        (tmp_path / "mirrors" / f"{m}.git").mkdir(parents=True)
    result = harness.run_round(ROOT / "tests" / "acceptance" / "godot-capsule-room", 1, trials=2, results_root=tmp_path, time_limit_s=43200)
    assert seen == [43200, 43200]
    assert json.loads(result.to_json())["time_limit_s"] == 43200
    with pytest.raises(ValueError, match="positive"):
        harness.run_round(ROOT / "tests" / "acceptance" / "godot-capsule-room", 2, trials=1, results_root=tmp_path, time_limit_s=0)


def _bare_mirror(path, branch="main"):
    work = path.parent / (path.name + "-work")
    subprocess.run(["git", "init", "-q", "-b", branch, str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(path)], check=True)
    return subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def test_round_records_standard_commit_and_kit_commits(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "run_trial", lambda test, *a, **k: TrialResult(test.name, "trial", reason="timeout"))
    monkeypatch.setattr(harness, "build_cli", lambda root: root / "artifactory")
    monkeypatch.setattr(harness, "render_index", lambda *a: "# index")
    shas = {m: _bare_mirror(tmp_path / "mirrors" / f"{m}.git") for m in GODOT_TEST.modules}
    result = harness.run_round(ROOT / "tests" / "acceptance" / "godot-capsule-room", 1, trials=1, results_root=tmp_path)
    data = json.loads((tmp_path / GODOT_TEST.name / "round-1" / "round.json").read_text())
    assert data["kits"] == shas == result.kits
    head = subprocess.run(["git", "-C", str(harness.REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert data["standard_commit"] in (head, head + "-dirty")


def test_standard_commit_is_none_when_git_fails(monkeypatch):
    monkeypatch.setattr(harness, "REPO", Path("/nonexistent-dir-for-test"))
    assert harness.standard_commit() is None


def test_cli_round_value_error_is_a_clean_exit_1(capsys):
    from artifactory.cli import main
    code = main(["round", str(ROOT / "tests" / "acceptance" / "godot-capsule-room"), "--time-limit-s", "0"])
    assert code == 1
    assert "artifactory round: --time-limit-s must be positive" in capsys.readouterr().err


def test_cli_round_roadmap_choices():
    from artifactory.cli import main
    with pytest.raises(SystemExit):
        main(["round", "x", "--roadmap", "bogus"])


def test_bd_run_timeout_is_a_clear_runtime_error(tmp_path, monkeypatch):
    fake = tmp_path / "bd"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr(harness, "bd_binary", lambda: fake)
    monkeypatch.setattr(harness, "BD_TIMEOUT_S", 1)
    with pytest.raises(RuntimeError, match="timed out after 1 s"):
        harness.bd_run(tmp_path, harness.bd_env("test", tmp_path), "export")


@pytest.mark.parametrize("exc", [ValueError("bad json"), OSError("disk gone")])
def test_bead_loop_failures_beyond_runtime_error_are_recorded_as_bd_error(tmp_path, monkeypatch, exc):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(harness, "bead_loop", boom)
    monkeypatch.setattr(harness, "_export", lambda trial, dest: [])
    test = dataclasses.replace(LANTERN, time_limit_s=30)
    out = harness.run_agent(trial, test, fake_agent("true"), "frontier").outcome
    assert out.bd_error == str(exc) and out.beads == 0


def test_final_export_is_attempted_after_a_bd_error(tmp_path, monkeypatch):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    def boom(*a, **k):
        raise RuntimeError("bd broke")
    monkeypatch.setattr(harness, "bead_loop", boom)
    monkeypatch.setattr(harness, "_export", lambda trial, dest: [{"status": "closed"}, {"status": "open"}])
    test = dataclasses.replace(LANTERN, time_limit_s=30)
    out = harness.run_agent(trial, test, fake_agent("true"), "frontier").outcome
    assert out.bd_error == "bd broke" and out.export_error is None
    assert (out.beads, out.closed) == (2, 1)


def test_failed_final_export_does_not_mask_the_bd_error(tmp_path, monkeypatch):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    def boom(*a, **k):
        raise RuntimeError("bd broke")
    def no_export(trial, dest):
        raise RuntimeError("export broke")
    monkeypatch.setattr(harness, "bead_loop", boom)
    monkeypatch.setattr(harness, "_export", no_export)
    test = dataclasses.replace(LANTERN, time_limit_s=30)
    out = harness.run_agent(trial, test, fake_agent("true"), "frontier").outcome
    assert out.bd_error == "bd broke" and out.export_error == "export broke" and out.beads == 0


def test_export_failure_after_the_writing_phase_falls_back_to_the_brief(tmp_path, monkeypatch):
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    calls = []
    def flaky(trial, dest):
        calls.append(dest.name)
        if len(calls) == 1:
            raise RuntimeError("bd export failed")
        return []
    monkeypatch.setattr(harness, "_export", flaky)
    test = dataclasses.replace(LANTERN, time_limit_s=60)
    out = harness.run_agent(trial, test, fake_agent("true"), "ornith").outcome
    assert out.roadmap_failed and out.sessions == 1 and out.bd_error is None
    assert calls == ["roadmap.jsonl", "beads-final.jsonl"]


# --- frontier writer workspace ----------------------------------------------

@pytest.fixture(scope="module")
def _workspace(tmp_path_factory, cli):
    if not harness.BD_FALLBACK.is_file() and shutil.which("bd") is None:
        pytest.skip("bd is not installed")
    arc_src = Path(os.environ.get("ARC_SRC") or harness.DEFAULT_ARC_SRC)
    if not arc_src.is_dir():
        pytest.skip("arc source not found (set ARC_SRC)")
    tmp = tmp_path_factory.mktemp("ws")
    mirrors = _product_mirrors(tmp, LANTERN.modules)
    arc = harness.build_arc(tmp / "arcbuild", arc_src)
    return harness.prepare_roadmap_workspace(LANTERN, tmp / "ws", mirrors, cli, arc)


@pytest.fixture
def workspace(_workspace):
    """The shared workspace (building one costs ~8 s) with every bead deleted, so tests are order-independent."""
    trial, prefix = _workspace
    rows = json.loads(sh(prefix, "bd list --all --json", trial.project).stdout or "[]") or []
    for row in rows:
        r = sh(prefix, f"bd delete {row['id']} --force", trial.project)
        assert r.returncode == 0, r.stderr
    assert json.loads(sh(prefix, "bd list --all --json", trial.project).stdout or "[]") in ([], None)
    return trial, prefix


def sh(prefix, cmd, cwd):
    return subprocess.run(f"{prefix} {cmd}", shell=True, cwd=cwd, capture_output=True, text=True)


def test_workspace_has_bin_brief_and_prompt_and_no_beads(workspace):
    trial, prefix = workspace
    for name in ("artifactory", "arc", "bd"):
        assert (trial.bin / name).is_file()
    assert (trial.project / "BRIEF.md").read_text() == LANTERN.prompt
    assert (trial.project / "ROADMAP-PROMPT.md").read_text() == LANTERN.roadmap_prompt
    assert git("status", "--porcelain", cwd=trial.project) == ""
    assert "BEADS_ACTOR=roadmap-writer" in prefix and "DO_NOT_TRACK=1" in prefix
    r = sh(prefix, "bd list --json", trial.project)
    assert json.loads(r.stdout) in ([], None)


def test_workspace_search_works_from_the_project_dir(workspace):
    trial, prefix = workspace
    r = sh(prefix, "artifactory search stand-in", trial.project)
    assert r.returncode == 0, r.stderr


def test_workspace_beads_export_as_roadmap_writer(workspace, tmp_path):
    trial, prefix = workspace
    r = sh(prefix, "bd create 'first bead' -p 2", trial.project)
    assert r.returncode == 0, r.stderr
    out = tmp_path / "frontier.jsonl"
    assert harness.export_roadmap(trial.project, out) == 1
    assert [json.loads(line)["created_by"] for line in out.read_text().splitlines()] == ["roadmap-writer"]


def test_export_takes_a_destination_relative_to_the_caller(workspace, tmp_path, monkeypatch):
    trial, _ = workspace
    monkeypatch.chdir(tmp_path)
    (tmp_path / "out").mkdir()
    harness.export_roadmap(trial.project, Path("out/frontier.jsonl"))
    assert (tmp_path / "out" / "frontier.jsonl").exists()


def test_export_refuses_an_in_progress_bead(workspace, tmp_path):
    trial, prefix = workspace
    bid = json.loads(sh(prefix, "bd create 'claimed bead' -p 2 --json", trial.project).stdout)["id"]
    assert sh(prefix, f"bd update {bid} --status in_progress", trial.project).returncode == 0
    out = tmp_path / "frontier.jsonl"
    with pytest.raises(RuntimeError, match=f"{bid}: in_progress"):
        harness.export_roadmap(trial.project, out)
    assert not out.exists()


def test_export_refuses_a_foreign_assignee(workspace, tmp_path):
    trial, prefix = workspace
    bid = json.loads(sh(prefix, "bd create 'taken bead' -p 2 --json", trial.project).stdout)["id"]
    assert sh(prefix, f"bd update {bid} --assignee someone-else", trial.project).returncode == 0
    with pytest.raises(RuntimeError, match=f"{bid}: assignee 'someone-else'"):
        harness.export_roadmap(trial.project, tmp_path / "frontier.jsonl")


def test_export_refuses_a_bead_created_by_another_actor(workspace, tmp_path):
    trial, prefix = workspace
    other = prefix.replace("BEADS_ACTOR=roadmap-writer", "BEADS_ACTOR=intruder")
    bid = json.loads(sh(other, "bd create 'foreign bead' -p 2 --json", trial.project).stdout)["id"]
    with pytest.raises(RuntimeError, match=f"{bid}: created_by 'intruder'"):
        harness.export_roadmap(trial.project, tmp_path / "frontier.jsonl")


def test_a_refused_export_keeps_the_existing_roadmap(workspace, tmp_path):
    trial, prefix = workspace
    bid = json.loads(sh(prefix, "bd create 'claimed bead' -p 2 --json", trial.project).stdout)["id"]
    sh(prefix, f"bd update {bid} --status in_progress", trial.project)
    out = tmp_path / "frontier.jsonl"
    out.write_text("old roadmap\n")
    with pytest.raises(RuntimeError):
        harness.export_roadmap(trial.project, out)
    assert out.read_text() == "old roadmap\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("frontier")] == ["frontier.jsonl"]


# --- local Python package source ------------------------------------------

PYPI_IP = "151.101.0.223"  # a pypi.org address (Fastly); the sandbox has no DNS, so the probe needs an IP


def py_package(root: Path, name: str, version: str, deps: list[str] = (), marker: str | None = None) -> Path:
    """A tiny hatchling project; importing it prints `marker`."""
    mod = name.replace("-", "_")
    (root / mod).mkdir(parents=True)
    (root / mod / "__init__.py").write_text(f"print({marker!r})\n" if marker else "")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\nrequires-python = ">=3.10"\n'
        f'dependencies = {json.dumps(list(deps))}\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n')
    return root


@pytest.fixture(scope="module")
def pyindex_wheels(tmp_path_factory):
    """An index with a hatchling kit, its pinned dependency (a prebuilt wheel) and the standard wheels.

    Building and downloading need the host's uv/pip caches or PyPI; without them the tests skip."""
    tmp = tmp_path_factory.mktemp("pyindex")
    try:
        dep = build_pyindex([py_package(tmp / "dep", "pinned-dep", "1.0", marker="DEP-ALIVE")], tmp / "wheelhouse")
        kit = py_package(tmp / "kit", "stub-kit", "0.1.0", deps=["pinned-dep==1.0"], marker="STUBKIT-ALIVE")
        index = tmp / "index"
        built = build_pyindex([kit], index, wheels=dep)
        backends = download_wheels(standard_wheels(), index)
    except RuntimeError as e:
        pytest.skip(f"host cannot build or download the stub wheels (cold cache or offline?): {e}")
    return index, built, backends


def test_pyindex_kits_and_backends_install_in_the_sandbox_with_network_off(tmp_path, pyindex_wheels):
    """pip and uv in a networkless sandbox install a kit and its pinned dependency from the index, and build
    model-written hatchling and uv_build projects offline from the backends in it, and install pytest."""
    index, built, backends = pyindex_wheels
    assert sorted(w.name for w in built) == ["pinned_dep-1.0-py3-none-any.whl", "stub_kit-0.1.0-py3-none-any.whl"]
    names = {w.name.split("-")[0] for w in backends}
    assert {"pytest", "iniconfig", "hatchling", "uv_build", "packaging", "pluggy"} <= names, names

    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None, pyindex=index)
    assert trial.env["PIP_FIND_LINKS"] == trial.env["UV_FIND_LINKS"] == str(index.resolve())
    assert trial.env["PIP_NO_INDEX"] == trial.env["UV_OFFLINE"] == "1"
    assert index.resolve() in trial.ro_binds
    py_package(trial.project / "happ", "hatch-app", "0.1.0", deps=["stub-kit"], marker="HATCHAPP-ALIVE")
    imports = "-c 'import pinned_dep, stub_kit'"
    script = (
        "set -e\n"
        f"python3 -m venv pipenv && pipenv/bin/pip install -q stub-kit\n"
        f"pipenv/bin/python {imports} > pip.out\n"
        "uv venv -q uvenv && VIRTUAL_ENV=uvenv uv pip install -q stub-kit\n"
        f"uvenv/bin/python {imports} > uvpip.out\n"
        # hatchling backend, build-isolated: pip and uv each fetch hatchling and its deps from the index
        "python3 -m venv hpip && hpip/bin/pip install -q ./happ\n"
        "hpip/bin/python -c 'import hatch_app' > hatch-pip.out\n"
        "uv venv -q huv && VIRTUAL_ENV=huv uv pip install -q --no-cache ./happ\n"
        "huv/bin/python -c 'import hatch_app' > hatch-uv.out\n"
        # uv_build backend: `uv init` / `uv add`, then pip builds the same project through the uv_build wheel
        "uv init -q --no-workspace --vcs none app && (cd app && uv add -q stub-kit "
        f"&& uv run -q python {imports} > ../uvadd.out)\n"
        "python3 -m venv apip && apip/bin/pip install -q ./app && apip/bin/python -c 'import app'\n"
        # pytest, as trials use it: pip into a venv, and `uv pip install` then `.venv/bin/python -m pytest`
        "pipenv/bin/pip install -q pytest && pipenv/bin/python -m pytest --version > pytest-pip.out\n"
        "uv venv -q .venv && uv pip install -q pytest && .venv/bin/python -m pytest --version > pytest-uv.out\n"
    )
    # No allow list: the sandbox has no network at all.
    cmd = sandbox_command(trial.project, trial.home, trial.ro_binds, ["/bin/sh", "-c", script], trial.env)
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    for out in ("pip.out", "uvpip.out", "uvadd.out"):
        assert (trial.project / out).read_text().split() == ["DEP-ALIVE", "STUBKIT-ALIVE"], out
    for out in ("hatch-pip.out", "hatch-uv.out"):
        assert (trial.project / out).read_text().split() == ["HATCHAPP-ALIVE"], out
    for out in ("pytest-pip.out", "pytest-uv.out"):
        assert (trial.project / out).read_text().startswith("pytest "), out


def test_pyindex_control_sandbox_reaches_no_pypi(tmp_path):
    """With no index set, the sandbox cannot reach PyPI: connects fail fast and pip reports a connection failure."""
    trial = prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None)
    assert "PIP_FIND_LINKS" not in trial.env and not (trial.bin / "uv").exists()
    cmd = sandbox_command(trial.project, trial.home, trial.ro_binds,
                          ["/usr/bin/python3", "-c", EGRESS_PROBE, PYPI_IP, "443"], trial.env)
    result, elapsed = _sandbox_run(cmd).stdout.split()
    assert result in FAST_REFUSAL and float(elapsed) < 2, (result, elapsed)
    script = "python3 -m venv v && v/bin/pip install --retries 1 --timeout 5 requests"
    cmd = sandbox_command(trial.project, trial.home, trial.ro_binds, ["/bin/sh", "-c", script], trial.env)
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    assert r.returncode != 0
    assert "No matching distribution" in r.stderr
    assert "NewConnectionError" in r.stderr or "Failed to establish a new connection" in r.stderr, r.stderr


def test_pyindex_missing_directory_fails_trial_setup(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None, pyindex=tmp_path / "nope")


def test_pyindex_uv_that_does_not_run_fails_trial_setup(tmp_path, monkeypatch):
    fake = tmp_path / "uv"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setattr(harness, "uv_binary", lambda: fake)
    (tmp_path / "idx").mkdir()
    with pytest.raises(RuntimeError, match="does not run"):
        prepare_trial(GO_TEST, "# index", tmp_path / "trial-1", None, None, pyindex=tmp_path / "idx")


def test_pyindex_export_kits_checks_out_the_branch_for_building(tmp_path):
    src = py_package(tmp_path / "src", "mirror-kit", "0.2.0")
    git("init", "-q", "-b", "main", cwd=src)
    git("add", "-A", cwd=src)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=src)
    git("clone", "-q", "--mirror", str(src), str(tmp_path / "mirrors" / "MirrorKit.git"), cwd=tmp_path)
    dirs = export_kits(tmp_path / "mirrors", ["MirrorKit"], "main", tmp_path / "out")
    assert dirs == [tmp_path / "out" / "MirrorKit"] and not (dirs[0] / ".git").exists()
    try:
        wheels = build_pyindex(dirs, tmp_path / "idx")
    except RuntimeError as e:
        pytest.skip(f"host cannot build the hatchling stub (cold cache or offline?): {e}")
    assert [w.name for w in wheels] == ["mirror_kit-0.2.0-py3-none-any.whl"]
    with pytest.raises(RuntimeError, match=r"cannot export kit MirrorKit \(nope\).*nope"):
        export_kits(tmp_path / "mirrors", ["MirrorKit"], "nope", tmp_path / "out2")


def test_pyindex_rejects_a_conflicting_wheel(tmp_path):
    try:
        a = build_pyindex([py_package(tmp_path / "a", "same", "1.0", marker="A")], tmp_path / "wa")
    except RuntimeError as e:
        pytest.skip(f"host cannot build the hatchling stub (cold cache or offline?): {e}")
    with pytest.raises(ValueError, match="two different wheels"):
        build_pyindex([py_package(tmp_path / "b", "same", "1.0", marker="B")], tmp_path / "idx", wheels=a)


def test_pyindex_round_uses_a_per_test_directory_and_test_wheels(tmp_path, monkeypatch):
    """run_round builds <root>/pyindex/<test> from the kit mirrors, the backends and test.yaml python_wheels."""
    test_dir = tmp_path / "py-test"
    (test_dir / "fixture").mkdir(parents=True)
    (test_dir / "prompt.md").write_text("p")
    (test_dir / "duplication.yaml").write_text("{}\n")
    (test_dir / "test.yaml").write_text("ecosystem: python\nfixture: fixture\nmodules: [PyKit]\ntime_limit_s: 10\n"
                                        "python_wheels: ['requests==2.32.3']\n")
    assert load_acceptance(test_dir).python_wheels == ("requests==2.32.3",)
    (tmp_path / "res" / "mirrors" / "PyKit.git").mkdir(parents=True)
    calls = {}
    monkeypatch.setattr(harness, "build_cli", lambda root: tmp_path / "cli")
    monkeypatch.setattr(harness, "render_index", lambda *a: "# index")
    monkeypatch.setattr(harness, "export_kits", lambda mirrors, modules, branch, dest: [dest / m for m in modules])
    def fake_download(specs, out):
        calls.update(specs=specs, dl_out=out)
        for name in ("pytest-9.2.0-py3-none-any.whl", "hatchling-1.33.0-py3-none-any.whl"):
            (out / name).write_bytes(b"")
    monkeypatch.setattr(harness, "download_wheels", fake_download)
    monkeypatch.setattr(harness, "run_trial", lambda *a, **k: calls.update(pyindex=k["pyindex"]) or TrialResult(
        test="py-test", trial="trial-1", checks=[], reason=None))
    monkeypatch.setattr(harness, "build_pyindex", lambda dirs, out: (calls.update(kits=[d.name for d in dirs], out=out),
                                                                     out.mkdir(parents=True)))
    result = harness.run_round(test_dir, 1, trials=1, results_root=tmp_path / "res")
    want = (tmp_path / "res" / "pyindex" / "py-test").resolve()
    assert calls["out"] == calls["dl_out"] == calls["pyindex"] == want
    assert calls["kits"] == ["PyKit"]
    assert calls["specs"][-1] == "requests==2.32.3" and any(s.startswith("uv_build") for s in calls["specs"])
    assert "pytest==9.2.0" in calls["specs"] and "hatchling==1.33.0" in calls["specs"]
    wheels = ["hatchling-1.33.0-py3-none-any.whl", "pytest-9.2.0-py3-none-any.whl"]
    assert result.pyindex_wheels == wheels
    recorded = json.loads(next((tmp_path / "res").rglob("round.json")).read_text())
    assert recorded["pyindex_wheels"] == wheels
