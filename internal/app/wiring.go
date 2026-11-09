package app

import "strings"

// wiringSection returns the README's Wiring section, heading included, up to
// the next heading of the same or a higher level; "" when there is none.
func wiringSection(readme string) string {
	lines := strings.Split(readme, "\n")
	start, level := -1, 0
	for i, l := range lines {
		h := len(l) - len(strings.TrimLeft(l, "#"))
		if h == 0 || !strings.HasPrefix(l[h:], " ") {
			continue
		}
		if start < 0 {
			if strings.EqualFold(strings.TrimSpace(l[h:]), "wiring") {
				start, level = i, h
			}
			continue
		}
		if h <= level {
			return strings.TrimSpace(strings.Join(lines[start:i], "\n"))
		}
	}
	if start < 0 {
		return ""
	}
	return strings.TrimSpace(strings.Join(lines[start:], "\n"))
}
