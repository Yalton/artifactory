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
			if got := Render(tt.eco, loadAll(t, tt.dir)); got != string(want) {
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
		if err := WriteAgents(path, AgentsBlock("go")); err != nil {
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
