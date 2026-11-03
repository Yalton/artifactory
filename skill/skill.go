// Package skill embeds the agent skill file that artifactory init installs.
package skill

import _ "embed"

//go:embed SKILL.md
var text string

// Text returns the contents of SKILL.md.
func Text() string { return text }
