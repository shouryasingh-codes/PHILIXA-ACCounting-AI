from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Callable

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_jwt_token
from app.database.session import get_db
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace_invite import WorkspaceInvite


@dataclass(frozen=True)
class Principal:
    user: User
    organization: Organization
    role: str  # "owner" | "admin" | "member"
    session_id: str

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def organization_id(self) -> str:
        return self.organization.id


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """
    Core FastAPI authentication dependency.
    1. Checks for legacy API Key header (X-API-Key).
    2. Reads `access_token` from cookie (or `Authorization: Bearer <token>` header).
    3. Decodes and verifies HS256 JWT claims.
    4. Resolves and validates User, Organization, and OrganizationMembership.
    5. Validates UserSession revocation if session record exists in DB.
    """
    # 0. Legacy / Dev API Key Header Authentication
    api_key_header = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    settings = get_settings()
    if settings.app_env != 'production' and api_key_header and api_key_header in (settings.api_key, settings.demo_api_key, "dev-api-key"):
        dev_user = (await db.execute(select(User).order_by(User.id.asc()))).scalars().first()
        dev_org = (await db.execute(select(Organization).order_by(Organization.id.asc()))).scalars().first()
        if not dev_user:
            dev_user = User(
                id="dev_user_01",
                email="dev@philixa.com",
                hashed_password="hash",
                is_active=True,
                is_verified=True,
            )
            db.add(dev_user)
        if not dev_org:
            dev_org = Organization(
                id="dev_org_01",
                name="Dev Org",
                slug="dev-org",
                workspace_type="company",
                plan="free",
                is_active=True,
            )
            db.add(dev_org)
        
        dev_mem = (await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == dev_user.id,
                OrganizationMembership.organization_id == dev_org.id,
            )
        )).scalar_one_or_none()
        if not dev_mem:
            dev_mem = OrganizationMembership(
                user_id=dev_user.id,
                organization_id=dev_org.id,
                role="owner",
                status="active",
            )
            db.add(dev_mem)
        await db.commit()
        return Principal(
            user=dev_user,
            organization=dev_org,
            role=dev_mem.role,
            session_id="dev-session",
        )

    # 1. Extract Token
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    # 2. Decode JWT
    try:
        payload = decode_jwt_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from exc

    user_id: str | None = payload.get("sub")
    org_id: str | None = payload.get("org_id")
    session_id: str = payload.get("sid", "")
    token_type: str = payload.get("type", "access")

    if not user_id or not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing mandatory identity claims.",
        )

    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for access authentication.",
        )

    # 3. Validate User
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is deactivated.",
        )

    # 4. Validate Organization
    org = await db.get(Organization, org_id)
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization not found or inactive.",
        )

    # 5. Validate Organization Membership
    membership_stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.organization_id == org.id,
    )
    membership = (await db.execute(membership_stmt)).scalar_one_or_none()
    if membership and membership.status == "active":
        effective_role = membership.role
    else:
        # Check if user has an active membership in any other organization
        any_mem_stmt = (
            select(OrganizationMembership, Organization)
            .join(Organization, OrganizationMembership.organization_id == Organization.id)
            .where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.status == "active",
                Organization.is_active.is_(True),
            )
        )
        any_result = (await db.execute(any_mem_stmt)).first()
        if any_result:
            any_mem, any_org = any_result
            effective_role = any_mem.role
        else:
            # Check if there is an active invite for this user and organization
            invite_stmt = select(WorkspaceInvite).where(
                WorkspaceInvite.organization_id == org.id,
                WorkspaceInvite.invited_email == user.email,
                WorkspaceInvite.accepted_at.is_(None),
            )
            invite = (await db.execute(invite_stmt)).scalar_one_or_none()
            if invite:
                effective_role = invite.role
            elif payload.get("role"):
                effective_role = payload.get("role")
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User does not have an active membership in this workspace.",
                )

    # 6. Validate Session Revocation (if session record is registered)
    if session_id:
        session = await db.get(UserSession, session_id)
        if session is not None:
            now = datetime.now(timezone.utc)
            expires_at = session.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if session.revoked_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session has been revoked.",
                )
            if expires_at is not None and expires_at < now:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session has expired.",
                )
            if session.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session user mismatch.",
                )

    return Principal(
        user=user,
        organization=org,
        role=effective_role,
        session_id=session_id,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*allowed_roles: str) -> Callable[[Principal], Principal]:
    """Dependency helper for role-based access control."""
    def _role_checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        normalized_allowed = [r.lower() for r in allowed_roles]
        if principal.role.lower() not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires role in: {', '.join(allowed_roles)}.",
            )
        return principal
    return _role_checker


require_owner = require_roles("owner")
require_admin_or_owner = require_roles("owner", "admin")
