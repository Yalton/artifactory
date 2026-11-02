"""Run acceptance-test trials: a local model in a bwrap sandbox, then the checker in another.

Layout of one trial directory:

    trial-K/
      project/          the model's working tree (writable by the model)
      home/             the model's HOME (writable by the model)
      bin/godot         launcher for the real Godot binary (read-only in the sandbox)
      transcript.jsonl  opencode JSON events (stdout)
      opencode.log      opencode stderr
      checker-home/     HOME for the checker run (the only writable path then)
      checker.log       checker output
      checker.json      the final TrialResult, including the harness reason

The checker runs model-written code (game autoloads, the Go service, go test),
so it is sandboxed too: the repository, the trial project and the trial HOME
are read-only there and only checker-home and a private /tmp are writable.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .acceptance import AcceptanceTest, load_acceptance
from .checks.go import go_env
from .descriptor import DescriptorError, load_descriptor
from .goproxy import build_goproxy
from .index import build_index, index_preamble
from .result import CheckResult, TrialResult
from .sandbox import sandbox_command

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results"
GO_SAMPLES = REPO / "samples" / "go"
GODOT_TEST = REPO / "tests" / "acceptance" / "godot-capsule-room"
BASELINE_README = Path("/data/fast/Projects/Tech/Games/Godot/Modules/README.md")

MODEL = "agentbox/ornith-1.5-q4"
LLAMA_URL = "http://192.168.50.174:8080/v1"
OPENCODE = Path(os.environ.get("ARTIFACTORY_OPENCODE", Path.home() / ".opencode" / "bin" / "opencode"))
GODOT_BINARY = Path(os.environ.get(
    "ARTIFACTORY_GODOT", "/opt/fastapps/godot/application-4.7/Godot_v4.7-stable_mono_linux.x86_64"))
NUGET_PACKAGES = Path.home() / ".nuget" / "packages"
KIT_REMOTE = "git@repo.billbert.co:artifactory/"
# Every spelling of the kit host a model might try, all served from the local mirrors.
# The yalt forms are the kits' old home; they stay mapped for older indexes and transcripts.
KIT_REMOTE_FORMS = [KIT_REMOTE, "ssh://git@repo.billbert.co/artifactory/", "https://repo.billbert.co/artifactory/",
                    "git@repo.billbert.co:yalt/", "ssh://git@repo.billbert.co/yalt/", "https://repo.billbert.co/yalt/"]
STITCH_BRANCH = "main"
# The baseline round read kit main before the stitchability merge. That state is tagged
# pre-stitchability in the 8 converted kits; a baseline rerun now reads the merged kits.
BASELINE_BRANCH = "main"
TRIAL_NAME = "Artifactory Trial"
TRIAL_EMAIL = "trial@artifactory.invalid"
CHECKER_TIMEOUT_S = 3600
PASS_BAR = 4
# A dropped model connection is the server's fault, not the model's: resume the
# session up to MAX_RESUMES times, pausing first so the server can recover.
MAX_RESUMES = 3
RESUME_PAUSE_S = 30
RESUME_PROMPT = "The connection to the model dropped. Continue the task from where you left off."
# opencode error text that means the transport failed, not the agent.
DROP_PATTERNS = ("Transport:", "ECONNRESET", "socket connection was closed",
                 "Standalone server exited before reporting readiness")
INFRA_PREFIX = "infrastructure: "

GO_ENV_KEYS = ("GOPROXY", "GONOSUMDB", "GOFLAGS", "GOMODCACHE", "GOPATH", "GOTOOLCHAIN", "GOWORK")


@dataclass
class RoundResult:
    test: str
    round: int
    results: list[TrialResult] = field(default_factory=list)

    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def met_bar(self) -> bool:
        return self.passes >= PASS_BAR

    @property
    def infrastructure_failures(self) -> int:
        return sum((r.reason or "").startswith(INFRA_PREFIX) for r in self.results)

    def to_json(self) -> str:
        return json.dumps({
            "test": self.test,
            "round": self.round,
            "passes": self.passes,
            "met_bar": self.met_bar,
            "infrastructure_failures": self.infrastructure_failures,
            "trials": [json.loads(r.to_json()) for r in self.results],
        }, indent=2)


@dataclass
class Trial:
    dir: Path
    project: Path
    home: Path
    bin: Path
    mirrors: Path | None
    proxy: Path | None
    env: dict[str, str]
    ro_binds: list[Path]


# --- trial setup -----------------------------------------------------------

def opencode_command(prompt: str) -> list[str]:
    # --standalone: a private server inside the sandbox, not the user's background service.
    return [str(OPENCODE), "run", "--standalone", "--auto", "--format", "json", "--model", MODEL, prompt]


def opencode_config() -> dict:
    """The agentbox provider with the one trial model; nothing else from the user's config."""
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": MODEL,
        "small_model": MODEL,
        "autoupdate": False,
        "share": "disabled",
        "provider": {
            "agentbox": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Agentbox llama.cpp",
                "options": {"baseURL": LLAMA_URL, "apiKey": "llama-cpp",
                            "headerTimeout": 300000, "timeout": False},
                "models": {
                    "ornith-1.5-q4": {
                        "name": "Ornith 1.5 35B A3B",
                        "tool_call": True,
                        "reasoning": True,
                        "limit": {"context": 131072, "output": 32768},
                        "cost": {"input": 0, "output": 0},
                    },
                },
            },
        },
    }


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _gitconfig(mirrors: Path | None) -> str:
    lines = ["[user]", f"\tname = {TRIAL_NAME}", f"\temail = {TRIAL_EMAIL}",
             "[init]", "\tdefaultBranch = main",
             "[protocol \"file\"]", "\tallow = always"]
    if mirrors is not None:
        lines += [f"[url \"file://{mirrors}/\"]"] + [f"\tinsteadOf = {url}" for url in KIT_REMOTE_FORMS]
    return "\n".join(lines) + "\n"


