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

// pyIndex skips without python3 and its venv module, isolates pip and uv
// from user configuration, clears the find-links variables, and returns a
// find-links folder holding a rate-limiter 0.1.0 wheel whose package carries
// files (module.yaml from rlYAML unless files says otherwise; a nil value
// leaves the file out).
func pyIndex(t *testing.T, files map[string]*string) string {
	t.Helper()
	if err := exec.Command("python3", "-c", "import venv, ensurepip").Run(); err != nil {
		t.Skip("python3 with venv and ensurepip not available")
	}
	for _, k := range []string{"PIP_FIND_LINKS", "UV_FIND_LINKS", "PIP_NO_INDEX", "UV_OFFLINE", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"} {
		unsetenv(t, k)
	}
	t.Setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
	t.Setenv("PIP_CONFIG_FILE", os.DevNull)
	t.Setenv("UV_NO_CONFIG", "1")
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

// unsetenv removes k for the test (uv rejects some variables set empty).
func unsetenv(t *testing.T, k string) {
	t.Setenv(k, "")
	os.Unsetenv(k)
}

// pipOffline sets only pip's offline variables, so uv cannot be chosen.
func pipOffline(t *testing.T, links string) {
	t.Setenv("PIP_FIND_LINKS", links)
	t.Setenv("PIP_NO_INDEX", "1")
}

func needUV(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not found")
	}
}

// uvOffline sets the variables a trial sets for both tools.
func uvOffline(t *testing.T, links string) {
	t.Helper()
	needUV(t)
	pipOffline(t, links)
	t.Setenv("UV_FIND_LINKS", links)
	t.Setenv("UV_OFFLINE", "1")
}

// commands records the python install command lines run during the test.
func commands(t *testing.T) *[]string {
	var got []string
	commandHook = func(l string) { got = append(got, l) }
	t.Cleanup(func() { commandHook = nil })
	return &got
}

// ranOne asserts exactly one install command ran and it has each part.
func ranOne(t *testing.T, got []string, parts ...string) {
	t.Helper()
	if len(got) != 1 {
		t.Fatalf("commands = %q", got)
	}
	for _, p := range parts {
		if !strings.Contains(got[0], p) {
			t.Errorf("command %q lacks %q", got[0], p)
		}
	}
}

// checkInstalled asserts Locate and Installed find the rate-limiter copy.
func checkInstalled(t *testing.T, proj string, m catalog.Module) {
	t.Helper()
	abs, _ := filepath.Abs(proj)
	dir, err := Locate(proj, m)
	if err != nil || filepath.Base(dir) != "rate_limiter" || !strings.HasPrefix(dir, filepath.Join(abs, ".venv")) {
		t.Errorf("Locate = %q, %v", dir, err)
	}
	got, err := Installed(context.Background(), proj, descriptor.Python, []string{"rate-limiter", "absent"})
	if err != nil || len(got.Found) != 1 || got.Found["rate-limiter"].Descriptor.Version != "0.1.0" || len(got.Problems) != 0 {
		t.Errorf("Installed = %+v, %v", got, err)
	}
}

func run(t *testing.T, proj string, m catalog.Module) []string {
	t.Helper()
	var said []string
	if v, err := RunProgress(context.Background(), proj, m, func(s string) { said = append(said, s) }); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	return said
}

func TestInstallPythonPip(t *testing.T) {
	links := pyIndex(t, nil)
	pipOffline(t, links)
	cmds := commands(t)
	proj := t.TempDir() // no .venv: Run makes one
	m := pyModule(t)
	said := run(t, proj, m)
	if len(said) != 1 || said[0] != "created .venv" {
		t.Errorf("progress = %q", said)
	}
	ranOne(t, *cmds, filepath.Join(proj, ".venv", "bin", "python")+"' -m pip install --no-index --find-links '"+links+"'", "rate-limiter==0.1.0")
	checkInstalled(t, proj, m)
}

// A relative project folder works: every path handed to a command is absolute.
func TestInstallPythonRelativeProject(t *testing.T) {
	links := pyIndex(t, nil)
	pipOffline(t, links)
	parent := t.TempDir()
	os.Mkdir(filepath.Join(parent, "sub"), 0o755)
	t.Chdir(parent)
	m := pyModule(t)
	run(t, "sub", m)
	checkInstalled(t, "sub", m)
}

func TestInstallPythonUVAdd(t *testing.T) {
	links := pyIndex(t, nil)
	uvOffline(t, links)
	cmds := commands(t)
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "pyproject.toml"),
		[]byte("[project]\nname = \"app\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = []\n"), 0o644)
	m := pyModule(t)
	run(t, proj, m)
	ranOne(t, *cmds, "uv add --offline --no-index --find-links '"+links+"' 'rate-limiter==0.1.0'")
	if b, _ := os.ReadFile(filepath.Join(proj, "pyproject.toml")); !strings.Contains(string(b), "rate-limiter==0.1.0") {
		t.Errorf("pyproject.toml does not pin the module:\n%s", b)
	}
	checkInstalled(t, proj, m)
}

func TestInstallPythonUVPip(t *testing.T) {
	links := pyIndex(t, nil)
	uvOffline(t, links)
	cmds := commands(t)
	proj := t.TempDir()
	// A poetry project is not a uv project: uv pip install, not uv add.
	os.WriteFile(filepath.Join(proj, "pyproject.toml"), []byte("[project]\nname = \"app\"\n\n[tool.poetry]\nname = \"app\"\n"), 0o644)
	m := pyModule(t)
	run(t, proj, m)
	ranOne(t, *cmds, "uv pip install --python '"+filepath.Join(proj, ".venv", "bin", "python")+"' --offline --no-index --find-links '"+links+"'")
	checkInstalled(t, proj, m)
}

