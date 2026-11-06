# kvstore

A string key-value store kept in a single JSON file. Writes are atomic and the store is safe for concurrent use. Do not read or write JSON files yourself.

Install: `go get repo.billbert.co/artifactory/kvstore`

## Wiring

```go
import "repo.billbert.co/artifactory/kvstore"

store, err := kvstore.Open(path) // creates the file if it is missing
if err != nil {
	log.Fatal(err)
}
defer store.Close()

added, err := store.PutIfAbsent("key", "value") // added is false if key exists
val, found, err := store.Get("key")
```

## Notes

- `PutIfAbsent` never overwrites; use it to claim a key without races.
- Every write is fsynced (file, then its directory after the atomic rename) before the call returns.
- `Open` fails if the file exists but is not valid JSON.

Runnable example: `example/main.go`. Test: `go test ./...`.
