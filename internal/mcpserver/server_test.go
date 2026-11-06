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

func TestInstallToolPartialFailureNamesInstalled(t *testing.T) {
	root := t.TempDir()
	for name, line := range map[string]string{
		"AKit": "mkdir -p addons/AKit && cp " + filepath.Join(root, "AKit", "module.yaml") + " addons/AKit/",
		"BKit": "false",
	} {
		dir := filepath.Join(root, name)
		os.Mkdir(dir, 0o755)
		y := "name: " + name + "\necosystem: godot-csharp\nversion: 0.1.0\nsummary: A kit.\nreplaces: [x]\n" +
			"install: \"" + line + "\"\nsetup: []\nentry: [X.Y]\nliveness: \"[" + name + "] live\"\n" +
			"docs: README.md\nexample: README.md\ntest: \"true\"\n"
		os.WriteFile(filepath.Join(dir, "module.yaml"), []byte(y), 0o644)
	}
	proj := t.TempDir()
	os.WriteFile(filepath.Join(proj, "artifactory.yaml"), []byte("ecosystem: godot-csharp\nprovider: dir:"+root+"\n"), 0o644)
	cs := connect(t, proj)
	r, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: "install", Arguments: map[string]any{"names": []string{"AKit", "BKit"}}})
	if err != nil {
		t.Fatal(err)
	}
	if !r.IsError || !strings.Contains(text(t, r), "installed before the failure: AKit (v0.1.0)") {
		t.Errorf("isError=%v text=%q", r.IsError, text(t, r))
	}
	md, _ := os.ReadFile(filepath.Join(proj, "MODULES.md"))
	if !strings.Contains(string(md), "## AKit") {
		t.Errorf("MODULES.md:\n%s", md)
	}
}

func TestMCPRejectsEmptyArguments(t *testing.T) {
	cs := connect(t, newProject(t))
	cases := []struct {
		tool string
		args map[string]any
		want string
	}{
		{"search", map[string]any{"query": "  "}, "query is empty"},
		{"show", map[string]any{"name": ""}, "name is empty"},
		{"install", map[string]any{"names": []string{}}, "names is empty"},
		{"install", map[string]any{"names": []string{"AKit", " "}}, "empty name"},
	}
	for _, c := range cases {
		res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: c.tool, Arguments: c.args})
		if err != nil {
			t.Fatalf("%s %v: protocol error %v", c.tool, c.args, err)
		}
		if !res.IsError || !strings.Contains(text(t, res), c.want) {
			t.Errorf("%s %v: isError=%v text=%q, want %q", c.tool, c.args, res.IsError, text(t, res), c.want)
		}
	}
}
