// Package index renders MODULES.md and the AGENTS.md block.
package index

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/standard"
)

const (
	beginMarker = "<!-- artifactory:begin -->"
	endMarker   = "<!-- artifactory:end -->"
)

// Options tune the rendered text.
type Options struct {
	// Arc leaves out the preamble bullets arc's own guidance replaces.
	Arc bool
	// CLIInstall shows `artifactory install NAME` as each module's install
	// command, with the raw line after it.
	CLIInstall bool
	// NotInstalled names modules in scope but not installed yet; with
	// CLIInstall they are marked so the agent installs them before writing
	// what they cover. The raw render (--modules-only) does not mark them.
	NotInstalled map[string]bool
}

// notInstalledRule is added to the CLI preamble. Round 1 of the tool-value
// experiment found agents searched the library, then wrote the code anyway.
const notInstalledRule = "- Modules marked (not installed) are in the library but not in this project yet. Before writing code for anything one covers, run `artifactory install NAME`, then follow the Wiring section of its README. For a need no module here covers, run `artifactory search WORDS` before writing it yourself."

func preamble(eco string, opt Options) string {
	text := standard.Preamble(opt.Arc)
	if opt.CLIInstall {
		text = strings.TrimRight(text, "\n") + "\n" + notInstalledRule
	}
	if notes, ok := standard.Notes(eco); ok {
		text += "\n\n## Project notes (" + eco + ")\n\n" + notes
	}
	return text
}

// Render builds MODULES.md for the modules, matching the Python build_index.
func Render(eco string, mods []descriptor.Descriptor, opt Options) string {
	sorted := append([]descriptor.Descriptor{}, mods...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })
	parts := []string{strings.TrimSpace(preamble(eco, opt)), ""}
	for _, d := range sorted {
		if opt.CLIInstall && opt.NotInstalled[d.Name] {
			parts = append(parts, "## "+d.Name+" (not installed)", "", d.Summary, "",
				"Not installed yet. If you need what it covers, run `artifactory install "+d.Name+"` first, then follow its README's Wiring section.", "",
				"Use instead of writing:")
		} else {
			parts = append(parts, "## "+d.Name, "", d.Summary, "", "Use instead of writing:")
		}
		for _, r := range d.Replaces {
			parts = append(parts, "- "+r)
		}
		if opt.CLIInstall {
			parts = append(parts, "", "```", "artifactory install "+d.Name, "```", "", "(artifactory runs this for you; do not run it yourself: "+d.Install+")", "")
		} else {
			parts = append(parts, "", "```", d.Install, "```", "")
		}
		if len(d.Setup) > 0 {
			parts = append(parts, "Setup:")
			for _, s := range d.Setup {
				parts = append(parts, "- "+s)
			}
			parts = append(parts, "")
		}
	}
	return strings.Join(parts, "\n")
}

// AgentsBlock is the marked block placed in AGENTS.md.
func AgentsBlock(eco string, opt Options) string {
	return beginMarker + "\n" + preamble(eco, opt) + "\n\nSee MODULES.md for the modules in scope and their install commands.\n" + endMarker + "\n"
}

// WriteAgents replaces the marked block in path, or appends it after a blank
// line, creating the file if needed. A begin marker with no end marker after
// it is an error: guessing where the old block ends could delete the user's
// text, and appending would leave two blocks.
func WriteAgents(path, block string) error {
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	text := string(data)
	if b := strings.Index(text, beginMarker); b >= 0 {
		e := strings.Index(text[b:], endMarker)
		if e < 0 {
			return fmt.Errorf("%s has %s but no %s after it; add the end marker or remove the old block, then re-run", path, beginMarker, endMarker)
		}
		e += b + len(endMarker)
		if e < len(text) && text[e] == '\n' {
			e++
		}
		return os.WriteFile(path, []byte(text[:b]+block+text[e:]), 0o644)
	}
	if text != "" {
		if !strings.HasSuffix(text, "\n") {
			text += "\n"
		}
		text += "\n"
	}
	return os.WriteFile(path, []byte(text+block), 0o644)
}
