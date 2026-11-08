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
        go(["get", f"repo.billbert.co/artifactory/{m}@latest"], project, proxy, tmp_path)
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
        "httpserver.Run(cfg.Addr, mux)",
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


def test_vendor_dir_fails_unmodified(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    (project / "vendor").mkdir()
    result = check_go(project, TEST, proxy)
    assert "modules_unmodified" in failing(result)
    assert checks(result)["modules_unmodified"].detail == "project vendors modules (vendor/)"


def test_go_work_fails_unmodified(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    (project / "go.work").write_text("go 1.24\n\nuse .\n")
    result = check_go(project, TEST, proxy)
    assert "modules_unmodified" in failing(result)
    assert "go.work" in checks(result)["modules_unmodified"].detail


def test_in_memory_store_fails_restart(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    main = project / "cmd" / "shortener" / "main.go"
    src = main.read_text()
    src = src.replace("added, err := store.PutIfAbsent(code, in.URL)",
                      "_, exists := mem[code]\n\t\t\tadded := !exists\n\t\t\tmem[code] = in.URL")
    src = src.replace("url, ok, err := store.Get(r.PathValue(\"code\"))",
                      "url, ok := mem[r.PathValue(\"code\")]\n\t\tvar err error")
    src = src.replace("type settings struct", "var mem = map[string]string{}\n\ntype settings struct")
    assert "mem[" in src
    main.write_text(src)
    result = check_go(project, TEST, proxy)
    assert failing(result) == {"service_works"}, result.to_json()
    assert "link lost after restart" in checks(result)["service_works"].detail


def test_malformed_json_body_is_failed_check_not_crash(tmp_path, proxy):
    project = make_project(tmp_path, proxy)
    main = project / "cmd" / "shortener" / "main.go"
    main.write_text(main.read_text().replace(
        'json.NewEncoder(w).Encode(map[string]string{"code": code})', 'w.Write([]byte(`"abc"`))'))
    result = check_go(project, TEST, proxy)
    assert failing(result) == {"service_works"}, result.to_json()
    assert "usable code" in checks(result)["service_works"].detail


# --- the link service (go-link-service: kit checks reported, per-bead service checks) ---------

LINKS_TEST = load_acceptance(ROOT / "tests" / "acceptance" / "go-link-service")
LINKS_CHECKS = ["build", "tests", "bead1_skeleton", "bead2_links", "bead3_expiry_stats", "bead4_delete",
                "modules_installed", "modules_live", "modules_unmodified", "no_duplication",
                "config_one_place", "storage_one_place", "handlers_no_file_io", "no_duplicate_funcs"]

LINKS_SERVER = r'''package main

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"
)

type link struct {
	URL     string     `json:"url"`
	Clicks  int        `json:"clicks"`
	Expires *time.Time `json:"expires_at"`
}

var (
	mu    sync.Mutex
	links = map[string]*link{}
	data  string
	n     int
)

func save() { b, _ := json.Marshal(links); os.WriteFile(data, b, 0o644) }

func main() {
	addr, token := os.Getenv("LINKS_ADDR"), os.Getenv("LINKS_ADMIN_TOKEN")
	data = os.Getenv("LINKS_DATA")
	if b, err := os.ReadFile(data); err == nil {
		json.Unmarshal(b, &links)
	}
	n = len(links)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {})
	mux.HandleFunc("POST /links", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			URL  string `json:"url"`
			TTLS int    `json:"ttl_s"`
		}
		if json.NewDecoder(r.Body).Decode(&in) != nil || in.URL == "" {
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		n++
		code := "c" + strconv.Itoa(n) + "x"
		l := &link{URL: in.URL}
		if in.TTLS > 0 && EXPIRY {
			t := time.Now().Add(time.Duration(in.TTLS) * time.Second)
			l.Expires = &t
		}
		links[code] = l
		save()
		w.WriteHeader(201)
		json.NewEncoder(w).Encode(map[string]string{"code": code})
	})
	mux.HandleFunc("GET /{code}", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		l := links[r.PathValue("code")]
		switch {
		case l == nil:
			w.WriteHeader(404)
		case l.Expires != nil && time.Now().After(*l.Expires):
			w.WriteHeader(410)
		default:
			l.Clicks++
			save()
			http.Redirect(w, r, l.URL, 302)
		}
	})
	mux.HandleFunc("GET /links/{code}/stats", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		l := links[r.PathValue("code")]
		if l == nil {
			w.WriteHeader(404)
			return
		}
		json.NewEncoder(w).Encode(l)
	})
	mux.HandleFunc("DELETE /links/{code}", func(w http.ResponseWriter, r *http.Request) {
		if token == "" || r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(401)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		if links[r.PathValue("code")] == nil {
			w.WriteHeader(404)
			return
		}
		delete(links, r.PathValue("code"))
		save()
		w.WriteHeader(204)
	})
	srv := &http.Server{Addr: addr, Handler: mux}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	go srv.ListenAndServe()
	<-ctx.Done()
	sctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	srv.Shutdown(sctx)
}
'''


def links_project(tmp_path, expiry=True) -> Path:
    project = tmp_path / "links-project"
    (project / "cmd" / "links").mkdir(parents=True)
    (project / "go.mod").write_text("module example.com/links\n\ngo 1.22\n")
    (project / "cmd" / "links" / "main.go").write_text(
        LINKS_SERVER.replace("EXPIRY", "true" if expiry else "false"))
    return project


def test_link_service_passes_every_bead_and_reports_kits(tmp_path, proxy):
    result = check_go(links_project(tmp_path), LINKS_TEST, proxy)
    c = checks(result)
    assert [x.name for x in result.checks] == LINKS_CHECKS
    assert {n for n in ("build", "tests", "bead1_skeleton", "bead2_links", "bead3_expiry_stats", "bead4_delete",
                        "modules_unmodified") if not c[n].passed} == set(), result.to_json()
    assert all(c[n].gating for n in ("bead1_skeleton", "bead2_links", "bead3_expiry_stats", "bead4_delete",
                                     "modules_unmodified"))
    for n in ("modules_installed", "modules_live", "no_duplication", "config_one_place", "storage_one_place",
              "handlers_no_file_io", "no_duplicate_funcs"):
        assert not c[n].gating, n
    assert not c["modules_installed"].passed and not c["modules_live"].passed
    assert c["modules_live"].detail == "live: none; not live: config, httpserver, shortid, kvstore"
    # No kit is live, so every kit's duplication patterns count; the server writes its own file.
    assert not c["no_duplication"].passed and "kvstore" in c["no_duplication"].detail
    assert not c["handlers_no_file_io"].passed and "cmd/links/main.go" in c["handlers_no_file_io"].detail
    assert result.passed  # kit and consistency findings are reported, not gating


def test_link_service_without_expiry_fails_only_bead3(tmp_path, proxy):
    result = check_go(links_project(tmp_path, expiry=False), LINKS_TEST, proxy)
    c = checks(result)
    gating_failures = {x.name for x in result.checks if x.gating and not x.passed}
    assert gating_failures == {"bead3_expiry_stats"}, result.to_json()
    assert "410" in c["bead3_expiry_stats"].detail
    assert not result.passed


def test_link_service_build_failure_reports_not_run(tmp_path, proxy):
    project = tmp_path / "empty"
    project.mkdir()
    result = check_go(project, LINKS_TEST, proxy)
    c = checks(result)
    assert not c["build"].passed
    for n in ("bead1_skeleton", "bead2_links", "bead3_expiry_stats", "bead4_delete"):
        assert c[n].detail == "not run: build failed"
    assert all(c[n].passed for n in ("config_one_place", "storage_one_place", "handlers_no_file_io",
                                     "no_duplicate_funcs"))


def test_report_mode_counts_duplication_only_for_kits_not_live(tmp_path, proxy):
    """The reference url-shortener uses every kit; graded with kit_checks report, a hand-rolled
    file write is not counted because kvstore is live."""
    import dataclasses
    project = make_project(tmp_path, proxy)
    (project / "cmd" / "shortener" / "store.go").write_text(
        'package main\n\nimport "os"\n\nfunc save(p string, b []byte) error { return os.WriteFile(p, b, 0o644) }\n')
    test = dataclasses.replace(TEST, kit_checks="report")
    c = checks(check_go(project, test, proxy))
    assert c["modules_live"].detail == "live: config, kvstore, shortid, httpserver; not live: none"
    assert c["no_duplication"].passed and not c["no_duplication"].gating, c["no_duplication"]


# --- arc gate, on a project without .arch -------------------------------------------------

def git(project, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=project, check=True, capture_output=True)


@pytest.fixture(scope="module")
def arc_bin(tmp_path_factory):
    from artifactory.harness import build_arc
    try:
        return build_arc(tmp_path_factory.mktemp("arc"))
    except (RuntimeError, OSError) as e:
        pytest.skip(f"arc cannot be built: {e}")


def test_arc_gate_reports_boundary_crossing_in_a_project_without_arch(tmp_path, arc_bin, monkeypatch):
    from artifactory.checks.go import check_arc_gate, go_env
    monkeypatch.setenv("PATH", f"{arc_bin.parent}:{os.environ['PATH']}")
    project = tmp_path / "p"
    for rel, text in {
        "go.mod": "module example.com/links\n\ngo 1.22\n",
        "cmd/links/main.go": 'package main\n\nimport _ "example.com/links/internal/httpapi"\n\nfunc main() {}\n',
        "internal/httpapi/h.go": 'package httpapi\n\nimport _ "example.com/links/internal/store"\n',
        "internal/store/s.go": "package store\n",
        "internal/links/l.go": "package links\n",
    }.items():
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(text)
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base: the crossing is already in the base commit")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
    (project / "internal" / "links" / "more.go").write_text("package links\n")  # uncommitted work
    registry = ROOT / "tests" / "acceptance" / "go-link-service" / "arc-registry.yaml"
    c = check_arc_gate(project, registry, base, go_env(tmp_path / "noproxy", tmp_path))
    assert c.name == "arc_gate" and not c.gating and not c.passed, c
    assert c.detail.startswith("1 boundary error(s)") and "http-not-store" in c.detail
    assert "placement" not in c.detail and "registry" not in c.detail.split(":", 1)[0]


def test_arc_gate_passes_on_a_clean_layout(tmp_path, arc_bin, monkeypatch):
    from artifactory.checks.go import check_arc_gate, go_env
    monkeypatch.setenv("PATH", f"{arc_bin.parent}:{os.environ['PATH']}")
    project = tmp_path / "p"
    (project / "internal" / "httpapi").mkdir(parents=True)
    (project / "go.mod").write_text("module example.com/links\n\ngo 1.22\n")
    (project / "internal" / "httpapi" / "h.go").write_text("package httpapi\n")
    (project / ".arch").mkdir()
    (project / ".arch" / "registry.yaml").write_text("not: [a valid registry\n")  # replaced by the held one
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base")
    registry = ROOT / "tests" / "acceptance" / "go-link-service" / "arc-registry.yaml"
    c = check_arc_gate(project, registry, "HEAD", go_env(tmp_path / "noproxy", tmp_path))
    assert c.passed and c.detail == "0 boundary error(s)", c


def test_arc_gate_on_a_project_that_is_not_a_repository_is_a_finding(tmp_path):
    from artifactory.checks.go import check_arc_gate, go_env
    registry = ROOT / "tests" / "acceptance" / "go-link-service" / "arc-registry.yaml"
    c = check_arc_gate(tmp_path, registry, "abc", go_env(tmp_path / "noproxy", tmp_path))
    assert not c.passed and not c.gating


def test_cli_check_forwards_go_experiment_flags(tmp_path, monkeypatch):
    from artifactory import cli
    from artifactory.checks import go as gomod
    from artifactory.result import TrialResult
    seen = {}

    def fake(project, test, proxy, *, arc_registry=None, arc_base=None):
        seen.update(main_pkg=test.main_pkg, arc_registry=arc_registry, arc_base=arc_base)
        return TrialResult(test.name, "t")
    monkeypatch.setattr(gomod, "check_go", fake)
    out = tmp_path / "o.json"
    code = cli.main(["check", str(ROOT / "tests" / "acceptance" / "go-link-service"), str(tmp_path),
                     "--proxy", str(tmp_path), "--main-pkg", "./cmd/other", "--arc-registry", "/r.yaml",
                     "--arc-base", "abc", "-o", str(out)])
    assert code == 0 and seen == {"main_pkg": "./cmd/other", "arc_registry": Path("/r.yaml"), "arc_base": "abc"}
    seen.clear()
    assert cli.main(["check", str(ROOT / "tests" / "acceptance" / "go-url-shortener"), str(tmp_path),
                     "--proxy", str(tmp_path), "-o", str(out)]) == 0
    assert seen == {"main_pkg": "./cmd/shortener", "arc_registry": None, "arc_base": None}
    assert cli.main(["check", str(ROOT / "tests" / "acceptance" / "go-link-service"), str(tmp_path),
                     "--proxy", str(tmp_path), "--arc-registry", "/r.yaml", "-o", str(out)]) == 2
