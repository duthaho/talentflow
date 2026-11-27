"""Local-only demo sink, isolated on the Compose webhook-demo bridge.

This sink accepts requests for transport demos; real receivers must verify signatures
using app.modules.webhooks.application.signing.verify (ADR-008).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 <= size <= 256 * 1024:
            self.send_error(413)
            return
        self.rfile.read(size)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass  # The default includes the URL, which can contain credentials.


def main():
    ThreadingHTTPServer(("0.0.0.0", 8080), Receiver).serve_forever()


if __name__ == "__main__":
    main()
