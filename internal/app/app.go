// Package app holds the operations behind the artifactory commands. Each
// returns a value (the struct the CLI prints with --json) and an error. The
// CLI in cmd/artifactory and the MCP server in internal/mcpserver both call
// it, so the two cannot drift apart.
package app

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"repo.billbert.co/artifactory/artifactory/internal/arcreg"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/index"
	"repo.billbert.co/artifactory/artifactory/internal/install"
	"repo.billbert.co/artifactory/artifactory/internal/project"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
	"repo.billbert.co/artifactory/artifactory/internal/search"
)

// Exit codes carried by Error.
const (
	CodeProblems = 1 // the check found problems
	CodeUsage    = 2 // usage, configuration or environment error
)

// Error is a failure with the process exit code the CLI uses for it.
type Error struct {
	Code int
	Msg  string
}

func (e *Error) Error() string { return e.Msg }

func usageErr(err error) error    { return &Error{CodeUsage, err.Error()} }
func problemErr(msg string) error { return &Error{CodeProblems, msg} }

// Code returns the exit code for err: the Error's code, else CodeUsage.
func Code(err error) int {
	var e *Error
	if errors.As(err, &e) {
		return e.Code
	}
	return CodeUsage
}

const cacheTTL = 10 * time.Minute

// App runs operations. Refresh skips catalog cache reads.
type App struct {
	Refresh bool
}

