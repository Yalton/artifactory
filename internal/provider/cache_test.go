package provider

import (
	"context"
	"net/http"
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
