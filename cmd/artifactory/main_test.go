package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validYAML = `name: kvstore
ecosystem: go
version: 0.1.0
summary: A store.
replaces: [storing data]
install: go get repo.billbert.co/artifactory/kvstore
setup: []
entry: [kvstore.Open]
liveness: go list -deps
docs: README.md
example: README.md
test: go test ./...
`

func mod(t *testing.T, yaml string) string {
	t.Helper()
	dir := t.TempDir()
	files := map[string]string{
		"module.yaml": yaml, "README.md": "x",
		"go.mod": "module repo.billbert.co/artifactory/kvstore\n",
	}
	for n, b := range files {
		if err := os.WriteFile(filepath.Join(dir, n), []byte(b), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func TestRunValidateExitCodes(t *testing.T) {
	good := mod(t, validYAML)
	bad := mod(t, strings.Replace(validYAML, "ecosystem: go", "ecosystem: rust", 1))
	tests := []struct {
		name string
		args []string
		want int
	}{
		{"valid", []string{"validate", good}, 0},
		{"invalid", []string{"validate", bad}, 1},
		{"one bad of two", []string{"validate", good, bad}, 1},
		{"unknown command", []string{"frobnicate"}, 2},
		{"no args", nil, 2},
		{"help", []string{"help"}, 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var out, errb bytes.Buffer
			if got := run(tt.args, &out, &errb); got != tt.want {
				t.Errorf("exit = %d, want %d (stdout %q stderr %q)", got, tt.want, out.String(), errb.String())
			}
		})
	}
}

func TestRunValidateOutput(t *testing.T) {
	bad := mod(t, strings.Replace(validYAML, "ecosystem: go", "ecosystem: rust", 1))
	var out, errb bytes.Buffer
	run([]string{"validate", bad}, &out, &errb)
	if want := bad + ": ecosystem: must be one of godot-csharp, go\n"; !strings.Contains(out.String()+errb.String(), want) {
		t.Errorf("output %q %q lacks %q", out.String(), errb.String(), want)
	}
}

func TestRunValidateJSON(t *testing.T) {
	good := mod(t, validYAML)
	var out, errb bytes.Buffer
	if code := run([]string{"validate", "--json", good}, &out, &errb); code != 0 {
		t.Fatalf("exit %d", code)
	}
	var got struct {
		Modules []struct {
			Dir        string         `json:"dir"`
			Descriptor map[string]any `json:"descriptor"`
			Problems   []string       `json:"problems"`
		} `json:"modules"`
	}
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatalf("%v: %s", err, out.String())
	}
	if len(got.Modules) != 1 || got.Modules[0].Dir != good || got.Modules[0].Descriptor["name"] != "kvstore" || len(got.Modules[0].Problems) != 0 {
		t.Errorf("got %+v", got)
	}
}

func TestRunShowUnknownModule(t *testing.T) {
	var so, se bytes.Buffer
	code := run([]string{"show", "nope", "--provider", "dir:../../samples/go"}, &so, &se)
	if code != 1 || !strings.Contains(se.String(), "no module named nope") {
		t.Errorf("code=%d stderr=%q", code, se.String())
	}
}

func TestRunCatalogSamples(t *testing.T) {
	var so, se bytes.Buffer
	code := run([]string{"catalog", "--provider", "dir:../../samples/go"}, &so, &se)
	lines := strings.Split(strings.TrimSpace(so.String()), "\n")
	if code != 0 || len(lines) != 4 {
		t.Errorf("code=%d out=%q err=%q", code, so.String(), se.String())
	}
}

func TestRunCatalogNoProvider(t *testing.T) {
	var so, se bytes.Buffer
	code := run([]string{"catalog"}, &so, &se)
	if code != 2 || !strings.Contains(se.String(), "no provider: pass --provider or run artifactory init") {
		t.Errorf("code=%d err=%q", code, se.String())
	}
}

func TestRunShowSample(t *testing.T) {
	var so, se bytes.Buffer
	code := run([]string{"show", "kvstore", "--provider", "dir:../../samples/go"}, &so, &se)
	if code != 0 || !strings.Contains(so.String(), "kvstore") || !strings.Contains(so.String(), "v0.1.0") {
		t.Errorf("code=%d out=%q err=%q", code, so.String(), se.String())
	}
}
