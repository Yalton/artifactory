package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/project"
)

func gitIn(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, b)
	}
}

// setupInstallEnv builds a dir: catalog holding one godot-csharp kit as a bare
// repo tagged v0.2.0, plus a git project initialised against it. installLine
// replaces the module's install line when non-empty.
func setupInstallEnv(t *testing.T, installLine string) (proj, name string) {
	t.Helper()
	t.Setenv("GIT_AUTHOR_NAME", "t")
	t.Setenv("GIT_AUTHOR_EMAIL", "t@t")
	t.Setenv("GIT_COMMITTER_NAME", "t")
	t.Setenv("GIT_COMMITTER_EMAIL", "t@t")
	t.Setenv("GIT_CONFIG_COUNT", "1")
	t.Setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
	t.Setenv("GIT_CONFIG_VALUE_0", "always")

	name = "FooKit"
	root := t.TempDir()
	bare := filepath.Join(root, name+".git")
	if installLine == "" {
		installLine = "git submodule add " + bare + " addons/" + name
	}
	work := t.TempDir()
	gitIn(t, work, "init", "-q", "-b", "main")
	yaml := `name: FooKit
ecosystem: godot-csharp
version: 0.2.0
summary: A test kit.
replaces:
  - "doing foo by hand"
install: "` + installLine + `"
setup: []
entry:
  - "Foo.Do"
liveness: "[FooKit] live"
docs: README.md
example: README.md
test: "true"
`
	os.WriteFile(filepath.Join(work, "module.yaml"), []byte(yaml), 0o644)
	gitIn(t, work, "add", ".")
	gitIn(t, work, "commit", "-q", "-m", "v0.2.0")
	gitIn(t, work, "tag", "v0.2.0")
	gitIn(t, root, "clone", "-q", "--bare", work, bare)

	proj = t.TempDir()
	gitIn(t, proj, "init", "-q", "-b", "main")
	os.WriteFile(filepath.Join(proj, "project.godot"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", proj, "--provider", "dir:"+root); code != 0 {
		t.Fatalf("init: %d %s", code, se)
	}
	return proj, name
}

func TestInstallRecordsVersion(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	code, so, se := runCmd("install", name, "--project", proj)
	if code != 0 {
		t.Fatalf("code=%d stdout=%q stderr=%q", code, so, se)
	}
	f, _ := project.Load(proj)
	if len(f.Modules) != 1 || f.Modules[0] != (project.Entry{Name: name, Version: "0.2.0"}) {
		t.Errorf("modules = %+v", f.Modules)
	}
	if _, err := os.Stat(filepath.Join(proj, "addons", name, "module.yaml")); err != nil {
		t.Error(err)
	}
	md, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if !strings.Contains(string(md), "## FooKit") {
		t.Errorf("MODULES.md not re-indexed:\n%s", md)
	}
}

func TestInstallSkipsInstalled(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	if code, _, se := runCmd("install", name, "--project", proj); code != 0 {
		t.Fatalf("first install: %d %s", code, se)
	}
	code, so, se := runCmd("install", name, "--project", proj)
	if code != 0 || !strings.Contains(so, "FooKit already installed (v0.2.0)") {
		t.Errorf("code=%d stdout=%q stderr=%q", code, so, se)
	}
}

func TestInstallFailureLeavesProjectUntouched(t *testing.T) {
	proj, name := setupInstallEnv(t, "false")
	if code, _, se := runCmd("add", name, "--project", proj); code != 0 {
		t.Fatalf("add: %d %s", code, se)
	}
	yamlBefore, _ := os.ReadFile(filepath.Join(proj, "artifactory.yaml"))
	mdBefore, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	code, _, _ := runCmd("install", name, "--project", proj)
	if code != 1 {
		t.Errorf("exit = %d, want 1", code)
	}
	yamlAfter, _ := os.ReadFile(filepath.Join(proj, "artifactory.yaml"))
	mdAfter, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if string(yamlBefore) != string(yamlAfter) || string(mdBefore) != string(mdAfter) {
		t.Error("project files changed after failed install")
	}
}

func TestInstallErrors(t *testing.T) {
	proj, name := setupInstallEnv(t, "")
	empty := t.TempDir()
	if code, _, _ := runCmd("install", name, "--project", empty); code != 2 {
		t.Errorf("no artifactory.yaml: exit %d, want 2", code)
	}
	if code, _, _ := runCmd("install", "Nope", "--project", proj); code != 1 {
		t.Errorf("unknown module: exit %d, want 1", code)
	}
	if code, _, _ := runCmd("install", "--project", proj); code != 2 {
		t.Errorf("no names: exit %d, want 2", code)
	}
}

// setupTwoKits builds a dir: catalog of plain folders AKit and BKit and a
// godot-csharp project on it. AKit installs by copying its descriptor into
// addons/AKit; BKit's install line fails.
func setupTwoKits(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for name, line := range map[string]string{
		"AKit": "mkdir -p addons/AKit && cp " + filepath.Join(root, "AKit", "module.yaml") + " addons/AKit/",
		"BKit": "false",
	} {
		dir := filepath.Join(root, name)
		os.Mkdir(dir, 0o755)
		y := "name: " + name + "\necosystem: godot-csharp\nversion: 0.1.0\nsummary: A kit.\nreplaces: [x]\n" +
			"install: \"" + line + "\"\nsetup: []\nentry: [X.Y]\nliveness: \"[" + name + "] live\"\n" +
			"docs: README.md\nexample: README.md\ntest: \"true\"\n"
		os.WriteFile(filepath.Join(dir, "module.yaml"), []byte(y), 0o644)
	}
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "project.godot"), nil, 0o644)
	if code, _, se := runCmd("init", "--project", proj, "--provider", "dir:"+root); code != 0 {
		t.Fatalf("init: %d %s", code, se)
	}
	return proj
}

func TestInstallPartialFailureReindexes(t *testing.T) {
	proj := setupTwoKits(t)
	code, so, se := runCmd("install", "AKit", "BKit", "--project", proj)
	if code != 1 {
		t.Fatalf("exit = %d, want 1 (stdout %q stderr %q)", code, so, se)
	}
	if !strings.Contains(se, "installed before the failure: AKit (v0.1.0)") {
		t.Errorf("stderr lacks installed list: %q", se)
	}
	md, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if !strings.Contains(string(md), "## AKit") || strings.Contains(string(md), "## BKit") {
		t.Errorf("MODULES.md:\n%s", md)
	}
	agents, _ := os.ReadFile(filepath.Join(proj, "AGENTS.md"))
	if len(agents) == 0 {
		t.Error("AGENTS.md block not written")
	}
}

func TestInstallPartialFailureJSON(t *testing.T) {
	proj := setupTwoKits(t)
	code, so, _ := runCmd("install", "--json", "AKit", "BKit", "--project", proj)
	if code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
	var v struct {
		Error     string `json:"error"`
		Installed []struct {
			Name, Version string
		} `json:"installed"`
	}
	if err := json.Unmarshal([]byte(so), &v); err != nil {
		t.Fatalf("%v: %q", err, so)
	}
	if v.Error == "" || len(v.Installed) != 1 || v.Installed[0].Name != "AKit" || v.Installed[0].Version != "0.1.0" {
		t.Errorf("json = %+v", v)
	}
}
