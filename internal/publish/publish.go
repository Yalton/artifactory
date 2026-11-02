// Package publish validates a module, runs its tests and pushes it to a
// provider as the repo's main branch plus a v<version> tag.
package publish

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/provider"
	"repo.billbert.co/artifactory/artifactory/internal/validate"
)

// Result describes a finished publish.
type Result struct {
	Name         string `json:"name"`
	Tag          string `json:"tag"`
	PushURL      string `json:"push_url"`
	Split        bool   `json:"split"`
	TestsSkipped bool   `json:"tests_skipped"`
}

// Options tune Publish.
type Options struct {
	// SkipTests skips the module's test command (with a warning).
	SkipTests bool
}

// CheckError is a failed pre-publish check (validation, tag, tests, dirty
// tree). Callers map it to "the check found problems" rather than an
// environment error.
type CheckError struct{ Msg string }

func (e *CheckError) Error() string { return e.Msg }

var repoName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

func validRepoName(n string) bool {
	return repoName.MatchString(n) && !strings.HasSuffix(n, ".git")
}

// Publish runs the publish steps for the module in dir against p. Tags are
// pushed as lightweight tag refs and nothing is ever force-pushed. A module
// in a subfolder of its git repo is published as a synthesized commit of the
// folder's tree whose parent is the remote's current main, so main always
// fast-forwards (no dependency on the optional `git subtree`).
func Publish(ctx context.Context, dir string, p provider.Provider, opts Options, stdout, stderr io.Writer) (Result, error) {
	d, problems := validate.Module(dir)
	if len(problems) > 0 {
		return Result{}, &CheckError{"module has problems: " + strings.Join(problems, "; ")}
	}
	if !validRepoName(d.Name) {
		return Result{}, &CheckError{fmt.Sprintf("name %q is not a plain repo name (letters, digits, . _ -; not ending in .git)", d.Name)}
	}
	tag := "v" + d.Version
	tags, err := p.Tags(ctx, d.Name)
	if err != nil && !errors.Is(err, provider.ErrNotFound) {
		return Result{}, err
	}
	for _, t := range tags {
		if t == tag {
			return Result{}, &CheckError{tag + " already published; bump version in module.yaml"}
		}
	}

	absDir, err := filepath.Abs(dir)
	if err != nil {
		return Result{}, err
	}
	absDir, err = filepath.EvalSymlinks(absDir)
	if err != nil {
		return Result{}, err
	}
	top, err := runGit(ctx, absDir, "rev-parse", "--show-toplevel")
	if err != nil {
		return Result{}, fmt.Errorf("%s is not in a git work tree: %w", dir, err)
	}
	top, err = filepath.EvalSymlinks(strings.TrimSpace(top))
	if err != nil {
		return Result{}, err
	}
	status, err := runGit(ctx, absDir, "status", "--porcelain", "--", ".")
	if err != nil {
		return Result{}, err
	}
	if strings.TrimSpace(status) != "" {
		return Result{}, &CheckError{"uncommitted changes under " + dir + ": commit your changes first"}
	}

	res := Result{Name: d.Name, Tag: tag, TestsSkipped: opts.SkipTests}
	if opts.SkipTests {
		fmt.Fprintln(stderr, "warning: --skip-tests: module tests were not run")
	} else {
		cmd := exec.CommandContext(ctx, "sh", "-c", d.Test)
		cmd.Dir = absDir
		cmd.Stdout, cmd.Stderr = stderr, stderr
		if err := cmd.Run(); err != nil {
			return Result{}, &CheckError{fmt.Sprintf("tests failed (%s): %v", d.Test, err)}
		}
	}

	url, err := p.Ensure(ctx, d.Name)
	if err != nil {
		return Result{}, err
	}
	res.PushURL = url

	commit := "HEAD"
	if absDir != top {
		res.Split = true
		if commit, err = splitCommit(ctx, top, absDir, url, d.Name, d.Version); err != nil {
			return Result{}, err
		}
	}
	if _, err := runGit(ctx, top, "push", url, commit+":refs/heads/main"); err != nil {
		return Result{}, fmt.Errorf("push main: %w", err)
	}
	if _, err := runGit(ctx, top, "push", url, commit+":refs/tags/"+tag); err != nil {
		return Result{}, fmt.Errorf("push tag %s: %w", tag, err)
	}
	return res, nil
}

// splitCommit builds a commit whose tree is HEAD:<rel> and whose parent is
// the remote's main (none if the remote has no main yet).
func splitCommit(ctx context.Context, top, absDir, url, name, version string) (string, error) {
	rel, err := filepath.Rel(top, absDir)
	if err != nil {
		return "", err
	}
	tree, err := runGit(ctx, top, "rev-parse", "HEAD:"+filepath.ToSlash(rel))
	if err != nil {
		return "", err
	}
	args := []string{"commit-tree", strings.TrimSpace(tree), "-m", fmt.Sprintf("Publish %s v%s", name, version)}
	// ls-remote distinguishes "no main yet" (empty output) from real errors.
	refs, err := runGit(ctx, top, "ls-remote", url, "refs/heads/main")
	if err != nil {
		return "", fmt.Errorf("check remote main: %w", err)
	}
	if strings.TrimSpace(refs) != "" {
		if _, err := runGit(ctx, top, "fetch", "--no-tags", url, "refs/heads/main"); err != nil {
			return "", fmt.Errorf("fetch remote main: %w", err)
		}
		parent, err := runGit(ctx, top, "rev-parse", "FETCH_HEAD^{commit}")
		if err != nil {
			return "", err
		}
		args = append(args, "-p", strings.TrimSpace(parent))
	}
	c, err := runGit(ctx, top, args...)
	return strings.TrimSpace(c), err
}

// runGit runs git in dir and returns stdout; errors carry stderr.
func runGit(ctx context.Context, dir string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	var so, se bytes.Buffer
	cmd.Stdout, cmd.Stderr = &so, &se
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("git %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(se.String()))
	}
	return so.String(), nil
}
