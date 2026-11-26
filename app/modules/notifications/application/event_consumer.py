"""Manual-ack consumer: inbox and delivery row commit together before broker ack."""

import copy
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.modules.notifications.persistence import InboxMessage, NotificationDelivery, OutboxEvent
from app.shared.observability import broker_depth, consumer_outcomes


class PoisonMessage(ValueError):
    pass


def decode_event(body: bytes) -> dict:
    try:
        event = json.loads(body)
        if not isinstance(event, dict):
            raise ValueError
        for name in ("id", "tenantid", "subject"):
            UUID(event[name])
        for name in ("correlationid", "causationid"):
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", event[name]):
                raise ValueError
        if (
            event["specversion"] != "1.0"
            or event["datacontenttype"] != "application/json"
            or event["type"] != "offer.approval_recorded.v1"
            or event["source"] != "urn:talentflow:offers"
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(event["time"])
        if timestamp.tzinfo is None:
            raise ValueError
        data = event["data"]
        UUID(data["offer_id"])
        if event["subject"] != data["offer_id"]:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", data["actor_id"]):
            raise ValueError
        if not isinstance(data["decision"], str):
            raise ValueError
        return event
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError):
        raise PoisonMessage("invalid_event") from None


class NotificationConsumer:
    name = "notifications"

    def __init__(self, sessions, broker):
        self.sessions = sessions
        self.broker = broker

    def apply(self, event: dict) -> bool:
        with self.sessions.begin() as session:
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            claimed = session.execute(
                insert(InboxMessage)
                .values(
                    consumer=self.name,
                    event_id=event["id"],
                    event_type=event["type"],
                    tenant_id=event["tenantid"],
                    processed_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["consumer", "event_id"])
                .returning(InboxMessage.event_id)
            ).scalar_one_or_none()
            if claimed is None:
                return False
            # Tolerant reader: a future decision is consumed without a delivery.
            if event["data"]["decision"] not in {"approved", "rejected"}:
                consumer_outcomes.labels(self.name, "skipped_enum").inc()
                return True
            # Do not trust a tenant supplied by a malformed/misrouted message.
            original = session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.id == event["id"],
                    OutboxEvent.tenant_id == event["tenantid"],
                    OutboxEvent.topic == event["type"],
                )
            )
            if original is None or any(
                original.payload_json.get(key) != event["data"][key]
                for key in ("offer_id", "decision", "actor_id")
            ):
                raise PoisonMessage("event_identity_mismatch")
            # Existing delivery rows (pre-inbox rollout) remain the business dedup key.
            if (
                session.scalar(
                    select(NotificationDelivery.id).where(
                        NotificationDelivery.outbox_event_id == event["id"]
                    )
                )
                is None
            ):
                session.add(
                    NotificationDelivery(
                        outbox_event_id=event["id"],
                        tenant_id=event["tenantid"],
                        recipient_id=event["data"]["actor_id"],
                        payload_json=event["data"],
                    )
                )
            return True

    def drain(self, *, limit: int = 10, should_stop=lambda: False) -> int:
        for _ in range(limit):
            if should_stop():
                break
            method, properties, body = self.broker.get()
            if method is None:
                break
            try:
                event = decode_event(body)
                applied = self.apply(event)
            except Exception as error:
                try:
                    self._failed(body, properties, error)
                except Exception:
                    self.broker.requeue(method.delivery_tag)
                    raise RuntimeError("consumer_republish_failed") from None
            else:
                consumer_outcomes.labels(self.name, "applied" if applied else "duplicate").inc()
            self.broker.ack(method.delivery_tag)
        depths = self.broker.depths()
        for queue, depth in depths.items():
            broker_depth.labels(queue).set(depth)
        # Inbox retention never prunes outbox rows while deliveries reference them.
        with self.sessions.begin() as session:
            session.execute(
                delete(InboxMessage).where(
                    InboxMessage.processed_at < datetime.now(UTC) - timedelta(days=30)
                )
            )
        return depths[f"{self.name}.events"]

    def _failed(self, body, properties, error) -> None:
        properties = copy.copy(properties)
        headers = dict(properties.headers or {})
        attempt = headers.get("x-tf-attempt", 0)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            error = PoisonMessage("invalid_attempt")
        if isinstance(error, PoisonMessage):
            outcome = "poison"
        elif attempt >= 3:
            outcome = "exhausted"
        else:
            outcome = "retry"
        if outcome == "retry":
            headers["x-tf-attempt"] = attempt + 1
            exchange, key = "talentflow.retry", f"{self.name}.retry.{attempt + 1}"
        else:
            headers["x-tf-failure"] = outcome
            headers["x-tf-error"] = type(error).__name__
            exchange, key = "talentflow.dead-letter", self.name
        properties.headers = headers
        properties.delivery_mode = 2
        self.broker.publish(exchange, key, body, properties)
        consumer_outcomes.labels(self.name, outcome).inc()
