package install

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

// VenvDir is the project's virtual environment, relative to the project.
// Python modules are installed into it and read from it, never from the
// system Python or another active environment.
const VenvDir = ".venv"

var pyIdent = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// PythonImportName returns the import package of a python module: the part
// before the first dot of its first entry (the profile writes entries as
// `rate_limiter.Limiter`).
func PythonImportName(entry []string) (string, error) {
	if len(entry) == 0 {
		return "", fmt.Errorf("entry is empty; the python profile names the import package there")
	}
	pkg, _, _ := strings.Cut(entry[0], ".")
	if !pyIdent.MatchString(pkg) {
		return "", fmt.Errorf("entry %q does not start with an import package name", entry[0])
	}
	return pkg, nil
}

// pythonOffline reports whether the environment points pip or uv at a local
// wheel directory, which means the git install line must not be used.
func pythonOffline() bool {
	return os.Getenv("PIP_FIND_LINKS") != "" || os.Getenv("UV_FIND_LINKS") != ""
}

// pythonInstallCmd picks the install command for a python module.
//
// Online (no PIP_FIND_LINKS or UV_FIND_LINKS) it is the descriptor's own
// install line. Offline it installs `<name>==<version>`:
//   - `uv add` when the project has a pyproject.toml, uv is on PATH and
//     UV_FIND_LINKS is set;
//   - else `uv pip install --python .venv/bin/python` when uv is on PATH and
//     UV_FIND_LINKS is set;
//   - else `.venv/bin/python -m pip install`.
//
// uv reads only UV_FIND_LINKS and pip only PIP_FIND_LINKS, so the tool follows
// the variable that is set. needVenv is true when .venv must exist first;
// `uv add` makes its own.
func pythonInstallCmd(projectDir string, m catalog.Module) (line string, needVenv bool) {
	if !pythonOffline() {
		return m.Install, !strings.HasPrefix(strings.TrimSpace(m.Install), "uv add ")
	}
	spec := shellQuote(m.Name + "==" + strings.TrimPrefix(m.Version, "v"))
	_, uvErr := exec.LookPath("uv")
	useUV := uvErr == nil && os.Getenv("UV_FIND_LINKS") != ""
	if _, err := os.Stat(filepath.Join(projectDir, "pyproject.toml")); err == nil && useUV {
		return "uv add " + spec, false
	}
	if useUV {
		return "uv pip install --python " + shellQuote(venvPython(projectDir)) + " " + spec, true
	}
	return shellQuote(venvPython(projectDir)) + " -m pip install " + spec, true
}

func venvPython(projectDir string) string {
	return filepath.Join(projectDir, VenvDir, "bin", "python")
}

func shellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

