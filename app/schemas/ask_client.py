from pydantic import BaseModel, Field

class AskClientRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user's query about the client.")

class AskClientResponse(BaseModel):
    answer: str
    source_meetings: list[int] = Field(default_factory=list, description="IDs of the meetings used to answer.")
