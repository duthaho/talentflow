"""Onboarding persistence contains identifiers and policy state only."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database import Base


class Saga(Base):
    __tablename__ = "onboarding_sagas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "candidate_case_id", name="uq_onboarding_saga_case"),
        CheckConstraint(
            "status IN ('running','compensating','compensated','completed','completed_with_warnings','cancelled','compensation_failed')",
            name="ck_onboarding_saga_status",
        ),
        CheckConstraint(
            "compensation_reason IS NULL OR compensation_reason IN ('step_failed','cancel_requested','candidate_erased')",
            name="ck_onboarding_saga_reason",
        ),
        CheckConstraint(
            "warning IS NULL OR warning IN ('notify_exhausted','no_recipients','candidate_erased')",
            name="ck_onboarding_saga_warning",
        ),
        Index("ix_onboarding_sagas_tenant_status", "tenant_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    candidate_case_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="running")
    attempt: Mapped[int] = mapped_column(default=1, server_default="1")
    start_date: Mapped[date] = mapped_column(Date)
    hired_by: Mapped[str | None] = mapped_column(String(128))
    compensation_reason: Mapped[str | None] = mapped_column(String(24))
    warning: Mapped[str | None] = mapped_column(String(32))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_event_id: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Step(Base):
    __tablename__ = "onboarding_saga_steps"
    __table_args__ = (
        UniqueConstraint("saga_id", "attempt", "step", name="uq_onboarding_step"),
        CheckConstraint(
            "step IN ('create_employee','provision_account','schedule_tasks','notify')",
            name="ck_onboarding_step_name",
        ),
        CheckConstraint(
            "status IN ('pending','in_flight','retry_wait','succeeded','failed','skipped','not_run')",
            name="ck_onboarding_step_status",
        ),
        CheckConstraint(
            "compensation_status IS NULL OR compensation_status IN ('pending','in_flight','retry_wait','done','failed')",
            name="ck_onboarding_comp_status",
        ),
        Index("ix_onboarding_steps_saga", "saga_id", "attempt", "position"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    saga_id: Mapped[str] = mapped_column(ForeignKey("onboarding_sagas.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(String(36))
    attempt: Mapped[int]
    step: Mapped[str] = mapped_column(String(24))
    position: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(64))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(String(64))
    compensation_status: Mapped[str | None] = mapped_column(String(16))
    compensation_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))


Index(
    "ix_onboarding_steps_due",
    Step.next_attempt_at,
    postgresql_where=Step.next_attempt_at.is_not(None),
    sqlite_where=Step.next_attempt_at.is_not(None),
)


class Task(Base):
    __tablename__ = "onboarding_tasks"
    __table_args__ = (
        UniqueConstraint("saga_id", "attempt", "key", name="uq_onboarding_task"),
        CheckConstraint("status IN ('scheduled','cancelled')", name="ck_onboarding_task_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    saga_id: Mapped[str] = mapped_column(ForeignKey("onboarding_sagas.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(String(36))
    attempt: Mapped[int]
    key: Mapped[str] = mapped_column(String(24))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", server_default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Tombstone(Base):
    __tablename__ = "onboarding_erasure_tombstones"
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    erased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_event_id: Mapped[str] = mapped_column(String(36))
