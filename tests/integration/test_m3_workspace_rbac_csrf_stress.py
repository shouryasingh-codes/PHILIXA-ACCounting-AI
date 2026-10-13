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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import generate_csrf_token, verify_csrf_token
from app.models.enums import MembershipStatus, UserRole
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
class TestWorkspaceRBACBoundariesEmpirical:
    """
    Empirical stress-testing of RBAC boundaries:
    - Only Owner can update roles. Admin and Member attempts MUST return 403.
    - Owner and Admin can remove members. Member attempts MUST return 403.
    - Admin CANNOT remove an Owner (Privilege Escalation protection) MUST return 403.
    - Owner and Admin can invite members. Member attempts MUST return 403.
    - Non-existent or cross-tenant member targets MUST return 404.
    """

    async def test_owner_can_update_member_role_to_admin_and_back(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_rbac_owner_1"
        target_id = "usr_rbac_target_1"
        org_id = "org_rbac_01"

        org = Organization(id=org_id, name="RBAC Test Org 1", slug="rbac-org-1", workspace_type="company")
        owner = User(id=owner_id, email="owner1@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        target = User(id=target_id, email="target1@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem_target = OrganizationMembership(user_id=target_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, target, mem_owner, mem_target])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        # Promote member to admin
        res1 = await async_client.patch(f"/workspaces/members/{target_id}/role", json={"role": "admin"})
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}: {res1.text}"
        await async_db_session.refresh(mem_target)
        assert mem_target.role == "admin"

        # Demote back to member
        res2 = await async_client.patch(f"/workspaces/members/{target_id}/role", json={"role": "member"})
        assert res2.status_code == 200, f"Expected 200, got {res2.status_code}: {res2.text}"
        await async_db_session.refresh(mem_target)
        assert mem_target.role == "member"

    async def test_admin_cannot_update_member_role_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        admin_id = "usr_rbac_admin_1"
        target_id = "usr_rbac_target_2"
        org_id = "org_rbac_02"

        org = Organization(id=org_id, name="RBAC Test Org 2", slug="rbac-org-2", workspace_type="company")
        admin = User(id=admin_id, email="admin1@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        target = User(id=target_id, email="target2@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_admin = OrganizationMembership(user_id=admin_id, organization_id=org_id, role="admin", status=MembershipStatus.ACTIVE.value)
        mem_target = OrganizationMembership(user_id=target_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, admin, target, mem_admin, mem_target])
        await async_db_session.commit()

        token = create_test_token(user_id=admin_id, org_id=org_id, role="admin")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.patch(f"/workspaces/members/{target_id}/role", json={"role": "admin"})
        assert response.status_code == 403, f"Admin role updating must return 403 Forbidden, got {response.status_code}"
        assert "Only workspace owners can update member roles" in response.text

    async def test_member_cannot_update_member_role_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        member_id = "usr_rbac_member_1"
        target_id = "usr_rbac_target_3"
        org_id = "org_rbac_03"

        org = Organization(id=org_id, name="RBAC Test Org 3", slug="rbac-org-3", workspace_type="company")
        member = User(id=member_id, email="member1@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        target = User(id=target_id, email="target3@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_member = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)
        mem_target = OrganizationMembership(user_id=target_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, member, target, mem_member, mem_target])
        await async_db_session.commit()

        token = create_test_token(user_id=member_id, org_id=org_id, role="member")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.patch(f"/workspaces/members/{target_id}/role", json={"role": "owner"})
        assert response.status_code == 403, f"Member role updating must return 403 Forbidden, got {response.status_code}"

    async def test_invalid_role_update_rejected_with_400(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_rbac_owner_inv"
        target_id = "usr_rbac_target_inv"
        org_id = "org_rbac_inv"

        org = Organization(id=org_id, name="RBAC Invalid Role Org", slug="rbac-inv-role-org", workspace_type="company")
        owner = User(id=owner_id, email="owner_inv@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        target = User(id=target_id, email="target_inv@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem_target = OrganizationMembership(user_id=target_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, target, mem_owner, mem_target])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.patch(f"/workspaces/members/{target_id}/role", json={"role": "superadmin"})
        assert response.status_code == 400
        assert "Invalid role" in response.text

    async def test_admin_cannot_delete_owner_returns_403_escalation_guard(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_rbac_owner_target"
        admin_id = "usr_rbac_admin_attacker"
        org_id = "org_rbac_escalate"

        org = Organization(id=org_id, name="RBAC Escalate Org", slug="rbac-esc-org", workspace_type="company")
        owner = User(id=owner_id, email="owner_tgt@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        admin = User(id=admin_id, email="admin_atk@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem_admin = OrganizationMembership(user_id=admin_id, organization_id=org_id, role="admin", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, admin, mem_owner, mem_admin])
        await async_db_session.commit()

        token = create_test_token(user_id=admin_id, org_id=org_id, role="admin")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        # Admin attempts to delete Owner
        response = await async_client.delete(f"/workspaces/members/{owner_id}")
        assert response.status_code == 403, f"Admin must NOT be allowed to delete owner, got {response.status_code}"
        assert "Admins cannot remove workspace owners" in response.text

    async def test_admin_can_delete_regular_member(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_rbac_owner_root"
        admin_id = "usr_rbac_admin_exec"
        member_id = "usr_rbac_member_target"
        org_id = "org_rbac_admin_del"

        org = Organization(id=org_id, name="RBAC Admin Del Org", slug="rbac-adm-del-org", workspace_type="company")
        owner = User(id=owner_id, email="owner_root@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        admin = User(id=admin_id, email="admin_exec@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        member = User(id=member_id, email="member_tgt@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_owner = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem_admin = OrganizationMembership(user_id=admin_id, organization_id=org_id, role="admin", status=MembershipStatus.ACTIVE.value)
        mem_member = OrganizationMembership(user_id=member_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        user_session = UserSession(
            id="sess_member_del_1",
            user_id=member_id,
            organization_id=org_id,
            refresh_token_hash="hash_mem_del",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        async_db_session.add_all([org, owner, admin, member, mem_owner, mem_admin, mem_member, user_session])
        await async_db_session.commit()

        token = create_test_token(user_id=admin_id, org_id=org_id, role="admin")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        # Admin deletes regular member
        response = await async_client.delete(f"/workspaces/members/{member_id}")
        assert response.status_code == 200

        # Verify membership removed
        deleted_mem = (await async_db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == member_id,
                OrganizationMembership.organization_id == org_id,
            )
        )).scalar_one_or_none()
        assert deleted_mem is None

        # Verify user session in that org revoked/deleted
        deleted_sess = (await async_db_session.execute(
            select(UserSession).where(
                UserSession.user_id == member_id,
                UserSession.organization_id == org_id,
            )
        )).scalar_one_or_none()
        assert deleted_sess is None

    async def test_member_cannot_delete_other_members_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        member1_id = "usr_rbac_mem_atk"
        member2_id = "usr_rbac_mem_tgt"
        org_id = "org_rbac_mem_del"

        org = Organization(id=org_id, name="RBAC Mem Del Org", slug="rbac-mem-del-org", workspace_type="company")
        m1 = User(id=member1_id, email="m1@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        m2 = User(id=member2_id, email="m2@rbac.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem1 = OrganizationMembership(user_id=member1_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)
        mem2 = OrganizationMembership(user_id=member2_id, organization_id=org_id, role="member", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, m1, m2, mem1, mem2])
        await async_db_session.commit()

        token = create_test_token(user_id=member1_id, org_id=org_id, role="member")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.delete(f"/workspaces/members/{member2_id}")
        assert response.status_code == 403, f"Member cannot delete others, got {response.status_code}"

    async def test_cross_tenant_member_role_and_delete_return_404(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_a_id = "usr_owner_a_xt"
        user_b_id = "usr_user_b_xt"
        org_a_id = "org_xt_a"
        org_b_id = "org_xt_b"

        org_a = Organization(id=org_a_id, name="Org A XT", slug="org-a-xt", workspace_type="company")
        org_b = Organization(id=org_b_id, name="Org B XT", slug="org-b-xt", workspace_type="company")
        user_a = User(id=owner_a_id, email="owner_a@xt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        user_b = User(id=user_b_id, email="user_b@xt.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem_a = OrganizationMembership(user_id=owner_a_id, organization_id=org_a_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem_b = OrganizationMembership(user_id=user_b_id, organization_id=org_b_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org_a, org_b, user_a, user_b, mem_a, mem_b])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_a_id, org_id=org_a_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        # Owner A attempts to update role of user B who is NOT in Org A
        res_role = await async_client.patch(f"/workspaces/members/{user_b_id}/role", json={"role": "admin"})
        assert res_role.status_code == 404, f"Cross-tenant role update must return 404, got {res_role.status_code}"

        # Owner A attempts to delete user B who is NOT in Org A
        res_del = await async_client.delete(f"/workspaces/members/{user_b_id}")
        assert res_del.status_code == 404, f"Cross-tenant delete member must return 404, got {res_del.status_code}"


@pytest.mark.asyncio
class TestLastOwnerInvariantPreservationEmpirical:
    """
    Empirical stress-testing of the Last-Owner invariant:
    - A workspace MUST always have at least one active owner.
    - Demoting or deleting the sole owner of a workspace MUST return 400 Bad Request.
    - When multiple owners exist, demotion and deletion are permitted down to exactly one owner.
    """

    async def test_sole_owner_demoting_self_to_admin_fails_with_400(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_sole_owner_01"
        org_id = "org_sole_01"

        org = Organization(id=org_id, name="Sole Owner Org 1", slug="sole-owner-org-1", workspace_type="company")
        owner = User(id=owner_id, email="sole1@owner.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.patch(f"/workspaces/members/{owner_id}/role", json={"role": "admin"})
        assert response.status_code == 400, f"Demoting sole owner must return 400, got {response.status_code}"
        assert "Cannot demote the last owner of the workspace" in response.text

        # Verify role unchanged in DB
        await async_db_session.refresh(mem)
        assert mem.role == "owner"

    async def test_sole_owner_demoting_self_to_member_fails_with_400(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_sole_owner_02"
        org_id = "org_sole_02"

        org = Organization(id=org_id, name="Sole Owner Org 2", slug="sole-owner-org-2", workspace_type="company")
        owner = User(id=owner_id, email="sole2@owner.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.patch(f"/workspaces/members/{owner_id}/role", json={"role": "member"})
        assert response.status_code == 400
        assert "Cannot demote the last owner of the workspace" in response.text

    async def test_sole_owner_deleting_self_fails_with_400(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        owner_id = "usr_sole_owner_03"
        org_id = "org_sole_03"

        org = Organization(id=org_id, name="Sole Owner Org 3", slug="sole-owner-org-3", workspace_type="company")
        owner = User(id=owner_id, email="sole3@owner.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=owner_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, owner, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=owner_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.delete(f"/workspaces/members/{owner_id}")
        assert response.status_code == 400, f"Deleting sole owner must return 400, got {response.status_code}"
        assert "Cannot remove the last owner of the workspace" in response.text

        # Verify membership intact in DB
        await async_db_session.refresh(mem)
        assert mem is not None

    async def test_multi_owner_demotion_and_deletion_lifecycle_preserves_invariant(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        """
        Setup: Org with Owner 1 and Owner 2.
        1. Owner 1 demotes Owner 2 to Admin -> 200 OK (Owner 1 is now sole owner).
        2. Owner 1 attempts to demote Owner 1 -> 400 Bad Request.
        3. Owner 1 promotes Owner 2 back to Owner -> 200 OK (2 owners again).
        4. Owner 1 deletes Owner 2 -> 200 OK (Owner 1 is now sole owner).
        5. Owner 1 attempts to delete Owner 1 -> 400 Bad Request.
        """
        owner1_id = "usr_multi_owner_1"
        owner2_id = "usr_multi_owner_2"
        org_id = "org_multi_owner_01"

        org = Organization(id=org_id, name="Multi Owner Org", slug="multi-owner-org", workspace_type="company")
        u1 = User(id=owner1_id, email="o1@multi.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        u2 = User(id=owner2_id, email="o2@multi.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem1 = OrganizationMembership(user_id=owner1_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem2 = OrganizationMembership(user_id=owner2_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, u1, u2, mem1, mem2])
        await async_db_session.commit()

        token1 = create_test_token(user_id=owner1_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token1)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        # Step 1: Demote Owner 2 to Admin -> Success
        res1 = await async_client.patch(f"/workspaces/members/{owner2_id}/role", json={"role": "admin"})
        assert res1.status_code == 200
        await async_db_session.refresh(mem2)
        assert mem2.role == "admin"

        # Step 2: Attempt to demote Owner 1 -> Failure (sole owner)
        res2 = await async_client.patch(f"/workspaces/members/{owner1_id}/role", json={"role": "admin"})
        assert res2.status_code == 400
        assert "Cannot demote the last owner" in res2.text

        # Step 3: Promote Owner 2 back to Owner -> Success
        res3 = await async_client.patch(f"/workspaces/members/{owner2_id}/role", json={"role": "owner"})
        assert res3.status_code == 200
        await async_db_session.refresh(mem2)
        assert mem2.role == "owner"

        # Step 4: Owner 1 deletes Owner 2 -> Success
        res4 = await async_client.delete(f"/workspaces/members/{owner2_id}")
        assert res4.status_code == 200

        # Step 5: Owner 1 attempts to delete Owner 1 -> Failure (sole owner)
        res5 = await async_client.delete(f"/workspaces/members/{owner1_id}")
        assert res5.status_code == 400
        assert "Cannot remove the last owner" in res5.text


@pytest.mark.asyncio
class TestCSRFProtectionEmpirical:
    """
    Empirical stress-testing of CSRF protection:
    - Safe methods (GET, HEAD, OPTIONS) do not require X-CSRF-Token.
    - Mutating methods (POST, PUT, PATCH, DELETE) with session cookie:
      - Missing X-CSRF-Token header -> 403 Forbidden.
      - Mismatched/tampered X-CSRF-Token header -> 403 Forbidden.
      - Empty string X-CSRF-Token header -> 403 Forbidden.
      - Missing csrf_token cookie -> 403 Forbidden.
      - Matching double-submit tokens -> 200 OK / processed.
    - Exempt paths (e.g. /auth/login, /auth/register) do not require CSRF header.
    """

    async def test_mutating_request_missing_csrf_header_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_csrf_test_01"
        org_id = "org_csrf_01"

        org = Organization(id=org_id, name="CSRF Org", slug="csrf-org", workspace_type="company")
        user = User(id=user_id, email="csrf1@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        csrf_tok = generate_test_csrf_token()
        
        # Set session cookies BUT DO NOT SET X-CSRF-Token header
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers.pop("X-CSRF-Token", None)
        async_client.headers.pop("x-csrf-token", None)

        response = await async_client.post("/workspaces/switch", json={"organization_id": org_id})
        assert response.status_code == 403, f"Mutating request without CSRF header MUST return 403, got {response.status_code}"
        assert "CSRF token validation failed" in response.text

    async def test_mutating_request_tampered_csrf_header_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_csrf_test_02"
        org_id = "org_csrf_02"

        org = Organization(id=org_id, name="CSRF Org 2", slug="csrf-org-2", workspace_type="company")
        user = User(id=user_id, email="csrf2@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        cookie_csrf = generate_test_csrf_token()
        attacker_csrf = generate_test_csrf_token()

        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", cookie_csrf)
        async_client.headers["X-CSRF-Token"] = attacker_csrf  # Mismatched/tampered header

        response = await async_client.post("/workspaces/switch", json={"organization_id": org_id})
        assert response.status_code == 403, f"Mismatched CSRF header MUST return 403, got {response.status_code}"
        assert "CSRF token validation failed" in response.text

    async def test_mutating_request_empty_csrf_header_returns_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_csrf_test_03"
        org_id = "org_csrf_03"

        org = Organization(id=org_id, name="CSRF Org 3", slug="csrf-org-3", workspace_type="company")
        user = User(id=user_id, email="csrf3@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        cookie_csrf = generate_test_csrf_token()

        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", cookie_csrf)
        async_client.headers["X-CSRF-Token"] = ""  # Empty string

        response = await async_client.post("/workspaces/switch", json={"organization_id": org_id})
        assert response.status_code == 403, f"Empty CSRF header MUST return 403, got {response.status_code}"

    async def test_patch_and_delete_endpoints_protected_by_csrf(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_csrf_test_04"
        org_id = "org_csrf_04"

        org = Organization(id=org_id, name="CSRF Org 4", slug="csrf-org-4", workspace_type="company")
        user = User(id=user_id, email="csrf4@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", generate_test_csrf_token())
        # Clear header
        async_client.headers.pop("X-CSRF-Token", None)

        # Test PATCH
        res_patch = await async_client.patch(f"/workspaces/members/{user_id}/role", json={"role": "admin"})
        assert res_patch.status_code == 403, "PATCH without CSRF header MUST return 403"

        # Test DELETE
        res_del = await async_client.delete(f"/workspaces/members/{user_id}")
        assert res_del.status_code == 403, "DELETE without CSRF header MUST return 403"

    async def test_safe_get_request_passes_and_seeds_csrf_cookie(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_csrf_get_01"
        org_id = "org_csrf_get_01"

        org = Organization(id=org_id, name="CSRF GET Org", slug="csrf-get-org", workspace_type="company")
        user = User(id=user_id, email="csrf_get@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
        mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_id, role="owner")
        async_client.cookies.clear()
        async_client.cookies.set("access_token", token)
        async_client.headers.pop("X-CSRF-Token", None)

        response = await async_client.get("/workspaces")
        assert response.status_code == 200
        # Check that GET requests seed csrf_token cookie
        assert "csrf_token" in response.cookies

    async def test_csrf_exempt_endpoints_bypass_validation(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        # Register and login are exempt
        email = "csrf_exempt@test.com"
        password = "Password123!"
        
        async_client.cookies.clear()
        async_client.headers.pop("X-CSRF-Token", None)

        reg_resp = await async_client.post("/auth/register", json={
            "email": email,
            "password": password,
            "workspace_name": "Exempt Org",
            "workspace_type": "company",
        })
        assert reg_resp.status_code in (200, 201), f"Register should not be blocked by CSRF: {reg_resp.status_code}"


@pytest.mark.asyncio
class TestWorkspaceSwitchingAndCrossTenantIsolationEmpirical:
    """
    Empirical stress-testing of workspace switching and tenant isolation:
    - Attempting to switch to an organization where user has no membership -> 403 Forbidden.
    - Attempting to switch to an inactive organization -> 403 Forbidden.
    - Valid switch updates tokens, session record, and active organization.
    """

    async def test_switch_workspace_to_unauthorized_org_fails_with_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_sw_unauth_01"
        org_allowed = "org_sw_allowed"
        org_foreign = "org_sw_foreign"

        org1 = Organization(id=org_allowed, name="Allowed Org", slug="allowed-org", workspace_type="company", is_active=True)
        org2 = Organization(id=org_foreign, name="Foreign Org", slug="foreign-org", workspace_type="company", is_active=True)
        user = User(id=user_id, email="sw_unauth@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem = OrganizationMembership(user_id=user_id, organization_id=org_allowed, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org1, org2, user, mem])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_allowed, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.post("/workspaces/switch", json={"organization_id": org_foreign})
        assert response.status_code == 403
        assert "Unauthorized workspace switch" in response.text

    async def test_switch_workspace_to_inactive_org_fails_with_403(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_sw_inactive_01"
        org_active = "org_sw_act"
        org_inactive = "org_sw_inact"

        org1 = Organization(id=org_active, name="Active Org", slug="active-org", workspace_type="company", is_active=True)
        org2 = Organization(id=org_inactive, name="Inactive Org", slug="inactive-org", workspace_type="company", is_active=False)
        user = User(id=user_id, email="sw_inact@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem1 = OrganizationMembership(user_id=user_id, organization_id=org_active, role="owner", status=MembershipStatus.ACTIVE.value)
        mem2 = OrganizationMembership(user_id=user_id, organization_id=org_inactive, role="owner", status=MembershipStatus.ACTIVE.value)

        async_db_session.add_all([org1, org2, user, mem1, mem2])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org_active, role="owner")
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.post("/workspaces/switch", json={"organization_id": org_inactive})
        assert response.status_code == 403

    async def test_switch_workspace_success_rotates_tokens_and_session(
        self,
        async_client: httpx.AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        user_id = "usr_sw_success_01"
        sess_id = "sess_sw_success_01"
        org1_id = "org_sw_s1"
        org2_id = "org_sw_s2"

        org1 = Organization(id=org1_id, name="Workspace Alpha", slug="ws-alpha", workspace_type="company", is_active=True)
        org2 = Organization(id=org2_id, name="Workspace Beta", slug="ws-beta", workspace_type="company", is_active=True)
        user = User(id=user_id, email="sw_success@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)

        mem1 = OrganizationMembership(user_id=user_id, organization_id=org1_id, role="owner", status=MembershipStatus.ACTIVE.value)
        mem2 = OrganizationMembership(user_id=user_id, organization_id=org2_id, role="admin", status=MembershipStatus.ACTIVE.value)

        user_session = UserSession(
            id=sess_id,
            user_id=user_id,
            organization_id=org1_id,
            refresh_token_hash="hash_sw_init",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        async_db_session.add_all([org1, org2, user, mem1, mem2, user_session])
        await async_db_session.commit()

        token = create_test_token(user_id=user_id, org_id=org1_id, role="owner", session_id=sess_id)
        csrf_tok = generate_test_csrf_token()
        async_client.cookies.set("access_token", token)
        async_client.cookies.set("csrf_token", csrf_tok)
        async_client.headers["X-CSRF-Token"] = csrf_tok

        response = await async_client.post("/workspaces/switch", json={"organization_id": org2_id})
        assert response.status_code == 200
        data = response.json()
        assert data["active_organization"]["id"] == org2_id
        assert data["role"] == "admin"

        # Verify DB UserSession updated
        await async_db_session.refresh(user_session)
        assert user_session.organization_id == org2_id

        # Verify cookies updated in response
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies
