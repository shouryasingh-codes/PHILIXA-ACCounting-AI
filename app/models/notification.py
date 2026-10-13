import enum
from sqlalchemy import String, Boolean, Enum, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.database.base import Base
from app.database.mixins import TimestampMixin, TenantMixin

class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"
    READ = "read"

class NotificationPreference(Base, TimestampMixin, TenantMixin):
    __tablename__ = "notification_preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String, nullable=True)
    is_opted_in: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_start: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g., "22:00"
    quiet_hours_end: Mapped[str | None] = mapped_column(String, nullable=True)    # e.g., "08:00"
    timezone: Mapped[str | None] = mapped_column(String, nullable=True, default="UTC")
    
    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery", 
        back_populates="preference",
        cascade="all, delete-orphan"
    )

class NotificationDelivery(Base, TimestampMixin, TenantMixin):
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    preference_id: Mapped[str] = mapped_column(String, ForeignKey("notification_preferences.id"), index=True)
    
    channel: Mapped[str] = mapped_column(String, default="whatsapp")
    message_content: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.PENDING)
    
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_payload: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

    preference: Mapped["NotificationPreference"] = relationship(
        "NotificationPreference",
        back_populates="deliveries"
    )
