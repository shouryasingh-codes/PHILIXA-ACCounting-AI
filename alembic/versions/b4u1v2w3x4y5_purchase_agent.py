"""Additive read evidence and checkpoint storage; existing drafts/actions retained."""
from alembic import op
from app.models.purchase_agent import PurchaseHistoryCache,PurchaseChatReceipt,PurchaseGraphCheckpoint,PurchaseGraphWrite
revision='b4u1v2w3x4y5'
down_revision='a3t0u1v2w3x4'
branch_labels=None
depends_on=None

def upgrade():
    for model in (PurchaseHistoryCache,PurchaseChatReceipt,PurchaseGraphCheckpoint,PurchaseGraphWrite):
        model.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():
    for model in (PurchaseGraphWrite,PurchaseGraphCheckpoint,PurchaseChatReceipt,PurchaseHistoryCache):
        model.__table__.drop(op.get_bind(),checkfirst=True)
