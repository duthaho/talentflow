from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Attachment:
    id: str
    tenant_id: str
    candidate_case_id: str
    document_type: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    created_by: str
    created_at: datetime


class AttachmentRepository(Protocol):
    def candidate_exists(self, *, candidate_case_id: str, tenant_id: str) -> bool: ...

    def add(self, attachment: Attachment) -> None: ...

    def list_for_candidate(self, *, candidate_case_id: str, tenant_id: str) -> list[Attachment]: ...

    def get(
        self, *, attachment_id: str, candidate_case_id: str, tenant_id: str
    ) -> Attachment | None: ...


class AttachmentStorage(Protocol):
    def save(self, *, storage_key: str, content: bytes) -> None: ...

    def open(self, *, storage_key: str) -> Path: ...

    def delete(self, *, storage_key: str) -> None: ...


class MalwareScanner(Protocol):
    def scan(self, content: bytes) -> None: ...


class AuditRecorder(Protocol):
    def record(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        aggregate_type: str,
        aggregate_id: str,
        correlation_id: str,
        metadata: dict[str, object],
    ) -> None: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
