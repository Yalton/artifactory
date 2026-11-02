import dataclasses
import json
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
from artifactory.harness import RoundResult, prepare_trial, run_trial
from artifactory.result import CheckResult, TrialResult

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


def test_every_kit_url_form_resolves_to_mirrors(tmp_path):
    cfg = tmp_path / "gitconfig"
    cfg.write_text(harness._gitconfig(tmp_path / "mirrors"))
    for form in harness.KIT_REMOTE_FORMS:
        out = subprocess.run(["git", "ls-remote", "--get-url", f"{form}PoolKit.git"],
                             env={"GIT_CONFIG_GLOBAL": str(cfg), "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, cwd=tmp_path).stdout.strip()
        assert out == f"file://{tmp_path / 'mirrors'}/PoolKit.git"
