package arcreg

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// logFakeArc puts an `arc` script on PATH that appends each call's argv (tab
// separated) to the returned log and serves list as `module list --json`.
// With ARC_FAIL=set, `module set` exits 1 with a validation problem.
func logFakeArc(t *testing.T, list string) (logPath string) {
	t.Helper()
	bin := t.TempDir()
	logPath = filepath.Join(bin, "calls.log")
	listPath := filepath.Join(bin, "list.json")
	if err := os.WriteFile(listPath, []byte(list), 0o644); err != nil {
		t.Fatal(err)
	}
	script := `#!/bin/sh
printf '%s\t' "$PWD" "$@" >> "` + logPath + `"
printf '\n' >> "` + logPath + `"
if [ "$1 $2" = "module list" ]; then cat "` + listPath + `"; exit 0; fi
if [ "$1 $2" = "module set" ] && [ "$ARC_FAIL" = set ]; then echo "problems: summary is required" >&2; exit 1; fi
exit 0
`
	if err := os.WriteFile(filepath.Join(bin, "arc"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return logPath
}

// calls returns the logged argv lists, without the working directory.
func calls(t *testing.T, logPath string) [][]string {
	t.Helper()
	b, _ := os.ReadFile(logPath)
	var out [][]string
	for _, line := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		if line == "" {
			continue
		}
		f := strings.Split(strings.TrimSuffix(line, "\t"), "\t")
		out = append(out, f[1:])
	}
	return out
}

func golden(t *testing.T) string {
	t.Helper()
	b, err := os.ReadFile("testdata/module-list.json")
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestSyncSetsGodotModule(t *testing.T) {
	log := logFakeArc(t, `{"modules":[]}`)
	Sync(t.TempDir(), []Entry{{
		ID: "CursorKit", Summary: "Cursor stack.", Paths: []string{"addons/CursorKit/**"},
		Covers: []string{"mouse modes"}, Entry: []string{"InputModeManager.Push"},
		Rules: []string{"Print `[CursorKit] live` at startup."},
	}})
	want := []string{"module", "set", "CursorKit", "--summary", "Cursor stack.", "--path", "addons/CursorKit/**",
		"--covers", "mouse modes", "--entry", "InputModeManager.Push",
		"--rule", "Print `[CursorKit] live` at startup.", "--source", "artifactory"}
	got := calls(t, log)
	if len(got) < 1 || !reflect.DeepEqual(got[0], want) {
		t.Errorf("got %q", got)
	}
}

func TestSyncGoModuleHasImportNoPath(t *testing.T) {
	log := logFakeArc(t, `{"modules":[]}`)
	Sync(t.TempDir(), []Entry{{ID: "cobra", Summary: "CLI.", Import: "github.com/spf13/cobra"}})
	got := calls(t, log)[0]
	joined := strings.Join(got, " ")
	if !strings.Contains(joined, "--import github.com/spf13/cobra") || strings.Contains(joined, "--path") {
		t.Errorf("got %q", got)
	}
}

func TestSyncRemovesOnlyStaleArtifactoryEntries(t *testing.T) {
	// The golden has GodotKit (source dir:...) and cobra (no source): neither
	// is ours, so neither is removed. Add artifactory entries around them.
	list := strings.Replace(golden(t), `"modules": [`, `"modules": [
    {"id": "Stale", "summary": "x", "source": "artifactory"},
    {"id": "Kept", "summary": "x", "source": "artifactory"},`, 1)
	log := logFakeArc(t, list)
	Sync(t.TempDir(), []Entry{{ID: "Kept", Summary: "x"}})
	var rm []string
	for _, c := range calls(t, log) {
		if c[1] == "rm" {
			rm = append(rm, c[2])
		}
	}
	if !reflect.DeepEqual(rm, []string{"Stale"}) {
		t.Errorf("rm %q", rm)
	}
}

func TestSyncSetFailureWarns(t *testing.T) {
	logFakeArc(t, `{"modules":[]}`)
	t.Setenv("ARC_FAIL", "set")
	w := Sync(t.TempDir(), []Entry{{ID: "A", Summary: "x"}})
	if len(w) != 1 || !strings.Contains(w[0], "module set A failed") || !strings.Contains(w[0], "summary is required") {
		t.Errorf("warnings %q", w)
	}
}

func TestSyncFromTopLevelWithRelativePaths(t *testing.T) {
	log := logFakeArc(t, `{"modules":[]}`)
	top := t.TempDir()
	if b, err := exec.Command("git", "-C", top, "init", "-q").CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, b)
	}
	sub := filepath.Join(top, "sub")
	os.MkdirAll(sub, 0o755)
	Sync(sub, []Entry{{ID: "K", Summary: "x", Paths: []string{"addons/K/**"}}})
	b, _ := os.ReadFile(log)
	first := strings.Split(strings.Split(string(b), "\n")[0], "\t")
	wantTop, _ := filepath.EvalSymlinks(top)
	gotTop, _ := filepath.EvalSymlinks(first[0])
	if gotTop != wantTop {
		t.Errorf("ran in %q, want %q", gotTop, wantTop)
	}
	if !strings.Contains(string(b), "--path\tsub/addons/K/**") {
		t.Errorf("paths not top-level relative: %q", b)
	}
}

func TestSyncStaleRemovalScopedToProject(t *testing.T) {
	list := `{"modules":[
{"id":"AOld","summary":"x","source":"artifactory","paths":["a/addons/AOld/**"]},
{"id":"BOld","summary":"x","source":"artifactory","paths":["b/addons/BOld/**"]},
{"id":"GoOld","summary":"x","source":"artifactory","import":"example.com/x"}]}`
	log := logFakeArc(t, list)
	top := t.TempDir()
	if b, err := exec.Command("git", "-C", top, "init", "-q").CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, b)
	}
	a := filepath.Join(top, "a")
	os.MkdirAll(a, 0o755)
	os.MkdirAll(filepath.Join(top, "b"), 0o755)
	rms := func() (rm []string) {
		for _, c := range calls(t, log) {
			if c[1] == "rm" {
				rm = append(rm, c[2])
			}
		}
		return
	}
	Sync(a, nil)
	if !reflect.DeepEqual(rms(), []string{"AOld"}) {
		t.Errorf("project a removed %q, want only AOld", rms())
	}
	os.Remove(log)
	Sync(top, nil)
	// A project at the top level contains every path, and owns path-less entries.
	if !reflect.DeepEqual(rms(), []string{"AOld", "BOld", "GoOld"}) {
		t.Errorf("top level removed %q, want all three", rms())
	}
}
