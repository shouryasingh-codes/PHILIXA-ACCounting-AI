from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskSignal(BaseModel):
    """
    Represents a client concern, risk, or negative sentiment extracted from the meeting.
    """
    description: str = Field(
        ..., 
        min_length=3, 
        max_length=500,
        description="Clear, concise description of the risk or concern. DO NOT include business opportunities, loan requirements, or general needs here. Only include actual risks, complaints, delays, negative sentiments, or technical issues."
    )
    severity: SeverityLevel = Field(
        ..., 
        description="Severity level of the risk. Must be exactly one of the enum values."
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="AI confidence score between 0.0 and 1.0."
    )
    # Made Optional — Gemini aur local provider dono kabhi nahi bhejte isko
    source_evidence: Optional[str] = Field(
        default=None,
        description="The exact snippet or quote from the raw transcript that proves this risk exists."
    )


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CommitmentExtraction(BaseModel):
    """
    Represents a task, promise, or action item extracted from the meeting.
    """
    description: str = Field(
        ..., 
        min_length=3,
        description="Clean description of the promise or action item. DO NOT include the time, date, or temporal conditions (e.g., 'aaj shaam tak') in this description. Keep it completely clean (e.g., 'Send loan documentation')."
    )
    owner: str = Field(
        default="RM", 
        description="Who is responsible (e.g., 'RM', 'Client', 'Operations'). IMPORTANT: Do not rely solely on Speaker Tags (e.g. Speaker 1/2). Use conversational context (e.g. 'I will check my schedule' usually indicates the Client) to identify the true owner."
    )
    due_date: Optional[date] = Field(
        default=None, 
        description="CRITICAL: Convert ALL Hinglish/English relative times (like 'aaj shaam', 'aaj dopehar', 'monday', 'kal') into strict YYYY-MM-DD format using the provided meeting_date. NEVER output raw strings like 'aaj shaam' here. Use null only if completely unknown."
    )
    due_date_text: Optional[str] = Field(
        default=None,
        description="The raw text for the due date (e.g., 'next Friday', '3 din mai')."
    )
    due_date_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for the extracted due date."
    )
    urgency_level: UrgencyLevel = Field(
        default=UrgencyLevel.MEDIUM,
        description="Urgency of the commitment. Must match Enum."
    )
    status: str = Field(
        default="pending",
        description="Current status of the commitment."
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0, 
        le=1.0,
        description="AI confidence score."
    )


class ClientIdentificationStatus(str, Enum):
    IDENTIFIED = "identified"
    MULTIPLE_MATCHES = "multiple_matches"
    NOT_FOUND = "not_found"
    # Gemini system prompt "unknown" aur "ambiguous" return karta tha — ab supported hain
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class ClientIdentificationExtraction(BaseModel):
    """
    Identifies which client the meeting is about.
    """
    model_config = ConfigDict(extra="ignore")

    status: ClientIdentificationStatus = Field(
        ...,
        description="Whether a specific client was clearly identified, multiple possible matches exist, or none were found."
    )
    suggested_client_name: Optional[str] = Field(
        default=None,
        description="The exact name of the client mentioned in the meeting, if any."
    )
    suggested_client_email: Optional[str] = Field(
        default=None,
        description="The client's email address, only when explicitly mentioned."
    )
    suggested_client_whatsapp_phone: Optional[str] = Field(
        default=None,
        description="The client's WhatsApp number, only when explicitly mentioned."
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="AI confidence that it correctly identified the client context."
    )


class MeetingExtraction(BaseModel):
    """
    The master output schema for the LLM processing a meeting transcript.
    This is the ONLY contract the LLM is allowed to return.
    Extra fields from Gemini (e.g. matched_client_id) are silently ignored.
    
    1. You are an expert CRM assistant parsing meeting transcripts and raw voice notes.
    2. Your ONLY job is to extract actionable information based strictly on the provided text.
    3. If an explicit due date is not mentioned, calculate it if relative (e.g., "next week") or omit it.
    4. If a client name is mentioned, normalize it. If not, output "Unknown Client".
    5. IMPORTANT GUARDRAIL: Do not rely solely on Speaker Tags (e.g. Speaker 1, Speaker 2) if they are present. Use conversational context (e.g., "I will check my schedule" usually indicates the Client) to identify who made a commitment or stated a fact.
    """
    model_config = ConfigDict(extra="ignore")

    client_identification: ClientIdentificationExtraction = Field(
        ...,
        description="Details about which client the meeting belongs to."
    )
    meeting_summary: str = Field(
        ...,
        min_length=5,
        description="A concise summary of the entire meeting."
    )
    key_discussion_points: list[str] = Field(
        default_factory=list,
        description="Bullet points of the main topics discussed."
    )
    products_owned: list[str] = Field(
        default_factory=list,
        description="Financial products the client ALREADY owns or currently holds."
    )
    products_interested: list[str] = Field(
        default_factory=list,
        description="Financial products or services the client EXPRESSED INTEREST in, inquired about, or requested information on."
    )
    concerns: list[RiskSignal] = Field(
        default_factory=list,
        description="CRITICAL: Extract ANY AND ALL actual risks, complaints, delays, or negative sentiments raised, including technical issues or app login problems. DO NOT extract business opportunities or standard client requirements (like a need for a loan) here. Must be empty if none."
    )
    commitments: list[CommitmentExtraction] = Field(
        default_factory=list,
        description="CRITICAL: Extract EVERY SINGLE task, action item, or promise made, including minor follow-ups and support tickets. Must be empty if none."
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Simple string list of action items."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Any warnings or flags from the AI."
    )
