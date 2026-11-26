"""Expand event metadata and introduce consumer inbox (ADR 006)."""

import sqlalchemy as sa
from alembic import op

revision = "d59a001"
down_revision = "d60a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, type_ in (
        ("occurred_at", sa.DateTime(timezone=True)),
        ("subject", sa.String(36)),
        ("correlation_id", sa.String(128)),
        ("causation_id", sa.String(128)),
        ("actor_id", sa.String(128)),
        ("traceparent", sa.String(55)),
        ("last_error", sa.Text()),
    ):
        op.add_column("outbox_events", sa.Column(name, type_, nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE outbox_events SET occurred_at = created_at")
    op.create_table(
        "inbox_messages",
        sa.Column("consumer", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_inbox_messages_processed_at", "inbox_messages", ["processed_at"])
    op.create_index("ix_outbox_pending_created", "outbox_events", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending_created", table_name="outbox_events")
    op.drop_table("inbox_messages")
    for name in (
        "occurred_at",
        "subject",
        "correlation_id",
        "causation_id",
        "actor_id",
        "traceparent",
        "last_error",
        "publish_attempts",
    ):
        op.drop_column("outbox_events", name)
