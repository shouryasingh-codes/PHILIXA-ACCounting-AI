from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from jose import jwt
from passlib.context import CryptContext
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app

# Import all models to ensure complete metadata registration
from app.models import (  # noqa: F401
    AIExtractionLog,
    Client,
    Commitment,
    CommitmentMeetingLink,
    FollowUpTask,
    Meeting,
    MeetingEvidence,
    NotificationDelivery,
    NotificationPreference,
    Organization,
    RiskSignal,
    User,
)
try:
    from app.models.organization_membership import OrganizationMembership
    from app.models.user_session import UserSession
    from app.models.auth_tokens import EmailVerificationToken, PasswordResetToken
    from app.models.workspace_invite import WorkspaceInvite
except ImportError:
    # Fallback placeholders if models are dynamically loaded
    OrganizationMembership = None
    UserSession = None
    EmailVerificationToken = None
    PasswordResetToken = None
    WorkspaceInvite = None


# -----------------------------------------------------------------------------
# Security & Token Helpers for Fixtures
# -----------------------------------------------------------------------------
from app.core.security import hash_password, verify_password
TEST_JWT_SECRET = "super-secret-test-key-minimum-32-chars-long-12345"
TEST_JWT_ALGORITHM = "HS256"


def create_test_token(
    user_id: str,
    org_id: str,
    role: str = "owner",
    session_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    token_type: str = "access",
) -> str:
    if session_id is None:
        session_id = f"test-sess-{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=15) if token_type == "access" else timedelta(days=30)
    expire = now + expires_delta
    payload = {
        "sub": user_id,
        "sid": session_id,
        "org_id": org_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_hex(16),
        "type": token_type,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def generate_test_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# -----------------------------------------------------------------------------
# Mock SMTP Fixture
# -----------------------------------------------------------------------------
class MockSMTPSink:
    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []

    def send(self, recipient: str, subject: str, body: str, token: Optional[str] = None, **kwargs: Any) -> None:
        self.sent_messages.append({
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "token": token,
            "timestamp": datetime.now(timezone.utc),
            "extra": kwargs,
        })

    def clear(self) -> None:
        self.sent_messages.clear()

    def get_latest_token_for(self, recipient: str) -> Optional[str]:
        for msg in reversed(self.sent_messages):
            if msg["recipient"] == recipient:
                if msg.get("token"):
                    return msg["token"]
                # Try to extract token from body
                import re
                match = re.search(r"token=([a-zA-Z0-9_\-\.]+)", msg["body"])
                if match:
                    return match.group(1)
        return None


@pytest.fixture
def mock_smtp() -> Generator[MockSMTPSink, None, None]:
    sink = MockSMTPSink()

    async def mock_send(message, *args, **kwargs):
        to_addr = message.get("To", "") if hasattr(message, "get") else ""
        subject = message.get("Subject", "") if hasattr(message, "get") else ""
        try:
            body = message.get_content() if hasattr(message, "get_content") else str(message)
        except Exception:
            body = str(message)
        sink.send(recipient=to_addr, subject=subject, body=body)
        return ({}, "OK")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=mock_send)), \
         patch("app.core.dependencies.get_notification_adapter") as mock_adapter:
        mock_instance = MagicMock()
        mock_instance.send_notification = AsyncMock(return_value=True)
        mock_instance.send_message = AsyncMock(return_value={"status": "sent", "provider_message_id": "mock_id"})
        mock_adapter.return_value = mock_instance
        yield sink


