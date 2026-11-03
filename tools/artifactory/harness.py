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

import yaml

from .acceptance import AcceptanceTest, load_acceptance
from .checks.go import go_env
from .goproxy import build_goproxy
from .result import CheckResult, TrialResult
from .sandbox import sandbox_command

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results"
GO_SAMPLES = REPO / "samples" / "go"
GODOT_TEST = REPO / "tests" / "acceptance" / "godot-capsule-room"
BD_FALLBACK = Path.home() / ".local" / "lib" / "node_modules" / "@beads" / "bd" / "bin" / "bd"
DEFAULT_ARC_SRC = Path("/home/yalt/Documents/Projects/Tech/AI/arc")
DENIAL_MARK = "do not edit it."  # the tail of arc's deny reason for a write inside an installed module
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

GO_ENV_KEYS = ("GOPROXY", "GONOSUMDB", "GOFLAGS", "GOMODCACHE", "GOPATH", "GOTOOLCHAIN", "GOWORK")


@dataclass
class RoundResult:
    test: str
    round: int
    results: list[TrialResult] = field(default_factory=list)
    product: bool = False
    arc: bool = False

    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def met_bar(self) -> bool:
        return self.passes >= PASS_BAR

    def to_json(self) -> str:
        return json.dumps({
            "test": self.test,
            "round": self.round,
            "product": self.product,
            "arc": self.arc,
            "passes": self.passes,
            "met_bar": self.met_bar,
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
    base_commit: str | None = None  # the fixture commit (arc mode), the checker's gate base


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


def _run_tool(argv: list[str], env: dict[str, str], home: Path, cwd: Path | None = None) -> None:
    r = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, env={**env, "HOME": str(home)})
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:2])} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")


def bd_binary() -> Path:
    """The real bd binary. `~/.local/bin/bd` is a Node wrapper that runs itself forever when copied."""
    found = shutil.which("bd")
    if found:
        real = Path(found).resolve().parent / "bd"  # the wrapper resolves to bd.js beside the binary
        if real.is_file() and real.read_bytes()[:4] == b"\x7fELF":
            return real
    if BD_FALLBACK.is_file():
        return BD_FALLBACK.resolve()
    raise FileNotFoundError(f"bd not found: neither the package beside `which bd` nor {BD_FALLBACK}")


def bd_env(actor: str, home: Path) -> dict[str, str]:
    """Metrics off, a fixed actor, bd's state inside `home`."""
    return {"DO_NOT_TRACK": "1", "BEADS_ACTOR": actor, "HOME": str(home)}


def bd_run(project: Path, env: dict, *args) -> subprocess.CompletedProcess:
    """Run bd in `project` with `env`, host-side. env must carry bd_env's values; PATH defaults to the host's (bd runs git)."""
    return subprocess.run([str(bd_binary()), *args], cwd=project, env={"PATH": os.environ["PATH"], **env}, capture_output=True, text=True)


