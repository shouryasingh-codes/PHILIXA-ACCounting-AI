"""Private saved business conversations."""
from alembic import op
import sqlalchemy as sa
revision = 'q3j0k1l2m3n4'
down_revision = 'p2i9j0k1l2m3'
branch_labels = depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('business_conversations'):
        required = {'id','organization_id','user_id','title','messages','session_id','revision','created_at','updated_at'}
        if {column['name'] for column in inspector.get_columns('business_conversations')} != required:
            raise RuntimeError('Existing conversation table differs from the migration.')
        return
    op.create_table('business_conversations',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('organization_id',sa.String(),sa.ForeignKey('organizations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('title',sa.String(100),nullable=False),
        sa.Column('messages',sa.JSON(),nullable=False),
        sa.Column('session_id',sa.String(64),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for column in ('organization_id','user_id','updated_at'):
        op.create_index('ix_business_conversations_'+column,'business_conversations',[column])


def downgrade():
    op.drop_table('business_conversations')
