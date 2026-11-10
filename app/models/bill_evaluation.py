"""Append-only measurements; no raw invoice content or provider credentials."""
from datetime import datetime
from sqlalchemy import String,JSON,DateTime,ForeignKey
from sqlalchemy.orm import Mapped,mapped_column
from app.database.base import Base

class BillEvaluationMetric(Base):
    __tablename__='bill_evaluation_metrics'
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    organization_id:Mapped[str]=mapped_column(ForeignKey('organizations.id',ondelete='CASCADE'),index=True)
    user_id:Mapped[str]=mapped_column(String(100))
    document_id:Mapped[str|None]=mapped_column(ForeignKey('bill_documents.id',ondelete='CASCADE'),nullable=True,index=True)
    draft_id:Mapped[str|None]=mapped_column(ForeignKey('purchase_drafts.id',ondelete='CASCADE'),nullable=True,index=True)
    kind:Mapped[str]=mapped_column(String(32))
    data:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
