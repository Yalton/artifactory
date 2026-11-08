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
        "internal/settings/s.go": 'package settings\nfunc L() { _ = config.Load(nil) }\n',
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
        "internal/store/store.go": 'package store\nfunc O() { kvstore.Open("x") }\n',
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
