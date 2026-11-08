"""Grade a Go acceptance-test trial project.

Everything runs on a copy of the project; the input is never modified. Modules
come from a local file GOPROXY, into a throwaway module cache.
"""
from __future__ import annotations

import dataclasses
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
from artifactory.checks.consistency import check_consistency
from artifactory.checks.duplication import check_duplication
from artifactory.checks.process import run
from artifactory.result import CheckResult, TrialResult

MODULE_PREFIX = "repo.billbert.co/artifactory"
BUILD_TIMEOUT_S = 300
TEST_TIMEOUT_S = 300
CMD_TIMEOUT_S = 120
STARTUP_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 5
ARC_GATE_TIMEOUT_S = 180
SIGTERM_EXIT_S = 5
ADMIN_TOKEN = "secret-token"
LINKS_BEADS = ("bead1_skeleton", "bead2_links", "bead3_expiry_stats", "bead4_delete")


def check_go(project: Path, test: AcceptanceTest, proxy: Path, *, arc_registry: Path | None = None,
             arc_base: str | None = None) -> TrialResult:
    """Grade `project`. The main package is test.main_pkg; test.service picks the service contract
    ("shortener": one service_works check; "links": one check per bead), and test.kit_checks "report"
    makes the kit checks (installed, live, duplication) informational. With arc_registry and arc_base,
    also report arc_gate (boundary findings only, informational)."""
    project = Path(project).resolve()
    proxy = Path(proxy).resolve()
    main_pkg = test.main_pkg
    report = test.kit_checks == "report"
    links = test.service == "links"
    tmp = Path(tempfile.mkdtemp(prefix="artifactory-go-"))
    try:
        copy = tmp / "project"
        shutil.copytree(project, copy, symlinks=True)
        env = go_env(proxy, tmp)
        logs = tmp / "logs"

        installed = _check_installed(copy, test.modules)
        unmodified = _check_unmodified(copy, env, logs)

        binary = tmp / (Path(main_pkg).name or "service")
        build = _check_build(copy, env, binary, logs, main_pkg)
        tests = _check_tests(copy, env, logs)
        if links:
            service = (_check_links(binary, copy, tmp, logs) if build.passed
                       else [CheckResult(n, False, "not run: build failed") for n in LINKS_BEADS])
        elif build.passed:
            service = [_check_service(binary, copy, tmp, logs)]
        else:
            service = [CheckResult("service_works", False, "not run: build failed")]
        live, live_kits = _check_live(copy, env, test.modules, logs, main_pkg, report)
        if report:
            duplication = check_duplication(copy, _project_code_files(copy),
                                            {k: v for k, v in test.duplication.items() if k not in live_kits})
        else:
            duplication = _check_duplication(copy, test)
        consistency = check_consistency(copy, env) if links else []
        gate = check_arc_gate(copy, Path(arc_registry), arc_base, env) if arc_registry and arc_base else None
    finally:
        _rmtree(tmp)
    if report:
        installed, live, duplication = (dataclasses.replace(c, gating=False) for c in (installed, live, duplication))
    checks = [build, tests, *service, installed, live, unmodified, duplication, *consistency]
    if gate is not None:
        checks.append(gate)
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

def _check_build(project: Path, env: dict, binary: Path, logs: Path, main_pkg: str) -> CheckResult:
    b = run(["go", "build", "-o", str(binary), main_pkg], project, BUILD_TIMEOUT_S, logs / "build.log", env)
    if b.timed_out:
        return CheckResult("build", False, f"go build timed out after {BUILD_TIMEOUT_S}s")
    if b.code != 0:
        return CheckResult("build", False, f"go build exit {b.code}: {_tail(b.output)}")
    return CheckResult("build", True, f"go build {main_pkg} succeeded in {b.seconds:.0f}s")


def _check_tests(project: Path, env: dict, logs: Path) -> CheckResult:
    t = run(["go", "test", "./..."], project, TEST_TIMEOUT_S, logs / "test.log", env)
    if t.timed_out:
        return CheckResult("tests", False, f"go test timed out after {TEST_TIMEOUT_S}s")
    if t.code != 0:
        return CheckResult("tests", False, f"go test exit {t.code}: {_tail(t.output)}")
    return CheckResult("tests", True, "go test ./... passed")


def _check_live(project: Path, env: dict, modules: list[str], logs: Path, main_pkg: str,
                report: bool = False) -> tuple[CheckResult, set[str]]:
    """modules_live and the set of live kits. `report` words the detail as live/not live lists."""
    r = run(["go", "list", "-deps", main_pkg], project, CMD_TIMEOUT_S, logs / "list.log", env)
    if r.code != 0:
        return CheckResult("modules_live", False, f"go list -deps {main_pkg} failed: {_tail(r.output)}"), set()
    pkgs = r.output.split()
    live = [m for m in modules
            if any(p == f"{MODULE_PREFIX}/{m}" or p.startswith(f"{MODULE_PREFIX}/{m}/") for p in pkgs)]
    missing = [m for m in modules if m not in live]
    if report:
        detail = f"live: {', '.join(live) or 'none'}; not live: {', '.join(missing) or 'none'}"
        return CheckResult("modules_live", not missing, detail), set(live)
    if missing:
        return CheckResult("modules_live", False, f"not in go list -deps {main_pkg}: " + ", ".join(missing)), set(live)
    return CheckResult("modules_live", True, f"all {len(modules)} modules in go list -deps {main_pkg}"), set(live)


