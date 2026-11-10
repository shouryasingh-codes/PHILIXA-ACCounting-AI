"""Scoped routing journal. Never a source of posting authority."""
from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class BusinessRoute(Base):
    __tablename__ = 'business_routes'
    __table_args__ = (UniqueConstraint('organization_id','user_id','request_id'),)
    id: Mapped[str] = mapped_column(String(32),primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100),index=True)
    user_id: Mapped[str] = mapped_column(String(100),index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32),nullable=True,index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    version: Mapped[str] = mapped_column(String(40))
    context_revision: Mapped[int | None] = mapped_column(Integer,nullable=True)
    context_data: Mapped[dict] = mapped_column(JSON,default=dict)
    decision: Mapped[dict] = mapped_column(JSON,default=dict)
    result: Mapped[dict] = mapped_column(JSON,default=dict)
    telemetry: Mapped[dict] = mapped_column(JSON,default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
