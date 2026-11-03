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


def _product_mirrors(tmp_path):
    """Local bare mirror stand-ins for the godot test's kits (no network)."""
    mirrors = tmp_path / "mirrors"
    for name in GODOT_TEST.modules:
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
