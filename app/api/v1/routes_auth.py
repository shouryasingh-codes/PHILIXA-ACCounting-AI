from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import re
import secrets
import string
import random
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentPrincipal, Principal
from app.core.config import get_settings
from app.core.dependencies import get_email_adapter, get_notification_adapter
from app.core.rate_limit import limiter
from app.services.notifications.email_adapter import EmailAdapter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_ws_ticket_token,
    decode_jwt_token,
    generate_csrf_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.database.session import get_db
from app.models.auth_tokens import EmailVerificationToken, PasswordResetToken
from app.models.enums import MembershipStatus, UserRole, WorkspaceType
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.client import Client
from app.models.meeting import Meeting
from app.models.follow_up_task import FollowUpTask
from app.models.risk_signal import RiskSignal
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MembershipRead,
    MessageResponse,
    OrganizationRead,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenRefreshResponse,
    UserProfileResponse,
    UserRead,
    VerifyEmailRequest,
    GoogleAuthRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

ws_ticket_router = APIRouter(
    prefix="/ws-ticket",
    tags=["websocket"],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    settings = get_settings()
    # 1. access_token (HttpOnly, 15m)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )
    # 2. refresh_token (HttpOnly, 30d)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/",
    )
    # 3. csrf_token (Readable by JavaScript, 30d)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for cookie_name in ("access_token", "refresh_token", "csrf_token"):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
        )


async def send_verification_email(
    recipient: str,
    raw_token: str,
    adapter: Optional[EmailAdapter] = None,
) -> None:
    try:
        if adapter is None:
            adapter = get_email_adapter()
        subject = "Verify your Philixa email"
        body = f"Welcome to Philixa! Please verify your email using the following token link: token={raw_token}"
        if hasattr(adapter, "send_message"):
            await adapter.send_message(to_destination=recipient, message_content=body, subject=subject)
        elif hasattr(adapter, "send_notification"):
            await adapter.send_notification(to_destination=recipient, message_content=body, subject=subject)
    except Exception as exc:
        logger.warning(f"Failed to send verification email to {recipient}: {exc}")


async def send_reset_password_email(
    recipient: str,
    raw_token: str,
    adapter: Optional[EmailAdapter] = None,
) -> None:
    try:
        if adapter is None:
            adapter = get_email_adapter()
        subject = "Reset your Philixa password"
        body = f"A password reset was requested for your account. Use the following token: token={raw_token}"
        if hasattr(adapter, "send_message"):
            await adapter.send_message(to_destination=recipient, message_content=body, subject=subject)
        elif hasattr(adapter, "send_notification"):
            await adapter.send_notification(to_destination=recipient, message_content=body, subject=subject)
    except Exception as exc:
        logger.warning(f"Failed to send password reset email to {recipient}: {exc}")


