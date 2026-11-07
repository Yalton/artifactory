package search

import (
	"os"
	"path/filepath"
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
		{"prefix is one-way", []string{"model"}, "", nil},
		{"query prefix of token", []string{"persist"}, "", []string{"kvstore"}},
		{"a third of the words must match", []string{"mouse", "inventory", "drag", "drop"}, "", nil},
		{"a name word makes a partial match", []string{"mouse", "cursor", "inventory", "drag"}, "", []string{"CursorKit"}},
		{"a word only one replaces list claims", []string{"mutex", "pool"}, "", []string{"kvstore"}},
		{"a shared or summary-only word does not", []string{"load", "model"}, "", nil},
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
	if !(name[0].Score > sum[0].Score && sum[0].Score > repl[0].Score && repl[0].Score > ent[0].Score) {
		t.Errorf("weights: %v %v %v %v", name[0].Score, repl[0].Score, sum[0].Score, ent[0].Score)
	}
}

// kits loads the real Godot kit descriptors from internal/testdata/kits.
func kits(t *testing.T) []catalog.Module {
	t.Helper()
	root := filepath.Join("..", "testdata", "kits")
	dirs, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	var out []catalog.Module
	for _, d := range dirs {
		desc, err := descriptor.Load(filepath.Join(root, d.Name()))
		if err != nil {
			t.Fatalf("%s: %v", d.Name(), err)
		}
		out = append(out, catalog.Module{Descriptor: desc})
	}
	if len(out) != 8 {
		t.Fatalf("got %d kits, want 8", len(out))
	}
	return out
}

// TestRankKits checks live queries against the real kit catalog: the module
// built for the need wins, and a word the kits only mention in passing does
// not hide a gap.
func TestRankKits(t *testing.T) {
	all := kits(t)
	tests := []struct {
		query string
		want  string // top hit; "" means no match
	}{
		{"save game", "RunSaveKit"},
		{"saving a game", "RunSaveKit"},
		{"model loading", ""},
		{"send email via smtp", ""},
		{"inventory system with drag and drop items", ""},
		{"mouse cursor", "CursorKit"},
		{"scene loading", "TransitionKit"},
		{"rebind keys", "InputRemapKit"},
		// Partial matches that still find the kit: a name word, or a word
		// only one kit's replaces list claims.
		{"volume slider", "SettingsKit"},
		{"vsync setting", "SettingsKit"},
		{"settings menu", "SettingsKit"},
		{"fade between scenes", "TransitionKit"},
		{"door transition between rooms", "TransitionKit"},
		{"screen transition", "TransitionKit"},
		{"crash report on exception", "CrashKit"},
		{"developer console command", "DevConsoleKit"},
		{"rebind controls", "InputRemapKit"},
		{"key bindings", "InputRemapKit"},
		{"custom mouse cursor", "CursorKit"},
		{"hide cursor during play", "CursorKit"},
		{"debug logging", "DebugLogKit"},
		{"log room changes", "DebugLogKit"},
		{"save player position", "RunSaveKit"},
		{"fullscreen toggle", "SettingsKit"},
		{"continue last game", "RunSaveKit"},
		// No kit owns a pause menu; it is a gap.
		{"pause menu", ""},
	}
	for _, tt := range tests {
		t.Run(tt.query, func(t *testing.T) {
			hits := Rank(all, []string{tt.query}, "")
			if tt.want == "" {
				if len(hits) != 0 {
					t.Errorf("want no match, got %v", hits)
				}
				return
			}
			if len(hits) == 0 || hits[0].Module.Name != tt.want {
				t.Errorf("want top %s, got %v", tt.want, hits)
			}
		})
	}
}

func TestStem(t *testing.T) {
	for in, want := range map[string]string{
		"save": "sav", "saves": "sav", "saved": "sav", "saving": "sav",
		"loading": "load", "game": "gam", "gamepad": "gamepad", "bus": "bus",
		"class": "class", "need": "need",
	} {
		if got := stem(in); got != want {
			t.Errorf("stem(%q) = %q, want %q", in, got, want)
		}
	}
}
