// Package project reads and writes a project's artifactory.yaml.
package project

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"gopkg.in/yaml.v3"
)

// FileName is the project file's name.
const FileName = "artifactory.yaml"

// Entry is one module in scope. An empty Version means in scope but not installed.
type Entry struct {
	Name    string `yaml:"name"`
	Version string `yaml:"version,omitempty"`
}

// File is the content of artifactory.yaml.
type File struct {
	Ecosystem string  `yaml:"ecosystem"`
	Provider  string  `yaml:"provider"`
	Modules   []Entry `yaml:"modules"`
}

// Load reads dir/artifactory.yaml. A missing file wraps os.ErrNotExist.
func Load(dir string) (File, error) {
	data, err := os.ReadFile(filepath.Join(dir, FileName))
	if err != nil {
		return File{}, err
	}
	var f File
	if err := yaml.Unmarshal(data, &f); err != nil {
		return File{}, fmt.Errorf("%s: %w", FileName, err)
	}
	return f, nil
}

// Save writes dir/artifactory.yaml with modules sorted by name.
func Save(dir string, f File) error {
	mods := append([]Entry{}, f.Modules...)
	sort.SliceStable(mods, func(i, j int) bool { return mods[i].Name < mods[j].Name })
	f.Modules = mods
	data, err := yaml.Marshal(f)
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, FileName), data, 0o644)
}

// Detect names the project's ecosystem: go for go.mod, godot-csharp for
// project.godot. Both or neither is an error.
func Detect(dir string) (string, error) {
	_, goErr := os.Stat(filepath.Join(dir, "go.mod"))
	_, godotErr := os.Stat(filepath.Join(dir, "project.godot"))
	hasGo, hasGodot := goErr == nil, godotErr == nil
	switch {
	case hasGo && hasGodot:
		return "", errors.New("both go.mod and project.godot found; pass --ecosystem")
	case hasGo:
		return "go", nil
	case hasGodot:
		return "godot-csharp", nil
	}
	return "", errors.New("no go.mod or project.godot found; pass --ecosystem")
}
