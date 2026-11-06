"""Grade a Python acceptance-test trial project.

Everything runs on a copy of the project; the input is never modified. The
checker builds its own clean virtual environment from the project's pins, with
uv, offline, from the trial's wheel index only (no PyPI, a throwaway uv cache).
The spec is standard/profiles/python.md and standard/consumer/python.md.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

from artifactory.acceptance import AcceptanceTest
from artifactory.checks.duplication import check_duplication
from artifactory.checks.process import run
from artifactory.pyindex import SANDBOX_PYTHON, uv_binary
from artifactory.result import CheckResult, TrialResult

INSTALL_TIMEOUT_S = 300
TEST_TIMEOUT_S = 300
CMD_TIMEOUT_S = 120
STARTUP_TIMEOUT_S = 20
SETTLE_S = 0.5  # after /healthz answers, so output printed right after start reaches the log
STOP_TIMEOUT_S = 5
REQUEST_TIMEOUT_S = 5
MAX_LISTED = 10
# Directories that are never the project's own code.
SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "tests", "test"}
# Variables that would point the checker's tools or interpreters elsewhere.
_DROP_ENV = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX")


def check_python(project: Path, test: AcceptanceTest, index: Path) -> TrialResult:
    if not test.python_app:
        raise ValueError(f"{test.name}: test.yaml has no python_app (the module run as `python -m <app>`)")
    project = Path(project).resolve()
    index = Path(index).resolve()
    if not index.is_dir():
        raise FileNotFoundError(f"wheel index {index} does not exist")
    tmp = Path(tempfile.mkdtemp(prefix="artifactory-python-"))
    try:
        copy = tmp / "project"
        shutil.copytree(project, copy, symlinks=True)
        logs = tmp / "logs"
        env = child_env(tmp)
        venv = tmp / "venv"

        pinned = _check_pinned(copy, test.modules)
        duplication = check_duplication(copy, _project_code_files(copy), test.duplication)
        install = _check_install(copy, venv, index, env, logs, tmp)
        if install.passed:
            python = venv / "bin" / "python"
            pip_check = _check_pip(python, copy, env, logs)
            tests = _check_tests(python, copy, env, logs)
            app, log_text = _check_app(python, copy, test, env, logs)
            live = _check_live(log_text, test.modules)
            traceback = _check_traceback(log_text)
            installed = _check_installed(venv, test.modules)
            unmodified = _check_unmodified(python, copy, venv, test.modules, env, logs)
        else:
            skipped = "not run: install failed"
            pip_check, tests, app, live, traceback, installed, unmodified = (
                CheckResult(name, False, skipped)
                for name in ("pip_check", "tests", "app_starts", "modules_live", "no_traceback",
                             "modules_installed", "modules_unmodified"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    checks = [install, pinned, pip_check, tests, app, installed, live, unmodified, traceback, duplication]
    return TrialResult(test=test.name, trial=project.name, checks=checks, reason=None)


def child_env(root: Path) -> dict[str, str]:
    """Environment for uv, the venv's python and the app: offline, no inherited interpreter settings,
    a private uv cache under `root` (so nothing comes from a cache the index does not hold)."""
    env = {k: v for k, v in os.environ.items()
           if k not in _DROP_ENV and not k.startswith(("UV_", "PIP_"))}
    env.update({
        "UV_CACHE_DIR": str(root / "uv-cache"),
        "UV_NO_CONFIG": "1",  # no uv.toml or [tool.uv] from the project redirecting the index
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _tail(text: str, n: int = 8) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return " | ".join(lines[-n:])


def _listed(problems: list[str]) -> str:
    more = f" (+{len(problems) - MAX_LISTED} more)" if len(problems) > MAX_LISTED else ""
    return "; ".join(problems[:MAX_LISTED]) + more


# --- static checks ---------------------------------------------------------

_REQ_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXACT_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*===?\s*[^\s;,*]+\s*(;.*)?$")


def _check_pinned(project: Path, modules: list[str]) -> CheckResult:
    """Each module pinned as `<name>==<version>` in requirements.txt, or locked from the index in uv.lock."""
    reqs, lock = project / "requirements.txt", project / "uv.lock"
    problems = []
    if reqs.is_file():
        lines = [l.split(" #")[0].strip() for l in reqs.read_text(errors="replace").splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
        for m in modules:
            if any((p := _EXACT_PIN.match(l)) and normalize(p.group(1)) == normalize(m) for l in lines):
                continue
            named = [l for l in lines if (n := _REQ_NAME.match(l)) and normalize(n.group(1)) == normalize(m)]
            problems.append(f"{m}: {named[0]!r} is not an exact == pin" if named
                            else f"{m}: no {m}==<version> line in requirements.txt")
        where = "requirements.txt"
    elif lock.is_file() and (project / "pyproject.toml").is_file():
        try:
            packages = tomllib.loads(lock.read_text(errors="replace")).get("package", [])
        except tomllib.TOMLDecodeError as e:
            return CheckResult("modules_pinned", False, f"uv.lock does not parse: {e}")
        by_name = {normalize(p.get("name", "")): p for p in packages if isinstance(p, dict)}
        for m in modules:
            p = by_name.get(normalize(m))
            source = p.get("source", {}) if p else {}
            if p is None:
                problems.append(f"{m}: not in uv.lock")
            elif "registry" not in source:
                problems.append(f"{m}: uv.lock takes it from {', '.join(source) or 'no source'}, not the index")
        where = "uv.lock"
    else:
        return CheckResult("modules_pinned", False, "no requirements.txt, and no uv.lock with pyproject.toml")
    if problems:
        return CheckResult("modules_pinned", False, _listed(problems))
    return CheckResult("modules_pinned", True, f"all {len(modules)} modules pinned in {where}")


def _project_code_files(project: Path):
    """The project's own non-test .py files: no virtual environments, dot directories or tests."""
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS
                       and not (Path(dirpath) / d / "pyvenv.cfg").exists()]
        for f in filenames:
            if f.endswith(".py") and not (f.startswith("test_") or f.endswith("_test.py") or f == "conftest.py"):
                yield Path(dirpath) / f


