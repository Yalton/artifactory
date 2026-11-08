package main

import (
	"context"
	"fmt"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/app"
)

const searchUsage = "usage: artifactory search WORDS... [--ecosystem E|all] [--provider SPEC]"

// runSearch ranks catalog modules against the given words. No match is not an
// error: it prints a gap notice and exits 0.
func runSearch(out *output, args []string) int {
	fs := newFlags("search")
	spec := fs.String("provider", "", "provider spec, e.g. dir:/path")
	eco := fs.String("ecosystem", "", "only this ecosystem (default: the project's; all for every ecosystem)")
	proj := fs.String("project", "", "project directory holding artifactory.yaml")
	// Words and flags may be mixed: parse, take one word, repeat.
	var words []string
	rest := args
	for {
		if err := fs.Parse(rest); err != nil {
			return out.fail(exitUsage, searchUsage)
		}
		if fs.NArg() == 0 {
			break
		}
		words = append(words, fs.Arg(0))
		rest = fs.Args()[1:]
	}
	if len(words) == 0 {
		return out.fail(exitUsage, searchUsage)
	}
	res, err := app.App{Refresh: refreshCache}.Search(context.Background(), *spec, *proj, words, *eco)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	hits := res.Hits
	if len(hits) == 0 {
		out.result(fmt.Sprintf("no module matches %q; record this as a gap", strings.Join(words, " ")), res)
		return exitOK
	}
	var lines []string
	for _, h := range hits {
		lines = append(lines, fmt.Sprintf("%s  %.0f  %s\ninstall: %s", h.Module.Name, h.Score, h.Module.Summary, h.Module.Install))
	}
	out.result(strings.Join(lines, "\n"), res)
	return exitOK
}
