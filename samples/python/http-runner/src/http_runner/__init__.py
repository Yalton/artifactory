"""Serve an http.server handler with a health endpoint and graceful shutdown."""
from __future__ import annotations

import signal
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

print("[http-runner] live", flush=True)

__all__ = ["run"]

HEALTH_PATH = "/healthz"
_POLL_S = 0.2
JOIN_TIMEOUT_S = 10.0  # how long shutdown waits for requests in flight


class _Server(ThreadingHTTPServer):
    """Tracks each connection, so shutdown can close the idle keep-alive ones and wait, for a bounded time,
    for requests in flight. Connection threads are daemons: one still busy at the deadline does not keep the
    process alive."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._conn_handlers: set = set()
        self._conn_threads: set[threading.Thread] = set()
        self.stopping = False

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._connection, args=(request, client_address), daemon=True)
        with self._lock:
            self._conn_threads.add(t)
        t.start()

    def _connection(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            with self._lock:
                self._conn_threads.discard(threading.current_thread())

    def track(self, handler, on: bool) -> None:
        with self._lock:
            (self._conn_handlers.add if on else self._conn_handlers.discard)(handler)
            idle_at_stop = on and self.stopping
        if idle_at_stop:
            self._wake(handler)

    def close_idle(self) -> None:
        """Stop reading on every connection waiting for its next request; busy ones close after replying."""
        with self._lock:
            self.stopping = True
            idle = [h for h in self._conn_handlers if h.idle]
        for h in idle:
            self._wake(h)

    @staticmethod
    def _wake(handler) -> None:
        try:
            handler.connection.shutdown(socket.SHUT_RD)  # the blocked readline sees EOF; replies can still go out
        except OSError:
            pass

    def join_connections(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                threads = list(self._conn_threads)
            if not threads:
                return
            left = deadline - time.monotonic()
            if left <= 0:
                return
            threads[0].join(min(left, _POLL_S))


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
        idle = True  # waiting for the next request line

        def setup(self) -> None:
            super().setup()
            self.server.track(self, True)

        def finish(self) -> None:
            try:
                super().finish()
            finally:
                self.server.track(self, False)

        def parse_request(self) -> bool:
            self.idle = False
            return super().parse_request()

        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            finally:
                self.idle = True
                if self.server.stopping:
                    self.close_connection = True

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
    then stop accepting, close idle keep-alive connections, give requests in flight up to JOIN_TIMEOUT_S
    to finish and return. Raises OSError if the port cannot be bound, and re-raises any error that stops
    the server loop.

    `health_check` makes /healthz answer 503 when it raises or returns False. Signal handlers are installed
    only when called from the main thread, and the previous handlers are restored on return."""
    if not (isinstance(handler, type) and issubclass(handler, BaseHTTPRequestHandler)):
        raise TypeError("http_runner.run: handler must be a BaseHTTPRequestHandler subclass")
    server = _Server((host, port), _wrap(handler, health_check))
    done = threading.Event()
    failed: list[BaseException] = []
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: done.set())

    def serve() -> None:
        try:
            server.serve_forever(poll_interval=_POLL_S)
        except BaseException as e:
            failed.append(e)

    serving = threading.Thread(target=serve, name="http-runner", daemon=True)
    serving.start()
    try:
        while not done.is_set() and not (stop is not None and stop.is_set()) and serving.is_alive():
            done.wait(_POLL_S)
    finally:
        if serving.is_alive():
            server.shutdown()
        serving.join()
        server.close_idle()
        server.join_connections(JOIN_TIMEOUT_S)
        server.server_close()
        for sig, old in previous.items():
            signal.signal(sig, old)
    if failed:
        raise failed[0]
