package main

import (
	"context"
	"errors"
	"fmt"

	"repo.billbert.co/artifactory/artifactory/internal/publish"
)

// runPublish validates, tests, pushes and tags the module in DIR (default ".").
func runPublish(out *output, args []string) int {
	const use = "usage: artifactory publish [DIR] [--provider SPEC] [--skip-tests]"
	dirs, rest := splitArgs(args)
	var skip bool
	rest, skip = extractFlag(rest, "skip-tests")
	fs := newFlags("publish")
	spec := fs.String("provider", "", "provider spec, e.g. dir:/path")
	if err := fs.Parse(rest); err != nil || len(dirs) > 1 || fs.NArg() > 0 {
		return out.fail(exitUsage, use)
	}
	dir := "."
	if len(dirs) == 1 {
		dir = dirs[0]
	}
	p, err := resolveProvider(*spec, "")
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	// Test output goes to stderr so --json stdout stays one value.
	res, err := publish.Publish(context.Background(), dir, p, publish.Options{SkipTests: skip}, out.stdout, out.stderr)
	if err != nil {
		var ce *publish.CheckError
		if errors.As(err, &ce) {
			return out.fail(exitProblems, err.Error())
		}
		return out.fail(exitUsage, err.Error())
	}
	out.result(fmt.Sprintf("published %s %s to %s", res.Name, res.Tag, res.PushURL), res)
	return exitOK
}
