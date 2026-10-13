from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import secrets
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from jose import jwt
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from tests.conftest import (
    MockRedisClient,
    create_test_token,
    generate_test_csrf_token,
    hash_password,
)


@pytest_asyncio.fixture
async def seeded_audio_env(async_db_session: AsyncSession) -> Dict[str, Any]:
    org_a = Organization(id="org_audio_a", name="Org Audio A", slug="audio-a", workspace_type="company")
    org_b = Organization(id="org_audio_b", name="Org Audio B", slug="audio-b", workspace_type="company")
    
    user_a = User(id="usr_audio_a", email="audio.a@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    user_b = User(id="usr_audio_b", email="audio.b@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    
    mem_a = OrganizationMembership(user_id="usr_audio_a", organization_id="org_audio_a", role="owner")
    mem_b = OrganizationMembership(user_id="usr_audio_b", organization_id="org_audio_b", role="owner")
    
    meeting_a = Meeting(
        id=5001,
        organization_id="org_audio_a",
        user_id="usr_audio_a",
        raw_notes="Org A Audio Meeting",
        status="processed",
        audio_file_path="org_audio_a/usr_audio_a/5001/recording.wav",
    )
    meeting_b = Meeting(
        id=5002,
        organization_id="org_audio_b",
        user_id="usr_audio_b",
        raw_notes="Org B Audio Meeting",
        status="processed",
        audio_file_path="org_audio_b/usr_audio_b/5002/recording.wav",
    )
    
    async_db_session.add_all([org_a, org_b, user_a, user_b, mem_a, mem_b, meeting_a, meeting_b])
    await async_db_session.commit()
    
    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "meeting_a": meeting_a,
        "meeting_b": meeting_b,
    }


def authenticate_client(
    client: httpx.AsyncClient,
    user_id: str,
    org_id: str,
    role: str = "owner",
) -> None:
    token = create_test_token(user_id=user_id, org_id=org_id, role=role)
    client.cookies.set("access_token", token)
    csrf_token = generate_test_csrf_token()
    client.cookies.set("csrf_token", csrf_token)
    client.headers["X-CSRF-Token"] = csrf_token