# --- environment, pip check, tests ------------------------------------------

def _check_install(project: Path, venv: Path, index: Path, env: dict, logs: Path, tmp: Path) -> CheckResult:
    uv = str(uv_binary())
    if (project / "requirements.txt").is_file():
        source, reqs = "requirements.txt", ["-r", "requirements.txt"]
    elif (project / "uv.lock").is_file() and (project / "pyproject.toml").is_file():
        locked = tmp / "uv-lock-requirements.txt"
        e = run([uv, "export", "--frozen", "--no-hashes", "--no-emit-project", "--no-header", "--quiet",
                 "-o", str(locked)], project, CMD_TIMEOUT_S, logs / "export.log", env)
        if e.code != 0:
            return CheckResult("install", False, f"uv export --frozen failed: {_tail(e.output)}")
        source, reqs = "uv.lock", ["-r", str(locked)]
    else:
        return CheckResult("install", False, "nothing to install from: no requirements.txt, "
                                             "and no uv.lock with pyproject.toml")
    if _is_package(project):
        reqs.append(".")
    v = run([uv, "venv", "--quiet", "--python", SANDBOX_PYTHON, str(venv)], project, CMD_TIMEOUT_S,
            logs / "venv.log", env)
    if v.code != 0:
        return CheckResult("install", False, f"uv venv failed: {_tail(v.output)}")
    i = run([uv, "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"),
             "--no-index", "--find-links", str(index), *reqs, "pytest"],
            project, INSTALL_TIMEOUT_S, logs / "install.log", env)
    if i.timed_out:
        return CheckResult("install", False, f"uv pip install timed out after {INSTALL_TIMEOUT_S}s")
    if i.code != 0:
        return CheckResult("install", False, f"uv pip install from {source} failed: {_tail(i.output)}")
    return CheckResult("install", True, f"clean venv from {source} installed offline from the wheel index")


