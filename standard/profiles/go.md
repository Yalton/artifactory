# Go profile (ecosystem `go`)

Applies Stitchability Standard Draft 0.1.

| Rule | In this profile |
|---|---|
| 1 Descriptor | `module.yaml` at the module root. |
| 2 Docs travel | README and `module.yaml` are in the module, so `go get` brings them. |
| 3 Unmodified | `go mod verify` passes. The consumer's `go.mod` has no `replace` directives. |
| 4 Live | Every module in `go.mod` appears in `go list -deps` of the main package (for example `./cmd/...`). |
| 5 Example | An `example/` directory with a runnable `main.go`. |
| 6 Setup | Prefer zero steps. |
| 7 Index | Generated from `module.yaml` files. |
| 8 Preamble | Prepended to the index. |

## Module path

`repo.billbert.co/artifactory/<name>`

## go.mod and versioning

The first released version is `v0.1.0`. The module's `go.mod` declares `go 1.24`.

## Install

```
go get repo.billbert.co/artifactory/<name>
```

## Liveness

Run `go list -deps` on the main package. The module's path must appear in the output.

## Unmodified

Go's module cache is read-only, so editing is largely prevented. Run `go mod verify`, and reject any `replace` directive that points at a local copy.

## Consumer notes

`standard/consumer/go.md` holds the consumer-facing project notes (verification commands). Every index for this ecosystem includes it after the preamble.
