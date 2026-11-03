package arcreg

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fakeArc puts an `arc` shell script with the given exit code on PATH.
func fakeArc(t *testing.T, exit string) {
	t.Helper()
	bin := t.TempDir()
	script := "#!/bin/sh\n[ \"$1 $2 $3\" = \"module list --json\" ] || exit 3\necho '{\"modules\":[]}'\nexit " + exit + "\n"
	if err := os.WriteFile(filepath.Join(bin, "arc"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func withRegistry(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".arch"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, RegistryPath), []byte("modules: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestDetect(t *testing.T) {
	t.Run("no registry", func(t *testing.T) {
		fakeArc(t, "0")
		if present, warn := Detect(t.TempDir()); present || warn != "" {
			t.Errorf("got %v %q", present, warn)
		}
	})
	t.Run("registry and working arc", func(t *testing.T) {
		fakeArc(t, "0")
		if present, warn := Detect(withRegistry(t)); !present || warn != "" {
			t.Errorf("got %v %q", present, warn)
		}
	})
	t.Run("registry and old arc", func(t *testing.T) {
		fakeArc(t, "2")
		if present, warn := Detect(withRegistry(t)); present || !strings.HasPrefix(warn, Warning) || !strings.Contains(warn, "failed: ") {
			t.Errorf("got %v %q", present, warn)
		}
	})
	t.Run("registry and no arc", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		if present, warn := Detect(withRegistry(t)); present || warn != Warning {
			t.Errorf("got %v %q", present, warn)
		}
	})
}
