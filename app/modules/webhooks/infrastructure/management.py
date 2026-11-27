"""Transactional admin persistence; all mutations serialize on a tenant or endpoint."""

import base64
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.modules.audit.persistence import AuditEvent
from app.modules.organization.persistence import Tenant
from app.modules.webhooks.application.contracts import WebhookError
from app.modules.webhooks.application.signing import aad
from app.modules.webhooks.infrastructure.models import (
    Attempt,
    Delivery,
    Endpoint,
    Secret,
    Subscription,
)
from app.shared.concurrency import resolve_expected_version


def timestamps(values):
    return {
        key: aware(value) if isinstance(value, datetime) else value for key, value in values.items()
    }


def now_utc():
    return datetime.now(UTC)


def aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def audit(session, endpoint, actor_id, action, correlation_id, *, secret_id=None):
    if secret_id is None:
        secret_id = session.scalar(
            select(Secret.id).where(
                Secret.tenant_id == endpoint.tenant_id,
                Secret.endpoint_id == endpoint.id,
                Secret.status == "current",
            )
        )
    types = list(
        session.scalars(
            select(Subscription.event_type).where(
                Subscription.tenant_id == endpoint.tenant_id,
                Subscription.endpoint_id == endpoint.id,
            )
        )
    )
    session.add(
        AuditEvent(
            tenant_id=endpoint.tenant_id,
            actor_id=actor_id,
            action="webhook." + action,
            aggregate_type="webhook_endpoint",
            aggregate_id=endpoint.id,
            correlation_id=correlation_id,
            metadata_json={
                "endpoint_id": endpoint.id,
                "host": urlsplit(endpoint.url).hostname,
                "event_types": types,
                "secret_id": secret_id,
            },
        )
    )


def cancel_pending(session, endpoint, now):
    session.execute(
        update(Delivery)
        .where(
            Delivery.tenant_id == endpoint.tenant_id,
            Delivery.endpoint_id == endpoint.id,
            Delivery.status == "pending",
        )
        .values(status="cancelled", completed_at=now, next_attempt_at=None, leased_until=None)
    )