// ResolveProvider opens the provider named by flagSpec, else the one in
// artifactory.yaml in projectDir ("" means the current directory). A relative
// dir: path in artifactory.yaml is relative to projectDir.
func (a App) ResolveProvider(flagSpec, projectDir string) (provider.Provider, error) {
	spec := flagSpec
	if spec == "" {
		if projectDir == "" {
			projectDir = "."
		}
		if f, err := project.Load(projectDir); err == nil {
			spec = f.ProviderSpec(projectDir)
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
	}
	if spec != "" {
		p, err := provider.Open(spec)
		if err != nil {
			return nil, err
		}
		return a.maybeCache(p), nil
	}
	return nil, fmt.Errorf("no provider: pass --provider or run artifactory init")
}

// maybeCache wraps remote (forgejo:) providers in the on-disk catalog cache.
func (a App) maybeCache(p provider.Provider) provider.Provider {
	if !strings.HasPrefix(p.Spec(), "forgejo:") {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	return provider.CachedRefresh(p, filepath.Join(home, ".cache", "artifactory"), cacheTTL, a.Refresh)
}

// SearchResult is the --json shape of search.
type SearchResult struct {
	Hits []search.Hit `json:"hits"`
}

// Search ranks catalog modules against words. No match is an empty result.
func (a App) Search(ctx context.Context, spec, projectDir string, words []string, eco string) (SearchResult, error) {
	p, err := a.ResolveProvider(spec, projectDir)
	if err != nil {
		return SearchResult{}, usageErr(err)
	}
	mods, _, err := catalog.Load(ctx, p)
	if err != nil {
		return SearchResult{}, usageErr(err)
	}
	switch eco {
	case "":
		// Inside a project, search its own ecosystem unless told otherwise.
		// An explicit --provider names another library: search all of it.
		if spec != "" {
			break
		}
		if projectDir == "" {
			projectDir = "."
		}
		f, err := project.Load(projectDir)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return SearchResult{}, usageErr(err)
		}
		eco = f.Ecosystem
	case EcosystemAll:
		eco = ""
	}
	hits := search.Rank(mods, words, eco)
	if hits == nil {
		hits = []search.Hit{}
	}
	return SearchResult{Hits: hits}, nil
}

// EcosystemAll as Search's eco searches every ecosystem, even inside a project.
const EcosystemAll = "all"

// ShowResult is the --json shape of show.
type ShowResult struct {
	Module catalog.Module `json:"module"`
	Readme string         `json:"readme"`
}

// Show returns one module and its README at the latest tag.
func (a App) Show(ctx context.Context, spec, projectDir, name string) (ShowResult, error) {
	p, err := a.ResolveProvider(spec, projectDir)
	if err != nil {
		return ShowResult{}, usageErr(err)
	}
	mods, _, err := catalog.Load(ctx, p)
	if err != nil {
		return ShowResult{}, usageErr(err)
	}
	m, ok := catalog.Find(mods, name)
	if !ok {
		return ShowResult{}, problemErr("no module named " + name)
	}
	readme := ""
	if m.Docs != "" {
		if b, err := p.ReadFile(ctx, m.Repo, m.Tag, m.Docs); err == nil {
			readme = string(b)
		}
	}
	return ShowResult{Module: m, Readme: readme}, nil
}

// IndexResult is the --json shape of index.
type IndexResult struct {
	Written []string `json:"written"`
	Modules int      `json:"modules"`
	// Arc is true when the preamble was rendered without the bullets arc's own
	// guidance replaces: arc is on and its registry holds a module.
	Arc bool `json:"arc"`
	// Warning is set when a registry exists but arc cannot be used.
	Warning string `json:"warning,omitempty"`
	// Warnings lists installed modules indexed from the catalog instead of
	// their installed copy (and why), installed copies whose version differs
	// from artifactory.yaml, and arc registration failures. The index itself
	// succeeded.
	Warnings []string `json:"warnings,omitempty"`
}

// Arc modes for Index: auto detects arc, on requires it, off ignores it.
const (
	ArcAuto = "auto"
	ArcOn   = "on"
	ArcOff  = "off"
)

// resolveArc decides whether the project is rendered for arc.
func resolveArc(dir, mode string) (bool, string, error) {
	switch mode {
	case "", ArcAuto:
		present, warn := arcreg.Detect(arcreg.Toplevel(dir))
		return present, warn, nil
	case ArcOff:
		return false, "", nil
	case ArcOn:
		if present, warn := arcreg.Detect(arcreg.Toplevel(dir)); !present {
			if warn == "" {
				warn = "no " + arcreg.RegistryPath
			}
			return false, "", usageErr(errors.New("--arc on: " + arcreg.RegistryPath + " and a working `arc module list --json` are required: " + warn))
		}
		return true, "", nil
	}
	return false, "", usageErr(errors.New("--arc must be auto, on or off"))
}

// Index rewrites MODULES.md and, unless modulesOnly, the AGENTS.md block.
// Each installed module is described by its installed copy's module.yaml
// (see install.Installed and moduleFor); in-scope modules not installed, and
// installed ones whose copy cannot be found or used, come from the catalog's
// latest tag, the latter with a warning. The provider is opened only when
// some module needs the catalog.
// arcMode is auto, on or off (empty means auto). A full index shows each
// module's install command as `artifactory install NAME`; modulesOnly keeps
// the raw install line.
func (a App) Index(ctx context.Context, dir string, modulesOnly bool, arcMode string) (IndexResult, error) {
	f, err := project.Load(dir)
	if err != nil {
		return IndexResult{}, usageErr(errors.New(loadProjectMsg(err)))
	}
	arc, warn, err := resolveArc(dir, arcMode)
	if err != nil {
		return IndexResult{}, err
	}
	opt := index.Options{CLIInstall: !modulesOnly}
	var ds []descriptor.Descriptor
	var reg []arcreg.Entry
	var skipped []string
	// Installed modules render from their installed module.yaml; the catalog
	// is loaded only for the rest, so a fully installed project needs no
	// provider. Every fallback to the catalog for an installed module warns.
	var notes []string
	var installed []string
	for _, e := range f.Modules {
		if e.Version != "" {
			installed = append(installed, e.Name)
		}
	}
	local, err := install.Installed(ctx, dir, f.Ecosystem, installed)
	if err != nil {
		notes = append(notes, "installed copies not read, using the catalog for all modules: "+err.Error())
	}
	var mods []catalog.Module
	if len(local.Found) < len(f.Modules) {
		p, err := a.ResolveProvider("", dir)
		if err != nil {
			return IndexResult{}, usageErr(err)
		}
		if mods, _, err = catalog.Load(ctx, p); err != nil {
			return IndexResult{}, usageErr(err)
		}
	}
	for _, e := range f.Modules {
		m, ok, note := moduleFor(e, local, mods)
		if note != "" {
			notes = append(notes, note)
		}
		if !ok {
			return IndexResult{}, problemErr("module " + e.Name + " is in scope but not in the catalog")
		}
		ds = append(ds, m.Descriptor)
		if e.Version != "" {
			ae, err := arcEntry(m)
			if err != nil {
				skipped = append(skipped, "arc: "+m.Name+" not registered: "+err.Error())
				reg = append(reg, arcreg.Entry{ID: m.Name, Keep: true})
				continue
			}
			reg = append(reg, ae)
		}
	}
	warnings := notes
	if arc {
		// Register first: arc's own rendered guidance exists only once its
		// registry holds a module, so the preamble drops its bullets then.
		n, w := arcreg.SyncCount(dir, reg)
		warnings = append(append(warnings, skipped...), w...)
		opt.Arc = n > 0
	}
	written := []string{"MODULES.md"}
	if err := os.WriteFile(filepath.Join(dir, "MODULES.md"), []byte(index.Render(f.Ecosystem, ds, opt)), 0o644); err != nil {
		return IndexResult{}, usageErr(err)
	}
	if !modulesOnly {
		if err := index.WriteAgents(filepath.Join(dir, "AGENTS.md"), index.AgentsBlock(f.Ecosystem, opt)); err != nil {
			return IndexResult{}, usageErr(err)
		}
		written = append(written, "AGENTS.md")
		// An agent folder made after init (by arc init, say) gets the skill
		// too. A failed copy only warns: the index itself is written.
		skills, err := WriteSkills(dir, true)
		if err != nil {
			warnings = append(warnings, "agent skill not copied: "+err.Error())
		}
		for _, p := range skills {
			if rel, err := filepath.Rel(dir, p); err == nil {
				p = rel
			}
			written = append(written, p)
		}
	}
	return IndexResult{Written: written, Modules: len(ds), Arc: opt.Arc, Warning: warn, Warnings: warnings}, nil
}

// moduleFor picks the descriptor for project entry e: its installed copy when
// local has exactly one (or, for a go name several dependencies carry, the
// one whose module path the catalog's install line names), else the catalog's
// latest. note is a warning for the index result, set when an installed
// module falls back to the catalog or its copy's version differs from the
// recorded one.
func moduleFor(e project.Entry, local install.Lookup, mods []catalog.Module) (m catalog.Module, ok bool, note string) {
	cat, inCat := catalog.Find(mods, e.Name)
	c, have := local.Found[e.Name]
	if cs := local.Ambiguous[e.Name]; len(cs) > 0 {
		var paths []string
		for _, x := range cs {
			paths = append(paths, x.Path)
		}
		want := ""
		if inCat {
			want, _ = install.GoModulePath(cat.Install)
		}
		for _, x := range cs {
			if want != "" && x.Path == want {
				c, have = x, true
			}
		}
		if !have {
			note = fmt.Sprintf("%s: installed copy not used, using the catalog: module.yaml named %s is in %d dependencies (%s) and the catalog names none of them",
				e.Name, e.Name, len(cs), strings.Join(paths, ", "))
		}
	}
	if why, bad := local.Problems[e.Name]; bad && !have {
		note = e.Name + ": installed copy not used, using the catalog: " + why
	}
	if !have {
		return cat, inCat, note
	}
	if strings.TrimPrefix(c.Descriptor.Version, "v") != strings.TrimPrefix(e.Version, "v") {
		note = fmt.Sprintf("%s: installed copy is version %s but %s records %s; indexing the installed copy",
			e.Name, c.Descriptor.Version, project.FileName, e.Version)
	}
	return catalog.Module{Descriptor: c.Descriptor}, true, note
}

// arcEntry maps an installed module's descriptor to its arc registry entry.
// Godot modules own addons/<Name>; go modules are imported by path; python
// modules by their import package, the first part of entry.
func arcEntry(m catalog.Module) (arcreg.Entry, error) {
	d := m.Descriptor
	e := arcreg.Entry{ID: m.Name, Summary: d.Summary, Covers: d.Replaces, Entry: d.Entry}
	switch d.Ecosystem {
	case descriptor.GodotCSharp:
		e.Paths = []string{"addons/" + m.Name + "/**"}
	case descriptor.Python:
		pkg, err := install.PythonImportName(d.Entry)
		if err != nil {
			return arcreg.Entry{}, err
		}
		e.Import = pkg
	default:
		p, err := install.GoModulePath(d.Install)
		if err != nil {
			return arcreg.Entry{}, err
		}
		e.Import = p
	}
	rules := []string{"Print `" + d.Liveness + "` at startup."}
	if len(d.Setup) > 0 {
		rules = append(rules, "Setup: "+strings.Join(d.Setup, "; ")+".")
	}
	e.Rules = []string{strings.Join(rules, " ")}
	return e, nil
}

// LoadProjectMsg turns a project.Load error into the CLI message.
func LoadProjectMsg(err error) string { return loadProjectMsg(err) }

func loadProjectMsg(err error) string {
	if os.IsNotExist(err) {
		return project.FileName + " not found: run artifactory init"
	}
	return err.Error()
}

// Installed is one module installed by Install.
type Installed struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// InstallResult is the --json shape of install.
type InstallResult struct {
	Installed []Installed `json:"installed"`
	// Index is the re-index that ran last; Skipped lists modules that were
	// already installed. Neither appears in JSON.
	Index   IndexResult `json:"-"`
	Skipped []Installed `json:"-"`
}

// Install runs each module's install line and records the installed version.
// All names are checked first. Each success is saved at once, so a failure
// stops at that module with earlier modules still recorded; the project is
// then re-indexed and the error and result name the modules installed. progress, if
// non-nil, is called with a line per skipped or installed module as it
// happens.
func (a App) Install(ctx context.Context, dir string, names []string, progress func(string)) (InstallResult, error) {
	say := func(s string) {
		if progress != nil {
			progress(s)
		}
	}
	res := InstallResult{Installed: []Installed{}}
	f, err := project.Load(dir)
	if err != nil {
		return res, usageErr(errors.New(loadProjectMsg(err)))
	}
	p, err := a.ResolveProvider("", dir)
	if err != nil {
		return res, usageErr(err)
	}
	mods, _, err := catalog.Load(ctx, p)
	if err != nil {
		return res, usageErr(err)
	}
	found := make([]catalog.Module, len(names))
	for i, n := range names {
		m, ok := catalog.Find(mods, n)
		if !ok {
			return res, problemErr("no module named " + n)
		}
		if m.Ecosystem != f.Ecosystem {
			return res, problemErr(fmt.Sprintf("%s is a %s module; this project is %s", n, m.Ecosystem, f.Ecosystem))
		}
		found[i] = m
	}
	for _, m := range found {
		if v := entryVersion(f.Modules, m.Name); v != "" {
			res.Skipped = append(res.Skipped, Installed{m.Name, v})
			say(fmt.Sprintf("%s already installed (v%s)", m.Name, strings.TrimPrefix(v, "v")))
			continue
		}
		v, err := install.RunProgress(ctx, dir, m, say)
		if err != nil {
			return a.partial(ctx, dir, res, problemErr(err.Error()))
		}
		f.Modules = setEntry(f.Modules, project.Entry{Name: m.Name, Version: v})
		if err := project.Save(dir, f); err != nil {
			return a.partial(ctx, dir, res, usageErr(err))
		}
		res.Installed = append(res.Installed, Installed{m.Name, v})
		say(fmt.Sprintf("installed %s (v%s)", m.Name, strings.TrimPrefix(v, "v")))
	}
	res.Index, err = a.Index(ctx, dir, false, ArcAuto)
	return res, err
}

// partial finishes an Install that failed with err. When earlier modules
// were installed it re-indexes the project so MODULES.md and AGENTS.md list
// them, and names them in the error.
func (a App) partial(ctx context.Context, dir string, res InstallResult, err error) (InstallResult, error) {
	if len(res.Installed) == 0 {
		return res, err
	}
	var e *Error
	errors.As(err, &e)
	var names []string
	for _, in := range res.Installed {
		names = append(names, fmt.Sprintf("%s (v%s)", in.Name, strings.TrimPrefix(in.Version, "v")))
	}
	msg := e.Msg + "; installed before the failure: " + strings.Join(names, ", ")
	idx, ierr := a.Index(ctx, dir, false, ArcAuto)
	if ierr != nil {
		msg += "; re-index failed: " + ierr.Error()
	} else {
		res.Index = idx
	}
	return res, &Error{e.Code, msg}
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