def _nuget_config() -> str:
    """Restore from the host package cache (read-only) as a fallback folder; new packages go to HOME."""
    fallback = (f'    <add key="host" value="{NUGET_PACKAGES}" />\n' if NUGET_PACKAGES.is_dir() else "")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n'
            f"  <fallbackPackageFolders>\n{fallback}  </fallbackPackageFolders>\n</configuration>\n")


def _write_home(home: Path, mirrors: Path | None) -> None:
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text(json.dumps(opencode_config(), indent=2))
    (home / ".gitconfig").write_text(_gitconfig(mirrors))
    (home / ".nuget" / "NuGet").mkdir(parents=True)
    (home / ".nuget" / "NuGet" / "NuGet.Config").write_text(_nuget_config())


def _base_env(home: Path, bin_dir: Path, proxy: Path | None) -> dict[str, str]:
    env = {
        "HOME": str(home),
        "USER": os.environ.get("USER", "trial"),
        "PATH": f"{bin_dir}:{OPENCODE.parent}:/usr/local/bin:/usr/bin",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if proxy is not None:
        genv = go_env(proxy, home / "go")
        env.update({k: genv[k] for k in GO_ENV_KEYS})
    return env


def _tool_binds(mirrors: Path | None, proxy: Path | None, bin_dir: Path) -> list[Path]:
    binds = [bin_dir, OPENCODE]
    if GODOT_BINARY.is_file():
        binds.append(GODOT_BINARY.parent)  # GodotSharp lives next to the binary
    if NUGET_PACKAGES.is_dir():
        binds.append(NUGET_PACKAGES)
    binds += [p for p in (mirrors, proxy) if p is not None]
    return binds


def prepare_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None,
                  proxy: Path | None) -> Trial:
    """Create project (fixture + MODULES.md, committed), HOME and the godot launcher."""
    trial_dir = Path(trial_dir).resolve()
    if trial_dir.exists():
        raise FileExistsError(f"{trial_dir} already exists; remove it to rerun the trial")
    mirrors = Path(mirrors).resolve() if mirrors is not None else None
    proxy = Path(proxy).resolve() if proxy is not None else None
    project, home, bin_dir = trial_dir / "project", trial_dir / "home", trial_dir / "bin"
    trial_dir.mkdir(parents=True)
    shutil.copytree(test.fixture, project, symlinks=True)
    (project / "MODULES.md").write_text(index_md)
    _git("init", "-q", "-b", "main", cwd=project)
    _git("add", "-A", cwd=project)
    _git("-c", f"user.name={TRIAL_NAME}", "-c", f"user.email={TRIAL_EMAIL}", "-c", "commit.gpgsign=false",
         "commit", "-qm", "Initial project", cwd=project)
    home.mkdir()
    _write_home(home, mirrors)
    bin_dir.mkdir()
    # A script, never a symlink: a symlinked Godot deadlocks headless.
    launcher = bin_dir / "godot"
    launcher.write_text(f'#!/bin/sh\nexec "{GODOT_BINARY}" "$@"\n')
    launcher.chmod(0o755)
    return Trial(trial_dir, project, home, bin_dir, mirrors, proxy,
                 _base_env(home, bin_dir, proxy), _tool_binds(mirrors, proxy, bin_dir))


