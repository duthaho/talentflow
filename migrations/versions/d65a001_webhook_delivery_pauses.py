"""Expand-only pause bookkeeping; downgrade removes only the new table."""

import sqlalchemy as sa
from alembic import op

revision = "d65a001"
down_revision = "d127a001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "webhook_delivery_pauses",
        sa.Column("tenant_id", sa.String(36), primary_key=True),
        sa.Column("paused_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.CheckConstraint("reason IN ('flag_off', 'flag_error')", name="ck_webhook_pause_reason"),
    )


def downgrade():
    op.drop_table("webhook_delivery_pauses")
