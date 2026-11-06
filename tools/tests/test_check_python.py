import dataclasses
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from artifactory import cli, harness
from artifactory.acceptance import AcceptanceTest, load_acceptance
from artifactory.checks.python import check_python, child_env
from artifactory.pyindex import SANDBOX_PYTHON, build_pyindex, download_wheels, standard_wheels, uv_binary

DATA = Path(__file__).parent / "data" / "python"
GOOD = DATA / "good"
KIT = DATA / "kits" / "stub-kit"
ALL_CHECKS = {"install", "modules_pinned", "pip_check", "tests", "app_starts", "modules_installed",
              "modules_live", "modules_unmodified", "no_traceback", "no_duplication"}
MAIN = Path("app") / "__main__.py"


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    """The stub kit's wheel plus pytest and the build backends, built once for the module.

    Building and downloading need the host's uv/pip caches or PyPI; without them the tests skip."""
    out = tmp_path_factory.mktemp("pyindex")
    try:
        build_pyindex([KIT], out)
        download_wheels(standard_wheels(), out)
    except RuntimeError as e:
        pytest.skip(f"host cannot build or download the stub wheels (cold cache or offline?): {e}")
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stub_test(fixture: Path = GOOD) -> AcceptanceTest:
    return AcceptanceTest(name="python-stub", ecosystem="python", fixture=fixture, prompt="p",
                          modules=["stub-kit"], time_limit_s=60, duplication={"stub-kit": [r"def greet\("]},
                          python_app="app", app_port=free_port())


def make_project(tmp_path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(GOOD, project)
    return project


def edit(project: Path, rel: Path | str, old: str, new: str) -> None:
    f = project / rel
    src = f.read_text()
    assert old in src, (rel, old)
    f.write_text(src.replace(old, new))


def checks(result):
    return {c.name: c for c in result.checks}


def failing(result):
    return {c.name for c in result.checks if not c.passed}


def test_good_project_passes_all(tmp_path, index):
    result = check_python(make_project(tmp_path), stub_test(), index)
    assert {c.name for c in result.checks} == ALL_CHECKS
    assert failing(result) == set(), result.to_json()
    assert result.passed


def test_input_project_not_modified(tmp_path, index):
    project = make_project(tmp_path)
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    check_python(project, stub_test(), index)
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == before


def test_pin_to_a_missing_version_fails_install(tmp_path, index):
    project = make_project(tmp_path)
    (project / "requirements.txt").write_text("stub-kit==9.9.9\n")
    result = check_python(project, stub_test(), index)
    c = checks(result)
    assert not c["install"].passed and "stub-kit" in c["install"].detail, c["install"]
    assert c["tests"].detail == "not run: install failed"


def test_unpinned_module_fails_pinned(tmp_path, index):
    project = make_project(tmp_path)
    (project / "requirements.txt").write_text("stub-kit>=0.1\n")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"modules_pinned"}, result.to_json()
    assert "not an exact == pin" in checks(result)["modules_pinned"].detail


def test_failing_project_test_fails_tests(tmp_path, index):
    project = make_project(tmp_path)
    (project / "tests" / "test_boom.py").write_text("def test_boom():\n    assert False, 'boom'\n")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"tests"}, result.to_json()


def test_app_that_crashes_fails_app_starts(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, "    port = int(", "    raise SystemExit(3)\n    port = int(")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"app_starts"}, result.to_json()
    assert "exited 3" in checks(result)["app_starts"].detail


def test_missing_health_endpoint_fails_app_starts(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, 'self.path == "/healthz"', 'self.path == "/health"')
    edit(project, MAIN, "        else:\n            body = greeting().encode()\n        self.send_response(200)",
         "            self.send_response(200)\n        else:\n            body = b'no'\n"
         "            self.send_response(404)")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"app_starts"}, result.to_json()
    assert "last: 404" in checks(result)["app_starts"].detail