# --- running ---------------------------------------------------------------

def agent_command(trial: Trial, argv: list[str]) -> list[str]:
    return sandbox_command(trial.project, trial.home, trial.ro_binds, argv, trial.env)


def _run_sandboxed(cmd: list[str], stdout: Path, stderr: Path | None, timeout: float,
                   append: bool = False) -> bool:
    """Run a sandbox; True if it finished, False if killed at the timeout.

    bwrap runs in its own session and process group; killing the group kills
    bwrap, and --die-with-parent plus the PID namespace take every process
    inside the sandbox with it, including ones that called setsid.
    """
    # Pipes, pumped to the files from here: under SELinux, pasta's domain may not
    # write user_home_t files, and the kernel then drops inherited file fds.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE if stderr else subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    pumps = [threading.Thread(target=_pump, args=(proc.stdout, stdout, append), daemon=True)]
    if stderr:
        pumps.append(threading.Thread(target=_pump, args=(proc.stderr, stderr, append), daemon=True))
    for t in pumps:
        t.start()
    try:
        proc.wait(timeout=timeout)
        finished = True
    except subprocess.TimeoutExpired:
        finished = False
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for t in pumps:
            t.join(timeout=30)
    return finished


def _pump(src, dest: Path, append: bool = False) -> None:
    with src, open(dest, "ab" if append else "wb") as out:
        for chunk in iter(lambda: src.read1(65536), b""):
            out.write(chunk)
            out.flush()


def _python_binds() -> list[Path]:
    """The interpreter install behind this venv (the venv itself is inside the repo)."""
    binds = [Path(sys.base_prefix)]
    link = Path(sys.executable)
    while link.is_symlink():
        target = Path(os.readlink(link))
        link = target if target.is_absolute() else link.parent / target
        binds.append(link.parent.parent)
    return binds


def checker_command(trial: Trial, test_dir: Path, ecosystem: str, fixture: Path, out: Path, branch: str,
                    baseline: bool) -> list[str]:
    check_home = trial.dir / "checker-home"
    argv = [sys.executable, "-m", "artifactory.cli", "check", str(Path(test_dir).resolve()), str(trial.project)]
    if ecosystem == "go":
        argv += ["--proxy", str(trial.proxy)]
    else:
        argv += ["--mirrors", str(trial.mirrors), "--branch", branch]
        if baseline:
            argv.append("--baseline")
    argv += ["-o", str(out)]
    env = _base_env(check_home, trial.bin, None)
    env["PATH"] = f"{trial.bin}:/usr/local/bin:/usr/bin"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO / "tools")
    ro = [REPO, Path(test_dir), fixture, trial.project, trial.home, *_python_binds(), *trial.ro_binds]
    return sandbox_command(check_home, check_home, ro, argv, env, cwd=check_home)


