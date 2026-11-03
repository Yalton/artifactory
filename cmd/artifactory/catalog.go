package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/app"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
)

// refreshCache is set by the global --refresh flag: skip cache reads.
var refreshCache bool

// resolveProvider opens the provider named by flagSpec, else the one in
// artifactory.yaml in projectDir ("" means the current directory).
func resolveProvider(flagSpec, projectDir string) (provider.Provider, error) {
	return app.App{Refresh: refreshCache}.ResolveProvider(flagSpec, projectDir)
}

// newFlags returns a quiet FlagSet for a command.
func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	return fs
}

// runCatalog lists the modules in the provider.
func runCatalog(out *output, args []string) int {
	fs := newFlags("catalog")
	spec := fs.String("provider", "", "provider spec, e.g. dir:/path")
	eco := fs.String("ecosystem", "", "only this ecosystem")
	proj := fs.String("project", "", "project directory holding artifactory.yaml")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory catalog [--provider SPEC] [--ecosystem E]")
	}
	p, err := resolveProvider(*spec, *proj)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	mods, warnings, err := catalog.Load(context.Background(), p)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	shown := []catalog.Module{}
	var lines []string
	for _, m := range mods {
		if *eco != "" && m.Ecosystem != *eco {
			continue
		}
		shown = append(shown, m)
		lines = append(lines, fmt.Sprintf("%s %s [%s] %s", m.Name, m.Tag, m.Ecosystem, m.Summary))
	}
	if warnings == nil {
		warnings = []string{}
	}
	if !out.json {
		for _, w := range warnings {
			fmt.Fprintln(out.stderr, "artifactory: warning: "+w)
		}
	}
	out.result(strings.Join(lines, "\n"), map[string]any{"modules": shown, "warnings": warnings})
	return exitOK
}

// runShow prints one module's descriptor and its README at the latest tag.
func runShow(out *output, args []string) int {
	fs := newFlags("show")
	spec := fs.String("provider", "", "provider spec, e.g. dir:/path")
	proj := fs.String("project", "", "project directory holding artifactory.yaml")
	// Allow the name before or after flags.
	var name string
	rest := args
	if len(rest) > 0 && !strings.HasPrefix(rest[0], "-") {
		name, rest = rest[0], rest[1:]
	}
	if err := fs.Parse(rest); err != nil {
		return out.fail(exitUsage, "usage: artifactory show NAME [--provider SPEC]")
	}
	if name == "" && fs.NArg() == 1 {
		name = fs.Arg(0)
	} else if fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory show NAME [--provider SPEC]")
	}
	if name == "" {
		return out.fail(exitUsage, "usage: artifactory show NAME [--provider SPEC]")
	}
	res, err := app.App{Refresh: refreshCache}.Show(context.Background(), *spec, *proj, name)
	if err != nil {
		return out.fail(app.Code(err), err.Error())
	}
	m, readme := res.Module, res.Readme
	var sb strings.Builder
	fmt.Fprintf(&sb, "%s %s (%s)\n%s\n\n", m.Name, m.Tag, m.Ecosystem, m.Summary)
	fmt.Fprintf(&sb, "replaces: %s\ninstall: %s\n", strings.Join(m.Replaces, "; "), m.Install)
	for _, s := range m.Setup {
		fmt.Fprintf(&sb, "setup: %s\n", s)
	}
	fmt.Fprintf(&sb, "entry: %s\nliveness: %s\ndocs: %s\nexample: %s\ntest: %s\n",
		strings.Join(m.Entry, ", "), m.Liveness, m.Docs, m.Example, m.Test)
	if readme != "" {
		sb.WriteString("\n" + strings.TrimRight(readme, "\n") + "\n")
	}
	out.result(strings.TrimRight(sb.String(), "\n"), res)
	return exitOK
}
