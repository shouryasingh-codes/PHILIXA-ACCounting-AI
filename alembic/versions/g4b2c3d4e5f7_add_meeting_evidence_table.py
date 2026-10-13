"""add meeting evidence table

Revision ID: g4b2c3d4e5f7
Revises: f3a1b2c4d5e6
Create Date: 2026-07-30 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = 'g4b2c3d4e5f7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IMPORTANT: Create the vector extension BEFORE creating the table
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        'meeting_evidence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('meeting_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=384), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meeting_evidence_id'), 'meeting_evidence', ['id'], unique=False)
    op.create_index(op.f('ix_meeting_evidence_meeting_id'), 'meeting_evidence', ['meeting_id'], unique=False)
    op.create_index(op.f('ix_meeting_evidence_organization_id'), 'meeting_evidence', ['organization_id'], unique=False)
    op.create_index(op.f('ix_meeting_evidence_user_id'), 'meeting_evidence', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meeting_evidence_user_id'), table_name='meeting_evidence')
    op.drop_index(op.f('ix_meeting_evidence_organization_id'), table_name='meeting_evidence')
    op.drop_index(op.f('ix_meeting_evidence_meeting_id'), table_name='meeting_evidence')
    op.drop_index(op.f('ix_meeting_evidence_id'), table_name='meeting_evidence')
    op.drop_table('meeting_evidence')
