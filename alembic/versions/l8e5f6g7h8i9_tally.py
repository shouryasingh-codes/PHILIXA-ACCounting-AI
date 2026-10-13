"""Add scoped Tally connection and durable write approvals."""
from alembic import op
import sqlalchemy as sa
revision = 'l8e5f6g7h8i9'
down_revision = 'k7d4e5f6g7h8'
branch_labels = depends_on = None


def upgrade():
    # Development startup calls metadata.create_all; accept only matching existing tables.
    inspector=sa.inspect(op.get_bind())
    if not inspector.has_table('tally_connections'):
      op.create_table('tally_connections',
        sa.Column('organization_id', sa.String(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('company', sa.String(200), nullable=False),
        sa.Column('godown', sa.String(200), nullable=False),
        sa.Column('purchase_ledger', sa.String(200), nullable=False),
        sa.Column('sales_ledger', sa.String(200), nullable=False),
        sa.Column('test_company', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False))
    if not inspector.has_table('tally_actions'):
      op.create_table('tally_actions',
        sa.Column('token', sa.String(32), primary_key=True),
        sa.Column('organization_id', sa.String(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('session_id', sa.String(100), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('connection_version', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('xml_payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True))
    for table,expected in {
        'tally_connections':{'organization_id','company','godown','purchase_ledger','sales_ledger','test_company','version'},
        'tally_actions':{'token','organization_id','user_id','session_id','expires_at','created_at','connection_version','payload','xml_payload','status','result'}
    }.items():
        if {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)} != expected:
            raise RuntimeError('Unexpected Tally table schema: '+table)
    if not any(i['name']=='ix_tally_actions_organization_id' for i in sa.inspect(op.get_bind()).get_indexes('tally_actions')):
        op.create_index('ix_tally_actions_organization_id', 'tally_actions', ['organization_id'])


def downgrade():
    op.drop_table('tally_actions')
    op.drop_table('tally_connections')
