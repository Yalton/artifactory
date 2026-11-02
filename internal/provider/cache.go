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

// authState is implemented by providers whose answers depend on whether a
// token is present. It reports presence only, never the token.
type authState interface {
	authed() bool
}

// file returns the cache file for op and args under the current auth state.
func (c *cached) file(op string, args ...string) string {
	authed := false
	if a, ok := c.Provider.(authState); ok {
		authed = a.authed()
	}
	return c.fileFor(authed, op, args...)
}

// fileFor keys the cache file by spec, auth state, op and args, so an
// unauthenticated answer is never served to an authenticated run.
func (c *cached) fileFor(authed bool, op string, args ...string) string {
	auth := "anon"
	if authed {
		auth = "auth"
	}
	h := sha256.New()
	for _, s := range append([]string{c.Spec(), auth, op}, args...) {
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

// put writes data to file atomically: a private directory, a unique temp
// file readable only by the user, then a rename.
func (c *cached) put(file string, data []byte) {
	raw, err := json.Marshal(cacheEntry{At: c.now(), Data: data})
	if err != nil || os.MkdirAll(c.dir, 0o700) != nil || os.Chmod(c.dir, 0o700) != nil {
		return
	}
	tmp, err := os.CreateTemp(c.dir, ".tmp-*")
	if err != nil {
		return
	}
	_, werr := tmp.Write(raw)
	cerr := tmp.Close()
	if werr != nil || cerr != nil || os.Rename(tmp.Name(), file) != nil {
		os.Remove(tmp.Name())
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

// Uncached returns the provider a cache wraps, or p itself when p is not a
// cache. Callers that must not act on stale data (publish's tag check) use it.
func Uncached(p Provider) Provider {
	if c, ok := p.(*cached); ok {
		return c.Provider
	}
	return p
}

// Invalidate drops the cached repo list and repo's cached tag list when p is
// a cache, so the next catalog read sees a module just published. It does
// nothing for other providers.
func Invalidate(p Provider, repo string) {
	c, ok := p.(*cached)
	if !ok {
		return
	}
	for _, authed := range []bool{false, true} {
		os.Remove(c.fileFor(authed, "list"))
		os.Remove(c.fileFor(authed, "tags", repo))
	}
}
