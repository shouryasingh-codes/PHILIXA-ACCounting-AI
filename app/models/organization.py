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
    from app.models.workspace_invite import WorkspaceInvite


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    workspace_type: Mapped[str] = mapped_column(String(20), default="company", nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        "OrganizationMembership", back_populates="organization", cascade="all, delete-orphan"
    )
    clients: Mapped[list[Client]] = relationship(
        "Client", back_populates="organization", cascade="all, delete-orphan"
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting", back_populates="organization", cascade="all, delete-orphan"
    )
    commitments: Mapped[list[Commitment]] = relationship(
        "Commitment", back_populates="organization", cascade="all, delete-orphan"
    )
    invites: Mapped[list[WorkspaceInvite]] = relationship(
        "WorkspaceInvite", back_populates="organization", cascade="all, delete-orphan"
    )
