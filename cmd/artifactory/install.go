package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/install"
	"repo.billbert.co/artifactory/artifactory/internal/project"
)

// runInstall runs each module's install line and records the installed
// version. All names are checked first. Each success is saved at once, so a
// failure stops at that module with earlier modules still recorded and
// artifactory.yaml and MODULES.md untouched for the failing one.
func runInstall(out *output, args []string) int {
	const use = "usage: artifactory install NAME... [--project DIR]"
	names, rest := splitArgs(args)
	fs := newFlags("install")
	dir := fs.String("project", ".", "project directory")
	if err := fs.Parse(rest); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, use)
	}
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
	ctx := context.Background()
	mods, _, err := catalog.Load(ctx, p)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	found := make([]catalog.Module, len(names))
	for i, n := range names {
		m, ok := catalog.Find(mods, n)
		if !ok {
			return out.fail(exitProblems, "no module named "+n)
		}
		if m.Ecosystem != f.Ecosystem {
			return out.fail(exitProblems, fmt.Sprintf("%s is a %s module; this project is %s", n, m.Ecosystem, f.Ecosystem))
		}
		found[i] = m
	}
	var installed []map[string]string
	for _, m := range found {
		if v := entryVersion(f.Modules, m.Name); v != "" {
			if !out.json {
				fmt.Fprintf(out.stdout, "%s already installed (v%s)\n", m.Name, strings.TrimPrefix(v, "v"))
			}
			continue
		}
		v, err := install.Run(ctx, *dir, m)
		if err != nil {
			return out.fail(exitProblems, err.Error())
		}
		f.Modules = setEntry(f.Modules, project.Entry{Name: m.Name, Version: v})
		if err := project.Save(*dir, f); err != nil {
			return out.fail(exitUsage, err.Error())
		}
		installed = append(installed, map[string]string{"name": m.Name, "version": v})
		if !out.json {
			fmt.Fprintf(out.stdout, "installed %s (v%s)\n", m.Name, strings.TrimPrefix(v, "v"))
		}
	}
	if out.json {
		return writeIndexQuiet(out, *dir, installed)
	}
	return writeIndex(out, *dir, false)
}

// writeIndexQuiet re-indexes, then prints one JSON object that includes installed.
func writeIndexQuiet(out *output, dir string, installed []map[string]string) int {
	var buf bytes.Buffer
	sink := &output{json: true, stdout: &buf, stderr: io.Discard}
	if code := writeIndex(sink, dir, false); code != exitOK {
		out.stdout.Write(buf.Bytes())
		return code
	}
	if installed == nil {
		installed = []map[string]string{}
	}
	out.result("", map[string]any{"installed": installed})
	return exitOK
}

func entryVersion(es []project.Entry, name string) string {
	for _, e := range es {
		if e.Name == name {
			return e.Version
		}
	}
	return ""
}

func setEntry(es []project.Entry, e project.Entry) []project.Entry {
	for i := range es {
		if es[i].Name == e.Name {
			es[i] = e
			return es
		}
	}
	return append(es, e)
}
