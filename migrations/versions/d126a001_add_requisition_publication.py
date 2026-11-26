"""Add requisition publication with safe defaults for existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "d126a001"
down_revision = "2d110f23a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "requisitions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_requisitions_public",
        "requisitions",
        ["tenant_id", sa.text("published_at DESC")],
        postgresql_where=sa.text("published"),
        sqlite_where=sa.text("published"),
    )


def downgrade() -> None:
    op.drop_index("ix_requisitions_public", table_name="requisitions")
    op.drop_column("requisitions", "published_at")
    op.drop_column("requisitions", "published")
