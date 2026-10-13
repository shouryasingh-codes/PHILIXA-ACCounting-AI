"""Private document batches, originals and durable processing leases."""
from alembic import op
import sqlalchemy as sa
revision='s5l2m3n4o5p6'
down_revision='r4k1l2m3n4o5'
branch_labels=depends_on=None


def upgrade():
    inspector=sa.inspect(op.get_bind())
    shapes={'document_batches':{'id','organization_id','user_id','company_id','created_at'},
        'bill_documents':{'id','organization_id','user_id','company_id','filename','media_type','size','sha256','object_key','status','error_code','page_count','attempts','generation','lease_token','lease_until','next_attempt_at','created_at','updated_at'},
        'document_batch_items':{'batch_id','document_id'}}
    for table,columns in shapes.items():
        if inspector.has_table(table) and {c['name'] for c in inspector.get_columns(table)}!=columns:raise RuntimeError('Existing '+table+' differs from migration')
    def scope():
        return [sa.Column('id',sa.String(32),primary_key=True),
            sa.Column('organization_id',sa.String(),sa.ForeignKey('organizations.id',ondelete='CASCADE'),nullable=False),
            sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
            sa.Column('company_id',sa.String(),sa.ForeignKey('tally_read_companies.id',ondelete='CASCADE'),nullable=False)]
    if not inspector.has_table('document_batches'):
        op.create_table('document_batches',*scope(),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
        for key in ('organization_id','user_id','company_id'):op.create_index('ix_document_batches_'+key,'document_batches',[key])
    if not inspector.has_table('bill_documents'):
        op.create_table('bill_documents',*scope(),
            sa.Column('filename',sa.String(160),nullable=False),sa.Column('media_type',sa.String(40),nullable=False),
            sa.Column('size',sa.Integer(),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),
            sa.Column('object_key',sa.String(400),nullable=False),sa.Column('status',sa.String(20),nullable=False),
            sa.Column('error_code',sa.String(40)),sa.Column('page_count',sa.Integer()),
            sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('generation',sa.Integer(),nullable=False),
            sa.Column('lease_token',sa.String(32)),sa.Column('lease_until',sa.DateTime(timezone=True)),sa.Column('next_attempt_at',sa.DateTime(timezone=True)),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint('organization_id','user_id','company_id','sha256',name='uq_bill_document_source'))
        for key in ('organization_id','user_id','company_id','status'):op.create_index('ix_bill_documents_'+key,'bill_documents',[key])
    if not inspector.has_table('document_batch_items'):
        op.create_table('document_batch_items',sa.Column('batch_id',sa.String(),sa.ForeignKey('document_batches.id',ondelete='CASCADE'),primary_key=True),
            sa.Column('document_id',sa.String(),sa.ForeignKey('bill_documents.id',ondelete='CASCADE'),primary_key=True))


def downgrade():
    for table in ('document_batch_items','bill_documents','document_batches'):op.drop_table(table)
