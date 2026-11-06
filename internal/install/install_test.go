package install

import (
	"archive/zip"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

func TestGoModulePath(t *testing.T) {
	tests := []struct {
		line, want string
		wantErr    bool
	}{
		{"go get repo.billbert.co/artifactory/kvstore", "repo.billbert.co/artifactory/kvstore", false},
		{"go get -u example.com/m@v1.2.3", "example.com/m", false},
		{"git submodule add x y", "", true},
		{"go get", "", true},
	}
	for _, tt := range tests {
		got, err := GoModulePath(tt.line)
		if got != tt.want || (err != nil) != tt.wantErr {
			t.Errorf("%q: got %q, %v", tt.line, got, err)
		}
	}
}

// buildGoProxy writes a file GOPROXY tree for the module in dir, using the
// layout of tools/artifactory/goproxy.py.
func buildGoProxy(t *testing.T, dir, out string) {
	t.Helper()
	gomod, err := os.ReadFile(filepath.Join(dir, "go.mod"))
	if err != nil {
		t.Fatal(err)
	}
	var module string
	for _, l := range strings.Split(string(gomod), "\n") {
		if f := strings.Fields(l); len(f) == 2 && f[0] == "module" {
			module = f[1]
		}
	}
	d, err := descriptor.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	version := "v" + strings.TrimPrefix(d.Version, "v")
	base := filepath.Join(out, filepath.FromSlash(module), "@v")
	if err := os.MkdirAll(base, 0o755); err != nil {
		t.Fatal(err)
	}
	write := func(name string, data []byte) {
		if err := os.WriteFile(filepath.Join(base, name), data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	info, _ := json.Marshal(map[string]string{"Version": version, "Time": "2026-01-01T00:00:00Z"})
	write("list", []byte(version+"\n"))
	write(version+".info", info)
	write(version+".mod", gomod)

	zf, err := os.Create(filepath.Join(base, version+".zip"))
	if err != nil {
		t.Fatal(err)
	}
	defer zf.Close()
	zw := zip.NewWriter(zf)
	err = filepath.WalkDir(dir, func(path string, e os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, path)
		if e.IsDir() {
			if rel != "." {
				if _, err := os.Stat(filepath.Join(path, "go.mod")); err == nil {
					return filepath.SkipDir // nested module
				}
			}
			if e.Name() == ".git" || e.Name() == "vendor" {
				return filepath.SkipDir
			}
			return nil
		}
		w, err := zw.Create(module + "@" + version + "/" + filepath.ToSlash(rel))
		if err != nil {
			return err
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
}

// goEnv points the go tool at a fresh GOPATH and a file GOPROXY built from
// the given sample module folders, and returns a go project to install into.
func goEnv(t *testing.T, srcs ...string) string {
	t.Helper()
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go binary not found")
	}
	proxy := t.TempDir()
	for _, src := range srcs {
		buildGoProxy(t, src, proxy)
	}
	gopath := t.TempDir()
	t.Cleanup(func() { exec.Command("chmod", "-R", "u+w", gopath).Run() })
	t.Setenv("GOPATH", gopath)
	t.Setenv("GOMODCACHE", filepath.Join(gopath, "pkg", "mod"))
	t.Setenv("GOPROXY", "file://"+proxy)
	t.Setenv("GOFLAGS", "-mod=mod")
	t.Setenv("GONOSUMDB", "*")
	t.Setenv("GONOSUMCHECK", "1")
	t.Setenv("GOSUMDB", "off")
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "go.mod"), []byte("module example.com/app\n\ngo 1.24\n"), 0o644)
	return proj
}

// installGo installs the module in src with `go get path@v0.1.0`.
func installGo(t *testing.T, proj, src, path string) catalog.Module {
	t.Helper()
	d, err := descriptor.Load(src)
	if err != nil {
		t.Fatal(err)
	}
	d.Install = "go get " + path + "@v0.1.0"
	m := catalog.Module{Descriptor: d, Tag: "v0.1.0"}
	if v, err := Run(context.Background(), proj, m); err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	return m
}

// forkModule copies the sample module in src under a new module path.
func forkModule(t *testing.T, src, path string) string {
	t.Helper()
	dst := filepath.Join(t.TempDir(), filepath.Base(src))
	if err := os.CopyFS(dst, os.DirFS(src)); err != nil {
		t.Fatal(err)
	}
	gomod := filepath.Join(dst, "go.mod")
	b, _ := os.ReadFile(gomod)
	lines := strings.Split(string(b), "\n")
	for i, l := range lines {
		if strings.HasPrefix(l, "module ") {
			lines[i] = "module " + path
		}
	}
	os.WriteFile(gomod, []byte(strings.Join(lines, "\n")), 0o644)
	return dst
}

const kvPath = "repo.billbert.co/artifactory/kvstore"

func TestInstallGoModule(t *testing.T) {
	src, _ := filepath.Abs("../../samples/go/kvstore")
	proj := goEnv(t, src)
	m := installGo(t, proj, src, kvPath)
	dir, err := Locate(proj, m)
	if err != nil || !strings.Contains(dir, "kvstore@v0.1.0") {
		t.Errorf("Locate = %q, %v", dir, err)
	}

	// Installed reads the copy in the module cache, with the proxy gone and
	// GOFLAGS asking for vendor mode.
	t.Setenv("GOPROXY", "file://"+filepath.Join(t.TempDir(), "gone"))
	t.Setenv("GOFLAGS", "-mod=vendor")
	got, err := Installed(context.Background(), proj, "go", []string{"kvstore", "absent"})
	if err != nil || len(got.Found) != 1 || got.Found["kvstore"].Path != kvPath ||
		got.Found["kvstore"].Descriptor.Version != "0.1.0" || len(got.Problems)+len(got.Ambiguous) != 0 {
		t.Errorf("Installed = %+v, %v", got, err)
	}
}

func TestInstalledGoNameCollision(t *testing.T) {
	src, _ := filepath.Abs("../../samples/go/kvstore")
	const forkPath = "example.com/fork/kvstore"
	fork := forkModule(t, src, forkPath)
	proj := goEnv(t, src, fork)
	installGo(t, proj, src, kvPath)
	installGo(t, proj, fork, forkPath)

	got, err := Installed(context.Background(), proj, "go", []string{"kvstore"})
	if err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, c := range got.Ambiguous["kvstore"] {
		paths = append(paths, c.Path)
	}
	sort.Strings(paths)
	if len(got.Found) != 0 || !reflect.DeepEqual(paths, []string{forkPath, kvPath}) {
		t.Errorf("Installed = %+v", got)
	}
}

func TestInstalledGoWithoutGoMod(t *testing.T) {
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go binary not found")
	}
	_, err := Installed(context.Background(), t.TempDir(), "go", []string{"kvstore"})
	if err == nil || !strings.Contains(err.Error(), "go.mod") {
		t.Errorf("err = %v, want the go.mod failure", err)
	}
	// Nothing to look up runs nothing.
	if _, err := Installed(context.Background(), t.TempDir(), "go", nil); err != nil {
		t.Errorf("empty lookup: %v", err)
	}
}

func TestReadonlyGoFlags(t *testing.T) {
	for in, want := range map[string]string{
		"":                       "-mod=readonly",
		"-mod=vendor":            "-mod=readonly",
		"-trimpath --mod=mod -v": "-trimpath -v -mod=readonly",
	} {
		if got := readonlyGoFlags(in); got != want {
			t.Errorf("readonlyGoFlags(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestInstalledGodot(t *testing.T) {
	proj := t.TempDir()
	src, _ := filepath.Abs("../testdata/kits/CursorKit")
	addons := filepath.Join(proj, "addons")
	if err := os.MkdirAll(filepath.Join(addons, "BadKit"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(src, filepath.Join(addons, "CursorKit")); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(addons, "BadKit", "module.yaml"), []byte("name: BadKit\n"), 0o644)
	// A module.yaml outside addons/ that a traversal name would reach.
	os.WriteFile(filepath.Join(proj, "module.yaml"), []byte("name: x\n"), 0o644)

	got, err := Installed(context.Background(), proj, "godot-csharp",
		[]string{"CursorKit", "CrashKit", "BadKit", "..", "../x", "a/b"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Found) != 1 || got.Found["CursorKit"].Descriptor.Name != "CursorKit" {
		t.Errorf("Found = %+v", got.Found)
	}
	for _, n := range []string{"BadKit", "..", "../x", "a/b"} {
		if got.Problems[n] == "" {
			t.Errorf("no problem for %q: %+v", n, got.Problems)
		}
	}
	if _, ok := got.Problems["CrashKit"]; ok {
		t.Errorf("uninstalled CrashKit reported as a problem")
	}
}

func TestRunFailure(t *testing.T) {
	m := catalog.Module{Descriptor: descriptor.Descriptor{Name: "X", Ecosystem: "godot-csharp", Install: "false"}}
	if _, err := Run(context.Background(), t.TempDir(), m); err == nil {
		t.Error("want error from failing install line")
	}
}
