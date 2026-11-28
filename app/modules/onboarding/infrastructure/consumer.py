"""Transactional inbox with tenant/case revalidation and start/erase serialization."""

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete

from app.modules.feature_flags.application.flags import ONBOARDING_SAGA, Context
from app.modules.notifications.application.event_consumer import NotificationConsumer, PoisonMessage
from app.modules.notifications.persistence import InboxMessage
from app.modules.onboarding.infrastructure.repository import insert_for
from app.shared.observability import consumer_outcomes


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
            or event["type"] not in {"candidate_case.stage_changed.v1", "candidate_case.erased.v1"}
            or event["source"] != "urn:talentflow:candidates"
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(event["time"])
        if timestamp.tzinfo is None:
            raise ValueError
        data = event["data"]
        if not isinstance(data, dict) or data.get("candidate_case_id") != event["subject"]:
            raise ValueError
        if event.get("actorid") is not None and not re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}", event["actorid"]
        ):
            raise ValueError
        return event
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError):
        raise PoisonMessage("invalid_event") from None


class OnboardingConsumer(NotificationConsumer):
    name = "onboarding"

    def __init__(self, sessions, broker, repository, flags, clock=lambda: datetime.now(UTC)):
        super().__init__(sessions, broker)
        self.repository, self.flags, self.clock = repository, flags, clock

    def apply(self, event):
        now = self.clock()
        with self.sessions.begin() as session:
            claimed = session.scalar(
                insert_for(session)(InboxMessage)
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
                return "duplicate"
            enabled = (
                self.flags.is_enabled(ONBOARDING_SAGA, Context(event["tenantid"]))
                if event["type"] == "candidate_case.stage_changed.v1"
                and event["data"].get("to_stage") == "hired"
                else False
            )
            outcome = self.repository.start(session, event, now, enabled)
        consumer_outcomes.labels(self.name, outcome).inc()
        return outcome

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
                    self._failed(body, properties, error)
                except Exception:
                    self.broker.requeue(method.delivery_tag)
                    raise RuntimeError("onboarding_republish_failed") from None
            self.broker.ack(method.delivery_tag)
        with self.sessions.begin() as session:
            session.execute(
                delete(InboxMessage).where(
                    InboxMessage.consumer == self.name,
                    InboxMessage.processed_at < self.clock() - timedelta(days=30),
                )
            )
        return self.broker.depths()[self.name + ".events"]
