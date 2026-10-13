"""Day 4 — Link bill_documents with purchase_drafts and store extraction metadata."""
from alembic import op
import sqlalchemy as sa

revision = 't6m3n4o5p6q7'
down_revision = 's5l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('purchase_drafts'):
        cols = {c['name'] for c in inspector.get_columns('purchase_drafts')}
        if 'document_id' not in cols:
            op.add_column(
                'purchase_drafts',
                sa.Column('document_id', sa.String(32), sa.ForeignKey('bill_documents.id', ondelete='SET NULL'), nullable=True),
            )
            op.create_index('ix_purchase_drafts_document_id', 'purchase_drafts', ['document_id'])
        if 'extraction_metadata' not in cols:
            op.add_column(
                'purchase_drafts',
                sa.Column('extraction_metadata', sa.JSON(), nullable=True),
            )
    if inspector.has_table('bill_documents'):
        cols = {c['name'] for c in inspector.get_columns('bill_documents')}
        if 'extraction_status' not in cols:
            op.add_column(
                'bill_documents',
                sa.Column('extraction_status', sa.String(30), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('bill_documents'):
        cols = {c['name'] for c in inspector.get_columns('bill_documents')}
        if 'extraction_status' in cols:
            op.drop_column('bill_documents', 'extraction_status')
    if inspector.has_table('purchase_drafts'):
        cols = {c['name'] for c in inspector.get_columns('purchase_drafts')}
        if 'extraction_metadata' in cols:
            op.drop_column('purchase_drafts', 'extraction_metadata')
        if 'document_id' in cols:
            op.drop_index('ix_purchase_drafts_document_id', table_name='purchase_drafts')
            op.drop_column('purchase_drafts', 'document_id')
