// Package install runs a module's own install line and finds the result.
package install

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

// ErrPythonUnsupported is returned where the CLI cannot yet handle python modules.
var ErrPythonUnsupported = errors.New("python modules are not supported yet by this command")

// Locate finds the installed copy of m in projectDir. For godot-csharp it is
// addons/<Name>. For go it is the module directory reported by `go list -m`
// for the module path in the install line.
func Locate(projectDir string, m catalog.Module) (string, error) {
	if m.Ecosystem == descriptor.Python {
		return "", ErrPythonUnsupported
	}
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
	if m.Ecosystem == descriptor.Python {
		return "", ErrPythonUnsupported
	}
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

// Copy is one installed copy of a module. Path is the go module path it was
// found under; it is empty for godot-csharp.
type Copy struct {
	Path       string
	Descriptor descriptor.Descriptor
}

// Lookup is what Installed found. A name in none of its maps has no
// installed copy.
type Lookup struct {
	// Found holds the names with exactly one valid installed copy.
	Found map[string]Copy
	// Ambiguous holds go names carried by more than one dependency's
	// module.yaml; the caller picks one by module path.
	Ambiguous map[string][]Copy
	// Problems holds names whose installed copy exists but cannot be used,
	// with the reason.
	Problems map[string]string
}

// Installed reads the installed copy's module.yaml for each named module in
// projectDir, an ecosystem project, without touching the network.
//
// A godot-csharp module is read from addons/<Name>; a name holding a path
// separator or ".." is a problem, never joined into a path. A go module is
// read from the module cache directory of whichever dependency in the build
// list carries a module.yaml with that name (see goModules). A module.yaml
// that is present but invalid, or names another module, is a problem.
//
// The error is set only when the go build list cannot be listed at all (go
// is missing, go.mod is missing or broken); the Lookup is then empty.
func Installed(ctx context.Context, projectDir, ecosystem string, names []string) (Lookup, error) {
	l := Lookup{Found: map[string]Copy{}, Ambiguous: map[string][]Copy{}, Problems: map[string]string{}}
	want := map[string]bool{}
	for _, n := range names {
		want[n] = true
	}
	if len(want) == 0 {
		return l, nil
	}
	if ecosystem == descriptor.GodotCSharp {
		for n := range want {
			if n == "" || n == "." || strings.ContainsAny(n, `/\`) || strings.Contains(n, "..") {
				l.Problems[n] = fmt.Sprintf("module name %q is not a folder name under addons/", n)
				continue
			}
			dir := filepath.Join(projectDir, "addons", n)
			if _, err := os.Stat(dir); err != nil {
				continue // not installed
			}
			d, err := descriptor.Load(dir)
			switch {
			case err != nil:
				l.Problems[n] = fmt.Sprintf("%s: %v", dir, err)
			case d.Name != n:
				l.Problems[n] = fmt.Sprintf("%s names module %q", filepath.Join(dir, "module.yaml"), d.Name)
			default:
				l.Found[n] = Copy{Descriptor: d}
			}
		}
		return l, nil
	}
	mods, err := goModules(ctx, projectDir)
	if err != nil {
		return l, err
	}
	copies := map[string][]Copy{}
	for _, gm := range mods {
		file := filepath.Join(gm.dir, "module.yaml")
		data, err := os.ReadFile(file)
		if err != nil {
			continue
		}
		d, problems := descriptor.Parse(data, filepath.Base(gm.dir))
		if len(problems) > 0 {
			var head struct {
				Name string `yaml:"name"`
			}
			if yaml.Unmarshal(data, &head) == nil && want[head.Name] {
				l.Problems[head.Name] = fmt.Sprintf("%s (module %s): %s", file, gm.path, strings.Join(problems, "; "))
			}
			continue
		}
		if want[d.Name] && d.Ecosystem == ecosystem {
			copies[d.Name] = append(copies[d.Name], Copy{Path: gm.path, Descriptor: d})
		}
	}
	for n, cs := range copies {
		delete(l.Problems, n) // a valid copy wins over an invalid one
		if len(cs) == 1 {
			l.Found[n] = cs[0]
		} else {
			l.Ambiguous[n] = cs
		}
	}
	return l, nil
}

type goModule struct{ path, dir string }

// goModules lists projectDir's dependencies that are in the module cache:
// `go list -m all` with GOPROXY=off, GOWORK=off and GOTOOLCHAIN=local, so
// nothing is downloaded and a go.work elsewhere does not change the build
// list. The user's GOFLAGS are kept, except that any -mod= flag is replaced
// by -mod=readonly: -mod=mod could rewrite go.mod during an index, and
// -mod=vendor cannot list "all", so module.yaml is always read from the
// module cache, never from vendor/. The main module is left out: it is the
// project itself, whose own module.yaml (if any) describes the project, not
// an installed module.
func goModules(ctx context.Context, projectDir string) ([]goModule, error) {
	cmd := exec.CommandContext(ctx, "go", "list", "-m", "-e", "-f", "{{if not .Main}}{{.Path}}\t{{.Dir}}{{end}}", "all")
	cmd.Dir = projectDir
	cmd.Env = append(os.Environ(), "GOPROXY=off", "GOWORK=off", "GOTOOLCHAIN=local", "GOFLAGS="+readonlyGoFlags(os.Getenv("GOFLAGS")))
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return nil, fmt.Errorf("go list -m all in %s: %s", projectDir, msg)
	}
	var mods []goModule
	for _, l := range strings.Split(stdout.String(), "\n") {
		path, dir, ok := strings.Cut(strings.TrimSpace(l), "\t")
		if ok && dir != "" {
			mods = append(mods, goModule{path, dir})
		}
	}
	return mods, nil
}

// readonlyGoFlags returns goflags with any -mod= flag replaced by -mod=readonly.
func readonlyGoFlags(goflags string) string {
	var out []string
	for _, f := range strings.Fields(goflags) {
		if !strings.HasPrefix(f, "-mod=") && !strings.HasPrefix(f, "--mod=") {
			out = append(out, f)
		}
	}
	return strings.Join(append(out, "-mod=readonly"), " ")
}
