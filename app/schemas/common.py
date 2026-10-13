from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "app_version": "1.0.0",
                "database": "ok",
            }
        }
    )

    status: str
    app_version: str
    database: str


class ConcernRead(BaseModel):
    description: str
    severity: str
    confidence: float


class CommitmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    description: str
    owner: str
    due_date: date | None
    due_date_text: str | None
    due_date_confidence: float
    urgency_level: str
    status: str
    extraction_confidence: float
    created_at: datetime
    updated_at: datetime


class ExtractedCommitmentRead(BaseModel):
    description: str
    owner: str
    due_date: date | None
    due_date_text: str | None
    due_date_confidence: float
    urgency_level: str
    status: str
    confidence: float


class ClientIdentificationRead(BaseModel):
    status: str
    matched_client_id: int | None
    suggested_client_name: str | None
    suggested_client_email: str | None = None
    suggested_client_whatsapp_phone: str | None = None
    confidence: float
    requires_confirmation: bool


class MeetingExtractionRead(BaseModel):
    client_identification: ClientIdentificationRead
    meeting_summary: str
    key_discussion_points: list[str]
    products_owned: list[str]
    products_interested: list[str] = []
    concerns: list[ConcernRead]
    commitments: list[ExtractedCommitmentRead]
    action_items: list[str]
    warnings: list[str]
