from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.list_events import AuditEventView
from app.shared.models import AuditEvent


class SqlAlchemyAuditEventReader:
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
