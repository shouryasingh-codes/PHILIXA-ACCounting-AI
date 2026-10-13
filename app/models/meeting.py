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
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database.base import Base
from app.models.enums import MeetingSourceType

if TYPE_CHECKING:
    from app.models.ai_extraction_log import AIExtractionLog
    from app.models.client import Client
    from app.models.commitment import CommitmentMeetingLink
    from app.models.organization import Organization
    from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    raw_notes: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    key_discussion_points_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    concerns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    audio_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_file_path = synonym("audio_path")
    audio_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    suggested_client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_client_whatsapp_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(40), default=MeetingSourceType.PASTED_NOTE.value, nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), default="processed", nullable=False)
    client_identification_status: Mapped[str] = mapped_column(
        String(60), default="identified", nullable=False
    )
    client_identification_confidence: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_memberships.user_id", "organization_memberships.organization_id"],
            ondelete="CASCADE",
            name="fk_meetings_membership",
        ),
        Index("ix_meetings_org_user", "organization_id", "user_id"),
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="meetings")
    user: Mapped[User] = relationship("User", back_populates="meetings")
    client: Mapped[Client | None] = relationship("Client", back_populates="meetings")
    commitment_links: Mapped[list[CommitmentMeetingLink]] = relationship(
        "CommitmentMeetingLink", back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )
    ai_logs: Mapped[list[AIExtractionLog]] = relationship(
        "AIExtractionLog", back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )
