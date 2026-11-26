from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.attachments.persistence import Attachment
from app.modules.audit.application.case_timeline import (
    CaseTimelineReader,
    TimelineEvent,
)
from app.modules.audit.application.list_events import AuditEventView
from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.persistence import CandidateCase


class SqlAlchemyAuditEventReader(CaseTimelineReader):
    def __init__(self, session: Session):
        self._session = session

    def list_for_tenant(self, *, tenant_id: str) -> list[AuditEventView]:
        events = self._session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc())
        ).all()
        return [
            AuditEventView(
                id=event.id,
                action=event.action,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                correlation_id=event.correlation_id,
            )
            for event in events
        ]

    def case_exists(self, *, tenant_id: str, candidate_case_id: str) -> bool:
        return (
            self._session.scalar(
                select(CandidateCase.id).where(
                    CandidateCase.id == candidate_case_id, CandidateCase.tenant_id == tenant_id
                )
            )
            is not None
        )

    def list_for_case(
        self,
        *,
        tenant_id: str,
        candidate_case_id: str,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> list[TimelineEvent]:
        attachment_ids = select(Attachment.id).where(
            Attachment.candidate_case_id == candidate_case_id, Attachment.tenant_id == tenant_id
        )
        scope = or_(
            and_(
                AuditEvent.aggregate_type == "candidate_case",
                AuditEvent.aggregate_id == candidate_case_id,
            ),
            and_(
                AuditEvent.aggregate_type == "candidate_attachment",
                AuditEvent.aggregate_id.in_(attachment_ids),
            ),
        )
        filters = [AuditEvent.tenant_id == tenant_id, scope]
        if after:
            timestamp, event_id = after
            filters.append(
                or_(
                    AuditEvent.created_at < timestamp,
                    and_(AuditEvent.created_at == timestamp, AuditEvent.id < event_id),
                )
            )
        events = self._session.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        ).all()
        return [
            TimelineEvent(
                id=e.id,
                action=e.action,
                aggregate_type=e.aggregate_type,
                aggregate_id=e.aggregate_id,
                actor_id=e.actor_id,
                occurred_at=e.created_at.replace(tzinfo=UTC)
                if e.created_at.tzinfo is None
                else e.created_at,
                metadata=e.metadata_json,
            )
            for e in events
        ]
