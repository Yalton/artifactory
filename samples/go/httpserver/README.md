# httpserver

Runs your `http.Handler`, adds `GET /healthz`, and shuts down gracefully on SIGINT or SIGTERM. `Run` handles SIGINT/SIGTERM itself. Do not use `http.ListenAndServe`, `http.Server` or `signal.Notify` yourself.

Install: `go get repo.billbert.co/artifactory/httpserver`

## Wiring

```go
package main

import (
	"log"
	"net/http"

	"repo.billbert.co/artifactory/httpserver"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /hello", hello)

	// Blocks until shutdown; returns nil after a clean stop.
	if err := httpserver.Run(":8080", mux); err != nil {
		log.Fatal(err)
	}
}

func hello(w http.ResponseWriter, r *http.Request) { w.Write([]byte("hello\n")) }
```

## Notes

- `GET /healthz` returns 200. Do not register it yourself.
- `httpserver.WithHealthCheck(func(context.Context) error)` makes `/healthz` return 503 when the function errors.
- Every other path goes to your handler.
- `httpserver.WithContext(ctx)` also stops the server when `ctx` is cancelled. For tests and embedding only.
- `Run` returns an error at once if `addr` cannot be listened on.

Runnable example: `example/main.go`. Test: `go test ./...`.
