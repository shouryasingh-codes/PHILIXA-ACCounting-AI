"""Content-free provider quota ledger, shared across application workers."""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

class GroqQuotaRequest(Base):
    __tablename__='groq_quota_requests'
    __table_args__=(Index('ix_groq_quota_bucket_created','bucket','created_at'),)
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    bucket:Mapped[str]=mapped_column(String(64))
    task_id:Mapped[str|None]=mapped_column(String(32),nullable=True,index=True)
    revision:Mapped[int|None]=mapped_column(Integer,nullable=True)
    status:Mapped[str]=mapped_column(String(24))
    reserved_tokens:Mapped[int]=mapped_column(Integer)
    charged_tokens:Mapped[int]=mapped_column(Integer)
    metadata_json:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))

class GroqQuotaCooldown(Base):
    __tablename__='groq_quota_cooldowns'
    bucket:Mapped[str]=mapped_column(String(64),primary_key=True)
    state:Mapped[dict]=mapped_column(JSON)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
