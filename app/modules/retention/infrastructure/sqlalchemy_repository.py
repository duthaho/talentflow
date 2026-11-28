from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.modules.attachments.application.ports import AttachmentStorage
from app.modules.attachments.persistence import Attachment
from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.persistence import CandidateCase, CandidateConsent
from app.modules.retention.application.retention import LegalHoldView, RetentionPolicy
from app.modules.retention.persistence import CandidateLegalHold
from app.modules.retention.persistence import RetentionPolicy as RetentionPolicyRecord


class SqlAlchemyRetentionRepository:
    def __init__(self, session: Session, *, attachment_storage: AttachmentStorage) -> None:
        self._session = session
        self._storage = attachment_storage

    def get_policy(self, *, tenant_id: str) -> int | None:
        return self._session.scalar(
            select(RetentionPolicyRecord.retention_days).where(
                RetentionPolicyRecord.tenant_id == tenant_id
            )
        )

    def get_legal_hold(self, *, tenant_id: str, candidate_case_id: str) -> LegalHoldView:
        hold = self._session.scalar(
            select(CandidateLegalHold).where(
                CandidateLegalHold.candidate_case_id == candidate_case_id,
                CandidateLegalHold.tenant_id == tenant_id,
            )
        )
        if hold is None:
            return LegalHoldView(held=False, reason=None, placed_at=None, placed_by=None)
        placed_at = hold.created_at
        return LegalHoldView(
            held=True,
            reason=hold.reason,
            placed_by=hold.created_by,
            placed_at=placed_at.replace(tzinfo=UTC) if placed_at.tzinfo is None else placed_at,
        )

    def set_policy(self, *, tenant_id: str, retention_days: int) -> RetentionPolicy:
        record = self._session.get(RetentionPolicyRecord, tenant_id)
        if record is None:
            record = RetentionPolicyRecord(tenant_id=tenant_id, retention_days=retention_days)
            self._session.add(record)
        else:
            record.retention_days = retention_days
        return RetentionPolicy(tenant_id=tenant_id, retention_days=retention_days)

    def candidate_exists(self, *, tenant_id: str, candidate_case_id: str) -> bool:
        return (
            self._session.scalar(
                select(CandidateCase.id).where(
                    CandidateCase.id == candidate_case_id, CandidateCase.tenant_id == tenant_id
                )
            )
            is not None
        )

    def set_legal_hold(
        self,
        *,
        tenant_id: str,
        candidate_case_id: str,
        held: bool,
        reason: str | None,
        actor_id: str,
    ) -> None:
        record = self._session.get(CandidateLegalHold, candidate_case_id)
        if held:
            if record is None:
                self._session.add(
                    CandidateLegalHold(
                        candidate_case_id=candidate_case_id,
                        tenant_id=tenant_id,
                        reason=reason or "Legal hold",
                        created_by=actor_id,
                    )
                )
            else:
                record.reason = reason or record.reason
        elif record is not None and record.tenant_id == tenant_id:
            self._session.delete(record)

    def policy_tenant_ids(self, *, limit: int) -> list[str]:
        return list(
            self._session.scalars(
                select(RetentionPolicyRecord.tenant_id)
                .order_by(RetentionPolicyRecord.tenant_id)
                .limit(limit)
            )
        )

    def purge_due(self, *, tenant_id: str, now: datetime) -> list[str]:
        policy = self._session.get(RetentionPolicyRecord, tenant_id)
        if policy is None:
            return []
        hold_exists = exists().where(
            CandidateLegalHold.candidate_case_id == CandidateCase.id,
            CandidateLegalHold.tenant_id == tenant_id,
        )
        records = self._session.scalars(
            select(CandidateCase).where(
                CandidateCase.tenant_id == tenant_id,
                CandidateCase.stage.in_(("rejected", "withdrawn")),
                CandidateCase.anonymized_at.is_(None),
                CandidateCase.terminal_at <= now - timedelta(days=policy.retention_days),
                ~hold_exists,
            )
        ).all()
        for record in records:
            attachments = self._session.scalars(
                select(Attachment).where(
                    Attachment.candidate_case_id == record.id,
                    Attachment.tenant_id == tenant_id,
                )
            ).all()
            for attachment in attachments:
                self._storage.delete(storage_key=attachment.storage_key)
                self._session.delete(attachment)
            consent = self._session.get(CandidateConsent, record.id)
            if consent is not None:
                consent.text = None
            record.first_name = "Redacted"
            record.last_name = "Candidate"
            record.email = f"purged+{record.id}@redacted.invalid"
            record.anonymized_at = now
        return [record.id for record in records]


class SqlAlchemyAuditRecorder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, **kwargs: object) -> None:
        self._session.add(AuditEvent(metadata_json=kwargs.pop("metadata"), **kwargs))


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()
