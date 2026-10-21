"""add calendar subscriptions

Revision ID: a47b9c0d13e6
Revises: 5b02a38d7c91
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a47b9c0d13e6"
down_revision: str | Sequence[str] | None = "5b02a38d7c91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_subscriptions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("interviewer_id", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["interviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_calendar_subscriptions_tenant_id", "calendar_subscriptions", ["tenant_id"])
    op.create_index(
        "ix_calendar_subscriptions_interviewer_id", "calendar_subscriptions", ["interviewer_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_subscriptions_interviewer_id", table_name="calendar_subscriptions")
    op.drop_index("ix_calendar_subscriptions_tenant_id", table_name="calendar_subscriptions")
    op.drop_table("calendar_subscriptions")
