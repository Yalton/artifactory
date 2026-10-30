// Example: serve a handler with /healthz and graceful shutdown (Ctrl-C to stop).
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"

	"repo.billbert.co/artifactory/httpserver"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /hello", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintln(w, "hello")
	})
	if err := httpserver.Run(context.Background(), "127.0.0.1:8080", mux); err != nil {
		log.Fatal(err)
	}
}
