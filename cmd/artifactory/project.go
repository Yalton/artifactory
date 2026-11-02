package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/app"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/project"
	"repo.billbert.co/artifactory/artifactory/skill"
)

const defaultProvider = "forgejo:repo.billbert.co/artifactory"

// splitArgs separates leading positional names from flags so `add A B --project D` works.
func splitArgs(args []string) (names, flags []string) {
	i := 0
	for i < len(args) && !strings.HasPrefix(args[i], "-") {
		i++
	}
	return args[:i], args[i:]
}

// runInit creates artifactory.yaml, then writes the index.
func runInit(out *output, args []string) int {
	const use = "usage: artifactory init [--ecosystem E] [--provider SPEC] [--project DIR]"
	fs := newFlags("init")
	eco := fs.String("ecosystem", "", "ecosystem (default: detected)")
	spec := fs.String("provider", defaultProvider, "provider spec")
	dir := fs.String("project", ".", "project directory")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, use)
	}
	if _, err := os.Stat(filepath.Join(*dir, project.FileName)); err == nil {
		return out.fail(exitProblems, project.FileName+" already exists in "+*dir)
	}
	if *eco == "" {
		e, err := project.Detect(*dir)
		if err != nil {
			return out.fail(exitUsage, err.Error())
		}
		*eco = e
	}
	if !contains(descriptor.Ecosystems, *eco) {
		return out.fail(exitUsage, "ecosystem must be one of "+strings.Join(descriptor.Ecosystems, ", "))
	}
	if err := project.Save(*dir, project.File{Ecosystem: *eco, Provider: *spec}); err != nil {
		return out.fail(exitUsage, err.Error())
	}
	paths, err := writeSkills(*dir)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	if !out.json {
		for _, p := range paths {
			fmt.Fprintln(out.stdout, "wrote "+p)
		}
	}
	return writeIndex(out, *dir, false)
}

// skillHarnessDirs are the agent harness folders that receive the skill.
var skillHarnessDirs = []string{".claude", ".agents", ".opencode"}

// writeSkills copies SKILL.md into skills/artifactory under each harness
// folder that already exists in dir. It never creates the harness folder.
func writeSkills(dir string) ([]string, error) {
	var paths []string
	for _, h := range skillHarnessDirs {
		if st, err := os.Stat(filepath.Join(dir, h)); err != nil || !st.IsDir() {
			continue
		}
		target := filepath.Join(dir, h, "skills", "artifactory")
		if err := os.MkdirAll(target, 0o755); err != nil {
			return paths, err
		}
		p := filepath.Join(target, "SKILL.md")
		if err := os.WriteFile(p, []byte(skill.Text()), 0o644); err != nil {
			return paths, err
		}
		paths = append(paths, p)
	}
	return paths, nil
}

// runAdd puts modules in scope without installing them.
func runAdd(out *output, args []string) int {
	const use = "usage: artifactory add NAME... [--project DIR]"
	names, rest := splitArgs(args)
	fs := newFlags("add")
	dir := fs.String("project", ".", "project directory")
	if err := fs.Parse(rest); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, use)
	}
	names = append(names, fs.Args()...)
	if len(names) == 0 {
		return out.fail(exitUsage, use)
	}
	f, err := project.Load(*dir)
	if err != nil {
		return out.fail(exitUsage, loadProjectMsg(err))
	}
	p, err := resolveProvider("", *dir)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	mods, _, err := catalog.Load(context.Background(), p)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	for _, n := range names {
		m, ok := catalog.Find(mods, n)
		if !ok {
			return out.fail(exitProblems, "no module named "+n)
		}
		if m.Ecosystem != f.Ecosystem {
			return out.fail(exitProblems, fmt.Sprintf("%s is a %s module; this project is %s", n, m.Ecosystem, f.Ecosystem))
		}
	}
	for _, n := range names {
		if !hasEntry(f.Modules, n) {
			f.Modules = append(f.Modules, project.Entry{Name: n})
		}
	}
	if err := project.Save(*dir, f); err != nil {
		return out.fail(exitUsage, err.Error())
	}
	return writeIndex(out, *dir, false)
}

// runIndex rewrites MODULES.md and the AGENTS.md block.
func runIndex(out *output, args []string) int {
	fs := newFlags("index")
	dir := fs.String("project", ".", "project directory")
	only := fs.Bool("modules-only", false, "write MODULES.md only")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory index [--project DIR] [--modules-only]")
	}
	return writeIndex(out, *dir, *only)
}

// writeIndex re-indexes the project and prints the result.
func writeIndex(out *output, dir string, modulesOnly bool) int {
	res, err := app.App{Refresh: refreshCache}.Index(context.Background(), dir, modulesOnly)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	printIndex(out, res)
	return exitOK
}

func printIndex(out *output, res app.IndexResult) {
	out.result("wrote "+strings.Join(res.Written, ", "), res)
}

func loadProjectMsg(err error) string { return app.LoadProjectMsg(err) }

func hasEntry(es []project.Entry, name string) bool {
	for _, e := range es {
		if e.Name == name {
			return true
		}
	}
	return false
}

func contains(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}
