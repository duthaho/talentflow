from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, or_, select

from app.api.schemas import AuditEventResponse, CaseAuditEventItem, CaseAuditEventPage
from app.modules.attachments.persistence import Attachment
from app.modules.audit.application.case_timeline import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    redact,
)
from app.modules.audit.application.list_events import ListAuditEventsHandler
from app.modules.audit.infrastructure.sqlalchemy_reader import SqlAlchemyAuditEventReader
from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.persistence import CandidateCase
from app.modules.identity.security import ActorContext, require
from app.shared.database import SessionDep

router = APIRouter(tags=["audit"])


@router.get("/v1/audit-events", response_model=list[AuditEventResponse])
def list_audit_events(
    session: SessionDep,
    actor: ActorContext = Depends(require("audit:read")),
) -> list[AuditEventResponse]:
    events = ListAuditEventsHandler(SqlAlchemyAuditEventReader(session)).handle(
        tenant_id=actor.tenant_id
    )
    return [AuditEventResponse(**event.__dict__) for event in events]


@router.get(
    "/v1/candidate-cases/{candidate_case_id}/audit-events", response_model=CaseAuditEventPage
)
def list_case_audit_events(
    candidate_case_id: str,
    response: Response,
    session: SessionDep,
    actor: ActorContext = Depends(require("audit:read")),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CaseAuditEventPage:
    candidate = session.scalar(
        select(CandidateCase.id).where(
            CandidateCase.id == candidate_case_id, CandidateCase.tenant_id == actor.tenant_id
        )
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        )
    after = None
    if cursor:
        try:
            after = decode_cursor(cursor)
        except InvalidCursorError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor"
            ) from error
    attachment_ids = select(Attachment.id).where(
        Attachment.candidate_case_id == candidate_case_id, Attachment.tenant_id == actor.tenant_id
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
    filters = [AuditEvent.tenant_id == actor.tenant_id, scope]
    if after:
        timestamp, event_id = after
        filters.append(
            or_(
                AuditEvent.created_at < timestamp,
                and_(AuditEvent.created_at == timestamp, AuditEvent.id < event_id),
            )
        )
    events = session.scalars(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit + 1)
    ).all()
    page = events[:limit]
    response.headers["Cache-Control"] = "private, no-store"
    return CaseAuditEventPage(
        items=[
            CaseAuditEventItem(
                id=event.id,
                action=event.action,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                actor_id=event.actor_id,
                occurred_at=event.created_at.replace(tzinfo=UTC)
                if event.created_at.tzinfo is None
                else event.created_at,
                metadata=redact(event.action, event.metadata_json),
            )
            for event in page
        ],
        next_cursor=encode_cursor(page[-1].created_at, page[-1].id)
        if len(events) > limit and page
        else None,
    )
