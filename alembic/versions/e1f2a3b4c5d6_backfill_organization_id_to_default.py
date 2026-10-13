"""Backfill organization_id to 'default' for all legacy SYSTEM/SYSTEM_ORG rows

Revision ID: e1f2a3b4c5d6
Revises: 23ca372069ef
Create Date: 2026-07-28

Background:
  The TenantMixin originally used server_default='SYSTEM' for the DB column
  and a Python-level default of 'SYSTEM_ORG'. Neither value matches the
  canonical org_id 'default' that the application now uses for tenant
  scoping. This migration normalises all legacy rows so existing data
  remains visible after the tenant-filtering changes go live.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "23ca372069ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_VALUES = ("SYSTEM", "SYSTEM_ORG")
_TARGET = "default"
_TABLES = ("clients", "meetings", "commitments")


def upgrade() -> None:
    for table in _TABLES:
        for legacy in _LEGACY_VALUES:
            op.execute(
                f"UPDATE {table} SET organization_id = '{_TARGET}' "  # noqa: S608
                f"WHERE organization_id = '{legacy}'"
            )


def downgrade() -> None:
    # We cannot know whether a row was originally 'SYSTEM' or 'SYSTEM_ORG',
    # so we restore everything to 'SYSTEM' (the original DB server_default).
    for table in _TABLES:
        op.execute(
            f"UPDATE {table} SET organization_id = 'SYSTEM' "  # noqa: S608
            f"WHERE organization_id = '{_TARGET}'"
        )
