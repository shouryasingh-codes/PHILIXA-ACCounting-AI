from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin
from app.models.enums import MembershipStatus, UserRole

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationMembership(Base, TimestampMixin):
    __tablename__ = "organization_memberships"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=UserRole.MEMBER.value, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=MembershipStatus.ACTIVE.value, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], back_populates="memberships")
    organization: Mapped[Organization] = relationship(
        "Organization", foreign_keys=[organization_id], back_populates="memberships"
    )
    inviter: Mapped[User | None] = relationship("User", foreign_keys=[invited_by])