def test_editable_kit_install_fails_installed(tmp_path, index):
    project = make_project(tmp_path)
    shutil.copytree(KIT, project / "kits" / "stub-kit")
    (project / "requirements.txt").write_text("-e ./kits/stub-kit\n")
    result = check_python(project, stub_test(), index)
    c = checks(result)
    assert c["install"].passed, c["install"]
    assert not c["modules_installed"].passed and "editable install" in c["modules_installed"].detail
    assert not c["modules_pinned"].passed


def test_modified_kit_file_in_project_venv_fails_unmodified(tmp_path, index):
    project = make_project(tmp_path)
    env = child_env(tmp_path)
    uv = str(uv_binary())
    venv = project / ".venv"
    for argv in ([uv, "venv", "-q", "--python", SANDBOX_PYTHON, str(venv)],
                 [uv, "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-index",
                  "--find-links", str(index), "-r", "requirements.txt"]):
        r = subprocess.run(argv, cwd=project, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    kit_init = next(venv.glob("lib/python*/site-packages/stub_kit/__init__.py"))
    kit_init.write_text(kit_init.read_text().replace("hello, ", "hi, "))
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"modules_unmodified"}, result.to_json()
    assert "stub-kit (project .venv): stub_kit/__init__.py modified" in checks(result)["modules_unmodified"].detail


def test_project_copy_shadowing_the_kit_fails_unmodified(tmp_path, index):
    project = make_project(tmp_path)
    shutil.copytree(KIT / "src" / "stub_kit", project / "stub_kit")
    result = check_python(project, stub_test(), index)
    c = checks(result)
    assert not c["modules_unmodified"].passed
    assert "import stub_kit resolves to stub_kit" in c["modules_unmodified"].detail


def test_app_that_never_imports_the_kit_fails_live(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, "from app.core import greeting\n", "def greeting():\n    return 'hello, world'\n")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"modules_live"}, result.to_json()
    assert "[stub-kit] live printed 0 times" in checks(result)["modules_live"].detail


def test_marker_printed_twice_fails_live(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, "def main():\n", "def main():\n    print('[stub-kit] live', flush=True)\n")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"modules_live"}, result.to_json()
    assert "printed 2 times" in checks(result)["modules_live"].detail


def test_marker_inside_a_longer_line_does_not_count(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, "from app.core import greeting\n", "def greeting():\n    return 'hello, world'\n")
    edit(project, MAIN, "def main():\n", "def main():\n    print('INFO [stub-kit] live', flush=True)\n")
    result = check_python(project, stub_test(), index)
    assert "printed 0 times" in checks(result)["modules_live"].detail


def test_traceback_in_app_log_fails_no_traceback(tmp_path, index):
    project = make_project(tmp_path)
    edit(project, MAIN, "def main():\n",
         "def main():\n    import traceback\n    try:\n        {}['missing']\n    except KeyError:\n"
         "        traceback.print_exc()\n")
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"no_traceback"}, result.to_json()
    assert "KeyError: 'missing'" in checks(result)["no_traceback"].detail


def test_hand_rolled_kit_function_fails_duplication(tmp_path, index):
    project = make_project(tmp_path)
    (project / "app" / "util.py").write_text("def greet(name):\n    return 'hello, ' + name\n")
    (project / "tests" / "helpers.py").write_text("def greet(name):\n    return name\n")  # tests are not scanned
    result = check_python(project, stub_test(), index)
    assert failing(result) == {"no_duplication"}, result.to_json()
    detail = checks(result)["no_duplication"].detail
    assert "app/util.py:1 matches stub-kit" in detail and "tests/" not in detail


def test_uv_lock_project_installs_and_passes(tmp_path, index):
    """A `uv init` style project (pyproject.toml + uv.lock, no requirements.txt) is pinned and installed."""
    project = make_project(tmp_path)
    (project / "requirements.txt").unlink()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        'dependencies = ["stub-kit==0.1.0"]\n\n[tool.uv]\npackage = false\n')
    env = {**child_env(tmp_path), "UV_FIND_LINKS": str(index)}
    r = subprocess.run([str(uv_binary()), "lock", "--python", SANDBOX_PYTHON], cwd=project, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"uv lock against the find-links index failed: {r.stderr}")
    result = check_python(project, stub_test(), index)
    c = checks(result)
    assert c["modules_pinned"].detail == "all 1 modules pinned in uv.lock", c["modules_pinned"]
    assert failing(result) == set(), result.to_json()


