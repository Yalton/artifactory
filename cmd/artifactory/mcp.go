package main

import (
	"context"
	"os"
	"os/signal"

	"repo.billbert.co/artifactory/artifactory/internal/app"
	"repo.billbert.co/artifactory/artifactory/internal/mcpserver"
)

// runMCP serves search, show, install and index as MCP tools over stdio.
func runMCP(out *output, args []string) int {
	fs := newFlags("mcp")
	dir := fs.String("project", ".", "project directory")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 {
		return out.fail(exitUsage, "usage: artifactory mcp [--project DIR]")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := mcpserver.Run(ctx, app.App{Refresh: refreshCache}, *dir); err != nil && ctx.Err() == nil {
		return out.fail(exitUsage, err.Error())
	}
	return exitOK
}
