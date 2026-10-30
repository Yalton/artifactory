Build a URL shortener in Go in this module (`shortener`). Use every module listed in `MODULES.md` for the job it does, instead of writing that functionality yourself.

Contracts:
- The main package is `./cmd/shortener`.
- Configuration comes from environment variables: `SHORTENER_ADDR` (listen address, default `:8080`) and `SHORTENER_DATA` (path of the data file).
- `POST /links` with JSON `{"url": "<url>"}` returns 201 and `{"code": "<code>"}`.
- `GET /<code>` returns 302 with the `Location` header set to the stored URL.
- An unknown code returns 404.
- `GET /healthz` returns 200.
