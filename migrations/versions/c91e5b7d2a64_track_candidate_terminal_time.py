"""track candidate terminal transition time

Revision ID: c91e5b7d2a64
Revises: b64d2e1a9f03
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91e5b7d2a64"
down_revision: str | Sequence[str] | None = "b64d2e1a9f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_cases", sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_candidate_cases_terminal_at", "candidate_cases", ["terminal_at"])


def downgrade() -> None:
    op.drop_index("ix_candidate_cases_terminal_at", table_name="candidate_cases")
    op.drop_column("candidate_cases", "terminal_at")
