// Package provider hides where a catalog's module repos are stored.
package provider

import (
	"context"
	"fmt"
	"strings"
)

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

// Open returns the provider named by spec: "dir:<path>". Other schemes are
// added here.
func Open(spec string) (Provider, error) {
	scheme, rest, ok := strings.Cut(spec, ":")
	if !ok {
		return nil, fmt.Errorf("invalid provider %q: want scheme:location, e.g. dir:/path", spec)
	}
	switch scheme {
	case "dir":
		return openDir(rest)
	}
	return nil, fmt.Errorf("unknown provider scheme %q in %q", scheme, spec)
}
