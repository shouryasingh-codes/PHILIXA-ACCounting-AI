"""Day 8 durable controlled automation."""
from alembic import op
revision='x0q7r8s9t0u1'
down_revision='w9p6q7r8s9t0'
branch_labels=None
depends_on=None
def upgrade():
    from app.models.purchase_automation import PurchaseAutomationPolicy, PurchaseAutomationDecision, PurchaseAutomationReservation, PurchaseAutomationPolicyEvent
    for model in (PurchaseAutomationPolicy,PurchaseAutomationDecision,PurchaseAutomationReservation,PurchaseAutomationPolicyEvent):model.__table__.create(op.get_bind(),checkfirst=True)
def downgrade():
    for table in ('purchase_automation_policy_events','purchase_automation_reservations','purchase_automation_decisions','purchase_automation_policies'):op.drop_table(table)
