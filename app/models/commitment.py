from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.meeting import Meeting
    from app.models.organization import Organization
    from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_description: Mapped[str] = mapped_column(String(520), nullable=False, index=True, default="")
    owner: Mapped[str] = mapped_column(String(80), default="RM", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_date_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    due_date_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    urgency_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_memberships.user_id", "organization_memberships.organization_id"],
            ondelete="CASCADE",
            name="fk_commitments_membership",
        ),
        Index("ix_commitments_org_user", "organization_id", "user_id"),
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="commitments")
    user: Mapped[User] = relationship("User", back_populates="commitments")
    client: Mapped[Client] = relationship("Client", back_populates="commitments")
    meeting_links: Mapped[list[CommitmentMeetingLink]] = relationship(
        "CommitmentMeetingLink", back_populates="commitment", cascade="all, delete-orphan", passive_deletes=True
    )


class CommitmentMeetingLink(Base):
    __tablename__ = "commitment_meeting_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    commitment_id: Mapped[int] = mapped_column(
        ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    commitment: Mapped[Commitment] = relationship("Commitment", back_populates="meeting_links")
    meeting: Mapped[Meeting] = relationship("Meeting", back_populates="commitment_links")
