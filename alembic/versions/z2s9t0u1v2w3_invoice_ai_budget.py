"""Durable invoice-provider cost reservations."""
from alembic import op
revision='z2s9t0u1v2w3'
down_revision='y1r8s9t0u1v2'
branch_labels=None
depends_on=None

def upgrade():
    from app.models.invoice_ai_budget import InvoiceAIBudgetDebit
    InvoiceAIBudgetDebit.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():op.drop_table('invoice_ai_budget_debits')
