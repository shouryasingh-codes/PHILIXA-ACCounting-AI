from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.notification import DeliveryStatus

class NotificationPreferenceBase(BaseModel):
    whatsapp_number: Optional[str] = None
    is_opted_in: bool = True
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: Optional[str] = Field(default="UTC")

class NotificationPreferenceCreate(NotificationPreferenceBase):
    id: str

class NotificationPreferenceUpdate(NotificationPreferenceBase):
    pass

class NotificationPreferenceResponse(NotificationPreferenceBase):
    id: str
    organization_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationDeliveryBase(BaseModel):
    channel: str = "whatsapp"
    message_content: str
    status: DeliveryStatus = DeliveryStatus.PENDING
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata_payload: Optional[Dict[str, Any]] = None

class NotificationDeliveryCreate(NotificationDeliveryBase):
    id: str
    preference_id: str

class NotificationDeliveryUpdate(BaseModel):
    status: Optional[DeliveryStatus] = None
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata_payload: Optional[Dict[str, Any]] = None

class NotificationDeliveryResponse(NotificationDeliveryBase):
    id: str
    preference_id: str
    organization_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