def test_cli_rejects_unknown_ecosystem(tmp_path, capsys):
    test_dir = tmp_path / "t"
    test_dir.mkdir()
    (test_dir / "test.yaml").write_text("ecosystem: rust\nfixture: .\nmodules: [x]\ntime_limit_s: 1\n")
    (test_dir / "duplication.yaml").write_text("")
    (test_dir / "prompt.md").write_text("p")
    rc = cli.main(["check", str(test_dir), str(tmp_path), "-o", str(tmp_path / "out.json")])
    assert rc == 2 and "no checker for ecosystem 'rust'" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_cli_python_needs_pyindex(tmp_path, capsys):
    test_dir = write_test_dir(tmp_path / "t")
    rc = cli.main(["check", str(test_dir), str(GOOD), "-o", str(tmp_path / "out.json")])
    assert rc == 2 and "--pyindex is required" in capsys.readouterr().err


def write_test_dir(test_dir: Path, port: int = 8080) -> Path:
    shutil.copytree(GOOD, test_dir / "fixture")
    (test_dir / "test.yaml").write_text(
        f"ecosystem: python\nfixture: fixture\nmodules: [stub-kit]\ntime_limit_s: 60\n"
        f"python_app: app\napp_port: {port}\n")
    (test_dir / "duplication.yaml").write_text("stub-kit:\n  - 'def greet\\('\n")
    (test_dir / "prompt.md").write_text("p")
    return test_dir


def test_checker_runs_in_the_networkless_sandbox(tmp_path, index):
    """The harness's checker command (python --pyindex, no network) grades the good project to all passes."""
    test_dir = write_test_dir(tmp_path / "test")
    test = load_acceptance(test_dir)
    trial = harness.prepare_trial(test, "# index", tmp_path / "trial-1", None, None, pyindex=index)
    cmd = harness.checker_command(trial, test_dir, "python", test.fixture, tmp_path / "x.json", "main", False)
    assert cmd[cmd.index("--pyindex") + 1] == str(index.resolve())
    result = harness.run_checker(trial, test, test_dir, "main", False)
    assert {c.name for c in result.checks} == ALL_CHECKS, result.to_json()
    assert failing(result) == set(), (result.to_json(), (trial.dir / "checker.log").read_text()[-3000:])


def test_checker_command_rejects_unknown_ecosystem(tmp_path, index):
    test = dataclasses.replace(stub_test(), ecosystem="rust")
    trial = harness.prepare_trial(test, "# index", tmp_path / "trial-1", None, None, pyindex=index)
    with pytest.raises(ValueError, match="no checker for ecosystem 'rust'"):
        harness.checker_command(trial, tmp_path, "rust", GOOD, tmp_path / "x.json", "main", False)


PACKAGED = ('[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
            'dependencies = ["stub-kit==0.1.0"]\n\n'
            '[build-system]\nrequires = ["{backend}"]\nbuild-backend = "uv_build"\n\n'
            '[tool.uv.build-backend]\nmodule-root = ""\n')


def test_packaged_app_is_built_offline_and_installed(tmp_path, index):
    """With a [build-system], the app itself is built (uv_build from the index) and installed."""
    project = make_project(tmp_path)
    (project / "pyproject.toml").write_text(PACKAGED.format(backend="uv_build>=0.12,<0.13"))
    result = check_python(project, stub_test(), index)
    assert failing(result) == set(), result.to_json()
    # The same project with a backend the index lacks fails install: the app is part of the install.
    (project / "pyproject.toml").write_text(PACKAGED.format(backend="no-such-backend"))
    result = check_python(project, stub_test(), index)
    assert "no-such-backend" in checks(result)["install"].detail, checks(result)["install"]
