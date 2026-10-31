### Before finishing

Build, vet and test, and confirm none of them prints an error:

```
go build ./... && go vet ./... && go test ./...
```

A server never exits on its own. Build it, start it in the background, wait for `/healthz` to answer 200, then stop it:

```
go build -o /tmp/app ./cmd/<main>
/tmp/app & pid=$!
for i in $(seq 20); do curl -sf -o /dev/null localhost:8080/healthz && echo healthy && break; sleep 0.5; done
kill $pid
```

Then run `go list -deps ./cmd/<main>` and confirm each module's import path is in the output.