# --- service check ---------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(method: str, url: str, body: dict | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if data else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
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


# --- link service (go-link-service): one check per bead ------------------------------------

class _Step(Exception):
    """A failed contract step; its message is the check's detail."""


def _location(headers: dict[str, str]) -> str | None:
    return next((v for k, v in headers.items() if k.lower() == "location"), None)


def _create(base: str, body: dict) -> str:
    status, _, raw = _request("POST", base + "/links", body)
    if status != 201:
        raise _Step(f"POST /links {json.dumps(body)} returned {status}, want 201")
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    code = parsed.get("code") if isinstance(parsed, dict) else None
    if not isinstance(code, str) or not code or "/" in code:
        raise _Step(f"POST /links body {raw[:100]!r} is not a JSON object with a usable code")
    return code


def _expect_redirect(base: str, code: str, target: str, when: str = "") -> None:
    status, headers, _ = _request("GET", f"{base}/{code}")
    if status != 302:
        raise _Step(f"GET /{code}{when} returned {status}, want 302")
    if _location(headers) != target:
        raise _Step(f"GET /{code}{when} Location is {_location(headers)!r}, want {target!r}")


def _expect_status(method: str, url: str, want: int, what: str, headers: dict[str, str] | None = None) -> None:
    status, _, _ = _request(method, url, headers=headers)
    if status != want:
        raise _Step(f"{what} returned {status}, want {want}")


def _bead2(base: str) -> tuple[str | None, str]:
    """Create, redirect, unknown code. Returns (code, target) for the restart step; raises _Step."""
    target = "https://example.com/some/long/path?x=1"
    code = _create(base, {"url": target})
    _expect_redirect(base, code, target)
    _expect_status("GET", f"{base}/doesnotexist", 404, "GET unknown code")
    return code, target


def _bead3(base: str) -> None:
    expiring = _create(base, {"url": "https://example.com/expiring", "ttl_s": 1})
    target = "https://example.com/counted"
    code = _create(base, {"url": target})
    _expect_redirect(base, code, target)
    _expect_redirect(base, code, target, " (second time)")
    status, _, raw = _request("GET", f"{base}/links/{code}/stats")
    if status != 200:
        raise _Step(f"GET /links/{code}/stats returned {status}, want 200")
    try:
        stats = json.loads(raw)
    except ValueError:
        stats = None
    if not isinstance(stats, dict):
        raise _Step(f"GET /links/{code}/stats body {raw[:100]!r} is not a JSON object")
    if stats.get("url") != target:
        raise _Step(f"stats url is {stats.get('url')!r}, want {target!r}")
    clicks = stats.get("clicks")
    if type(clicks) is not int or clicks != 2:
        raise _Step(f"stats clicks is {clicks!r} after two redirects, want 2")
    if "expires_at" not in stats or stats["expires_at"] is not None:
        raise _Step(f"stats expires_at is {stats.get('expires_at', 'missing')!r} for a link without ttl_s, want null")
    time.sleep(2)
    _expect_status("GET", f"{base}/{expiring}", 410, f"GET /{expiring} 2 s after ttl_s 1")


def _bead4(base: str) -> None:
    target = "https://example.com/doomed"
    code = _create(base, {"url": target})
    url = f"{base}/links/{code}"
    _expect_status("DELETE", url, 401, "DELETE without a token")
    _expect_status("DELETE", url, 401, "DELETE with a wrong token", {"Authorization": "Bearer wrong-token"})
    _expect_redirect(base, code, target, " after refused deletes")
    _expect_status("DELETE", url, 204, "DELETE with the admin token", {"Authorization": f"Bearer {ADMIN_TOKEN}"})
    _expect_status("GET", f"{base}/{code}", 404, f"GET /{code} after delete")


def _step(fn, *args):
    """(result, None) or (None, failure detail)."""
    try:
        return fn(*args), None
    except _Step as e:
        return None, str(e)
    except _NET_ERRORS as e:
        return None, f"malformed or failed response: {type(e).__name__}: {e}"


