import http.client
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler

import pytest

import http_runner


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port, method="GET", path="/", timeout=5):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request(method, path)
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def wait_up(port, deadline=5.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            return request(port, path="/healthz")
        except OSError:
            time.sleep(0.05)
    raise AssertionError("server never answered")


class Hello(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Serving:
    def __init__(self, handler, **kw):
        self.port = free_port()
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, args=(handler,), kwargs=kw)

    def _run(self, handler, **kw):
        try:
            http_runner.run(handler, self.port, "127.0.0.1", stop=self.stop, **kw)
        except BaseException as e:
            self.error = e

    def __enter__(self):
        self.thread.start()
        wait_up(self.port)
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(10)
        assert not self.thread.is_alive(), "run did not return after stop"
        assert self.error is None, self.error


def test_healthz_and_handler_paths():
    with Serving(Hello) as s:
        assert request(s.port, path="/healthz") == (200, b"ok\n")
        assert request(s.port, path="/healthz?x=1")[0] == 200
        assert request(s.port, "HEAD", "/healthz")[0] == 200
        assert request(s.port, path="/a/b") == (200, b"hello /a/b")


def test_health_check_failure_returns_503():
    def boom():
        raise RuntimeError("db down")

    with Serving(Hello, health_check=boom) as s:
        status, body = request(s.port, path="/healthz")
        assert status == 503 and b"db down" in body
    with Serving(Hello, health_check=lambda: False) as s:
        assert request(s.port, path="/healthz")[0] == 503


def test_unsupported_method_is_501():
    with Serving(Hello) as s:
        assert request(s.port, "HEAD", "/x")[0] == 501
        assert request(s.port, "POST", "/x")[0] == 501


def test_in_flight_request_finishes_on_stop():
    started = threading.Event()

    class Slow(Hello):
        def do_GET(self):
            started.set()
            time.sleep(0.5)
            super().do_GET()

    with Serving(Slow) as s:
        got = {}
        t = threading.Thread(target=lambda: got.update(r=request(s.port, path="/slow")))
        t.start()
        assert started.wait(5)
        s.stop.set()
        t.join(10)
    assert got["r"] == (200, b"hello /slow")


def test_port_in_use_raises_at_once():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(OSError):
            http_runner.run(Hello, busy.getsockname()[1], "127.0.0.1")


def test_rejects_a_non_handler():
    with pytest.raises(TypeError):
        http_runner.run(object, free_port())


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_stops_the_server_cleanly(tmp_path, sig):
    port = free_port()
    script = tmp_path / "app.py"
    script.write_text(textwrap.dedent(f"""
        from http.server import BaseHTTPRequestHandler
        import http_runner
        http_runner.run(BaseHTTPRequestHandler, {port}, "127.0.0.1")
        print("returned", flush=True)
    """))
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    try:
        wait_up(port)
        proc.send_signal(sig)
        out, _ = proc.communicate(timeout=10)
    finally:
        proc.kill()
    assert proc.returncode == 0, out
    lines = out.splitlines()
    assert lines.count("[http-runner] live") == 1 and "returned" in lines and "Traceback" not in out, out


def test_sigterm_with_an_idle_keep_alive_connection_returns_promptly(tmp_path):
    port = free_port()
    script = tmp_path / "app.py"
    script.write_text(textwrap.dedent(f"""
        from http.server import BaseHTTPRequestHandler
        import http_runner

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"hi")

        http_runner.run(H, {port}, "127.0.0.1")
        print("returned", flush=True)
    """))
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    conn = None
    try:
        wait_up(port)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/x")
        r = conn.getresponse()
        assert r.status == 200 and r.read() == b"hi" and not r.will_close  # the connection stays open, idle
        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=5)
        took = time.monotonic() - start
    finally:
        if conn is not None:
            conn.close()
        proc.kill()
    assert proc.returncode == 0 and "returned" in out and "Traceback" not in out, out
    assert took < 3, took


def test_keep_alive_request_in_flight_finishes_then_closes():
    started = threading.Event()

    class Slow(Hello):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            started.set()
            time.sleep(0.5)
            super().do_GET()

    with Serving(Slow) as s:
        conn = http.client.HTTPConnection("127.0.0.1", s.port, timeout=5)
        got = {}

        def call():
            conn.request("GET", "/slow")
            r = conn.getresponse()
            got.update(status=r.status, body=r.read(), will_close=r.will_close)

        t = threading.Thread(target=call)
        t.start()
        assert started.wait(5)
        start = time.monotonic()
        s.stop.set()
        t.join(10)
        s.thread.join(10)
        assert time.monotonic() - start < 3
        conn.close()
    assert got["status"] == 200 and got["body"] == b"hello /slow"


def test_serve_loop_error_is_re_raised(monkeypatch):
    def boom(self, poll_interval=0.5):
        raise RuntimeError("selector broke")

    monkeypatch.setattr(http_runner._Server, "serve_forever", boom)
    with pytest.raises(RuntimeError, match="selector broke"):
        http_runner.run(Hello, free_port(), "127.0.0.1", stop=threading.Event())


def test_docs_travel_as_package_data():
    from importlib.resources import files
    pkg = files("http_runner")
    assert "name: http-runner" in (pkg / "module.yaml").read_text()
    assert "# http-runner" in (pkg / "README.md").read_text()
