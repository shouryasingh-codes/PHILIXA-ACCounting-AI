"""Add the missing meeting client-name suggestion column.

Revision ID: j6c3d4e5f6g7
Revises: 924be62947b0
"""
from alembic import op
import sqlalchemy as sa

revision = "j6c3d4e5f6g7"
down_revision = "924be62947b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some existing databases have this column from manual schema updates.
    columns = sa.inspect(op.get_bind()).get_columns("meetings")
    if not any(column["name"] == "suggested_client_name" for column in columns):
        op.add_column(
            "meetings",
            sa.Column("suggested_client_name", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("meetings", "suggested_client_name")
