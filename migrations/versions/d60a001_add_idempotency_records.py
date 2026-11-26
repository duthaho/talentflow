"""Add tenant/principal-scoped command reservations (expand only)."""

import sqlalchemy as sa
from alembic import op

revision = "d60a001"
down_revision = "2d110f23a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=True),
    )
    op.create_index(
        "uq_idempotency_scope_key",
        "idempotency_records",
        ["tenant_id", "actor_id", "key"],
        unique=True,
    )
    op.create_index("ix_idempotency_expires_at", "idempotency_records", ["expires_at"])


def downgrade() -> None:
    op.drop_table("idempotency_records")
