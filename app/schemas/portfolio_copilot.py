from pydantic import BaseModel

class CopilotRequest(BaseModel):
    query: str
    chat_history: list[dict] = []

class CopilotResponse(BaseModel):
    answer: str
    source_type: str
    data: list | dict | None = None