// uvVenv makes proj/.venv with uv venv, which has no pip.
func uvVenv(t *testing.T, proj string) {
	t.Helper()
	needUV(t)
	if out, err := exec.Command("uv", "venv", "--quiet", filepath.Join(proj, ".venv")).CombinedOutput(); err != nil {
		t.Fatalf("uv venv: %v: %s", err, out)
	}
}

// Offline with only pip's variables, a pip-less venv gets ensurepip first;
// the system pip never runs.
func TestInstallPythonPiplessVenvEnsurepip(t *testing.T) {
	links := pyIndex(t, nil)
	proj := t.TempDir()
	uvVenv(t, proj)
	pipOffline(t, links)
	cmds := commands(t)
	m := pyModule(t)
	run(t, proj, m)
	ranOne(t, *cmds, filepath.Join(proj, ".venv", "bin", "python")+"' -m pip install --no-index")
	checkInstalled(t, proj, m)
}

// Online, a `pip install` line becomes uv pip install into a pip-less venv.
func TestInstallPythonPiplessVenvOnlineUsesUV(t *testing.T) {
	links := pyIndex(t, nil)
	proj := t.TempDir()
	uvVenv(t, proj)
	t.Setenv("UV_OFFLINE", "1")
	cmds := commands(t)
	m := pyModule(t)
	wheel := filepath.Join(links, "rate_limiter-0.1.0-py3-none-any.whl")
	m.Install = "pip install " + wheel
	run(t, proj, m)
	ranOne(t, *cmds, "uv pip install --python '"+filepath.Join(proj, ".venv", "bin", "python")+"' "+wheel)
	checkInstalled(t, proj, m)
}

// Online, a `pip install` line runs the venv's pip, never the system one.
func TestInstallPythonOnlineLineUsesVenvPip(t *testing.T) {
	links := pyIndex(t, nil)
	t.Setenv("PIP_NO_INDEX", "1")
	cmds := commands(t)
	proj := t.TempDir()
	m := pyModule(t)
	wheel := filepath.Join(links, "rate_limiter-0.1.0-py3-none-any.whl")
	m.Install = "pip install " + wheel
	run(t, proj, m)
	ranOne(t, *cmds, "'"+filepath.Join(proj, ".venv", "bin", "python")+"' -m pip install "+wheel)
	checkInstalled(t, proj, m)
}

func TestInstallPythonOfflineIgnoresGitLine(t *testing.T) {
	links := pyIndex(t, nil)
	pipOffline(t, links)
	m := pyModule(t)
	m.Install = "touch should-not-exist"
	proj := t.TempDir()
	run(t, proj, m)
	if _, err := os.Stat(filepath.Join(proj, "should-not-exist")); err == nil {
		t.Error("the descriptor install line ran offline")
	}
}

func TestPlanPythonRefusals(t *testing.T) {
	m := catalog.Module{Descriptor: descriptor.Descriptor{Name: "rate-limiter", Version: "0.1.0", Install: "uv add x"}}
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "pyproject.toml"), []byte("[project]\nname = \"app\"\n"), 0o644)
	for _, k := range []string{"PIP_FIND_LINKS", "UV_FIND_LINKS", "UV_PROJECT_ENVIRONMENT"} {
		t.Setenv(k, "")
	}

	// Offline with only uv's find-links but no uv on PATH.
	t.Setenv("PATH", t.TempDir())
	t.Setenv("UV_FIND_LINKS", "/wheels")
	if _, err := planPython(proj, m); err == nil || !strings.Contains(err.Error(), "PIP_FIND_LINKS") {
		t.Errorf("no uv: err = %v", err)
	}

	// Online uv add with UV_PROJECT_ENVIRONMENT elsewhere.
	t.Setenv("UV_FIND_LINKS", "")
	t.Setenv("UV_PROJECT_ENVIRONMENT", "/elsewhere")
	if _, err := planPython(proj, m); err == nil || !strings.Contains(err.Error(), "UV_PROJECT_ENVIRONMENT") {
		t.Errorf("project env: err = %v", err)
	}
}

func TestUVProject(t *testing.T) {
	for body, want := range map[string]bool{
		"[project]\nname = \"a\"\n":                             true,
		"[build-system]\nrequires = []\n":                       false,
		"[project]\nname = \"a\"\n[tool.pdm]\n":                 false,
		"[project]\nname = \"a\"\n[tool.poetry.dependencies]\n": false,
	} {
		dir := t.TempDir()
		os.WriteFile(filepath.Join(dir, "pyproject.toml"), []byte(body), 0o644)
		if got := uvProject(dir); got != want {
			t.Errorf("%q: %v", body, got)
		}
	}
}

// With module.yaml in two packages, the one its own entry names is chosen.
func TestChoosePythonByEntry(t *testing.T) {
	root := t.TempDir()
	var dirs []string
	for _, pkg := range []string{"aaa_other", "rate_limiter"} {
		d := filepath.Join(root, pkg)
		os.Mkdir(d, 0o755)
		os.WriteFile(filepath.Join(d, "module.yaml"), []byte(rlYAML), 0o644)
		dirs = append(dirs, d)
	}
	dir, d, err := choosePython("rate-limiter", dirs)
	if err != nil || filepath.Base(dir) != "rate_limiter" || d.Name != "rate-limiter" {
		t.Errorf("choosePython = %q, %v", dir, err)
	}
	if _, _, err := choosePython("rate-limiter", nil); err == nil {
		t.Error("no package: want error")
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
