package config_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"repo.billbert.co/artifactory/config"
)

type cfg struct {
	Addr  string        `env:"ADDR" default:":8080"`
	Data  string        `env:"DATA"`
	Max   int           `env:"MAX" default:"3"`
	Debug bool          `env:"DEBUG"`
	Wait  time.Duration `env:"WAIT" default:"2s"`
}

func TestDefaults(t *testing.T) {
	var c cfg
	if err := config.Load("CFGT1", &c, ""); err != nil {
		t.Fatal(err)
	}
	if c.Addr != ":8080" || c.Max != 3 || c.Wait != 2*time.Second || c.Debug || c.Data != "" {
		t.Fatalf("got %+v", c)
	}
}

func TestFileOverridesDefault(t *testing.T) {
	f := filepath.Join(t.TempDir(), "app.conf")
	os.WriteFile(f, []byte("# comment\nADDR = :9000\nDEBUG=true\n\nMAX=7\n"), 0o644)
	var c cfg
	if err := config.Load("CFGT2", &c, f); err != nil {
		t.Fatal(err)
	}
	if c.Addr != ":9000" || !c.Debug || c.Max != 7 {
		t.Fatalf("got %+v", c)
	}
}

func TestEnvOverridesFile(t *testing.T) {
	f := filepath.Join(t.TempDir(), "app.conf")
	os.WriteFile(f, []byte("ADDR=:9000\n"), 0o644)
	t.Setenv("CFGT3_ADDR", "127.0.0.1:1")
	t.Setenv("CFGT3_DATA", "/tmp/x")
	var c cfg
	if err := config.Load("CFGT3", &c, f); err != nil {
		t.Fatal(err)
	}
	if c.Addr != "127.0.0.1:1" || c.Data != "/tmp/x" {
		t.Fatalf("got %+v", c)
	}
}

func TestMissingFileIsFine(t *testing.T) {
	var c cfg
	if err := config.Load("CFGT4", &c, filepath.Join(t.TempDir(), "nope")); err != nil {
		t.Fatal(err)
	}
}

func TestBadValue(t *testing.T) {
	t.Setenv("CFGT5_MAX", "abc")
	var c cfg
	if err := config.Load("CFGT5", &c, ""); err == nil {
		t.Fatal("want error")
	}
}

func TestNeedsStructPointer(t *testing.T) {
	var c cfg
	if err := config.Load("X", c, ""); err == nil {
		t.Fatal("want error for non-pointer")
	}
}
