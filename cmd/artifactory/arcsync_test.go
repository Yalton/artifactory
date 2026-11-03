package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// logArcOnPath puts a fake `arc` on PATH that logs argv (tab separated, one
// call per line), serves the golden `module list --json`, and fails
// `module set` when ARC_FAIL=set.
func logArcOnPath(t *testing.T) (logPath string) {
	t.Helper()
	golden, err := os.ReadFile("../../internal/arcreg/testdata/module-list.json")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	logPath = filepath.Join(bin, "calls.log")
	os.WriteFile(filepath.Join(bin, "list.json"), golden, 0o644)
	script := `#!/bin/sh
printf '%s\t' "$@" >> "` + logPath + `"
printf '\n' >> "` + logPath + `"
if [ "$1 $2" = "module list" ]; then cat "` + filepath.Join(bin, "list.json") + `"; exit 0; fi
if [ "$1 $2" = "module set" ] && [ "$ARC_FAIL" = set ]; then echo "invalid module" >&2; exit 1; fi
exit 0
`
	if err := os.WriteFile(filepath.Join(bin, "arc"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return logPath
}

func withArcRegistry(t *testing.T, proj string) {
	t.Helper()
	os.MkdirAll(filepath.Join(proj, ".arch"), 0o755)
	if err := os.WriteFile(filepath.Join(proj, ".arch", "registry.yaml"), []byte("modules: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestInstallRegistersWithArc(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	withArcRegistry(t, proj)
	log := logArcOnPath(t)
	code, _, se := runCmd("install", name, "--project", proj)
	if code != 0 {
		t.Fatalf("code=%d stderr=%q", code, se)
	}
	b, _ := os.ReadFile(log)
	want := "module\tset\tFooKit\t--summary\tA test kit.\t--path\taddons/FooKit/**\t--covers\tdoing foo by hand\t--entry\tFoo.Do\t--rule\tPrint `[FooKit] live` at startup.\t--source\tartifactory\t"
	if !strings.Contains(string(b), want+"\n") {
		t.Errorf("arc calls:\n%s\nwant a line %q", b, want)
	}
}

func TestInstallArcSetFailureWarns(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	withArcRegistry(t, proj)
	logArcOnPath(t)
	t.Setenv("ARC_FAIL", "set")
	code, _, se := runCmd("install", name, "--project", proj)
	if code != 0 || !strings.Contains(se, "warning: arc: module set FooKit failed: invalid module") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
	code, so, _ := runCmd("index", "--project", proj, "--json")
	if code != 0 || !strings.Contains(so, `"warnings"`) {
		t.Errorf("json index: %d %q", code, so)
	}
}

func TestIndexDoesNotSetUnversionedModule(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	withArcRegistry(t, proj)
	log := logArcOnPath(t)
	if code, _, se := runCmd("add", name, "--project", proj); code != 0 {
		t.Fatal(se)
	}
	if code, _, se := runCmd("index", "--project", proj); code != 0 {
		t.Fatal(se)
	}
	b, _ := os.ReadFile(log)
	if strings.Contains(string(b), "module\tset") {
		t.Errorf("unversioned module was set:\n%s", b)
	}
}

func TestNoRegistryCallsNoArc(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	log := logArcOnPath(t)
	if code, _, se := runCmd("install", name, "--project", proj); code != 0 {
		t.Fatal(se)
	}
	if _, err := os.Stat(log); err == nil {
		b, _ := os.ReadFile(log)
		t.Errorf("arc was called:\n%s", b)
	}
}

func TestRegistryWithoutArcWarnsAndKeepsPreamble(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	if code, _, se := runCmd("install", name, "--project", proj); code != 0 {
		t.Fatal(se)
	}
	withArcRegistry(t, proj)
	// A PATH with git (the catalog needs it) but no arc.
	bin := t.TempDir()
	gitPath, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(gitPath, filepath.Join(bin, "git")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	code, _, se := runCmd("index", "--project", proj)
	if code != 0 || !strings.Contains(se, "module rules not registered") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
	if !strings.Contains(readFile(t, filepath.Join(proj, "AGENTS.md")), "Never edit files inside an installed module") {
		t.Error("full preamble missing")
	}
}
