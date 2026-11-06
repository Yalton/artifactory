package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// forgejoBaseURL returns the API base for host. Tests override it.
var forgejoBaseURL = func(host string) string { return "https://" + host + "/api/v1" }

const forgejoPageSize = 50

// forgejoMaxPages caps list paging so a server that never returns an empty
// page cannot loop forever. Tests lower it.
var forgejoMaxPages = 200

// forgejoProvider keeps one repo per module in a Forgejo organization.
type forgejoProvider struct {
	host, org string
	client    *http.Client
}

func openForgejo(rest string) (*forgejoProvider, error) {
	host, org, ok := strings.Cut(rest, "/")
	if !ok || host == "" || org == "" || strings.Contains(org, "/") {
		return nil, fmt.Errorf("invalid provider forgejo:%s: want forgejo:<host>/<org>", rest)
	}
	return &forgejoProvider{host: host, org: org, client: &http.Client{Timeout: 30 * time.Second}}, nil
}

func (f *forgejoProvider) Spec() string { return "forgejo:" + f.host + "/" + f.org }

// authed reports whether a token is available, for the cache key.
func (f *forgejoProvider) authed() bool { return forgejoToken() != "" }

// forgejoToken returns FORGEJO_TOKEN, else the default tea login's token, else "".
func forgejoToken() string {
	if t := os.Getenv("FORGEJO_TOKEN"); t != "" {
		return t
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	data, err := os.ReadFile(filepath.Join(home, ".config", "tea", "config.yml"))
	if err != nil {
		return ""
	}
	var cfg struct {
		Logins []struct {
			Token   string `yaml:"token"`
			Default bool   `yaml:"default"`
		} `yaml:"logins"`
	}
	if yaml.Unmarshal(data, &cfg) != nil {
		return ""
	}
	for _, l := range cfg.Logins {
		if l.Default {
			return l.Token
		}
	}
	return ""
}

// do sends a request and returns the status and body. Network errors are errors;
// HTTP statuses are the caller's to judge.
func (f *forgejoProvider) do(ctx context.Context, method, path string, body any) (int, []byte, error) {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return 0, nil, err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, forgejoBaseURL(f.host)+path, rd)
	if err != nil {
		return 0, nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if t := forgejoToken(); t != "" {
		req.Header.Set("Authorization", "token "+t)
	}
	resp, err := f.client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	return resp.StatusCode, b, err
}

// names pages through a list endpoint and returns each item's name, sorted.
func (f *forgejoProvider) names(ctx context.Context, path string) ([]string, error) {
	var out []string
	for page := 1; ; page++ {
		if page > forgejoMaxPages {
			return nil, fmt.Errorf("forgejo %s: more than %d pages of %d; stopped paging", path, forgejoMaxPages, forgejoPageSize)
		}
		status, b, err := f.do(ctx, "GET", fmt.Sprintf("%s?page=%d&limit=%d", path, page, forgejoPageSize), nil)
		if err != nil {
			return nil, err
		}
		if status == http.StatusNotFound {
			return nil, fmt.Errorf("forgejo %s: %w", path, ErrNotFound)
		}
		if status != http.StatusOK {
			return nil, fmt.Errorf("forgejo %s: HTTP %d", path, status)
		}
		var items []struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(b, &items); err != nil {
			return nil, fmt.Errorf("forgejo %s: %w", path, err)
		}
		if len(items) == 0 {
			break
		}
		for _, it := range items {
			out = append(out, it.Name)
		}
	}
	sort.Strings(out)
	return out, nil
}

func (f *forgejoProvider) List(ctx context.Context) ([]string, error) {
	return f.names(ctx, "/orgs/"+url.PathEscape(f.org)+"/repos")
}

func (f *forgejoProvider) Tags(ctx context.Context, repo string) ([]string, error) {
	return f.names(ctx, "/repos/"+url.PathEscape(f.org)+"/"+url.PathEscape(repo)+"/tags")
}

func (f *forgejoProvider) ReadFile(ctx context.Context, repo, ref, path string) ([]byte, error) {
	segs := strings.Split(path, "/")
	for i, s := range segs {
		segs[i] = url.PathEscape(s)
	}
	p := "/repos/" + url.PathEscape(f.org) + "/" + url.PathEscape(repo) + "/raw/" + strings.Join(segs, "/") + "?ref=" + url.QueryEscape(ref)
	status, b, err := f.do(ctx, "GET", p, nil)
	if err != nil {
		return nil, err
	}
	if status == http.StatusNotFound {
		return nil, fmt.Errorf("%s/%s %s at %s: %w", f.org, repo, path, ref, ErrNotFound)
	}
	if status != http.StatusOK {
		return nil, fmt.Errorf("forgejo read %s/%s %s: HTTP %d", f.org, repo, path, status)
	}
	return b, nil
}

// Ensure creates the repo when missing and returns its SSH URL.
func (f *forgejoProvider) Ensure(ctx context.Context, repo string) (string, error) {
	if forgejoToken() == "" {
		return "", fmt.Errorf("no Forgejo token: set FORGEJO_TOKEN or log in with tea")
	}
	status, _, err := f.do(ctx, "GET", "/repos/"+url.PathEscape(f.org)+"/"+url.PathEscape(repo), nil)
	if err != nil {
		return "", err
	}
	switch status {
	case http.StatusOK:
	case http.StatusNotFound:
		status, b, err := f.do(ctx, "POST", "/orgs/"+url.PathEscape(f.org)+"/repos",
			map[string]string{"name": repo, "default_branch": "main"})
		if err != nil {
			return "", err
		}
		if status != http.StatusCreated && status != http.StatusOK {
			return "", fmt.Errorf("forgejo create %s/%s: HTTP %d: %s", f.org, repo, status, strings.TrimSpace(string(b)))
		}
	default:
		return "", fmt.Errorf("forgejo check %s/%s: HTTP %d", f.org, repo, status)
	}
	return fmt.Sprintf("git@%s:%s/%s.git", f.host, f.org, repo), nil
}
