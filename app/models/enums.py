from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceType(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class WorkspacePlan(str, Enum):
    FREE = "free"
    PRO = "pro"


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class MeetingStatus(str, Enum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    EXTRACTING = "extracting"
    PROCESSING = "processing"
    PROCESSED = "processed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    CLIENT_IDENTIFICATION_REQUIRED = "client_identification_required"
    FAILED = "failed"


class MeetingSourceType(str, Enum):
    PASTED_NOTE = "pasted_note"
    AUDIO_UPLOAD = "audio_upload"
    LIVE_BROWSER = "live_browser"


class CommitmentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
