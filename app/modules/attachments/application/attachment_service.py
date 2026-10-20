from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePath
from uuid import uuid4

from app.modules.attachments.application.ports import (
    Attachment,
    AttachmentRepository,
    AttachmentStorage,
    AuditRecorder,
    MalwareScanner,
    UnitOfWork,
)

ALLOWED_DOCUMENT_TYPES = frozenset({"resume", "cover_letter", "portfolio", "other"})
ALLOWED_CONTENT_TYPES = frozenset(
    {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
)


class CandidateNotFoundError(Exception):
    pass


class AttachmentNotFoundError(Exception):
    pass


class InvalidAttachmentError(ValueError):
    pass


class AttachmentTooLargeError(ValueError):
    pass


class MalwareScanRejectedError(ValueError):
    pass


class MalwareScannerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadAttachmentCommand:
    tenant_id: str
    candidate_case_id: str
    document_type: str
    filename: str
    content_type: str
    content: bytes
    actor_id: str
    correlation_id: str


class AttachmentService:
    def __init__(
        self,
        *,
        repository: AttachmentRepository,
        storage: AttachmentStorage,
        scanner: MalwareScanner,
        audit: AuditRecorder,
        unit_of_work: UnitOfWork,
        max_bytes: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._scanner = scanner
        self._audit = audit
        self._unit_of_work = unit_of_work
        self._max_bytes = max_bytes

    def upload(self, command: UploadAttachmentCommand) -> Attachment:
        if not self._repository.candidate_exists(
            candidate_case_id=command.candidate_case_id, tenant_id=command.tenant_id
        ):
            raise CandidateNotFoundError(command.candidate_case_id)
        filename = _validate(command, max_bytes=self._max_bytes)
        self._scanner.scan(command.content)
        attachment = Attachment(
            id=str(uuid4()),
            tenant_id=command.tenant_id,
            candidate_case_id=command.candidate_case_id,
            document_type=command.document_type,
            filename=filename,
            content_type=command.content_type,
            size_bytes=len(command.content),
            sha256=sha256(command.content).hexdigest(),
            storage_key=uuid4().hex,
            created_by=command.actor_id,
            created_at=datetime.now(UTC),
        )
        self._storage.save(storage_key=attachment.storage_key, content=command.content)
        try:
            self._repository.add(attachment)
            self._audit.record(
                tenant_id=command.tenant_id,
                actor_id=command.actor_id,
                action="candidate_attachment.uploaded",
                aggregate_type="candidate_attachment",
                aggregate_id=attachment.id,
                correlation_id=command.correlation_id,
                metadata={
                    "candidate_case_id": command.candidate_case_id,
                    "document_type": attachment.document_type,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                    "sha256": attachment.sha256,
                },
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            self._storage.delete(storage_key=attachment.storage_key)
            raise
        return attachment

    def list(self, *, candidate_case_id: str, tenant_id: str) -> list[Attachment]:
        if not self._repository.candidate_exists(
            candidate_case_id=candidate_case_id, tenant_id=tenant_id
        ):
            raise CandidateNotFoundError(candidate_case_id)
        return self._repository.list_for_candidate(
            candidate_case_id=candidate_case_id, tenant_id=tenant_id
        )

    def download(
        self,
        *,
        attachment_id: str,
        candidate_case_id: str,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[Attachment, Path]:
        attachment = self._repository.get(
            attachment_id=attachment_id,
            candidate_case_id=candidate_case_id,
            tenant_id=tenant_id,
        )
        if attachment is None:
            raise AttachmentNotFoundError(attachment_id)
        content = self._storage.open(storage_key=attachment.storage_key)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="candidate_attachment.downloaded",
            aggregate_type="candidate_attachment",
            aggregate_id=attachment.id,
            correlation_id=correlation_id,
            metadata={"candidate_case_id": candidate_case_id, "sha256": attachment.sha256},
        )
        self._unit_of_work.commit()
        return attachment, content


def _validate(command: UploadAttachmentCommand, *, max_bytes: int) -> str:
    filename = PurePath(command.filename).name.strip()
    if (
        not filename
        or filename != command.filename
        or len(filename) > 255
        or any(ord(character) < 32 for character in filename)
    ):
        raise InvalidAttachmentError("Attachment filename is invalid")
    if command.document_type not in ALLOWED_DOCUMENT_TYPES:
        raise InvalidAttachmentError("Attachment document type is invalid")
    if not command.content or len(command.content) > max_bytes:
        raise AttachmentTooLargeError(f"Attachment must be between 1 and {max_bytes} bytes")
    if command.content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidAttachmentError("Attachment content type is not allowed")
    if command.content_type == "application/pdf":
        if not filename.lower().endswith(".pdf") or not command.content.startswith(b"%PDF-"):
            raise InvalidAttachmentError("Attachment content does not match PDF type")
    elif not filename.lower().endswith(".docx") or not command.content.startswith(b"PK\x03\x04"):
        raise InvalidAttachmentError("Attachment content does not match DOCX type")
    return filename
