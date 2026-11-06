"""Grade a Go acceptance-test trial project.

Everything runs on a copy of the project; the input is never modified. Modules
come from a local file GOPROXY, into a throwaway module cache.
"""
from __future__ import annotations

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
import urllib.error
import urllib.request
from pathlib import Path

from artifactory.acceptance import AcceptanceTest
from artifactory.checks.duplication import check_duplication
from artifactory.checks.process import run
from artifactory.result import CheckResult, TrialResult

MODULE_PREFIX = "repo.billbert.co/artifactory"
BUILD_TIMEOUT_S = 300
TEST_TIMEOUT_S = 300
CMD_TIMEOUT_S = 120
STARTUP_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 5
MAIN_PKG = "./cmd/shortener"


def check_go(project: Path, test: AcceptanceTest, proxy: Path) -> TrialResult:
    project = Path(project).resolve()
    proxy = Path(proxy).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="artifactory-go-"))
    try:
        copy = tmp / "project"
        shutil.copytree(project, copy, symlinks=True)
        env = go_env(proxy, tmp)
        logs = tmp / "logs"

        installed = _check_installed(copy, test.modules)
        unmodified = _check_unmodified(copy, env, logs)
        duplication = _check_duplication(copy, test)

        binary = tmp / "shortener"
        build = _check_build(copy, env, binary, logs)
        tests = _check_tests(copy, env, logs)
        if build.passed:
            service = _check_service(binary, copy, tmp, logs)
        else:
            service = CheckResult("service_works", False, "not run: build failed")
        live = _check_live(copy, env, test.modules, logs)
    finally:
        _rmtree(tmp)
    checks = [build, tests, service, installed, live, unmodified, duplication]
    return TrialResult(test=test.name, trial=project.name, checks=checks, reason=None)


def go_env(proxy: Path, root: Path) -> dict[str, str]:
    """Environment for every go command: local proxy, private module cache under `root`."""
    env = dict(os.environ)
    for k in ("GOPRIVATE", "GONOPROXY", "GOINSECURE", "GOFLAGS"):
        env.pop(k, None)
    env.update({
        "GOPROXY": f"file://{proxy}",
        "GONOSUMDB": MODULE_PREFIX,
        "GOFLAGS": "-mod=mod",
        "GOMODCACHE": str(root / "modcache"),
        "GOPATH": str(root / "gopath"),
        "GOTOOLCHAIN": "local",
        "GOWORK": "off",
    })
    return env


def _rmtree(path: Path) -> None:
    """Go makes module-cache files read-only; restore write bits first."""
    for dirpath, dirnames, _ in os.walk(path):
        os.chmod(dirpath, 0o755)
        for d in dirnames:
            p = os.path.join(dirpath, d)
            if not os.path.islink(p):
                os.chmod(p, 0o755)
    shutil.rmtree(path, ignore_errors=True)


def _tail(text: str, n: int = 8) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return " | ".join(lines[-n:])


# --- static checks ---------------------------------------------------------

def _check_installed(project: Path, modules: list[str]) -> CheckResult:
    gomod = project / "go.mod"
    text = gomod.read_text(errors="replace") if gomod.is_file() else ""
    required = set(re.findall(r"^\s*(?:require\s+)?(\S+)\s+v\d\S*", text, re.M))
    missing = [m for m in modules if f"{MODULE_PREFIX}/{m}" not in required]
    if missing:
        return CheckResult("modules_installed", False, "not in go.mod: " + ", ".join(missing))
    return CheckResult("modules_installed", True, f"all {len(modules)} modules required in go.mod")


def _check_unmodified(project: Path, env: dict, logs: Path) -> CheckResult:
    if (project / "vendor").exists():
        return CheckResult("modules_unmodified", False, "project vendors modules (vendor/)")
    if (project / "go.work").exists():
        return CheckResult("modules_unmodified", False, "project has a go.work file; modules could be replaced locally")
    gomod = project / "go.mod"
    text = gomod.read_text(errors="replace") if gomod.is_file() else ""
    if re.search(r"^\s*replace\b", text, re.M):
        return CheckResult("modules_unmodified", False, "go.mod has a replace directive")
    dl = run(["go", "mod", "download"], project, CMD_TIMEOUT_S, logs / "download.log", env)
    if dl.code != 0:
        return CheckResult("modules_unmodified", False, f"go mod download failed: {_tail(dl.output)}")
    v = run(["go", "mod", "verify"], project, CMD_TIMEOUT_S, logs / "verify.log", env)
    if v.code != 0:
        return CheckResult("modules_unmodified", False, f"go mod verify failed: {_tail(v.output)}")
    return CheckResult("modules_unmodified", True, "no replace directives; go mod verify passed")


def _check_duplication(project: Path, test: AcceptanceTest) -> CheckResult:
    return check_duplication(project, _project_code_files(project), test.duplication)


def _project_code_files(project: Path):
    """Non-test .go files. Installed modules live in the module cache, not the project."""
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d != "vendor" and not d.startswith(".")]
        for f in filenames:
            if f.endswith(".go") and not f.endswith("_test.go"):
                yield Path(dirpath) / f


# --- build, tests, liveness ------------------------------------------------