async def generate_unique_slug(db: AsyncSession, name: str) -> str:
    base_slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    if not base_slug:
        base_slug = "workspace"
    slug = base_slug
    idx = 1
    while True:
        existing = (await db.execute(select(Organization).where(Organization.slug == slug))).scalar_one_or_none()
        if not existing:
            return slug
        slug = f"{base_slug}-{idx}"
        idx += 1


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    email_adapter: EmailAdapter = Depends(get_email_adapter),
) -> Any:
    normalized_email = payload.email.strip().lower()

    # 1. Duplicate email rejection
    existing_user = (await db.execute(select(User).where(User.email == normalized_email))).scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 2. Create User
    user_id = f"usr_{secrets.token_hex(12)}"
    user = User(
        id=user_id,
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_verified=False,
    )
    db.add(user)

    # 3. Create Organization
    org_id = f"org_{secrets.token_hex(12)}"
    slug = await generate_unique_slug(db, payload.workspace_name)
    org_type = payload.workspace_type.strip().lower() if payload.workspace_type else "company"
    if org_type not in ("individual", "company"):
        org_type = "company"

    org = Organization(
        id=org_id,
        name=payload.workspace_name.strip(),
        workspace_type=org_type,
        slug=slug,
        plan="free",
        is_active=True,
    )
    db.add(org)

    # 4. Create Owner Membership
    membership = OrganizationMembership(
        user_id=user_id,
        organization_id=org_id,
        role=UserRole.OWNER.value,
        status=MembershipStatus.ACTIVE.value,
        joined_at=utc_now(),
    )
    db.add(membership)

    # 5. Create Email Verification Token
    raw_token = ''.join(random.choices(string.digits, k=6))
    token_record = EmailVerificationToken(
        id=secrets.token_hex(16),
        user_id=user_id,
        token_hash=hash_token(raw_token),
        expires_at=utc_now() + timedelta(minutes=15),
    )
    db.add(token_record)

    await db.commit()

    # 6. Dispatch email
    await send_verification_email(normalized_email, raw_token, adapter=email_adapter)

    return {
        "message": "User registered successfully. Please check your email to verify your account.",
        "user": user,
        "organization": org,
    }


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    token: Optional[str] = Query(default=None),
    body: Optional[VerifyEmailRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> Any:
    raw_token = token or (body.token if body else None)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token is required.",
        )

    t_hash = hash_token(raw_token)
    token_record = (await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == t_hash)
    )).scalar_one_or_none()

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email verification token.",
        )

    if token_record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This email verification token has already been used.",
        )

    now = utc_now()
    expires_at = token_record.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is not None and expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email verification token has expired.",
        )

    user = await db.get(User, token_record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found for this token.",
        )

    user.is_verified = True
    token_record.used_at = utc_now()
    await db.commit()

    return {
        "message": "Email verified successfully.",
        "verified": True,
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    normalized_email = payload.email.strip().lower()

    user = (await db.execute(
        select(User).where(User.email == normalized_email)
    )).scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated.",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not verified. Please verify your email before logging in.",
        )

    # Resolve active organization membership
    memberships_stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Organization.is_active.is_(True),
        )
    )
    memberships = (await db.execute(memberships_stmt)).all()
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active workspace membership found.",
        )

    active_membership, active_org = memberships[0]

    # Create User Session
    session_id = f"sess_{secrets.token_hex(16)}"
    refresh_jwt = create_refresh_token(
        user_id=user.id,
        org_id=active_org.id,
        role=active_membership.role,
        session_id=session_id,
    )
    refresh_hash = hash_token(refresh_jwt)

    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        organization_id=active_org.id,
        refresh_token_hash=refresh_hash,
        ip_address=ip_addr,
        user_agent=user_agent[:255] if user_agent else None,
        expires_at=utc_now() + timedelta(days=get_settings().jwt_refresh_token_expire_days),
    )
    db.add(user_session)
    await db.commit()

    # Generate Access and CSRF tokens
    access_jwt = create_access_token(
        user_id=user.id,
        org_id=active_org.id,
        role=active_membership.role,
        session_id=session_id,
    )
    csrf_token = generate_csrf_token()

    set_auth_cookies(
        response=response,
        access_token=access_jwt,
        refresh_token=refresh_jwt,
        csrf_token=csrf_token,
    )

    return {
        "user": user,
        "active_organization": active_org,
        "role": active_membership.role,
        "csrf_token": csrf_token,
    }


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # Query all memberships for this user
    memberships_stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(OrganizationMembership.user_id == principal.user.id)
    )
    membership_rows = (await db.execute(memberships_stmt)).all()

    memberships_list = [
        MembershipRead(
            organization_id=org.id,
            organization_name=org.name,
            slug=org.slug,
            organization_slug=org.slug,
            workspace_type=org.workspace_type,
            role=mem.role,
            status=mem.status,
            joined_at=mem.joined_at,
        )
        for mem, org in membership_rows
    ]

    return {
        "user": principal.user,
        "active_organization": principal.organization,
        "role": principal.role,
        "session_id": principal.session_id,
        "memberships": memberships_list,
    }


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 1. Extract refresh token
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            refresh_token = auth_header[7:].strip()

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required.",
        )

    # 2. Decode refresh JWT
    try:
        payload = decode_jwt_token(refresh_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token type must be 'refresh'.",
        )

    session_id = payload.get("sid")
    user_id = payload.get("sub")
    org_id = payload.get("org_id")

    if not session_id or not user_id or not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims.",
        )

    # 3. Look up session
    session = await db.get(UserSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found.",
        )

    if session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked.",
        )

    now = utc_now()
    expires_at = session.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is not None and expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired.",
        )

    # 4. Anti-Replay Defense
    incoming_hash = hash_token(refresh_token)
    if session.refresh_token_hash != incoming_hash:
        session.revoked_at = utc_now()
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token or token reuse detected.",
        )

    # 5. Validate membership
    membership_stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.status == MembershipStatus.ACTIVE.value,
    )
    membership = (await db.execute(membership_stmt)).scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer has an active workspace membership.",
        )

    # 6. Rotate Tokens
    new_refresh_jwt = create_refresh_token(
        user_id=user_id,
        org_id=org_id,
        role=membership.role,
        session_id=session_id,
    )
    new_access_jwt = create_access_token(
        user_id=user_id,
        org_id=org_id,
        role=membership.role,
        session_id=session_id,
    )
    new_csrf_token = generate_csrf_token()

    session.refresh_token_hash = hash_token(new_refresh_jwt)
    session.updated_at = utc_now()
    await db.commit()

    set_auth_cookies(
        response=response,
        access_token=new_access_jwt,
        refresh_token=new_refresh_jwt,
        csrf_token=new_csrf_token,
    )

    return {
        "message": "Tokens refreshed successfully.",
        "csrf_token": new_csrf_token,
    }


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # Attempt to extract session ID from access or refresh token
    token = request.cookies.get("access_token") or request.cookies.get("refresh_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        try:
            payload = decode_jwt_token(token)
            session_id = payload.get("sid")
            if session_id:
                session = await db.get(UserSession, session_id)
                if session and session.revoked_at is None:
                    session.revoked_at = utc_now()
                    await db.commit()
        except Exception:
            pass

    clear_auth_cookies(response)
    return {"message": "Logged out successfully."}


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    email_adapter: EmailAdapter = Depends(get_email_adapter),
) -> Any:
    normalized_email = payload.email.strip().lower()
    user = (await db.execute(
        select(User).where(User.email == normalized_email)
    )).scalar_one_or_none()

    if user and user.is_active:
        raw_token = ''.join(random.choices(string.digits, k=6))
        reset_token = PasswordResetToken(
            id=secrets.token_hex(16),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=utc_now() + timedelta(minutes=15),
        )
        db.add(reset_token)
        await db.commit()

        await send_reset_password_email(normalized_email, raw_token, adapter=email_adapter)

    return {
        "message": "If that email address is in our database, we will send you an email to reset your password.",
    }


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    t_hash = hash_token(payload.token)
    reset_record = (await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == t_hash)
    )).scalar_one_or_none()

    now = utc_now()
    expires_at = reset_record.expires_at if reset_record else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if not reset_record or reset_record.used_at is not None or (expires_at is not None and expires_at < now):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token.",
        )

    user = await db.get(User, reset_record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found for this reset token.",
        )

    user.hashed_password = hash_password(payload.new_password)
    reset_record.used_at = utc_now()

    # Invalidate all active sessions for this user on password reset
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )

    await db.commit()

    return {
        "message": "Password has been reset successfully. You can now log in with your new password.",
    }


