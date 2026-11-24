from pathlib import Path


class LocalAttachmentStorage:
    """Filesystem adapter shared by attachment retention and upload adapters."""

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
        if len(storage_key) != 32 or any(char not in "0123456789abcdef" for char in storage_key):
            raise ValueError("Invalid attachment storage key")
        target = (self._root / storage_key).resolve()
        if target.parent != self._root:
            raise ValueError("Attachment storage path escapes root")
        return target
