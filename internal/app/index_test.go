package app

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/project"
)

// kitYAML is a valid godot-csharp module.yaml for name with summary.
func kitYAML(name, summary string) string {
	return `name: ` + name + `
ecosystem: godot-csharp
version: 0.1.0
summary: "` + summary + `"
replaces:
  - "doing it by hand"
install: "git submodule add example.com/` + name + `.git addons/` + name + `"
setup: []
entry:
  - "` + name + `.Do"
liveness: "[` + name + `] live"
docs: README.md
example: README.md
test: "true"
`
}

func writeKit(t *testing.T, dir, name, summary string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "module.yaml"), []byte(kitYAML(name, summary)), 0o644); err != nil {
		t.Fatal(err)
	}
}

// godotProject makes a godot project with provider and modules, each
// installed at version 0.1.0, and returns its folder.
func godotProject(t *testing.T, provider string, names ...string) string {
	t.Helper()
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "project.godot"), nil, 0o644)
	f := project.File{Ecosystem: "godot-csharp", Provider: provider}
	for _, n := range names {
		f.Modules = append(f.Modules, project.Entry{Name: n, Version: "0.1.0"})
	}
	if err := project.Save(proj, f); err != nil {
		t.Fatal(err)
	}
	return proj
}

func indexModules(t *testing.T, proj string) string {
	t.Helper()
	res, err := App{}.Index(context.Background(), proj, true, ArcOff)
	if err != nil {
		t.Fatalf("Index: %v", err)
	}
	if res.Modules == 0 {
		t.Fatalf("Index rendered no modules")
	}
	b, err := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestIndexRendersInstalledDescriptor(t *testing.T) {
	cat := t.TempDir()
	writeKit(t, filepath.Join(cat, "FooKit"), "FooKit", "Catalog summary.")
	proj := godotProject(t, "dir:"+cat, "FooKit")
	writeKit(t, filepath.Join(proj, "addons", "FooKit"), "FooKit", "Installed summary.")

	md := indexModules(t, proj)
	if !strings.Contains(md, "Installed summary.") || strings.Contains(md, "Catalog summary.") {
		t.Errorf("MODULES.md does not render the installed descriptor:\n%s", md)
	}
}

func TestIndexWithoutProviderWhenAllInstalled(t *testing.T) {
	proj := godotProject(t, "dir:"+filepath.Join(t.TempDir(), "missing"), "FooKit", "BarKit")
	writeKit(t, filepath.Join(proj, "addons", "FooKit"), "FooKit", "Foo installed.")
	writeKit(t, filepath.Join(proj, "addons", "BarKit"), "BarKit", "Bar installed.")

	md := indexModules(t, proj)
	if !strings.Contains(md, "Foo installed.") || !strings.Contains(md, "Bar installed.") {
		t.Errorf("MODULES.md:\n%s", md)
	}
}

func TestIndexFallsBackToCatalogForMissingCopy(t *testing.T) {
	cat := t.TempDir()
	writeKit(t, filepath.Join(cat, "FooKit"), "FooKit", "Foo catalog.")
	writeKit(t, filepath.Join(cat, "BarKit"), "BarKit", "Bar catalog.")
	proj := godotProject(t, "dir:"+cat, "FooKit", "BarKit")
	writeKit(t, filepath.Join(proj, "addons", "FooKit"), "FooKit", "Foo installed.")

	md := indexModules(t, proj)
	for _, want := range []string{"Foo installed.", "Bar catalog."} {
		if !strings.Contains(md, want) {
			t.Errorf("MODULES.md lacks %q:\n%s", want, md)
		}
	}
	if strings.Contains(md, "Foo catalog.") {
		t.Errorf("installed FooKit rendered from the catalog:\n%s", md)
	}
}

func TestIndexMissingCopyNeedsProvider(t *testing.T) {
	proj := godotProject(t, "dir:"+filepath.Join(t.TempDir(), "missing"), "FooKit")
	if _, err := (App{}).Index(context.Background(), proj, true, ArcOff); err == nil || Code(err) != CodeUsage {
		t.Errorf("err = %v, want a usage error for the unreachable provider", err)
	}
}
