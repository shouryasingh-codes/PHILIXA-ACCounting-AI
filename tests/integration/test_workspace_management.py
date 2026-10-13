from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace_invite import WorkspaceInvite
from tests.conftest import (
    MockSMTPSink,
    create_test_token,
    generate_test_csrf_token,
    hash_password,
)


@pytest.mark.asyncio
class TestWorkspaceListingAndSwitching:
    async def test_list_user_workspaces_returns_all_memberships(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_ws_multi_01"
        email = "multi.workspace@test.com"
        
        user = User(id=user_id, email=email, hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        org1 = Organization(id="org_ws_01", name="Alpha Corp", slug="alpha-corp", workspace_type="company")
        org2 = Organization(id="org_ws_02", name="Beta LLC", slug="beta-llc", workspace_type="individual")
        
        mem1 = OrganizationMembership(user_id=user_id, organization_id="org_ws_01", role="owner")
        mem2 = OrganizationMembership(user_id=user_id, organization_id="org_ws_02", role="member")
        
        async_db_session.add_all([user, org1, org2, mem1, mem2])
        await async_db_session.commit()
        
        token = create_test_token(user_id=user_id, org_id="org_ws_01", role="owner")
        async_client.cookies.set("access_token", token)
        
        response = await async_client.get("/workspaces")
        assert response.status_code == 200
        workspaces = response.json()
        if isinstance(workspaces, dict) and "workspaces" in workspaces:
            workspaces = workspaces["workspaces"]
            
        org_ids = [ws["id"] for ws in workspaces]
        assert "org_ws_01" in org_ids
        assert "org_ws_02" in org_ids

    async def test_switch_workspace_success_updates_session(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_switch_01"
        session_id = "sess_switch_01"
        
        user = User(id=user_id, email="switcher@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        org1 = Organization(id="org_src_01", name="Source Org", slug="source-org", workspace_type="company")
        org2 = Organization(id="org_dst_02", name="Dest Org", slug="dest-org", workspace_type="company")
        
        mem1 = OrganizationMembership(user_id=user_id, organization_id="org_src_01", role="owner")
        mem2 = OrganizationMembership(user_id=user_id, organization_id="org_dst_02", role="admin")
        
        user_session = UserSession(
            id=session_id,
            user_id=user_id,
            organization_id="org_src_01",
            refresh_token_hash="hash_switch",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        
        async_db_session.add_all([user, org1, org2, mem1, mem2, user_session])
        await async_db_session.commit()
        
        token = create_test_token(user_id=user_id, org_id="org_src_01", role="owner", session_id=session_id)
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.post("/workspaces/switch", json={"organization_id": "org_dst_02"})
        assert response.status_code == 200
        
        # Verify active org updated in DB session
        await async_db_session.refresh(user_session)
        assert user_session.organization_id == "org_dst_02"

    async def test_switch_workspace_unauthorized_org_fails(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_switch_unauth"
        user = User(id=user_id, email="unauth@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        org1 = Organization(id="org_allowed_01", name="Allowed Org", slug="allowed-org", workspace_type="company")
        org_foreign = Organization(id="org_foreign_99", name="Foreign Org", slug="foreign-org", workspace_type="company")
        
        mem1 = OrganizationMembership(user_id=user_id, organization_id="org_allowed_01", role="owner")
        async_db_session.add_all([user, org1, org_foreign, mem1])
        await async_db_session.commit()
        
        token = create_test_token(user_id=user_id, org_id="org_allowed_01", role="owner")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        # Attempt to switch to an org the user is not a member of
        response = await async_client.post("/workspaces/switch", json={"organization_id": "org_foreign_99"})
        assert response.status_code in (403, 404), "Unauthorized workspace switch must be rejected"


@pytest.mark.asyncio
class TestWorkspaceInvitations:
    async def test_owner_can_invite_member_via_email(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
        mock_smtp: MockSMTPSink,
    ) -> None:
        owner_id = "usr_owner_inviter"
        org_id = "org_invite_01"
        
        org = Organization(id=org_id, name="Invite Test Org", slug="invite-org", workspace_type="company")
        owner = User(id=owner_id, email="owner@invitetest.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner")
        
        async_db_session.add_all([org, owner, mem])
        await async_db_session.commit()
        
        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        invite_email = "newmember@invitetest.com"
        response = await async_client.post("/workspaces/invite", json={"email": invite_email, "role": "member"})
        assert response.status_code in (200, 201)
        
        # Verify invite recorded in DB
        invite = (await async_db_session.execute(
            select(WorkspaceInvite).where(
                WorkspaceInvite.organization_id == org_id,
                WorkspaceInvite.invited_email == invite_email,
            )
        )).scalar_one_or_none()
        assert invite is not None
        assert invite.role == "member"
        exp_dt = invite.expires_at.replace(tzinfo=timezone.utc) if invite.expires_at.tzinfo is None else invite.expires_at
        assert exp_dt > datetime.now(timezone.utc)

    async def test_member_cannot_invite_others_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        member_id = "usr_member_inviter"
        org_id = "org_no_invite_01"
        
        org = Organization(id=org_id, name="No Invite Org", slug="no-invite-org", workspace_type="company")
        member = User(id=member_id, email="member@noinvite.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member")
        
        async_db_session.add_all([org, member, mem])
        await async_db_session.commit()
        
        token = create_test_token(user_id=member_id, org_id=org_id, role="member")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.post("/workspaces/invite", json={"email": "target@test.com", "role": "member"})
        assert response.status_code == 403, "Member role must not be permitted to send invites"

    async def test_accept_invite_creates_membership(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        org_id = "org_accept_01"
        new_user_id = "usr_acceptor_01"
        email = "acceptor@test.com"
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        org = Organization(id=org_id, name="Accept Org", slug="accept-org", workspace_type="company")
        user = User(id=new_user_id, email=email, hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        
        invite = WorkspaceInvite(
            id=secrets.token_hex(16),
            organization_id=org_id,
            invited_email=email,
            role="member",
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            invited_by_user_id="usr_some_owner",
        )
        
        async_db_session.add_all([org, user, invite])
        await async_db_session.commit()
        
        token = create_test_token(user_id=new_user_id, org_id=org_id, role="member")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.post(f"/workspaces/invite/accept?token={raw_token}")
        assert response.status_code in (200, 201)
        
        # Verify membership created
        membership = (await async_db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == new_user_id,
                OrganizationMembership.organization_id == org_id,
            )
        )).scalar_one_or_none()
        assert membership is not None
        assert membership.role == "member"


@pytest.mark.asyncio
class TestWorkspaceMemberManagement:
    async def test_owner_can_update_member_role(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_role_mgr_owner"
        member_id = "usr_role_mgr_target"
        org_id = "org_role_mgmt_01"
        
        org = Organization(id=org_id, name="Role Org", slug="role-org", workspace_type="company")
        owner = User(id=owner_id, email="owner@rolemgmt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        target = User(id=member_id, email="target@rolemgmt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        
        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner")
        mem_target = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member")
        
        async_db_session.add_all([org, owner, target, mem_owner, mem_target])
        await async_db_session.commit()
        
        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.patch(f"/workspaces/members/{member_id}/role", json={"role": "admin"})
        assert response.status_code == 200
        
        await async_db_session.refresh(mem_target)
        assert mem_target.role == "admin"

    async def test_admin_cannot_update_roles_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        admin_id = "usr_role_admin"
        member_id = "usr_role_member"
        org_id = "org_admin_block_01"
        
        org = Organization(id=org_id, name="Admin Block Org", slug="admin-block-org", workspace_type="company")
        admin = User(id=admin_id, email="admin@rolemgmt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        member = User(id=member_id, email="member@rolemgmt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        
        mem_admin = OrganizationMembership(user_id=admin_id, organization_id=org_id, role="admin")
        mem_member = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member")
        
        async_db_session.add_all([org, admin, member, mem_admin, mem_member])
        await async_db_session.commit()
        
        token = create_test_token(user_id=admin_id, org_id=org_id, role="admin")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        # Admin cannot change roles (owner only per R3)
        response = await async_client.patch(f"/workspaces/members/{member_id}/role", json={"role": "admin"})
        assert response.status_code == 403

    async def test_owner_can_remove_member(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_del_owner"
        member_id = "usr_del_target"
        org_id = "org_del_01"
        
        org = Organization(id=org_id, name="Delete Org", slug="delete-org", workspace_type="company")
        owner = User(id=owner_id, email="owner@delete.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        member = User(id=member_id, email="member@delete.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        
        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner")
        mem_member = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member")
        
        async_db_session.add_all([org, owner, member, mem_owner, mem_member])
        await async_db_session.commit()
        
        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        async_client.cookies.set("access_token", token)
        csrf_token = generate_test_csrf_token()
        async_client.cookies.set("csrf_token", csrf_token)
        async_client.headers["X-CSRF-Token"] = csrf_token
        
        response = await async_client.delete(f"/workspaces/members/{member_id}")
        assert response.status_code in (200, 204)
        
        # Verify membership removed
        deleted_mem = (await async_db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == member_id,
                OrganizationMembership.organization_id == org_id,
            )
        )).scalar_one_or_none()
        assert deleted_mem is None
