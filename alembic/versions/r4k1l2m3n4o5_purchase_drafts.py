"""Durable purchase drafts and append-only revision history."""
from alembic import op
import sqlalchemy as sa

revision = 'r4k1l2m3n4o5'
down_revision = 'q3j0k1l2m3n4'
branch_labels = depends_on = None


def upgrade():
    # Development startup calls create_all; accept only the same table shape.
    inspector = sa.inspect(op.get_bind())
    tables = {
        'purchase_drafts': {'id','organization_id','user_id','company_id','content','revision','action_id','created_at','updated_at'},
        'purchase_draft_events': {'id','draft_id','revision','actor_id','kind','snapshot','action_id','created_at'},
    }
    for name, columns in tables.items():
        if inspector.has_table(name) and {c['name'] for c in inspector.get_columns(name)} != columns:
            raise RuntimeError('Existing '+name+' differs from the migration.')
    if not inspector.has_table('purchase_drafts'):
        op.create_table('purchase_drafts',
            sa.Column('id',sa.String(32),primary_key=True),
            sa.Column('organization_id',sa.String(),sa.ForeignKey('organizations.id',ondelete='CASCADE'),nullable=False),
            sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
            sa.Column('company_id',sa.String(),sa.ForeignKey('tally_read_companies.id',ondelete='CASCADE'),nullable=False),
            sa.Column('content',sa.JSON(),nullable=False),
            sa.Column('revision',sa.Integer(),nullable=False),
            sa.Column('action_id',sa.String(),sa.ForeignKey('tally_actions.token',ondelete='SET NULL'),nullable=True),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
            sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint('action_id'))
        for column in ('organization_id','user_id','company_id','updated_at'):
            op.create_index('ix_purchase_drafts_'+column,'purchase_drafts',[column])
    if not inspector.has_table('purchase_draft_events'):
        op.create_table('purchase_draft_events',
            sa.Column('id',sa.String(32),primary_key=True),
            sa.Column('draft_id',sa.String(),sa.ForeignKey('purchase_drafts.id',ondelete='CASCADE'),nullable=False),
            sa.Column('revision',sa.Integer(),nullable=False),
            sa.Column('actor_id',sa.String(100),nullable=False),
            sa.Column('kind',sa.String(30),nullable=False),
            sa.Column('snapshot',sa.JSON(),nullable=False),
            sa.Column('action_id',sa.String(32),nullable=True),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint('draft_id','revision',name='uq_purchase_draft_event_revision'))
        op.create_index('ix_purchase_draft_events_draft_id','purchase_draft_events',['draft_id'])


def downgrade():
    op.drop_table('purchase_draft_events')
    op.drop_table('purchase_drafts')