def _check_build(project: Path, env: dict, binary: Path, logs: Path) -> CheckResult:
    b = run(["go", "build", "-o", str(binary), MAIN_PKG], project, BUILD_TIMEOUT_S, logs / "build.log", env)
    if b.timed_out:
        return CheckResult("build", False, f"go build timed out after {BUILD_TIMEOUT_S}s")
    if b.code != 0:
        return CheckResult("build", False, f"go build exit {b.code}: {_tail(b.output)}")
    return CheckResult("build", True, f"go build {MAIN_PKG} succeeded in {b.seconds:.0f}s")


def _check_tests(project: Path, env: dict, logs: Path) -> CheckResult:
    t = run(["go", "test", "./..."], project, TEST_TIMEOUT_S, logs / "test.log", env)
    if t.timed_out:
        return CheckResult("tests", False, f"go test timed out after {TEST_TIMEOUT_S}s")
    if t.code != 0:
        return CheckResult("tests", False, f"go test exit {t.code}: {_tail(t.output)}")
    return CheckResult("tests", True, "go test ./... passed")


def _check_live(project: Path, env: dict, modules: list[str], logs: Path) -> CheckResult:
    r = run(["go", "list", "-deps", MAIN_PKG], project, CMD_TIMEOUT_S, logs / "list.log", env)
    if r.code != 0:
        return CheckResult("modules_live", False, f"go list -deps {MAIN_PKG} failed: {_tail(r.output)}")
    pkgs = r.output.split()
    missing = [m for m in modules
               if not any(p == f"{MODULE_PREFIX}/{m}" or p.startswith(f"{MODULE_PREFIX}/{m}/") for p in pkgs)]
    if missing:
        return CheckResult("modules_live", False, f"not in go list -deps {MAIN_PKG}: " + ", ".join(missing))
    return CheckResult("modules_live", True, f"all {len(modules)} modules in go list -deps {MAIN_PKG}")


# --- service check ---------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=REQUEST_TIMEOUT_S) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_NET_ERRORS = (urllib.error.URLError, OSError, ValueError, http.client.HTTPException)


def _start(binary: Path, project: Path, env: dict, log: Path) -> subprocess.Popen:
    with open(log, "ab") as out:
        return subprocess.Popen([str(binary)], cwd=project, env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _not_healthy(proc: subprocess.Popen, base: str, log: Path) -> str | None:
    if _wait_healthy(proc, base):
        return None
    code = proc.poll()
    why = f"exited {code}" if code is not None else f"no /healthz within {STARTUP_TIMEOUT_S}s"
    return f"{why}: {_tail(log.read_text(errors='replace'), 4)}"


def _check_service(binary: Path, project: Path, tmp: Path, logs: Path) -> CheckResult:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    data_dir = tmp / "data"
    data_dir.mkdir()
    env = dict(os.environ)
    env["SHORTENER_ADDR"] = f"127.0.0.1:{port}"
    env["SHORTENER_DATA"] = str(data_dir / "links.json")  # does not exist yet
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "service.log"
    proc = _start(binary, project, env, log)
    try:
        bad = _not_healthy(proc, base, log)
        if bad:
            return CheckResult("service_works", False, bad)
        problem, code, target = _exercise(base)
        if problem:
            return CheckResult("service_works", False, problem)
        _kill(proc)
        proc = _start(binary, project, env, log)
        bad = _not_healthy(proc, base, log)
        if bad:
            return CheckResult("service_works", False, f"restart failed: {bad}")
        status, headers, _ = _request("GET", f"{base}/{code}")
        location = next((v for k, v in headers.items() if k.lower() == "location"), None)
        if status != 302 or location != target:
            return CheckResult("service_works", False,
                               f"link lost after restart: GET /{code} returned {status}, Location {location!r}")
        return CheckResult("service_works", True,
                           "create, redirect, 404 and healthz work; link survives restart")
    except _NET_ERRORS as e:
        return CheckResult("service_works", False, f"malformed or failed response: {type(e).__name__}: {e}")
    finally:
        _kill(proc)


def _wait_healthy(proc: subprocess.Popen, base: str) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            if _request("GET", base + "/healthz")[0] == 200:
                return True
        except _NET_ERRORS:
            pass
        time.sleep(0.1)
    return False


def _exercise(base: str) -> tuple[str | None, str, str]:
    """Return (first contract violation or None, created code, target url)."""
    target = "https://example.com/some/long/path?x=1"
    fail = lambda msg: (msg, "", target)  # noqa: E731
    status, _, body = _request("POST", base + "/links", {"url": target})
    if status != 201:
        return fail(f"POST /links returned {status}, want 201")
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    code = parsed.get("code") if isinstance(parsed, dict) else None
    if not isinstance(code, str) or not code or "/" in code:
        return fail(f"POST /links body {body[:100]!r} is not a JSON object with a usable code")
    status, headers, _ = _request("GET", f"{base}/{code}")
    if status != 302:
        return fail(f"GET /{code} returned {status}, want 302")
    location = next((v for k, v in headers.items() if k.lower() == "location"), None)
    if location != target:
        return fail(f"GET /{code} Location is {location!r}, want {target!r}")
    status, _, _ = _request("GET", f"{base}/doesnotexist")
    if status != 404:
        return fail(f"GET unknown code returned {status}, want 404")
    status, _, _ = _request("GET", base + "/healthz")
    if status != 200:
        return fail(f"GET /healthz returned {status}, want 200")
    return None, code, target
