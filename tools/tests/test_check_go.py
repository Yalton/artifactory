import os
import shutil
import subprocess
from pathlib import Path

import pytest

from artifactory.acceptance import load_acceptance
from artifactory.checks.go import check_go
from artifactory.goproxy import build_goproxy

ROOT = Path(__file__).resolve().parents[2]
GOOD = Path(__file__).parent / "data" / "go" / "good"
SAMPLES = ROOT / "samples" / "go"
TEST = load_acceptance(ROOT / "tests" / "acceptance" / "go-url-shortener")
MODULES = ["config", "kvstore", "shortid", "httpserver"]
ALL_CHECKS = {"build", "tests", "service_works", "modules_installed", "modules_live",
              "modules_unmodified", "no_duplication"}


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    p = tmp_path_factory.mktemp("proxy")
    build_goproxy([SAMPLES / m for m in MODULES], p)
    return p


def go(args, cwd, proxy, root):
    env = {**os.environ, "GOPROXY": f"file://{proxy}", "GONOSUMDB": "repo.billbert.co/artifactory",
           "GOFLAGS": "-mod=mod", "GOMODCACHE": str(root / "modcache"), "GOPATH": str(root / "gopath")}
    r = subprocess.run(["go", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def make_project(tmp_path, proxy, modules=MODULES) -> Path:
    project = tmp_path / "project"
    shutil.copytree(GOOD, project)
    for m in modules:
        go(["get", f"repo.billbert.co/artifactory/{m}@v0.1.0"], project, proxy, tmp_path)
    return project


def checks(result):
    return {c.name: c for c in result.checks}


def failing(result):
    return {c.name for c in result.checks if not c.passed}


def test_reference_solution_passes_all(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    result = check_go(project, TEST, proxy)
    assert {c.name for c in result.checks} == ALL_CHECKS
    assert failing(result) == set(), result.to_json()
    assert result.passed


def test_input_project_not_modified(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    check_go(project, TEST, proxy)
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == before


def test_replace_directive_fails(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    with open(project / "go.mod", "a") as f:
        f.write(f"\nreplace repo.billbert.co/artifactory/kvstore => {SAMPLES / 'kvstore'}\n")
    result = check_go(project, TEST, proxy)
    assert "modules_unmodified" in failing(result)
    assert "replace" in checks(result)["modules_unmodified"].detail


def test_unused_module_fails_live(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    main = project / "cmd" / "shortener" / "main.go"
    # Swap the shortid import for a blank-free local generator: shortid stays in go.mod, unused.
    src = main.read_text().replace('\t"repo.billbert.co/artifactory/shortid"\n', "")
    src = src.replace("shortid.New(7)", 'func() (string, error) { return fmt.Sprint(time.Now().UnixNano()), nil }()')
    src = src.replace('import (\n', 'import (\n\t"fmt"\n\t"time"\n')
    main.write_text(src)
    result = check_go(project, TEST, proxy)
    c = checks(result)
    assert failing(result) == {"modules_live"}, result.to_json()
    assert "shortid" in c["modules_live"].detail


def test_missing_module_fails_installed(tmp_path, proxy):
    project = make_project(tmp_path, proxy, modules=MODULES[:3])
    main = project / "cmd" / "shortener" / "main.go"
    main.write_text(main.read_text().replace(
        '\t"repo.billbert.co/artifactory/httpserver"\n', '').replace(
        "httpserver.Run(context.Background(), cfg.Addr, mux)",
        "http.ListenAndServe(cfg.Addr, mux)").replace('\t"context"\n', ""))
    result = check_go(project, TEST, proxy)
    c = checks(result)
    assert not c["modules_installed"].passed and "httpserver" in c["modules_installed"].detail
    assert not c["modules_live"].passed
    assert not c["no_duplication"].passed


def test_wrong_status_code_fails_service_works(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    main = project / "cmd" / "shortener" / "main.go"
    main.write_text(main.read_text().replace("w.WriteHeader(http.StatusCreated)", "w.WriteHeader(http.StatusOK)"))
    result = check_go(project, TEST, proxy)
    assert failing(result) == {"service_works"}, result.to_json()
    assert "201" in checks(result)["service_works"].detail


def test_build_failure_skips_service(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    main = project / "cmd" / "shortener" / "main.go"
    main.write_text(main.read_text() + "\nfunc broken() { undefined() }\n")
    result = check_go(project, TEST, proxy)
    c = checks(result)
    assert not c["build"].passed and "undefined" in c["build"].detail
    assert not c["service_works"].passed and c["service_works"].detail.startswith("not run")


def test_failing_project_tests_fail_tests_check(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    (project / "cmd" / "shortener" / "x_test.go").write_text(
        'package main\nimport "testing"\nfunc TestX(t *testing.T) { t.Fatal("boom") }\n')
    result = check_go(project, TEST, proxy)
    assert failing(result) == {"tests"}, result.to_json()


def test_hand_rolled_store_fails_duplication(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    (project / "cmd" / "shortener" / "store.go").write_text(
        'package main\n\nimport "os"\n\nfunc save(p string, b []byte) error { return os.WriteFile(p, b, 0o644) }\n')
    result = check_go(project, TEST, proxy)
    assert failing(result) == {"no_duplication"}, result.to_json()
    detail = checks(result)["no_duplication"].detail
    assert "cmd/shortener/store.go:5" in detail and "kvstore" in detail


def test_modified_module_cache_fails_unmodified(tmp_path, proxy):
    """go.sum pins the module hash; a proxy serving different bytes must be caught by go mod verify."""
    project = make_project(tmp_path, proxy)
    other = tmp_path / "other"
    shutil.copytree(SAMPLES / "shortid", other / "shortid")
    (other / "shortid" / "shortid.go").write_text(
        (other / "shortid" / "shortid.go").read_text().replace("makes short", "makes tampered"))
    evil = tmp_path / "evil"
    shutil.copytree(proxy, evil)
    shutil.rmtree(evil / "repo.billbert.co/artifactory/shortid")
    build_goproxy([other / "shortid"], evil)
    result = check_go(project, TEST, evil)
    assert "modules_unmodified" in failing(result)
    assert "mismatch" in checks(result)["modules_unmodified"].detail
