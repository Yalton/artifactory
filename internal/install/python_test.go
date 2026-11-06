package install

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/pystub"
)

const rlYAML = `name: rate-limiter
ecosystem: python
version: 0.1.0
summary: Token bucket rate limiter.
replaces:
  - "a hand-rolled rate limiter"
install: "pip install \"rate-limiter @ git+ssh://git@example.invalid/artifactory/rate-limiter.git@v0.1.0\""
entry:
  - "rate_limiter.Limiter"
liveness: "[rate-limiter] live"
docs: README.md
example: example/main.py
test: pytest
`

// pyModule is the catalog entry for the stub rate-limiter module.
func pyModule(t *testing.T) catalog.Module {
	t.Helper()
	d, problems := descriptor.Parse([]byte(rlYAML), "rate-limiter")
	if len(problems) > 0 {
		t.Fatal(problems)
	}
	return catalog.Module{Descriptor: d, Tag: "v0.1.0"}
}

// pyIndex skips without python3, clears the find-links variables, and
// returns a find-links folder holding a rate-limiter 0.1.0 wheel whose
// package carries files (module.yaml from rlYAML unless files says otherwise;
// a nil value leaves the file out).
func pyIndex(t *testing.T, files map[string]*string) string {
	t.Helper()
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 not found")
	}
	for _, k := range []string{"PIP_FIND_LINKS", "UV_FIND_LINKS", "PIP_NO_INDEX", "UV_OFFLINE", "VIRTUAL_ENV"} {
		t.Setenv(k, "")
	}
	t.Setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
	t.Setenv("UV_CACHE_DIR", t.TempDir())
	y := rlYAML
	content := map[string]*string{"module.yaml": &y, "__init__.py": ptr("print('[rate-limiter] live', flush=True)\n")}
	for k, v := range files {
		content[k] = v
	}
	wheelFiles := map[string]string{}
	for k, v := range content {
		if v != nil {
			wheelFiles[k] = *v
		}
	}
	dir := t.TempDir()
	if _, err := pystub.Wheel(dir, "rate-limiter", "0.1.0", "rate_limiter", wheelFiles); err != nil {
		t.Fatal(err)
	}
	return dir
}

func ptr(s string) *string { return &s }

func pipOffline(t *testing.T, links string) {
	t.Setenv("PIP_FIND_LINKS", links)
	t.Setenv("PIP_NO_INDEX", "1")
}

func uvOffline(t *testing.T, links string) {
	t.Helper()
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not found")
	}
	pipOffline(t, links)
	t.Setenv("UV_FIND_LINKS", links)
	t.Setenv("UV_OFFLINE", "1")
}

// checkInstalled asserts Locate and Installed find the rate-limiter copy.
func checkInstalled(t *testing.T, proj string, m catalog.Module) {
	t.Helper()
	dir, err := Locate(proj, m)
	if err != nil || filepath.Base(dir) != "rate_limiter" || !strings.Contains(dir, filepath.Join(proj, ".venv")) {
		t.Errorf("Locate = %q, %v", dir, err)
	}
	got, err := Installed(context.Background(), proj, descriptor.Python, []string{"rate-limiter", "absent"})
	if err != nil || len(got.Found) != 1 || got.Found["rate-limiter"].Descriptor.Version != "0.1.0" || len(got.Problems) != 0 {
		t.Errorf("Installed = %+v, %v", got, err)
	}
}

func TestInstallPythonPip(t *testing.T) {
	links := pyIndex(t, nil)
	pipOffline(t, links)
	proj := t.TempDir() // no .venv: Run makes one
	m := pyModule(t)
	if v, err := Run(context.Background(), proj, m); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	checkInstalled(t, proj, m)
}

func TestInstallPythonUVAdd(t *testing.T) {
	links := pyIndex(t, nil)
	uvOffline(t, links)
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "pyproject.toml"),
		[]byte("[project]\nname = \"app\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = []\n"), 0o644)
	m := pyModule(t)
	if v, err := Run(context.Background(), proj, m); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	if b, _ := os.ReadFile(filepath.Join(proj, "pyproject.toml")); !strings.Contains(string(b), "rate-limiter==0.1.0") {
		t.Errorf("pyproject.toml does not pin the module:\n%s", b)
	}
	checkInstalled(t, proj, m)
}

