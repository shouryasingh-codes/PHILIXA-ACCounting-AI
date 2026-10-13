"""add_email_to_clients_and_meetings

Revision ID: 70f242efc17d
Revises: 9a1b2c3d4e5f
Create Date: 2026-09-02 11:57:33.029342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70f242efc17d'
down_revision: Union[str, None] = '9a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('meetings', sa.Column('suggested_client_email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('meetings', 'suggested_client_email')
    op.drop_column('clients', 'email')
