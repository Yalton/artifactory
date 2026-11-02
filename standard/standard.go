// Package standard embeds the stitchability standard's markdown.
package standard

import (
	"embed"
	"strings"
)

//go:embed preamble.md consumer/*.md profiles/*.md
var files embed.FS

// Preamble returns the shared preamble text, trimmed.
func Preamble() string {
	b, err := files.ReadFile("preamble.md")
	if err != nil {
		panic(err)
	}
	return strings.TrimSpace(string(b))
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
