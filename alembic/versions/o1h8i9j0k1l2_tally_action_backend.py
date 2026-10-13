"""Add operation-neutral metadata without altering existing action payloads."""
from alembic import op
import sqlalchemy as sa
revision='o1h8i9j0k1l2'
down_revision='n0g7h8i9j0k1'
branch_labels=depends_on=None

def upgrade():
    op.add_column('tally_actions',sa.Column('backend',sa.String(20),nullable=False,server_default='python'))
    op.add_column('tally_actions',sa.Column('schema_version',sa.Integer(),nullable=False,server_default='1'))
    for name in ('approved_arguments','target_identity','preconditions','verification_result'):
        op.add_column('tally_actions',sa.Column(name,sa.JSON(),nullable=True))

def downgrade():
    for name in ('verification_result','preconditions','target_identity','approved_arguments','schema_version','backend'):
        op.drop_column('tally_actions',name)
