// Package install runs a module's own install line and finds the result.
package install

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

// Locate finds the installed copy of m in projectDir. For godot-csharp it is
// addons/<Name>. For go it is the module directory reported by `go list -m`
// for the module path in the install line.
func Locate(projectDir string, m catalog.Module) (string, error) {
	if m.Ecosystem == "godot-csharp" {
		dir := filepath.Join(projectDir, "addons", m.Name)
		if _, err := os.Stat(dir); err != nil {
			return "", fmt.Errorf("%s not found after install: %w", dir, err)
		}
		return dir, nil
	}
	path, err := goModulePath(m.Install)
	if err != nil {
		return "", err
	}
	cmd := exec.Command("go", "list", "-m", "-f", "{{.Dir}}", path)
	cmd.Dir = projectDir
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("go list -m %s: %v: %s", path, err, strings.TrimSpace(stderr.String()))
	}
	dir := strings.TrimSpace(stdout.String())
	if dir == "" {
		return "", fmt.Errorf("go list -m %s: no directory reported", path)
	}
	return dir, nil
}

// goModulePath extracts the module path from a `go get [flags] path[@ver]` line.
func goModulePath(line string) (string, error) {
	f := strings.Fields(line)
	if len(f) < 3 || f[0] != "go" || f[1] != "get" {
		return "", fmt.Errorf("install line %q is not a go get command", line)
	}
	for _, a := range f[2:] {
		if strings.HasPrefix(a, "-") {
			continue
		}
		path, _, _ := strings.Cut(a, "@")
		return path, nil
	}
	return "", fmt.Errorf("install line %q names no module", line)
}

// Run executes m.Install with sh -c in projectDir, streaming output to
// stderr, then reads the installed copy's module.yaml and returns its version.
func Run(ctx context.Context, projectDir string, m catalog.Module) (string, error) {
	cmd := exec.CommandContext(ctx, "sh", "-c", m.Install)
	cmd.Dir = projectDir
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("install %s: %w", m.Name, err)
	}
	dir, err := Locate(projectDir, m)
	if err != nil {
		return "", err
	}
	d, err := descriptor.Load(dir)
	if err != nil {
		return "", fmt.Errorf("installed copy of %s: %w", m.Name, err)
	}
	return d.Version, nil
}
