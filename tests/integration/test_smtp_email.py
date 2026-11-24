import socketserver
import threading
from email import message_from_bytes

from app.modules.notifications.infrastructure.smtp_email import SmtpEmailAdapter


class _SmtpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 test SMTP server\r\n")
        self.wfile.flush()
        while command := self.rfile.readline().rstrip(b"\r\n"):
            verb = command.split(maxsplit=1)[0].upper()
            if verb in {b"EHLO", b"HELO"}:
                self.wfile.write(b"250-test SMTP server\r\n250 OK\r\n")
            elif verb in {b"MAIL", b"RCPT"}:
                self.wfile.write(b"250 OK\r\n")
            elif verb == b"DATA":
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                self.wfile.flush()
                data = bytearray()
                while line := self.rfile.readline():
                    if line == b".\r\n":
                        break
                    data.extend(line)
                self.server.messages.append(bytes(data))  # type: ignore[attr-defined]
                self.wfile.write(b"250 Queued\r\n")
            elif verb == b"QUIT":
                self.wfile.write(b"221 Bye\r\n")
                self.wfile.flush()
                return
            else:
                self.wfile.write(b"502 Unsupported command\r\n")
            self.wfile.flush()


class _SmtpTestServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmtpHandler)
        self.messages: list[bytes] = []


def test_smtp_adapter_delivers_a_mapped_message_to_an_smtp_server() -> None:
    server = _SmtpTestServer()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        SmtpEmailAdapter(host=host, port=port, sender="notifications@example.test").send(
            recipient="manager@example.test",
            subject="Offer approved",
            text="The offer was approved.",
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    message = message_from_bytes(server.messages[0])
    assert message["From"] == "notifications@example.test"
    assert message["To"] == "manager@example.test"
    assert message["Subject"] == "Offer approved"
    assert message.get_payload(decode=True).decode().strip() == "The offer was approved."
