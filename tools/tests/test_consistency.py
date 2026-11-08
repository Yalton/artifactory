from pathlib import Path

from artifactory.checks.consistency import (check_consistency, config_one_place, handlers_no_file_io,
                                            no_duplicate_funcs, storage_one_place)


def tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_empty_project_passes_every_check_without_crashing(tmp_path):
    results = check_consistency(tmp_path)
    assert [c.name for c in results] == ["config_one_place", "storage_one_place", "handlers_no_file_io",
                                         "no_duplicate_funcs"]
    assert all(c.passed and not c.gating for c in results), results


def test_config_in_one_package_passes(tmp_path):
    tree(tmp_path, {
        "internal/config/config.go": 'package config\nimport "os"\nfunc A() string { return os.Getenv("A") }\n'
                                     'func B() (string, bool) { return os.LookupEnv("B") }\n',
        "cmd/links/main.go": 'package main\n// os.Getenv( in a comment does not count\nfunc main() {}\n',
        "cmd/links/main_test.go": 'package main\nimport "os"\nvar _ = os.Getenv("T")\n',
    })
    c = config_one_place(tmp_path)
    assert c.passed and not c.gating and "internal/config" in c.detail


def test_config_in_two_packages_fails_and_names_them(tmp_path):
    tree(tmp_path, {
        "internal/settings/s.go": 'package settings\nimport "repo.billbert.co/artifactory/config"\n'
                                  'func L() { _ = config.Load(nil) }\n',
        "cmd/links/main.go": 'package main\nimport "os"\nfunc main() { _ = os.Environ() }\n',
        "vendor/x/x.go": 'package x\nimport "os"\nvar _ = os.Getenv("V")\n',
        ".hidden/y.go": 'package y\nimport "os"\nvar _ = os.Getenv("V")\n',
    })
    c = config_one_place(tmp_path)
    assert not c.passed
    assert "cmd/links" in c.detail and "internal/settings" in c.detail
    assert "vendor" not in c.detail and "hidden" not in c.detail


def test_storage_in_one_package_passes(tmp_path):
    tree(tmp_path, {
        "internal/store/store.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x"); os.WriteFile("x", nil, 0) }\n',
        "internal/links/links_test.go": 'package links\nimport "os"\nvar _, _ = os.Create("t")\n',
    })
    assert storage_one_place(tmp_path).passed


def test_storage_in_two_packages_fails(tmp_path):
    tree(tmp_path, {
        "internal/store/store.go": 'package store\nimport "repo.billbert.co/artifactory/kvstore"\n'
                                   'func O() { kvstore.Open("x") }\n',
        "cmd/links/main.go": 'package main\nimport "os"\nfunc main() { os.OpenFile("x", 0, 0) }\n',
    })
    c = storage_one_place(tmp_path)
    assert not c.passed and "cmd/links" in c.detail and "internal/store" in c.detail


def test_handlers_without_file_io_pass(tmp_path):
    tree(tmp_path, {
        "internal/httpapi/h.go": 'package httpapi\nimport "net/http"\n'
                                 'func Register(m *http.ServeMux) { m.HandleFunc("/x", nil) }\n',
        "internal/store/s.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x") }\n',
    })
    assert handlers_no_file_io(tmp_path).passed


def test_handler_file_with_file_io_fails_and_names_the_file(tmp_path):
    tree(tmp_path, {
        "cmd/links/main.go": 'package main\nimport ("net/http"; "os")\n'
                             'func h(w http.ResponseWriter, r *http.Request) { os.WriteFile("d", nil, 0) }\n',
        "internal/store/s.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x") }\n',
    })
    c = handlers_no_file_io(tmp_path)
    assert not c.passed and "cmd/links/main.go" in c.detail and "internal/store" not in c.detail


BODY = """{
\tx := 1
\ty := x + 2
\treturn y
}
"""


def test_distinct_functions_pass(tmp_path):
    tree(tmp_path, {
        "a/a.go": "package a\n\nfunc A() int " + BODY,
        "b/b.go": "package b\n\nfunc B() int " + BODY.replace("x + 2", "x + 3"),
        # short identical bodies (under 3 lines) do not count
        "c/c.go": "package c\n\nfunc C() {}\nfunc D() {}\nfunc E() int { return 1 }\nfunc F() int { return 1 }\n",
    })
    c = no_duplicate_funcs(tmp_path)
    assert c.passed, c.detail


def test_duplicate_function_bodies_fail_even_with_other_whitespace(tmp_path):
    tree(tmp_path, {
        "a/a.go": "package a\n\nfunc A() int " + BODY,
        "b/b.go": "package b\n\ntype T struct{}\n\nfunc (T) B(m map[string]interface{}) int "
                  + BODY.replace("\t", "    ").replace("x + 2", "x  +  2"),
    })
    c = no_duplicate_funcs(tmp_path)
    assert not c.passed and not c.gating
    assert "a/a.go:3 A" in c.detail and "b/b.go:5 B" in c.detail


def test_unparseable_file_does_not_crash_duplicate_check(tmp_path):
    tree(tmp_path, {"a/a.go": "package a\n\nfunc A( {\n"})
    c = no_duplicate_funcs(tmp_path)
    assert c.passed


