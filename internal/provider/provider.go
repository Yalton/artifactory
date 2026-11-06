// Package provider hides where a catalog's module repos are stored.
package provider

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// ErrNotFound is returned (possibly wrapped) when a repo or file is missing.
var ErrNotFound = errors.New("not found")

// Provider is a place that holds one repo per module.
type Provider interface {
	// Spec returns the spec the provider was opened with, e.g. "dir:/abs/path".
	Spec() string
	// List returns the repo names, sorted.
	List(ctx context.Context) ([]string, error)
	// Tags returns the tags of repo, sorted.
	Tags(ctx context.Context, repo string) ([]string, error)
	// ReadFile returns the content of path in repo at ref.
	ReadFile(ctx context.Context, repo, ref, path string) ([]byte, error)
	// Ensure creates repo if it is missing and returns the URL to push to.
	Ensure(ctx context.Context, repo string) (pushURL string, err error)
}

// Open returns the provider named by spec: "dir:<path>" or
// "forgejo:<host>/<org>".
func Open(spec string) (Provider, error) {
	scheme, rest, ok := strings.Cut(spec, ":")
	if !ok {
		return nil, fmt.Errorf("invalid provider %q: want scheme:location, e.g. dir:/path", spec)
	}
	switch scheme {
	case "dir":
		return openDir(rest)
	case "forgejo":
		return openForgejo(rest)
	}
	return nil, fmt.Errorf("unknown provider scheme %q in %q", scheme, spec)
}

// HasTag reports whether repo has tag, reading past any cache so a publish
// check is never stale. A missing repo has no tags.
func HasTag(ctx context.Context, p Provider, repo, tag string) (bool, error) {
	tags, err := Uncached(p).Tags(ctx, repo)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return false, err
	}
	for _, t := range tags {
		if t == tag {
			return true, nil
		}
	}
	return false, nil
}
