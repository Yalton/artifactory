package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestSearchCommand(t *testing.T) {
	kits := "dir:../../internal/testdata/kits"
	samples := "dir:../../samples/go"
	tests := []struct {
		name      string
		args      []string
		wantFirst string // first line starts with this; "" means no hits
	}{
		{"finds cursor", []string{"search", "mouse", "cursor", "mode", "--provider", kits}, "CursorKit"},
		{"finds kv", []string{"search", "persist", "key", "value", "--provider", samples}, "kvstore"},
		{"flags first", []string{"search", "--provider", samples, "persist", "key", "value"}, "kvstore"},
		{"ecosystem filter", []string{"search", "config", "--ecosystem", "godot-csharp", "--provider", samples}, ""},
		{"no match kits", []string{"search", "send", "mail", "to", "the", "IRS", "--provider", kits}, ""},
		{"no match samples", []string{"search", "send", "mail", "to", "the", "IRS", "--provider", samples}, ""},
		{"inventory gap kits", []string{"search", "inventory system with drag and drop items", "--provider", kits}, ""},
		{"inventory gap samples", []string{"search", "inventory system with drag and drop items", "--provider", samples}, ""},
		{"model loading samples", []string{"search", "model", "loading", "--provider", samples}, ""},
		{"cursor short query", []string{"search", "mouse", "cursor", "--provider", kits}, "CursorKit"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var out, errb bytes.Buffer
			if code := run(tt.args, &out, &errb); code != 0 {
				t.Fatalf("exit %d: %s", code, errb.String())
			}
			s := out.String()
			if tt.wantFirst == "" {
				if !strings.Contains(s, "no module matches") || !strings.Contains(s, "record this as a gap") {
					t.Errorf("want no-match message, got %q", s)
				}
				return
			}
			if !strings.HasPrefix(s, tt.wantFirst) || !strings.Contains(s, "install: ") {
				t.Errorf("got %q", s)
			}
		})
	}
}

func TestSearchUsage(t *testing.T) {
	var out, errb bytes.Buffer
	if code := run([]string{"search", "--provider", "dir:."}, &out, &errb); code != 2 {
		t.Errorf("exit %d, want 2", code)
	}
}
