"""Example: serve GET /hello and /healthz until Ctrl-C."""
from http.server import BaseHTTPRequestHandler

import http_runner


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/hello":
            self.send_error(404)
            return
        body = b"hello\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    http_runner.run(Handler, port=8080)


if __name__ == "__main__":
    main()