def test_hand_rolled_config_package_called_from_main_is_one_place(tmp_path):
    tree(tmp_path, {
        "internal/config/config.go": 'package config\nimport "os"\ntype C struct{ Addr string }\n'
                                     'func Load() C { return C{Addr: os.Getenv("LINKS_ADDR")} }\n',
        "cmd/links/main.go": 'package main\nimport "example.com/links/internal/config"\n'
                             'func main() { _ = config.Load() }\n',
        "internal/store/store.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x") }\n',
        "cmd/links/wire.go": 'package main\nimport "example.com/links/internal/kvstore"\nfunc w() { kvstore.Open("d") }\n',
    })
    c = config_one_place(tmp_path)
    assert c.passed and c.detail == "environment read in 1 package(s): internal/config", c
    s = storage_one_place(tmp_path)
    assert s.passed and s.detail == "file I/O in 1 package(s): internal/store", s


def test_aliased_kit_imports_count_under_their_alias(tmp_path):
    tree(tmp_path, {
        "internal/env/env.go": 'package env\nimport "os"\nvar _ = os.Getenv("A")\n',
        "cmd/links/main.go": 'package main\n\nimport (\n\tcfg "repo.billbert.co/artifactory/config"\n'
                             '\tdb "repo.billbert.co/artifactory/kvstore"\n)\n\n'
                             'func main() { _ = cfg.Load(nil); db.Open("x"); config.Load(); kvstore.Open("y") }\n',
        "internal/store/s.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x") }\n',
    })
    c = config_one_place(tmp_path)
    assert not c.passed and "cmd/links" in c.detail and "internal/env" in c.detail
    s = storage_one_place(tmp_path)
    assert not s.passed and "cmd/links" in s.detail and "internal/store" in s.detail


def test_kit_import_without_a_call_and_unaliased_name_without_import_do_not_count(tmp_path):
    tree(tmp_path, {
        "internal/env/env.go": 'package env\nimport "os"\nvar _ = os.Getenv("A")\n',
        "cmd/links/main.go": 'package main\nimport cfg "repo.billbert.co/artifactory/config"\n'
                             'var _ cfg.Options\nfunc main() { config.Load() }\n',
    })
    assert config_one_place(tmp_path).passed


def test_route_registration_and_kit_open_beside_routes_is_wiring_not_handler_io(tmp_path):
    tree(tmp_path, {
        "cmd/links/main.go": 'package main\nimport ("net/http"; "repo.billbert.co/artifactory/kvstore")\n'
                             'func main() { kvstore.Open("d"); m := http.NewServeMux(); m.HandleFunc("/", h); '
                             'm.Handle("/x", nil) }\n',
        "cmd/links/routes.go": 'package main\nimport ("net/http"; "os")\n'
                               'func reg(m *http.ServeMux) { m.HandleFunc("/y", nil); os.ReadFile("seed") }\n',
    })
    c = handlers_no_file_io(tmp_path)
    assert c.passed, c


def test_method_handler_with_file_io_fails(tmp_path):
    tree(tmp_path, {
        "internal/httpapi/api.go": 'package httpapi\nimport ("net/http"; "os")\ntype API struct{}\n'
                                   'func (a *API) Get(rw http.ResponseWriter, req *http.Request) { os.Open("d") }\n',
    })
    c = handlers_no_file_io(tmp_path)
    assert not c.passed and "internal/httpapi/api.go" in c.detail


def test_duplicate_minimum_counts_lines_after_normalization(tmp_path):
    padded = "{\n\n\treturn 1\n\n\n}\n"  # 6 raw lines, 3 once blank lines are dropped: "{", "return 1", "}"
    two = "{\n\n\n\n\treturn 1 }\n"      # 5 raw lines, 2 after normalization
    tree(tmp_path, {
        "a/a.go": "package a\n\nfunc A() int " + two + "\nfunc B() int " + two,
    })
    assert no_duplicate_funcs(tmp_path).passed
    tree(tmp_path, {
        "b/b.go": "package b\n\nfunc C() int " + padded + "\nfunc D() int " + padded,
    })
    c = no_duplicate_funcs(tmp_path)
    assert not c.passed and "b/b.go:3 C" in c.detail and "a/a.go" not in c.detail


def test_generated_files_are_skipped_by_every_check(tmp_path):
    gen = ('// Code generated by stringer; DO NOT EDIT.\n\npackage gen\n'
           'import ("net/http"; "os")\nvar _ = os.Getenv("G")\n'
           'func h(w http.ResponseWriter, r *http.Request) { os.WriteFile("f", nil, 0) }\n'
           'func A() int ' + BODY + 'func B() int ' + BODY)
    tree(tmp_path, {
        "internal/gen/gen.go": gen,
        "internal/config/c.go": 'package config\nimport "os"\nvar _ = os.Getenv("A")\n',
        "internal/store/s.go": 'package store\nimport "os"\nfunc R() { os.ReadFile("x") }\n',
        # "Code generated" after the package clause does not make a file generated
        "internal/other/o.go": 'package other\n// Code generated by hand; DO NOT EDIT.\nfunc C() int ' + BODY,
    })
    assert all(c.passed for c in check_consistency(tmp_path)), check_consistency(tmp_path)
    (tmp_path / "internal/other/o2.go").write_text('package other\nfunc D() int ' + BODY)
    c = no_duplicate_funcs(tmp_path)
    assert not c.passed and "internal/gen" not in c.detail
