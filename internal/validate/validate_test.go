package validate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const goYAML = `name: kvstore
ecosystem: go
version: 0.1.0
summary: A store.
replaces: [storing data]
install: go get repo.billbert.co/artifactory/kvstore
setup: []
entry: [kvstore.Open]
liveness: go list -deps
docs: README.md
example: README.md#wiring
test: go test ./...
`

func write(t *testing.T, dir, name, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func module(t *testing.T, yaml, gomod string, files ...string) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "kvstore")
	if err := os.Mkdir(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, dir, "module.yaml", yaml)
	if gomod != "" {
		write(t, dir, "go.mod", gomod)
	}
	for _, f := range files {
		write(t, dir, f, "x")
	}
	return dir
}

const goodMod = "module repo.billbert.co/artifactory/kvstore\n\ngo 1.24\n"

func TestValidateClean(t *testing.T) {
	_, problems := Module(module(t, goYAML, goodMod, "README.md"))
	if len(problems) != 0 {
		t.Fatal(problems)
	}
}

func TestValidateMissingDocs(t *testing.T) {
	y := strings.Replace(goYAML, "docs: README.md", "docs: NOTES.md", 1)
	_, problems := Module(module(t, y, goodMod, "README.md"))
	if len(problems) != 1 || problems[0] != "docs: NOTES.md not found" {
		t.Fatalf("problems = %q", problems)
	}
}

func TestValidateExampleFragment(t *testing.T) {
	_, problems := Module(module(t, goYAML, goodMod, "README.md"))
	if len(problems) != 0 {
		t.Fatalf("fragment example should pass: %q", problems)
	}
	_, problems = Module(module(t, goYAML, goodMod))
	if len(problems) != 2 || problems[1] != "example: README.md not found" {
		t.Fatalf("problems = %q", problems)
	}
}

func TestValidateGoModPathMismatch(t *testing.T) {
	_, problems := Module(module(t, goYAML, "module example.com/kv\n", "README.md"))
	want := "go.mod: module example.com/kv does not match install path repo.billbert.co/artifactory/kvstore"
	if len(problems) != 1 || problems[0] != want {
		t.Fatalf("problems = %q", problems)
	}
}

func TestValidateGoModMissing(t *testing.T) {
	_, problems := Module(module(t, goYAML, "", "README.md"))
	if len(problems) != 1 || !strings.HasPrefix(problems[0], "go.mod:") {
		t.Fatalf("problems = %q", problems)
	}
}

func TestValidateDescriptorProblemsShortCircuit(t *testing.T) {
	_, problems := Module(module(t, "name: x\n", ""))
	if len(problems) == 0 || strings.Contains(strings.Join(problems, ""), "not found") {
		t.Fatalf("problems = %q", problems)
	}
}

func TestValidateRealSamples(t *testing.T) {
	var dirs []string
	for _, eco := range []string{"go", "python"} {
		found, err := filepath.Glob("../../samples/" + eco + "/*")
		if err != nil || len(found) == 0 {
			t.Fatalf("no %s samples found: %v", eco, err)
		}
		dirs = append(dirs, found...)
	}
	for _, d := range dirs {
		t.Run(filepath.Base(d), func(t *testing.T) {
			if _, problems := Module(d); len(problems) != 0 {
				t.Fatal(problems)
			}
		})
	}
}

func TestValidateVersionFormat(t *testing.T) {
	tests := []struct {
		version string
		want    []string
	}{
		{"0.1.0", nil},
		{"1.0", []string{"version: 1.0 is not MAJOR.MINOR.PATCH (e.g. 0.1.0)"}},
		{"v1.2.3", []string{"version: v1.2.3 is not MAJOR.MINOR.PATCH (e.g. 0.1.0)"}},
	}
	for _, tt := range tests {
		t.Run(tt.version, func(t *testing.T) {
			y := strings.Replace(goYAML, "version: 0.1.0", "version: "+tt.version, 1)
			_, problems := Module(module(t, y, goodMod, "README.md"))
			if strings.Join(problems, "|") != strings.Join(tt.want, "|") {
				t.Errorf("problems = %q, want %q", problems, tt.want)
			}
		})
	}
}