@router.delete("/me", status_code=status.HTTP_200_OK)
async def delete_current_user(
    principal: CurrentPrincipal,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # SQLAlchemy cascade will automatically delete the user's sessions, memberships, clients, meetings, etc.
    user = await db.get(User, principal.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    
    await db.delete(user)
    await db.commit()

    # Clear authentication cookies
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("csrf_token", path="/")

    return {"message": "Account successfully deleted."}


@ws_ticket_router.post("")
async def create_ws_ticket(
    principal: CurrentPrincipal,
) -> dict[str, str]:
    """Issues a short-lived (60s) signed ticket for WebSocket connection authentication."""
    ticket = create_ws_ticket_token(
        user_id=principal.user_id,
        org_id=principal.organization_id,
        role=principal.role,
        session_id=principal.session_id,
        expires_delta=timedelta(seconds=60),
    )
    return {"ticket": ticket, "token": ticket}


@router.post("/demo-login", response_model=LoginResponse)
async def demo_login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 1. Create a unique demo guest user
    unique_id = secrets.token_hex(6)
    demo_email = f"demo_guest_{unique_id}@philixa.com"
    user_id = f"usr_{secrets.token_hex(12)}"
    
    user = User(
        id=user_id,
        email=demo_email,
        hashed_password=hash_password(secrets.token_urlsafe(16)), # Unused password
        is_active=True,
        is_verified=True, # Auto-verify so they can log in
    )
    db.add(user)

    # 2. Create Demo Organization
    org_id = f"org_{secrets.token_hex(12)}"
    slug = await generate_unique_slug(db, f"demo-workspace-{unique_id}")
    org = Organization(
        id=org_id,
        name="Philixa Demo Workspace",
        workspace_type="individual",
        slug=slug,
        plan="free",
        is_active=True,
    )
    db.add(org)

    # 3. Create Membership
    membership = OrganizationMembership(
        user_id=user_id,
        organization_id=org_id,
        role=UserRole.OWNER.value,
        status=MembershipStatus.ACTIVE.value,
        joined_at=utc_now(),
    )
    db.add(membership)
    await db.flush()

    # 4. Seed Data (Clients)
    client1 = Client(
        organization_id=org_id,
        user_id=user_id,
        name="Rajesh Sharma",
        normalized_name="rajesh sharma",
        products_owned_json='["Business Loan", "Current Account"]',
        rolling_summary="Rajesh is expanding his retail business. Very concerned about fast processing times.",
        relationship_notes='["Needs frequent updates", "Prefers WhatsApp communication"]',
    )
    client2 = Client(
        organization_id=org_id,
        user_id=user_id,
        name="Manoj Kumar",
        normalized_name="manoj kumar",
        products_owned_json='["Home Loan"]',
        rolling_summary="Looking for a loan top-up to renovate property.",
    )
    db.add(client1)
    db.add(client2)
    await db.flush()

    # 5. Seed Data (Meetings and Tasks)
    meeting = Meeting(
        organization_id=org_id,
        user_id=user_id,
        client_id=client1.id,
        meeting_date=utc_now().date(),
        raw_notes="Met Rajesh regarding a 500cr loan request. He is concerned about the processing time and threatened to switch to HDFC bank if it is delayed.",
        summary="Client requested a 500cr business loan. High priority due to retention risk.",
    )
    db.add(meeting)
    await db.flush()
    
    risk = RiskSignal(
        organization_id=org_id,
        user_id=user_id,
        client_id=client1.id,
        meeting_id=meeting.id,
        description="Client threatened to switch to HDFC bank.",
        severity_level="high",
        confidence=0.8
    )
    db.add(risk)

    task = FollowUpTask(
        organization_id=org_id,
        user_id=user_id,
        client_id=client1.id,
        description="Follow up on 500cr loan approval timeline.",
        due_date=(utc_now() + timedelta(days=1)).date(),
        is_completed=False,
    )
    db.add(task)
    await db.commit()

    # 6. Create User Session and Tokens
    session_id = f"sess_{secrets.token_hex(16)}"
    refresh_jwt = create_refresh_token(
        user_id=user.id,
        org_id=org.id,
        role=membership.role,
        session_id=session_id,
    )
    
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        organization_id=org.id,
        refresh_token_hash=hash_token(refresh_jwt),
        ip_address=ip_addr,
        user_agent=user_agent[:255] if user_agent else None,
        expires_at=utc_now() + timedelta(days=1), # Expire session in 1 day
    )
    db.add(user_session)
    await db.commit()

    access_jwt = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=membership.role,
        session_id=session_id,
    )
    csrf_token = generate_csrf_token()

    set_auth_cookies(
        response=response,
        access_token=access_jwt,
        refresh_token=refresh_jwt,
        csrf_token=csrf_token,
    )

    return {
        "user": user,
        "active_organization": org,
        "role": membership.role,
        "csrf_token": csrf_token,
    }

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

