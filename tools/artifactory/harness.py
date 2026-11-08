"""Run acceptance-test trials: a local model in a bwrap sandbox, then the checker in another.

Layout of one trial directory:

    trial-K/
      project/          the model's working tree (writable by the model)
      home/             the model's HOME (writable by the model)
      bin/godot         launcher for the real Godot binary (read-only in the sandbox)
      transcript.jsonl  opencode JSON events (stdout)
      opencode.log      opencode stderr
      transcript-<n>.jsonl, opencode-<n>.log
                        the same per session, in roadmap trials (frontier, ornith)
      roadmap.jsonl     ornith: the beads its writing session created
      beads-final.jsonl roadmap trials: every bead at the end of the build loop
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
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .acceptance import AcceptanceTest, load_acceptance
from .checks.go import go_env
from .goproxy import build_goproxy
from .tooluse import count_tool_use
from .pyindex import build_pyindex, download_wheels, index_env, standard_wheels, uv_binary
from .result import CheckResult, TrialResult
from .sandbox import allowlist, sandbox_command

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
BAR_TRIALS = 5  # the bar is 4 of 5; a round with fewer trials reports pass counts without a verdict
# A dropped model connection is the server's fault, not the model's: resume the
# session up to MAX_RESUMES times, pausing first so the server can recover.
MAX_RESUMES = 3
RESUME_PAUSE_S = 30
RESUME_PROMPT = "The connection to the model dropped. Continue the task from where you left off."
# opencode error text that means the transport failed, not the agent.
DROP_PATTERNS = ("Transport:", "ECONNRESET", "socket connection was closed",
                 "Standalone server exited before reporting readiness")
INFRA_PREFIX = "infrastructure: "

ROADMAPS = ("none", "frontier", "ornith")
# The tool-value experiment's conditions: which of the artifactory CLI and arc the agent gets.
CONDITIONS = ("control", "artifactory", "arc", "both")
WRITER_ACTOR = "roadmap-writer"  # the frontier roadmap writer's bd actor
BD_TIMEOUT_S = 120  # one host-side bd call; a hung bd must not end the trial's bookkeeping silently
WRITING_LIMIT_S = 1200  # the ornith writing phase's share of the trial budget, at most
QUICK_SESSION_S = 60    # a loop session shorter than this, with no bead status change, is "quick"
STALL_RUN = 3           # this many quick sessions in a row stop the loop (a dead model server)
BEAD_PROMPT = "Work bead {id}. Run bd show {id} first, do only what it says, run its check, then bd close {id}."
STALL_PROMPT = ("Some beads are unfinished. Run bd list --status open,blocked and work through them in any order, "
                "ignoring dependencies. Close each one you finish.")

GO_ENV_KEYS = ("GOPROXY", "GONOSUMDB", "GOFLAGS", "GOMODCACHE", "GOPATH", "GOTOOLCHAIN", "GOWORK")


@dataclass
class RoundResult:
    test: str
    round: int
    results: list[TrialResult] = field(default_factory=list)
    product: bool = False
    arc: bool = False
    roadmap: str = "none"
    time_limit_s: int | None = None
    standard_commit: str | None = None  # REPO HEAD, "-dirty" if the tree had changes; None if git failed
    kits: dict[str, str | None] = field(default_factory=dict)  # module -> mirror main SHA (empty for Go rounds)
    pyindex_wheels: list[str] = field(default_factory=list)  # wheel filenames of the built index (Python rounds only)
    condition: str | None = None  # experiment rounds only (one of CONDITIONS); omitted from JSON otherwise

    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def met_bar(self) -> bool | None:
        """None when the round has fewer than BAR_TRIALS trials: the 4-of-5 bar does not apply."""
        if len(self.results) < BAR_TRIALS:
            return None
        return self.passes >= PASS_BAR

    @property
    def infrastructure_failures(self) -> int:
        return sum((r.reason or "").startswith(INFRA_PREFIX) for r in self.results)

    def to_json(self) -> str:
        return json.dumps({
            "test": self.test,
            "round": self.round,
            "product": self.product,
            "arc": self.arc,
            "roadmap": self.roadmap,
            **({"condition": self.condition} if self.condition is not None else {}),
            "time_limit_s": self.time_limit_s,
            "standard_commit": self.standard_commit,
            "kits": self.kits,
            "pyindex_wheels": self.pyindex_wheels,
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
    base_commit: str | None = None  # the fixture commit (arc mode, every experiment trial), the checker's gate base
    pyindex: Path | None = None  # the local wheel directory pip and uv install from (Python tests)
    condition: str | None = None  # experiment trials only: one of CONDITIONS
    checker_bin: Path | None = None  # experiment trials: tools only the checker gets (arc), never bound for the agent


# --- trial setup -----------------------------------------------------------

def opencode_command(prompt: str) -> list[str]:
    # --standalone: a private server inside the sandbox, not the user's background service.
    return [str(OPENCODE), "run", "--standalone", "--auto", "--format", "json", "--model", MODEL, prompt]


def opencode_config(mcp: bool = False) -> dict:
    """The agentbox provider with the one trial model; nothing else from the user's config.

    With `mcp`, also the `artifactory mcp` server (the experiment's artifactory and both conditions);
    opencode starts it itself, so `artifactory` must be on the sandbox PATH."""
    config = {
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
    if mcp:
        config["mcp"] = {"artifactory": {"type": "local", "command": ["artifactory", "mcp"], "enabled": True}}
    return config


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


def _write_home(home: Path, mirrors: Path | None, mcp: bool = False) -> None:
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text(json.dumps(opencode_config(mcp), indent=2))
    (home / ".gitconfig").write_text(_gitconfig(mirrors))
    (home / ".nuget" / "NuGet").mkdir(parents=True)
    (home / ".nuget" / "NuGet" / "NuGet.Config").write_text(_nuget_config())


def _base_env(home: Path, bin_dir: Path, proxy: Path | None, pyindex: Path | None = None) -> dict[str, str]:
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
        "OPENCODE_DISABLE_MODELS_FETCH": "1",  # models.dev is out of reach: the sandbox only reaches the model
    }
    if proxy is not None:
        genv = go_env(proxy, home / "go")
        env.update({k: genv[k] for k in GO_ENV_KEYS})
    if pyindex is not None:
        env.update(index_env(pyindex))
    return env


def _tool_binds(mirrors: Path | None, proxy: Path | None, bin_dir: Path,
                pyindex: Path | None = None) -> list[Path]:
    binds = [bin_dir, OPENCODE]
    if GODOT_BINARY.is_file():
        binds.append(GODOT_BINARY.parent)  # GodotSharp lives next to the binary
    if NUGET_PACKAGES.is_dir():
        binds.append(NUGET_PACKAGES)
    binds += [p for p in (mirrors, proxy, pyindex) if p is not None]
    return binds


def _install_uv(dest: Path) -> None:
    """Hard-link the host uv into the trial bin (copy across filesystems), then check that it runs."""
    src = uv_binary()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)
    r = subprocess.run([str(dest), "--version"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.startswith("uv "):
        raise RuntimeError(f"uv installed at {dest} (from {src}) does not run: "
                           f"{r.returncode}: {r.stderr.strip() or r.stdout.strip()}")


def _run_tool(argv: list[str], env: dict[str, str], home: Path, cwd: Path | None = None) -> None:
    r = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, env={**env, "HOME": str(home)})
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:2])} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")


def bd_binary() -> Path:
    """The real bd binary. `~/.local/bin/bd` is a Node wrapper that runs itself forever when copied."""
    found = shutil.which("bd")
    if found:
        real = Path(found).resolve().parent / "bd"  # the wrapper resolves to bd.js beside the binary
        if real.is_file() and _magic(real) == b"\x7fELF":
            return real
    if BD_FALLBACK.is_file():
        return BD_FALLBACK.resolve()
    raise FileNotFoundError(f"bd not found: neither the package beside `which bd` nor {BD_FALLBACK}")


def _magic(path: Path) -> bytes:
    with open(path, "rb") as f:  # the binary is ~150 MB and this runs on every bd call
        return f.read(4)


def bd_env(actor: str, home: Path) -> dict[str, str]:
    """Metrics off, a fixed actor, bd's state inside `home`."""
    return {"DO_NOT_TRACK": "1", "BEADS_ACTOR": actor, "HOME": str(home)}


def bd_run(project: Path, env: dict, *args) -> subprocess.CompletedProcess:
    """Run bd in `project` with `env`, host-side. env must carry bd_env's values; PATH defaults to the host's (bd runs git)."""
    if "HOME" not in env:  # never fall back to the user's HOME: bd would write ~/.beads there
        raise ValueError("bd_run needs HOME in env (see bd_env)")
    try:
        return subprocess.run([str(bd_binary()), *args], cwd=project, env={"PATH": os.environ["PATH"], **env},
                              capture_output=True, text=True, timeout=BD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"bd {' '.join(args[:2])} timed out after {BD_TIMEOUT_S} s") from None


def _product_setup(test: AcceptanceTest, cli: Path, project: Path, home: Path, bin_dir: Path,
                   mirrors: Path | None, env: dict[str, str], arc: Path | None = None) -> None:
    """Put the CLI in the trial bin, point the project at the local mirrors and run `artifactory index`.

    With `arc` the project also gets arc: registry, opencode plugin, no pre-commit hook, and the
    index registers modules with arc. The project must already be a git repository."""
    if mirrors is None:
        raise ValueError("--product needs local kit mirrors")
    shutil.copy2(cli, bin_dir / "artifactory")
    config = {"ecosystem": test.ecosystem, "provider": f"dir:{mirrors}",
              "modules": [{"name": m} for m in test.modules]}
    (project / "artifactory.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    if arc is not None:
        _arc_setup(test, arc, project, home, bin_dir, env)
    _run_tool([str(bin_dir / "artifactory"), "index", "--project", str(project), "--arc",
               "on" if arc is not None else "off"], env, home)


def _arc_setup(test: AcceptanceTest, arc: Path, project: Path, home: Path, bin_dir: Path,
               env: dict[str, str]) -> None:
    """arc in the trial bin, <test.dir>/arc-registry.yaml as the project's registry, `arc init` with the
    opencode plugin, and no pre-commit hook. The project must already be a git repository."""
    shutil.copy2(arc, bin_dir / "arc")
    (project / ".arch").mkdir(exist_ok=True)
    shutil.copy2(test.dir / "arc-registry.yaml", project / ".arch" / "registry.yaml")
    _run_tool([str(bin_dir / "arc"), "init", "--opencode", "--no-detect", "--ci", "none"], env, home, project)
    (project / ".git" / "hooks" / "pre-commit").unlink(missing_ok=True)


def _commit_fixture(project: Path) -> str:
    """Commit everything as the initial project and return the commit."""
    _git("add", "-A", cwd=project)
    _git("-c", f"user.name={TRIAL_NAME}", "-c", f"user.email={TRIAL_EMAIL}", "-c", "commit.gpgsign=false",
         "commit", "-qm", "Initial project", cwd=project)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True,
                          text=True).stdout.strip()


def _bd_setup(test: AcceptanceTest, project: Path, bin_dir: Path, home: Path, env: dict[str, str],
              roadmap: str) -> None:
    """bd in the trial bin, its env in `env`, initialised in the project; frontier imports the roadmap."""
    shutil.copy2(bd_binary(), bin_dir / "bd")
    env.update(bd_env(WRITER_ACTOR if roadmap == "workspace" else "ornith", home))
    for args in [("init", "--stealth", "--non-interactive"),
                 *([("import", str(test.dir / "roadmaps" / "frontier.jsonl"))] if roadmap == "frontier" else [])]:
        r = bd_run(project, env, *args)
        if r.returncode != 0:
            raise RuntimeError(f"bd {args[0]} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")


def prepare_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None,
                  proxy: Path | None, cli: Path | None = None, arc: Path | None = None, roadmap: str = "none",
                  pyindex: Path | None = None) -> Trial:
    """Create project (fixture + MODULES.md, committed), HOME and the godot launcher.

    With `cli` (product mode) the CLI is copied into the trial bin and writes MODULES.md itself.
    With `arc` (arc mode, needs `cli`) arc is installed in the project too.
    With `roadmap` frontier or ornith, bd is installed (metrics off, actor ornith) and initialised in
    the project; frontier also imports <test.dir>/roadmaps/frontier.jsonl. `workspace` (only for
    prepare_roadmap_workspace) installs bd with actor roadmap-writer and imports nothing.
    With `pyindex` (Python tests) uv is copied into the trial bin and pip and uv install only from that
    wheel directory, bound read-only."""
    if arc is not None and cli is None:
        raise ValueError("--arc needs --product")
    trial_dir = Path(trial_dir).resolve()
    if trial_dir.exists():
        raise FileExistsError(f"{trial_dir} already exists; remove it to rerun the trial")
    mirrors = Path(mirrors).resolve() if mirrors is not None else None
    proxy = Path(proxy).resolve() if proxy is not None else None
    pyindex = Path(pyindex).resolve() if pyindex is not None else None
    project, home, bin_dir = trial_dir / "project", trial_dir / "home", trial_dir / "bin"
    trial_dir.mkdir(parents=True)
    shutil.copytree(test.fixture, project, symlinks=True)
    home.mkdir()
    _write_home(home, mirrors)
    bin_dir.mkdir()
    if pyindex is not None and not pyindex.is_dir():
        raise FileNotFoundError(f"Python wheel index {pyindex} does not exist; build it with build_pyindex")
    env = _base_env(home, bin_dir, proxy, pyindex)
    if pyindex is not None:
        _install_uv(bin_dir / "uv")
    _git("init", "-q", "-b", "main", cwd=project)
    if cli is not None:
        _product_setup(test, Path(cli), project, home, bin_dir, mirrors, env, Path(arc) if arc else None)
    else:
        (project / "MODULES.md").write_text(index_md)
    base = _commit_fixture(project)
    if arc is None:
        base = None
    if roadmap != "none":
        _bd_setup(test, project, bin_dir, home, env, roadmap)
    # A script, never a symlink: a symlinked Godot deadlocks headless.
    launcher = bin_dir / "godot"
    launcher.write_text(f'#!/bin/sh\nexec "{GODOT_BINARY}" "$@"\n')
    launcher.chmod(0o755)
    return Trial(trial_dir, project, home, bin_dir, mirrors, proxy,
                 env, _tool_binds(mirrors, proxy, bin_dir, pyindex), base, pyindex)


