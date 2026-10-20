"""add candidate attachments

Revision ID: 5b02a38d7c91
Revises: ef1b28c33b03
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b02a38d7c91"
down_revision: str | Sequence[str] | None = "ef1b28c33b03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_case_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_case_id"], ["candidate_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_candidate_attachment_storage_key"),
    )
    op.create_index(
        op.f("ix_candidate_attachments_candidate_case_id"),
        "candidate_attachments",
        ["candidate_case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_attachments_tenant_id"),
        "candidate_attachments",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_candidate_attachments_tenant_id"), table_name="candidate_attachments")
    op.drop_index(
        op.f("ix_candidate_attachments_candidate_case_id"), table_name="candidate_attachments"
    )
    op.drop_table("candidate_attachments")
