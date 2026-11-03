package app

import (
	"reflect"
	"testing"

	"repo.billbert.co/artifactory/artifactory/internal/arcreg"
	"repo.billbert.co/artifactory/artifactory/internal/catalog"
	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
)

func TestArcEntry(t *testing.T) {
	tests := []struct {
		name    string
		d       descriptor.Descriptor
		want    arcreg.Entry
		wantErr bool
	}{
		{
			name: "godot with setup",
			d: descriptor.Descriptor{Name: "CursorKit", Ecosystem: "godot-csharp", Summary: "S.",
				Replaces: []string{"r1"}, Entry: []string{"Mgr.Push"}, Liveness: "[CursorKit] live",
				Setup: []string{"a", "b"}},
			want: arcreg.Entry{ID: "CursorKit", Summary: "S.", Paths: []string{"addons/CursorKit/**"},
				Covers: []string{"r1"}, Entry: []string{"Mgr.Push"},
				Rules: []string{"Print `[CursorKit] live` at startup. Setup: a; b."}},
		},
		{
			name: "go import without paths",
			d: descriptor.Descriptor{Name: "kit", Ecosystem: "go", Summary: "S.", Entry: []string{"kit.Do"},
				Liveness: "kit live", Install: "go get example.com/kit@latest"},
			want: arcreg.Entry{ID: "kit", Summary: "S.", Entry: []string{"kit.Do"}, Import: "example.com/kit",
				Rules: []string{"Print `kit live` at startup."}},
		},
		{
			name:    "go with bad install line",
			d:       descriptor.Descriptor{Name: "kit", Ecosystem: "go", Install: "make"},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := arcEntry(catalog.Module{Descriptor: tt.d})
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v", err)
			}
			if !tt.wantErr && !reflect.DeepEqual(got, tt.want) {
				t.Errorf("got %+v\nwant %+v", got, tt.want)
			}
		})
	}
}
