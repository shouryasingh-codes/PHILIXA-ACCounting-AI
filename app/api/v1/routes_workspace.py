from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentPrincipal, Principal
from app.core.config import get_settings
from app.core.dependencies import get_email_adapter, get_notification_adapter
from app.services.notifications.email_adapter import EmailAdapter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    decode_jwt_token,
    hash_password,
    generate_csrf_token,
)
from app.api.v1.routes_auth import set_auth_cookies
from app.database.session import get_db
from app.models.enums import MembershipStatus, UserRole
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace_invite import WorkspaceInvite
from app.schemas.workspace import (
    MemberRead,
    WorkspaceInviteAcceptResponse,
    WorkspaceInviteRequest,
    WorkspaceInviteResponse,
    WorkspaceItem,
    WorkspaceMemberDeleteResponse,
    WorkspaceMemberRoleUpdateRequest,
    WorkspaceMemberRoleUpdateResponse,
    WorkspaceSwitchRequest,
    WorkspaceSwitchResponse,
    AcceptInviteRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces",
    tags=["workspaces"],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def send_invite_email(
    recipient: str,
    raw_token: str,
    inviter_email: str,
    org_name: str,
    adapter: Optional[EmailAdapter] = None,
) -> None:
    try:
        if adapter is None:
            adapter = get_email_adapter()
        subject = f"Invitation to join '{org_name}' on Philixa"
        body = (
            f"You have been invited by {inviter_email} to join '{org_name}' on Philixa! "
            f"Accept your invitation here: http://localhost:8000/?action=invite-accept&token={raw_token}"
        )
        if hasattr(adapter, "send_message"):
            await adapter.send_message(to_destination=recipient, message_content=body, subject=subject)
        elif hasattr(adapter, "send_notification"):
            await adapter.send_notification(to_destination=recipient, message_content=body, subject=subject)
    except Exception as exc:
        logger.warning(f"Failed to send invite email to {recipient}: {exc}")


@router.get("", response_model=list[WorkspaceItem])
async def list_workspaces(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == principal.user_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Organization.is_active.is_(True),
        )
        .order_by(Organization.name.asc())
    )
    results = (await db.execute(stmt)).all()

    workspaces = []
    for mem, org in results:
        workspaces.append(
            WorkspaceItem(
                id=org.id,
                name=org.name,
                slug=org.slug,
                workspace_type=org.workspace_type,
                plan=org.plan,
                role=mem.role,
                status=mem.status,
                is_active=org.is_active,
                is_current=(org.id == principal.organization_id),
                created_at=org.created_at,
                updated_at=org.updated_at,
            )
        )
    return workspaces


@router.post("/switch", response_model=WorkspaceSwitchResponse)
async def switch_workspace(
    payload: WorkspaceSwitchRequest,
    response: Response,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    target_org_id = payload.organization_id.strip()

    # 1. Verify membership in target organization
    stmt = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == principal.user_id,
            OrganizationMembership.organization_id == target_org_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Organization.is_active.is_(True),
        )
    )
    result = (await db.execute(stmt)).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized workspace switch. You are not an active member of this organization.",
        )

    target_membership, target_org = result

    # 2. Issue new tokens scoped to target organization
    new_access_jwt = create_access_token(
        user_id=principal.user_id,
        org_id=target_org.id,
        role=target_membership.role,
        session_id=principal.session_id,
    )
    new_refresh_jwt = create_refresh_token(
        user_id=principal.user_id,
        org_id=target_org.id,
        role=target_membership.role,
        session_id=principal.session_id,
    )

    # 3. Update UserSession in database if session exists
    if principal.session_id:
        session = await db.get(UserSession, principal.session_id)
        if session:
            session.organization_id = target_org.id
            session.refresh_token_hash = hash_token(new_refresh_jwt)
            session.updated_at = utc_now()

    await db.commit()

    # 4. Set updated cookies
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=new_access_jwt,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_jwt,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/",
    )

    return {
        "message": "Switched workspace successfully.",
        "active_organization": {
            "id": target_org.id,
            "name": target_org.name,
            "slug": target_org.slug,
            "workspace_type": target_org.workspace_type,
            "plan": target_org.plan,
        },
        "role": target_membership.role,
        "access_token": new_access_jwt,
    }


