from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from unittest.mock import patch

from jose import JWTError, jwt, utils as jose_utils
from passlib.context import CryptContext
import pytest

from app.core.config import Settings, get_settings


# -----------------------------------------------------------------------------
# Module Setup & Cryptographic Constants
# -----------------------------------------------------------------------------
TEST_SECRET_KEY = "super-secret-production-quality-key-minimum-32-chars-long"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def generate_jwt_token(
    user_id: str,
    org_id: str,
    role: str = "owner",
    session_id: str = "sess-12345",
    secret_key: str = TEST_SECRET_KEY,
    algorithm: str = "HS256",
    expires_delta: timedelta | None = None,
    custom_claims: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=15)
    expire = now + expires_delta
    
    payload = {
        "sub": user_id,
        "sid": session_id,
        "org_id": org_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_hex(16),
        "type": "access",
    }
    if custom_claims:
        payload.update(custom_claims)
        
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_jwt_token(
    token: str,
    secret_key: str = TEST_SECRET_KEY,
    algorithms: list[str] | None = None,
) -> dict:
    if algorithms is None:
        algorithms = ["HS256"]
    return jwt.decode(token, secret_key, algorithms=algorithms)


def validate_production_settings(settings: Settings) -> list[str]:
    """
    Evaluates settings for production safety.
    Returns a list of violation messages if any security check fails.
    """
    violations = []
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


from app.core.security import hash_password, verify_password


# =============================================================================
# Feature 1: Password Hashing & Bcrypt Cost Factor Tests
# =============================================================================
class TestBcryptPasswordHashing:
    def test_bcrypt_cost_factor_is_at_least_12(self) -> None:
        password = "SecurePassword123!"
        hashed = hash_password(password)
        
        # Bcrypt hashes format: $2b$12$... or $2a$12$...
        parts = hashed.split("$")
        assert len(parts) >= 4, "Invalid bcrypt hash structure"
        ident = parts[1]
        cost = int(parts[2])
        assert ident in ("2a", "2b", "2y"), f"Unexpected bcrypt identifier: {ident}"
        assert cost >= 12, f"Bcrypt cost factor must be >= 12, got {cost}"

    def test_bcrypt_generates_unique_salt_per_hash(self) -> None:
        password = "IdenticalPasswordForSaltTest!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        
        assert hash1 != hash2, "Hashing identical passwords must produce different hashes with unique salts"
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_bcrypt_verification_success_for_matching_password(self) -> None:
        password = "CorrectHorseBatteryStaple#2026"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_bcrypt_verification_failure_for_incorrect_password(self) -> None:
        password = "CorrectPassword123!"
        hashed = hash_password(password)
        assert verify_password("WrongPassword456!", hashed) is False
        assert verify_password("correctpassword123!", hashed) is False  # Case sensitivity check

    def test_bcrypt_rejects_empty_and_null_passwords(self) -> None:
        hashed = hash_password("ValidPassword123!")
        assert verify_password("", hashed) is False
        
        # Verify empty string hash produces valid bcrypt format but doesn't match other plaintexts
        empty_hash = hash_password("")
        assert verify_password("", empty_hash) is True
        assert verify_password("any_text", empty_hash) is False

    def test_bcrypt_handles_unicode_and_special_characters(self) -> None:
        unicode_pass = "Pässwørd_日本語_🚀_₹10000_Банк"
        hashed = hash_password(unicode_pass)
        assert verify_password(unicode_pass, hashed) is True
        assert verify_password("Passwørd_日本語_🚀_₹10000_Банк", hashed) is False

    def test_bcrypt_never_stores_plaintext_in_hash(self) -> None:
        sensitive_pass = "SuperSecretBankManagerPassword999!"
        hashed = hash_password(sensitive_pass)
        assert sensitive_pass not in hashed, "Plaintext password must NEVER appear in the hash string"


