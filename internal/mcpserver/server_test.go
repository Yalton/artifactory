package mcpserver

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"repo.billbert.co/artifactory/artifactory/internal/app"
)

// connect starts the server on one end of an in-memory transport and returns
// a client session on the other.
func connect(t *testing.T, projectDir string) *mcp.ClientSession {
	t.Helper()
	ctx := context.Background()
	st, ct := mcp.NewInMemoryTransports()
	srv := New(app.App{}, projectDir)
	ss, err := srv.Connect(ctx, st, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ss.Close() })
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "0"}, nil)
	cs, err := client.Connect(ctx, ct, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cs.Close() })
	return cs
}

// newProject makes a godot-csharp project whose catalog is the test kits.
func newProject(t *testing.T) string {
	t.Helper()
	kits, err := filepath.Abs("../testdata/kits")
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	yaml := "ecosystem: godot-csharp\nprovider: dir:" + kits + "\n"
	if err := os.WriteFile(filepath.Join(dir, "artifactory.yaml"), []byte(yaml), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func text(t *testing.T, r *mcp.CallToolResult) string {
	t.Helper()
	if len(r.Content) == 0 {
		t.Fatal("no content")
	}
	return r.Content[0].(*mcp.TextContent).Text
}

func TestMCPToolsListAndSearch(t *testing.T) {
	cs := connect(t, newProject(t))
	ctx := context.Background()

	lt, err := cs.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range lt.Tools {
		names = append(names, tool.Name)
	}
	sort.Strings(names)
	if got := strings.Join(names, ","); got != "index,install,search,show" {
		t.Fatalf("tools = %s", got)
	}

	res, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: "search", Arguments: map[string]any{"query": "mouse cursor"}})
	if err != nil {
		t.Fatal(err)
	}
	if res.IsError {
		t.Fatalf("tool error: %s", text(t, res))
	}
	var out struct {
		Hits []struct {
			Module struct{ Name string } `json:"Module"`
		} `json:"hits"`
	}
	if err := json.Unmarshal([]byte(text(t, res)), &out); err != nil {
		t.Fatalf("%v: %s", err, text(t, res))
	}
	if len(out.Hits) == 0 || !strings.Contains(text(t, res), "CursorKit") {
		t.Errorf("want CursorKit, got %s", text(t, res))
	}
}

func TestMCPShowAndErrors(t *testing.T) {
	cs := connect(t, newProject(t))
	ctx := context.Background()

	res, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: "show", Arguments: map[string]any{"name": "CursorKit"}})
	if err != nil || res.IsError {
		t.Fatalf("show: %v %v", err, res)
	}
	if !strings.Contains(text(t, res), `"module"`) {
		t.Errorf("show output: %s", text(t, res))
	}

	res, err = cs.CallTool(ctx, &mcp.CallToolParams{Name: "show", Arguments: map[string]any{"name": "NoSuchKit"}})
	if err != nil {
		t.Fatal(err)
	}
	if !res.IsError || !strings.Contains(text(t, res), "no module named NoSuchKit") {
		t.Errorf("want tool error, got %+v", res)
	}
}

func TestMCPIndex(t *testing.T) {
	dir := newProject(t)
	cs := connect(t, dir)
	res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: "index", Arguments: map[string]any{}})
	if err != nil || res.IsError {
		t.Fatalf("index: %v %v", err, res)
	}
	if _, err := os.Stat(filepath.Join(dir, "MODULES.md")); err != nil {
		t.Error(err)
	}
}
