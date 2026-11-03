// Package mcpserver exposes the search, show, install and index operations as
// MCP tools. It calls internal/app directly, the same functions the CLI uses.
//
// Every tool returns the JSON the CLI prints with --json. The SDK sends it
// as one text content block and, identically, as structured content. A failed operation is a tool error (isError true) whose text is the
// error message, never a protocol failure.
package mcpserver

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"repo.billbert.co/artifactory/artifactory/internal/app"
)

// SearchInput is the argument object of the search tool.
type SearchInput struct {
	Query     string `json:"query" jsonschema:"words describing the capability you need"`
	Ecosystem string `json:"ecosystem,omitempty" jsonschema:"only modules of this ecosystem"`
}

// ShowInput is the argument object of the show tool.
type ShowInput struct {
	Name string `json:"name" jsonschema:"module name"`
}

// InstallInput is the argument object of the install tool.
type InstallInput struct {
	Names []string `json:"names" jsonschema:"module names to install into the project"`
}

// IndexInput is the (empty) argument object of the index tool.
type IndexInput struct{}

// New builds an MCP server whose tools operate on the project in projectDir
// ("" means the current directory).
func New(a app.App, projectDir string) *mcp.Server {
	if projectDir == "" {
		projectDir = "."
	}
	s := mcp.NewServer(&mcp.Implementation{Name: "artifactory", Version: "0.1.0"}, nil)

	mcp.AddTool(s, &mcp.Tool{
		Name:        "search",
		Description: "Rank catalog modules against a free-text query. No hits means a gap.",
	}, func(ctx context.Context, _ *mcp.CallToolRequest, in SearchInput) (*mcp.CallToolResult, any, error) {
		res, err := a.Search(ctx, "", projectDir, strings.Fields(in.Query), in.Ecosystem)
		return reply(res, err)
	})

	mcp.AddTool(s, &mcp.Tool{
		Name:        "show",
		Description: "Show one module's descriptor and its README at the latest tag.",
	}, func(ctx context.Context, _ *mcp.CallToolRequest, in ShowInput) (*mcp.CallToolResult, any, error) {
		res, err := a.Show(ctx, "", projectDir, in.Name)
		return reply(res, err)
	})

	mcp.AddTool(s, &mcp.Tool{
		Name:        "install",
		Description: "Run each module's install line in the project, record it in artifactory.yaml and re-index. Modifies the project.",
	}, func(ctx context.Context, _ *mcp.CallToolRequest, in InstallInput) (*mcp.CallToolResult, any, error) {
		res, err := a.Install(ctx, projectDir, in.Names, nil)
		return reply(res, err)
	})

	mcp.AddTool(s, &mcp.Tool{
		Name:        "index",
		Description: "Rewrite MODULES.md and the AGENTS.md block from the project's modules. Modifies the project.",
	}, func(ctx context.Context, _ *mcp.CallToolRequest, _ IndexInput) (*mcp.CallToolResult, any, error) {
		res, err := a.Index(ctx, projectDir, false, app.ArcAuto)
		return reply(res, err)
	})
	return s
}

// reply wraps v as the tool result: the CLI's --json text, plus the same
// value as structured content. Types such as search.Hit marshal differently
// from their Go shape, so no output schema is declared. An error becomes a
// tool error.
func reply(v any, err error) (*mcp.CallToolResult, any, error) {
	if err != nil {
		return nil, nil, err
	}
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return nil, nil, err
	}
	var structured any
	if err := json.Unmarshal(b, &structured); err != nil {
		return nil, nil, err
	}
	return &mcp.CallToolResult{
		Content:           []mcp.Content{&mcp.TextContent{Text: string(b)}},
		StructuredContent: structured,
	}, nil, nil
}

// Run serves the tools over stdio until the client disconnects.
func Run(ctx context.Context, a app.App, projectDir string) error {
	return New(a, projectDir).Run(ctx, &mcp.StdioTransport{})
}
