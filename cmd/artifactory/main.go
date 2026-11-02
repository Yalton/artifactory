// Command artifactory manages a catalog of stitchable modules.
package main

import (
	"fmt"
	"io"
	"os"
	"strings"
)

var commands = []string{"validate", "catalog", "show", "search", "init", "add", "index", "install"}

// handlers maps implemented commands to their entry points.
var handlers = map[string]func(*output, []string) int{
	"validate": runValidate,
	"catalog":  runCatalog,
	"show":     runShow,
	"search":   runSearch,
	"init":     runInit,
	"add":      runAdd,
	"index":    runIndex,
	"install":  runInstall,
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// run executes artifactory with args and returns the process exit code.
func run(args []string, stdout, stderr io.Writer) int {
	out := &output{stdout: stdout, stderr: stderr}
	args, out.json = extractJSONFlag(args)
	args, refreshCache = extractFlag(args, "refresh")

	if len(args) == 0 {
		fmt.Fprint(stderr, usage())
		return exitUsage
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "-h", "--help", "help":
		fmt.Fprint(stdout, usage())
		return exitOK
	}
	if h, ok := handlers[cmd]; ok {
		return h(out, rest)
	}
	return out.fail(exitUsage, fmt.Sprintf("unknown command %q\n\n%s", cmd, usage()))
}

// extractJSONFlag removes --json from args (before any "--") so every
// command accepts it in any position.
func extractJSONFlag(args []string) ([]string, bool) {
	return extractFlag(args, "json")
}

// extractFlag removes the boolean flag --name (or -name) from args, before
// any "--", and reports whether it was present.
func extractFlag(args []string, name string) ([]string, bool) {
	var kept []string
	found := false
	for i, a := range args {
		if a == "--" {
			kept = append(kept, args[i:]...)
			break
		}
		if a == "--"+name || a == "-"+name {
			found = true
			continue
		}
		kept = append(kept, a)
	}
	return kept, found
}

func usage() string {
	return "usage: artifactory [--json] [--refresh] <command> [args]\n\ncommands: " +
		strings.Join(commands, ", ") + "\n"
}
