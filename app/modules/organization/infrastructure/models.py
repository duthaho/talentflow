from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class Requisition(Base):
    __tablename__ = "requisitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


Index(
    "ix_requisitions_public",
    Requisition.tenant_id,
    Requisition.published_at.desc(),
    postgresql_where=Requisition.published,
    sqlite_where=Requisition.published,
)
