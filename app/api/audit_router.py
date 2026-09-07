from fastapi import APIRouter, Depends

from app.api.schemas import AuditEventResponse
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
