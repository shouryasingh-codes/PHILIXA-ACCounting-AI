"""Durable company policies, immutable decisions and conservative daily reservations."""
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, JSON, Integer, DateTime, Date, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

class PurchaseAutomationPolicy(Base):
    __tablename__='purchase_automation_policies'
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),primary_key=True)
    revision: Mapped[int]=mapped_column(Integer)
    actor_id: Mapped[str]=mapped_column(String(100))
    data: Mapped[dict]=mapped_column(JSON)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class PurchaseAutomationDecision(Base):
    __tablename__='purchase_automation_decisions'
    id: Mapped[str]=mapped_column(String(32),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    draft_id: Mapped[str]=mapped_column(ForeignKey('purchase_drafts.id',ondelete='CASCADE'),index=True)
    revision: Mapped[int]=mapped_column(Integer)
    policy_revision: Mapped[int]=mapped_column(Integer)
    decision: Mapped[str]=mapped_column(String(12))
    reasons: Mapped[list]=mapped_column(JSON)
    evidence: Mapped[dict]=mapped_column(JSON)
    action_id: Mapped[str|None]=mapped_column(String(32),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class PurchaseAutomationPolicyEvent(Base):
    __tablename__='purchase_automation_policy_events'
    id: Mapped[str]=mapped_column(String(32),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    revision: Mapped[int]=mapped_column(Integer)
    actor_id: Mapped[str]=mapped_column(String(100))
    data: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class PurchaseAutomationReservation(Base):
    __tablename__='purchase_automation_reservations'
    action_id: Mapped[str]=mapped_column(ForeignKey('tally_actions.token',ondelete='CASCADE'),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    policy_revision: Mapped[int]=mapped_column(Integer)
    day: Mapped[date]=mapped_column(Date,index=True)
    amount: Mapped[Decimal]=mapped_column(Numeric(20,2))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
