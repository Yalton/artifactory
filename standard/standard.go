// Package standard embeds the stitchability standard's markdown.
package standard

import (
	"embed"
	"strings"
)

//go:embed preamble.md consumer/*.md profiles/*.md
var files embed.FS

// arcMarker ends a preamble line that arc's own guidance replaces.
const arcMarker = " <!-- arc -->"

// Preamble returns the shared preamble text, trimmed. Lines marked with
// <!-- arc --> lose the marker, or are dropped when arc is set.
func Preamble(arc bool) string {
	b, err := files.ReadFile("preamble.md")
	if err != nil {
		panic(err)
	}
	var out []string
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasSuffix(line, arcMarker) {
			if arc {
				continue
			}
			line = strings.TrimSuffix(line, arcMarker)
		}
		out = append(out, line)
	}
	return strings.TrimSpace(strings.Join(out, "\n"))
}

// Notes returns the consumer notes for an ecosystem, trimmed. The bool is
// false when the ecosystem has none.
func Notes(eco string) (string, bool) {
	b, err := files.ReadFile("consumer/" + eco + ".md")
	if err != nil {
		return "", false
	}
	return strings.TrimSpace(string(b)), true
}
