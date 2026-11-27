"""Commit inbox + fanout before ack; no HTTP or outbox reads here."""

import copy
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.modules.notifications.persistence import InboxMessage
from app.modules.webhooks.application.contracts import EVENT_TYPES
from app.modules.webhooks.infrastructure.models import Delivery, Endpoint, Event, Subscription


class PoisonMessage(ValueError):
    pass


def decode_event(body):
    try:
        if len(body) > 256 * 1024:
            raise ValueError
        event = json.loads(body)
        for field in ("id", "subject", "tenantid"):
            UUID(event[field])
        for field in ("correlationid", "causationid"):
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", event[field]):
                raise ValueError
        typ = event["type"]
        if (
            typ not in EVENT_TYPES
            or event["specversion"] != "1.0"
            or event["datacontenttype"] != "application/json"
        ):
            raise ValueError
        context = {"candidate_case": "candidates", "interview": "interviews", "offer": "offers"}[
            typ.split(".")[0]
        ]
        if (
            event["source"] != "urn:talentflow:" + context
            or datetime.fromisoformat(event["time"]).tzinfo is None
        ):
            raise ValueError
        if not isinstance(event["data"], dict):
            raise ValueError
        return event
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise PoisonMessage("invalid_event") from None


class WebhookConsumer:
    name = "webhooks"

    def __init__(self, sessions, broker):
        self.sessions, self.broker = sessions, broker

    def apply(self, event):
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            claimed = session.scalar(
                insert(InboxMessage)
                .values(
                    consumer=self.name,
                    event_id=event["id"],
                    tenant_id=event["tenantid"],
                    event_type=event["type"],
                    processed_at=now,
                )
                .on_conflict_do_nothing()
                .returning(InboxMessage.event_id)
            )
            if claimed is None:
                return False
            session.execute(
                insert(Event)
                .values(
                    tenant_id=event["tenantid"],
                    event_id=event["id"],
                    event_type=event["type"],
                    body=event,
                    occurred_at=datetime.fromisoformat(event["time"]),
                    received_at=now,
                )
                .on_conflict_do_nothing()
            )
            # Lock endpoint before delivery inserts, the same order as disable/delete.
            endpoints = session.scalars(
                select(Endpoint)
                .where(
                    Endpoint.tenant_id == event["tenantid"],
                    Endpoint.status == "enabled",
                    Endpoint.id.in_(
                        select(Subscription.endpoint_id).where(
                            Subscription.tenant_id == event["tenantid"],
                            Subscription.event_type == event["type"],
                        )
                    ),
                )
                .order_by(Endpoint.id)
                .with_for_update()
            )
            for endpoint in endpoints:
                session.execute(
                    insert(Delivery)
                    .values(
                        id=str(uuid4()),
                        tenant_id=event["tenantid"],
                        endpoint_id=endpoint.id,
                        event_id=event["id"],
                        event_type=event["type"],
                        status="pending",
                        kind="fanout",
                        attempt_count=0,
                        created_at=now,
                        next_attempt_at=now,
                    )
                    .on_conflict_do_nothing()
                )
            return True

    def drain(self, *, limit=10, should_stop=lambda: False):
        for _ in range(limit):
            if should_stop():
                break
            method, properties, body = self.broker.get()
            if method is None:
                break
            try:
                self.apply(decode_event(body))
            except Exception as error:
                try:
                    self.failed(body, properties, error)
                except Exception:
                    self.broker.requeue(method.delivery_tag)
                    raise RuntimeError("webhook_consumer_republish_failed") from None
            self.broker.ack(method.delivery_tag)
        with self.sessions.begin() as session:
            session.execute(
                delete(InboxMessage).where(
                    InboxMessage.consumer == self.name,
                    InboxMessage.processed_at < datetime.now(UTC) - timedelta(days=30),
                )
            )
        return self.broker.depths()["webhooks.events"]

    def failed(self, body, properties, error):
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
            exchange, key = "talentflow.retry", f"webhooks.retry.{attempt + 1}"
        else:
            headers["x-tf-failure"] = outcome
            headers["x-tf-error"] = type(error).__name__
            exchange, key = "talentflow.dead-letter", "webhooks"
        properties.headers, properties.delivery_mode = headers, 2
        self.broker.publish(exchange, key, body, properties)
