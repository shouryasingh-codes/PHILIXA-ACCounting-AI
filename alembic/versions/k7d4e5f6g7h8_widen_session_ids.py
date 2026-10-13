"""Allow prefixed session IDs, matching UserSession.id.

Revision ID: k7d4e5f6g7h8
Revises: j6c3d4e5f6g7
"""
from alembic import op
import sqlalchemy as sa

revision = "k7d4e5f6g7h8"
down_revision = "j6c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_sessions", "id", existing_type=sa.String(36),
        type_=sa.String(50), existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_sessions", "id", existing_type=sa.String(50),
        type_=sa.String(36), existing_nullable=False,
    )
