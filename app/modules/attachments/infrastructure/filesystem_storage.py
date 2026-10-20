from pathlib import Path

from app.modules.attachments.application.attachment_service import (
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.modules.attachments.application.ports import MalwareScanner


class LocalAttachmentStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def save(self, *, storage_key: str, content: bytes) -> None:
        target = self._path(storage_key)
        temporary = target.with_suffix(".tmp")
        with temporary.open("xb") as stream:
            stream.write(content)
        temporary.chmod(0o600)
        temporary.replace(target)

    def open(self, *, storage_key: str) -> Path:
        target = self._path(storage_key)
        if not target.is_file():
            raise FileNotFoundError(storage_key)
        return target

    def delete(self, *, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)

    def _path(self, storage_key: str) -> Path:
        if len(storage_key) != 32 or any(
            character not in "0123456789abcdef" for character in storage_key
        ):
            raise ValueError("Invalid attachment storage key")
        target = (self._root / storage_key).resolve()
        if target.parent != self._root:
            raise ValueError("Attachment storage path escapes root")
        return target


class NoopMalwareScanner:
    def scan(self, content: bytes) -> None:
        del content


class ClamAvMalwareScanner:
    def __init__(self, command: str) -> None:
        self._command = command

    def scan(self, content: bytes) -> None:
        import subprocess

        try:
            result = subprocess.run(
                [self._command, "--no-summary", "--stdin"],
                input=content,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise MalwareScannerUnavailableError(
                "Attachment malware scanner is unavailable"
            ) from error
        if result.returncode == 1:
            raise MalwareScanRejectedError("Attachment malware scan rejected the file")
        if result.returncode != 0:
            raise MalwareScannerUnavailableError("Attachment malware scanner is unavailable")


def build_scanner(*, mode: str, command: str) -> MalwareScanner:
    if mode == "clamav":
        return ClamAvMalwareScanner(command)
    return NoopMalwareScanner()
