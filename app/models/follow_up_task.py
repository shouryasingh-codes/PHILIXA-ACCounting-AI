from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TenantMixin, TimestampMixin


class FollowUpTask(Base, TenantMixin, TimestampMixin):
    __tablename__ = "follow_up_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    commitment_id: Mapped[int | None] = mapped_column(ForeignKey("commitments.id", ondelete="CASCADE"), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Classification fields
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_due_today: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    client = relationship("Client", foreign_keys=[client_id], back_populates="follow_up_tasks")
    commitment = relationship("Commitment", foreign_keys=[commitment_id])
