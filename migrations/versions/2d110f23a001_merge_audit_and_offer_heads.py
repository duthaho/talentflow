"""Merge the audit index and offer decision migration branches.

Revision ID: 2d110f23a001
Revises: 1d110a1b3c01, f23b5e9d1120

Both additive migrations must remain intact for databases that already applied
either branch. This revision only joins their histories; it changes no schema.
"""

revision = "2d110f23a001"
down_revision = ("1d110a1b3c01", "f23b5e9d1120")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