func TestInstallPythonUVPip(t *testing.T) {
	links := pyIndex(t, nil)
	uvOffline(t, links)
	proj := t.TempDir()
	m := pyModule(t)
	if v, err := Run(context.Background(), proj, m); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	checkInstalled(t, proj, m)
}

// Online, the descriptor's install line runs with the project's venv active.
func TestInstallPythonOnlineLineUsesVenv(t *testing.T) {
	links := pyIndex(t, nil)
	t.Setenv("PIP_NO_INDEX", "1")
	proj := t.TempDir()
	m := pyModule(t)
	m.Install = "pip install " + filepath.Join(links, "rate_limiter-0.1.0-py3-none-any.whl")
	if v, err := Run(context.Background(), proj, m); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	checkInstalled(t, proj, m)
}

func TestInstallPythonOfflineIgnoresGitLine(t *testing.T) {
	links := pyIndex(t, nil)
	pipOffline(t, links)
	m := pyModule(t)
	m.Install = "touch should-not-exist"
	proj := t.TempDir()
	if _, err := Run(context.Background(), proj, m); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(proj, "should-not-exist")); err == nil {
		t.Error("the descriptor install line ran offline")
	}
}

func TestInstallPythonMissingFromIndex(t *testing.T) {
	pipOffline(t, pyIndex(t, nil))
	m := pyModule(t)
	m.Version = "9.9.9"
	if _, err := Run(context.Background(), t.TempDir(), m); err == nil || !strings.Contains(err.Error(), "rate-limiter==9.9.9") {
		t.Errorf("err = %v, want the failed install", err)
	}
}

func TestInstallPythonNoModuleYAML(t *testing.T) {
	pipOffline(t, pyIndex(t, map[string]*string{"module.yaml": nil}))
	proj := t.TempDir()
	m := pyModule(t)
	if _, err := Run(context.Background(), proj, m); err == nil || !strings.Contains(err.Error(), "module.yaml") {
		t.Errorf("Run err = %v", err)
	}
	if _, err := Locate(proj, m); err == nil {
		t.Error("Locate found a copy without module.yaml")
	}
	got, err := Installed(context.Background(), proj, descriptor.Python, []string{"rate-limiter"})
	if err != nil || len(got.Found) != 0 || !strings.Contains(got.Problems["rate-limiter"], "module.yaml") {
		t.Errorf("Installed = %+v, %v", got, err)
	}
}

func TestInstalledPythonWrongName(t *testing.T) {
	other := strings.Replace(rlYAML, "name: rate-limiter", "name: other-kit", 1)
	other = strings.Replace(other, "[rate-limiter] live", "[other-kit] live", 1)
	pipOffline(t, pyIndex(t, map[string]*string{"module.yaml": &other}))
	proj := t.TempDir()
	if _, err := Run(context.Background(), proj, pyModule(t)); err == nil || !strings.Contains(err.Error(), "other-kit") {
		t.Errorf("Run err = %v", err)
	}
	got, err := Installed(context.Background(), proj, descriptor.Python, []string{"rate-limiter"})
	if err != nil || !strings.Contains(got.Problems["rate-limiter"], "other-kit") {
		t.Errorf("Installed = %+v, %v", got, err)
	}
}

func TestInstalledPythonNoVenv(t *testing.T) {
	_, err := Installed(context.Background(), t.TempDir(), descriptor.Python, []string{"rate-limiter"})
	if err == nil || !strings.Contains(err.Error(), ".venv") {
		t.Errorf("err = %v", err)
	}
}

func TestPythonImportName(t *testing.T) {
	for _, tt := range []struct {
		entry []string
		want  string
	}{
		{[]string{"rate_limiter.Limiter", "x.y"}, "rate_limiter"},
		{[]string{"rate_limiter"}, "rate_limiter"},
		{[]string{"rate-limiter.Limiter"}, ""},
		{nil, ""},
	} {
		got, err := PythonImportName(tt.entry)
		if got != tt.want || (err != nil) != (tt.want == "") {
			t.Errorf("%v: %q, %v", tt.entry, got, err)
		}
	}
}
