Build a URL shortener in Python in this directory. Use every module listed in `MODULES.md` for the job it does, instead of writing that functionality yourself.

Contracts:
- The app is the package `shortener`, started from the project root with `python -m shortener`.
- Configuration comes from environment variables: `SHORTENER_PORT` (listen port, default `8080`) and `SHORTENER_DATA` (path of the data file, default `shortener.json`).
- Links are stored in the data file and survive a restart.
- `POST /links` with JSON `{"url": "<url>"}` returns 201 and `{"code": "<code>"}`.
- `GET /<code>` returns 302 with the `Location` header set to the stored URL.
- An unknown code returns 404.
- `GET /healthz` returns 200.
- Tests live in `tests/` and run with `pytest`.
