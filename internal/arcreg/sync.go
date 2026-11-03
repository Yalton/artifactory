package arcreg

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"path"
	"path/filepath"
	"strings"
)

// Source marks arc registry entries that artifactory owns.
const Source = "artifactory"

// Entry mirrors the arc module fields that `arc module set` takes. Paths are
// relative to the project directory; Sync makes them relative to the git top
// level.
type Entry struct {
	ID      string
	Summary string
	Paths   []string
	Covers  []string
	Entry   []string
	Import  string
	Rules   []string
	// Keep marks a module that could not be built into an entry this time:
	// Sync leaves its registered entry alone instead of removing it.
	Keep bool
}

// Toplevel returns the git top level of dir, or dir when it is not in a
// repository.
func Toplevel(dir string) string {
	out, err := run(dir, "git", "rev-parse", "--show-toplevel")
	if err != nil {
		return dir
	}
	return strings.TrimSpace(out)
}

// Sync registers mods with arc (`arc module set`, which replaces the whole
// entry) and removes `source: artifactory` entries not in mods. It runs arc
// from the git top level of projectDir. Failures are warnings: the install
// that called Sync still succeeded.
func Sync(projectDir string, mods []Entry) (warnings []string) {
	_, warnings = SyncCount(projectDir, mods)
	return warnings
}

// SyncCount is Sync that also returns how many modules arc's registry holds
// afterwards, from any source. The count is 0 when the registry cannot be
// listed.
func SyncCount(projectDir string, mods []Entry) (count int, warnings []string) {
	top := Toplevel(projectDir)
	warn := func(format string, args ...any) {
		warnings = append(warnings, "arc: "+fmt.Sprintf(format, args...))
	}
	prefix, perr := prefixOf(projectDir, top)
	if perr != nil {
		warn("cannot place %s inside %s: %v", projectDir, top, perr)
	}

	keep := map[string]bool{}
	for _, m := range mods {
		keep[m.ID] = true
		if m.Keep {
			continue
		}
		args := []string{"module", "set", m.ID, "--summary", m.Summary}
		for _, p := range m.Paths {
			args = append(args, "--path", path.Join(prefix, p))
		}
		for _, c := range m.Covers {
			args = append(args, "--covers", c)
		}
		for _, e := range m.Entry {
			args = append(args, "--entry", e)
		}
		if m.Import != "" {
			args = append(args, "--import", m.Import)
		}
		for _, r := range m.Rules {
			args = append(args, "--rule", r)
		}
		args = append(args, "--source", Source)
		if out, err := run(top, "arc", args...); err != nil {
			warn("module set %s failed: %s", m.ID, detail(out, err))
		}
	}

	out, err := run(top, "arc", "module", "list", "--json")
	if err != nil {
		warn("module list failed, stale entries not removed: %s", detail(out, err))
		return 0, warnings
	}
	var list struct {
		Modules []struct {
			ID     string   `json:"id"`
			Source string   `json:"source"`
			Paths  []string `json:"paths"`
		} `json:"modules"`
	}
	if err := json.Unmarshal([]byte(out), &list); err != nil {
		warn("module list gave unreadable output, stale entries not removed: %v", err)
		return 0, warnings
	}
	count = len(list.Modules)
	for _, e := range list.Modules {
		if perr != nil || e.Source != Source || keep[e.ID] || !ownedBy(prefix, e.Paths) {
			continue
		}
		if out, err := run(top, "arc", "module", "rm", e.ID); err != nil {
			warn("module rm %s failed: %s", e.ID, detail(out, err))
		} else {
			count--
		}
	}
	return count, warnings
}

// prefixOf returns dir's path below the git top level, slash separated and
// empty at the top. A relative dir is made absolute first.
func prefixOf(dir, top string) (string, error) {
	a, err := filepath.Abs(dir)
	if err != nil {
		return "", err
	}
	if a, err = filepath.EvalSymlinks(a); err != nil {
		return "", err
	}
	b, err := filepath.Abs(top)
	if err != nil {
		return "", err
	}
	if b, err = filepath.EvalSymlinks(b); err != nil {
		return "", err
	}
	rel, err := filepath.Rel(b, a)
	if err != nil {
		return "", err
	}
	if rel == "." {
		return "", nil
	}
	return filepath.ToSlash(rel), nil
}

// run executes name with a timeout in dir. It returns stdout, or on failure
// the combined stderr and stdout text for detail.
func run(dir, name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), Timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		return strings.TrimSpace(stderr.String() + "\n" + stdout.String()), err
	}
	return stdout.String(), nil
}

func detail(out string, err error) string {
	out = strings.Join(strings.Fields(out), " ")
	if out == "" {
		return err.Error()
	}
	return out
}

// ownedBy reports whether a registry entry with paths belongs to the project
// at prefix (its top-level-relative directory, empty at the top level). An
// entry with no paths (a go import) belongs only to a project at the top.
func ownedBy(prefix string, paths []string) bool {
	if len(paths) == 0 {
		return prefix == ""
	}
	for _, p := range paths {
		if prefix != "" && !strings.HasPrefix(p, prefix+"/") {
			return false
		}
	}
	return true
}
