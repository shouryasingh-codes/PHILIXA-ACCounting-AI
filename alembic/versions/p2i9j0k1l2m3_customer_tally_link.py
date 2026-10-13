"""Persist verified customer-to-Tally ledger links."""
from alembic import op
import sqlalchemy as sa
revision = 'p2i9j0k1l2m3'
down_revision = 'o1h8i9j0k1l2'
branch_labels = depends_on = None

def upgrade():
    # The development app calls metadata.create_all() on hot reload. Accept only
    # the identical table it may have created before Alembic records this revision.
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table('tally_customer_links'):
        required={'id','organization_id','client_id','company_id','company_identity','ledger_guid','ledger_name','ledger_parent','action_id','verified_at'}
        if {c['name'] for c in inspector.get_columns('tally_customer_links')}!=required:
            raise RuntimeError('Existing customer link table differs from the migration.')
        unique={tuple(c['column_names']) for c in inspector.get_unique_constraints('tally_customer_links')}
        if not {('company_id','ledger_guid'),('company_id','client_id')}<=unique:
            raise RuntimeError('Customer link identity constraints missing.')
        return
    op.create_table('tally_customer_links',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('organization_id', sa.String(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', sa.String(32), sa.ForeignKey('tally_read_companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_identity', sa.String(250), nullable=False),
        sa.Column('ledger_guid', sa.String(250), nullable=False),
        sa.Column('ledger_name', sa.String(200), nullable=False),
        sa.Column('ledger_parent', sa.String(200), nullable=False),
        sa.Column('action_id', sa.String(32), sa.ForeignKey('tally_actions.token'), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('company_id','ledger_guid',name='uq_customer_native_ledger'),
        sa.UniqueConstraint('company_id','client_id',name='uq_customer_company_link'))
    op.create_index('ix_tally_customer_links_organization_id','tally_customer_links',['organization_id'])

def downgrade():
    op.drop_table('tally_customer_links')
