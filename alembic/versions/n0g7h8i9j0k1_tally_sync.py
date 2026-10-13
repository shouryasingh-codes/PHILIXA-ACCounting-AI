"""Durable snapshots and confirmed purchase queue."""
from alembic import op
import sqlalchemy as sa
from app.models.tally import TallySnapshot
revision = 'n0g7h8i9j0k1'
down_revision = 'm9f6g7h8i9j0'
branch_labels = depends_on = None

def upgrade():
    op.add_column('tally_read_companies', sa.Column('refresh_requested', sa.Boolean(), nullable=False, server_default=sa.true()))
    TallySnapshot.__table__.create(op.get_bind(), checkfirst=True)
    op.add_column('tally_actions', sa.Column('company_id', sa.String(32), sa.ForeignKey('tally_read_companies.id'), nullable=True))
    op.add_column('tally_actions', sa.Column('device_version', sa.String(64), nullable=True))
    op.add_column('tally_actions', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tally_actions', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    op.create_index('ix_tally_actions_next_attempt_at', 'tally_actions', ['next_attempt_at'])

def downgrade():
    op.drop_column('tally_read_companies', 'refresh_requested')
    op.drop_index('ix_tally_actions_next_attempt_at', 'tally_actions')
    for field in ('attempts', 'next_attempt_at', 'device_version', 'company_id'):
        op.drop_column('tally_actions', field)
    op.drop_table('tally_snapshots')
