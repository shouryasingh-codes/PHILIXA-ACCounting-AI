from datetime import datetime, timezone
from sqlalchemy import DateTime, String
from sqlalchemy.orm import declarative_mixin, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@declarative_mixin
class TimestampMixin:
    """Automatically adds created_at and updated_at columns."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


@declarative_mixin
class TenantMixin:
    """Enforces strict tenant isolation by requiring organization_id and user_id."""
    organization_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
