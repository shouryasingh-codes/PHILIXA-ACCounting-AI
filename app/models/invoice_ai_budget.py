"""Conservative paid-call debits; deletion of source/workspace must not refund spend."""
from datetime import date,datetime
from decimal import Decimal
from sqlalchemy import String,Integer,Date,DateTime,Numeric,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from app.database.base import Base


class InvoiceAIBudgetDebit(Base):
    __tablename__='invoice_ai_budget_debits'
    __table_args__=(UniqueConstraint('document_id','generation','attempt',name='uq_invoice_ai_attempt'),)
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    organization_id:Mapped[str]=mapped_column(String(100),index=True)
    document_id:Mapped[str]=mapped_column(String(32),index=True)
    generation:Mapped[int]=mapped_column(Integer)
    attempt:Mapped[int]=mapped_column(Integer)
    day:Mapped[date]=mapped_column(Date,index=True)
    reserved_usd:Mapped[Decimal]=mapped_column(Numeric(20,8))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
