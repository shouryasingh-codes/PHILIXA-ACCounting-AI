from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_url: str
    redis_url: str
    api_key: str
    demo_api_key: str
    # Primary provider (legacy / single-provider path)
    ai_provider: str
    ai_model: str
    ai_api_key: str
    ai_base_url: str
    ai_timeout_seconds: int

    # Dual-provider fallback system
    ai_economy_provider: str
    ai_economy_model: str
    ai_review_provider: str
    ai_review_model: str
    # Per-provider API keys
    groq_api_key: str
    gemini_api_key: str
    # Notifications
    notification_mode: str
    smtp_hostname: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    smtp_from_address: str
    # WhatsApp Cloud API
    whatsapp_phone_number_id: str
    whatsapp_business_account_id: str
    whatsapp_access_token: str
    whatsapp_verify_token: str
    # Misc
    prompt_version: str
    raw_notes_max_chars: int
    client_name_max_chars: int
    commitment_description_max_chars: int
    client_auto_match_threshold: float
    client_auto_create_threshold: float
    due_date_threshold: float
    skip_startup_checks: bool
    embedding_model: str
    # MinIO Audio Storage (Day 9 & Day 10 Prep)
    minio_url: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_name: str
    retain_audio_files: bool
    
    # HuggingFace
    hf_token: str
    
    # Voice AI Architecture
    transcription_mode: str = "local"
    deepgram_api_key: str = ""
    sarvam_api_key: str = ""
    enable_audio_upload: bool = False
    voice_gateway_provider: str = "dual"
    vapi_api_key: str = ""
    vapi_webhook_secret: str = ""
    vapi_custom_llm_secret: str = ""
    vapi_custom_llm_url: str = "http://localhost:8000/api/v1/vapi/chat/completions"

    # Milestone 2 Auth & Security Additions
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None
    csrf_secret: str = ""
    allowed_origins: str | list[str] = ""
    app_env: str = "development"
    google_client_id: str | None = None
    philixa_env: str = "development"
    db_pool_size: int = 15
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_pre_ping: bool = True


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def validate_production_settings(settings: Settings) -> list[str]:
    """
    Evaluates settings for production safety.
    Returns a list of violation messages if any security check fails.
    """
    violations: list[str] = []
    # 1. JWT Secret Validation
    jwt_sec = getattr(settings, "jwt_secret", "") or getattr(settings, "api_key", "")
    if not jwt_sec or len(jwt_sec) < 32 or "demo" in jwt_sec or "secret-123" in jwt_sec:
        violations.append("JWT_SECRET must be at least 32 characters and cannot be a demo/default key.")

    # 2. CORS Wildcard Validation
    allowed_origins = getattr(settings, "allowed_origins", "")
    if allowed_origins == "*" or (isinstance(allowed_origins, (list, tuple)) and "*" in allowed_origins):
        violations.append("ALLOWED_ORIGINS cannot contain wildcard '*' in production.")

    # 3. SMTP Validation
    if not settings.smtp_username:
        violations.append("SMTP_USERNAME is required in production for secure email verification.")

    # 4. Cookie Secure Validation
    cookie_secure = getattr(settings, "cookie_secure", True)
    if not cookie_secure:
        violations.append("Cookies must have Secure=True in production mode.")

    return violations


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    env_name = os.getenv("PHILIXA_ENV", os.getenv("APP_ENV", "development")).lower().strip()
    return Settings(
        app_name=os.getenv("PHILIXA_APP_NAME", "PHILIXA 6.0 V1-MVP"),
        app_version=os.getenv("PHILIXA_APP_VERSION", "1.0.0"),
        database_url=os.getenv("PHILIXA_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/philixa"),
        redis_url=os.getenv("PHILIXA_REDIS_URL", "redis://localhost:6379/0"),
        api_key=os.getenv("PHILIXA_API_KEY", "super-secret-test-key-minimum-32-chars-long-12345"),
        demo_api_key=os.getenv("PHILIXA_DEMO_API_KEY", ""),
        # Primary provider
        ai_provider=os.getenv("PHILIXA_AI_PROVIDER", "groq").lower().strip(),
        ai_model=os.getenv("PHILIXA_AI_MODEL", "groq/openai/gpt-oss-20b").strip(),
        ai_api_key=os.getenv("PHILIXA_AI_API_KEY", "").strip(),
        ai_base_url=os.getenv("PHILIXA_AI_BASE_URL", "").strip(),
        ai_timeout_seconds=_env_int("PHILIXA_AI_TIMEOUT_SECONDS", 20),
        # Dual-provider fallback
        ai_economy_provider=os.getenv("PHILIXA_AI_ECONOMY_PROVIDER", "groq").lower().strip(),
        ai_economy_model=os.getenv("PHILIXA_AI_ECONOMY_MODEL", "groq/openai/gpt-oss-20b").strip(),
        ai_review_provider=os.getenv("PHILIXA_AI_REVIEW_PROVIDER", "gemini").lower().strip(),
        ai_review_model=os.getenv("PHILIXA_AI_REVIEW_MODEL", "gemini-2.5-flash").strip(),
        # Per-provider keys
        groq_api_key=os.getenv("PHILIXA_GROQ_API_KEY", "").strip(),
        gemini_api_key=os.getenv("PHILIXA_GEMINI_API_KEY", "").strip(),
        # Notifications
        notification_mode=os.getenv("PHILIXA_NOTIFICATION_MODE", "whatsapp").lower().strip(),
        smtp_hostname=os.getenv("PHILIXA_SMTP_HOSTNAME", "smtp.gmail.com").strip(),
        smtp_port=_env_int("PHILIXA_SMTP_PORT", 587),
        smtp_username=os.getenv("PHILIXA_SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("PHILIXA_SMTP_PASSWORD", "").strip(),
        smtp_use_tls=os.getenv("PHILIXA_SMTP_USE_TLS", "1") == "1",
        smtp_from_address=os.getenv("PHILIXA_SMTP_FROM_ADDRESS", "no-reply@philixa.com").strip(),
        # WhatsApp Cloud API
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        whatsapp_business_account_id=os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip(),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip(),
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip(),
        # Misc
        prompt_version=os.getenv("PHILIXA_PROMPT_VERSION", "v1-mvp-2026-06-19"),
        raw_notes_max_chars=_env_int("PHILIXA_RAW_NOTES_MAX_CHARS", 10000),
        client_name_max_chars=_env_int("PHILIXA_CLIENT_NAME_MAX_CHARS", 120),
        commitment_description_max_chars=_env_int(
            "PHILIXA_COMMITMENT_DESCRIPTION_MAX_CHARS", 500
        ),
        client_auto_match_threshold=_env_float(
            "PHILIXA_CLIENT_AUTO_MATCH_THRESHOLD", 0.85
        ),
        client_auto_create_threshold=_env_float(
            "PHILIXA_CLIENT_AUTO_CREATE_THRESHOLD", 0.80
        ),
        due_date_threshold=_env_float("PHILIXA_DUE_DATE_THRESHOLD", 0.75),
        skip_startup_checks=os.getenv("PHILIXA_SKIP_STARTUP_CHECKS", "0") == "1",
        embedding_model=os.getenv("PHILIXA_EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
        # MinIO Audio Storage
        minio_url=os.getenv("PHILIXA_MINIO_URL", "localhost:9000").strip(),
        minio_access_key=os.getenv("PHILIXA_MINIO_ACCESS_KEY", "philixa_minio").strip(),
        minio_secret_key=os.getenv("PHILIXA_MINIO_SECRET_KEY", "philixa_secret").strip(),
        minio_bucket_name=os.getenv("PHILIXA_MINIO_BUCKET_NAME", "philixa-audio").strip(),
        retain_audio_files=os.getenv("PHILIXA_RETAIN_AUDIO", "0") == "1",
        # HuggingFace Token
        hf_token=os.getenv("PHILIXA_HF_TOKEN", "").strip(),
        # Voice AI Architecture
        transcription_mode=os.getenv("PHILIXA_TRANSCRIPTION_MODE", "local").strip(),
        deepgram_api_key=os.getenv("PHILIXA_DEEPGRAM_API_KEY", "").strip(),
        sarvam_api_key=os.getenv("PHILIXA_SARVAM_API_KEY", "").strip(),
        enable_audio_upload=bool(_env_int("PHILIXA_ENABLE_AUDIO_UPLOAD", 0)),
        voice_gateway_provider=os.getenv("VOICE_GATEWAY_PROVIDER", os.getenv("PHILIXA_VOICE_GATEWAY_PROVIDER", "dual")).strip(),
        vapi_api_key=os.getenv("VAPI_API_KEY", os.getenv("PHILIXA_VAPI_API_KEY", "")).strip(),
        vapi_webhook_secret=os.getenv("VAPI_WEBHOOK_SECRET", os.getenv("PHILIXA_VAPI_WEBHOOK_SECRET", "")).strip(),
        vapi_custom_llm_secret=os.getenv("VAPI_CUSTOM_LLM_SECRET", os.getenv("PHILIXA_VAPI_CUSTOM_LLM_SECRET", "")).strip(),
        vapi_custom_llm_url=os.getenv("VAPI_CUSTOM_LLM_URL", os.getenv("PHILIXA_VAPI_CUSTOM_LLM_URL", "http://localhost:8000/api/v1/vapi/chat/completions")).strip(),
        # Milestone 2 Auth & Security Additions
        jwt_secret=os.getenv("PHILIXA_JWT_SECRET", os.getenv("JWT_SECRET", "super-secret-test-key-minimum-32-chars-long-12345")),
        jwt_algorithm=os.getenv("PHILIXA_JWT_ALGORITHM", "HS256"),
        jwt_access_token_expire_minutes=_env_int("PHILIXA_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15),
        jwt_refresh_token_expire_days=_env_int("PHILIXA_JWT_REFRESH_TOKEN_EXPIRE_DAYS", 30),
        cookie_secure=os.getenv("PHILIXA_COOKIE_SECURE", "0" if env_name != "production" else "1") == "1",
        cookie_samesite=os.getenv("PHILIXA_COOKIE_SAMESITE", "lax"),
        cookie_domain=os.getenv("PHILIXA_COOKIE_DOMAIN", None),
        csrf_secret=os.getenv("PHILIXA_CSRF_SECRET", os.getenv("CSRF_SECRET", "")),
        allowed_origins=os.getenv("PHILIXA_ALLOWED_ORIGINS", ""),
        app_env=env_name,
        philixa_env=env_name,
        google_client_id='401674766048-lofabuacl8s0f91siit3uh5glptfe7jt.apps.googleusercontent.com',
    )
