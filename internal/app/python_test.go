package app

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/project"
	"repo.billbert.co/artifactory/artifactory/internal/pystub"
)

const pyKitYAML = `name: rate-limiter
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

// Install of a python module offline (find-links only) installs it into the
// project's .venv, records it, and indexes it from the installed module.yaml.
func TestInstallPythonOffline(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 not found")
	}
	for _, k := range []string{"UV_FIND_LINKS", "UV_OFFLINE", "VIRTUAL_ENV"} {
		t.Setenv(k, "")
	}
	links := t.TempDir()
	if _, err := pystub.Wheel(links, "rate-limiter", "0.1.0", "rate_limiter", map[string]string{"module.yaml": pyKitYAML}); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PIP_FIND_LINKS", links)
	t.Setenv("PIP_NO_INDEX", "1")
	t.Setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")

	// The catalog's copy has another summary, so the index shows which it read.
	kits := t.TempDir()
	os.MkdirAll(filepath.Join(kits, "rate-limiter"), 0o755)
	os.WriteFile(filepath.Join(kits, "rate-limiter", "module.yaml"),
		[]byte(strings.Replace(pyKitYAML, "Token bucket", "Catalog", 1)), 0o644)

	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "requirements.txt"), nil, 0o644)
	if eco, err := project.Detect(proj); err != nil || eco != descriptor.Python {
		t.Fatalf("Detect = %q, %v", eco, err)
	}
	if err := project.Save(proj, project.File{Ecosystem: descriptor.Python, Provider: "dir:" + kits}); err != nil {
		t.Fatal(err)
	}
	res, err := App{}.Install(context.Background(), proj, []string{"rate-limiter"}, nil)
	if err != nil || len(res.Installed) != 1 || res.Installed[0].Version != "0.1.0" {
		t.Fatalf("Install = %+v, %v", res, err)
	}

	// With the catalog gone, the index reads only the installed copy.
	os.RemoveAll(kits)
	md, warnings := indexWarnings(t, proj)
	if !strings.Contains(md, "## rate-limiter\n\nToken bucket rate limiter.") || warnings != "" {
		t.Errorf("MODULES.md:\n%s\nwarnings: %s", md, warnings)
	}
	if !strings.Contains(md, "Project notes (python)") {
		t.Errorf("MODULES.md lacks the python consumer notes")
	}
	d, _ := descriptor.Parse([]byte(pyKitYAML), "")
	e, err := arcEntry(catalog.Module{Descriptor: d})
	if err != nil || e.Import != "rate_limiter" {
		t.Errorf("arcEntry = %+v, %v", e, err)
	}
}