class Management:
    def __init__(self, session, cipher, tenant_id, actor_id, correlation_id):
        self.session = session
        self.cipher = cipher
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.correlation_id = correlation_id

    def endpoint(self, endpoint_id, *, lock=False):
        query = select(Endpoint).where(
            Endpoint.tenant_id == self.tenant_id,
            Endpoint.id == endpoint_id,
            Endpoint.status != "deleted",
        )
        if lock:
            query = query.with_for_update()
        endpoint = self.session.scalar(query)
        if endpoint is None:
            raise WebhookError(404, "not-found", "Webhook endpoint not found")
        return endpoint

    def delivery(self, delivery_id):
        result = self.session.scalar(
            select(Delivery).where(Delivery.tenant_id == self.tenant_id, Delivery.id == delivery_id)
        )
        if result is None:
            raise WebhookError(404, "not-found", "Webhook delivery not found")
        return result

    def new_secret(self, endpoint, now):
        key = secrets.token_bytes(32)
        secret_id = str(uuid4())
        record = Secret(
            id=secret_id,
            tenant_id=self.tenant_id,
            endpoint_id=endpoint.id,
            status="current",
            created_at=now,
            key_id=self.cipher.active,
            ciphertext=self.cipher.encrypt(key, aad(self.tenant_id, endpoint.id, secret_id)),
        )
        self.session.add(record)
        self.session.flush()
        return {"id": secret_id, "value": "whsec_" + base64.b64encode(key).decode()}

    def subscriptions(self, endpoint, values, now):
        self.session.execute(
            delete(Subscription).where(
                Subscription.tenant_id == self.tenant_id, Subscription.endpoint_id == endpoint.id
            )
        )
        for event_type in values:
            self.session.add(
                Subscription(
                    tenant_id=self.tenant_id,
                    endpoint_id=endpoint.id,
                    event_type=event_type,
                    created_at=now,
                )
            )
        self.session.flush()

    def commit(self):
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise WebhookError(409, "conflict", "Webhook URL already registered") from None

    def create(self, data):
        # Serializes the limit check across competing creates in one tenant.
        self.session.scalar(select(Tenant).where(Tenant.id == self.tenant_id).with_for_update())
        count = self.session.scalar(
            select(func.count())
            .select_from(Endpoint)
            .where(Endpoint.tenant_id == self.tenant_id, Endpoint.status != "deleted")
        )
        if count >= 10:
            raise WebhookError(
                409, "webhook-endpoint-limit-reached", "A tenant may register at most 10 endpoints"
            )
        now = now_utc()
        endpoint = Endpoint(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            url=data["url"],
            description=data.get("description"),
            status="enabled" if data.get("enabled", True) else "disabled",
            disabled_reason=None if data.get("enabled", True) else "manual",
            created_by=self.actor_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(endpoint)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise WebhookError(409, "conflict", "Webhook URL already registered") from None
        self.subscriptions(endpoint, data["event_types"], now)
        secret = self.new_secret(endpoint, now)
        audit(
            self.session,
            endpoint,
            self.actor_id,
            "created",
            self.correlation_id,
            secret_id=secret["id"],
        )
        self.commit()
        return {**self.endpoint_view(endpoint), "secret": secret}

    def checked(self, endpoint_id, conditions):
        endpoint = self.endpoint(endpoint_id, lock=True)
        resolve_expected_version(
            current_version=endpoint.version, expected_version=None, if_match=conditions
        )
        return endpoint

    def patch(self, endpoint_id, data, conditions):
        # Take tenant lock before endpoint lock, also used by create's URL/limit checks.
        self.session.scalar(select(Tenant).where(Tenant.id == self.tenant_id).with_for_update())
        endpoint = self.checked(endpoint_id, conditions)
        now = now_utc()
        for field in ("url", "description"):
            if field in data:
                setattr(endpoint, field, data[field])
        if "event_types" in data:
            self.subscriptions(endpoint, data["event_types"], now)
        if "enabled" in data:
            endpoint.status = "enabled" if data["enabled"] else "disabled"
            endpoint.disabled_reason = None if data["enabled"] else "manual"
            if data["enabled"]:
                endpoint.consecutive_failures = 0
                endpoint.failure_streak_started_at = None
            else:
                cancel_pending(self.session, endpoint, now)
        endpoint.version += 1
        endpoint.updated_at = now
        audit(self.session, endpoint, self.actor_id, "updated", self.correlation_id)
        self.commit()
        return self.endpoint_view(endpoint)

    def rotate(self, endpoint_id, grace, conditions):
        endpoint = self.checked(endpoint_id, conditions)
        now = now_utc()
        previous = list(
            self.session.scalars(
                select(Secret).where(
                    Secret.tenant_id == self.tenant_id,
                    Secret.endpoint_id == endpoint.id,
                    Secret.status == "previous",
                )
            )
        )
        for secret in previous:
            secret.status, secret.ciphertext, secret.expires_at = "expired", None, now
        self.session.flush()
        current = self.session.scalar(
            select(Secret).where(
                Secret.tenant_id == self.tenant_id,
                Secret.endpoint_id == endpoint.id,
                Secret.status == "current",
            )
        )
        expires = now + timedelta(seconds=grace)
        current.expires_at = expires
        current.status = "previous" if grace else "expired"
        if not grace:
            current.ciphertext = None
        self.session.flush()
        secret = self.new_secret(endpoint, now)
        endpoint.version += 1
        endpoint.updated_at = now
        audit(
            self.session,
            endpoint,
            self.actor_id,
            "rotated",
            self.correlation_id,
            secret_id=secret["id"],
        )
        self.commit()
        return {
            "endpoint": self.endpoint_view(endpoint),
            "secret": secret,
            "previous_secret_expires_at": expires,
        }

    def delete(self, endpoint_id, conditions):
        endpoint = self.checked(endpoint_id, conditions)
        now = now_utc()
        audit(self.session, endpoint, self.actor_id, "deleted", self.correlation_id)
        endpoint.status, endpoint.disabled_reason = "deleted", None
        endpoint.deleted_at = endpoint.updated_at = now
        endpoint.version += 1
        self.session.execute(
            update(Secret)
            .where(Secret.tenant_id == self.tenant_id, Secret.endpoint_id == endpoint.id)
            .values(status="expired", ciphertext=None, expires_at=now)
        )
        cancel_pending(self.session, endpoint, now)
        self.commit()

    def redeliver(self, delivery_id):
        original = self.delivery(delivery_id)
        endpoint = self.endpoint(original.endpoint_id, lock=True)
        pending = self.session.scalar(
            select(Delivery.id).where(
                Delivery.tenant_id == self.tenant_id,
                Delivery.endpoint_id == endpoint.id,
                Delivery.event_id == original.event_id,
                Delivery.status == "pending",
            )
        )
        if original.status == "pending" or endpoint.status != "enabled" or pending:
            raise WebhookError(
                409,
                "delivery-not-redeliverable",
                "Delivery must be terminal with an enabled endpoint and no pending delivery",
            )
        now = now_utc()
        delivery = Delivery(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            endpoint_id=endpoint.id,
            event_id=original.event_id,
            event_type=original.event_type,
            kind="redelivery",
            redelivery_of_id=original.id,
            requested_by=self.actor_id,
            status="pending",
            created_at=now,
            next_attempt_at=now,
        )
        self.session.add(delivery)
        endpoint.version += 1
        endpoint.updated_at = now
        audit(self.session, endpoint, self.actor_id, "redelivered", self.correlation_id)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise WebhookError(
                409, "delivery-not-redeliverable", "Another delivery is pending"
            ) from None
        return delivery_view(delivery)

    def endpoint_view(self, endpoint):
        result = {
            name: getattr(endpoint, name)
            for name in (
                "id",
                "url",
                "description",
                "status",
                "disabled_reason",
                "consecutive_failures",
                "failure_streak_started_at",
                "version",
                "created_at",
                "updated_at",
            )
        }
        result["event_types"] = sorted(
            self.session.scalars(
                select(Subscription.event_type).where(
                    Subscription.tenant_id == self.tenant_id,
                    Subscription.endpoint_id == endpoint.id,
                )
            )
        )
        result["secrets"] = [
            {"id": s.id, "status": s.status, "created_at": s.created_at, "expires_at": s.expires_at}
            for s in self.session.scalars(
                select(Secret)
                .where(
                    Secret.tenant_id == self.tenant_id,
                    Secret.endpoint_id == endpoint.id,
                    or_(
                        Secret.status == "current",
                        (Secret.status == "previous") & (Secret.expires_at > now_utc()),
                    ),
                )
                .order_by(Secret.created_at.desc())
            )
        ]
        result["secrets"] = [timestamps(secret) for secret in result["secrets"]]
        return timestamps(result)

    def detail(self, delivery_id):
        delivery = self.delivery(delivery_id)
        attempts = self.session.scalars(
            select(Attempt)
            .where(Attempt.tenant_id == self.tenant_id, Attempt.delivery_id == delivery_id)
            .order_by(Attempt.attempt_number)
        )
        return {
            **delivery_view(delivery),
            "attempts": [
                {
                    name: getattr(a, name)
                    for name in (
                        "attempt_number",
                        "started_at",
                        "duration_ms",
                        "status_code",
                        "error_code",
                    )
                }
                for a in attempts
            ],
        }


def delivery_view(delivery):
    return timestamps(
        {
            **{
                name: getattr(delivery, name)
                for name in (
                    "id",
                    "endpoint_id",
                    "event_id",
                    "event_type",
                    "kind",
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_attempt_at",
                    "last_status_code",
                    "last_error_code",
                    "redelivery_of_id",
                    "requested_by",
                    "created_at",
                    "completed_at",
                )
            },
            "max_attempts": 8,
        }
    )


def page(session, query, model, cursor, limit, render):
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            timestamp, ident = decoded.split("|")
            timestamp = datetime.fromisoformat(timestamp)
            if timestamp.tzinfo is None:
                raise ValueError
            from uuid import UUID

            UUID(ident)
        except (ValueError, UnicodeError):
            raise WebhookError(400, "validation-error", "Invalid cursor") from None
        query = query.where(
            or_(model.created_at < timestamp, (model.created_at == timestamp) & (model.id < ident))
        )
    rows = list(
        session.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))
    )
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            f"{aware(rows[-1].created_at).isoformat()}|{rows[-1].id}".encode()
        ).decode()
        if more
        else None
    )
    return {"items": [render(row) for row in rows], "next_cursor": next_cursor}
