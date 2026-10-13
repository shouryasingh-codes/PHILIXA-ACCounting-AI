"""Recoverable invoice extraction state."""
from alembic import op
import sqlalchemy as sa
revision='u7n4o5p6q7r8'
down_revision='t6m3n4o5p6q7'
branch_labels=None
depends_on=None

def upgrade():
    existing={c['name'] for c in sa.inspect(op.get_bind()).get_columns('bill_documents')}
    columns=[sa.Column('extraction_result',sa.JSON(),nullable=True),sa.Column('extraction_error',sa.String(500),nullable=True),
        sa.Column('extraction_attempts',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('extraction_generation',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('extraction_split',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('extraction_lease_token',sa.String(32),nullable=True),
        sa.Column('extraction_lease_until',sa.DateTime(timezone=True),nullable=True),
        sa.Column('extraction_next_attempt_at',sa.DateTime(timezone=True),nullable=True)]
    for c in columns:
        if c.name not in existing:op.add_column('bill_documents',c)

def downgrade():
    for name in ('extraction_next_attempt_at','extraction_lease_until','extraction_lease_token','extraction_split','extraction_generation','extraction_attempts','extraction_error','extraction_result'):
        op.drop_column('bill_documents',name)
