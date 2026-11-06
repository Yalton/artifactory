package app

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/install"
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
	md, _ := indexWarnings(t, proj)
	return md
}

// indexWarnings runs a modules-only index without arc and returns
// MODULES.md and the result's warnings joined by newlines.
func indexWarnings(t *testing.T, proj string) (string, string) {
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
	return string(b), strings.Join(res.Warnings, "\n")
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

func TestIndexWarnsOnVersionMismatch(t *testing.T) {
	proj := godotProject(t, "dir:"+filepath.Join(t.TempDir(), "missing"), "FooKit")
	project.Save(proj, project.File{Ecosystem: "godot-csharp", Provider: "dir:/nowhere",
		Modules: []project.Entry{{Name: "FooKit", Version: "0.0.9"}}})
	writeKit(t, filepath.Join(proj, "addons", "FooKit"), "FooKit", "Foo installed.")

	md, w := indexWarnings(t, proj)
	if !strings.Contains(md, "Foo installed.") {
		t.Errorf("MODULES.md should render the installed copy:\n%s", md)
	}
	if !strings.Contains(w, "FooKit") || !strings.Contains(w, "0.1.0") || !strings.Contains(w, "0.0.9") {
		t.Errorf("warnings = %q, want both versions", w)
	}
}

func TestIndexWarnsOnInvalidInstalledDescriptor(t *testing.T) {
	cat := t.TempDir()
	writeKit(t, filepath.Join(cat, "FooKit"), "FooKit", "Foo catalog.")
	proj := godotProject(t, "dir:"+cat, "FooKit")
	os.MkdirAll(filepath.Join(proj, "addons", "FooKit"), 0o755)
	os.WriteFile(filepath.Join(proj, "addons", "FooKit", "module.yaml"), []byte("name: FooKit\n"), 0o644)

	md, w := indexWarnings(t, proj)
	if !strings.Contains(md, "Foo catalog.") {
		t.Errorf("MODULES.md should fall back to the catalog:\n%s", md)
	}
	if !strings.Contains(w, "FooKit: installed copy not used, using the catalog") || !strings.Contains(w, "missing field") {
		t.Errorf("warnings = %q", w)
	}
}

func TestIndexWarnsWhenGoListFails(t *testing.T) {
	cat := t.TempDir()
	os.MkdirAll(filepath.Join(cat, "kvstore"), 0o755)
	y := strings.NewReplacer("godot-csharp", "go", "git submodule add example.com/kvstore.git addons/kvstore",
		"go get example.com/kvstore", "[kvstore] live", "kvstore live").Replace(kitYAML("kvstore", "KV catalog."))
	os.WriteFile(filepath.Join(cat, "kvstore", "module.yaml"), []byte(y), 0o644)
	proj := t.TempDir() // no go.mod
	project.Save(proj, project.File{Ecosystem: "go", Provider: "dir:" + cat,
		Modules: []project.Entry{{Name: "kvstore", Version: "0.1.0"}}})

	md, w := indexWarnings(t, proj)
	if !strings.Contains(md, "KV catalog.") {
		t.Errorf("MODULES.md should fall back to the catalog:\n%s", md)
	}
	if !strings.Contains(w, "installed copies not read, using the catalog") || !strings.Contains(w, "go") {
		t.Errorf("warnings = %q", w)
	}
}

func TestModuleForGoNameCollision(t *testing.T) {
	kv := func(summary string) descriptor.Descriptor {
		return descriptor.Descriptor{Name: "kvstore", Ecosystem: "go", Version: "0.1.0", Summary: summary}
	}
	local := install.Lookup{Ambiguous: map[string][]install.Copy{"kvstore": {
		{Path: "example.com/a/kvstore", Descriptor: kv("A.")},
		{Path: "example.com/b/kvstore", Descriptor: kv("B.")},
	}}}
	e := project.Entry{Name: "kvstore", Version: "0.1.0"}
	catB := kv("Catalog.")
	catB.Install = "go get example.com/b/kvstore@latest"

	m, ok, note := moduleFor(e, local, []catalog.Module{{Descriptor: catB}})
	if !ok || m.Summary != "B." || note != "" {
		t.Errorf("catalog path match: %+v %v %q", m, ok, note)
	}

	catC := catB
	catC.Install = "go get example.com/c/kvstore"
	m, ok, note = moduleFor(e, local, []catalog.Module{{Descriptor: catC}})
	if !ok || m.Summary != "Catalog." || !strings.Contains(note, "example.com/a/kvstore, example.com/b/kvstore") {
		t.Errorf("no path match: %+v %v %q", m, ok, note)
	}
}

func TestIndexArcEntryFromInstalledDescriptor(t *testing.T) {
	proj := godotProject(t, "dir:"+filepath.Join(t.TempDir(), "missing"), "FooKit")
	writeKit(t, filepath.Join(proj, "addons", "FooKit"), "FooKit", "Foo installed.")
	os.MkdirAll(filepath.Join(proj, ".arch"), 0o755)
	os.WriteFile(filepath.Join(proj, ".arch", "registry.yaml"), []byte("concepts: []\n"), 0o644)
	bin := t.TempDir()
	log := filepath.Join(bin, "calls.log")
	script := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + log + "\n" +
		"if [ \"$1 $2\" = \"module list\" ]; then echo '{\"modules\":[]}'; fi\nexit 0\n"
	os.WriteFile(filepath.Join(bin, "arc"), []byte(script), 0o755)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))

	if _, err := (App{}).Index(context.Background(), proj, false, ArcOn); err != nil {
		t.Fatalf("Index: %v", err)
	}
	b, _ := os.ReadFile(log)
	if !strings.Contains(string(b), "module set FooKit --summary Foo installed.") {
		t.Errorf("arc calls:\n%s", b)
	}
}
