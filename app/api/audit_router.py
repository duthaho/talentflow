from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.schemas import AuditEventResponse, CaseAuditEventItem, CaseAuditEventPage
from app.modules.audit.application.case_timeline import (
    CandidateNotFoundError,
    CaseTimelineHandler,
    InvalidCursorError,
)
from app.modules.audit.application.list_events import ListAuditEventsHandler
from app.modules.audit.infrastructure.sqlalchemy_reader import SqlAlchemyAuditEventReader
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
    try:
        page = CaseTimelineHandler(SqlAlchemyAuditEventReader(session)).handle(
            tenant_id=actor.tenant_id,
            candidate_case_id=candidate_case_id,
            cursor=cursor,
            limit=limit,
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate case not found"
        ) from error
    except InvalidCursorError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor"
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return CaseAuditEventPage(
        items=[CaseAuditEventItem(**event.__dict__) for event in page.items],
        next_cursor=page.next_cursor,
    )
