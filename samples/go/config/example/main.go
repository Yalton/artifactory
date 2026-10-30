// Example: load settings from SHORTENER_ADDR / SHORTENER_DATA, an optional file, or defaults.
package main

import (
	"fmt"
	"log"

	"repo.billbert.co/artifactory/config"
)

type Settings struct {
	Addr string `env:"ADDR" default:":8080"`
	Data string `env:"DATA" default:"data.json"`
}

func main() {
	var s Settings
	if err := config.Load("SHORTENER", &s, "shortener.conf"); err != nil {
		log.Fatal(err)
	}
	fmt.Println(s.Addr, s.Data)
}