def prepare_experiment_trial(test: AcceptanceTest, condition: str, trial_dir: Path, proxy: Path, catalog: Path,
                             cli: Path, arc: Path) -> Trial:
    """One experiment trial's project, HOME and bin for `condition` (see CONDITIONS), on the frozen roadmap.

    Every condition: the fixture as a git repository, bd with <test.dir>/roadmaps/frontier.jsonl imported,
    the file GOPROXY, and arc in <trial>/checker-bin for the checker only.
    arc, both: the arc_overlay files, then arc as in product mode (`_arc_setup`).
    artifactory, both: the CLI in the bin, `.opencode/`, `artifactory init` over the `dir:` catalog
    (bound read-only for the agent), and the `artifactory mcp` server in the opencode config."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {', '.join(CONDITIONS)}, not {condition!r}")
    tool, has_arc = condition in ("artifactory", "both"), condition in ("arc", "both")
    trial_dir = Path(trial_dir).resolve()
    if trial_dir.exists():
        raise FileExistsError(f"{trial_dir} already exists; remove it to rerun the trial")
    proxy, catalog = Path(proxy).resolve(), Path(catalog).resolve()
    project, home, bin_dir = trial_dir / "project", trial_dir / "home", trial_dir / "bin"
    checker_bin = trial_dir / "checker-bin"
    trial_dir.mkdir(parents=True)
    shutil.copytree(test.fixture, project, symlinks=True)
    home.mkdir()
    _write_home(home, None, mcp=tool)
    bin_dir.mkdir()
    checker_bin.mkdir()
    shutil.copy2(arc, checker_bin / "arc")
    env = _base_env(home, bin_dir, proxy)
    _git("init", "-q", "-b", "main", cwd=project)
    if has_arc:
        if test.arc_overlay is not None:
            shutil.copytree(test.arc_overlay, project, symlinks=True, dirs_exist_ok=True)
        _arc_setup(test, Path(arc), project, home, bin_dir, env)
    if tool:
        shutil.copy2(cli, bin_dir / "artifactory")
        (project / ".opencode").mkdir(exist_ok=True)
        # arc auto: in both, kits installed later are registered with arc
        _run_tool([str(bin_dir / "artifactory"), "init", "--ecosystem", test.ecosystem,
                   "--provider", f"dir:{catalog}", "--project", str(project)], env, home)
    base = _commit_fixture(project)
    _bd_setup(test, project, bin_dir, home, env, "frontier")
    binds = _tool_binds(None, proxy, bin_dir) + ([catalog] if tool else [])
    return Trial(trial_dir, project, home, bin_dir, None, proxy, env, binds, base,
                 condition=condition, checker_bin=checker_bin)


def prepare_roadmap_workspace(test: AcceptanceTest, out_dir: Path, mirrors: Path, cli: Path, arc: Path) -> tuple[Trial, str]:
    """A frontier trial's product+arc project without a roadmap, for the writer subagent.

    BRIEF.md and ROADMAP-PROMPT.md sit in the project (git-excluded). Returns the trial and the
    `env` prefix the writer puts before every command."""
    if not test.roadmap_prompt:
        raise ValueError(f"{test.dir / 'test.yaml'} has no roadmap_prompt")
    trial = prepare_trial(test, "", out_dir, mirrors, None, cli=cli, arc=arc, roadmap="workspace")
    (trial.project / "BRIEF.md").write_text(test.prompt)
    (trial.project / "ROADMAP-PROMPT.md").write_text(test.roadmap_prompt)
    with open(trial.project / ".git" / "info" / "exclude", "a") as f:
        f.write("\nBRIEF.md\nROADMAP-PROMPT.md\n")
    prefix = (f"env PATH={shlex.quote(str(trial.bin))}:$PATH DO_NOT_TRACK=1 BEADS_ACTOR={WRITER_ACTOR} "
              f"HOME={shlex.quote(str(trial.home))}")
    return trial, prefix


def export_roadmap(project: Path, dest: Path) -> int:
    """Export the writer's beads to `dest` (jsonl) and return how many; refuse a roadmap the writer left
    claimed or that a different actor touched (a bead the build would trip over, or not frontier's own)."""
    project, dest = Path(project).resolve(), Path(dest).resolve()  # bd runs in the project
    env = bd_env(WRITER_ACTOR, project.parent / "home")
    tmp = dest.with_name(f".{dest.name}.tmp")  # moved into place only once the beads pass
    try:
        r = bd_run(project, env, "export", "-o", str(tmp))
        if r.returncode != 0:
            raise RuntimeError(f"bd export failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
        rows = [json.loads(line) for line in tmp.read_text().splitlines() if line.strip()]
        beads = [b for b in rows if b.get("_type", "issue") == "issue"]
        bad = _unexportable(beads)
        if bad:
            raise RuntimeError("roadmap not exportable: " + "; ".join(bad))
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return len(beads)


def _unexportable(beads: list[dict]) -> list[str]:
    bad = [f"{b['id']}: " + ("in_progress" if b.get("status") == "in_progress" else f"assignee {b['assignee']!r}")
           for b in beads if b.get("status") == "in_progress" or b.get("assignee") not in (None, "", WRITER_ACTOR)]
    bad += [f"{b['id']}: created_by {b.get('created_by')!r} (`bd q` leaves it empty; use `bd create`)" for b in beads if b.get("created_by") != WRITER_ACTOR]
    return bad


# --- running ---------------------------------------------------------------

def model_endpoints(url: str | None = None) -> list[tuple[str, int]]:
    """The llama server as (ip, port) for each address its host resolves to on the host.

    These are the agent sandbox's only network destinations (the sandbox itself has no DNS).
    """
    url = url or LLAMA_URL
    parts = urlsplit(url)
    if not parts.hostname:
        raise RuntimeError(f"LLAMA_URL {url!r} has no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise RuntimeError(f"LLAMA_URL {url!r}: cannot resolve {parts.hostname!r}: {e}") from e
    return list(dict.fromkeys((info[4][0], port) for info in infos))


def agent_command(trial: Trial, argv: list[str]) -> list[str]:
    return sandbox_command(trial.project, trial.home, trial.ro_binds, argv, trial.env,
                           allow=allowlist(model_endpoints()))


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
                    baseline: bool, main_pkg: str | None = None) -> list[str]:
    """The sandboxed checker argv. An experiment trial (trial.condition set, Go) also gets the main package,
    the held arc registry and the fixture commit; trial.checker_bin follows trial.bin on its PATH."""
    check_home = trial.dir / "checker-home"
    test_dir = Path(test_dir).resolve()
    argv = [sys.executable, "-m", "artifactory.cli", "check", str(test_dir), str(trial.project)]
    if ecosystem == "go":
        argv += ["--proxy", str(trial.proxy)]
        if trial.condition is not None:
            if main_pkg is None or trial.base_commit is None:
                raise ValueError("an experiment trial's checker needs main_pkg and the trial's base commit")
            argv += ["--main-pkg", main_pkg, "--arc-registry", str(test_dir / "arc-registry.yaml"),
                     "--arc-base", trial.base_commit]
    elif ecosystem == "python":
        if trial.pyindex is None:
            raise ValueError("a Python trial needs a wheel index (pyindex)")
        argv += ["--pyindex", str(trial.pyindex)]
    elif ecosystem == "godot-csharp":
        argv += ["--mirrors", str(trial.mirrors), "--branch", branch]
        if baseline:
            argv.append("--baseline")
        if trial.base_commit is not None:
            argv += ["--arc", "--arc-base", trial.base_commit]
    else:
        raise ValueError(f"no checker for ecosystem {ecosystem!r}")
    argv += ["-o", str(out)]
    env = _base_env(check_home, trial.bin, None, trial.pyindex)
    extra = [trial.checker_bin] if trial.checker_bin is not None else []
    env["PATH"] = ":".join(map(str, [trial.bin, *extra, "/usr/local/bin", "/usr/bin"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO / "tools")
    ro = [REPO, test_dir, fixture, trial.project, trial.home, *_python_binds(), *trial.ro_binds, *extra]
    # No allow list, not even ARTIFACTORY_SANDBOX_ALLOW: the checker gets no network.
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
    cmd = checker_command(trial, test_dir, test.ecosystem, test.fixture, out, branch, baseline, test.main_pkg)
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


@dataclass
class RoadmapOutcome:
    """A roadmap trial's bead counts (from the final export) and how its build loop went."""
    beads: int = 0
    closed: int = 0
    blocked: int = 0
    sessions: int = 0        # build-phase sessions: bead, stall, or the brief fallback; not the writing session
    stall_sessions: int = 0
    roadmap_failed: bool = False  # ornith wrote no beads; the build was one session with the brief
    loop_stalled: bool = False    # STALL_RUN quick sessions in a row with no bead status change
    bd_error: str | None = None   # host-side bd failed (say the agent broke .beads); the loop stopped there
    export_error: str | None = None  # the final export failed after a bd_error; counts then read 0


@dataclass
class SessionRun:
    """One agent session, resumed in place after dropped model connections."""
    finished: bool               # False: killed at its time limit
    resumes: int = 0
    drop: tuple[str | None, str] | None = None  # (session id, message) if still dropped after the last resume


def run_session(trial: Trial, argv: list[str], transcript: Path, log: Path, limit: float) -> SessionRun:
    """Run `argv` sandboxed for at most `limit` seconds; on a dropped model connection, resume the same
    session (appending to transcript and log) up to MAX_RESUMES times while time allows."""
    deadline = time.monotonic() + limit
    finished = _run_sandboxed(agent_command(trial, argv), transcript, log, limit)
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
    return SessionRun(finished, resumes, drop)


class _Sessions:
    """Fresh agent sessions in one trial, all against one deadline. Session n writes transcript-<n>.jsonl."""

    def __init__(self, trial: Trial, opencode_argv: list[str] | None, time_limit_s: float):
        self.trial, self.argv = trial, opencode_argv
        self.deadline = time.monotonic() + time_limit_s
        self.n = 0
        self.killed_at_deadline = False  # the last session's fate: the timeout rule reads only this
        self.resumes = 0  # over all sessions
        self.dropped: SessionRun | None = None  # a session still dropped after its resumes; no more run

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def run(self, prompt: str, cap: float | None = None) -> float:
        """Run one session (limit: the time left, or `cap` if smaller); return its duration."""
        self.n += 1
        left = self.remaining()
        limit = left if cap is None else min(cap, left)
        argv = self.argv + [prompt] if self.argv is not None else opencode_command(prompt)
        start = time.monotonic()
        run = run_session(self.trial, argv, self.trial.dir / f"transcript-{self.n}.jsonl",
                          self.trial.dir / f"opencode-{self.n}.log", max(limit, 0))
        self.resumes += run.resumes
        if run.drop:
            self.dropped = run
        self.killed_at_deadline = not run.finished and limit == left
        return time.monotonic() - start

    def usable(self) -> bool:
        """Time is left and no session has ended on a connection that resuming could not restore."""
        return self.remaining() > 0 and self.dropped is None


def _bd_json(trial: Trial, *args: str):
    r = bd_run(trial.project, trial.env, *args, "--json")
    if r.returncode != 0:
        raise RuntimeError(f"bd {' '.join(args)} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout or "null") or []


def _bd_ok(trial: Trial, *args: str) -> None:
    r = bd_run(trial.project, trial.env, *args)
    if r.returncode != 0:
        raise RuntimeError(f"bd {' '.join(args[:2])} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")


def _bead_states(trial: Trial) -> dict[str, str]:
    return {b["id"]: b["status"] for b in _bd_json(trial, "list", "--all", "--limit", "0")}


def _export(trial: Trial, dest: Path) -> list[dict]:
    _bd_ok(trial, "export", "-o", str(dest))
    return [json.loads(line) for line in dest.read_text().splitlines() if line.strip()]


def _writing_phase(trial: Trial, test: AcceptanceTest, sessions: _Sessions) -> int:
    """One ornith session writes the roadmap from BRIEF.md; return how many beads it created.

    BRIEF.md is removed afterwards: bead sessions never see the brief, as in frontier."""
    brief = trial.project / "BRIEF.md"
    brief.write_text(test.prompt)
    with open(trial.project / ".git" / "info" / "exclude", "a") as f:
        f.write("\nBRIEF.md\n")
    try:
        sessions.run(test.roadmap_prompt, WRITING_LIMIT_S)
    finally:
        brief.unlink(missing_ok=True)
    try:
        return len(_export(trial, trial.dir / "roadmap.jsonl"))
    except (RuntimeError, ValueError, OSError):  # unreadable beads are no roadmap: the brief fallback applies
        return 0


def bead_loop(trial: Trial, sessions: _Sessions, out: RoadmapOutcome) -> None:
    """Work beads one fresh session at a time until all are closed, time is up, or sessions stall.

    Ready beads get a bead session, and a second if the first leaves them unclosed; then they are
    set blocked with a note. With nothing ready but beads unfinished, a stall session works them
    regardless of dependencies, and the loop goes back to `bd ready`, so no time is left unused."""
    failures: dict[str, int] = {}
    retry = None
    quick = 0
    while sessions.usable():
        before = _bead_states(trial)
        for bid in [b for b, st in before.items() if st == "in_progress"]:  # claimed by a finished session
            _bd_ok(trial, "update", bid, "--status", "open")
            before[bid] = "open"
        ready = [b["id"] for b in _bd_json(trial, "ready", "--limit", "0")]
        if ready:
            bead = retry if retry in ready else ready[0]
            prompt = BEAD_PROMPT.format(id=bead)
        elif any(st in ("open", "in_progress", "blocked") for st in before.values()):
            bead, prompt = None, STALL_PROMPT
        else:
            return  # every bead is closed
        if sessions.remaining() <= 0:
            return  # bd bookkeeping used the last of the time; no zero-length session
        out.sessions += 1
        out.stall_sessions += bead is None
        took = sessions.run(prompt)
        after = _bead_states(trial)
        quick = quick + 1 if took < QUICK_SESSION_S and after == before else 0
        retry = None
        if bead is not None and after.get(bead) != "closed" and not sessions.killed_at_deadline:
            failures[bead] = failures.get(bead, 0) + 1
            if failures[bead] >= 2:
                _bd_ok(trial, "update", bead, "--status", "blocked")
                _bd_ok(trial, "note", bead, f"harness: not closed after {failures[bead]} bead sessions; set blocked.")
            else:
                retry = bead
        if quick >= STALL_RUN:
            out.loop_stalled = True
            return


@dataclass
class AgentRun:
    timed_out: bool
    outcome: RoadmapOutcome | None  # roadmap trials only
    resumes: int = 0                # over all sessions
    dropped: SessionRun | None = None  # the session whose connection stayed dropped, if any


def run_agent(trial: Trial, test: AcceptanceTest, opencode_argv: list[str] | None,
              roadmap: str = "none") -> AgentRun:
    """Run the trial's agent session(s) within test.time_limit_s.

    none: one session with the brief, into transcript.jsonl (`opencode_argv` runs as given).
    frontier/ornith: ornith first writes the roadmap; then the bead loop. Timed out means the last
    session was killed at the deadline. Every session is resumed after a dropped model connection;
    a bead trial runs no further session once one stays dropped."""
    if roadmap == "none":
        argv = opencode_argv if opencode_argv is not None else opencode_command(test.prompt)
        run = run_session(trial, argv, trial.dir / "transcript.jsonl", trial.dir / "opencode.log",
                          test.time_limit_s)
        return AgentRun(not run.finished, None, run.resumes, run if run.drop else None)
    sessions = _Sessions(trial, opencode_argv, test.time_limit_s)
    out = RoadmapOutcome()
    try:
        if roadmap == "ornith" and _writing_phase(trial, test, sessions) == 0:
            out.roadmap_failed = True
            if sessions.usable():
                out.sessions += 1
                sessions.run(test.prompt)
        else:
            bead_loop(trial, sessions, out)
    except (RuntimeError, ValueError, OSError) as e:
        out.bd_error = str(e)
    try:  # also after a bd_error: whatever beads are readable still count
        final = _export(trial, trial.dir / "beads-final.jsonl")
    except (RuntimeError, ValueError, OSError) as e:
        final = []
        if out.bd_error is None:
            out.bd_error = str(e)
        else:
            out.export_error = str(e)
    out.beads = len(final)
    out.closed = sum(b.get("status") == "closed" for b in final)
    out.blocked = sum(b.get("status") == "blocked" for b in final)
    return AgentRun(sessions.killed_at_deadline, out, sessions.resumes, sessions.dropped)


def trial_denials(trial_dir: Path) -> int:
    """arc denials over every session's transcript."""
    return sum(count_denials(t) for t in sorted(Path(trial_dir).glob("transcript*.jsonl")))


def run_trial(test: AcceptanceTest, index_md: str, trial_dir: Path, mirrors: Path | None, proxy: Path | None,
              opencode_argv: list[str] | None = None, *, test_dir: Path | None = None,
              branch: str = STITCH_BRANCH, baseline: bool = False, cli: Path | None = None,
              arc: Path | None = None, roadmap: str = "none", pyindex: Path | None = None) -> TrialResult:
    """Set up the trial, run the agent sandboxed until done or time_limit_s, then check it sandboxed."""
    trial = prepare_trial(test, index_md, trial_dir, mirrors, proxy, cli, arc, roadmap=roadmap, pyindex=pyindex)
    run = run_agent(trial, test, opencode_argv, roadmap)
    test_dir = Path(test_dir) if test_dir is not None else REPO / "tests" / "acceptance" / test.name
    result = run_checker(trial, test, test_dir, branch, baseline)
    return _record_run(trial, result, run, arc is not None)


def _record_run(trial: Trial, result: TrialResult, run: AgentRun, arc: bool, *,
                tool_use_proxy: Path | None = None, count_tools: bool = False) -> TrialResult:
    """Put the agent run's outcome on the checker's result and write <trial>/checker.json."""
    result.resumes = run.resumes
    if result.reason is not None:
        pass  # the checker failed (infrastructure); that reason stands
    elif run.dropped:
        result.reason = (f"{INFRA_PREFIX}model connection dropped after {run.dropped.resumes} resumes: "
                         f"{run.dropped.drop[1]}")
    elif run.timed_out:
        result.reason = "timeout"
    if run.outcome is not None:
        result.roadmap = asdict(run.outcome)
    if arc:
        try:
            result.arc_denials = trial_denials(trial.dir)
        except Exception:  # noqa: BLE001 - a bad transcript must not lose the checker result
            result.arc_denials = None
        result.arc_hook_live = arc_hook_live(trial.project)
    if count_tools:
        try:
            result.tool_use = count_tool_use(sorted(trial.dir.glob("transcript*.jsonl")), tool_use_proxy)
        except Exception as e:  # noqa: BLE001
            result.tool_use = {"error": f"{type(e).__name__}: {e}"}
    (trial.dir / "checker.json").write_text(result.to_json())
    return result


def run_experiment_trial(test: AcceptanceTest, condition: str, trial_dir: Path, *, proxy: Path, catalog: Path,
                         cli: Path, arc: Path, opencode_argv: list[str] | None = None) -> TrialResult:
    """One experiment trial: prepare `condition`, run the bead loop on the frozen roadmap within
    test.time_limit_s, then check it sandboxed, the same way in every condition."""
    trial = prepare_experiment_trial(test, condition, trial_dir, proxy, catalog, cli, arc)
    run = run_agent(trial, test, opencode_argv, "frontier")
    try:
        result = run_checker(trial, test, test.dir, STITCH_BRANCH, False)
    except Exception as e:  # noqa: BLE001 - keep the (long) agent run's outcome on the result
        result = TrialResult(test.name, trial.dir.name, reason=f"{INFRA_PREFIX}checker: {str(e) or type(e).__name__}")
    return _record_run(trial, result, run, condition in ("arc", "both"), tool_use_proxy=proxy, count_tools=True)


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


def _git_out(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def standard_commit() -> str | None:
    """HEAD of the repo the harness runs from; '-dirty' suffix when the working tree has changes."""
    head = _git_out(REPO, "rev-parse", "HEAD")
    status = _git_out(REPO, "status", "--porcelain")
    if not head or status is None:
        return None
    return head + ("-dirty" if status else "")


def kit_commits(mirrors: Path, modules: list[str]) -> dict[str, str | None]:
    return {m: _git_out(mirrors / f"{m}.git", "rev-parse", "refs/heads/main") for m in modules}


def run_round(test_dir: Path, round_no: int, trials: int = 5, baseline: bool = False, *,
              results_root: Path | None = None, opencode_argv: list[str] | None = None,
              product: bool = False, arc: bool = False, arc_src: Path | None = None,
              roadmap: str = "none", time_limit_s: int | None = None) -> RoundResult:
    test_dir = Path(test_dir).resolve()
    test = load_acceptance(test_dir)
    if time_limit_s is not None:
        if time_limit_s <= 0:
            raise ValueError("--time-limit-s must be positive")
        test = replace(test, time_limit_s=time_limit_s)  # overrides test.yaml for this round only
    root = Path(results_root or RESULTS).resolve()
    mirrors = proxy = cli = arc_bin = pyindex = None
    if roadmap not in ROADMAPS:
        raise ValueError(f"--roadmap must be one of {', '.join(ROADMAPS)}")
    if roadmap != "none":
        if not (product and arc):
            raise ValueError(f"--roadmap {roadmap} needs --product and --arc")
        if roadmap == "ornith" and not test.roadmap_prompt:
            raise ValueError(f"--roadmap ornith needs roadmap_prompt in {test_dir / 'test.yaml'}")
        if roadmap == "frontier" and not (test_dir / "roadmaps" / "frontier.jsonl").is_file():
            raise ValueError(f"--roadmap frontier needs {test_dir / 'roadmaps' / 'frontier.jsonl'}")
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
        proxy = root / "goproxy" / test.name  # per test, so concurrent Go rounds do not clobber each other
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
        if test.ecosystem == "python":
            # per test, so rounds of different tests keep their own
            pyindex = build_python_index(mirrors, test, branch, root / "pyindex" / test.name)

    out = round_dir(root, test.name, round_no, baseline, roadmap)
    out.mkdir(parents=True, exist_ok=True)
    result = RoundResult(test.name, round_no, product=product, arc=arc, roadmap=roadmap,
                         time_limit_s=test.time_limit_s, standard_commit=standard_commit(),
                         kits=kit_commits(mirrors, test.modules) if mirrors is not None else {},
                         pyindex_wheels=sorted(w.name for w in pyindex.glob("*.whl")) if pyindex is not None else [])
    for k in range(1, trials + 1):
        tr = run_trial(test, index_md, out / f"trial-{k}", mirrors, proxy, opencode_argv,
                       test_dir=test_dir, branch=branch, baseline=baseline, cli=cli, arc=arc_bin,
                       roadmap=roadmap, pyindex=pyindex)
        result.results.append(tr)
        (out / "round.json").write_text(result.to_json())
    (out / "round.json").write_text(result.to_json())
    return result


def build_catalog(dest: Path) -> Path:
    """The experiment's `dir:` catalog at `dest` (replaced if present): a fresh copy of every Go and
    Python sample kit (a directory with a module.yaml)."""
    dest = Path(dest).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for eco in ("go", "python"):
        for d in sorted((REPO / "samples" / eco).iterdir()):
            if (d / "module.yaml").is_file():
                shutil.copytree(d, dest / d.name, symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".venv"))
    return dest


def run_experiment(test_dir: Path, round_no: int, trials: int = 3, conditions: list[str] | None = None, *,
                   results_root: Path | None = None, opencode_argv: list[str] | None = None,
                   arc_src: Path | None = None) -> dict[str, RoundResult]:
    """Run `trials` trials of each condition, interleaved (trial 1 of every condition, then trial 2, ...),
    into results/<test>/round-<N>-<condition>/trial-<k>/. Each condition's round.json is rewritten after
    each of its trials. An exception in one trial is recorded as that trial's infrastructure failure."""
    test_dir = Path(test_dir).resolve()
    test = load_acceptance(test_dir)
    if test.ecosystem != "go":
        raise ValueError(f"experiments are defined for Go tests only; {test.name} is {test.ecosystem}")
    if not test.conditions:
        raise ValueError(f"{test_dir / 'test.yaml'} lists no conditions")
    conditions = list(conditions) if conditions else list(test.conditions)
    bad = [c for c in conditions if c not in CONDITIONS or c not in test.conditions]
    if bad:
        raise ValueError(f"unknown conditions {', '.join(bad)}; {test.name} has {', '.join(test.conditions)}")
    if len(set(conditions)) != len(conditions):
        raise ValueError("each condition may be named once")
    if trials < 1:
        raise ValueError("--trials must be positive")
    if not (test_dir / "roadmaps" / "frontier.jsonl").is_file():
        raise ValueError(f"an experiment needs {test_dir / 'roadmaps' / 'frontier.jsonl'}")
    missing = [m for m in test.modules if m not in {d.name for d in _go_sample_dirs()}]
    if missing:
        raise RuntimeError(f"no Go sample module for: {', '.join(missing)}")
    root = Path(results_root or RESULTS).resolve()
    outs = {c: round_dir(root, test.name, round_no, False, c) for c in conditions}
    taken = [out / f"trial-{k}" for out in outs.values() for k in range(1, trials + 1) if (out / f"trial-{k}").exists()]
    if taken:
        raise FileExistsError(f"{taken[0]} already exists; use another --round or remove it")
    cli, arc = build_cli(root), build_arc(root, arc_src)
    proxy = root / "goproxy" / test.name
    if proxy.exists():
        shutil.rmtree(proxy)
    build_goproxy(_go_sample_dirs(), proxy)
    catalog = build_catalog(root / "go-catalog" / test.name)
    commit = standard_commit()
    rounds = {c: RoundResult(test.name, round_no, product=c in ("artifactory", "both"), arc=c in ("arc", "both"),
                             roadmap="frontier", time_limit_s=test.time_limit_s, standard_commit=commit, condition=c)
              for c in conditions}
    for out in outs.values():
        out.mkdir(parents=True, exist_ok=True)
    for k in range(1, trials + 1):
        for c in conditions:
            trial_dir = outs[c] / f"trial-{k}"
            try:
                tr = run_experiment_trial(test, c, trial_dir, proxy=proxy, catalog=catalog, cli=cli, arc=arc,
                                          opencode_argv=opencode_argv)
            except Exception as e:  # noqa: BLE001 - one trial's failure must not stop the others
                tr = TrialResult(test.name, trial_dir.name, reason=f"{INFRA_PREFIX}{str(e) or type(e).__name__}")
                if trial_dir.is_dir():
                    (trial_dir / "checker.json").write_text(tr.to_json())
            rounds[c].results.append(tr)
            (outs[c] / "round.json").write_text(rounds[c].to_json())
    return rounds


def build_python_index(mirrors: Path, test: AcceptanceTest, branch: str, dest: Path) -> Path:
    """A Python round's wheel index at `dest` (replaced if present): each kit built from `branch` of its
    mirror, plus the standard wheels and the test's python_wheels."""
    if dest.exists():
        shutil.rmtree(dest)
    with tempfile.TemporaryDirectory(prefix="pykits-") as tmp:
        build_pyindex(export_kits(mirrors, test.modules, branch, Path(tmp)), dest)
    download_wheels([*standard_wheels(), *test.python_wheels], dest)
    return dest


def export_kits(mirrors: Path, modules: list[str], branch: str, dest: Path) -> list[Path]:
    """Check out `branch` of each kit mirror into dest/<module> (no .git); return the directories."""
    dirs = []
    for m in modules:
        d = dest / m
        d.mkdir(parents=True)
        try:
            archive = subprocess.run(["git", "--git-dir", str(mirrors / f"{m}.git"), "archive",
                                      f"refs/heads/{branch}"], check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", str(d)], input=archive, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"cannot export kit {m} ({branch}) from {mirrors / (m + '.git')}: "
                               f"{e.stderr.decode(errors='replace').strip()}") from e
        dirs.append(d)
    return dirs


def round_dir(root: Path, test: str, round_no: int, baseline: bool, roadmap: str = "none") -> Path:
    """round-<N> for none (as before), round-<N>-<roadmap> for the bead conditions; experiments pass
    their condition as `roadmap` (round-<N>-<condition>)."""
    if baseline:
        return Path(root) / test / "baseline"
    return Path(root) / test / (f"round-{round_no}" if roadmap == "none" else f"round-{round_no}-{roadmap}")


def refresh_mirrors(root: Path | None = None, tests: list[Path] | None = None) -> list[Path]:
    """Bare mirrors of the given tests' kits (default: the Godot test's), with the user's ssh credentials.

    Runs outside any sandbox.
    """
    mirrors = Path(root or RESULTS).resolve() / "mirrors"
    mirrors.mkdir(parents=True, exist_ok=True)
    names = dict.fromkeys(name for test in (tests or [GODOT_TEST]) for name in load_acceptance(test).modules)
    done = []
    for name in names:
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