# -----------------------------------------------------------------------------
# Mock Redis Engine Fixture
# -----------------------------------------------------------------------------
class MockRedisClient:
    def __init__(self) -> None:
        self._data: Dict[str, str] = {}
        self._expiry: Dict[str, float] = {}

    def _is_expired(self, key: str) -> bool:
        if key in self._expiry:
            if datetime.now(timezone.utc).timestamp() > self._expiry[key]:
                del self._data[key]
                del self._expiry[key]
                return True
        return False

    async def get(self, key: str) -> Optional[str]:
        if self._is_expired(key):
            return None
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._data[key] = str(value)
        if ex is not None:
            self._expiry[key] = datetime.now(timezone.utc).timestamp() + ex
        elif key in self._expiry:
            del self._expiry[key]
        return True

    async def setex(self, key: str, time: int, value: str) -> bool:
        return await self.set(key, value, ex=time)

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                if key in self._expiry:
                    del self._expiry[key]
                count += 1
        return count

    async def exists(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if not self._is_expired(key) and key in self._data:
                count += 1
        return count

    async def expire(self, key: str, time: int) -> bool:
        if key in self._data:
            self._expiry[key] = datetime.now(timezone.utc).timestamp() + time
            return True
        return False

    async def ttl(self, key: str) -> int:
        if self._is_expired(key) or key not in self._data:
            return -2
        if key not in self._expiry:
            return -1
        remaining = int(self._expiry[key] - datetime.now(timezone.utc).timestamp())
        return max(0, remaining)

    async def flushall(self) -> bool:
        self._data.clear()
        self._expiry.clear()
        return True

    async def ping(self) -> bool:
        return True


@pytest.fixture
def mock_redis() -> Generator[MockRedisClient, None, None]:
    client = MockRedisClient()
    with patch("app.core.redis.get_redis_client", AsyncMock(return_value=client)), \
         patch("app.core.redis.get_redis", return_value=client), \
         patch("app.api.v1.routes_live.get_redis_client", AsyncMock(return_value=client)):
        yield client


# -----------------------------------------------------------------------------
# Database Engine Fixtures (Sync & Async)
# -----------------------------------------------------------------------------
@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Synchronous database session for legacy tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest_asyncio.fixture()
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Asynchronous database session for modern multi-tenant tests."""
    test_db_url = os.getenv("PHILIXA_TEST_DATABASE_URL")
    if not test_db_url:
        test_db_url = "sqlite+aiosqlite:///:memory:"
    elif test_db_url.startswith("postgresql://"):
        test_db_url = test_db_url.replace("postgresql://", "postgresql+asyncpg://")

    connect_args = {"check_same_thread": False} if "sqlite" in test_db_url else {}
    engine = create_async_engine(
        test_db_url,
        connect_args=connect_args,
        poolclass=StaticPool if "sqlite" in test_db_url else None,
        future=True,
    )
    TestingAsyncSessionLocal = async_sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingAsyncSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# -----------------------------------------------------------------------------
# Test Clients (Sync & Async)
# -----------------------------------------------------------------------------
@pytest.fixture()
def client_app() -> Generator[TestClient, None, None]:
    """Synchronous TestClient with overridden async get_db for legacy tests."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingAsyncSessionLocal = async_sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def init_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_schema())

    async def override_get_async_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestingAsyncSessionLocal() as session:
            yield session

    @asynccontextmanager
    async def noop_lifespan(app_instance):
        yield

    from app.ai.provider import LocalHeuristicProvider
    heuristic_provider = LocalHeuristicProvider()

    app.dependency_overrides[get_db] = override_get_async_db
    orig_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan
    with patch("app.ai.provider.get_ai_provider", return_value=heuristic_provider), \
         patch("app.services.meeting_processing_service.get_ai_provider", return_value=heuristic_provider), \
         patch("app.services.ai_routing_service.get_ai_provider", return_value=heuristic_provider):
        try:
            with TestClient(app) as test_client:
                yield test_client
        finally:
            app.router.lifespan_context = orig_lifespan
            app.dependency_overrides.clear()


@pytest.fixture()
def api_headers() -> dict[str, str]:
    """Legacy API Key header fixture."""
    return {"X-API-Key": "dev-api-key"}


@pytest_asyncio.fixture()
async def async_client(async_db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Modern asynchronous httpx client with cookie jar support for FastAPI."""
    async def override_get_async_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_async_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={}) as client:
        yield client
    app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# Multi-Tenant Test Matrix Fixture
# -----------------------------------------------------------------------------
@pytest.fixture
def tenant_matrix() -> Dict[str, Any]:
    """
    Standard test matrix containing Org A (Owner A1, Member A2)
    and Org B (Owner B1, Member B2) specifications.
    """
    return {
        "org_a": {
            "id": "org_aaa_111",
            "name": "Acme Global Banking",
            "workspace_type": "company",
            "slug": "acme-global",
            "owner": {
                "id": "user_a1_owner",
                "email": "a1_owner@acme.com",
                "password": "Password123!",
                "role": "owner",
            },
            "member": {
                "id": "user_a2_member",
                "email": "a2_member@acme.com",
                "password": "Password123!",
                "role": "member",
            },
        },
        "org_b": {
            "id": "org_bbb_222",
            "name": "Beta Financial Partners",
            "workspace_type": "company",
            "slug": "beta-financial",
            "owner": {
                "id": "user_b1_owner",
                "email": "b1_owner@beta.com",
                "password": "Password123!",
                "role": "owner",
            },
            "member": {
                "id": "user_b2_member",
                "email": "b2_member@beta.com",
                "password": "Password123!",
                "role": "member",
            },
        },
    }


# -----------------------------------------------------------------------------
# Authenticated Async Client Helpers
# -----------------------------------------------------------------------------
class AuthenticatedClientFactory:
    """Helper to create client instances pre-authenticated as a given user."""
    def __init__(self, async_client: httpx.AsyncClient) -> None:
        self.client = async_client

    def authenticate_as(
        self,
        user_id: str,
        org_id: str,
        role: str = "owner",
        session_id: Optional[str] = None,
    ) -> httpx.AsyncClient:
        access_token = create_test_token(user_id=user_id, org_id=org_id, role=role, session_id=session_id, token_type="access")
        refresh_token = create_test_token(user_id=user_id, org_id=org_id, role=role, session_id=session_id, token_type="refresh")
        csrf_token = generate_test_csrf_token()

        self.client.cookies.set("access_token", access_token)
        self.client.cookies.set("refresh_token", refresh_token)
        self.client.cookies.set("csrf_token", csrf_token)
        self.client.headers["X-CSRF-Token"] = csrf_token
        return self.client


@pytest.fixture
def auth_factory(async_client: httpx.AsyncClient) -> AuthenticatedClientFactory:
    return AuthenticatedClientFactory(async_client)
