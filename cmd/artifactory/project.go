package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/app"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/project"
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

// runInit writes the skill copies and artifactory.yaml, then the index.
func runInit(out *output, args []string) int {
	const use = "usage: artifactory init [--ecosystem E] [--provider SPEC] [--project DIR] [--scope all|none]"
	fs := newFlags("init")
	eco := fs.String("ecosystem", "", "ecosystem (default: detected)")
	spec := fs.String("provider", defaultProvider, "provider spec")
	dir := fs.String("project", ".", "project directory")
	scope := fs.String("scope", "all", "all: list every library module of the ecosystem in MODULES.md, marked not installed; none: list none")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 || (*scope != "all" && *scope != "none") {
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
	// Skills go first: artifactory.yaml blocks a second init, so a skill
	// write failure must leave nothing behind that stops a re-run.
	paths, err := app.WriteSkills(*dir, false)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	f := project.File{Ecosystem: *eco, Provider: *spec}
	if err := project.Save(*dir, f); err != nil {
		return out.fail(exitUsage, err.Error())
	}
	// --scope all puts every library module of the ecosystem in scope, not
	// installed, so the agent sees what exists before it writes its own.
	// A library that cannot be read leaves the scope empty, with a warning.
	if *scope == "all" {
		if p, err := resolveProvider("", *dir); err != nil {
			fmt.Fprintln(out.stderr, "warning: library not listed in MODULES.md: "+err.Error())
		} else if mods, _, err := catalog.Load(context.Background(), p); err != nil {
			fmt.Fprintln(out.stderr, "warning: library not listed in MODULES.md: "+err.Error())
		} else {
			for _, m := range mods {
				if m.Ecosystem == *eco {
					f.Modules = append(f.Modules, project.Entry{Name: m.Name})
				}
			}
			sort.Slice(f.Modules, func(i, j int) bool { return f.Modules[i].Name < f.Modules[j].Name })
			if err := project.Save(*dir, f); err != nil {
				return out.fail(exitUsage, err.Error())
			}
		}
	}
	if !out.json {
		for _, p := range paths {
			fmt.Fprintln(out.stdout, "wrote "+p)
		}
	}
	res, err := app.App{Refresh: refreshCache}.Index(context.Background(), *dir, false, app.ArcAuto)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	if paths == nil {
		paths = []string{}
	}
	printIndexAs(out, res, initResult{IndexResult: res, Skills: paths})
	return exitOK
}

// initResult is the --json shape of init: the index result plus the skill
// copies init wrote.
type initResult struct {
	app.IndexResult
	Skills []string `json:"skills"`
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
	return writeIndex(out, *dir, false, app.ArcAuto)
}

// runIndex rewrites MODULES.md and the AGENTS.md block.
func runIndex(out *output, args []string) int {
	fs := newFlags("index")
	dir := fs.String("project", ".", "project directory")
	only := fs.Bool("modules-only", false, "write MODULES.md only")
	arc := fs.String("arc", app.ArcAuto, "arc mode: auto, on or off")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory index [--project DIR] [--modules-only] [--arc auto|on|off]")
	}
	return writeIndex(out, *dir, *only, *arc)
}

// writeIndex re-indexes the project and prints the result.
func writeIndex(out *output, dir string, modulesOnly bool, arcMode string) int {
	res, err := app.App{Refresh: refreshCache}.Index(context.Background(), dir, modulesOnly, arcMode)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	printIndex(out, res)
	return exitOK
}

func printIndex(out *output, res app.IndexResult) { printIndexAs(out, res, res) }

// printIndexAs prints res's warnings and text, and v as the --json value.
func printIndexAs(out *output, res app.IndexResult, v any) {
	if res.Warning != "" && !out.json {
		fmt.Fprintln(out.stderr, "artifactory: warning: "+res.Warning)
	}
	if !out.json {
		for _, w := range res.Warnings {
			fmt.Fprintln(out.stderr, "artifactory: warning: "+w)
		}
	}
	out.result("wrote "+strings.Join(res.Written, ", "), v)
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
