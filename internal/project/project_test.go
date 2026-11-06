package project

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestDetect(t *testing.T) {
	tests := []struct {
		name    string
		files   []string
		want    string
		wantErr bool
	}{
		{"go", []string{"go.mod"}, "go", false},
		{"godot", []string{"project.godot"}, "godot-csharp", false},
		{"pyproject", []string{"pyproject.toml"}, "python", false},
		{"requirements", []string{"requirements.txt"}, "python", false},
		{"pyproject and requirements", []string{"pyproject.toml", "requirements.txt"}, "python", false},
		{"both", []string{"go.mod", "project.godot"}, "", true},
		{"go and python", []string{"go.mod", "requirements.txt"}, "", true},
		{"neither", nil, "", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			for _, f := range tt.files {
				os.WriteFile(filepath.Join(dir, f), nil, 0o644)
			}
			got, err := Detect(dir)
			if got != tt.want || (err != nil) != tt.wantErr {
				t.Errorf("got %q, %v", got, err)
			}
		})
	}
}

func TestProjectRoundTrip(t *testing.T) {
	dir := t.TempDir()
	in := File{Ecosystem: "go", Provider: "dir:/x", Modules: []Entry{{Name: "b", Version: "1.0.0"}, {Name: "a"}}}
	if err := Save(dir, in); err != nil {
		t.Fatal(err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	want := File{Ecosystem: "go", Provider: "dir:/x", Modules: []Entry{{Name: "a"}, {Name: "b", Version: "1.0.0"}}}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v", got)
	}
	raw, _ := os.ReadFile(filepath.Join(dir, FileName))
	if string(raw) == "" || filepath.Base(FileName) != "artifactory.yaml" {
		t.Errorf("bad file")
	}
}
