// Example: print a random 7-character id.
package main

import (
	"fmt"
	"log"

	"repo.billbert.co/artifactory/shortid"
)

func main() {
	id, err := shortid.New(7)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(id)
}
