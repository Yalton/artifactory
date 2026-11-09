Read this index before writing any code.

- If a module here does what you need, use it instead of writing your own.
- Install a module only with its `install` command.
- Before finishing, build and run the project and confirm each module's liveness marker appears and no errors are printed. The project notes below give the commands.
- The Wiring section of the module's README shows where its calls go. Merge it into your existing class of the same name instead of adding a second one.
- When the Before-finishing checks pass, stop. A module is in use once it is wired and its marker prints. Do not add features the task did not ask for (console commands, menus) just to exercise a module.
- Modules marked (not installed) are in the library but not in this project yet. Before writing code for anything one covers, run `artifactory install NAME`, then follow the Wiring section of its README. For a need no module here covers, run `artifactory search WORDS` before writing it yourself.

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
artifactory install config
```

(artifactory runs this for you; do not run it yourself: go get repo.billbert.co/artifactory/config)
