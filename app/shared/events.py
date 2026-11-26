"""Transactional event writing shared by persistence adapters (ADR 006)."""

from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry.propagate import inject
from sqlalchemy.orm import Session

from app.modules.notifications.persistence import OutboxEvent

CONTEXTS = {
    "candidate_case": "candidates",
    "interview": "interviews",
    "offer": "offers",
    "attachment": "attachments",
}


def record_event(
    session: Session,
    *,
    topic: str,
    tenant_id: str,
    subject: str,
    data: dict,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> OutboxEvent:
    request = session.info.get("event_request")
    if request is not None:
        correlation_id = correlation_id or getattr(request.state, "correlation_id", None)
        actor_id = actor_id or getattr(request.state, "actor_id", None)
    event_id = str(uuid4())
    correlation_id = correlation_id or event_id
    carrier = {}
    inject(carrier)
    event = OutboxEvent(
        id=event_id,
        tenant_id=tenant_id,
        topic=topic,
        subject=subject,
        payload_json=data,
        occurred_at=datetime.now(UTC),
        correlation_id=correlation_id,
        causation_id=correlation_id,
        actor_id=actor_id,
        traceparent=carrier.get("traceparent"),
    )
    session.add(event)
    return event


def envelope(event: OutboxEvent) -> dict:
    timestamp = event.occurred_at or event.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    result = {
        "specversion": "1.0",
        "id": event.id,
        "source": f"urn:talentflow:{CONTEXTS[event.topic.split('.')[0]]}",
        "type": event.topic,
        "time": timestamp.isoformat(),
        "datacontenttype": "application/json",
        "subject": event.subject or event.payload_json["offer_id"],
        "tenantid": event.tenant_id,
        "correlationid": event.correlation_id or event.id,
        "causationid": event.causation_id or event.id,
        "data": event.payload_json,
    }
    for name, value in (("actorid", event.actor_id), ("traceparent", event.traceparent)):
        if value:
            result[name] = value
    return result
