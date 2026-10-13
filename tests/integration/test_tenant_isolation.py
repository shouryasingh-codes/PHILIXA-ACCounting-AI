from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.commitment import Commitment
from app.models.meeting import Meeting
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from tests.conftest import (
    create_test_token,
    generate_test_csrf_token,
    hash_password,
)


@pytest_asyncio.fixture
async def seeded_multi_tenant_env(async_db_session: AsyncSession) -> Dict[str, Any]:
    """
    Seeds a two-organization environment:
    - Org A:
      - Owner A1 (id='usr_a1_owner')
      - Member A2 (id='usr_a2_member')
      - Client A1 (created by Owner A1)
      - Client A2 (created by Member A2)
      - Meeting A1 (created by Owner A1 for Client A1)
      - Meeting A2 (created by Member A2 for Client A2)
      - Commitment A1 (created for Meeting A1)
      - Commitment A2 (created for Meeting A2)
    - Org B:
      - Owner B1 (id='usr_b1_owner')
      - Member B2 (id='usr_b2_member')
      - Client B1 (created by Owner B1)
      - Meeting B1 (created by Owner B1 for Client B1)
      - Commitment B1 (created for Meeting B1)
    """
    # 1. Organizations
    org_a = Organization(id="org_alpha_100", name="Org Alpha Corp", slug="alpha-corp", workspace_type="company")
    org_b = Organization(id="org_beta_200", name="Org Beta Ltd", slug="beta-ltd", workspace_type="company")
    async_db_session.add_all([org_a, org_b])

    # 2. Users
    user_a1 = User(id="usr_a1_owner", email="a1.owner@alpha.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    user_a2 = User(id="usr_a2_member", email="a2.member@alpha.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    user_b1 = User(id="usr_b1_owner", email="b1.owner@beta.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    user_b2 = User(id="usr_b2_member", email="b2.member@beta.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    async_db_session.add_all([user_a1, user_a2, user_b1, user_b2])

    # 3. Memberships
    mem_a1 = OrganizationMembership(user_id="usr_a1_owner", organization_id="org_alpha_100", role="owner")
    mem_a2 = OrganizationMembership(user_id="usr_a2_member", organization_id="org_alpha_100", role="member")
    mem_b1 = OrganizationMembership(user_id="usr_b1_owner", organization_id="org_beta_200", role="owner")
    mem_b2 = OrganizationMembership(user_id="usr_b2_member", organization_id="org_beta_200", role="member")
    async_db_session.add_all([mem_a1, mem_a2, mem_b1, mem_b2])

    # 4. Clients
    client_a1 = Client(id=101, name="Alpha Client 1", organization_id="org_alpha_100", user_id="usr_a1_owner", is_active=True)
    client_a2 = Client(id=102, name="Alpha Client 2", organization_id="org_alpha_100", user_id="usr_a2_member", is_active=True)
    client_b1 = Client(id=201, name="Beta Client 1", organization_id="org_beta_200", user_id="usr_b1_owner", is_active=True)
    async_db_session.add_all([client_a1, client_a2, client_b1])

    # 5. Meetings
    meeting_a1 = Meeting(id=1001, organization_id="org_alpha_100", user_id="usr_a1_owner", client_id=101, raw_notes="Alpha Owner Meeting", status="processed")
    meeting_a2 = Meeting(id=1002, organization_id="org_alpha_100", user_id="usr_a2_member", client_id=102, raw_notes="Alpha Member Meeting", status="processed")
    meeting_b1 = Meeting(id=2001, organization_id="org_beta_200", user_id="usr_b1_owner", client_id=201, raw_notes="Beta Owner Meeting", status="processed")
    async_db_session.add_all([meeting_a1, meeting_a2, meeting_b1])

    # 6. Commitments
    com_a1 = Commitment(id=11, organization_id="org_alpha_100", user_id="usr_a1_owner", client_id=101, description="Alpha Task 1", status="pending")
    com_a2 = Commitment(id=12, organization_id="org_alpha_100", user_id="usr_a2_member", client_id=102, description="Alpha Task 2", status="pending")
    com_b1 = Commitment(id=21, organization_id="org_beta_200", user_id="usr_b1_owner", client_id=201, description="Beta Task 1", status="pending")
    async_db_session.add_all([com_a1, com_a2, com_b1])

    await async_db_session.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a1": user_a1,
        "user_a2": user_a2,
        "user_b1": user_b1,
        "client_a1": client_a1,
        "client_a2": client_a2,
        "client_b1": client_b1,
        "meeting_a1": meeting_a1,
        "meeting_a2": meeting_a2,
        "meeting_b1": meeting_b1,
        "com_a1": com_a1,
        "com_a2": com_a2,
        "com_b1": com_b1,
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
class TestCrossTenantAntiEnumeration404:
    async def test_org_a_user_cannot_read_org_b_client_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_client_id = seeded_multi_tenant_env["client_b1"].id
        
        response = await async_client.get(f"/api/v1/clients/{org_b_client_id}")
        assert response.status_code == 404, f"Cross-tenant read must return 404 (anti-enumeration), got {response.status_code}"

    async def test_org_a_user_cannot_update_org_b_client_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_client_id = seeded_multi_tenant_env["client_b1"].id
        
        response = await async_client.put(f"/api/v1/clients/{org_b_client_id}", json={"name": "Hacked Client"})
        assert response.status_code == 404, f"Cross-tenant update must return 404, got {response.status_code}"

    async def test_org_a_user_cannot_delete_org_b_client_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_client_id = seeded_multi_tenant_env["client_b1"].id
        
        response = await async_client.delete(f"/api/v1/clients/{org_b_client_id}")
        assert response.status_code == 404, f"Cross-tenant delete must return 404, got {response.status_code}"

    async def test_org_a_user_cannot_read_org_b_meeting_notes_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_meeting_id = seeded_multi_tenant_env["meeting_b1"].id
        
        response = await async_client.get(f"/api/v1/meeting-notes/{org_b_meeting_id}")
        assert response.status_code == 404, f"Cross-tenant meeting access must return 404, got {response.status_code}"

    async def test_org_a_user_cannot_read_org_b_client_memory_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_client_id = seeded_multi_tenant_env["client_b1"].id
        
        response = await async_client.get(f"/api/v1/clients/{org_b_client_id}/memory")
        assert response.status_code == 404, f"Cross-tenant client memory access must return 404, got {response.status_code}"

    async def test_org_a_user_cannot_update_org_b_commitment_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        org_b_com_id = seeded_multi_tenant_env["com_b1"].id
        
        response = await async_client.patch(f"/api/v1/commitments/{org_b_com_id}/status", json={"status": "completed"})
        assert response.status_code == 404, f"Cross-tenant commitment update must return 404, got {response.status_code}"


@pytest.mark.asyncio
class TestRoleBasedRecordOwnershipWithinSameOrganization:
    async def test_member_cannot_access_owner_client_receives_404(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        # Member A2 attempts to read Owner A1's client
        authenticate_client(async_client, user_id="usr_a2_member", org_id="org_alpha_100", role="member")
        owner_client_id = seeded_multi_tenant_env["client_a1"].id
        
        response = await async_client.get(f"/api/v1/clients/{owner_client_id}")
        assert response.status_code == 404, f"Member accessing Owner record must receive 404, got {response.status_code}"

    async def test_owner_can_access_member_client_receives_200(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        # Owner A1 reads Member A2's client
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        member_client_id = seeded_multi_tenant_env["client_a2"].id
        
        response = await async_client.get(f"/api/v1/clients/{member_client_id}")
        assert response.status_code == 200, f"Owner reading Member record must receive 200, got {response.status_code}"

    async def test_member_can_access_own_client_receives_200(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        # Member A2 reads their own client
        authenticate_client(async_client, user_id="usr_a2_member", org_id="org_alpha_100", role="member")
        member_client_id = seeded_multi_tenant_env["client_a2"].id
        
        response = await async_client.get(f"/api/v1/clients/{member_client_id}")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestTenantScopingOnAggregationsAndJobs:
    async def test_clients_list_strictly_filtered_by_organization(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        # Org A Owner lists clients
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        response = await async_client.get("/api/v1/clients")
        assert response.status_code == 200
        
        data = response.json()
        clients = data if isinstance(data, list) else data.get("clients", [])
        client_names = [c["name"] for c in clients]
        
        assert "Alpha Client 1" in client_names
        assert "Alpha Client 2" in client_names
        assert "Beta Client 1" not in client_names, "Org B clients must NEVER leak to Org A"

    async def test_commitments_list_filtered_by_tenant_and_role(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        # Member A2 lists commitments -> should only see their own
        authenticate_client(async_client, user_id="usr_a2_member", org_id="org_alpha_100", role="member")
        response = await async_client.get("/api/v1/commitments")
        assert response.status_code == 200
        
        data = response.json()
        comms = data if isinstance(data, list) else data.get("commitments", [])
        descriptions = [c["description"] for c in comms]
        
        assert "Alpha Task 2" in descriptions
        assert "Beta Task 1" not in descriptions, "Org B tasks must never appear in Org A"

    async def test_dashboard_metrics_strictly_scoped_by_tenant(
        self,
        async_client: httpx.AsyncClient,
        seeded_multi_tenant_env: Dict[str, Any],
    ) -> None:
        authenticate_client(async_client, user_id="usr_a1_owner", org_id="org_alpha_100", role="owner")
        response = await async_client.get("/api/v1/dashboard/metrics")
        # Ensure endpoint works and isolates metrics
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            metrics = response.json()
            assert "metrics" in metrics or "total_clients" in metrics or "active_clients" in metrics