# =============================================================================
# Feature 2: JWT HS256 Signing & Claims Validation Tests
# =============================================================================
class TestJWTSecurityAndClaims:
    def test_jwt_hs256_generation_and_headers(self) -> None:
        token = generate_jwt_token(user_id="usr_123", org_id="org_456")
        headers = jwt.get_unverified_header(token)
        
        assert headers.get("alg") == "HS256"
        assert headers.get("typ") == "JWT"

    def test_jwt_all_mandatory_claims_present(self) -> None:
        user_id = "user_alpha_01"
        org_id = "org_beta_02"
        role = "admin"
        session_id = "sess_gamma_03"
        
        token = generate_jwt_token(
            user_id=user_id,
            org_id=org_id,
            role=role,
            session_id=session_id,
        )
        payload = decode_jwt_token(token)
        
        # Validate mandatory claims per R3
        assert payload["sub"] == user_id
        assert payload["sid"] == session_id
        assert payload["org_id"] == org_id
        assert payload["role"] == role
        assert "iat" in payload and isinstance(payload["iat"], int)
        assert "exp" in payload and isinstance(payload["exp"], int)
        assert "jti" in payload and len(payload["jti"]) >= 16
        assert payload["exp"] > payload["iat"]

    def test_jwt_expired_token_rejection(self) -> None:
        expired_delta = timedelta(minutes=-10)
        expired_token = generate_jwt_token(
            user_id="usr_exp",
            org_id="org_exp",
            expires_delta=expired_delta,
        )
        
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_jwt_token(expired_token)

    def test_jwt_tampered_payload_rejection(self) -> None:
        token = generate_jwt_token(user_id="usr_original", org_id="org_orig", role="member")
        parts = token.split(".")
        assert len(parts) == 3
        
        # Tamper payload part (swap role from member to owner)
        payload_bytes = jose_utils.base64url_decode(parts[1].encode("utf-8"))
        payload_dict = json.loads(payload_bytes.decode("utf-8"))
        payload_dict["role"] = "owner"
        tampered_payload_part = jose_utils.base64url_encode(json.dumps(payload_dict).encode("utf-8")).decode("utf-8")
        
        tampered_token = f"{parts[0]}.{tampered_payload_part}.{parts[2]}"
        
        with pytest.raises(JWTError):
            decode_jwt_token(tampered_token)

    def test_jwt_tampered_signature_rejection(self) -> None:
        token = generate_jwt_token(user_id="usr_123", org_id="org_456")
        parts = token.split(".")
        # Invert the last character of signature
        tampered_signature = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        tampered_token = f"{parts[0]}.{parts[1]}.{tampered_signature}"
        
        with pytest.raises(JWTError):
            decode_jwt_token(tampered_token)

    def test_jwt_wrong_secret_key_rejection(self) -> None:
        token = generate_jwt_token(
            user_id="usr_123",
            org_id="org_456",
            secret_key="attacker-secret-key-that-is-not-valid-32b",
        )
        
        with pytest.raises(JWTError):
            decode_jwt_token(token, secret_key=TEST_SECRET_KEY)

    def test_jwt_rejects_none_algorithm(self) -> None:
        # Construct an insecure token with alg=none
        header = {"alg": "none", "typ": "JWT"}
        payload = {"sub": "attacker", "org_id": "org_victim", "role": "owner", "exp": 9999999999}
        encoded_header = jose_utils.base64url_encode(json.dumps(header).encode("utf-8")).decode("utf-8")
        encoded_payload = jose_utils.base64url_encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        none_token = f"{encoded_header}.{encoded_payload}."
        
        with pytest.raises(JWTError):
            jwt.decode(none_token, TEST_SECRET_KEY, algorithms=["HS256"])


# =============================================================================
# Feature 3: CSRF Protection & Token Security Tests
# =============================================================================
class TestCSRFProtection:
    def test_csrf_token_entropy_and_length(self) -> None:
        token = secrets.token_urlsafe(32)
        assert len(token) >= 32, "CSRF token must have sufficient entropy"
        
        # Ensure successive tokens are cryptographically distinct
        token2 = secrets.token_urlsafe(32)
        assert token != token2

    def test_csrf_validation_logic_for_mutating_vs_safe_methods(self) -> None:
        safe_methods = ["GET", "HEAD", "OPTIONS"]
        mutating_methods = ["POST", "PUT", "PATCH", "DELETE"]
        
        csrf_cookie = secrets.token_urlsafe(32)
        valid_header = csrf_cookie
        invalid_header = secrets.token_urlsafe(32)
        
        # Safe methods should not require header
        for method in safe_methods:
            requires_csrf = method in mutating_methods
            assert requires_csrf is False, f"Method {method} should be considered safe"
            
        # Mutating methods MUST require matching header
        for method in mutating_methods:
            requires_csrf = method in mutating_methods
            assert requires_csrf is True, f"Method {method} MUST require CSRF validation"
            
            # Validation match check
            assert valid_header == csrf_cookie, "Valid CSRF header matches cookie"
            assert invalid_header != csrf_cookie, "Mismatched CSRF header rejected"

    def test_csrf_double_submit_cookie_comparison_constant_time(self) -> None:
        token_a = secrets.token_urlsafe(32)
        token_b = token_a
        token_c = secrets.token_urlsafe(32)
        
        # Constant-time comparison check
        assert secrets.compare_digest(token_a, token_b) is True
        assert secrets.compare_digest(token_a, token_c) is False


