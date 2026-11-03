Read this index before writing any code.

- If a module here does what you need, use it instead of writing your own.
- Install a module only with its `install` command.
- Never edit files inside an installed module. Configure, wrap or extend it through its public surface.
- Wire every module you install into the program's real entry point. A module that only tests reach is not in use.
- Before finishing, build and run the project and confirm each module's liveness marker appears and no errors are printed. The project notes below give the commands.
- The Wiring section of the module's README shows where its calls go. Merge it into your existing class of the same name instead of adding a second one.
- When the Before-finishing checks pass, stop. A module is in use once it is wired and its marker prints. Do not add features the task did not ask for (console commands, menus) just to exercise a module.

## Project notes (go)

### Reading a module

After installing, read each module's README before coding. Its Wiring section is the snippet to follow:

```
cat $(go list -m -f '{{.Dir}}' <module path>)/README.md
```

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

## config

Load typed settings from env vars, an optional key=value file and struct-tag defaults.

Use instead of writing:
- reading settings with os.Getenv
- parsing env vars and config files into a struct
- default values for settings

```
go get repo.billbert.co/artifactory/config
```

## httpserver

Run an http.Handler with GET /healthz and graceful shutdown on signal or cancel.

Use instead of writing:
- http.ListenAndServe and http.Server setup
- graceful shutdown on SIGINT and SIGTERM
- a /healthz endpoint

```
go get repo.billbert.co/artifactory/httpserver
```

## kvstore

Persistent string key-value store in one JSON file, safe for concurrent use.

Use instead of writing:
- storing key-value data in a JSON file
- a mutex-guarded map saved to disk
- atomic file rewrite on every write

```
go get repo.billbert.co/artifactory/kvstore
```

## shortid

Short random base62 identifiers from crypto/rand.

Use instead of writing:
- generating random short codes or ids
- random strings with math/rand or crypto/rand

```
go get repo.billbert.co/artifactory/shortid
```
