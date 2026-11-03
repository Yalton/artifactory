package index

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

func loadAll(t *testing.T, root string) []descriptor.Descriptor {
	t.Helper()
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	var ds []descriptor.Descriptor
	for _, e := range entries {
		d, err := descriptor.Load(filepath.Join(root, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		ds = append(ds, d)
	}
	return ds
}

func TestRenderMatchesPythonGolden(t *testing.T) {
	tests := []struct{ eco, dir, golden string }{
		{"godot-csharp", "../testdata/kits", "testdata/godot-csharp.golden.md"},
		{"go", "../../samples/go", "testdata/go.golden.md"},
	}
	for _, tt := range tests {
		t.Run(tt.eco, func(t *testing.T) {
			want, err := os.ReadFile(tt.golden)
			if err != nil {
				t.Fatal(err)
			}
			if got := Render(tt.eco, loadAll(t, tt.dir), Options{}); got != string(want) {
				t.Errorf("Render differs from %s", tt.golden)
			}
		})
	}
}

func TestWriteAgentsBlockIsIdempotent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "AGENTS.md")
	if err := os.WriteFile(path, []byte("# Mine\n\ntext\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err := WriteAgents(path, AgentsBlock("go", Options{})); err != nil {
			t.Fatal(err)
		}
	}
	got, _ := os.ReadFile(path)
	s := string(got)
	if !strings.HasPrefix(s, "# Mine\n\ntext\n\n<!-- artifactory:begin -->") {
		t.Errorf("user text or spacing lost: %q", s[:60])
	}
	if strings.Count(s, "<!-- artifactory:begin -->") != 1 || strings.Count(s, "<!-- artifactory:end -->") != 1 {
		t.Errorf("want exactly one block")
	}
	if !strings.Contains(s, "See MODULES.md for the modules in scope and their install commands.") {
		t.Errorf("pointer line missing")
	}
}

var arcBullets = []string{
	"- If a module here does what you need",
	"- Never edit files inside an installed module",
	"- Wire every module you install",
}

var keptBullets = []string{
	"- Install a module only with its `install` command.",
	"- Before finishing, build and run",
	"- The Wiring section of the module's README",
	"- When the Before-finishing checks pass, stop.",
}

func TestArcDropsModuleBullets(t *testing.T) {
	ds := loadAll(t, "../../samples/go")
	for name, got := range map[string]string{
		"MODULES.md": Render("go", ds, Options{Arc: true}),
		"AGENTS.md":  AgentsBlock("go", Options{Arc: true}),
	} {
		for _, b := range arcBullets {
			if strings.Contains(got, b) {
				t.Errorf("%s: arc bullet kept: %s", name, b)
			}
		}
		for _, b := range keptBullets {
			if !strings.Contains(got, b) {
				t.Errorf("%s: bullet dropped: %s", name, b)
			}
		}
		if strings.Contains(got, "<!-- arc -->") {
			t.Errorf("%s: marker leaked", name)
		}
	}
	if off := AgentsBlock("go", Options{}); strings.Contains(off, "<!-- arc -->") || !strings.Contains(off, arcBullets[0]) {
		t.Errorf("arc off block wrong: %s", off)
	}
}

func TestArcRenderMatchesGolden(t *testing.T) {
	want, err := os.ReadFile("testdata/go.arc.golden.md")
	if err != nil {
		t.Fatal(err)
	}
	if got := Render("go", loadAll(t, "../../samples/go"), Options{Arc: true}); got != string(want) {
		t.Error("Render with Arc differs from testdata/go.arc.golden.md")
	}
}

func TestCLIInstallRenderMatchesGolden(t *testing.T) {
	ds := loadAll(t, "../../samples/go")[:1]
	for name, opt := range map[string]Options{
		"testdata/go.cli.golden.md":     {CLIInstall: true},
		"testdata/go.cli-arc.golden.md": {CLIInstall: true, Arc: true},
	} {
		want, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		if got := Render("go", ds, opt); got != string(want) {
			t.Errorf("Render differs from %s", name)
		}
	}
	raw := Render("go", ds, Options{})
	if strings.Contains(raw, "artifactory install") {
		t.Errorf("raw render mentions the CLI")
	}
}
