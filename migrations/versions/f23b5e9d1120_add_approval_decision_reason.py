"""add approval decision reason and timestamp

Revision ID: f23b5e9d1120
Revises: c91e5b7d2a64
Create Date: 2026-11-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f23b5e9d1120"
down_revision: str | Sequence[str] | None = "c91e5b7d2a64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approval_decisions", sa.Column("reason", sa.String(length=500), nullable=True))
    op.add_column(
        "approval_decisions", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("approval_decisions", "decided_at")
    op.drop_column("approval_decisions", "reason")
