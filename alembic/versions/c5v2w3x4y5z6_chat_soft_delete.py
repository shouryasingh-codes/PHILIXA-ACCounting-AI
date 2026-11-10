"""Recoverable conversation deletion; accounting records are unchanged."""
from alembic import op
import sqlalchemy as sa

revision='c5v2w3x4y5z6'
down_revision='b4u1v2w3x4y5'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('business_conversations',sa.Column('deleted_at',sa.DateTime(timezone=True),nullable=True))


def downgrade():
    op.drop_column('business_conversations','deleted_at')
