# config

Fills a struct from environment variables, an optional `key=value` file and struct-tag defaults. Do not call `os.Getenv` yourself.

Install: `go get repo.billbert.co/artifactory/config`

## Wiring

```go
import "repo.billbert.co/artifactory/config"

type Settings struct {
	Addr string `env:"ADDR" default:":8080"`
	Data string `env:"DATA"`
}

var s Settings
if err := config.Load("SHORTENER", &s, ""); err != nil { // reads SHORTENER_ADDR, SHORTENER_DATA
	log.Fatal(err)
}
```

## Notes

- Precedence: env var `<PREFIX>_<ENV>`, then the file (lines `ADDR=:9000`, `#` comments), then `default`.
- The file path may be `""` or missing.
- Field types: `string`, `int`, `bool`, `float64`, `time.Duration`.
- Pass a pointer to a struct.

Runnable example: `example/main.go`. Test: `go test ./...`.
