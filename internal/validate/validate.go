// Package validate checks a module folder beyond its descriptor: the files
// the descriptor points at and, for Go modules, the go.mod path.
package validate

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

// Module validates the module in dir. It returns the descriptor (zero when the
// descriptor itself is invalid) and the problems found, empty when valid.
func Module(dir string) (descriptor.Descriptor, []string) {
	d, err := descriptor.Load(dir)
	if err != nil {
		if de, ok := err.(*descriptor.Error); ok {
			return descriptor.Descriptor{}, de.Problems
		}
		return descriptor.Descriptor{}, []string{err.Error()}
	}
	var problems []string
	if !isFile(filepath.Join(dir, d.Docs)) {
		problems = append(problems, fmt.Sprintf("docs: %s not found", d.Docs))
	}
	example, _, _ := strings.Cut(d.Example, "#")
	if !isFile(filepath.Join(dir, example)) {
		problems = append(problems, fmt.Sprintf("example: %s not found", example))
	}
	if d.Ecosystem == "go" {
		if path, ok := strings.CutPrefix(d.Install, "go get "); ok {
			problems = append(problems, checkGoMod(dir, strings.TrimSpace(path))...)
		}
	}
	return d, problems
}

func checkGoMod(dir, installPath string) []string {
	data, err := os.ReadFile(filepath.Join(dir, "go.mod"))
	if err != nil {
		return []string{"go.mod: not found"}
	}
	var mod string
	for _, line := range strings.Split(string(data), "\n") {
		if rest, ok := strings.CutPrefix(strings.TrimSpace(line), "module "); ok {
			rest, _, _ = strings.Cut(rest, "//")
			mod = strings.Trim(strings.TrimSpace(rest), `"`)
			break
		}
	}
	if mod == "" {
		return []string{"go.mod: no module line"}
	}
	if mod != installPath {
		return []string{fmt.Sprintf("go.mod: module %s does not match install path %s", mod, installPath)}
	}
	return nil
}

func isFile(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.Mode().IsRegular()
}