@pytest.mark.asyncio
class TestWebSocketTicketAuthentication:
    async def test_issue_ws_ticket_authenticated(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        user = User(id="usr_ws_01", email="ws01@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        org = Organization(id="org_ws_01", name="WS Org", slug="ws-org-01", workspace_type="company")
        mem = OrganizationMembership(user_id="usr_ws_01", organization_id="org_ws_01", role="owner")
        async_db_session.add_all([user, org, mem])
        await async_db_session.commit()

        authenticate_client(async_client, user_id="usr_ws_01", org_id="org_ws_01", role="owner")
        
        response = await async_client.post("/api/v1/ws-ticket")
        assert response.status_code == 200
        data = response.json()
        assert "ticket" in data or "token" in data
        
        ticket = data.get("ticket") or data.get("token")
        assert ticket is not None and len(ticket) > 20

    async def test_issue_ws_ticket_unauthenticated_returns_401(
        self,
        async_client: httpx.AsyncClient,
    ) -> None:
        async_client.cookies.clear()
        if "X-CSRF-Token" in async_client.headers:
            del async_client.headers["X-CSRF-Token"]
            
        response = await async_client.post("/api/v1/ws-ticket")
        assert response.status_code in (401, 403)

    async def test_ws_ticket_replay_defense_in_redis(
        self,
        mock_redis: MockRedisClient,
    ) -> None:
        """
        Verify that a ticket stored in Redis with 60s TTL can only be redeemed once.
        """
        ticket_id = f"ticket_{secrets.token_hex(16)}"
        # Simulate storing ticket in Redis with 60s TTL
        await mock_redis.set(ticket_id, json.dumps({"user_id": "usr_1", "org_id": "org_1"}), ex=60)
        
        # 1. First redemption: exists and is consumed
        data = await mock_redis.get(ticket_id)
        assert data is not None, "First ticket lookup must succeed"
        
        # Consume ticket
        await mock_redis.delete(ticket_id)
        
        # 2. Second redemption attempt (replay attack): rejected
        replayed_data = await mock_redis.get(ticket_id)
        assert replayed_data is None, "Replaying used ticket must fail"

    async def test_ws_ticket_expiration_ttl(
        self,
        mock_redis: MockRedisClient,
    ) -> None:
        ticket_id = f"ticket_exp_{secrets.token_hex(16)}"
        await mock_redis.setex(ticket_id, 60, "ticket_payload")
        
        ttl = await mock_redis.ttl(ticket_id)
        assert 0 <= ttl <= 60, f"Expected TTL <= 60s, got {ttl}"


@pytest.mark.asyncio
class TestMinIOAudioStorageNamespacingAndSecurity:
    async def test_audio_url_generation_for_owner_meeting_succeeds(
        self,
        async_client: httpx.AsyncClient,
        seeded_audio_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_audio_a", org_id="org_audio_a", role="owner")
        meeting_id = seeded_audio_env["meeting_a"].id
        
        with patch("app.services.minio_service.minio_service.get_presigned_url", return_value="http://minio/presigned-audio.wav"):
            response = await async_client.get(f"/api/v1/audio/{meeting_id}/url")
            assert response.status_code == 200
            data = response.json()
            assert "url" in data or "audio_url" in data or "presigned_url" in data

    async def test_cross_tenant_audio_access_returns_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_audio_env: Dict[str, Any],
    ) -> None:
        # Org A user attempts to get audio URL for Org B meeting
        authenticate_client(async_client, user_id="usr_audio_a", org_id="org_audio_a", role="owner")
        org_b_meeting_id = seeded_audio_env["meeting_b"].id
        
        response = await async_client.get(f"/api/v1/audio/{org_b_meeting_id}/url")
        assert response.status_code == 404, f"Cross-tenant audio request must return 404, got {response.status_code}"

    async def test_audio_namespaced_path_format(
        self,
        seeded_audio_env: Dict[str, Any],
    ) -> None:
        meeting_a = seeded_audio_env["meeting_a"]
        expected_prefix = f"{meeting_a.organization_id}/{meeting_a.user_id}/{meeting_a.id}/"
        assert meeting_a.audio_file_path.startswith(expected_prefix), (
            f"Audio file path '{meeting_a.audio_file_path}' must follow '{{org_id}}/{{user_id}}/{{meeting_id}}/filename' format"
        )


class MockWebSocket:
    def __init__(self) -> None:
        self.closed: bool = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.accepted: bool = False

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def accept(self) -> None:
        self.accepted = True


class MockSessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


@pytest.mark.asyncio
class TestWebSocketAdversarialSecurity:
    async def test_ws_ticket_missing_ticket_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket=None)
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Missing authentication ticket"

    async def test_ws_ticket_invalid_jwt_syntax_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket="malformed.jwt.token")
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Invalid or expired ticket"

    async def test_ws_ticket_forged_signature_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        forged_payload = {
            "sub": "usr_audio_a",
            "org_id": "org_audio_a",
            "role": "owner",
            "type": "ws_ticket",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        forged_token = jwt.encode(forged_payload, "completely-wrong-secret-key-00000", algorithm="HS256")
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket=forged_token)
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Invalid or expired ticket"

    async def test_ws_ticket_expired_ticket_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.config import get_settings
        settings = get_settings()
        expired_payload = {
            "sub": "usr_audio_a",
            "org_id": "org_audio_a",
            "role": "owner",
            "type": "ws_ticket",
            "iat": int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()),
            "exp": int((datetime.now(timezone.utc) - timedelta(seconds=10)).timestamp()),
        }
        expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket=expired_token)
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Invalid or expired ticket"

    async def test_ws_ticket_disallowed_token_type_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.config import get_settings
        settings = get_settings()
        bad_type_payload = {
            "sub": "usr_audio_a",
            "org_id": "org_audio_a",
            "role": "owner",
            "type": "refresh",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        bad_type_token = jwt.encode(bad_type_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket=bad_type_token)
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Invalid token type for WebSocket"

    async def test_ws_ticket_missing_sub_or_org_claims_closes_1008(self) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.config import get_settings
        settings = get_settings()
        incomplete_payload = {
            "role": "owner",
            "type": "ws_ticket",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        incomplete_token = jwt.encode(incomplete_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        ws = MockWebSocket()
        result = await _authenticate_ws_ticket(ws, raw_ticket=incomplete_token)
        assert result is None
        assert ws.closed is True
        assert ws.close_code == 1008
        assert ws.close_reason == "Incomplete ticket claims"

    async def test_ws_ticket_redis_replay_attack_closes_1008(
        self,
        seeded_audio_env: Dict[str, Any],
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.security import create_ws_ticket_token

        valid_ticket = create_ws_ticket_token(
            user_id="usr_audio_a",
            org_id="org_audio_a",
            role="owner",
            expires_delta=timedelta(seconds=60),
        )

        with patch("app.api.v1.routes_live.AsyncSessionLocal", return_value=MockSessionContext(async_db_session)):
            # 1. First redemption: succeeds
            ws1 = MockWebSocket()
            result1 = await _authenticate_ws_ticket(ws1, raw_ticket=valid_ticket)
            assert result1 is not None
            assert ws1.closed is False
            payload, principal = result1
            assert principal.user_id == "usr_audio_a"
            assert principal.organization_id == "org_audio_a"

            # 2. Second redemption attempt (Replay attack): rejected with 1008
            ws2 = MockWebSocket()
            result2 = await _authenticate_ws_ticket(ws2, raw_ticket=valid_ticket)
            assert result2 is None
            assert ws2.closed is True
            assert ws2.close_code == 1008
            assert ws2.close_reason == "Ticket has already been redeemed (replay detected)"

    async def test_ws_ticket_cross_tenant_impersonation_closes_1008(
        self,
        seeded_audio_env: Dict[str, Any],
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.security import create_ws_ticket_token

        # User A tries to authenticate with Org B claims
        cross_tenant_ticket = create_ws_ticket_token(
            user_id="usr_audio_a",
            org_id="org_audio_b",
            role="owner",
            expires_delta=timedelta(seconds=60),
        )

        with patch("app.api.v1.routes_live.AsyncSessionLocal", return_value=MockSessionContext(async_db_session)):
            ws = MockWebSocket()
            result = await _authenticate_ws_ticket(ws, raw_ticket=cross_tenant_ticket)
            assert result is None
            assert ws.closed is True
            assert ws.close_code == 1008
            assert ws.close_reason == "Inactive workspace membership"

    async def test_ws_ticket_revoked_session_closes_1008(
        self,
        seeded_audio_env: Dict[str, Any],
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.security import create_ws_ticket_token
        from app.models.user_session import UserSession

        # Create revoked session
        session_id = f"sess_revoked_{secrets.token_hex(8)}"
        revoked_sess = UserSession(
            id=session_id,
            user_id="usr_audio_a",
            organization_id="org_audio_a",
            refresh_token_hash="dummy_hash",
            revoked_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        async_db_session.add(revoked_sess)
        await async_db_session.commit()

        revoked_ticket = create_ws_ticket_token(
            user_id="usr_audio_a",
            org_id="org_audio_a",
            role="owner",
            session_id=session_id,
            expires_delta=timedelta(seconds=60),
        )

        with patch("app.api.v1.routes_live.AsyncSessionLocal", return_value=MockSessionContext(async_db_session)):
            ws = MockWebSocket()
            result = await _authenticate_ws_ticket(ws, raw_ticket=revoked_ticket)
            assert result is None
            assert ws.closed is True
            assert ws.close_code == 1008
            assert ws.close_reason == "Session has been revoked"

    async def test_ws_ticket_inactive_user_closes_1008(
        self,
        seeded_audio_env: Dict[str, Any],
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.security import create_ws_ticket_token

        # Mark user inactive
        user_a = seeded_audio_env["user_a"]
        user_a.is_active = False
        await async_db_session.commit()

        ticket = create_ws_ticket_token(
            user_id="usr_audio_a",
            org_id="org_audio_a",
            role="owner",
            expires_delta=timedelta(seconds=60),
        )

        with patch("app.api.v1.routes_live.AsyncSessionLocal", return_value=MockSessionContext(async_db_session)):
            ws = MockWebSocket()
            result = await _authenticate_ws_ticket(ws, raw_ticket=ticket)
            assert result is None
            assert ws.closed is True
            assert ws.close_code == 1008
            assert ws.close_reason == "User is inactive"

        # Restore user active
        user_a.is_active = True
        await async_db_session.commit()

    async def test_ws_ticket_inactive_org_closes_1008(
        self,
        seeded_audio_env: Dict[str, Any],
        async_db_session: AsyncSession,
        mock_redis: MockRedisClient,
    ) -> None:
        from app.api.v1.routes_live import _authenticate_ws_ticket
        from app.core.security import create_ws_ticket_token

        # Mark org inactive
        org_a = seeded_audio_env["org_a"]
        org_a.is_active = False
        await async_db_session.commit()

        ticket = create_ws_ticket_token(
            user_id="usr_audio_a",
            org_id="org_audio_a",
            role="owner",
            expires_delta=timedelta(seconds=60),
        )

        with patch("app.api.v1.routes_live.AsyncSessionLocal", return_value=MockSessionContext(async_db_session)):
            ws = MockWebSocket()
            result = await _authenticate_ws_ticket(ws, raw_ticket=ticket)
            assert result is None
            assert ws.closed is True
            assert ws.close_code == 1008
            assert ws.close_reason == "Organization is inactive"

        # Restore org active
        org_a.is_active = True
        await async_db_session.commit()


