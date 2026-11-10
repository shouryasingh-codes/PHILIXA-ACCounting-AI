"""Day 7 company aliases and atomic duplicate invoice claims."""
from alembic import op
import sqlalchemy as sa
revision='w9p6q7r8s9t0'
down_revision='v8o5p6q7r8s9'
branch_labels=None
depends_on=None

def upgrade():
    from app.models.purchase_memory import PurchaseAlias, PurchaseInvoiceClaim
    PurchaseAlias.__table__.create(op.get_bind(),checkfirst=True)
    PurchaseInvoiceClaim.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():
    op.drop_table('purchase_invoice_claims')
    op.drop_table('purchase_aliases')
