package catalog

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/provider"
)

type fake struct {
	tags  map[string][]string
	files map[string]string // repo -> module.yaml
}

func (f fake) Spec() string { return "fake:" }
func (f fake) List(context.Context) ([]string, error) {
	var r []string
	for k := range f.tags {
		r = append(r, k)
	}
	return r, nil
}
func (f fake) Tags(_ context.Context, repo string) ([]string, error) { return f.tags[repo], nil }
func (f fake) ReadFile(_ context.Context, repo, ref, path string) ([]byte, error) {
	if s, ok := f.files[repo]; ok && path == "module.yaml" {
		return []byte(s), nil
	}
	return nil, fmt.Errorf("not found")
}
func (f fake) Ensure(context.Context, string) (string, error) { return "", nil }

func yamlFor(name string) string {
	return "name: " + name + "\necosystem: go\nversion: 0.1.0\nsummary: s\nreplaces: [x]\ninstall: i\nsetup: []\nentry: [e]\nliveness: l\ndocs: README.md\nexample: README.md\ntest: t\n"
}

func TestLatest(t *testing.T) {
	tests := []struct {
		tags []string
		want string
		ok   bool
	}{
		{[]string{"v0.1.0", "v0.10.0", "v0.2.0", "pre-stitchability"}, "v0.10.0", true},
		{[]string{"main"}, "", false},
		{nil, "", false},
	}
	for _, tt := range tests {
		got, ok := Latest(tt.tags)
		if got != tt.want || ok != tt.ok {
			t.Errorf("Latest(%v) = %q, %v", tt.tags, got, ok)
		}
	}
}

func TestLoadSkipsInvalidDescriptor(t *testing.T) {
	f := fake{
		tags:  map[string][]string{"good": {"v0.1.0"}, "bad": {"v0.1.0"}},
		files: map[string]string{"good": yamlFor("good"), "bad": "a: ["},
	}
	mods, warns, err := Load(context.Background(), f)
	if err != nil {
		t.Fatal(err)
	}
	if len(mods) != 1 || mods[0].Name != "good" || mods[0].Repo != "good" || mods[0].Tag != "v0.1.0" {
		t.Errorf("mods = %+v", mods)
	}
	if len(warns) != 1 || !strings.Contains(warns[0], "bad") {
		t.Errorf("warnings = %v", warns)
	}
}

func TestLoadSkipsUntagged(t *testing.T) {
	f := fake{tags: map[string][]string{"u": {"main"}}, files: map[string]string{"u": yamlFor("u")}}
	mods, warns, err := Load(context.Background(), f)
	if err != nil || len(mods) != 0 || len(warns) != 0 {
		t.Errorf("mods=%v warns=%v err=%v", mods, warns, err)
	}
}

func TestLoadSortedAndFind(t *testing.T) {
	f := fake{
		tags:  map[string][]string{"b": {"v1.0.0"}, "a": {"v1.0.0"}},
		files: map[string]string{"a": yamlFor("a"), "b": yamlFor("b")},
	}
	mods, _, _ := Load(context.Background(), f)
	if len(mods) != 2 || mods[0].Name != "a" {
		t.Fatalf("mods = %+v", mods)
	}
	if m, ok := Find(mods, "b"); !ok || m.Name != "b" {
		t.Errorf("Find b = %+v, %v", m, ok)
	}
	if _, ok := Find(mods, "zz"); ok {
		t.Error("Find zz found")
	}
}

func TestLoadSkipsRepoWhoseTagsFail(t *testing.T) {
	root := t.TempDir()
	good := filepath.Join(root, "good")
	os.Mkdir(good, 0o755)
	os.WriteFile(filepath.Join(good, "module.yaml"), []byte(yamlFor("good")), 0o644)
	// A folder that looks like a bare repo but is not one: git tag fails.
	broken := filepath.Join(root, "broken.git")
	os.MkdirAll(filepath.Join(broken, "objects"), 0o755)
	os.WriteFile(filepath.Join(broken, "HEAD"), []byte("garbage\n"), 0o644)
	p, err := provider.Open("dir:" + root)
	if err != nil {
		t.Fatal(err)
	}
	mods, warns, err := Load(context.Background(), p)
	if err != nil {
		t.Fatalf("Load error: %v", err)
	}
	if len(mods) != 1 || mods[0].Name != "good" {
		t.Errorf("mods = %+v", mods)
	}
	if len(warns) != 1 || !strings.HasPrefix(warns[0], "broken: skipped, cannot list tags") {
		t.Errorf("warnings = %v", warns)
	}
}
