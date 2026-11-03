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
	top := Toplevel(projectDir)
	prefix := ""
	if a, err := filepath.EvalSymlinks(projectDir); err == nil {
		if b, err := filepath.EvalSymlinks(top); err == nil {
			if rel, err := filepath.Rel(b, a); err == nil && rel != "." {
				prefix = filepath.ToSlash(rel)
			}
		}
	}
	warn := func(format string, args ...any) {
		warnings = append(warnings, "arc: "+fmt.Sprintf(format, args...))
	}

	keep := map[string]bool{}
	for _, m := range mods {
		keep[m.ID] = true
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
		return warnings
	}
	var list struct {
		Modules []struct {
			ID     string `json:"id"`
			Source string `json:"source"`
		} `json:"modules"`
	}
	if err := json.Unmarshal([]byte(out), &list); err != nil {
		warn("module list gave unreadable output, stale entries not removed: %v", err)
		return warnings
	}
	for _, e := range list.Modules {
		if e.Source != Source || keep[e.ID] {
			continue
		}
		if out, err := run(top, "arc", "module", "rm", e.ID); err != nil {
			warn("module rm %s failed: %s", e.ID, detail(out, err))
		}
	}
	return warnings
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
