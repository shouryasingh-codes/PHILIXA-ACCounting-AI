"""Durable, company-scoped read evidence and serializable agent checkpoints."""
from datetime import datetime
from sqlalchemy import String, JSON, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class PurchaseHistoryCache(Base):
    __tablename__='purchase_history_cache'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    organization_id:Mapped[str]=mapped_column(ForeignKey('organizations.id',ondelete='CASCADE'),index=True)
    company_id:Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    draft_id:Mapped[str]=mapped_column(ForeignKey('purchase_drafts.id',ondelete='CASCADE'))
    user_id:Mapped[str]=mapped_column(String(100))
    query:Mapped[dict]=mapped_column(JSON)
    binding:Mapped[dict]=mapped_column(JSON)
    data:Mapped[dict]=mapped_column(JSON,default=dict)
    status:Mapped[str]=mapped_column(String(24),default='queued',index=True)
    error:Mapped[str|None]=mapped_column(String(250),nullable=True)
    generation:Mapped[str|None]=mapped_column(String(32),nullable=True)
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    lease_token:Mapped[str|None]=mapped_column(String(32),nullable=True)
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    collected_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))


class PurchaseChatReceipt(Base):
    __tablename__='purchase_chat_receipts'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    draft_id:Mapped[str]=mapped_column(ForeignKey('purchase_drafts.id',ondelete='CASCADE'),index=True)
    user_id:Mapped[str]=mapped_column(String(100))
    request_hash:Mapped[str]=mapped_column(String(64))
    response:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))


class PurchaseGraphCheckpoint(Base):
    __tablename__='purchase_graph_checkpoints'
    thread_id:Mapped[str]=mapped_column(String(200),primary_key=True)
    namespace:Mapped[str]=mapped_column(String(200),primary_key=True)
    checkpoint_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    parent_id:Mapped[str|None]=mapped_column(String(64),nullable=True)
    data:Mapped[dict]=mapped_column(JSON)
    metadata_:Mapped[dict]=mapped_column('metadata',JSON)


class PurchaseGraphWrite(Base):
    __tablename__='purchase_graph_writes'
    thread_id:Mapped[str]=mapped_column(String(200),primary_key=True)
    namespace:Mapped[str]=mapped_column(String(200),primary_key=True)
    checkpoint_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    task_id:Mapped[str]=mapped_column(String(200),primary_key=True)
    index:Mapped[int]=mapped_column(Integer,primary_key=True)
    channel:Mapped[str]=mapped_column(String(200))
    data:Mapped[dict]=mapped_column(JSON)
