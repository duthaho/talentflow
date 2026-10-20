from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.attachments.application.ports import Attachment
from app.shared.models import Attachment as AttachmentRecord
from app.shared.models import AuditEvent, CandidateCase


class SqlAlchemyAttachmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def candidate_exists(self, *, candidate_case_id: str, tenant_id: str) -> bool:
        return (
            self._session.scalar(
                select(CandidateCase.id).where(
                    CandidateCase.id == candidate_case_id,
                    CandidateCase.tenant_id == tenant_id,
                )
            )
            is not None
        )

    def add(self, attachment: Attachment) -> None:
        self._session.add(
            AttachmentRecord(
                id=attachment.id,
                tenant_id=attachment.tenant_id,
                candidate_case_id=attachment.candidate_case_id,
                document_type=attachment.document_type,
                original_filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                sha256=attachment.sha256,
                storage_key=attachment.storage_key,
                created_by=attachment.created_by,
                created_at=attachment.created_at,
            )
        )

    def list_for_candidate(self, *, candidate_case_id: str, tenant_id: str) -> list[Attachment]:
        rows = self._session.scalars(
            select(AttachmentRecord)
            .where(
                AttachmentRecord.candidate_case_id == candidate_case_id,
                AttachmentRecord.tenant_id == tenant_id,
            )
            .order_by(AttachmentRecord.created_at.desc(), AttachmentRecord.id.desc())
        )
        return [_to_entity(row) for row in rows]

    def get(
        self, *, attachment_id: str, candidate_case_id: str, tenant_id: str
    ) -> Attachment | None:
        row = self._session.scalar(
            select(AttachmentRecord).where(
                AttachmentRecord.id == attachment_id,
                AttachmentRecord.candidate_case_id == candidate_case_id,
                AttachmentRecord.tenant_id == tenant_id,
            )
        )
        return _to_entity(row) if row else None


class SqlAlchemyAuditRecorder:
    def __init__(self, session: Session) -> None:
        self._session = session

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
    ) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                correlation_id=correlation_id,
                metadata_json=metadata,
            )
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


def _to_entity(row: AttachmentRecord) -> Attachment:
    return Attachment(
        id=row.id,
        tenant_id=row.tenant_id,
        candidate_case_id=row.candidate_case_id,
        document_type=row.document_type,
        filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        storage_key=row.storage_key,
        created_by=row.created_by,
        created_at=_utc(row.created_at),
    )


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)