def run_checker(trial: Trial, test: AcceptanceTest, test_dir: Path, branch: str, baseline: bool) -> TrialResult:
    check_home = trial.dir / "checker-home"
    if check_home.exists():
        shutil.rmtree(check_home)
    check_home.mkdir()
    (check_home / ".nuget" / "NuGet").mkdir(parents=True)
    (check_home / ".nuget" / "NuGet" / "NuGet.Config").write_text(_nuget_config())
    (check_home / ".gitconfig").write_text(_gitconfig(None))
    out = check_home / "checker.json"
    log = trial.dir / "checker.log"
    cmd = checker_command(trial, test_dir, test.ecosystem, test.fixture, out, branch, baseline)
    finished = _run_sandboxed(cmd, log, None, CHECKER_TIMEOUT_S)
    try:
        data = json.loads(out.read_text())
        checks = [CheckResult(c["name"], bool(c["passed"]), c["detail"]) for c in data["checks"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        why = "checker timed out" if not finished else f"checker produced no result ({type(e).__name__})"
        tail = log.read_text(errors="replace")[-2000:] if log.exists() else ""
        checks = [CheckResult("checker", False, f"{why}: {tail}")]
    return TrialResult(test=test.name, trial=trial.dir.name, checks=checks, reason=None)


def run_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None, proxy: Path | None,
              opencode_argv: list[str] | None = None, *, test_dir: Path | None = None,
              branch: str = STITCH_BRANCH, baseline: bool = False) -> TrialResult:
    """Set up the trial, run the agent sandboxed until done or time_limit_s, then check it sandboxed."""
    trial = prepare_trial(test, index_md, trial_dir, mirrors, proxy)
    argv = opencode_argv if opencode_argv is not None else opencode_command(test.prompt)
    transcript, log = trial.dir / "transcript.jsonl", trial.dir / "opencode.log"
    deadline = time.monotonic() + test.time_limit_s
    finished = _run_sandboxed(agent_command(trial, argv), transcript, log, test.time_limit_s)
    drop = _model_drop(transcript, 0, log, 0) if finished else None
    resumes = 0
    while drop and resumes < MAX_RESUMES and deadline - time.monotonic() > RESUME_PAUSE_S + 60:
        resumes += 1
        time.sleep(RESUME_PAUSE_S)
        at, log_at = transcript.stat().st_size, log.stat().st_size
        session, _ = drop
        finished = _run_sandboxed(agent_command(trial, resume_command(argv, session)), transcript, log,
                                  max(1.0, deadline - time.monotonic()), append=True)
        drop = _model_drop(transcript, at, log, log_at) if finished else None
    test_dir = Path(test_dir) if test_dir is not None else REPO / "tests" / "acceptance" / test.name
    result = run_checker(trial, test, test_dir, branch, baseline)
    result.resumes = resumes
    if drop:
        result.reason = f"{INFRA_PREFIX}model connection dropped after {resumes} resumes: {drop[1]}"
    elif not finished:
        result.reason = "timeout"
    (trial.dir / "checker.json").write_text(result.to_json())
    return result


def resume_command(argv: list[str], session: str | None) -> list[str]:
    """The agent command again, continuing `session` with RESUME_PROMPT in place of the prompt.

    With no session (the agent never started one), the original command runs again.
    """
    if session is None:
        return argv
    return [*argv[:-1], "--session", session, RESUME_PROMPT]


def _model_drop(transcript: Path, at: int, log: Path, log_at: int) -> tuple[str | None, str] | None:
    """(session id, message) if this attempt's run ended on a dropped model connection, else None.

    Only output written since byte offsets `at` and `log_at` counts. The run counts as dropped
    when its last transcript event is a transport error, or when it wrote no events and its
    log shows the standalone server failing to start.
    """
    events = []
    if transcript.exists():
        with open(transcript, "rb") as f:
            f.seek(at)
            for line in f.read().decode(errors="replace").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    if events:
        last = events[-1]
        message = str((last.get("error") or {}).get("message", "")) if last.get("type") == "error" else ""
        if any(p in message for p in DROP_PATTERNS):
            session = next((e["sessionID"] for e in reversed(events) if e.get("sessionID")), None)
            return session, message.splitlines()[0][:200]
        return None
    if log.exists():
        with open(log, "rb") as f:
            f.seek(log_at)
            text = f.read().decode(errors="replace")
        hit = next((p for p in DROP_PATTERNS if p in text), None)
        if hit:
            return None, hit
    return None


# --- rounds ----------------------------------------------------------------

def _godot_descriptors(mirrors: Path, modules: list[str], branch: str) -> list:
    descriptors = []
    with tempfile.TemporaryDirectory(prefix="artifactory-descriptors-") as tmp:
        for name in modules:
            mirror = mirrors / f"{name}.git"
            if not mirror.is_dir():
                raise RuntimeError(f"no mirror at {mirror}; run `artifactory mirror` first")
            r = subprocess.run(["git", "show", f"{branch}:module.yaml"], cwd=mirror, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: no module.yaml on {branch}: {r.stderr.strip()}")
            d = Path(tmp) / name
            d.mkdir()
            (d / "module.yaml").write_text(r.stdout)
            try:
                descriptors.append(load_descriptor(d))
            except DescriptorError as e:
                raise RuntimeError(f"{name}: invalid module.yaml on {branch}: {'; '.join(e.problems)}") from e
    return descriptors


def _go_descriptors(modules: list[str]) -> list:
    descriptors = []
    for name in modules:
        try:
            descriptors.append(load_descriptor(GO_SAMPLES / name))
        except DescriptorError as e:
            raise RuntimeError(f"{name}: {'; '.join(e.problems)}") from e
    return descriptors


def _go_sample_dirs() -> list[Path]:
    return sorted(d for d in GO_SAMPLES.iterdir() if (d / "go.mod").is_file())


def run_round(test_dir: Path, round_no: int, trials: int = 5, baseline: bool = False, *,
              results_root: Path | None = None, opencode_argv: list[str] | None = None) -> RoundResult:
    test_dir = Path(test_dir).resolve()
    test = load_acceptance(test_dir)
    root = Path(results_root or RESULTS).resolve()
    mirrors = proxy = None
    branch = BASELINE_BRANCH if baseline else STITCH_BRANCH
    if test.ecosystem == "go":
        if baseline:
            raise ValueError("baseline rounds are defined for the Godot test only")
        sample_names = {d.name for d in _go_sample_dirs()}
        missing = [m for m in test.modules if m not in sample_names]
        if missing:
            raise RuntimeError(f"no Go sample module for: {', '.join(missing)}")
        index_md = build_index(_go_descriptors(sorted(sample_names)), index_preamble("go"))
        proxy = root / "goproxy"
        if proxy.exists():
            shutil.rmtree(proxy)
        build_goproxy(_go_sample_dirs(), proxy)
    else:
        mirrors = root / "mirrors"
        for name in test.modules:
            if not (mirrors / f"{name}.git").is_dir():
                raise RuntimeError(f"no mirror at {mirrors / (name + '.git')}; run `artifactory mirror` first")
        if baseline:
            index_md = BASELINE_README.read_text()
        else:
            index_md = build_index(_godot_descriptors(mirrors, test.modules, branch), index_preamble(test.ecosystem))

    out = root / test.name / ("baseline" if baseline else f"round-{round_no}")
    out.mkdir(parents=True, exist_ok=True)
    result = RoundResult(test.name, round_no)
    for k in range(1, trials + 1):
        tr = run_trial(test, index_md, out / f"trial-{k}", mirrors, proxy, opencode_argv,
                       test_dir=test_dir, branch=branch, baseline=baseline)
        result.results.append(tr)
        (out / "round.json").write_text(result.to_json())
    (out / "round.json").write_text(result.to_json())
    return result


def refresh_mirrors(root: Path | None = None) -> list[Path]:
    """Bare mirrors of the Godot test's kits, with the user's ssh credentials (runs outside any sandbox)."""
    mirrors = Path(root or RESULTS).resolve() / "mirrors"
    mirrors.mkdir(parents=True, exist_ok=True)
    done = []
    for name in load_acceptance(GODOT_TEST).modules:
        dest = mirrors / f"{name}.git"
        if dest.is_dir():
            _git_retrying(["git", "remote", "update", "--prune"], cwd=dest)
        else:
            _git_retrying(["git", "clone", "--mirror", f"{KIT_REMOTE}{name}.git", str(dest)])
        done.append(dest)
    return done


def _git_retrying(argv: list[str], cwd: Path | None = None, attempts: int = 4) -> None:
    # The Forgejo host resets ssh connections that arrive in quick succession.
    for attempt in range(1, attempts + 1):
        if subprocess.run(argv, cwd=cwd).returncode == 0:
            return
        if attempt < attempts:
            time.sleep(5 * attempt)
    raise subprocess.CalledProcessError(1, argv)
