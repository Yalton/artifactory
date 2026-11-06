"""Serve an http.server handler with a health endpoint and graceful shutdown."""
from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

print("[http-runner] live", flush=True)

__all__ = ["run"]

HEALTH_PATH = "/healthz"
_POLL_S = 0.2


class _Server(ThreadingHTTPServer):
    daemon_threads = False  # request threads are joined on close, so in-flight requests finish
    block_on_close = True


def _is_health(path: str) -> bool:
    return path == HEALTH_PATH or path.startswith(HEALTH_PATH + "?")


def _healthy(check: Callable[[], object] | None) -> tuple[bool, str]:
    if check is None:
        return True, "ok"
    try:
        ok = check()
    except Exception as e:  # the check failing is the unhealthy signal
        return False, f"unhealthy: {e}"
    return (False, "unhealthy") if ok is False else (True, "ok")


def _wrap(handler: type[BaseHTTPRequestHandler], check: Callable[[], object] | None):
    class Handler(handler):  # type: ignore[misc, valid-type]
        def _health(self, with_body: bool) -> None:
            ok, text = _healthy(check)
            body = (text + "\n").encode()
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if with_body:
                self.wfile.write(body)

        def _delegate(self, method: str) -> None:
            inner = getattr(super(), method, None)
            if inner is None:
                self.send_error(501, f"Unsupported method ({self.command!r})")
                return
            inner()

        def do_GET(self) -> None:
            if _is_health(self.path):
                self._health(True)
            else:
                self._delegate("do_GET")

        def do_HEAD(self) -> None:
            if _is_health(self.path):
                self._health(False)
            else:
                self._delegate("do_HEAD")

    Handler.__name__ = Handler.__qualname__ = handler.__name__
    return Handler


def run(handler: type[BaseHTTPRequestHandler], port: int = 8080, host: str = "", *,
        health_check: Callable[[], object] | None = None, stop: threading.Event | None = None) -> None:
    """Serve `handler` on host:port, adding GET /healthz. Block until SIGINT, SIGTERM or `stop` is set,
    then stop accepting, let requests in flight finish and return. Raises OSError if the port cannot be bound.

    `health_check` makes /healthz answer 503 when it raises or returns False. Signal handlers are installed
    only when called from the main thread, and the previous handlers are restored on return."""
    if not (isinstance(handler, type) and issubclass(handler, BaseHTTPRequestHandler)):
        raise TypeError("http_runner.run: handler must be a BaseHTTPRequestHandler subclass")
    server = _Server((host, port), _wrap(handler, health_check))
    done = threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: done.set())
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": _POLL_S},
                               name="http-runner", daemon=True)
    serving.start()
    try:
        while not done.is_set() and not (stop is not None and stop.is_set()) and serving.is_alive():
            done.wait(_POLL_S)
    finally:
        server.shutdown()
        server.server_close()
        serving.join()
        for sig, old in previous.items():
            signal.signal(sig, old)
