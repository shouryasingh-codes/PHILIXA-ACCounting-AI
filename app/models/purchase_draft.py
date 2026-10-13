"""Durable purchase working copies, separate from write authorisation."""
from datetime import datetime
from sqlalchemy import String, Integer, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class PurchaseDraft(Base):
    __tablename__ = 'purchase_drafts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('tally_read_companies.id', ondelete='CASCADE'), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('bill_documents.id', ondelete='SET NULL'), index=True, nullable=True)
    content: Mapped[dict] = mapped_column(JSON)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    action_id: Mapped[str | None] = mapped_column(ForeignKey('tally_actions.token', ondelete='SET NULL'), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PurchaseDraftEvent(Base):
    __tablename__ = 'purchase_draft_events'
    __table_args__ = (UniqueConstraint('draft_id', 'revision', name='uq_purchase_draft_event_revision'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey('purchase_drafts.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON)
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
