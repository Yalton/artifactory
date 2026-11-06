// Package project reads and writes a project's artifactory.yaml.
package project

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

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

// ProviderSpec returns f.Provider with a relative dir: path resolved against
// dir, the folder holding artifactory.yaml, so it does not depend on the cwd.
func (f File) ProviderSpec(dir string) string {
	if path, ok := strings.CutPrefix(f.Provider, "dir:"); ok && path != "" && !filepath.IsAbs(path) {
		return "dir:" + filepath.Join(dir, path)
	}
	return f.Provider
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
// project.godot, python for pyproject.toml or requirements.txt. More than one
// ecosystem, or none, is an error.
func Detect(dir string) (string, error) {
	has := func(name string) bool {
		_, err := os.Stat(filepath.Join(dir, name))
		return err == nil
	}
	var found, files []string
	for _, c := range []struct {
		eco   string
		files []string
	}{
		{"go", []string{"go.mod"}},
		{"godot-csharp", []string{"project.godot"}},
		{"python", []string{"pyproject.toml", "requirements.txt"}},
	} {
		for _, f := range c.files {
			if has(f) {
				found = append(found, c.eco)
				files = append(files, f)
				break
			}
		}
	}
	switch len(found) {
	case 0:
		return "", errors.New("no go.mod, project.godot, pyproject.toml or requirements.txt found; pass --ecosystem")
	case 1:
		return found[0], nil
	}
	return "", fmt.Errorf("found %s; pass --ecosystem", strings.Join(files, " and "))
}