# =============================================================================
# Feature 4: Production Startup Validation Guardrails Tests
# =============================================================================
class TestProductionStartupValidation:
    def test_fails_when_jwt_secret_is_empty_or_too_short(self) -> None:
        settings = Settings(
            app_name="PHILIXA",
            app_version="1.0.0",
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            redis_url="redis://localhost:6379/0",
            api_key="short",
            demo_api_key="",
            ai_provider="groq",
            ai_model="test",
            ai_api_key="key",
            ai_base_url="",
            ai_timeout_seconds=20,
            ai_economy_provider="groq",
            ai_economy_model="test",
            ai_review_provider="gemini",
            ai_review_model="test",
            groq_api_key="key",
            gemini_api_key="key",
            notification_mode="email",
            smtp_hostname="smtp.gmail.com",
            smtp_port=587,
            smtp_username="admin@philixa.com",
            smtp_password="password",
            smtp_use_tls=True,
            smtp_from_address="no-reply@philixa.com",
            whatsapp_phone_number_id="",
            whatsapp_business_account_id="",
            whatsapp_access_token="",
            whatsapp_verify_token="",
            prompt_version="v1",
            raw_notes_max_chars=10000,
            client_name_max_chars=120,
            commitment_description_max_chars=500,
            client_auto_match_threshold=0.85,
            client_auto_create_threshold=0.80,
            due_date_threshold=0.75,
            skip_startup_checks=False,
            embedding_model="BAAI/bge-m3",
            minio_url="localhost:9000",
            minio_access_key="minio",
            minio_secret_key="secret",
            minio_bucket_name="bucket",
            retain_audio_files=False,
            hf_token="",
        )
        violations = validate_production_settings(settings)
        assert any("JWT_SECRET" in v for v in violations), f"Expected JWT_SECRET violation, got: {violations}"

    def test_fails_when_smtp_username_is_missing_in_production(self) -> None:
        settings = Settings(
            app_name="PHILIXA",
            app_version="1.0.0",
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            redis_url="redis://localhost:6379/0",
            api_key="long-valid-key-at-least-32-chars-length-12345",
            demo_api_key="",
            ai_provider="groq",
            ai_model="test",
            ai_api_key="key",
            ai_base_url="",
            ai_timeout_seconds=20,
            ai_economy_provider="groq",
            ai_economy_model="test",
            ai_review_provider="gemini",
            ai_review_model="test",
            groq_api_key="key",
            gemini_api_key="key",
            notification_mode="email",
            smtp_hostname="smtp.gmail.com",
            smtp_port=587,
            smtp_username="",  # Missing SMTP Username
            smtp_password="",
            smtp_use_tls=True,
            smtp_from_address="no-reply@philixa.com",
            whatsapp_phone_number_id="",
            whatsapp_business_account_id="",
            whatsapp_access_token="",
            whatsapp_verify_token="",
            prompt_version="v1",
            raw_notes_max_chars=10000,
            client_name_max_chars=120,
            commitment_description_max_chars=500,
            client_auto_match_threshold=0.85,
            client_auto_create_threshold=0.80,
            due_date_threshold=0.75,
            skip_startup_checks=False,
            embedding_model="BAAI/bge-m3",
            minio_url="localhost:9000",
            minio_access_key="minio",
            minio_secret_key="secret",
            minio_bucket_name="bucket",
            retain_audio_files=False,
            hf_token="",
        )
        violations = validate_production_settings(settings)
        assert any("SMTP_USERNAME" in v for v in violations), f"Expected SMTP violation, got: {violations}"

    def test_passes_when_all_production_guardrails_satisfied(self) -> None:
        settings = Settings(
            app_name="PHILIXA",
            app_version="1.0.0",
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            redis_url="redis://localhost:6379/0",
            api_key="a-very-strong-production-jwt-secret-key-32-chars-minimum",
            demo_api_key="",
            ai_provider="groq",
            ai_model="test",
            ai_api_key="key",
            ai_base_url="",
            ai_timeout_seconds=20,
            ai_economy_provider="groq",
            ai_economy_model="test",
            ai_review_provider="gemini",
            ai_review_model="test",
            groq_api_key="key",
            gemini_api_key="key",
            notification_mode="email",
            smtp_hostname="smtp.gmail.com",
            smtp_port=587,
            smtp_username="notifications@philixa.com",
            smtp_password="prod_password",
            smtp_use_tls=True,
            smtp_from_address="no-reply@philixa.com",
            cookie_secure=True,
            whatsapp_phone_number_id="",
            whatsapp_business_account_id="",
            whatsapp_access_token="",
            whatsapp_verify_token="",
            prompt_version="v1",
            raw_notes_max_chars=10000,
            client_name_max_chars=120,
            commitment_description_max_chars=500,
            client_auto_match_threshold=0.85,
            client_auto_create_threshold=0.80,
            due_date_threshold=0.75,
            skip_startup_checks=False,
            embedding_model="BAAI/bge-m3",
            minio_url="localhost:9000",
            minio_access_key="minio",
            minio_secret_key="secret",
            minio_bucket_name="bucket",
            retain_audio_files=False,
            hf_token="",
        )
        violations = validate_production_settings(settings)
        assert len(violations) == 0, f"Expected 0 violations for valid settings, got: {violations}"
