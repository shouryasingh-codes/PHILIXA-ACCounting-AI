"""Merge all heads: timezone + source_type

Revision ID: a1b2c3d4e5f6
Revises: 22ee53e99b7a, f3a1b2c4d5e6
Create Date: 2026-07-29 12:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = ('22ee53e99b7a', 'f3a1b2c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
