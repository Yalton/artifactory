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
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t), "--scope", "none"); code != 0 {
		t.Fatalf("%d %s", code, se)
	}
	if code, _, se := runCmd("add", "CrashKit", "CursorKit", "--project", dir); code != 0 {
		t.Fatalf("add: %d %s", code, se)
	}
	md, err := os.ReadFile(filepath.Join(dir, "MODULES.md"))
	if err != nil {
		t.Fatal(err)
	}
	if n := strings.Count("\n"+string(md), "\n## CrashKit (not installed)\n") + strings.Count(string(md), "\n## CursorKit (not installed)\n"); n != 2 {
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

func TestRelativeDirProviderResolvesAgainstProject(t *testing.T) {
	kits := kitsDir(t)
	proj := t.TempDir()
	if err := os.Symlink(kits, filepath.Join(proj, "kits")); err != nil {
		t.Fatal(err)
	}
	y := "ecosystem: godot-csharp\nprovider: dir:kits\nmodules:\n  - name: CursorKit\n"
	os.WriteFile(filepath.Join(proj, "artifactory.yaml"), []byte(y), 0o644)
	t.Chdir(t.TempDir())
	code, so, se := runCmd("index", "--project", proj)
	if code != 0 {
		t.Fatalf("exit %d: %q %q", code, so, se)
	}
	md, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if !strings.Contains(string(md), "## CursorKit") {
		t.Errorf("MODULES.md:\n%s", md)
	}
}

// fakeArcOnPath puts an `arc` script that exits with code on PATH.
func fakeArcOnPath(t *testing.T, code string, withModule bool) {
	t.Helper()
	bin := t.TempDir()
	list := `{"modules":[]}`
	if withModule {
		list = `{"modules":[{"id":"Other","summary":"x","paths":["lib/Other/**"]}]}`
	}
	script := "#!/bin/sh\necho '" + list + "'\nexit " + code + "\n"
	if err := os.WriteFile(filepath.Join(bin, "arc"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func indexProject(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "project.godot"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 0 {
		t.Fatalf("init: %d %s", code, se)
	}
	if code, _, se := runCmd("add", "CrashKit", "--project", dir); code != 0 {
		t.Fatalf("add: %d %s", code, se)
	}
	return dir
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestFullIndexUsesCLIInstallLines(t *testing.T) {
	dir := indexProject(t)
	md := readFile(t, filepath.Join(dir, "MODULES.md"))
	if !strings.Contains(md, "```\nartifactory install CrashKit\n```\n\n(artifactory runs this for you; do not run it yourself: ") {
		t.Errorf("full index lacks CLI install line:\n%s", md)
	}
	if code, _, _ := runCmd("index", "--project", dir, "--modules-only"); code != 0 {
		t.Fatal("index --modules-only failed")
	}
	if md := readFile(t, filepath.Join(dir, "MODULES.md")); strings.Contains(md, "artifactory install") {
		t.Errorf("--modules-only should keep raw install lines:\n%s", md)
	}
}

func TestIndexArcModes(t *testing.T) {
	dir := indexProject(t)
	os.MkdirAll(filepath.Join(dir, ".arch"), 0o755)
	os.WriteFile(filepath.Join(dir, ".arch", "registry.yaml"), []byte("concepts: []\n"), 0o644)
	const arcBullet = "Never edit files inside an installed module"

	// Arc with an empty registry has no guidance of its own yet.
	fakeArcOnPath(t, "0", false)
	code, so, se := runCmd("index", "--project", dir, "--json")
	if code != 0 || !strings.Contains(so, `"arc": false`) || !strings.Contains(readFile(t, filepath.Join(dir, "AGENTS.md")), arcBullet) {
		t.Fatalf("auto with empty arc: %d %q %q", code, so, se)
	}

	fakeArcOnPath(t, "0", true)
	code, so, se = runCmd("index", "--project", dir, "--json")
	if code != 0 || !strings.Contains(so, `"arc": true`) {
		t.Fatalf("auto with arc: %d %q %q", code, so, se)
	}
	for _, f := range []string{"MODULES.md", "AGENTS.md"} {
		if strings.Contains(readFile(t, filepath.Join(dir, f)), arcBullet) {
			t.Errorf("%s keeps the arc bullet", f)
		}
	}

	code, so, _ = runCmd("index", "--project", dir, "--arc", "off", "--json")
	if code != 0 || !strings.Contains(so, `"arc": false`) {
		t.Fatalf("off: %d %q", code, so)
	}
	if !strings.Contains(readFile(t, filepath.Join(dir, "AGENTS.md")), arcBullet) {
		t.Errorf("--arc off should keep the full preamble")
	}

	// An arc too old for `module list` warns and keeps the full preamble.
	fakeArcOnPath(t, "2", false)
	code, so, se = runCmd("index", "--project", dir)
	if code != 0 || !strings.Contains(se, "module rules not registered") || !strings.Contains(readFile(t, filepath.Join(dir, "AGENTS.md")), arcBullet) {
		t.Errorf("old arc: %d %q %q", code, so, se)
	}
}

func TestIndexArcOnWithoutArcExits2(t *testing.T) {
	dir := indexProject(t)
	t.Setenv("PATH", t.TempDir())
	code, _, se := runCmd("index", "--project", dir, "--arc", "on")
	if code != 2 || !strings.Contains(se, "--arc on") || !strings.Contains(se, "no .arch/registry.yaml") {
		t.Errorf("code=%d stderr=%q", code, se)
	}
	if code, _, _ := runCmd("index", "--project", dir, "--arc", "bogus"); code != 2 {
		t.Errorf("bad mode exit %d, want 2", code)
	}
}

// init lists every library module of the ecosystem, marked not installed,
// so the agent sees what exists before writing its own (tool-value round 1).
func TestInitScopesTheEcosystemsModules(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "project.godot"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", dir, "--provider", "dir:"+kitsDir(t)); code != 0 {
		t.Fatalf("%d %s", code, se)
	}
	md, err := os.ReadFile(filepath.Join(dir, "MODULES.md"))
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"## CrashKit (not installed)", "## DebugLogKit (not installed)", "run `artifactory install CrashKit` first"} {
		if !strings.Contains(string(md), want) {
			t.Errorf("MODULES.md lacks %q", want)
		}
	}
	y, _ := os.ReadFile(filepath.Join(dir, "artifactory.yaml"))
	if strings.Contains(string(y), "version:") {
		t.Errorf("init installed something:\n%s", y)
	}
}