@router.post("/invite", response_model=WorkspaceInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: WorkspaceInviteRequest,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
    email_adapter: EmailAdapter = Depends(get_email_adapter),
) -> Any:
    # 1. RBAC Guard: Only Owner or Admin
    if principal.role.lower() not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners and admins can send invitations.",
        )

    invited_email = payload.email.strip().lower()
    invited_role = payload.role.strip().lower()
    if invited_role not in ("owner", "admin", "member"):
        invited_role = "member"

    # 2. Check if user is already an active member of this organization
    target_user = (await db.execute(select(User).where(User.email == invited_email))).scalar_one_or_none()
    if target_user:
        existing_mem = (await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == target_user.id,
                OrganizationMembership.organization_id == principal.organization_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            )
        )).scalar_one_or_none()
        if existing_mem:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already an active member of this workspace.",
            )

    # 3. Create WorkspaceInvite
    raw_token = secrets.token_urlsafe(32)
    token_h = hash_token(raw_token)
    expires_at = utc_now() + timedelta(days=7)

    invite = WorkspaceInvite(
        id=secrets.token_hex(16),
        organization_id=principal.organization_id,
        invited_email=invited_email,
        role=invited_role,
        token_hash=token_h,
        invited_by_user_id=principal.user_id,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()

    # 4. Dispatch Email
    await send_invite_email(
        recipient=invited_email,
        raw_token=raw_token,
        inviter_email=principal.user.email,
        org_name=principal.organization.name,
        adapter=email_adapter,
    )

    return {
        "message": "Invitation sent successfully.",
        "invite_id": invite.id,
        "email": invited_email,
        "role": invited_role,
        "expires_at": expires_at,
    }


@router.post("/invite/accept", response_model=WorkspaceInviteAcceptResponse)
async def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not payload.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token is required.",
        )

    t_hash = hash_token(payload.token)
    invite = (await db.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == t_hash)
    )).scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token.",
        )

    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has already been accepted.",
        )

    now = utc_now()
    expires_at = invite.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is not None and expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has expired.",
        )

    # Resolve active user from cookie if present
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    active_user = None
    if token:
        try:
            jwt_payload = decode_jwt_token(token)
            user_id = jwt_payload.get("sub")
            if user_id:
                active_user = await db.get(User, user_id)
        except Exception:
            pass # Ignore invalid tokens during invite accept

    # Check if a user with this email already exists
    normalized_email = invite.invited_email.strip().lower()
    existing_user_by_email = (await db.execute(
        select(User).where(User.email == normalized_email)
    )).scalar_one_or_none()

    if active_user:
        target_user = active_user
    else:
        if existing_user_by_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please log in first.",
            )
        else:
            # Create a new user on the fly
            if not payload.password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A password is required to create your account.",
                )
            
            new_user_id = f"usr_{secrets.token_hex(12)}"
            target_user = User(
                id=new_user_id,
                email=normalized_email,
                hashed_password=hash_password(payload.password),
                is_active=True,
                is_verified=True,
            )
            db.add(target_user)
            
            # Create User Session
            session_id = f"sess_{secrets.token_hex(16)}"
            refresh_jwt = create_refresh_token(
                user_id=target_user.id,
                org_id=invite.organization_id,
                role=invite.role,
                session_id=session_id,
            )
            refresh_hash = hash_token(refresh_jwt)

            ip_addr = request.client.host if request.client else None
            user_agent = request.headers.get("User-Agent")

            user_session = UserSession(
                id=session_id,
                user_id=target_user.id,
                organization_id=invite.organization_id,
                refresh_token_hash=refresh_hash,
                ip_address=ip_addr,
                user_agent=user_agent[:255] if user_agent else None,
                expires_at=utc_now() + timedelta(days=get_settings().jwt_refresh_token_expire_days),
            )
            db.add(user_session)
            
            # Set auth cookies
            access_jwt = create_access_token(
                user_id=target_user.id,
                org_id=invite.organization_id,
                role=invite.role,
                session_id=session_id,
            )
            csrf_token = generate_csrf_token()

            set_auth_cookies(
                response=response,
                access_token=access_jwt,
                refresh_token=refresh_jwt,
                csrf_token=csrf_token,
            )

    # Upsert OrganizationMembership
    existing_mem = (await db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == target_user.id,
            OrganizationMembership.organization_id == invite.organization_id,
        )
    )).scalar_one_or_none()

    if existing_mem:
        existing_mem.role = invite.role
        existing_mem.status = MembershipStatus.ACTIVE.value
        existing_mem.joined_at = utc_now()
    else:
        new_mem = OrganizationMembership(
            user_id=target_user.id,
            organization_id=invite.organization_id,
            role=invite.role,
            status=MembershipStatus.ACTIVE.value,
            invited_by=invite.invited_by_user_id,
            invited_at=invite.created_at,
            joined_at=utc_now(),
        )
        db.add(new_mem)

    invite.accepted_at = utc_now()
    await db.commit()

    return {
        "message": "Invitation accepted successfully.",
        "organization_id": invite.organization_id,
        "role": invite.role,
    }


