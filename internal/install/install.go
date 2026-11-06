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
	if m.Ecosystem == descriptor.GodotCSharp {
		dir := filepath.Join(projectDir, "addons", m.Name)
		if _, err := os.Stat(dir); err != nil {
			return "", fmt.Errorf("%s not found after install: %w", dir, err)
		}
		return dir, nil
	}
	path, err := GoModulePath(m.Install)
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

// GoModulePath extracts the module path from a `go get [flags] path[@ver]` line.
func GoModulePath(line string) (string, error) {
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

// Installed reads the installed copy's module.yaml for each named module in
// projectDir, an ecosystem project, without touching the network. A godot-csharp
// module is read from addons/<Name>; a go module from the module cache
// directory of whichever dependency in the build list carries a module.yaml
// with that name. Names whose installed descriptor cannot be found or is
// invalid are left out of the result.
func Installed(projectDir, ecosystem string, names []string) map[string]descriptor.Descriptor {
	want := map[string]bool{}
	for _, n := range names {
		want[n] = true
	}
	found := map[string]descriptor.Descriptor{}
	if len(want) == 0 {
		return found
	}
	if ecosystem == descriptor.GodotCSharp {
		for n := range want {
			if d, err := descriptor.Load(filepath.Join(projectDir, "addons", n)); err == nil && d.Name == n {
				found[n] = d
			}
		}
		return found
	}
	for _, dir := range goModuleDirs(projectDir) {
		d, err := descriptor.Load(dir)
		if err != nil || !want[d.Name] || d.Ecosystem != ecosystem {
			continue
		}
		if _, dup := found[d.Name]; !dup {
			found[d.Name] = d
		}
	}
	return found
}

// goModuleDirs lists the module cache directories of projectDir's
// dependencies with the network, toolchain downloads and go.mod updates all
// off. Modules not in the cache have no directory and are skipped; any
// failure yields what was listed before it.
func goModuleDirs(projectDir string) []string {
	cmd := exec.Command("go", "list", "-m", "-e", "-f", "{{if not .Main}}{{.Dir}}{{end}}", "all")
	cmd.Dir = projectDir
	cmd.Env = append(os.Environ(), "GOPROXY=off", "GOFLAGS=-mod=readonly", "GOTOOLCHAIN=local")
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	_ = cmd.Run()
	var dirs []string
	for _, l := range strings.Split(stdout.String(), "\n") {
		if l = strings.TrimSpace(l); l != "" {
			dirs = append(dirs, l)
		}
	}
	return dirs
}
