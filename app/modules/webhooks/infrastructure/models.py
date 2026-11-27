"""Tenant-scoped webhook records (ADR-008)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database import Base


def uid():
    return str(uuid4())


class Endpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("status IN ('enabled','disabled','deleted')"),
        CheckConstraint("disabled_reason IN ('manual','failing','gone')"),
        CheckConstraint("(status = 'disabled') = (disabled_reason IS NOT NULL)"),
        Index(
            "uq_webhook_endpoints_tenant_url",
            "tenant_id",
            "url",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
            sqlite_where=text("status <> 'deleted'"),
        ),
        Index(
            "ix_webhook_endpoints_tenant_page",
            "tenant_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    url: Mapped[str] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    disabled_reason: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failure_streak_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "endpoint_id"],
            ["webhook_endpoints.tenant_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        Index("ix_webhook_subscriptions_fanout", "tenant_id", "event_type"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36))
    endpoint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(160), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Secret(Base):
    __tablename__ = "webhook_secrets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "endpoint_id"],
            ["webhook_endpoints.tenant_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('current','previous','expired')"),
        CheckConstraint("(status = 'expired') = (ciphertext IS NULL)"),
        Index(
            "uq_webhook_secrets_current",
            "endpoint_id",
            unique=True,
            postgresql_where=text("status = 'current'"),
            sqlite_where=text("status = 'current'"),
        ),
        Index(
            "uq_webhook_secrets_previous",
            "endpoint_id",
            unique=True,
            postgresql_where=text("status = 'previous'"),
            sqlite_where=text("status = 'previous'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    endpoint_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    ciphertext: Mapped[str | None] = mapped_column(Text)
    key_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "webhook_events"
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(160))
    body: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Delivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "endpoint_id"], ["webhook_endpoints.tenant_id", "webhook_endpoints.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"], ["webhook_events.tenant_id", "webhook_events.event_id"]
        ),
        CheckConstraint("status IN ('pending','succeeded','dead_lettered','cancelled')"),
        CheckConstraint("kind IN ('fanout','redelivery')"),
        CheckConstraint(
            "kind = 'redelivery' OR (redelivery_of_id IS NULL AND requested_by IS NULL)"
        ),
        CheckConstraint("kind = 'fanout' OR requested_by IS NOT NULL"),
        Index(
            "uq_webhook_deliveries_fanout",
            "endpoint_id",
            "event_id",
            unique=True,
            postgresql_where=text("kind = 'fanout'"),
            sqlite_where=text("kind = 'fanout'"),
        ),
        Index(
            "uq_webhook_deliveries_pending",
            "endpoint_id",
            "event_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "ix_webhook_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "ix_webhook_deliveries_log",
            "tenant_id",
            "endpoint_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_webhook_deliveries_purge",
            "completed_at",
            postgresql_where=text("status <> 'pending'"),
            sqlite_where=text("status <> 'pending'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    endpoint_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    redelivery_of_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("webhook_deliveries.id", ondelete="SET NULL")
    )
    requested_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number"),
        ForeignKeyConstraint(
            ["tenant_id", "delivery_id"],
            ["webhook_deliveries.tenant_id", "webhook_deliveries.id"],
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    delivery_id: Mapped[str] = mapped_column(String(36))
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(32))
    signed_secret_ids: Mapped[str] = mapped_column(String(80))
