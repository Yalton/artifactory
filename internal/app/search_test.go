package app

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/project"
)

// TestSearchDefaultsToProjectEcosystem searches a catalog holding a go and a
// godot-csharp config kit from inside a go project.
func TestSearchDefaultsToProjectEcosystem(t *testing.T) {
	cat := t.TempDir()
	if err := os.CopyFS(filepath.Join(cat, "config"), os.DirFS("../../samples/go/config")); err != nil {
		t.Fatal(err)
	}
	writeKit(t, filepath.Join(cat, "SettingsKit"), "SettingsKit", "Load config settings from a file.")
	proj := t.TempDir()
	if err := project.Save(proj, project.File{Ecosystem: "go", Provider: "dir:" + cat}); err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		eco  string
		want []string
	}{
		{"", []string{"config"}},
		{"godot-csharp", []string{"SettingsKit"}},
		{EcosystemAll, []string{"config", "SettingsKit"}},
	}
	for _, tt := range tests {
		res, err := App{}.Search(context.Background(), "", proj, []string{"config", "settings"}, tt.eco)
		if err != nil {
			t.Fatalf("eco %q: %v", tt.eco, err)
		}
		got := map[string]bool{}
		for _, h := range res.Hits {
			got[h.Module.Name] = true
		}
		if len(got) != len(tt.want) {
			t.Errorf("eco %q: hits %v, want %v", tt.eco, got, tt.want)
		}
		for _, w := range tt.want {
			if !got[w] {
				t.Errorf("eco %q: missing %s in %v", tt.eco, w, got)
			}
		}
	}
}
