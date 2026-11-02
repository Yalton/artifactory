package publish

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/provider"
)

const yamlTmpl = `name: mymod
ecosystem: go
version: VERSION
summary: A module.
replaces: [things]
install: go get repo.billbert.co/artifactory/mymod
setup: []
entry: [mymod.Do]
liveness: go list -deps
docs: README.md
example: README.md#wiring
test: "TESTCMD"
`

func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func writeModule(t *testing.T, dir, version, testCmd string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	y := strings.NewReplacer("VERSION", version, "TESTCMD", testCmd).Replace(yamlTmpl)
	for name, body := range map[string]string{
		"module.yaml": y, "README.md": "x", "go.mod": "module repo.billbert.co/artifactory/mymod\n\ngo 1.24\n",
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

// setup returns a committed repo, the module dir and a dir: provider.
// With sub, the module lives in lib/mymod and the repo root holds more files.
func setup(t *testing.T, sub bool, testCmd string) (repo, mod string, p provider.Provider, root string) {
	t.Helper()
	repo, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	mod = repo
	if sub {
		mod = filepath.Join(repo, "lib", "mymod")
		os.WriteFile(filepath.Join(repo, "other.txt"), []byte("o"), 0o644)
	}
	git(t, repo, "init", "-q", "-b", "work")
	writeModule(t, mod, "0.1.0", testCmd)
	git(t, repo, "add", "-A")
	git(t, repo, "commit", "-qm", "init")
	root = t.TempDir()
	p, err = provider.Open("dir:" + root)
	if err != nil {
		t.Fatal(err)
	}
	return repo, mod, p, root
}

func pub(t *testing.T, mod string, p provider.Provider, skip bool) (Result, error, string) {
	var out, errb bytes.Buffer
	r, err := Publish(context.Background(), mod, p, Options{SkipTests: skip}, &out, &errb)
	return r, err, errb.String()
}

func TestPublishRootRepo(t *testing.T) {
	repo, mod, p, root := setup(t, false, "true")
	r, err, _ := pub(t, mod, p, false)
	if err != nil {
		t.Fatal(err)
	}
	bare := filepath.Join(root, "mymod.git")
	if r.Name != "mymod" || r.Tag != "v0.1.0" || r.Split || r.PushURL != bare {
		t.Errorf("result = %+v", r)
	}
	if got, want := git(t, bare, "rev-parse", "main"), git(t, repo, "rev-parse", "HEAD"); got != want {
		t.Errorf("main = %s, want %s", got, want)
	}
	if git(t, bare, "rev-parse", "v0.1.0^{commit}") != git(t, bare, "rev-parse", "main") {
		t.Error("tag not on main")
	}
}

func TestPublishSubfolderSplits(t *testing.T) {
	repo, mod, p, root := setup(t, true, "true")
	r, err, _ := pub(t, mod, p, false)
	if err != nil || !r.Split {
		t.Fatalf("r=%+v err=%v", r, err)
	}
	bare := filepath.Join(root, "mymod.git")
	files := strings.Fields(git(t, bare, "ls-tree", "-r", "--name-only", "main"))
	if strings.Join(files, ",") != "README.md,go.mod,module.yaml" {
		t.Errorf("main tree = %v", files)
	}
	first := git(t, bare, "rev-parse", "main")

	writeModule(t, mod, "0.2.0", "true")
	git(t, repo, "add", "-A")
	git(t, repo, "commit", "-qm", "bump")
	if _, err, _ := pub(t, mod, p, false); err != nil {
		t.Fatal(err)
	}
	second := git(t, bare, "rev-parse", "main")
	if second == first || git(t, bare, "rev-parse", "main^") != first {
		t.Errorf("main not fast-forwarded: %s -> %s", first, second)
	}
	if git(t, bare, "rev-parse", "v0.2.0^{commit}") != second {
		t.Error("v0.2.0 not on new main")
	}
}

func TestPublishRefusesExistingTag(t *testing.T) {
	_, mod, p, _ := setup(t, false, "touch ran")
	if _, err, _ := pub(t, mod, p, true); err != nil {
		t.Fatal(err)
	}
	os.Remove(filepath.Join(mod, "ran"))
	_, err, _ := pub(t, mod, p, false)
	if err == nil || err.Error() != "v0.1.0 already published; bump version in module.yaml" {
		t.Fatalf("err = %v", err)
	}
	if _, serr := os.Stat(filepath.Join(mod, "ran")); serr == nil {
		t.Error("test command ran")
	}
}

func TestPublishFailingTestPushesNothing(t *testing.T) {
	_, mod, p, root := setup(t, false, "exit 3")
	if _, err, _ := pub(t, mod, p, false); err == nil {
		t.Fatal("want error")
	}
	if _, err := os.Stat(filepath.Join(root, "mymod.git")); err == nil {
		t.Error("repo created")
	}
}

func TestPublishRefusesDirtyTree(t *testing.T) {
	for _, name := range []string{"README.md", "new.txt"} {
		_, mod, p, root := setup(t, false, "touch ran")
		os.WriteFile(filepath.Join(mod, name), []byte("changed"), 0o644)
		_, err, _ := pub(t, mod, p, false)
		if err == nil || !strings.Contains(err.Error(), "commit your changes first") {
			t.Errorf("%s: err = %v", name, err)
		}
		if _, serr := os.Stat(filepath.Join(mod, "ran")); serr == nil {
			t.Error("test ran before dirty check")
		}
		if _, serr := os.Stat(filepath.Join(root, "mymod.git")); serr == nil {
			t.Error("repo created")
		}
	}
}

func TestPublishSkipTests(t *testing.T) {
	_, mod, p, _ := setup(t, false, "exit 1")
	r, err, stderr := pub(t, mod, p, true)
	if err != nil || !r.TestsSkipped || !strings.Contains(stderr, "warning") {
		t.Errorf("r=%+v err=%v stderr=%q", r, err, stderr)
	}
}

func TestPublishRejectsBadName(t *testing.T) {
	for _, name := range []string{"../x", "a.git", ".hid", "a/b"} {
		if validRepoName(name) {
			t.Errorf("%q accepted", name)
		}
	}
	if !validRepoName("my-mod_1.x") {
		t.Error("good name rejected")
	}
}

func TestPublishNonFastForwardFails(t *testing.T) {
	repo, mod, p, root := setup(t, false, "true")
	if _, err, _ := pub(t, mod, p, false); err != nil {
		t.Fatal(err)
	}
	// Rewrite history locally so the next publish is not a descendant.
	git(t, repo, "checkout", "-q", "--orphan", "other")
	writeModule(t, mod, "0.2.0", "true")
	git(t, repo, "add", "-A")
	git(t, repo, "commit", "-qm", "unrelated")
	_, err, _ := pub(t, mod, p, false)
	if err == nil {
		t.Fatal("want rejection")
	}
	_ = root
}
