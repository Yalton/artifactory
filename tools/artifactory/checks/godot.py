"""Grade a Godot C# acceptance-test trial project.

Everything runs on a copy of the project; the input is never modified. Static
checks (installed, unmodified, duplication) run on the pristine copy before the
probe is added and the project is built and run.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from artifactory.acceptance import AcceptanceTest
from artifactory.descriptor import DescriptorError, load_descriptor
from artifactory.checks.process import ANSI, Proc
from artifactory.checks.process import run as run_process
from artifactory.result import CheckResult, TrialResult

BUILD_TIMEOUT_S = 600
IMPORT_TIMEOUT_S = 180
RUN_TIMEOUT_S = 60

PROBE_SRC = Path(__file__).resolve().parent.parent / "godot_probe" / "CheckerProbe.cs"
PROBE_DIR = "artifactory_probe"
PROBE_AUTOLOAD = f'ArtifactoryCheckerProbe="*res://{PROBE_DIR}/CheckerProbe.cs"'

ERROR_LINE = re.compile(r"ERROR:|Unhandled exception")
ROOT_SKIP_DIRS = {".godot", "bin", "obj"}  # generated output, only at the project root
MAX_LISTED = 10

_baseline_errors: dict[Path, set[str]] = {}


_Proc = Proc


def check_godot(project: Path, test: AcceptanceTest, mirrors: Path, branch: str,
                baseline: bool = False) -> TrialResult:
    project = Path(project).resolve()
    mirrors = Path(mirrors).resolve()
    with tempfile.TemporaryDirectory(prefix="artifactory-godot-") as tmp:
        copy = Path(tmp) / "project"
        shutil.copytree(project, copy, symlinks=True)

        installed, installed_check = _check_installed(copy, test.modules)
        unmodified = _check_unmodified(copy, test.modules, installed, mirrors, branch)
        duplication = _check_duplication(copy, test)

        build, run = _build_and_run(copy, Path(tmp) / "logs")
        if run is None:
            runs = CheckResult("runs", False, "not run: build failed")
            moves = CheckResult("player_moves", False, "not run: build failed")
            output = ""
        else:
            runs = _check_runs(run, copy, _blank_errors(test.fixture))
            moves = _check_moves(run)
            output = run.output
        live = _check_live(copy, test.modules, output)

    if baseline:
        live = CheckResult("modules_live", False,
                           f"manual: judge kit wiring from the tree (automatic: {live.detail})")
        unmodified = CheckResult("modules_unmodified", False,
                                 f"manual: judge kit edits from the tree (automatic: {unmodified.detail})")

    checks = [build, runs, moves, installed_check, live, unmodified, duplication]
    return TrialResult(test=test.name, trial=project.name, checks=checks, reason=None)


# --- static checks ---------------------------------------------------------

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _submodule_paths(project: Path) -> set[str]:
    if not (project / ".gitmodules").is_file():
        return set()
    r = _git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$", cwd=project)
    paths = set()
    for line in r.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            paths.add(parts[1].strip().strip("/"))
    return paths


def _is_own_checkout(path: Path) -> bool:
    """True if `path` is the top of its own git checkout with a resolvable HEAD."""
    if not (path / ".git").exists():
        return False
    top = _git("rev-parse", "--show-toplevel", cwd=path)
    head = _git("rev-parse", "--verify", "HEAD", cwd=path)
    return top.returncode == 0 and head.returncode == 0 and Path(top.stdout.strip()).resolve() == path.resolve()


def _check_installed(project: Path, modules: list[str]) -> tuple[set[str], CheckResult]:
    registered = _submodule_paths(project)
    installed: set[str] = set()
    problems = []
    for name in modules:
        rel = f"addons/{name}"
        path = project / rel
        if rel in registered and path.is_dir() and _is_own_checkout(path):
            installed.add(name)
        elif rel in registered:
            problems.append(f"{name}: submodule in .gitmodules but not checked out at {rel}")
        elif path.exists():
            problems.append(f"{name}: copied, not submodule ({rel} has no .gitmodules entry)")
        else:
            problems.append(f"{name}: missing ({rel} not found)")
    if problems:
        return installed, CheckResult("modules_installed", False, "; ".join(problems))
    return installed, CheckResult("modules_installed", True, f"all {len(modules)} kits installed as submodules")


def _check_unmodified(project: Path, modules: list[str], installed: set[str], mirrors: Path,
                      branch: str) -> CheckResult:
    problems = []
    for name in modules:
        if name not in installed:
            problems.append(f"{name}: not installed")
            continue
        path = project / "addons" / name
        status = _git("status", "--porcelain", cwd=path)
        if status.returncode != 0:
            problems.append(f"{name}: git status failed: {status.stderr.strip()}")
            continue
        changes = status.stdout.splitlines()
        if changes:
            problems.append(f"{name}: dirty working tree ({len(changes)} changes, e.g. {changes[0].strip()})")
            continue
        head = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
        mirror = mirrors / f"{name}.git"
        if not mirror.is_dir():
            problems.append(f"{name}: no mirror at {mirror}")
            continue
        r = _git("merge-base", "--is-ancestor", head, f"refs/heads/{branch}", cwd=mirror)
        if r.returncode != 0:
            problems.append(f"{name}: commit {head[:10]} is not published on {branch}")
    if problems:
        return CheckResult("modules_unmodified", False, "; ".join(problems))
    return CheckResult("modules_unmodified", True, f"all kits clean and published on {branch}")


def _check_duplication(project: Path, test: AcceptanceTest) -> CheckResult:
    excluded = {f"addons/{name}" for name in test.modules}
    compiled = {name: [re.compile(p) for p in pats] for name, pats in test.duplication.items()}
    hits = []
    for file in sorted(_project_code_files(project, excluded)):
        rel = file.relative_to(project).as_posix()
        try:
            lines = file.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            for name, regexes in compiled.items():
                for rx in regexes:
                    if rx.search(line):
                        hits.append(f"{rel}:{lineno} matches {name} pattern {rx.pattern!r}")
    if hits:
        more = f" (+{len(hits) - MAX_LISTED} more)" if len(hits) > MAX_LISTED else ""
        return CheckResult("no_duplication", False, "; ".join(hits[:MAX_LISTED]) + more)
    return CheckResult("no_duplication", True, "no duplication patterns in project code")


def _project_code_files(project: Path, excluded: set[str]):
    for dirpath, dirnames, filenames in os.walk(project):
        rel_dir = Path(dirpath).relative_to(project).as_posix()
        dirnames[:] = [
            d for d in dirnames
            if d != ".git"
            and not (rel_dir == "." and d in ROOT_SKIP_DIRS)
            and (d if rel_dir == "." else f"{rel_dir}/{d}") not in excluded
        ]
        for f in filenames:
            if f.endswith((".cs", ".gd")) or f == "project.godot":
                yield Path(dirpath) / f


# --- build and run ---------------------------------------------------------

def _env() -> dict[str, str]:
    env = dict(os.environ)
    # Headless Godot still pops a zenity dialog for some errors when a display is set.
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"
    return env


def _run(cmd: list[str], cwd: Path, timeout: float, log: Path) -> _Proc:
    return run_process(cmd, cwd, timeout, log, env=_env())


def _project_setting(project: Path, section: str, key: str) -> str | None:
    current = None
    for line in (project / "project.godot").read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            current = s[1:-1]
        elif current == section and s.startswith(f"{key}="):
            return s.split("=", 1)[1].strip().strip('"')
    return None


def _find_csproj(project: Path) -> Path | None:
    assembly = _project_setting(project, "dotnet", "project/assembly_name")
    if assembly and (project / f"{assembly}.csproj").is_file():
        return project / f"{assembly}.csproj"
    found = sorted(project.glob("*.csproj"))
    return found[0] if len(found) == 1 else None


def _add_autoload(project: Path, entry: str) -> None:
    file = project / "project.godot"
    lines = file.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "[autoload]":
            lines.insert(i + 1, entry)
            break
    else:
        lines += ["", "[autoload]", "", entry]
    file.write_text("\n".join(lines) + "\n")


def _tail(text: str, n: int = 8) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return " | ".join(lines[-n:])


def _build_and_run(project: Path, logs: Path) -> tuple[CheckResult, _Proc | None]:
    """Build the copy with the probe compiled in, import, then run it headless."""
    if not (project / "project.godot").is_file():
        return CheckResult("build", False, "no project.godot"), None
    csproj = _find_csproj(project)
    if csproj is None:
        return CheckResult("build", False, "no unique .csproj matching [dotnet] project/assembly_name"), None
    (project / PROBE_DIR).mkdir(exist_ok=True)
    shutil.copy(PROBE_SRC, project / PROBE_DIR / "CheckerProbe.cs")

    b = _run(["dotnet", "build", csproj.name, "-nodeReuse:false"], project, BUILD_TIMEOUT_S, logs / "build.log")
    if b.timed_out:
        return CheckResult("build", False, f"dotnet build timed out after {BUILD_TIMEOUT_S}s"), None
    if b.code != 0:
        errors = [l.strip() for l in b.output.splitlines() if ": error " in l]
        detail = "; ".join(dict.fromkeys(errors[:MAX_LISTED])) or _tail(b.output)
        return CheckResult("build", False, f"dotnet build exit {b.code}: {detail}"), None
    build = CheckResult("build", True, f"dotnet build {csproj.name} succeeded in {b.seconds:.0f}s")

    _add_autoload(project, PROBE_AUTOLOAD)
    imp = _run(["godot", "--headless", "--import", "--path", str(project)], project, IMPORT_TIMEOUT_S,
               logs / "import.log")
    if imp.timed_out:
        return build, _Proc(None, f"godot --import timed out after {IMPORT_TIMEOUT_S}s\n" + imp.output, imp.seconds)
    run = _run(["godot", "--headless", "--path", str(project)], project, RUN_TIMEOUT_S, logs / "run.log")
    return build, run


def _error_lines(output: str, project: Path) -> set[str]:
    out = set()
    for line in output.splitlines():
        if ERROR_LINE.search(line):
            out.add(line.replace(str(project), "<project>").strip())
    return out


def _blank_errors(fixture: Path) -> set[str]:
    """Error lines a run of the blank fixture (plus probe) prints; these are not the trial's fault."""
    fixture = Path(fixture).resolve()
    if fixture not in _baseline_errors:
        with tempfile.TemporaryDirectory(prefix="artifactory-godot-blank-") as tmp:
            copy = Path(tmp) / "project"
            shutil.copytree(fixture, copy, symlinks=True)
            if _project_setting(copy, "application", "run/main_scene") is None:
                (copy / PROBE_DIR).mkdir(exist_ok=True)
                (copy / PROBE_DIR / "BlankMain.tscn").write_text(
                    '[gd_scene format=3]\n\n[node name="BlankMain" type="Node"]\n')
                _set_main_scene(copy, f"res://{PROBE_DIR}/BlankMain.tscn")
            build, run = _build_and_run(copy, Path(tmp) / "logs")
            if run is None or run.timed_out or run.code != 0:
                raise RuntimeError(f"blank fixture {fixture} does not build and run cleanly: "
                                   f"{build.detail}; {_tail(run.output) if run else ''}")
            _baseline_errors[fixture] = _error_lines(run.output, copy)
    return _baseline_errors[fixture]


