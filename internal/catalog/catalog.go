// Package catalog lists the modules a provider holds.
package catalog

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strconv"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
)

// Module is a descriptor plus where it was found.
type Module struct {
	descriptor.Descriptor
	Repo string `json:"repo"`
	Tag  string `json:"tag"`
}

var semver = regexp.MustCompile(`^v(\d+)\.(\d+)\.(\d+)$`)

func parseSemver(tag string) ([3]int, bool) {
	m := semver.FindStringSubmatch(tag)
	if m == nil {
		return [3]int{}, false
	}
	var v [3]int
	for i := range v {
		n, err := strconv.Atoi(m[i+1])
		if err != nil {
			return [3]int{}, false
		}
		v[i] = n
	}
	return v, true
}

// Latest returns the highest vMAJOR.MINOR.PATCH tag. Other tags are ignored.
func Latest(tags []string) (string, bool) {
	best, found := "", false
	var bv [3]int
	for _, t := range tags {
		v, ok := parseSemver(t)
		if !ok {
			continue
		}
		if !found || v[0] > bv[0] || (v[0] == bv[0] && (v[1] > bv[1] || (v[1] == bv[1] && v[2] > bv[2]))) {
			best, bv, found = t, v, true
		}
	}
	return best, found
}

// Load reads every repo's descriptor at its latest tag. Modules are sorted by
// name. Repos with no semver tag are skipped silently; repos whose descriptor
// is missing or invalid at the tag are skipped with a warning.
func Load(ctx context.Context, p provider.Provider) ([]Module, []string, error) {
	repos, err := p.List(ctx)
	if err != nil {
		return nil, nil, err
	}
	var mods []Module
	var warnings []string
	for _, repo := range repos {
		tags, err := p.Tags(ctx, repo)
		if err != nil {
			return nil, nil, fmt.Errorf("%s: %w", repo, err)
		}
		tag, ok := Latest(tags)
		if !ok {
			continue
		}
		data, err := p.ReadFile(ctx, repo, tag, "module.yaml")
		if err != nil {
			warnings = append(warnings, fmt.Sprintf("%s: skipped, no module.yaml at %s", repo, tag))
			continue
		}
		d, problems := descriptor.Parse(data, repo)
		if len(problems) > 0 {
			warnings = append(warnings, fmt.Sprintf("%s: skipped, invalid module.yaml at %s: %s", repo, tag, problems[0]))
			continue
		}
		mods = append(mods, Module{Descriptor: d, Repo: repo, Tag: tag})
	}
	sort.SliceStable(mods, func(i, j int) bool { return mods[i].Name < mods[j].Name })
	return mods, warnings, nil
}

// Find returns the module called name.
func Find(mods []Module, name string) (Module, bool) {
	for _, m := range mods {
		if m.Name == name {
			return m, true
		}
	}
	return Module{}, false
}