def _check_links(binary: Path, project: Path, tmp: Path, logs: Path) -> list[CheckResult]:
    """The four bead contracts against the built binary. Each bead's detail is its first failing step."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    data_dir = tmp / "data"
    data_dir.mkdir()
    env = dict(os.environ)
    env.update({"LINKS_ADDR": f"127.0.0.1:{port}", "LINKS_DATA": str(data_dir / "links.json"),  # not there yet
                "LINKS_ADMIN_TOKEN": ADMIN_TOKEN})
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "service.log"
    fails: dict[str, str | None] = dict.fromkeys(LINKS_BEADS)
    proc = _start(binary, project, env, log)
    try:
        bad = _not_healthy(proc, base, log)
        if bad:
            return [CheckResult(n, False, f"not run: service did not start: {bad}") for n in LINKS_BEADS]
        _, fails["bead1_skeleton"] = _step(lambda: _expect_status("GET", base + "/healthz", 200, "GET /healthz"))
        kept, fails["bead2_links"] = _step(_bead2, base)
        _, fails["bead3_expiry_stats"] = _step(_bead3, base)
        _, fails["bead4_delete"] = _step(_bead4, base)
        stopped = _sigterm(proc)
        if stopped and not fails["bead1_skeleton"]:
            fails["bead1_skeleton"] = stopped
        _kill(proc)
        if kept and not fails["bead2_links"]:
            proc = _start(binary, project, env, log)
            bad = _not_healthy(proc, base, log)
            if bad:
                fails["bead2_links"] = f"restart failed: {bad}"
            else:
                code, target = kept
                _, why = _step(_expect_redirect, base, code, target, " after restart")
                if why:
                    fails["bead2_links"] = f"link lost after restart: {why}"
    finally:
        _kill(proc)
    ok = {"bead1_skeleton": "healthz 200; SIGTERM exits 0",
          "bead2_links": "create 201, redirect 302, unknown 404; link survives restart",
          "bead3_expiry_stats": "ttl_s expiry gives 410; stats count clicks",
          "bead4_delete": "delete needs the admin token (401 without, 401 wrong, 204 right), then 404"}
    return [CheckResult(n, fails[n] is None, fails[n] or ok[n]) for n in LINKS_BEADS]


def _sigterm(proc: subprocess.Popen) -> str | None:
    """SIGTERM the service; None if it exits 0 within SIGTERM_EXIT_S, else what went wrong."""
    if proc.poll() is not None:
        return f"service exited ({proc.returncode}) before SIGTERM"
    proc.send_signal(signal.SIGTERM)
    try:
        code = proc.wait(timeout=SIGTERM_EXIT_S)
    except subprocess.TimeoutExpired:
        return f"still running {SIGTERM_EXIT_S}s after SIGTERM"
    return None if code == 0 else f"exit status {code} after SIGTERM, want 0"


# --- arc gate (informational) ----------------------------------------------------------------

def check_arc_gate(project: Path, registry: Path, base: str | None, env: dict) -> CheckResult:
    """arc's boundary findings over the whole project, with the held registry installed.

    Changes `project` (the checker's disposable copy): puts `registry` at .arch/registry.yaml and
    commits everything. `arc gate --base` judges only imports on lines added since the base, and
    the base differs by condition (the arc conditions' base already has the registry and overlay,
    the control's has neither), so a diff would not score conditions alike. The brief's fallback,
    basing on the empty tree, cannot work: arc diffs `<base>...HEAD`, which needs a commit, not a
    tree. `--all` judges every line of every file, which is what that fallback was for, so `base`
    is not used for the diff. Only boundary findings count; other checks are not run."""
    project = Path(project)
    try:
        (project / ".arch").mkdir(exist_ok=True)
        shutil.copyfile(registry, project / ".arch" / "registry.yaml")
    except OSError as e:
        return CheckResult("arc_gate", False, f"could not install the registry: {e}", gating=False)
    for argv in (["add", "-A"],
                 ["-c", "user.name=Artifactory Checker", "-c", "user.email=checker@artifactory.invalid",
                  "-c", "commit.gpgsign=false", "commit", "--allow-empty", "--no-verify", "-qm", "checker snapshot"]):
        c = subprocess.run(["git", *argv], cwd=project, capture_output=True, text=True)
        if c.returncode != 0:
            return CheckResult("arc_gate", False, f"could not snapshot the project: {c.stderr.strip()[-300:]}",
                               gating=False)
    try:
        r = subprocess.run(["arc", "gate", "--all", "--only", "boundaries", "--json"], cwd=project, env=env,
                           capture_output=True, text=True, timeout=ARC_GATE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        return CheckResult("arc_gate", False, f"arc gate did not run: {type(e).__name__}", gating=False)
    try:
        rep = json.loads(r.stdout)
        findings = [f for f in rep.get("findings") or [] if f.get("check") == "boundaries"]
    except (ValueError, AttributeError, TypeError):
        return CheckResult("arc_gate", False, f"arc gate exit {r.returncode}: {(r.stderr or r.stdout).strip()[-500:]}",
                           gating=False)
    errors = sum(1 for f in findings if f.get("severity", "error") == "error")
    detail = f"{errors} boundary error(s)"
    if findings:
        detail += ": " + json.dumps(findings, separators=(",", ":"))[:2000]
    return CheckResult("arc_gate", errors == 0, detail, gating=False)
