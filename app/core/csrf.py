from __future__ import annotations

import secrets
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

CSRF_EXEMPT_PATHS = {
    "/auth/register",
    "/api/v1/auth/register",
    "/auth/login",
    "/api/v1/auth/login",
    "/auth/google",
    "/api/v1/auth/google",
    "/auth/verify-email",
    "/api/v1/auth/verify-email",
    "/auth/forgot-password",
    "/api/v1/auth/forgot-password",
    "/auth/reset-password",
    "/api/v1/auth/reset-password",
    "/api/v1/webhooks/whatsapp",
    "/webhooks/whatsapp",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Device-only Bearer authentication; these routes never accept browser sessions.
    "/api/v1/integrations/tally/helper/jobs",
    "/api/v1/integrations/tally/helper/results",
    # Vapi Integration
    "/api/v1/vapi/chat/completions",
    "/api/v1/vapi/webhook",
    "/api/v1/vapi/assistants/inbound",
    "/vapi/chat/completions",
    "/vapi/webhook",
    "/vapi/assistants/inbound",
}


def generate_csrf_token() -> str:
    """Generates a cryptographically secure random CSRF token with high entropy."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(cookie_token: str | None, header_token: str | None) -> bool:
    """Constant-time double-submit cookie verification."""
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    """Helper to attach the CSRF cookie to a response."""
    settings = get_settings()
    if not token:
        token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,  # JavaScript must read this cookie to populate X-CSRF-Token header
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/",
    )
    return token


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware validating CSRF tokens on mutating requests using double-submit cookie pattern.
    Auto-seeds csrf_token cookie on safe requests if missing.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method.upper()

        # Check exemption
        is_exempt = (
            path in CSRF_EXEMPT_PATHS
            or path.startswith("/api/v1/vapi")
            or path.startswith("/vapi")
            or any(path.startswith(prefix) for prefix in ["/static", "/docs", "/redoc", "/openapi.json"])
        )

        if method not in SAFE_METHODS and not is_exempt:
            # Check if this request uses session cookies
            has_session_cookie = (
                "access_token" in request.cookies
                or "refresh_token" in request.cookies
                or "csrf_token" in request.cookies
            )
            if has_session_cookie:
                cookie_csrf = request.cookies.get("csrf_token")
                header_csrf = request.headers.get("X-CSRF-Token") or request.headers.get("x-csrf-token")

                if not verify_csrf_token(cookie_csrf, header_csrf):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token validation failed. Missing or invalid X-CSRF-Token header."},
                    )

        response = await call_next(request)

        # Seed CSRF cookie on GET requests if not present
        if method == "GET" and "csrf_token" not in request.cookies and not is_exempt:
            set_csrf_cookie(response)

        return response
