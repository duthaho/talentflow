"""Leased, fenced HTTP attempts, signed anew with the current DB key set."""

import asyncio
import json
import random
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from prometheus_client import Counter
from sqlalchemy import func, or_, select

from app.modules.webhooks.application.signing import aad, signature
from app.modules.webhooks.infrastructure.management import audit, aware, cancel_pending
from app.modules.webhooks.infrastructure.models import Attempt, Delivery, Endpoint, Event, Secret

outcomes = Counter("talentflow_webhook_deliveries_total", "Webhook delivery outcomes", ["outcome"])
DELAYS = (0, 30, 120, 600, 3600, 10800, 21600, 43200)


def retry_seconds(value, now):
    if not value:
        return 0
    try:
        seconds = (
            int(value)
            if value.isascii() and value.isdigit()
            else (parsedate_to_datetime(value) - now).total_seconds()
        )
        return max(0, min(3600, seconds))
    except (ValueError, TypeError, OverflowError):
        return 0


class WebhookWorker:
    def __init__(
        self,
        sessions,
        sender,
        cipher,
        *,
        clock=lambda: datetime.now(UTC),
        jitter=lambda: random.uniform(0.8, 1.2),
    ):
        self.sessions, self.sender, self.cipher = sessions, sender, cipher
        self.clock, self.jitter = clock, jitter
        self.owned = {}

    def claim(self):
        now = self.clock()
        with self.sessions.begin() as session:
            # Endpoint lock serializes the per-endpoint in-flight count across replicas.
            endpoints = list(
                session.scalars(
                    select(Endpoint)
                    .where(
                        Endpoint.status == "enabled",
                        Endpoint.id.in_(
                            select(Delivery.endpoint_id).where(
                                Delivery.status == "pending",
                                Delivery.next_attempt_at <= now,
                                or_(Delivery.leased_until.is_(None), Delivery.leased_until <= now),
                            )
                        ),
                    )
                    .order_by(Endpoint.id)
                    .with_for_update(skip_locked=True)
                )
            )
            for endpoint in endpoints:
                active = session.scalar(
                    select(func.count())
                    .select_from(Delivery)
                    .where(
                        Delivery.tenant_id == endpoint.tenant_id,
                        Delivery.endpoint_id == endpoint.id,
                        Delivery.status == "pending",
                        Delivery.leased_until > now,
                    )
                )
                if active >= 4:
                    continue
                row = session.scalar(
                    select(Delivery)
                    .where(
                        Delivery.tenant_id == endpoint.tenant_id,
                        Delivery.endpoint_id == endpoint.id,
                        Delivery.status == "pending",
                        Delivery.next_attempt_at <= now,
                        or_(Delivery.leased_until.is_(None), Delivery.leased_until <= now),
                    )
                    .order_by(Delivery.next_attempt_at, Delivery.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    continue
                row.leased_until = now + timedelta(seconds=60)
                self.owned[row.id] = row.leased_until
                return row.id, row.tenant_id, row.endpoint_id, row.leased_until
        return None

    async def attempt(self, claim):
        try:
            return await self._attempt(claim)
        finally:
            self.owned.pop(claim[0], None)

    async def _attempt(self, claim):
        ident, tenant_id, endpoint_id, lease = claim
        started = self.clock()
        with self.sessions() as session:
            endpoint = session.scalar(
                select(Endpoint).where(Endpoint.tenant_id == tenant_id, Endpoint.id == endpoint_id)
            )
            delivery = session.scalar(
                select(Delivery).where(Delivery.tenant_id == tenant_id, Delivery.id == ident)
            )
            if (
                endpoint.status != "enabled"
                or delivery.status != "pending"
                or aware(delivery.leased_until) != lease
            ):
                return False
            event = session.get(Event, (tenant_id, delivery.event_id))
            body = json.dumps(event.body, separators=(",", ":"), ensure_ascii=False).encode()
            keys = list(
                session.scalars(
                    select(Secret)
                    .where(
                        Secret.tenant_id == tenant_id,
                        Secret.endpoint_id == endpoint_id,
                        or_(
                            Secret.status == "current",
                            (Secret.status == "previous") & (Secret.expires_at > started),
                        ),
                    )
                    .order_by(Secret.status)
                )
            )
            # 'current' sorts before 'previous'. No key-cache authority or queued URL snapshot.
            timestamp = str(int(started.timestamp()))
            signatures = [
                signature(
                    self.cipher.decrypt(k.ciphertext, aad(tenant_id, endpoint_id, k.id)),
                    delivery.event_id,
                    timestamp,
                    body,
                )
                for k in keys
            ]
            if not signatures:
                raise RuntimeError("webhook_signing_key_unavailable")
            headers = {
                "Content-Type": "application/cloudevents+json; charset=utf-8",
                "User-Agent": "TalentFlow-Webhooks/1",
                "webhook-id": delivery.event_id,
                "webhook-timestamp": timestamp,
                "webhook-signature": " ".join(signatures),
            }
            secret_ids = " ".join(k.id for k in keys)
            url = endpoint.url
        start = time.monotonic()
        result = await self.sender.send(url, headers, body)
        duration = int((time.monotonic() - start) * 1000)
        now = self.clock()
        with self.sessions.begin() as session:
            # Lock ordering is endpoint -> delivery everywhere, including admin cancellation.
            endpoint = session.scalar(
                select(Endpoint)
                .where(Endpoint.tenant_id == tenant_id, Endpoint.id == endpoint_id)
                .with_for_update()
            )
            row = session.scalar(
                select(Delivery)
                .where(Delivery.tenant_id == tenant_id, Delivery.id == ident)
                .with_for_update()
            )
            if aware(row.leased_until) != lease or row.status != "pending":
                return False  # cancelled/reclaimed while HTTP was in flight
            row.attempt_count += 1
            row.last_attempt_at, row.last_status_code, row.last_error_code = (
                started,
                result.status_code,
                result.error_code,
            )
            row.leased_until = None
            session.add(
                Attempt(
                    tenant_id=tenant_id,
                    delivery_id=ident,
                    attempt_number=row.attempt_count,
                    started_at=started,
                    duration_ms=duration,
                    status_code=result.status_code,
                    error_code=result.error_code,
                    signed_secret_ids=secret_ids,
                )
            )
            success = (
                result.status_code is not None
                and 200 <= result.status_code < 300
                and result.error_code is None
            )
            if success:
                row.status = "succeeded"
                endpoint.consecutive_failures, endpoint.failure_streak_started_at = 0, None
            else:
                endpoint.consecutive_failures += 1
                if endpoint.failure_streak_started_at is None:
                    endpoint.failure_streak_started_at = now
                if result.status_code == 410 or row.attempt_count >= 8:
                    row.status = "dead_lettered"
                disable = (
                    "gone"
                    if result.status_code == 410
                    else (
                        "failing"
                        if endpoint.consecutive_failures >= 20
                        and (now - aware(endpoint.failure_streak_started_at)).total_seconds()
                        > 72 * 3600
                        else None
                    )
                )
                if disable:
                    endpoint.status, endpoint.disabled_reason = "disabled", disable
                    endpoint.version += 1
                    endpoint.updated_at = now
                    # Flush this attempt's terminal state before bulk cancelling others.
                    session.flush()
                    cancel_pending(session, endpoint, now)
                    audit(session, endpoint, "system", "auto_disabled", row.event_id)
                if row.status == "pending" and not disable:
                    delay = DELAYS[row.attempt_count] * self.jitter()
                    if result.status_code in (429, 503):
                        delay = max(delay, retry_seconds(result.retry_after, now))
                    row.next_attempt_at = now + timedelta(seconds=delay)
                elif disable and row.status == "pending":
                    row.status = "cancelled"
            if row.status != "pending":
                row.completed_at, row.next_attempt_at = now, None
            outcomes.labels(row.status).inc()
        self.owned.pop(ident, None)
        return success

    def deliver_pending(self, *, should_stop=lambda: False, limit=100):
        delivered = 0
        for _ in range(limit):
            if should_stop():
                break
            claim = self.claim()
            if claim is None:
                break
            delivered += asyncio.run(self.attempt(claim))
        return delivered

    def release_leases(self):
        with self.sessions.begin() as session:
            for ident, lease in self.owned.items():
                row = session.get(Delivery, ident)
                if row and aware(row.leased_until) == lease:
                    row.leased_until = None
        self.owned.clear()

    def pending_count(self):
        with self.sessions() as session:
            return session.scalar(
                select(func.count()).select_from(Delivery).where(Delivery.status == "pending")
            )
