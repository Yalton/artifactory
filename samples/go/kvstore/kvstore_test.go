package kvstore_test

import (
	"fmt"
	"path/filepath"
	"sync"
	"testing"

	"repo.billbert.co/artifactory/kvstore"
)

func TestCreatesMissingFileAndRoundTrips(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sub", "data.json")
	s, err := kvstore.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.Get("a"); ok || err != nil {
		t.Fatalf("empty store: ok=%v err=%v", ok, err)
	}
	if added, err := s.PutIfAbsent("a", "1"); !added || err != nil {
		t.Fatalf("first put: %v %v", added, err)
	}
	if added, _ := s.PutIfAbsent("a", "2"); added {
		t.Fatal("second put must not overwrite")
	}
	s.Close()

	s, err = kvstore.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if v, ok, _ := s.Get("a"); !ok || v != "1" {
		t.Fatalf("reopen got %q %v", v, ok)
	}
}

func TestConcurrent(t *testing.T) {
	s, err := kvstore.Open(filepath.Join(t.TempDir(), "d.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.PutIfAbsent(fmt.Sprint("k", i), "v")
			s.Get("k0")
		}()
	}
	wg.Wait()
	if _, ok, _ := s.Get("k19"); !ok {
		t.Fatal("missing k19")
	}
}

func TestCorruptFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "d.json")
	s, _ := kvstore.Open(path)
	s.Close()
	if err := writeFile(path, "not json"); err != nil {
		t.Fatal(err)
	}
	if _, err := kvstore.Open(path); err == nil {
		t.Fatal("want error")
	}
}
