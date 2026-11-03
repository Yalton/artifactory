package install

import (
	"archive/zip"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
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

func TestInstallGoModule(t *testing.T) {
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go binary not found")
	}
	src, _ := filepath.Abs("../../samples/go/kvstore")
	proxy := t.TempDir()
	buildGoProxy(t, src, proxy)

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
	d, err := descriptor.Load(src)
	if err != nil {
		t.Fatal(err)
	}
	m := catalog.Module{Descriptor: d, Tag: "v0.1.0"}

	v, err := Run(context.Background(), proj, m)
	if err != nil || v != "0.1.0" {
		t.Fatalf("Run = %q, %v", v, err)
	}
	dir, err := Locate(proj, m)
	if err != nil || !strings.Contains(dir, "kvstore@v0.1.0") {
		t.Errorf("Locate = %q, %v", dir, err)
	}
}

func TestRunFailure(t *testing.T) {
	m := catalog.Module{Descriptor: descriptor.Descriptor{Name: "X", Ecosystem: "godot-csharp", Install: "false"}}
	if _, err := Run(context.Background(), t.TempDir(), m); err == nil {
		t.Error("want error from failing install line")
	}
}
