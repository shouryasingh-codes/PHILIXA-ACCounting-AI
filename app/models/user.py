from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.commitment import Commitment
    from app.models.meeting import Meeting
    from app.models.organization_membership import OrganizationMembership
    from app.models.user_session import UserSession


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        "OrganizationMembership",
        foreign_keys="[OrganizationMembership.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    clients: Mapped[list[Client]] = relationship(
        "Client", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    commitments: Mapped[list[Commitment]] = relationship(
        "Commitment", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
