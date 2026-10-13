"""Add source_type to meetings

Revision ID: f3a1b2c4d5e6
Revises: 23ca372069ef
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1b2c4d5e6'
down_revision: Union[str, None] = '23ca372069ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw connection to safely add the column only if it doesn't exist.
    # This prevents DuplicateColumn errors on databases that were already
    # running before this migration was introduced.
    connection = op.get_bind()
    result = connection.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='meetings' AND column_name='source_type'"
        )
    ).fetchone()
    if result is None:
        op.add_column(
            'meetings',
            sa.Column(
                'source_type',
                sa.String(40),
                nullable=False,
                server_default='pasted_note',
            ),
        )


def downgrade() -> None:
    op.drop_column('meetings', 'source_type')
