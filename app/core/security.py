from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Optional

from jose import JWTError, jwt
import bcrypt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """Hashes a password using bcrypt with cost factor >= 12."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a bcrypt hash."""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def hash_token(token: str) -> str:
    """Generates SHA-256 hex digest for opaque token indexing in database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generates a cryptographically secure random CSRF token with high entropy."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(cookie_token: str | None, header_token: str | None) -> bool:
    """Constant-time double-submit cookie verification."""
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)


def create_access_token(
    user_id: str,
    org_id: str,
    role: str = "member",
    session_id: str = "",
    expires_delta: timedelta | None = None,
    custom_claims: dict[str, Any] | None = None,
) -> str:
    """Creates a signed HS256 access JWT with standard claims."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expire = now + expires_delta

    payload: dict[str, Any] = {
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

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    org_id: str,
    role: str = "member",
    session_id: str = "",
    expires_delta: timedelta | None = None,
    custom_claims: dict[str, Any] | None = None,
) -> str:
    """Creates a signed HS256 refresh JWT with standard claims."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    expire = now + expires_delta

    payload: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "org_id": org_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_hex(16),
        "type": "refresh",
    }
    if custom_claims:
        payload.update(custom_claims)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_ws_ticket_token(
    user_id: str,
    org_id: str,
    role: str = "member",
    session_id: str = "",
    expires_delta: timedelta | None = None,
    custom_claims: dict[str, Any] | None = None,
) -> str:
    """Creates a short-lived (60s default) signed HS256 JWT ticket for WebSocket authentication."""
    if expires_delta is None:
        expires_delta = timedelta(seconds=60)
    claims = {"type": "ws_ticket"}
    if custom_claims:
        claims.update(custom_claims)
    return create_access_token(
        user_id=user_id,
        org_id=org_id,
        role=role,
        session_id=session_id,
        expires_delta=expires_delta,
        custom_claims=claims,
    )


def decode_jwt_token(
    token: str,
    secret_key: str | None = None,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """
    Decodes and validates a JWT token.
    Strictly verifies signature, expiration, and algorithm.
    """
    settings = get_settings()
    if secret_key is None:
        secret_key = settings.jwt_secret
    if algorithms is None:
        algorithms = [settings.jwt_algorithm]

    # Rejection of none algorithm
    if any(a.lower() == "none" for a in algorithms):
        raise JWTError("Insecure algorithm 'none' rejected")

    return jwt.decode(token, secret_key, algorithms=algorithms)
