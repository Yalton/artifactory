package descriptor

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validYAML = `name: FooKit
ecosystem: godot-csharp
version: 1.0.0
summary: Does foo things.
replaces: [foo handling]
install: git submodule add git@repo.billbert.co:artifactory/FooKit.git addons/FooKit
setup: []
entry: [Foo.Run]
liveness: "[FooKit] live"
docs: README.md
example: README.md
test: dotnet test
`

// mutate replaces the line starting with key+":" (or removes it when line is "").
func mutate(t *testing.T, key, line string) string {
	t.Helper()
	var out []string
	found := false
	for _, l := range strings.Split(strings.TrimRight(validYAML, "\n"), "\n") {
		if strings.HasPrefix(l, key+":") {
			found = true
			if line != "" {
				out = append(out, line)
			}
			continue
		}
		out = append(out, l)
	}
	if !found {
		t.Fatalf("key %s not in valid yaml", key)
	}
	return strings.Join(out, "\n") + "\n"
}

func TestParse(t *testing.T) {
	long := strings.Repeat("x", 100)
	tests := []struct {
		name   string
		yaml   string
		folder string
		want   []string // substrings, one per expected problem; nil means valid
	}{
		{"valid", validYAML, "FooKit", nil},
		{"setup absent ok", mutate(t, "setup", ""), "FooKit", nil},
		{"missing install and liveness", mutate(t, "install", ""), "FooKit", []string{"missing field: install"}},
		{"summary 100 chars", mutate(t, "summary", "summary: "+long), "FooKit", []string{"summary: must be one line"}},
		{"summary 99 chars ok", mutate(t, "summary", "summary: "+long[:99]), "FooKit", nil},
		{"summary multiline", mutate(t, "summary", `summary: "a\nb"`), "FooKit", []string{"summary: must be one line"}},
		{"replaces empty", mutate(t, "replaces", "replaces: []"), "FooKit", []string{"replaces: needs 1 to 5 items"}},
		{"replaces six", mutate(t, "replaces", "replaces: [a, b, c, d, e, f]"), "FooKit", []string{"replaces: needs 1 to 5 items"}},
		{"replaces five ok", mutate(t, "replaces", "replaces: [a, b, c, d, e]"), "FooKit", nil},
		{"replaces item 80 chars", mutate(t, "replaces", "replaces: ["+strings.Repeat("x", 80)+"]"), "FooKit", []string{"replaces: each item"}},
		{"replaces blank item", mutate(t, "replaces", `replaces: [" "]`), "FooKit", []string{"replaces: each item"}},
		{"godot name mismatch", mutate(t, "name", "name: BarKit"), "FooKit", []string{"BarKit"}},
		{"go name need not match folder", strings.Replace(mutate(t, "liveness", "liveness: go list"), "godot-csharp", "go", 1), "other", nil},
		{"python accepted, hyphenated marker, name need not match folder", strings.Replace(mutate(t, "liveness", `liveness: "[foo-bar] live"`), "godot-csharp", "python", 1), "other", nil},
		{"python liveness not marker", strings.Replace(mutate(t, "liveness", `liveness: "prints [foo-bar] live"`), "godot-csharp", "python", 1), "other", []string{"liveness: python"}},
		{"python liveness spaces", strings.Replace(mutate(t, "liveness", `liveness: "[foo bar] live"`), "godot-csharp", "python", 1), "other", []string{"liveness: python"}},
		{"godot liveness not marker", mutate(t, "liveness", `liveness: "prints [FooKit] live at startup"`), "FooKit", []string{"liveness: godot-csharp"}},
		{"unknown ecosystem", strings.Replace(validYAML, "godot-csharp", "rust", 1), "FooKit", []string{"ecosystem: must be one of godot-csharp, go, python"}},
		{"string field is list", mutate(t, "docs", "docs: [a]"), "FooKit", []string{"docs: must be a string"}},
		{"list field is string", mutate(t, "entry", "entry: Foo.Run"), "FooKit", []string{"entry: must be a list of strings"}},
		{"numeric version accepted", mutate(t, "version", "version: 1"), "FooKit", nil},
		{"not a mapping", "- a\n- b\n", "FooKit", []string{"must be a mapping"}},
		{"invalid yaml", "a: [", "FooKit", []string{"invalid YAML"}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, problems := Parse([]byte(tt.yaml), tt.folder)
			if len(problems) != len(tt.want) {
				t.Fatalf("problems = %q, want %d matching %q", problems, len(tt.want), tt.want)
			}
			for i, w := range tt.want {
				if !strings.Contains(problems[i], w) {
					t.Errorf("problem %d = %q, want substring %q", i, problems[i], w)
				}
			}
		})
	}
}

func TestParseMissingInstallAndLivenessAllReported(t *testing.T) {
	y := mutate(t, "install", "")
	y = strings.Replace(y, "liveness: \"[FooKit] live\"\n", "", 1)
	_, problems := Parse([]byte(y), "FooKit")
	joined := strings.Join(problems, "\n")
	if !strings.Contains(joined, "install") || !strings.Contains(joined, "liveness") {
		t.Errorf("problems = %q", problems)
	}
}

func TestParseNumericVersionText(t *testing.T) {
	for _, v := range []string{"1", "1.0", "0.10"} {
		d, problems := Parse([]byte(mutate(t, "version", "version: "+v)), "FooKit")
		if len(problems) != 0 || d.Version != v {
			t.Errorf("version %s: got %q, problems %q", v, d.Version, problems)
		}
	}
}

func TestParseValues(t *testing.T) {
	d, problems := Parse([]byte(validYAML), "FooKit")
	if len(problems) != 0 {
		t.Fatal(problems)
	}
	if d.Name != "FooKit" || len(d.Replaces) != 1 || d.Replaces[0] != "foo handling" || d.Setup == nil {
		t.Errorf("descriptor = %+v", d)
	}
}

func TestLoad(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "FooKit")
	if err := os.Mkdir(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(dir); err == nil || !strings.Contains(err.(*Error).Problems[0], "module.yaml not found") {
		t.Fatalf("missing file err = %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "module.yaml"), []byte(validYAML), 0o644); err != nil {
		t.Fatal(err)
	}
	d, err := Load(dir)
	if err != nil || d.Name != "FooKit" {
		t.Fatalf("Load = %+v, %v", d, err)
	}
	if err := os.WriteFile(filepath.Join(dir, "module.yaml"), []byte(mutate(t, "name", "name: Bar")), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = Load(dir)
	if e, ok := err.(*Error); !ok || len(e.Problems) != 1 {
		t.Fatalf("mismatch err = %v", err)
	}
}
