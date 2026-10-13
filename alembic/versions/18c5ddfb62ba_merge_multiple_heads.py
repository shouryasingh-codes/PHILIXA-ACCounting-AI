"""Merge multiple heads

Revision ID: 18c5ddfb62ba
Revises: bb88f5a4f089, e1f2a3b4c5d6
Create Date: 2026-07-28 16:35:28.849661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18c5ddfb62ba'
down_revision: Union[str, None] = ('bb88f5a4f089', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