def _product_setup(test: AcceptanceTest, cli: Path, project: Path, home: Path, bin_dir: Path,
                   mirrors: Path | None, env: dict[str, str], arc: Path | None = None) -> None:
    """Put the CLI in the trial bin, point the project at the local mirrors and run `artifactory index`.

    With `arc` the project also gets arc: registry, opencode plugin, no pre-commit hook, and the
    index registers modules with arc. The project must already be a git repository."""
    if mirrors is None:
        raise ValueError("--product needs local kit mirrors")
    shutil.copy2(cli, bin_dir / "artifactory")
    if arc is not None:
        shutil.copy2(arc, bin_dir / "arc")
    config = {"ecosystem": test.ecosystem, "provider": f"dir:{mirrors}",
              "modules": [{"name": m} for m in test.modules]}
    (project / "artifactory.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    if arc is not None:
        (project / ".arch").mkdir(exist_ok=True)
        shutil.copy2(test.dir / "arc-registry.yaml", project / ".arch" / "registry.yaml")
        _run_tool([str(bin_dir / "arc"), "init", "--opencode", "--no-detect", "--ci", "none"], env, home, project)
        (project / ".git" / "hooks" / "pre-commit").unlink(missing_ok=True)
    _run_tool([str(bin_dir / "artifactory"), "index", "--project", str(project), "--arc",
               "on" if arc is not None else "off"], env, home)


def prepare_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None,
                  proxy: Path | None, cli: Path | None = None, arc: Path | None = None, roadmap: str = "none") -> Trial:
    """Create project (fixture + MODULES.md, committed), HOME and the godot launcher.

    With `cli` (product mode) the CLI is copied into the trial bin and writes MODULES.md itself.
    With `arc` (arc mode, needs `cli`) arc is installed in the project too.
    With `roadmap` frontier or ornith, bd is installed (metrics off, actor ornith) and initialised in
    the project; frontier also imports <test.dir>/roadmaps/frontier.jsonl."""
    if arc is not None and cli is None:
        raise ValueError("--arc needs --product")
    trial_dir = Path(trial_dir).resolve()
    if trial_dir.exists():
        raise FileExistsError(f"{trial_dir} already exists; remove it to rerun the trial")
    mirrors = Path(mirrors).resolve() if mirrors is not None else None
    proxy = Path(proxy).resolve() if proxy is not None else None
    project, home, bin_dir = trial_dir / "project", trial_dir / "home", trial_dir / "bin"
    trial_dir.mkdir(parents=True)
    shutil.copytree(test.fixture, project, symlinks=True)
    home.mkdir()
    _write_home(home, mirrors)
    bin_dir.mkdir()
    env = _base_env(home, bin_dir, proxy)
    _git("init", "-q", "-b", "main", cwd=project)
    if cli is not None:
        _product_setup(test, Path(cli), project, home, bin_dir, mirrors, env, Path(arc) if arc else None)
    else:
        (project / "MODULES.md").write_text(index_md)
    _git("add", "-A", cwd=project)
    _git("-c", f"user.name={TRIAL_NAME}", "-c", f"user.email={TRIAL_EMAIL}", "-c", "commit.gpgsign=false",
         "commit", "-qm", "Initial project", cwd=project)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True,
                          text=True).stdout.strip() if arc is not None else None
    if roadmap != "none":
        shutil.copy2(bd_binary(), bin_dir / "bd")
        env.update(bd_env("ornith", home))
        for args in [("init", "--stealth", "--non-interactive"),
                     *([("import", str(test.dir / "roadmaps" / "frontier.jsonl"))] if roadmap == "frontier" else [])]:
            r = bd_run(project, env, *args)
            if r.returncode != 0:
                raise RuntimeError(f"bd {args[0]} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
    # A script, never a symlink: a symlinked Godot deadlocks headless.
    launcher = bin_dir / "godot"
    launcher.write_text(f'#!/bin/sh\nexec "{GODOT_BINARY}" "$@"\n')
    launcher.chmod(0o755)
    return Trial(trial_dir, project, home, bin_dir, mirrors, proxy,
                 env, _tool_binds(mirrors, proxy, bin_dir), base)


# --- running ---------------------------------------------------------------

def agent_command(trial: Trial, argv: list[str]) -> list[str]:
    return sandbox_command(trial.project, trial.home, trial.ro_binds, argv, trial.env)


def _run_sandboxed(cmd: list[str], stdout: Path, stderr: Path | None, timeout: float) -> bool:
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
    pumps = [threading.Thread(target=_pump, args=(proc.stdout, stdout), daemon=True)]
    if stderr:
        pumps.append(threading.Thread(target=_pump, args=(proc.stderr, stderr), daemon=True))
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


def _pump(src, dest: Path) -> None:
    with src, open(dest, "wb") as out:
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
        if trial.base_commit is not None:
            argv += ["--arc", "--arc-base", trial.base_commit]
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
        checks = [CheckResult(c["name"], bool(c["passed"]), c["detail"], c.get("gating", True))
                  for c in data["checks"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        why = "checker timed out" if not finished else f"checker produced no result ({type(e).__name__})"
        tail = log.read_text(errors="replace")[-2000:] if log.exists() else ""
        checks = [CheckResult("checker", False, f"{why}: {tail}")]
    return TrialResult(test=test.name, trial=trial.dir.name, checks=checks, reason=None)


def run_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None, proxy: Path | None,
              opencode_argv: list[str] | None = None, *, test_dir: Path | None = None,
              branch: str = STITCH_BRANCH, baseline: bool = False, cli: Path | None = None,
              arc: Path | None = None) -> TrialResult:
    """Set up the trial, run the agent sandboxed until done or time_limit_s, then check it sandboxed."""
    trial = prepare_trial(test, index_md, trial_dir, mirrors, proxy, cli, arc)
    argv = opencode_argv if opencode_argv is not None else opencode_command(test.prompt)
    finished = _run_sandboxed(agent_command(trial, argv), trial.dir / "transcript.jsonl",
                              trial.dir / "opencode.log", test.time_limit_s)
    test_dir = Path(test_dir) if test_dir is not None else REPO / "tests" / "acceptance" / test.name
    result = run_checker(trial, test, test_dir, branch, baseline)
    if not finished:
        result.reason = "timeout"
    if arc is not None:
        result.arc_denials = count_denials(trial.dir / "transcript.jsonl")
        result.arc_hook_live = arc_hook_live(trial.project)
    (trial.dir / "checker.json").write_text(result.to_json())
    return result


# --- rounds ----------------------------------------------------------------

def build_cli(out: Path) -> Path:
    """Build the Go `artifactory` CLI into <out>/bin/artifactory and return its path."""
    binary = Path(out) / "bin" / "artifactory"
    binary.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["go", "build", "-o", str(binary), "./cmd/artifactory"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"go build failed: {r.stderr.strip()}")
    return binary


def build_arc(out: Path, src: Path | None = None) -> Path:
    """Build `arc` from its source tree (default $ARC_SRC, else the main checkout) into <out>/bin/arc."""
    src = Path(src or os.environ.get("ARC_SRC") or DEFAULT_ARC_SRC)
    binary = Path(out) / "bin" / "arc"
    binary.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["go", "build", "-o", str(binary), "./cmd/arc"], cwd=src, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"arc build failed in {src}: {r.stderr.strip()}")
    return binary


def arc_hook_live(project: Path) -> bool:
    """Whether arc's hook ran in the trial: it keeps per-session state in .arch/cache/hook-<session>.json
    (arc SPEC, "arc hook"), and only a hook that loaded and ran under the agent writes it."""
    return any((Path(project) / ".arch" / "cache").glob("hook-*.json"))


def count_denials(transcript: Path) -> int:
    """How often arc refused a write: its deny reason as the model saw it in the opencode stdout."""
    # Deliberately a plain substring count over the raw transcript, not a parse of tool events:
    # it also counts the phrase if the model quotes it in its own text. Good enough as a tally.
    try:
        return Path(transcript).read_text(errors="replace").count(DENIAL_MARK)
    except OSError:
        return 0


def render_index(cli: Path, ecosystem: str, provider: str, modules: list[str]) -> str:
    """The MODULES.md that `artifactory index --modules-only` renders for these modules."""
    config = {"ecosystem": ecosystem, "provider": provider, "modules": [{"name": m} for m in modules]}
    with tempfile.TemporaryDirectory(prefix="artifactory-index-") as tmp:
        (Path(tmp) / "artifactory.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        r = subprocess.run([str(cli), "index", "--project", tmp, "--modules-only"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"artifactory index failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
        return (Path(tmp) / "MODULES.md").read_text()


def _go_sample_dirs() -> list[Path]:
    return sorted(d for d in GO_SAMPLES.iterdir() if (d / "go.mod").is_file())


def run_round(test_dir: Path, round_no: int, trials: int = 5, baseline: bool = False, *,
              results_root: Path | None = None, opencode_argv: list[str] | None = None,
              product: bool = False, arc: bool = False, arc_src: Path | None = None) -> RoundResult:
    test_dir = Path(test_dir).resolve()
    test = load_acceptance(test_dir)
    root = Path(results_root or RESULTS).resolve()
    mirrors = proxy = cli = arc_bin = None
    if arc and not product:
        raise ValueError("--arc needs --product")
    if product and (baseline or test.ecosystem == "go"):
        raise ValueError("--product is defined for non-baseline Godot rounds only")
    branch = BASELINE_BRANCH if baseline else STITCH_BRANCH
    if test.ecosystem == "go":
        if baseline:
            raise ValueError("baseline rounds are defined for the Godot test only")
        sample_names = {d.name for d in _go_sample_dirs()}
        missing = [m for m in test.modules if m not in sample_names]
        if missing:
            raise RuntimeError(f"no Go sample module for: {', '.join(missing)}")
        index_md = render_index(build_cli(root), "go", f"dir:{GO_SAMPLES}", sorted(sample_names))
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
        elif product:
            cli = build_cli(root)
            arc_bin = build_arc(root, arc_src) if arc else None
            index_md = ""  # the CLI renders MODULES.md in each trial
        else:
            index_md = render_index(build_cli(root), test.ecosystem, f"dir:{mirrors}", test.modules)

    out = root / test.name / ("baseline" if baseline else f"round-{round_no}")
    out.mkdir(parents=True, exist_ok=True)
    result = RoundResult(test.name, round_no, product=product, arc=arc)
    for k in range(1, trials + 1):
        tr = run_trial(test, index_md, out / f"trial-{k}", mirrors, proxy, opencode_argv,
                       test_dir=test_dir, branch=branch, baseline=baseline, cli=cli, arc=arc_bin)
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
