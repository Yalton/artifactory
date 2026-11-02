package provider

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func git(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, b)
	}
}

func TestDirProviderGitRepo(t *testing.T) {
	root := t.TempDir()
	work := filepath.Join(t.TempDir(), "work")
	if err := os.Mkdir(work, 0o755); err != nil {
		t.Fatal(err)
	}
	git(t, work, "init", "-q", "-b", "main")
	for _, v := range []string{"v0.1.0", "v0.2.0"} {
		if err := os.WriteFile(filepath.Join(work, "f.txt"), []byte("content "+v), 0o644); err != nil {
			t.Fatal(err)
		}
		git(t, work, "add", ".")
		git(t, work, "commit", "-q", "-m", v)
		git(t, work, "tag", v)
	}
	git(t, root, "clone", "-q", "--bare", work, "thing.git")

	p, err := Open("dir:" + root)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	repos, err := p.List(ctx)
	if err != nil || !reflect.DeepEqual(repos, []string{"thing"}) {
		t.Fatalf("List = %v, %v", repos, err)
	}
	tags, err := p.Tags(ctx, "thing")
	if err != nil || !reflect.DeepEqual(tags, []string{"v0.1.0", "v0.2.0"}) {
		t.Fatalf("Tags = %v, %v", tags, err)
	}
	b, err := p.ReadFile(ctx, "thing", "v0.1.0", "f.txt")
	if err != nil || string(b) != "content v0.1.0" {
		t.Fatalf("ReadFile = %q, %v", b, err)
	}
}

func TestDirProviderPlainFolder(t *testing.T) {
	p, err := Open("dir:../../samples/go")
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	repos, err := p.List(ctx)
	want := []string{"config", "httpserver", "kvstore", "shortid"}
	if err != nil || !reflect.DeepEqual(repos, want) {
		t.Fatalf("List = %v, %v", repos, err)
	}
	tags, err := p.Tags(ctx, "httpserver")
	if err != nil || !reflect.DeepEqual(tags, []string{"v0.2.0"}) {
		t.Fatalf("Tags = %v, %v", tags, err)
	}
	b, err := p.ReadFile(ctx, "httpserver", "v0.2.0", "module.yaml")
	if err != nil || !strings.Contains(string(b), "name: httpserver") {
		t.Fatalf("ReadFile = %q, %v", b, err)
	}
}

func TestEnsureCreatesBareRepo(t *testing.T) {
	root := t.TempDir()
	p, err := Open("dir:" + root)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	url, err := p.Ensure(ctx, "newmod")
	if err != nil {
		t.Fatal(err)
	}
	if url != filepath.Join(root, "newmod.git") {
		t.Errorf("url = %q", url)
	}
	if _, err := os.Stat(filepath.Join(url, "HEAD")); err != nil {
		t.Errorf("not a bare repo: %v", err)
	}
	again, err := p.Ensure(ctx, "newmod")
	if err != nil || again != url {
		t.Errorf("second Ensure = %q, %v", again, err)
	}
	repos, _ := p.List(ctx)
	if !reflect.DeepEqual(repos, []string{"newmod"}) {
		t.Errorf("List = %v", repos)
	}
}

func TestOpenErrors(t *testing.T) {
	for _, spec := range []string{"", "bogus:x", "dir:/no/such/dir/xyz"} {
		if _, err := Open(spec); err == nil {
			t.Errorf("Open(%q) succeeded", spec)
		}
	}
}

func TestEnsureRejectsBadName(t *testing.T) {
	root := t.TempDir()
	p, _ := Open("dir:" + root)
	for _, name := range []string{"../x", "a/b", "", ".."} {
		if _, err := p.Ensure(context.Background(), name); err == nil {
			t.Errorf("Ensure(%q) succeeded", name)
		}
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(root), "x.git")); err == nil {
		t.Error("repo created outside root")
	}
}
