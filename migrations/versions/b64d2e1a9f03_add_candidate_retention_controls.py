"""add candidate retention controls

Revision ID: b64d2e1a9f03
Revises: a47b9c0d13e6
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b64d2e1a9f03"
down_revision: str | Sequence[str] | None = "a47b9c0d13e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_cases", sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "retention_policies",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "candidate_legal_holds",
        sa.Column("candidate_case_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_case_id"], ["candidate_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_case_id"),
    )
    op.create_index("ix_candidate_legal_holds_tenant_id", "candidate_legal_holds", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_legal_holds_tenant_id", table_name="candidate_legal_holds")
    op.drop_table("candidate_legal_holds")
    op.drop_table("retention_policies")
    op.drop_column("candidate_cases", "anonymized_at")
