from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings
from app.models.enums import MeetingSourceType
from app.schemas.client import MeetingRead
from app.schemas.common import CommitmentRead, MeetingExtractionRead


class MeetingNoteProcessRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_notes": "Met Rajesh Sharma today. Interested in business loan. Concerned about processing time. Promised documents by Friday. Asked for approval status update in 3 days.",
                "meeting_date": "2026-06-19",
                "known_client_id": 1,
            }
        }
    )

    raw_notes: str = Field(..., min_length=1)
    meeting_date: date | None = None
    known_client_id: int | None = Field(default=None, gt=0)
    source_type: MeetingSourceType = Field(default=MeetingSourceType.PASTED_NOTE)

    @field_validator("raw_notes")
    @classmethod
    def validate_raw_notes(cls, value: str) -> str:
        settings = get_settings()
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_notes cannot be empty.")
        if len(stripped) > settings.raw_notes_max_chars:
            raise ValueError(
                f"raw_notes cannot exceed {settings.raw_notes_max_chars} characters."
            )
        return stripped


class ClientConfirmationRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"client_id": 1},
                {"new_client_name": "Rajesh Sharma"},
            ]
        }
    )

    client_id: int | None = Field(default=None, gt=0)
    new_client_name: str | None = Field(default=None, min_length=1, max_length=120)
    new_client_email: str | None = Field(default=None, max_length=255)
    new_client_whatsapp_phone: str | None = Field(default=None, max_length=20)

    @field_validator("new_client_name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class MeetingNoteProcessResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "meeting_id": 1,
                "client_status": "identified",
                "client_id": 1,
                "requires_client_confirmation": False,
                "meeting_summary": "Rajesh Sharma discussed interest in a business loan and raised concern about processing time.",
                "meeting": {
                    "id": 1,
                    "client_id": 1,
                    "raw_notes": "Met Rajesh Sharma today. Interested in business loan. Concerned about processing time. Promised documents by Friday.",
                    "meeting_date": "2026-06-19",
                    "summary": "Rajesh Sharma discussed interest in a business loan and raised concern about processing time.",
                    "key_discussion_points": [
                        "Interested in business loan",
                        "Concerned about loan processing time",
                    ],
                    "products_owned": ["Business Loan"],
                    "concerns": [
                        {
                            "description": "Processing time concern",
                            "severity": "medium",
                            "confidence": 0.86,
                        }
                    ],
                    "status": "processed",
                    "client_identification_status": "identified",
                    "client_identification_confidence": 0.92,
                },
                "extraction": {
                    "client_identification": {
                        "status": "identified",
                        "matched_client_id": 1,
                        "suggested_client_name": "Rajesh Sharma",
                        "confidence": 0.92,
                        "requires_confirmation": False,
                    },
                    "meeting_summary": "Rajesh Sharma discussed interest in a business loan and raised concern about processing time.",
                    "key_discussion_points": [
                        "Interested in business loan",
                        "Concerned about loan processing time",
                    ],
                    "concerns": [
                        {
                            "description": "Processing time concern",
                            "severity": "medium",
                            "confidence": 0.86,
                        }
                    ],
                    "commitments": [
                        {
                            "description": "Send documents",
                            "owner": "RM",
                            "due_date": "2026-06-26",
                            "due_date_text": "by Friday",
                            "due_date_confidence": 0.82,
                            "urgency_level": "medium",
                            "status": "pending",
                            "confidence": 0.9,
                        }
                    ],
                    "action_items": ["Send documents"],
                    "warnings": [],
                },
                "commitments_created": [],
                "commitments_updated": [],
                "pending_commitments": [],
                "warnings": [],
            }
        }
    )

    meeting_id: int
    client_status: str
    client_id: int | None
    requires_client_confirmation: bool
    meeting_summary: str
    meeting: MeetingRead
    extraction: MeetingExtractionRead
    commitments_created: list[CommitmentRead]
    commitments_updated: list[CommitmentRead]
    pending_commitments: list[CommitmentRead]
    warnings: list[str]


class ClientConfirmationResponse(MeetingNoteProcessResponse):
    pass
