"""index audit events by aggregate

Revision ID: 1d110a1b3c01
Revises: c91e5b7d2a64
Create Date: 2026-11-26
"""

from alembic import op

revision = "1d110a1b3c01"
down_revision = "c91e5b7d2a64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Production deployments should use CREATE INDEX CONCURRENTLY for large tables.
    op.create_index(
        "ix_audit_events_tenant_aggregate_created",
        "audit_events",
        ["tenant_id", "aggregate_type", "aggregate_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_aggregate_created", table_name="audit_events")
