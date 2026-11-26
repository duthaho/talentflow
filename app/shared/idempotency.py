"""Database reservations shared by HTTP commands and the retention worker."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.shared.database import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("uq_idempotency_scope_key", "tenant_id", "actor_id", "key", unique=True),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    headers: Mapped[dict | None] = mapped_column(JSON)


def purge_expired_keys(session: Session, *, batch_size: int) -> int:
    """Bound each worker cycle; PostgreSQL replicas skip rows already being purged."""
    expired = (
        select(IdempotencyRecord.id)
        .where(IdempotencyRecord.expires_at <= datetime.now(UTC))
        .order_by(IdempotencyRecord.expires_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    ids = list(session.scalars(expired))
    if ids:
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id.in_(ids)))
    session.commit()
    return len(ids)