@router.post("/google", response_model=LoginResponse)
async def google_login(
    payload: GoogleAuthRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
) -> Any:
    try:
        idinfo = id_token.verify_oauth2_token(
            payload.id_token, 
            google_requests.Request(),
            get_settings().google_client_id if hasattr(get_settings(), 'google_client_id') else None
        )
        email = idinfo['email'].lower()
        
        # Check if user exists
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        
        if not user:
            # Create user
            user_id = f"usr_{secrets.token_hex(12)}"
            user = User(
                id=user_id,
                email=email,
                hashed_password=hash_password(secrets.token_hex(16)),
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            
            # Create Organization
            org_id = f"org_{secrets.token_hex(12)}"
            slug = await generate_unique_slug(db, f"{idinfo.get('given_name', 'User')}'s Workspace")
            org = Organization(
                id=org_id,
                name=f"{idinfo.get('given_name', 'User')}'s Workspace",
                workspace_type="individual",
                slug=slug,
                plan="free",
                is_active=True,
            )
            db.add(org)
            
            # Create Membership
            membership = OrganizationMembership(
                user_id=user_id,
                organization_id=org_id,
                role=UserRole.OWNER.value,
                status=MembershipStatus.ACTIVE.value,
                joined_at=utc_now(),
            )
            db.add(membership)
            await db.commit()
            
        else:
            # Get active org
            mem_result = await db.execute(
                select(OrganizationMembership, Organization)
                .join(Organization, OrganizationMembership.organization_id == Organization.id)
                .where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE.value
                )
            )
            row = mem_result.first()
            if not row:
                raise HTTPException(status_code=403, detail="No active organization found.")
            membership, org = row
            
        # Create User Session
        session_id = f"sess_{secrets.token_hex(16)}"
        refresh_jwt = create_refresh_token(
            user_id=user.id,
            org_id=org.id,
            role=membership.role,
            session_id=session_id,
        )
        
        ip_addr = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        user_session = UserSession(
            id=session_id,
            user_id=user.id,
            organization_id=org.id,
            refresh_token_hash=hash_token(refresh_jwt),
            ip_address=ip_addr,
            user_agent=user_agent[:255] if user_agent else None,
            expires_at=utc_now() + timedelta(days=get_settings().jwt_refresh_token_expire_days),
        )
        db.add(user_session)
        await db.commit()
        
        # Generate Access and CSRF tokens
        access_jwt = create_access_token(
            user_id=user.id,
            org_id=org.id,
            role=membership.role,
            session_id=session_id,
        )
        csrf_token = generate_csrf_token()
        
        set_auth_cookies(
            response=response,
            access_token=access_jwt,
            refresh_token=refresh_jwt,
            csrf_token=csrf_token,
        )
        
        return {
            "user": user,
            "active_organization": org,
            "role": membership.role,
            "csrf_token": csrf_token,
        }
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")


