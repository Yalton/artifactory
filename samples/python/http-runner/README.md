# http-runner

Serves your `http.server.BaseHTTPRequestHandler` subclass on a threading server, answers `GET /healthz`, and shuts down gracefully on SIGINT or SIGTERM. `run` handles the signals itself. Do not create `HTTPServer` or `ThreadingHTTPServer`, call `serve_forever` or install signal handlers yourself.

Install: `pip install "http-runner @ git+ssh://git@repo.billbert.co/artifactory/http-runner.git@v0.1.1"` (offline, with `PIP_FIND_LINKS` or `UV_FIND_LINKS` set: `pip install "http-runner==0.1.1"`)

Importing `http_runner` prints `[http-runner] live` once. There is no setup step.

## Wiring

```python
from http.server import BaseHTTPRequestHandler

import http_runner


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"hello\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    # Blocks until SIGINT or SIGTERM, then returns after a clean stop.
    http_runner.run(Handler, port=8080)


if __name__ == "__main__":
    main()
```

To give the handler state (a store, settings), build the class in a function and close over it:

```python
def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            value = store.get(self.path)
            ...
    return Handler

http_runner.run(make_handler(store), port=settings.port)
```

## Notes

- `GET /healthz` (and `HEAD`) returns 200 `ok`. Do not handle it yourself. Every other request goes to your handler.
- `run(..., health_check=fn)` makes `/healthz` return 503 when `fn()` raises or returns `False`.
- `run(handler, port, host="")` listens on all IPv4 addresses by default. It raises `OSError` at once if the port cannot be bound.
- Each request runs in its own thread, so shared state must be thread-safe. On shutdown, idle keep-alive connections are closed and requests in flight get up to 10 seconds to finish before `run` returns.
- An error that stops the server loop is re-raised from `run`.
- Signal handling needs the main thread: call `run` from the main thread of your app. Called from any other thread, `run` installs no signal handlers and stops only when its `stop` event is set:

```python
import threading

stop = threading.Event()
t = threading.Thread(target=http_runner.run, args=(Handler,), kwargs={"port": 8080, "stop": stop})
t.start()
...
stop.set()  # run returns after a graceful stop
t.join()
```

Runnable example: `example/main.py`. Test: `pytest`.
