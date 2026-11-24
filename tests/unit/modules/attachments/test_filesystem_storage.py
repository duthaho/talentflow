import socket

import pytest

from app.modules.attachments.application.attachment_service import (
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.modules.attachments.infrastructure.filesystem_storage import (
    ClamAvMalwareScanner,
    ClamdMalwareScanner,
)


def test_clamav_scanner_fails_closed_when_command_is_unavailable() -> None:
    scanner = ClamAvMalwareScanner("definitely-not-an-installed-clamav-command")

    with pytest.raises(MalwareScannerUnavailableError):
        scanner.scan(b"%PDF-1.7\nresume")


class FakeClamdConnection:
    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses)
        self.sent = b""

    def __enter__(self) -> "FakeClamdConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def sendall(self, content: bytes) -> None:
        self.sent += content

    def recv(self, _: int) -> bytes:
        return self.responses.pop(0) if self.responses else b""


def test_clamd_scanner_accepts_chunked_ok_response(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeClamdConnection(b"stream: O", b"K\0")
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: connection)

    ClamdMalwareScanner(host="clamav", port=3310).scan(b"resume")

    assert connection.sent == b"zINSTREAM\0\x00\x00\x00\x06resume\x00\x00\x00\x00"


def test_clamd_scanner_rejects_malware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: FakeClamdConnection(b"stream: Eicar FOUND\0"),
    )

    with pytest.raises(MalwareScanRejectedError):
        ClamdMalwareScanner(host="clamav", port=3310).scan(b"resume")


@pytest.mark.parametrize("response", [(), (b"garbage\0",)])
def test_clamd_scanner_fails_closed_when_unavailable(
    monkeypatch: pytest.MonkeyPatch, response: tuple[bytes, ...]
) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: FakeClamdConnection(*response),
    )

    with pytest.raises(MalwareScannerUnavailableError):
        ClamdMalwareScanner(host="clamav", port=3310).scan(b"resume")
