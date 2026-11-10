"""Recoverable document trash; original bytes and accounting history retained."""
from alembic import op
import sqlalchemy as sa
revision='a3t0u1v2w3x4'
down_revision='z2s9t0u1v2w3'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('bill_documents',sa.Column('trashed_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_bill_documents_trashed_at','bill_documents',['trashed_at'])

def downgrade():
    op.drop_index('ix_bill_documents_trashed_at',table_name='bill_documents')
    op.drop_column('bill_documents','trashed_at')
