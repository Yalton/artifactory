package provider

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// dirProvider treats each child folder of root as one repo. Children may be
// git repos (bare or not) or plain folders holding a module.yaml.
type dirProvider struct {
	root string
}

func openDir(path string) (*dirProvider, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	fi, err := os.Stat(abs)
	if err != nil {
		return nil, fmt.Errorf("provider dir:%s: %w", path, err)
	}
	if !fi.IsDir() {
		return nil, fmt.Errorf("provider dir:%s: not a directory", path)
	}
	return &dirProvider{root: abs}, nil
}

func (d *dirProvider) Spec() string { return "dir:" + d.root }

// List returns each child folder's name minus any .git suffix.
func (d *dirProvider) List(ctx context.Context) ([]string, error) {
	entries, err := os.ReadDir(d.root)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var names []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		n := strings.TrimSuffix(e.Name(), ".git")
		if n == "" || seen[n] {
			continue
		}
		seen[n] = true
		names = append(names, n)
	}
	sort.Strings(names)
	return names, nil
}

// path finds the folder for repo, preferring <repo>.git.
func (d *dirProvider) path(repo string) (string, error) {
	if repo == "" || repo != filepath.Base(repo) || repo == "." || repo == ".." {
		return "", fmt.Errorf("invalid repo name %q", repo)
	}
	for _, n := range []string{repo + ".git", repo} {
		p := filepath.Join(d.root, n)
		if fi, err := os.Stat(p); err == nil && fi.IsDir() {
			return p, nil
		}
	}
	return "", fmt.Errorf("repo %q in %s: %w", repo, d.root, ErrNotFound)
}

func isGit(p string) bool {
	if _, err := os.Stat(filepath.Join(p, ".git")); err == nil {
		return true
	}
	_, errH := os.Stat(filepath.Join(p, "HEAD"))
	_, errO := os.Stat(filepath.Join(p, "objects"))
	return errH == nil && errO == nil
}

// Tags lists a git repo's tags, or for a plain folder returns "v"+version
// from its module.yaml.
func (d *dirProvider) Tags(ctx context.Context, repo string) ([]string, error) {
	p, err := d.path(repo)
	if err != nil {
		return nil, err
	}
	if isGit(p) {
		out, err := runGit(ctx, p, "tag", "--list")
		if err != nil {
			return nil, err
		}
		tags := strings.Fields(string(out))
		sort.Strings(tags)
		return tags, nil
	}
	data, err := os.ReadFile(filepath.Join(p, "module.yaml"))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var v struct {
		Version yaml.Node `yaml:"version"`
	}
	if err := yaml.Unmarshal(data, &v); err != nil || v.Version.Kind != yaml.ScalarNode || v.Version.Value == "" {
		return nil, nil
	}
	return []string{"v" + v.Version.Value}, nil
}

// ReadFile reads path at ref from a git repo, or from the working tree of a
// plain folder (where ref is ignored).
func (d *dirProvider) ReadFile(ctx context.Context, repo, ref, path string) ([]byte, error) {
	p, err := d.path(repo)
	if err != nil {
		return nil, err
	}
	clean := filepath.Clean(path)
	if filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return nil, fmt.Errorf("invalid path %q", path)
	}
	if isGit(p) {
		if strings.HasPrefix(ref, "-") {
			return nil, fmt.Errorf("invalid ref %q", ref)
		}
		b, err := runGit(ctx, p, "show", ref+":"+filepath.ToSlash(clean))
		if err != nil && (strings.Contains(err.Error(), "does not exist") || strings.Contains(err.Error(), "exists on disk")) {
			return nil, fmt.Errorf("%s at %s: %w", path, ref, ErrNotFound)
		}
		return b, err
	}
	b, err := os.ReadFile(filepath.Join(p, clean))
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("%s: %w", path, ErrNotFound)
	}
	return b, err
}

// Ensure creates <repo>.git as a bare repo when the repo is missing and
// returns the repo's absolute path.
func (d *dirProvider) Ensure(ctx context.Context, repo string) (string, error) {
	if p, err := d.path(repo); err == nil {
		return p, nil
	}
	p := filepath.Join(d.root, repo+".git")
	if _, err := runGit(ctx, d.root, "init", "--bare", "-q", p); err != nil {
		return "", err
	}
	return p, nil
}

// runGit runs git in dir and returns stdout.
func runGit(ctx context.Context, dir string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("git %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return stdout.Bytes(), nil
}
