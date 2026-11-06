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

func venvPython(absDir string) string { return filepath.Join(absDir, VenvDir, "bin", "python") }

func shellQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

// pyPlan is how runPython installs one module.
type pyPlan struct {
	line      string // the shell command
	tool      string // "uv" or "pip"
	makeVenv  bool   // create .venv first
	ensurepip bool   // run ensurepip in .venv first
}

var (
	uvProjectTable = regexp.MustCompile(`(?m)^\s*\[project\]\s*$`)
	otherPyTool    = regexp.MustCompile(`(?m)^\s*\[tool\.(poetry|pdm)[\].]`)
)

// uvProject reports whether `uv add` may manage absDir: its pyproject.toml has
// a [project] table and no poetry or pdm configuration.
func uvProject(absDir string) bool {
	b, err := os.ReadFile(filepath.Join(absDir, "pyproject.toml"))
	return err == nil && uvProjectTable.Match(b) && !otherPyTool.Match(b)
}

// venvHasPip reports whether the venv python can run pip.
func venvHasPip(py string) bool {
	return exec.Command(py, "-I", "-c", "import importlib.util, sys; sys.exit(importlib.util.find_spec('pip') is None)").Run() == nil
}

func noProjectEnv() error {
	if v := os.Getenv("UV_PROJECT_ENVIRONMENT"); v != "" {
		return fmt.Errorf("UV_PROJECT_ENVIRONMENT=%s is set; artifactory installs python modules into %s only, so unset it", v, VenvDir)
	}
	return nil
}

// planPython picks the install command for python module m in absDir.
//
// Offline (PIP_FIND_LINKS or UV_FIND_LINKS set) it installs
// `<name>==<version>` from the local wheel folder only, never the git line:
//   - with uv on PATH and UV_FIND_LINKS set: `uv add` when the project is a
//     uv project (see uvProject), else `uv pip install --python .venv/bin/python`,
//     both with --offline --no-index --find-links;
//   - else with PIP_FIND_LINKS set: `.venv/bin/python -m pip install
//     --no-index --find-links`;
//   - else it fails: the tool that would run has no find-links of its own.
//
// Online it runs the descriptor's install line. A leading `pip install` is
// rewritten to `.venv/bin/python -m pip install` (or `uv pip install --python
// .venv/bin/python` when the venv has no pip and uv is on PATH), so the system
// pip never runs; `uv add` and `uv pip` lines are left alone, with the venv
// active.
//
// pip is always the venv's own: a missing .venv is created (with pip), and an
// existing one without pip gets ensurepip first. `uv add` makes its own
// .venv and refuses UV_PROJECT_ENVIRONMENT, which would put it elsewhere.
func planPython(absDir string, m catalog.Module) (pyPlan, error) {
	py := venvPython(absDir)
	qpy := shellQuote(py)
	_, statErr := os.Stat(py)
	venvExists := statErr == nil
	_, uvErr := exec.LookPath("uv")
	hasUV := uvErr == nil
	pipPlan := func(rest string) pyPlan {
		return pyPlan{line: qpy + " -m pip install" + rest, tool: "pip", makeVenv: !venvExists, ensurepip: venvExists && !venvHasPip(py)}
	}

	uvLinks, pipLinks := strings.Fields(os.Getenv("UV_FIND_LINKS")), strings.Fields(os.Getenv("PIP_FIND_LINKS"))
	if len(uvLinks)+len(pipLinks) > 0 {
		spec := " " + shellQuote(m.Name+"=="+strings.TrimPrefix(m.Version, "v"))
		links := func(ls []string) string {
			var b strings.Builder
			for _, l := range ls {
				b.WriteString(" --find-links " + shellQuote(l))
			}
			return b.String()
		}
		switch {
		case hasUV && len(uvLinks) > 0:
			flags := " --offline --no-index" + links(uvLinks)
			if uvProject(absDir) {
				if err := noProjectEnv(); err != nil {
					return pyPlan{}, err
				}
				return pyPlan{line: "uv add" + flags + spec, tool: "uv"}, nil
			}
			return pyPlan{line: "uv pip install --python " + qpy + flags + spec, tool: "uv", makeVenv: !venvExists}, nil
		case len(pipLinks) > 0:
			return pipPlan(" --no-index" + links(pipLinks) + spec), nil
		}
		return pyPlan{}, fmt.Errorf("offline install of %s: UV_FIND_LINKS is set but uv is not on PATH, and pip needs PIP_FIND_LINKS", m.Name)
	}

	line := strings.TrimSpace(m.Install)
	switch {
	case strings.HasPrefix(line, "uv add "):
		if err := noProjectEnv(); err != nil {
			return pyPlan{}, err
		}
		return pyPlan{line: line, tool: "uv"}, nil
	case strings.HasPrefix(line, "uv pip "):
		return pyPlan{line: line, tool: "uv", makeVenv: !venvExists}, nil
	case strings.HasPrefix(line, "pip install "):
		rest := strings.TrimPrefix(line, "pip install")
		if venvExists && hasUV && !venvHasPip(py) {
			return pyPlan{line: "uv pip install --python " + qpy + rest, tool: "uv"}, nil
		}
		return pipPlan(rest), nil
	}
	return pyPlan{line: line, makeVenv: !venvExists}, nil
}

