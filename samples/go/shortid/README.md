# shortid

Random base62 identifiers (`0-9a-zA-Z`) from `crypto/rand`. Do not import `math/rand` or `crypto/rand` to make codes.

Install: `go get repo.billbert.co/artifactory/shortid`

## Wiring

```go
import "repo.billbert.co/artifactory/shortid"

code, err := shortid.New(7) // for example "aZ3kP9q"
if err != nil {
	log.Fatal(err)
}
```

## Notes

- `New(n)` returns exactly `n` characters; `n` must be positive.
- Ids are random, not unique. When ids must be unique, retry if the store says the id is taken.

Runnable example: `example/main.go`. Test: `go test ./...`.
