package shortid_test

import (
	"testing"

	"repo.billbert.co/artifactory/shortid"
)

func TestNew(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		id, err := shortid.New(8)
		if err != nil {
			t.Fatal(err)
		}
		if len(id) != 8 {
			t.Fatalf("len %d", len(id))
		}
		for _, c := range id {
			if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z') {
				t.Fatalf("bad char %q", c)
			}
		}
		seen[id] = true
	}
	if len(seen) < 199 {
		t.Fatalf("too many collisions: %d unique", len(seen))
	}
}

func TestBadLength(t *testing.T) {
	if _, err := shortid.New(0); err == nil {
		t.Fatal("want error")
	}
}
