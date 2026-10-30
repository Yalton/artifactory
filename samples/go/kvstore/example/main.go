// Example: store and fetch a value in a JSON file.
package main

import (
	"fmt"
	"log"
	"os"
	"path/filepath"

	"repo.billbert.co/artifactory/kvstore"
)

func main() {
	dir, err := os.MkdirTemp("", "kvexample")
	if err != nil {
		log.Fatal(err)
	}
	defer os.RemoveAll(dir)

	s, err := kvstore.Open(filepath.Join(dir, "data.json"))
	if err != nil {
		log.Fatal(err)
	}
	defer s.Close()

	added, _ := s.PutIfAbsent("greeting", "hello")
	v, found, _ := s.Get("greeting")
	fmt.Println(added, v, found)
}
