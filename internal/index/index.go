// Package index renders MODULES.md and the AGENTS.md block.
package index

import (
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
}

func preamble(eco string, opt Options) string {
	text := standard.Preamble(opt.Arc)
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
		parts = append(parts, "## "+d.Name, "", d.Summary, "", "Use instead of writing:")
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
// line, creating the file if needed.
func WriteAgents(path, block string) error {
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	text := string(data)
	b, e := strings.Index(text, beginMarker), strings.Index(text, endMarker)
	if b >= 0 && e > b {
		e += len(endMarker)
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
