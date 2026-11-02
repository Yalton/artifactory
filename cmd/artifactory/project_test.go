package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/project"
)

func kitsDir(t *testing.T) string {
	t.Helper()
	abs, err := filepath.Abs("../../internal/testdata/kits")
	if err != nil {
		t.Fatal(err)
	}
	return abs
}

func runCmd(args ...string) (int, string, string) {
	var so, se bytes.Buffer
	code := run(args, &so, &se)
	return code, so.String(), se.String()
}

func TestRunAddRejectsOtherEcosystem(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), []byte("module x\n"), 0o644)
	code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t))
	if code != 0 {
		t.Fatalf("init: %d %s", code, se)
	}
	code, _, se = runCmd("add", "CrashKit", "--project", dir)
	if code != 1 || !strings.Contains(se, "CrashKit") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
	if f, _ := project.Load(dir); len(f.Modules) != 0 {
		t.Errorf("module added despite mismatch: %+v", f.Modules)
	}
}

func TestRunAddUnknownModule(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "project.godot"), nil, 0o644)
	runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t))
	code, _, se := runCmd("add", "Nope", "--project", dir)
	if code != 1 || !strings.Contains(se, "Nope") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
}

func TestRunInitRefusesExisting(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 0 {
		t.Fatalf("%d %s", code, se)
	}
	if code, _, _ := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 1 {
		t.Errorf("second init exit %d, want 1", code)
	}
}

func TestRunIndexScopesModules(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "project.godot"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 0 {
		t.Fatalf("%d %s", code, se)
	}
	if code, _, se := runCmd("add", "CrashKit", "CursorKit", "--project", dir); code != 0 {
		t.Fatalf("add: %d %s", code, se)
	}
	md, err := os.ReadFile(filepath.Join(dir, "MODULES.md"))
	if err != nil {
		t.Fatal(err)
	}
	if n := strings.Count("\n"+string(md), "\n## CrashKit\n") + strings.Count(string(md), "\n## CursorKit\n"); n != 2 {
		t.Errorf("want CrashKit and CursorKit headings, got %d", n)
	}
	if strings.Contains(string(md), "## DebugLogKit") {
		t.Errorf("out-of-scope module rendered")
	}
	if _, err := os.Stat(filepath.Join(dir, "AGENTS.md")); err != nil {
		t.Errorf("AGENTS.md missing: %v", err)
	}
	// --modules-only leaves AGENTS.md alone.
	os.Remove(filepath.Join(dir, "AGENTS.md"))
	if code, _, _ := runCmd("index", "--project", dir, "--modules-only"); code != 0 {
		t.Fatal("index --modules-only failed")
	}
	if _, err := os.Stat(filepath.Join(dir, "AGENTS.md")); err == nil {
		t.Errorf("AGENTS.md written with --modules-only")
	}
}

func TestRunIndexMissingModule(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), nil, 0o644)
	project.Save(dir, project.File{Ecosystem: "go", Provider: "dir:" + kitsDir(t), Modules: []project.Entry{{Name: "ghost"}}})
	code, _, se := runCmd("index", "--project", dir)
	if code != 1 || !strings.Contains(se, "ghost") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
}

func TestResolveProviderUsesProjectFile(t *testing.T) {
	dir := t.TempDir()
	project.Save(dir, project.File{Ecosystem: "godot-csharp", Provider: "dir:" + kitsDir(t)})
	code, so, se := runCmd("catalog", "--project", dir)
	if code != 0 || !strings.Contains(so, "CrashKit") {
		t.Errorf("code=%d out=%q err=%q", code, so, se)
	}
}
