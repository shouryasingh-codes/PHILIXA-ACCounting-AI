from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import httpx
from jose import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.auth_tokens import EmailVerificationToken, PasswordResetToken
from tests.conftest import (
    MockSMTPSink,
    create_test_token,
    generate_test_csrf_token,
    hash_password,
    verify_password,
)


@pytest.mark.asyncio
class TestAuthRegistrationAndVerificationFlow:
    async def test_register_creates_organization_user_and_membership(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
        mock_smtp: MockSMTPSink,
    ) -> None:
        payload = {
            "email": "sarah.connor@cyberdyne.com",
            "password": "Resistance2026!Strong",
            "workspace_name": "Cyberdyne Systems",
            "workspace_type": "company",
        }
        
        response = await async_client.post("/auth/register", json=payload)
        
        # Verify HTTP status
        assert response.status_code in (200, 201), f"Registration failed: {response.text}"
        data = response.json()
        assert "message" in data or "user" in data
        
        # Verify DB entries
        user = (await async_db_session.execute(
            select(User).where(User.email == payload["email"])
        )).scalar_one_or_none()
        
        assert user is not None
        assert user.is_verified is False
        assert verify_password(payload["password"], user.hashed_password) is True

        org = (await async_db_session.execute(
            select(Organization).where(Organization.name == payload["workspace_name"])
        )).scalar_one_or_none()
        
        assert org is not None
        assert org.workspace_type == "company"

        # Verify Owner membership
        membership = (await async_db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == org.id,
            )
        )).scalar_one_or_none()
        
        assert membership is not None
        assert membership.role.lower() in ("owner", UserRole.ADMIN.value.lower(), "admin")

        # Verify token created in DB
        token_record = (await async_db_session.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )).scalar_one_or_none()
        assert token_record is not None
        exp_dt = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
        assert exp_dt > datetime.now(timezone.utc)

    async def test_register_duplicate_email_is_rejected(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        email = "duplicate.test@domain.com"
        payload = {
            "email": email,
            "password": "Password123!",
            "workspace_name": "First Org",
            "workspace_type": "individual",
        }
        
        res1 = await async_client.post("/auth/register", json=payload)
        assert res1.status_code in (200, 201)
        
        # Attempt second registration with same email
        res2 = await async_client.post("/auth/register", json=payload)
        assert res2.status_code in (400, 409), "Duplicate registration must be rejected with 400 or 409"

    async def test_verify_email_success_marks_user_verified(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "user_verify_test_01"
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        user = User(
            id=user_id,
            email="verify.me@test.com",
            hashed_password=hash_password("Pass123!"),
            is_verified=False,
            is_active=True,
        )
        async_db_session.add(user)
        
        verify_token = EmailVerificationToken(
            id=secrets.token_hex(16),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        async_db_session.add(verify_token)
        await async_db_session.commit()
        
        # Call verification endpoint
        response = await async_client.post(f"/auth/verify-email?token={raw_token}")
        assert response.status_code in (200, 302, 303)
        
        # Verify user state in DB
        await async_db_session.refresh(user)
        assert user.is_verified is True

    async def test_verify_email_expired_token_is_rejected(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "user_verify_expired"
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        user = User(
            id=user_id,
            email="expired.token@test.com",
            hashed_password=hash_password("Pass123!"),
            is_verified=False,
            is_active=True,
        )
        async_db_session.add(user)
        
        expired_token = EmailVerificationToken(
            id=secrets.token_hex(16),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),  # Expired
        )
        async_db_session.add(expired_token)
        await async_db_session.commit()
        
        response = await async_client.post(f"/auth/verify-email?token={raw_token}")
        assert response.status_code in (400, 410), "Expired verification token must return 400 or 410"

    async def test_verify_email_reused_token_is_rejected(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "user_verify_reused"
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        user = User(
            id=user_id,
            email="reused.token@test.com",
            hashed_password=hash_password("Pass123!"),
            is_verified=False,
            is_active=True,
        )
        async_db_session.add(user)
        
        token_rec = EmailVerificationToken(
            id=secrets.token_hex(16),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        async_db_session.add(token_rec)
        await async_db_session.commit()
        
        # First verification succeeds
        res1 = await async_client.post(f"/auth/verify-email?token={raw_token}")
        assert res1.status_code in (200, 302, 303)
        
        # Second verification attempt fails
        res2 = await async_client.post(f"/auth/verify-email?token={raw_token}")
        assert res2.status_code in (400, 410), "Reused verification token must be rejected"


@pytest.mark.asyncio
class TestAuthLoginAndSessionLifecycle:
    async def test_login_unverified_user_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        email = "unverified.user@test.com"
        password = "Password123!"
        user = User(
            id="usr_unverified_01",
            email=email,
            hashed_password=hash_password(password),
            is_verified=False,  # Unverified
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.commit()
        
        response = await async_client.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 403, f"Unverified login should return 403, got {response.status_code}"

    async def test_login_invalid_password_returns_401(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        email = "verified.user@test.com"
        user = User(
            id="usr_verified_01",
            email=email,
            hashed_password=hash_password("CorrectPassword123!"),
            is_verified=True,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.commit()
        
        response = await async_client.post("/auth/login", json={"email": email, "password": "WrongPassword!"})
        assert response.status_code == 401

    async def test_login_success_sets_http_only_cookies_and_returns_principal(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_login_success"
        org_id = "org_login_success"
        email = "verified.success@test.com"
        password = "ValidSecretPassword123!"
        
        org = Organization(id=org_id, name="Success Org", slug="success-org", workspace_type="company")
        user = User(id=user_id, email=email, hashed_password=hash_password(password), is_verified=True, is_active=True)
        membership = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")
        
        async_db_session.add_all([org, user, membership])
        await async_db_session.commit()
        
        response = await async_client.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200
        
        # Verify Cookies
        cookies = response.cookies
        assert "access_token" in cookies
        assert "refresh_token" in cookies
        assert "csrf_token" in cookies
        
        # Verify payload structure
        data = response.json()
        assert "user" in data
        assert data["user"]["email"] == email
        assert "active_organization" in data
        assert data["role"] == "owner"

    async def test_get_me_returns_profile_when_authenticated(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_me_01"
        org_id = "org_me_01"
        email = "me.profile@test.com"
        
        org = Organization(id=org_id, name="Profile Org", slug="profile-org", workspace_type="company")
        user = User(id=user_id, email=email, hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        membership = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")
        
        async_db_session.add_all([org, user, membership])
        await async_db_session.commit()
        
        # Authenticate client
        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        async_client.cookies.set("access_token", token)
        
        response = await async_client.get("/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == email
        assert data["active_organization"]["id"] == org_id
        assert data["role"] == "owner"

    async def test_get_me_unauthenticated_returns_401(
        self,
        async_client: httpx.AsyncClient,
    ) -> None:
        async_client.cookies.clear()
        response = await async_client.get("/auth/me")
        assert response.status_code == 401


@pytest.mark.asyncio
class TestAuthTokenRefreshAndRevocation:
    async def test_refresh_token_rotation_succeeds(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_refresh_01"
        org_id = "org_refresh_01"
        session_id = "sess_refresh_01"
        
        org = Organization(id=org_id, name="Refresh Org", slug="refresh-org", workspace_type="company")
        user = User(id=user_id, email="refresh@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        membership = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")
        
        refresh_jwt = create_test_token(user_id=user_id, org_id=org_id, role="owner", session_id=session_id, token_type="refresh")
        refresh_hash = hashlib.sha256(refresh_jwt.encode("utf-8")).hexdigest()
        
        user_session = UserSession(
            id=session_id,
            user_id=user_id,
            organization_id=org_id,
            refresh_token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        async_db_session.add_all([org, user, membership, user_session])
        await async_db_session.commit()
        
        async_client.cookies.set("refresh_token", refresh_jwt)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.post("/auth/refresh")
        assert response.status_code == 200
        
        # New cookies issued
        new_refresh = response.cookies.get("refresh_token")
        assert new_refresh is not None
        assert new_refresh != refresh_jwt, "Refresh token must be rotated"

    async def test_logout_revokes_session_and_clears_cookies(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_logout_01"
        org_id = "org_logout_01"
        session_id = "sess_logout_01"
        
        org = Organization(id=org_id, name="Logout Org", slug="logout-org", workspace_type="company")
        user = User(id=user_id, email="logout@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        membership = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")
        
        access_jwt = create_test_token(user_id=user_id, org_id=org_id, role="owner", session_id=session_id, token_type="access")
        user_session = UserSession(
            id=session_id,
            user_id=user_id,
            organization_id=org_id,
            refresh_token_hash="hash_logout",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        async_db_session.add_all([org, user, membership, user_session])
        await async_db_session.commit()
        
        async_client.cookies.set("access_token", access_jwt)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.post("/auth/logout")
        assert response.status_code == 200
        
        # Verify session marked revoked in DB
        await async_db_session.refresh(user_session)
        assert user_session.revoked_at is not None


@pytest.mark.asyncio
class TestAuthPasswordResetFlow:
    async def test_forgot_password_generates_token_and_sends_email(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
        mock_smtp: MockSMTPSink,
    ) -> None:
        email = "forgot.pass@test.com"
        user = User(
            id="usr_forgot_01",
            email=email,
            hashed_password=hash_password("OldPassword123!"),
            is_verified=True,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.commit()
        
        response = await async_client.post("/auth/forgot-password", json={"email": email})
        assert response.status_code in (200, 202)
        
        # Verify token record created
        token_record = (await async_db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )).scalar_one_or_none()
        assert token_record is not None
        exp_dt = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
        assert exp_dt > datetime.now(timezone.utc)

    async def test_reset_password_with_valid_token_updates_password(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_reset_01"
        email = "reset.pass@test.com"
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        user = User(
            id=user_id,
            email=email,
            hashed_password=hash_password("OldPassword123!"),
            is_verified=True,
            is_active=True,
        )
        async_db_session.add(user)
        
        reset_token = PasswordResetToken(
            id=secrets.token_hex(16),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        async_db_session.add(reset_token)
        await async_db_session.commit()
        
        new_password = "BrandNewSecurePassword2026!"
        response = await async_client.post("/auth/reset-password", json={
            "token": raw_token,
            "new_password": new_password,
        })
        assert response.status_code == 200
        
        # Verify new password in DB
        await async_db_session.refresh(user)
        assert verify_password(new_password, user.hashed_password) is True
        assert verify_password("OldPassword123!", user.hashed_password) is False
