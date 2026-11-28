"""Expand candidate source and consent; retain the system principal on rollback."""

import sqlalchemy as sa
from alembic import op

revision = "d127a001"
down_revision = "d62a001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("candidate_cases") as batch:
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="staff"))
        batch.create_check_constraint("ck_candidate_cases_source", "source IN ('staff', 'careers')")
    op.create_table(
        "candidate_consents",
        sa.Column(
            "candidate_case_id",
            sa.String(36),
            sa.ForeignKey("candidate_cases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "INSERT INTO users (id, email, created_at) VALUES ('system:careers', NULL, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
    )


def downgrade():
    op.drop_table("candidate_consents")
    with op.batch_alter_table("candidate_cases") as batch:
        batch.drop_constraint("ck_candidate_cases_source", type_="check")
        batch.drop_column("source")
