package main

import (
	"context"
	"fmt"

	"repo.billbert.co/artifactory/artifactory/internal/app"
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
	var progress func(string)
	if !out.json {
		progress = func(s string) { fmt.Fprintln(out.stdout, s) }
	}
	res, err := app.App{Refresh: refreshCache}.Install(context.Background(), *dir, names, progress)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	if out.json {
		out.result("", res)
		return exitOK
	}
	printIndex(out, res.Index)
	return exitOK
}