def _set_main_scene(project: Path, scene: str) -> None:
    file = project / "project.godot"
    lines = file.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "[application]":
            lines.insert(i + 1, f'run/main_scene="{scene}"')
            break
    else:
        lines += ["", "[application]", "", f'run/main_scene="{scene}"']
    file.write_text("\n".join(lines) + "\n")


# --- runtime checks --------------------------------------------------------

def _check_runs(run: _Proc, project: Path, blank_errors: set[str]) -> CheckResult:
    if run.timed_out:
        return CheckResult("runs", False, f"timed out after {RUN_TIMEOUT_S}s: {_tail(run.output, 4)}")
    if run.code != 0:
        return CheckResult("runs", False, f"godot exit {run.code}: {_tail(run.output)}")
    new = sorted(_error_lines(run.output, project) - blank_errors)
    if new:
        more = f" (+{len(new) - MAX_LISTED} more)" if len(new) > MAX_LISTED else ""
        return CheckResult("runs", False, f"{len(new)} new error lines: " + " | ".join(new[:MAX_LISTED]) + more)
    return CheckResult("runs", True, f"exited 0 after {run.seconds:.1f}s with no new errors")


def _check_moves(run: _Proc) -> CheckResult:
    probe = [l.strip() for l in run.output.splitlines() if l.strip().startswith("PROBE ")]
    if not probe:
        return CheckResult("player_moves", False, "probe never reported (game did not run to 3 s)")
    line = probe[-1]
    return CheckResult("player_moves", "player_moves=true" in line.split(), line)


def _marker(project: Path, name: str) -> str:
    """The kit's liveness marker: its descriptor's `liveness`, else the profile default."""
    try:
        return load_descriptor(project / "addons" / name).liveness
    except DescriptorError:
        return f"[{name}] live"


def _check_live(project: Path, modules: list[str], output: str) -> CheckResult:
    missing = [name for name in modules if _marker(project, name) not in output]
    if missing:
        return CheckResult("modules_live", False,
                           "marker missing for " + ", ".join(f"{n} ({_marker(project, n)!r})" for n in missing))
    return CheckResult("modules_live", True, f"all {len(modules)} markers printed")
