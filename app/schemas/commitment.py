from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import CommitmentRead


class CommitmentStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(pending|completed)$")


class CommitmentListResponse(BaseModel):
    commitments: list[CommitmentRead]


class CommitmentStatusUpdateResponse(BaseModel):
    commitment: CommitmentRead
