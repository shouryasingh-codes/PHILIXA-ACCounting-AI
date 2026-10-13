from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.commitment import Commitment
    from app.models.follow_up_task import FollowUpTask
    from app.models.meeting import Meeting
    from app.models.organization import Organization
    from app.models.risk_signal import RiskSignal
    from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(140), nullable=False, index=True, default="")
    products_owned_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    products_interested_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    rolling_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    relationship_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_memberships.user_id", "organization_memberships.organization_id"],
            ondelete="CASCADE",
            name="fk_clients_membership",
        ),
        Index("ix_clients_org_user", "organization_id", "user_id"),
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="clients")
    user: Mapped[User] = relationship("User", back_populates="clients")
    meetings: Mapped[list[Meeting]] = relationship("Meeting", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)
    commitments: Mapped[list[Commitment]] = relationship("Commitment", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)
    risk_signals: Mapped[list[RiskSignal]] = relationship("RiskSignal", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)
    follow_up_tasks: Mapped[list[FollowUpTask]] = relationship("FollowUpTask", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)
