from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TenantMixin, TimestampMixin


class RiskSignal(Base, TenantMixin, TimestampMixin):
    __tablename__ = "risk_signals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    severity_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Classification fields
    is_high_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    client = relationship("Client", foreign_keys=[client_id], back_populates="risk_signals")
    meeting = relationship("Meeting", foreign_keys=[meeting_id])
