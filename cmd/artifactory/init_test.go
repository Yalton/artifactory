package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/skill"
)

func TestInitCopiesSkillOnlyIntoExistingHarnessDirs(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), []byte("module x\n"), 0o644)
	os.Mkdir(filepath.Join(dir, ".claude"), 0o755)
	code, so, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t))
	if code != 0 {
		t.Fatalf("init: %d %s", code, se)
	}
	want := filepath.Join(dir, ".claude", "skills", "artifactory", "SKILL.md")
	got, err := os.ReadFile(want)
	if err != nil || string(got) != skill.Text() {
		t.Fatalf("skill copy missing or differs: %v", err)
	}
	if !strings.Contains(so, "wrote "+want) {
		t.Errorf("stdout lacks wrote line: %q", so)
	}
	for _, d := range []string{".agents", ".opencode"} {
		if _, err := os.Stat(filepath.Join(dir, d)); err == nil {
			t.Errorf("%s was created", d)
		}
	}
}

func TestInitRefusesExistingProjectFile(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), nil, 0o644)
	os.Mkdir(filepath.Join(dir, ".agents"), 0o755)
	os.WriteFile(filepath.Join(dir, "artifactory.yaml"), []byte("ecosystem: go\n"), 0o644)
	code, _, _ := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t))
	if code != 1 {
		t.Errorf("exit %d, want 1", code)
	}
	if _, err := os.Stat(filepath.Join(dir, ".agents", "skills")); err == nil {
		t.Errorf("skill written despite refusal")
	}
}

func TestSkillIsShort(t *testing.T) {
	if n := strings.Count(skill.Text(), "\n"); n >= 60 {
		t.Errorf("SKILL.md has %d lines, want under 60", n)
	}
}

func TestInitSkillFailureLeavesInitRerunnable(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "go.mod"), []byte("module x\n"), 0o644)
	os.MkdirAll(filepath.Join(dir, ".claude"), 0o755)
	// A file where the skills folder belongs makes the skill write fail.
	os.WriteFile(filepath.Join(dir, ".claude", "skills"), nil, 0o644)
	code, _, _ := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t))
	if code == 0 {
		t.Fatal("init succeeded despite a blocked skill write")
	}
	if _, err := os.Stat(filepath.Join(dir, "artifactory.yaml")); err == nil {
		t.Fatal("artifactory.yaml written despite skill failure")
	}
	os.Remove(filepath.Join(dir, ".claude", "skills"))
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 0 {
		t.Fatalf("re-run init: %d %s", code, se)
	}
}
