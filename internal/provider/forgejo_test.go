package provider

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// useServer points the Forgejo provider at h and returns an opened provider.
func useServer(t *testing.T, h http.Handler) Provider {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	old := forgejoBaseURL
	forgejoBaseURL = func(string) string { return srv.URL + "/api/v1" }
	t.Cleanup(func() { forgejoBaseURL = old })
	p, err := Open("forgejo:forge.test/kits")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func TestForgejoListPages(t *testing.T) {
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/orgs/kits/repos" {
			http.NotFound(w, r)
			return
		}
		var repos []map[string]string
		switch r.URL.Query().Get("page") {
		case "1":
			for i := 0; i < 50; i++ {
				repos = append(repos, map[string]string{"name": fmt.Sprintf("r%02d", i)})
			}
		case "2":
			for i := 50; i < 60; i++ {
				repos = append(repos, map[string]string{"name": fmt.Sprintf("r%02d", i)})
			}
		}
		json.NewEncoder(w).Encode(repos)
	}))
	names, err := p.List(context.Background())
	if err != nil || len(names) != 60 {
		t.Fatalf("List = %d names, %v", len(names), err)
	}
}

func TestForgejoTags(t *testing.T) {
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/repos/kits/thing/tags" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Query().Get("page") == "1" {
			w.Write([]byte(`[{"name":"v0.2.0"},{"name":"v0.1.0"}]`))
			return
		}
		w.Write([]byte(`[]`))
	}))
	tags, err := p.Tags(context.Background(), "thing")
	if err != nil || strings.Join(tags, ",") != "v0.1.0,v0.2.0" {
		t.Fatalf("Tags = %v, %v", tags, err)
	}
}

func TestForgejoReadFile(t *testing.T) {
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/repos/kits/thing/raw/module.yaml" && r.URL.Query().Get("ref") == "v1.0.0" {
			w.Write([]byte("name: thing\n"))
			return
		}
		http.NotFound(w, r)
	}))
	b, err := p.ReadFile(context.Background(), "thing", "v1.0.0", "module.yaml")
	if err != nil || string(b) != "name: thing\n" {
		t.Fatalf("ReadFile = %q, %v", b, err)
	}
}

func TestForgejoReadFileNotFound(t *testing.T) {
	p := useServer(t, http.NotFoundHandler())
	_, err := p.ReadFile(context.Background(), "thing", "main", "nope")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound", err)
	}
}

func TestForgejoEnsureCreatesMissing(t *testing.T) {
	t.Setenv("FORGEJO_TOKEN", "sekret")
	var body map[string]string
	var auth string
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/api/v1/repos/kits/newmod":
			http.NotFound(w, r)
		case r.Method == "POST" && r.URL.Path == "/api/v1/orgs/kits/repos":
			auth = r.Header.Get("Authorization")
			json.NewDecoder(r.Body).Decode(&body)
			w.WriteHeader(http.StatusCreated)
			w.Write([]byte(`{}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL)
			http.NotFound(w, r)
		}
	}))
	url, err := p.Ensure(context.Background(), "newmod")
	if err != nil {
		t.Fatal(err)
	}
	if url != "git@forge.test:kits/newmod.git" {
		t.Errorf("url = %q", url)
	}
	if auth != "token sekret" {
		t.Errorf("auth header = %q", auth)
	}
	if body["name"] != "newmod" || body["default_branch"] != "main" {
		t.Errorf("body = %v", body)
	}
}

func TestForgejoEnsureExistingNoPost(t *testing.T) {
	t.Setenv("FORGEJO_TOKEN", "sekret")
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			t.Errorf("unexpected %s", r.Method)
		}
		w.Write([]byte(`{}`))
	}))
	if _, err := p.Ensure(context.Background(), "have"); err != nil {
		t.Fatal(err)
	}
}

func TestForgejoEnsureNeedsToken(t *testing.T) {
	t.Setenv("FORGEJO_TOKEN", "")
	t.Setenv("HOME", t.TempDir())
	p := useServer(t, http.NotFoundHandler())
	_, err := p.Ensure(context.Background(), "x")
	if err == nil || err.Error() != "no Forgejo token: set FORGEJO_TOKEN or log in with tea" {
		t.Fatalf("err = %v", err)
	}
}

func TestTokenFromTeaConfig(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("FORGEJO_TOKEN", "")
	dir := filepath.Join(home, ".config", "tea")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	cfg := "logins:\n  - name: other\n    token: wrong\n    default: false\n  - name: home\n    token: right\n    default: true\n"
	if err := os.WriteFile(filepath.Join(dir, "config.yml"), []byte(cfg), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := forgejoToken(); got != "right" {
		t.Errorf("token = %q", got)
	}
	t.Setenv("FORGEJO_TOKEN", "env")
	if got := forgejoToken(); got != "env" {
		t.Errorf("env token = %q", got)
	}
}

func TestForgejoPagingStopsAtCap(t *testing.T) {
	old := forgejoMaxPages
	forgejoMaxPages = 3
	t.Cleanup(func() { forgejoMaxPages = old })
	calls := 0
	p := useServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		json.NewEncoder(w).Encode([]map[string]string{{"name": "same"}})
	}))
	_, err := p.List(context.Background())
	if err == nil || !strings.Contains(err.Error(), "more than 3 pages") {
		t.Fatalf("err = %v, want a page cap error", err)
	}
	if calls != 3 {
		t.Errorf("server saw %d requests, want 3", calls)
	}
}
