package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
)

// resolveProvider opens the provider named by flagSpec. Task 4 adds the
// artifactory.yaml step here.
func resolveProvider(flagSpec string) (provider.Provider, error) {
	if flagSpec != "" {
		p, err := provider.Open(flagSpec)
		if err != nil {
			return nil, err
		}
		return maybeCache(p), nil
	}
	return nil, fmt.Errorf("no provider: pass --provider or run artifactory init")
}

// refreshCache is set by the global --refresh flag: skip cache reads.
var refreshCache bool

const cacheTTL = 10 * time.Minute

// maybeCache wraps remote (forgejo:) providers in the on-disk catalog cache.
func maybeCache(p provider.Provider) provider.Provider {
	if !strings.HasPrefix(p.Spec(), "forgejo:") {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	return provider.CachedRefresh(p, filepath.Join(home, ".cache", "artifactory"), cacheTTL, refreshCache)
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
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory catalog [--provider SPEC] [--ecosystem E]")
	}
	p, err := resolveProvider(*spec)
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
	p, err := resolveProvider(*spec)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	ctx := context.Background()
	mods, _, err := catalog.Load(ctx, p)
	if err != nil {
		return out.fail(exitUsage, err.Error())
	}
	m, ok := catalog.Find(mods, name)
	if !ok {
		return out.fail(exitProblems, "no module named "+name)
	}
	readme := ""
	if m.Docs != "" {
		if b, err := p.ReadFile(ctx, m.Repo, m.Tag, m.Docs); err == nil {
			readme = string(b)
		}
	}
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
	out.result(strings.TrimRight(sb.String(), "\n"), map[string]any{"module": m, "readme": readme})
	return exitOK
}