// pythonEnv activates the project's venv for an install command: VIRTUAL_ENV
// names it and its bin directory leads PATH.
func pythonEnv(absDir string) []string {
	venv := filepath.Join(absDir, VenvDir)
	return append(os.Environ(), "VIRTUAL_ENV="+venv, "PATH="+filepath.Join(venv, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// commandHook, when set by tests, sees each python install command line.
var commandHook func(line string)

func runCmd(ctx context.Context, dir string, env []string, name string, args ...string) error {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	cmd.Env = env
	cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
	return cmd.Run()
}

// runPython installs m into absDir's venv as planPython says. say reports
// a created venv.
func runPython(ctx context.Context, absDir string, m catalog.Module, say func(string)) error {
	p, err := planPython(absDir, m)
	if err != nil {
		return fmt.Errorf("install %s: %w", m.Name, err)
	}
	venv := filepath.Join(absDir, VenvDir)
	if p.makeVenv {
		if err := exec.CommandContext(ctx, "python3", "-c", "import sys; sys.exit(sys.version_info < (3, 11))").Run(); err != nil {
			return fmt.Errorf("install %s: creating %s needs python3 3.11 or newer on PATH: %v", m.Name, venv, err)
		}
		if err := runCmd(ctx, absDir, nil, "python3", "-m", "venv", venv); err != nil {
			return fmt.Errorf("install %s: python3 -m venv %s: %w", m.Name, venv, err)
		}
		say("created " + VenvDir)
	}
	if p.ensurepip {
		if err := runCmd(ctx, absDir, nil, venvPython(absDir), "-m", "ensurepip"); err != nil {
			return fmt.Errorf("install %s: %s has no pip and ensurepip failed: %w", m.Name, venv, err)
		}
	}
	if commandHook != nil {
		commandHook(p.line)
	}
	if err := runCmd(ctx, absDir, pythonEnv(absDir), "sh", "-c", p.line); err != nil {
		return fmt.Errorf("install %s: %s: %w", m.Name, p.line, err)
	}
	return nil
}

// pyFindScript prints, as JSON, the package directories holding module.yaml
// in each named distribution. It reads only importlib.metadata, never imports
// the package, so a module's liveness print does not run. Only top-level
// import packages count; namespace packages are not supported.
const pyFindScript = `
import json, sys
from importlib import metadata
out = {}
for name in sys.argv[1:]:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        out[name] = {"missing": True}
        continue
    pkgs = sorted({f.parts[0] for f in (dist.files or [])
                   if len(f.parts) == 2 and f.parts[1] == "module.yaml"
                   and f.parts[0].isidentifier() and f.parts[0] != ".."
                   and not f.parts[0].endswith(".dist-info")})
    out[name] = {"dirs": [str(dist.locate_file(p)) for p in pkgs]}
print(json.dumps(out))
`

type pyFound struct {
	Dirs    []string `json:"dirs"`
	Missing bool     `json:"missing"`
}

// pythonFind runs the venv's python with pyFindScript for names. The error
// is set when the venv python cannot run at all.
func pythonFind(ctx context.Context, absDir string, names []string) (map[string]pyFound, error) {
	py := venvPython(absDir)
	if _, err := os.Stat(py); err != nil {
		return nil, fmt.Errorf("no python virtual environment at %s", filepath.Join(absDir, VenvDir))
	}
	cmd := exec.CommandContext(ctx, py, append([]string{"-I", "-c", pyFindScript}, names...)...)
	cmd.Dir = absDir
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

// choosePython picks the installed copy of name among the package dirs
// holding a module.yaml, and reads it: a sole package, else the one package
// whose own module.yaml's entry names it. Locate (so install) and Installed
// (so index) both use it and read the entry from the installed copy, so they
// always agree.
func choosePython(name string, dirs []string) (string, descriptor.Descriptor, error) {
	if len(dirs) == 0 {
		return "", descriptor.Descriptor{}, fmt.Errorf("%s: the installed distribution has no <package>/module.yaml in a top-level import package (it must ship as package data)", name)
	}
	pick := func(dir string) (string, descriptor.Descriptor, error) {
		d, err := loadPython(dir, name)
		return dir, d, err
	}
	if len(dirs) == 1 {
		return pick(dirs[0])
	}
	var match []string
	for _, dir := range dirs {
		if d, err := loadPython(dir, name); err == nil {
			if pkg, _ := PythonImportName(d.Entry); pkg == filepath.Base(dir) {
				match = append(match, dir)
			}
		}
	}
	if len(match) == 1 {
		return pick(match[0])
	}
	var pkgs []string
	for _, dir := range dirs {
		pkgs = append(pkgs, filepath.Base(dir))
	}
	return "", descriptor.Descriptor{}, fmt.Errorf("%s: module.yaml is in several packages (%s) and entry picks none", name, strings.Join(pkgs, ", "))
}

// locatePython finds the import package directory holding m's module.yaml in
// projectDir's venv and reads it.
func locatePython(projectDir string, m catalog.Module) (string, descriptor.Descriptor, error) {
	absDir, err := filepath.Abs(projectDir)
	if err != nil {
		return "", descriptor.Descriptor{}, err
	}
	got, err := pythonFind(context.Background(), absDir, []string{m.Name})
	if err != nil {
		return "", descriptor.Descriptor{}, err
	}
	f, ok := got[m.Name]
	if !ok || f.Missing {
		return "", descriptor.Descriptor{}, fmt.Errorf("%s is not installed in %s", m.Name, filepath.Join(absDir, VenvDir))
	}
	return choosePython(m.Name, f.Dirs)
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
// finds every name's distribution, then choosePython reads each copy. A name
// with no installed distribution is not installed; one whose distribution
// lacks a usable module.yaml is a problem.
func installedPython(ctx context.Context, projectDir string, want map[string]bool, l Lookup) (Lookup, error) {
	absDir, err := filepath.Abs(projectDir)
	if err != nil {
		return l, err
	}
	var names []string
	for n := range want {
		names = append(names, n)
	}
	got, err := pythonFind(ctx, absDir, names)
	if err != nil {
		return l, err
	}
	for _, n := range names {
		f, ok := got[n]
		if !ok || f.Missing {
			continue
		}
		if _, d, err := choosePython(n, f.Dirs); err != nil {
			l.Problems[n] = err.Error()
		} else {
			l.Found[n] = Copy{Descriptor: d}
		}
	}
	return l, nil
}
