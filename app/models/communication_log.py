import enum
from sqlalchemy import String, Enum, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, TenantMixin
from app.models.notification import DeliveryStatus

class CommunicationChannel(str, enum.Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"

class CommunicationLog(Base, TimestampMixin, TenantMixin):
    __tablename__ = "communication_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    channel: Mapped[CommunicationChannel] = mapped_column(Enum(CommunicationChannel), nullable=False)
    message_content: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.PENDING)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    client = relationship("Client", backref="communication_logs")