// pythonEnv activates the project's venv for an install command: VIRTUAL_ENV
// names it and its bin directory leads PATH, so a bare `pip` or `uv` in the
// install line acts on it.
func pythonEnv(projectDir string) []string {
	venv := filepath.Join(projectDir, VenvDir)
	if abs, err := filepath.Abs(venv); err == nil {
		venv = abs
	}
	return append(os.Environ(), "VIRTUAL_ENV="+venv, "PATH="+filepath.Join(venv, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// runPython installs m into projectDir's venv, creating the venv with
// `python3 -m venv` when the command needs one and none exists.
func runPython(ctx context.Context, projectDir string, m catalog.Module) error {
	line, needVenv := pythonInstallCmd(projectDir, m)
	if _, err := os.Stat(venvPython(projectDir)); err != nil && needVenv {
		cmd := exec.CommandContext(ctx, "python3", "-m", "venv", VenvDir)
		cmd.Dir = projectDir
		cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("install %s: create %s: %w", m.Name, VenvDir, err)
		}
	}
	cmd := exec.CommandContext(ctx, "sh", "-c", line)
	cmd.Dir = projectDir
	cmd.Env = pythonEnv(projectDir)
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("install %s: %s: %w", m.Name, line, err)
	}
	return nil
}

// pyFindScript prints, as JSON, where each requested distribution's
// module.yaml lives. Arguments are name=pkg, pkg being the import package
// the caller expects (may be empty). It reads only importlib.metadata, never
// imports the package, so a module's liveness print does not run.
const pyFindScript = `
import json, sys
from importlib import metadata
out = {}
for arg in sys.argv[1:]:
    name, _, pkg = arg.partition("=")
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        out[name] = {"missing": True}
        continue
    cands = sorted({f.parts[0] for f in (dist.files or []) if len(f.parts) == 2 and f.parts[1] == "module.yaml"})
    if pkg in cands:
        cands = [pkg]
    if len(cands) == 1:
        out[name] = {"dir": str(dist.locate_file(cands[0]))}
    elif cands:
        out[name] = {"error": "module.yaml is in several packages: " + ", ".join(cands)}
    else:
        out[name] = {"error": "the installed distribution has no <package>/module.yaml (it must ship as package data)"}
print(json.dumps(out))
`

type pyFound struct {
	Dir     string `json:"dir"`
	Missing bool   `json:"missing"`
	Error   string `json:"error"`
}

// pythonFind runs the venv's python with pyFindScript for want (name to
// expected import package). The error is set when the venv python cannot
// run at all.
func pythonFind(ctx context.Context, projectDir string, want map[string]string) (map[string]pyFound, error) {
	py := venvPython(projectDir)
	if _, err := os.Stat(py); err != nil {
		return nil, fmt.Errorf("no python virtual environment at %s", filepath.Join(projectDir, VenvDir))
	}
	args := []string{"-I", "-c", pyFindScript}
	for n, pkg := range want {
		args = append(args, n+"="+pkg)
	}
	cmd := exec.CommandContext(ctx, py, args...)
	cmd.Dir = projectDir
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s: %v: %s", py, err, strings.TrimSpace(stderr.String()))
	}
	var got map[string]pyFound
	if err := json.Unmarshal(stdout.Bytes(), &got); err != nil {
		return nil, fmt.Errorf("%s: bad output: %v", py, err)
	}
	return got, nil
}

// locatePython finds the import package directory holding m's module.yaml in
// projectDir's venv.
func locatePython(projectDir string, m catalog.Module) (string, error) {
	pkg, _ := PythonImportName(m.Entry)
	got, err := pythonFind(context.Background(), projectDir, map[string]string{m.Name: pkg})
	if err != nil {
		return "", err
	}
	f := got[m.Name]
	switch {
	case f.Missing || (f.Dir == "" && f.Error == ""):
		return "", fmt.Errorf("%s is not installed in %s", m.Name, filepath.Join(projectDir, VenvDir))
	case f.Error != "":
		return "", fmt.Errorf("%s: %s", m.Name, f.Error)
	}
	return f.Dir, nil
}

// loadPython reads and checks the module.yaml in dir, which must name the
// python module name.
func loadPython(dir, name string) (descriptor.Descriptor, error) {
	d, err := descriptor.Load(dir)
	if err != nil {
		return d, fmt.Errorf("%s: %w", dir, err)
	}
	if d.Name != name {
		return d, fmt.Errorf("%s names module %q", filepath.Join(dir, "module.yaml"), d.Name)
	}
	if d.Ecosystem != descriptor.Python {
		return d, fmt.Errorf("%s is a %s module", filepath.Join(dir, "module.yaml"), d.Ecosystem)
	}
	return d, nil
}

// installedPython is Installed for a python project: one venv python run
// finds every name's distribution, then each module.yaml is read and checked.
// A name with no installed distribution is not installed; one whose
// distribution lacks a usable module.yaml is a problem.
func installedPython(ctx context.Context, projectDir string, want map[string]bool, l Lookup) (Lookup, error) {
	q := map[string]string{}
	for n := range want {
		q[n] = ""
	}
	got, err := pythonFind(ctx, projectDir, q)
	if err != nil {
		return l, err
	}
	for n := range want {
		f := got[n]
		switch {
		case f.Missing || (f.Dir == "" && f.Error == ""):
		case f.Error != "":
			l.Problems[n] = f.Error
		default:
			if d, err := loadPython(f.Dir, n); err != nil {
				l.Problems[n] = err.Error()
			} else {
				l.Found[n] = Copy{Descriptor: d}
			}
		}
	}
	return l, nil
}
