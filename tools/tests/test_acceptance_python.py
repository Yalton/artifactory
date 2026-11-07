"""python-url-shortener end to end without a model: the round's kit path from local sample mirrors, then the
checker in its sandbox against a hand-written reference solution and a variant that hand-rolls the store.

The kits are not published yet, so `mirror_samples` stands in for `artifactory mirror`: it makes bare git
mirrors (branch main, tag v<version>) of samples/python/* in tmp_path. From there the test takes the same
path a round does: harness.build_python_index (export_kits, build_pyindex, download_wheels), prepare_trial
and run_checker."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from artifactory import harness
from artifactory.acceptance import load_acceptance
from artifactory.checks.duplication import check_duplication

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "python"
TEST_DIR = ROOT / "tests" / "acceptance" / "python-url-shortener"
ALL_CHECKS = {"install", "modules_pinned", "pip_check", "tests", "app_starts", "modules_installed",
              "modules_live", "modules_unmodified", "no_traceback", "no_duplication"}

KIT_VERSIONS = {"env-settings": "0.1.0", "json-kv": "0.1.0", "http-runner": "0.1.1"}
REQUIREMENTS = "".join(f"{m}=={v}\n" for m, v in KIT_VERSIONS.items())

APP = '''\
"""URL shortener: POST /links stores a URL under a random code, GET /<code> redirects to it."""
import json
import secrets
import string
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler

import env_settings
import http_runner
import json_kv

ALPHABET = string.ascii_letters + string.digits
CODE_LEN = 7


@dataclass
class Settings:
    port: int = 8080
    data: str = "shortener.json"


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def shorten(store, url: str) -> str:
    while True:
        code = new_code()
        if store.put_if_absent(code, url):
            return code


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body=b"", headers=()):
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/links":
                return self._send(404)
            try:
                url = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))["url"]
            except (ValueError, KeyError, TypeError):
                return self._send(400)
            if not isinstance(url, str) or not url:
                return self._send(400)
            body = json.dumps({"code": shorten(store, url)}).encode()
            self._send(201, body, [("Content-Type", "application/json")])

        def do_GET(self):
            url = store.get(self.path.lstrip("/"))
            if url is None:
                return self._send(404)
            self._send(302, headers=[("Location", url)])

        def log_message(self, *args):
            pass

    return Handler


def main():
    settings = env_settings.load(Settings, "SHORTENER")
    store = json_kv.open(settings.data)
    http_runner.run(make_handler(store), port=settings.port)
'''

MAIN = '''\
from shortener.app import main

if __name__ == "__main__":
    main()
'''

TESTS = '''\
import json_kv

from shortener.app import ALPHABET, CODE_LEN, shorten


def test_shorten_stores_and_survives_reopen(tmp_path):
    store = json_kv.open(tmp_path / "links.json")
    code = shorten(store, "https://example.com/")
    assert len(code) == CODE_LEN and set(code) <= set(ALPHABET)
    assert json_kv.open(tmp_path / "links.json").get(code) == "https://example.com/"


def test_codes_differ(tmp_path):
    store = json_kv.open(tmp_path / "links.json")
    assert len({shorten(store, "https://example.com/") for _ in range(20)}) == 20
'''

# The variant: the same service with its own JSON-file store instead of json-kv.
OWN_STORE = '''\
import json
import os
import threading


class FileStore:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        self.data = {}
        if os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)

    def get(self, key):
        with self.lock:
            return self.data.get(key)

    def put_if_absent(self, key, value):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value
            with open(self.path + ".tmp", "w") as f:
                json.dump(self.data, f)
            os.replace(self.path + ".tmp", self.path)
            return True
'''


def reference_files() -> dict[str, str]:
    return {"requirements.txt": REQUIREMENTS, "shortener/__init__.py": "", "shortener/__main__.py": MAIN,
            "shortener/app.py": APP, "tests/test_app.py": TESTS}


def own_store_files() -> dict[str, str]:
    files = reference_files()
    files["requirements.txt"] = "env-settings==0.1.0\nhttp-runner==0.1.1\n"
    files["shortener/store.py"] = OWN_STORE
    files["shortener/app.py"] = (APP.replace("import json_kv\n", "")
                                 .replace("import env_settings\n", "import env_settings\nfrom shortener.store import FileStore\n")
                                 .replace("json_kv.open(settings.data)", "FileStore(settings.data)"))
    files["tests/test_app.py"] = (TESTS.replace("import json_kv\n", "from shortener.store import FileStore\n")
                                  .replace('json_kv.open(tmp_path / "links.json")', 'FileStore(str(tmp_path / "links.json"))'))
    assert "json_kv" not in files["shortener/app.py"] + files["tests/test_app.py"]
    return files


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


def mirror_samples(samples: Path, mirrors: Path, work: Path) -> list[str]:
    """Bare mirrors <mirrors>/<name>.git of each sample kit, as `artifactory publish` would leave them on
    Forgejo: the kit at the repo root on branch main, tagged v<version>. Returns the kit names."""
    names = []
    for kit in sorted(d for d in samples.iterdir() if (d / "module.yaml").is_file()):
        desc = yaml.safe_load((kit / "module.yaml").read_text())
        src = work / kit.name
        shutil.copytree(kit, src, symlinks=True)
        _git("init", "-q", "-b", "main", cwd=src)
        _git("add", "-A", cwd=src)
        _git("commit", "-qm", f"{desc['name']} {desc['version']}", cwd=src)
        _git("tag", f"v{desc['version']}", cwd=src)
        _git("clone", "-q", "--mirror", str(src), str(mirrors / f"{desc['name']}.git"), cwd=work)
        names.append(desc["name"])
    return names


@pytest.fixture(scope="module")
def kits(tmp_path_factory):
    """Sample mirrors and the round's wheel index built from them. Needs the host's uv/pip caches or PyPI."""
    tmp = tmp_path_factory.mktemp("pykits")
    mirrors = tmp / "mirrors"
    mirrors.mkdir()
    names = mirror_samples(SAMPLES, mirrors, tmp / "work")
    test = load_acceptance(TEST_DIR)
    try:
        index = harness.build_python_index(mirrors, test, harness.STITCH_BRANCH, tmp / "pyindex" / test.name)
    except RuntimeError as e:
        if not network_failure(str(e)):
            raise  # a kit that does not build is a real failure
        pytest.skip(f"host cannot fetch wheels (cold cache or offline?): {e}")
    return test, mirrors, index, names


# uv's wording when it cannot reach PyPI for the build backend; pip download failures all count.
_FETCH_ERRORS = ("Failed to fetch", "error sending request", "dns error", "Could not connect", "offline",
                 "Network is unreachable", "Temporary failure in name resolution")


def network_failure(message: str) -> bool:
    """Whether build_python_index failed fetching wheels (download_wheels, or uv build getting uv_build)."""
    return message.startswith("pip download ") or any(m in message for m in _FETCH_ERRORS)


def test_network_failure_tells_fetching_from_building():
    assert network_failure("pip download pytest==9.2.0 failed (1): no route")
    assert network_failure("uv build /x failed (2): error: Failed to fetch: `https://pypi.org/simple/uv-build/`")
    assert not network_failure("uv build /x failed (2): error: Expected a Python module at: `src/json_kv/__init__.py`")


def test_index_holds_each_kit_wheel(kits):
    test, _, index, names = kits
    assert sorted(names) == sorted(test.modules)
    wheels = {w.name for w in index.glob("*.whl")}
    for m in test.modules:
        assert f"{m.replace('-', '_')}-{KIT_VERSIONS[m]}-py3-none-any.whl" in wheels, wheels
    assert any(w.startswith("pytest-") for w in wheels) and any(w.startswith("uv_build-") for w in wheels)


def test_modules_md_renders_from_the_mirrors(kits, tmp_path):
    test, mirrors, _, _ = kits
    md = harness.render_index(harness.build_cli(tmp_path), "python", f"dir:{mirrors}", test.modules)
    for m in test.modules:
        assert f"\n## {m}\n" in md
        assert f'pip install "{m} @ git+ssh://git@repo.billbert.co/artifactory/{m}.git@v{KIT_VERSIONS[m]}"' in md
    # The consumer notes carry the pinning contract, so the prompt does not repeat it.
    assert "Pin each module as `<name>==<version>` in `requirements.txt`" in md


def run_trial_checker(kits, tmp_path, files: dict[str, str]):
    test, mirrors, index, _ = kits
    trial = harness.prepare_trial(test, "# index", tmp_path / "trial-1", mirrors, None, pyindex=index)
    for rel, text in files.items():
        (trial.project / rel).parent.mkdir(parents=True, exist_ok=True)
        (trial.project / rel).write_text(text)
    result = harness.run_checker(trial, test, TEST_DIR, harness.STITCH_BRANCH, False)
    log = (trial.dir / "checker.log").read_text(errors="replace")[-3000:]
    return result, log


def test_reference_solution_passes_every_check(kits, tmp_path):
    result, log = run_trial_checker(kits, tmp_path, reference_files())
    assert {c.name for c in result.checks} == ALL_CHECKS, result.to_json()
    assert [c.name for c in result.checks if not c.passed] == [], (result.to_json(), log)


def test_hand_rolled_store_fails_the_kit_checks(kits, tmp_path):
    result, log = run_trial_checker(kits, tmp_path, own_store_files())
    by_name = {c.name: c for c in result.checks}
    failed = {n for n, c in by_name.items() if not c.passed}
    assert failed == {"modules_pinned", "modules_installed", "modules_live", "no_duplication"}, (result.to_json(), log)
    assert "json-kv" in by_name["modules_pinned"].detail and "json-kv" in by_name["modules_installed"].detail
    assert "[json-kv] live printed 0 times" in by_name["modules_live"].detail
    dup = by_name["no_duplication"].detail
    assert "shortener/store.py" in dup and "json-kv pattern" in dup
    assert "env-settings pattern" not in dup and "http-runner pattern" not in dup


# Small re-implementations of each kit's job. Every duplication.yaml pattern must flag at least one snippet
# of its module, and every snippet must be flagged.
REIMPLEMENTATIONS = {
    "env-settings": [
        'port = int(os.environ.get("SHORTENER_PORT", "8080"))',
        'data = os.getenv("SHORTENER_DATA")',
        "from os import environ, getenv",
    ],
    "json-kv": [
        "data = json.load(f)",
        "json.dump(data, f)",
        'os.replace(tmp, path)',
        'os.rename(tmp, path)',
        "os.fsync(f.fileno())",
        "Path(path).write_text(json.dumps(data))",
        "p.write_bytes(raw)",
        'with open(path, "w") as f:',
        'with open(path, "wt", encoding="utf-8") as f:',
        'with open(path, mode="a+") as f:',
        'with open(path, "r+b") as f:',
        'with open(Path(folder) / "x.json", "xb") as f:',
        'with Path(path).open("w") as f:',
        'f = os.fdopen(fd, "w")',
        "import sqlite3",
        "from tempfile import NamedTemporaryFile",
        "import shelve",
    ],
    "http-runner": [
        'server = ThreadingHTTPServer(("", port), Handler)',
        "server.serve_forever()",
        "import socketserver",
        "from wsgiref.simple_server import make_server",
        "server = await asyncio.start_server(handle, port=port)",
        "signal.signal(signal.SIGTERM, stop)",
        "from signal import SIGTERM, signal",
        "loop.add_signal_handler(signal.SIGTERM, stop)",
        'if self.path == "/healthz":',
    ],
}

# Needed glue and the reference style that must not be flagged.
GLUE = [
    "store = json_kv.open(settings.data)",
    'with open(path) as f:',
    'with open(path, "rb") as f:',
    'text = Path(path).read_text()',
    "body = json.loads(self.rfile.read(n))",
    'pool.shutdown()',
    "from http.server import BaseHTTPRequestHandler",
    "code = secrets.choice(ALPHABET)",
]


def test_every_duplication_pattern_flags_a_reimplementation():
    dup = load_acceptance(TEST_DIR).duplication
    assert set(REIMPLEMENTATIONS) == set(dup)
    for module, patterns in dup.items():
        compiled = [re.compile(p) for p in patterns]
        for rx in compiled:
            assert any(rx.search(line) for line in REIMPLEMENTATIONS[module]), f"{module}: {rx.pattern} flags nothing"
        for line in REIMPLEMENTATIONS[module]:
            assert any(rx.search(line) for rx in compiled), f"{module}: {line!r} is not flagged"
    every = [re.compile(p) for ps in dup.values() for p in ps]
    for line in GLUE:
        assert not any(rx.search(line) for rx in every), f"glue flagged: {line!r}"


def test_reference_solution_has_no_duplication_hits(tmp_path):
    dup = load_acceptance(TEST_DIR).duplication
    for name, files in (("ref", reference_files()), ("own", own_store_files())):
        root = tmp_path / name
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        result = check_duplication(root, sorted(root.rglob("*.py")), dup)
        if name == "ref":
            assert result.passed, result.detail
        else:
            assert not result.passed and "shortener/store.py" in result.detail
