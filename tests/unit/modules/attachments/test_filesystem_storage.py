import pytest

from app.modules.attachments.application.attachment_service import MalwareScannerUnavailableError
from app.modules.attachments.infrastructure.filesystem_storage import ClamAvMalwareScanner


def test_clamav_scanner_fails_closed_when_command_is_unavailable() -> None:
    scanner = ClamAvMalwareScanner("definitely-not-an-installed-clamav-command")

    with pytest.raises(MalwareScannerUnavailableError):
        scanner.scan(b"%PDF-1.7\nresume")
