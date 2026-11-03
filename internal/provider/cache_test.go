package provider

import (
	"context"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func cachedFor(t *testing.T, ttl time.Duration, refresh bool) (Provider, *atomic.Int32, *time.Time) {
	t.Helper()
	var calls atomic.Int32
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Query().Get("page") == "1" {
			w.Write([]byte(`[{"name":"a"}]`))
			return
		}
		w.Write([]byte(`[]`))
	}))
	now := time.Now()
	c := CachedRefresh(p, t.TempDir(), ttl, refresh).(*cached)
	c.now = func() time.Time { return now }
	return c, &calls, &now
}

func TestCachedServesWithinTTL(t *testing.T) {
	ctx := context.Background()
	p, calls, now := cachedFor(t, time.Minute, false)
	if _, err := p.List(ctx); err != nil {
		t.Fatal(err)
	}
	first := calls.Load()
	names, err := p.List(ctx)
	if err != nil || len(names) != 1 || names[0] != "a" {
		t.Fatalf("List = %v, %v", names, err)
	}
	if calls.Load() != first {
		t.Errorf("second List made HTTP calls")
	}
	*now = now.Add(2 * time.Minute)
	if _, err := p.List(ctx); err != nil {
		t.Fatal(err)
	}
	if calls.Load() == first {
		t.Errorf("List after TTL made no HTTP call")
	}
}

func TestCachedRefreshSkipsReads(t *testing.T) {
	ctx := context.Background()
	p, calls, _ := cachedFor(t, time.Minute, true)
	p.List(ctx)
	first := calls.Load()
	p.List(ctx)
	if calls.Load() == first {
		t.Errorf("refresh served from cache")
	}
}

func TestCachedKeyedByArgs(t *testing.T) {
	ctx := context.Background()
	p, calls, _ := cachedFor(t, time.Minute, false)
	p.Tags(ctx, "x")
	n := calls.Load()
	p.Tags(ctx, "y")
	if calls.Load() == n {
		t.Errorf("different repo served from cache")
	}
}

func TestCachedFileModes(t *testing.T) {
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`[]`)) }))
	dir := filepath.Join(t.TempDir(), "cache")
	c := Cached(p, dir, time.Minute)
	if _, err := c.List(context.Background()); err != nil {
		t.Fatal(err)
	}
	fi, err := os.Stat(dir)
	if err != nil || fi.Mode().Perm() != 0o700 {
		t.Fatalf("dir mode = %v, %v", fi.Mode().Perm(), err)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("entries = %v", entries)
	}
	for _, e := range entries {
		fi, _ := e.Info()
		if fi.Mode().Perm() != 0o600 || !strings.HasSuffix(e.Name(), ".json") {
			t.Errorf("%s mode %v", e.Name(), fi.Mode().Perm())
		}
	}
}

func TestCachedKeyedByToken(t *testing.T) {
	ctx := context.Background()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("FORGEJO_TOKEN", "")
	p, calls, _ := cachedFor(t, time.Minute, false)
	p.List(ctx)
	n := calls.Load()
	t.Setenv("FORGEJO_TOKEN", "x")
	p.List(ctx)
	if calls.Load() == n {
		t.Errorf("authenticated run served the unauthenticated cache entry")
	}
}

func TestInvalidateDropsListAndTags(t *testing.T) {
	ctx := context.Background()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("FORGEJO_TOKEN", "")
	p, calls, _ := cachedFor(t, time.Minute, false)
	p.List(ctx)
	p.Tags(ctx, "a")
	t.Setenv("FORGEJO_TOKEN", "x")
	p.List(ctx)
	p.Tags(ctx, "a")
	Invalidate(p, "a")
	for _, tok := range []string{"", "x"} {
		t.Setenv("FORGEJO_TOKEN", tok)
		n := calls.Load()
		p.List(ctx)
		if calls.Load() == n {
			t.Errorf("token %q: List served from cache after Invalidate", tok)
		}
		n = calls.Load()
		p.Tags(ctx, "a")
		if calls.Load() == n {
			t.Errorf("token %q: Tags served from cache after Invalidate", tok)
		}
	}
	if Uncached(p) == p {
		t.Error("Uncached returned the cache")
	}
}
