package provider

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// cached wraps a Provider with a JSON file cache for List, Tags and ReadFile.
type cached struct {
	Provider
	dir     string
	ttl     time.Duration
	refresh bool
	now     func() time.Time
}

type cacheEntry struct {
	At   time.Time `json:"at"`
	Data []byte    `json:"data"`
}

// Cached wraps p so List, Tags and ReadFile are served from JSON files under
// dir for ttl. Ensure is never cached. Cache failures are ignored.
func Cached(p Provider, dir string, ttl time.Duration) Provider {
	return CachedRefresh(p, dir, ttl, false)
}

// CachedRefresh is Cached; when refresh is true it skips cache reads but
// still writes fresh results.
func CachedRefresh(p Provider, dir string, ttl time.Duration, refresh bool) Provider {
	return &cached{Provider: p, dir: dir, ttl: ttl, refresh: refresh, now: time.Now}
}

func (c *cached) file(op string, args ...string) string {
	h := sha256.New()
	for _, s := range append([]string{c.Spec(), op}, args...) {
		h.Write([]byte(s))
		h.Write([]byte{0})
	}
	return filepath.Join(c.dir, hex.EncodeToString(h.Sum(nil))[:32]+".json")
}

func (c *cached) get(file string) ([]byte, bool) {
	if c.refresh {
		return nil, false
	}
	raw, err := os.ReadFile(file)
	if err != nil {
		return nil, false
	}
	var e cacheEntry
	if json.Unmarshal(raw, &e) != nil || c.now().Sub(e.At) >= c.ttl {
		return nil, false
	}
	return e.Data, true
}

func (c *cached) put(file string, data []byte) {
	raw, err := json.Marshal(cacheEntry{At: c.now(), Data: data})
	if err != nil || os.MkdirAll(c.dir, 0o755) != nil {
		return
	}
	tmp := file + ".tmp"
	if os.WriteFile(tmp, raw, 0o644) == nil {
		os.Rename(tmp, file)
	}
}

func (c *cached) list(ctx context.Context, op string, fetch func() ([]string, error), args ...string) ([]string, error) {
	f := c.file(op, args...)
	if b, ok := c.get(f); ok {
		var out []string
		if json.Unmarshal(b, &out) == nil {
			return out, nil
		}
	}
	out, err := fetch()
	if err != nil {
		return nil, err
	}
	if b, err := json.Marshal(out); err == nil {
		c.put(f, b)
	}
	return out, nil
}

func (c *cached) List(ctx context.Context) ([]string, error) {
	return c.list(ctx, "list", func() ([]string, error) { return c.Provider.List(ctx) })
}

func (c *cached) Tags(ctx context.Context, repo string) ([]string, error) {
	return c.list(ctx, "tags", func() ([]string, error) { return c.Provider.Tags(ctx, repo) }, repo)
}

func (c *cached) ReadFile(ctx context.Context, repo, ref, path string) ([]byte, error) {
	f := c.file("file", repo, ref, path)
	if b, ok := c.get(f); ok {
		return b, nil
	}
	b, err := c.Provider.ReadFile(ctx, repo, ref, path)
	if err != nil {
		return nil, err
	}
	c.put(f, b)
	return b, nil
}
