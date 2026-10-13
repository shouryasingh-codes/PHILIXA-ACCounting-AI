"""add WhatsApp phone fields for clients and client confirmation

Revision ID: 2d7e8f9a0b1c
Revises: 70f242efc17d
Create Date: 2026-09-03 01:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d7e8f9a0b1c"
down_revision: Union[str, None] = "70f242efc17d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("whatsapp_phone", sa.String(length=20), nullable=True))
    op.add_column(
        "meetings",
        sa.Column("suggested_client_whatsapp_phone", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meetings", "suggested_client_whatsapp_phone")
    op.drop_column("clients", "whatsapp_phone")
