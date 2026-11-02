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

func preamble(eco string) string {
	text := standard.Preamble()
	if notes, ok := standard.Notes(eco); ok {
		text += "\n\n## Project notes (" + eco + ")\n\n" + notes
	}
	return text
}

// Render builds MODULES.md for the modules, matching the Python build_index.
func Render(eco string, mods []descriptor.Descriptor) string {
	sorted := append([]descriptor.Descriptor{}, mods...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })
	parts := []string{strings.TrimSpace(preamble(eco)), ""}
	for _, d := range sorted {
		parts = append(parts, "## "+d.Name, "", d.Summary, "", "Use instead of writing:")
		for _, r := range d.Replaces {
			parts = append(parts, "- "+r)
		}
		parts = append(parts, "", "```", d.Install, "```", "")
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
func AgentsBlock(eco string) string {
	return beginMarker + "\n" + preamble(eco) + "\n\nSee MODULES.md for the modules in scope and their install commands.\n" + endMarker + "\n"
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