def _is_package(project: Path) -> bool:
    """The project is itself installable: a pyproject.toml with a [build-system], not marked `package = false`
    (a plain `uv init` app has no build-system; installing it would need setuptools, which the index lacks)."""
    try:
        cfg = tomllib.loads((project / "pyproject.toml").read_text(errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return "build-system" in cfg and cfg.get("tool", {}).get("uv", {}).get("package", True) is not False


def _check_pip(python: Path, project: Path, env: dict, logs: Path) -> CheckResult:
    r = run([str(uv_binary()), "pip", "check", "--python", str(python)], project, CMD_TIMEOUT_S,
            logs / "check.log", env)
    if r.code != 0:
        return CheckResult("pip_check", False, f"uv pip check exit {r.code}: {_tail(r.output)}")
    return CheckResult("pip_check", True, "uv pip check found no conflicts")


def _check_tests(python: Path, project: Path, env: dict, logs: Path) -> CheckResult:
    t = run([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"], project, TEST_TIMEOUT_S,
            logs / "test.log", env)
    if t.timed_out:
        return CheckResult("tests", False, f"pytest timed out after {TEST_TIMEOUT_S}s")
    if t.code == 5:
        return CheckResult("tests", False, "pytest collected no tests")
    if t.code != 0:
        return CheckResult("tests", False, f"pytest exit {t.code}: {_tail(t.output)}")
    return CheckResult("tests", True, f"pytest passed: {_tail(t.output, 1)}")


# --- the running app ---------------------------------------------------------

def _health(port: int) -> int | str:
    """Status of GET /healthz on 127.0.0.1 or ::1, or why neither answered."""
    why = "no answer"
    for host in ("127.0.0.1", "::1"):
        conn = http.client.HTTPConnection(host, port, timeout=REQUEST_TIMEOUT_S)
        try:
            conn.request("GET", "/healthz")
            return conn.getresponse().status
        except (OSError, http.client.HTTPException) as e:
            why = f"{type(e).__name__}: {e}"
        finally:
            conn.close()
    return why


def _port_open(port: int) -> bool:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as s:
                s.settimeout(1)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def _stop(proc: subprocess.Popen) -> None:
    """SIGTERM (Python dies quietly, no traceback), then SIGKILL the whole group."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=STOP_TIMEOUT_S)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _check_app(python: Path, project: Path, test: AcceptanceTest, env: dict,
               logs: Path) -> tuple[CheckResult, str | None]:
    """Start `python -m <app>`, wait for /healthz to answer 200, stop it. Returns the result and the app log."""
    port, app = test.app_port, test.python_app
    if _port_open(port):
        return CheckResult("app_starts", False, f"port {port} was already in use before the app started"), None
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "app.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen([str(python), "-m", app], cwd=project, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env={**env, "PYTHONUNBUFFERED": "1", "PORT": str(port)})
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        last: int | str = "no answer"
        while time.monotonic() < deadline and proc.poll() is None:
            last = _health(port)
            if last == 200:
                time.sleep(SETTLE_S)
                break
            time.sleep(0.2)
        code = proc.poll()
    finally:
        _stop(proc)
    text = log.read_text(errors="replace")
    if last == 200:
        return CheckResult("app_starts", True, f"python -m {app} started; GET /healthz returned 200"), text
    if code is not None:
        return CheckResult("app_starts", False, f"python -m {app} exited {code} before /healthz answered 200: "
                                                f"{_tail(text, 4)}"), text
    return CheckResult("app_starts", False, f"no 200 from /healthz on port {port} within {STARTUP_TIMEOUT_S}s "
                                            f"(last: {last}): {_tail(text, 4)}"), text


def _check_live(log: str | None, modules: list[str]) -> CheckResult:
    if log is None:
        return CheckResult("modules_live", False, "not run: the app did not start")
    lines = [l.rstrip("\r") for l in log.splitlines()]
    problems = []
    for m in modules:
        n = lines.count(f"[{m}] live")
        if n != 1:
            problems.append(f"[{m}] live printed {n} times, want 1")
    if problems:
        return CheckResult("modules_live", False, "; ".join(problems))
    return CheckResult("modules_live", True, f"each of {len(modules)} markers printed once by the app")


def _check_traceback(log: str | None) -> CheckResult:
    if log is None:
        return CheckResult("no_traceback", False, "not run: the app did not start")
    lines = log.splitlines()
    at = next((i for i, l in enumerate(lines) if "Traceback" in l), None)
    if at is None:
        return CheckResult("no_traceback", True, "no Traceback in the app log")
    # The exception line ends the block: the first unindented line after the header.
    end = next((l for l in lines[at + 1:] if l and not l[0].isspace()), "")
    return CheckResult("no_traceback", False, f"Traceback in the app log: {end or lines[at]}")


# --- installed from the index, unmodified --------------------------------------

def _site_packages(venv: Path) -> Path | None:
    found = sorted(venv.glob("lib/python*/site-packages"))
    return found[0] if found else None


def _find_dist(site: Path, module: str) -> Path | None:
    """The module's .dist-info directory in `site`, by the Name in METADATA."""
    for d in sorted(site.glob("*.dist-info")):
        try:
            meta = (d / "METADATA").read_text(errors="replace")
        except OSError:
            continue
        name = re.search(r"^Name:\s*(\S+)", meta, re.M)
        if name and normalize(name.group(1)) == normalize(module):
            return d
    return None


def _check_installed(venv: Path, modules: list[str]) -> CheckResult:
    site = _site_packages(venv)
    problems = []
    for m in modules:
        dist = _find_dist(site, m) if site else None
        if dist is None:
            problems.append(f"{m}: not installed")
            continue
        direct = dist / "direct_url.json"
        if direct.exists():
            try:
                info = json.loads(direct.read_text())
            except ValueError:
                info = {}
            dir_info = info.get("dir_info") if isinstance(info, dict) else None
            url = info.get("url", "?") if isinstance(info, dict) else "?"
            kind = ("an editable install" if isinstance(dir_info, dict) and dir_info.get("editable")
                    else "a local directory install" if dir_info is not None else "a direct URL install")
            problems.append(f"{m}: {kind} from {url}, not from the wheel index")
    if problems:
        return CheckResult("modules_installed", False, _listed(problems))
    return CheckResult("modules_installed", True, f"all {len(modules)} modules installed from the wheel index")


def _record_problems(site: Path, dist: Path) -> list[str]:
    """Files under `site` that differ from, or are missing against, the hashes in `dist`/RECORD.

    RECORD is read directly: importlib.metadata (3.12+) drops files that no longer exist."""
    try:
        rows = list(csv.reader((dist / "RECORD").read_text(errors="replace").splitlines()))
    except OSError:
        return [f"{dist.name}/RECORD is missing"]
    problems = []
    for row in rows:
        if len(row) < 2 or not row[1]:
            continue  # RECORD itself, compiled files
        algo, _, want = row[1].partition("=")
        path = site / row[0]
        try:
            digest = hashlib.new(algo, path.read_bytes()).digest()
        except FileNotFoundError:
            problems.append(f"{row[0]} missing")
            continue
        except (OSError, ValueError) as e:
            problems.append(f"{row[0]} unreadable ({type(e).__name__})")
            continue
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != want:
            problems.append(f"{row[0]} modified")
    return problems


def _import_names(dist: Path) -> list[str]:
    """Top-level importable names a distribution installs, from its RECORD."""
    try:
        rows = csv.reader((dist / "RECORD").read_text(errors="replace").splitlines())
    except OSError:
        return []
    names = set()
    for row in rows:
        if not row:
            continue
        parts = row[0].split("/")
        top = parts[0]
        if top in ("..", "__pycache__") or top.endswith((".dist-info", ".data")):
            continue
        if len(parts) > 1 or top.endswith(".py"):
            names.add(top.removesuffix(".py"))
    return sorted(n for n in names if n.isidentifier())


_FIND_SPECS = """\
import importlib.util, json, sys
out = {}
for name in sys.argv[1:]:
    try:
        spec = importlib.util.find_spec(name)
    except Exception as e:
        out[name] = None
        continue
    if spec is None:
        out[name] = None
    else:
        out[name] = spec.origin or next(iter(spec.submodule_search_locations or []), None)
print(json.dumps(out))
"""


def _shadowed(python: Path, project: Path, site: Path, names: list[str], env: dict, logs: Path) -> list[str]:
    """Names that, imported from the project directory (as `python -m <app>` does), resolve outside `site`."""
    if not names:
        return []
    r = run([str(python), "-c", _FIND_SPECS, *names], project, CMD_TIMEOUT_S, logs / "find-spec.log", env)
    try:
        origins = json.loads(r.output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [f"could not locate {', '.join(names)}: {_tail(r.output, 2)}"]
    problems = []
    site = site.resolve()
    for name, origin in origins.items():
        if origin and not Path(origin).resolve().is_relative_to(site):
            where = Path(origin).resolve()
            shown = where.relative_to(project) if where.is_relative_to(project) else where
            problems.append(f"import {name} resolves to {shown}, not the installed module")
    return problems


def _check_unmodified(python: Path, project: Path, venv: Path, modules: list[str], env: dict,
                      logs: Path) -> CheckResult:
    """After tests and app ran: each module's files match RECORD in the checker's venv and in the project's
    own .venv (if any), and the project does not shadow a module's import with its own copy."""
    problems = []
    envs = [("checker venv", venv)]
    if (project / ".venv").is_dir():
        envs.append(("project .venv", project / ".venv"))
    for label, root in envs:
        site = _site_packages(root)
        if site is None:
            continue
        for m in modules:
            dist = _find_dist(site, m)
            if dist is None:
                continue  # modules_installed reports a module missing from the checker venv
            problems += [f"{m} ({label}): {p}" for p in _record_problems(site, dist)]
            if root == venv:
                problems += [f"{m}: {p}" for p in _shadowed(python, project, site, _import_names(dist), env, logs)]
    if problems:
        return CheckResult("modules_unmodified", False, _listed(problems))
    where = " and the project .venv" if len(envs) > 1 else ""
    return CheckResult("modules_unmodified", True, f"module files match RECORD in the checker venv{where}; "
                                                   "no module shadowed by project code")
