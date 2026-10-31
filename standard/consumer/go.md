### Before finishing

Build, vet and test, and confirm none of them prints an error:

```
go build ./... && go vet ./... && go test ./...
```

A server never exits on its own, so start it in the background, check it answers, then stop it:

```
go run ./cmd/<main> & pid=$!; sleep 3; curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/healthz; kill $pid
```

Then run `go list -deps ./cmd/<main>` and confirm each module's import path is in the output.