@router.patch("/members/{member_user_id}/role", response_model=WorkspaceMemberRoleUpdateResponse)
async def update_member_role(
    member_user_id: str,
    payload: WorkspaceMemberRoleUpdateRequest,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 1. RBAC Guard: Only Owner can modify roles
    if principal.role.lower() != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can update member roles.",
        )

    new_role = payload.role.strip().lower()
    if new_role not in ("owner", "admin", "member"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Role must be owner, admin, or member.",
        )

    # 2. Find target membership
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == member_user_id,
        OrganizationMembership.organization_id == principal.organization_id,
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace member not found.",
        )

    # 3. Last Owner Protection
    if membership.role.lower() == "owner" and new_role != "owner":
        owner_count_stmt = select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.organization_id == principal.organization_id,
            OrganizationMembership.role == UserRole.OWNER.value,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
        )
        owner_count = await db.scalar(owner_count_stmt) or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last owner of the workspace.",
            )

    membership.role = new_role
    await db.commit()

    return {
        "message": "Member role updated successfully.",
        "user_id": member_user_id,
        "role": new_role,
    }


@router.delete("/members/{member_user_id}", response_model=WorkspaceMemberDeleteResponse)
async def remove_member(
    member_user_id: str,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 1. RBAC Guard: Owner or Admin
    if principal.role.lower() not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners and admins can remove members.",
        )

    # 2. Find target membership
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == member_user_id,
        OrganizationMembership.organization_id == principal.organization_id,
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace member not found.",
        )

    # 3. Admin Privilege Escalation Protection: Admin cannot remove Owner
    if principal.role.lower() == "admin" and membership.role.lower() == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot remove workspace owners.",
        )

    # 4. Last Owner Protection
    if membership.role.lower() == "owner":
        owner_count_stmt = select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.organization_id == principal.organization_id,
            OrganizationMembership.role == UserRole.OWNER.value,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
        )
        owner_count = await db.scalar(owner_count_stmt) or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last owner of the workspace.",
            )

    # 5. Revoke user sessions for this user in this organization
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id == member_user_id,
            UserSession.organization_id == principal.organization_id,
        )
    )

    # 6. Delete membership
    await db.delete(membership)
    await db.commit()

    return {
        "message": "Member removed successfully.",
        "user_id": member_user_id,
    }


@router.get("/members", response_model=list[MemberRead])
async def list_members(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    stmt = (
        select(OrganizationMembership, User)
        .join(User, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.organization_id == principal.organization_id)
        .order_by(OrganizationMembership.joined_at.asc())
    )
    results = (await db.execute(stmt)).all()

    members = []
    for mem, usr in results:
        members.append(
            MemberRead(
                user_id=usr.id,
                email=usr.email,
                role=mem.role,
                status=mem.status,
                joined_at=mem.joined_at,
            )
        )
    return members
