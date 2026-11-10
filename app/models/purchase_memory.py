"""Explicit company memory and atomic invoice reservations."""
from datetime import datetime
from sqlalchemy import String, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

class PurchaseAlias(Base):
    __tablename__='purchase_aliases'
    __table_args__=(UniqueConstraint('company_id','kind','alias_key',name='uq_purchase_alias_company'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    kind: Mapped[str]=mapped_column(String(12))
    alias_key: Mapped[str]=mapped_column(String(200))
    source: Mapped[str]=mapped_column(String(200))
    target: Mapped[str]=mapped_column(String(200))
    master_identity: Mapped[str]=mapped_column(String(250))
    fingerprint: Mapped[str]=mapped_column(String(64))
    actor_id: Mapped[str]=mapped_column(String(100))
    draft_id: Mapped[str]=mapped_column(String(32))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class PurchaseInvoiceClaim(Base):
    __tablename__='purchase_invoice_claims'
    key: Mapped[str]=mapped_column(String(64),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    action_id: Mapped[str]=mapped_column(ForeignKey('tally_actions.token',ondelete='CASCADE'),unique=True)
    evidence: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
