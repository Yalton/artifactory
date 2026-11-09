package app

import "testing"

func TestWiringSection(t *testing.T) {
	readme := "# kit\n\nIntro.\n\n## Wiring\n\n```go\nx := kit.New()\n```\n\n### Detail\n\nmore\n\n## Notes\n\nnot this\n"
	want := "## Wiring\n\n```go\nx := kit.New()\n```\n\n### Detail\n\nmore"
	if got := wiringSection(readme); got != want {
		t.Errorf("got %q, want %q", got, want)
	}
	if got := wiringSection("# kit\n\nno section\n"); got != "" {
		t.Errorf("no section: got %q", got)
	}
}
