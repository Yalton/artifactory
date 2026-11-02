package search

import (
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

func m(name, eco, summary string, replaces, entry []string) catalog.Module {
	return catalog.Module{Descriptor: descriptor.Descriptor{Name: name, Ecosystem: eco, Summary: summary, Replaces: replaces, Entry: entry}}
}

var mods = []catalog.Module{
	m("CursorKit", "godot-csharp", "Stack that owns the mouse cursor mode.", []string{"setting Input.MouseMode directly"}, []string{"InputModeManager.Push"}),
	m("kvstore", "go", "Persistent string key-value store in one JSON file.", []string{"a mutex-guarded map saved to disk"}, []string{"kvstore.Open"}),
	m("config", "go", "Load typed configuration from files.", []string{"parsing env vars by hand"}, []string{"config.Load"}),
}

func TestRank(t *testing.T) {
	tests := []struct {
		name  string
		query []string
		eco   string
		want  []string
	}{
		{"cursor", []string{"mouse", "cursor", "mode"}, "", []string{"CursorKit"}},
		{"case insensitive", []string{"KVSTORE"}, "", []string{"kvstore"}},
		{"replaces beats entry", []string{"mutex"}, "", []string{"kvstore"}},
		{"ecosystem filter", []string{"config"}, "godot-csharp", nil},
		{"stopwords only", []string{"the", "of"}, "", nil},
		{"no match", []string{"send", "mail", "to", "the", "IRS"}, "", nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			hits := Rank(mods, tt.query, tt.eco)
			var got []string
			for _, h := range hits {
				got = append(got, h.Module.Name)
			}
			if len(got) != len(tt.want) || (len(got) > 0 && got[0] != tt.want[0]) {
				t.Errorf("got %v, want %v", got, tt.want)
			}
		})
	}
}

func TestWeightOrder(t *testing.T) {
	name := Rank([]catalog.Module{m("zebra", "go", "x", nil, nil)}, []string{"zebra"}, "")
	repl := Rank([]catalog.Module{m("a", "go", "x", []string{"zebra"}, nil)}, []string{"zebra"}, "")
	sum := Rank([]catalog.Module{m("a", "go", "zebra", nil, nil)}, []string{"zebra"}, "")
	ent := Rank([]catalog.Module{m("a", "go", "x", nil, []string{"zebra"})}, []string{"zebra"}, "")
	if len(name) != 1 || len(repl) != 1 || len(sum) != 1 || len(ent) != 1 {
		t.Fatalf("expected hits: %d %d %d %d", len(name), len(repl), len(sum), len(ent))
	}
	if !(name[0].Score >= repl[0].Score && repl[0].Score > sum[0].Score && sum[0].Score > ent[0].Score) {
		t.Errorf("weights: %v %v %v %v", name[0].Score, repl[0].Score, sum[0].Score, ent[0].Score)
	}
}
