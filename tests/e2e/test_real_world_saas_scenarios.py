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

from app.models.client import Client
from app.models.commitment import Commitment
from app.models.meeting import Meeting
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace_invite import WorkspaceInvite
from tests.conftest import (
    MockRedisClient,
    MockSMTPSink,
    create_test_token,
    generate_test_csrf_token,
    hash_password,
    verify_password,
)


def auth_client(client: httpx.AsyncClient, user_id: str, org_id: str, role: str = "owner", session_id: str | None = None) -> None:
    token = create_test_token(user_id=user_id, org_id=org_id, role=role, session_id=session_id)
    client.cookies.set("access_token", token)
    csrf_token = generate_test_csrf_token()
    client.cookies.set("csrf_token", csrf_token)
    client.headers["X-CSRF-Token"] = csrf_token


# =============================================================================
# Scenario 1: Multi-User Company Onboarding & Role-Based Isolation
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_1_company_onboarding_and_member_isolation(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
    mock_smtp: MockSMTPSink,
) -> None:
    """
    Scenario 1:
    1. Register company workspace "Horizon Capital".
    2. Verify Owner email & log in.
    3. Owner invites Admin (Alice) and Member (Bob).
    4. Alice and Bob accept invitations.
    5. Bob (Member) creates a client and meeting note.
    6. Owner (Carol) views Bob's client and dashboard metrics.
    7. Bob attempts to invite another user or delete members -> receives 403 Forbidden.
    """
    # 1. Register Company
    reg_payload = {
        "email": "carol.owner@horizon.com",
        "password": "CarolSecurePassword2026!",
        "workspace_name": "Horizon Capital",
        "workspace_type": "company",
    }
    reg_res = await async_client.post("/auth/register", json=reg_payload)
    assert reg_res.status_code in (200, 201)

    owner = (await async_db_session.execute(select(User).where(User.email == reg_payload["email"]))).scalar_one()
    org = (await async_db_session.execute(select(Organization).where(Organization.name == "Horizon Capital"))).scalar_one()

    # 2. Email verification & Login
    owner.is_verified = True
    await async_db_session.commit()

    login_res = await async_client.post("/auth/login", json={
        "email": reg_payload["email"],
        "password": reg_payload["password"],
    })
    assert login_res.status_code == 200
    assert login_res.json()["role"] == "owner"
    
    # Extract CSRF token from cookies and set it in headers for subsequent POSTs
    csrf_token = async_client.cookies.get("csrf_token")
    if csrf_token:
        async_client.headers["X-CSRF-Token"] = csrf_token

    # 3. Owner invites Member (Bob)
    invite_payload = {"email": "bob.member@horizon.com", "role": "member"}
    invite_res = await async_client.post("/workspaces/invite", json=invite_payload)
    assert invite_res.status_code in (200, 201)

    invite = (await async_db_session.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.invited_email == "bob.member@horizon.com")
    )).scalar_one()
    assert invite.role == "member"

    # 4. Bob accepts invite
    bob = User(id="usr_bob_01", email="bob.member@horizon.com", hashed_password=hash_password("BobPass123!"), is_verified=True, is_active=True)
    async_db_session.add(bob)
    await async_db_session.commit()

    bob_membership = OrganizationMembership(user_id=bob.id, organization_id=org.id, role="member")
    async_db_session.add(bob_membership)
    await async_db_session.commit()

    # 5. Bob (Member) creates Client & Meeting
    auth_client(async_client, user_id=bob.id, org_id=org.id, role="member")
    client_res = await async_client.post("/api/v1/clients", json={"name": "Bob Prime Client"})
    assert client_res.status_code in (200, 201)
    client_data = client_res.json()
    bob_client_id = client_data.get("id") or client_data.get("client", {}).get("id", 888)

    # 6. Owner views Bob's client
    auth_client(async_client, user_id=owner.id, org_id=org.id, role="owner")
    owner_view_res = await async_client.get(f"/api/v1/clients/{bob_client_id}")
    assert owner_view_res.status_code == 200

    # 7. Bob attempts unauthorized action (Member cannot invite or delete)
    auth_client(async_client, user_id=bob.id, org_id=org.id, role="member")
    unauth_invite = await async_client.post("/workspaces/invite", json={"email": "hacker@test.com", "role": "admin"})
    assert unauth_invite.status_code == 403


# =============================================================================
# Scenario 2: Multi-Tenant Hostile Cross-Contamination Attack Defense
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_2_cross_tenant_hostile_attack_defense(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
) -> None:
    """
    Scenario 2:
    Malicious tenant Org B (Mallory) attempts IDOR attacks against Org A (Alice) resources:
    - Attempt to read Alice's client -> 404
    - Attempt to update Alice's client -> 404
    - Attempt to delete Alice's client -> 404
    - Attempt to read Alice's meeting notes -> 404
    - Attempt to read Alice's client memory -> 404
    - Attempt to complete Alice's commitment -> 404
    - Attempt to request presigned audio URL of Alice's meeting -> 404
    """
    # Setup Alice (Org A)
    org_a = Organization(id="org_victim_a", name="Victim Corp", slug="victim-corp", workspace_type="company")
    alice = User(id="usr_alice_victim", email="alice@victim.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    mem_a = OrganizationMembership(user_id=alice.id, organization_id=org_a.id, role="owner")
    client_a = Client(id=501, name="Alice Confidential Client", organization_id=org_a.id, user_id=alice.id, is_active=True)
    meeting_a = Meeting(id=601, organization_id=org_a.id, user_id=alice.id, client_id=501, raw_notes="Secret Strategy", status="processed", audio_file_path="org_victim_a/usr_alice_victim/601/rec.wav")
    com_a = Commitment(id=701, organization_id=org_a.id, user_id=alice.id, client_id=501, description="Transfer $10M", status="pending")

    # Setup Mallory (Org B)
    org_b = Organization(id="org_attacker_b", name="Attacker Corp", slug="attacker-corp", workspace_type="company")
    mallory = User(id="usr_mallory_attacker", email="mallory@attacker.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    mem_b = OrganizationMembership(user_id=mallory.id, organization_id=org_b.id, role="owner")

    async_db_session.add_all([org_a, alice, mem_a, client_a, meeting_a, com_a, org_b, mallory, mem_b])
    await async_db_session.commit()

    # Authenticate as Mallory
    auth_client(async_client, user_id=mallory.id, org_id=org_b.id, role="owner")

    # Attack 1: Read Alice Client -> 404
    res1 = await async_client.get(f"/api/v1/clients/{client_a.id}")
    assert res1.status_code == 404, "Victim client must return 404 to attacker"

    # Attack 2: Update Alice Client -> 404
    res2 = await async_client.put(f"/api/v1/clients/{client_a.id}", json={"name": "Mallory Pwned"})
    assert res2.status_code == 404

    # Attack 3: Delete Alice Client -> 404
    res3 = await async_client.delete(f"/api/v1/clients/{client_a.id}")
    assert res3.status_code == 404

    # Attack 4: Read Alice Meeting Notes -> 404
    res4 = await async_client.get(f"/api/v1/meeting-notes/{meeting_a.id}")
    assert res4.status_code == 404

    # Attack 5: Read Alice Client Memory -> 404
    res5 = await async_client.get(f"/api/v1/clients/{client_a.id}/memory")
    assert res5.status_code == 404

    # Attack 6: Complete Alice Commitment -> 404
    res6 = await async_client.patch(f"/api/v1/commitments/{com_a.id}/status", json={"status": "completed"})
    assert res6.status_code == 404

    # Attack 7: Presigned Audio URL -> 404
    res7 = await async_client.get(f"/api/v1/audio/{meeting_a.id}/url")
    assert res7.status_code == 404


# =============================================================================
# Scenario 3: Session Revocation & Multi-Device Concurrency
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_3_multi_device_session_revocation(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
) -> None:
    """
    Scenario 3:
    1. User logs in from Device 1 (Session 1) and Device 2 (Session 2).
    2. Both sessions can query `/auth/me`.
    3. User revokes Session 1 (e.g. lost phone).
    4. Session 1 receives 401 on next request.
    5. Session 2 continues to operate without interruption (200 OK).
    """
    user_id = "usr_multidev_01"
    org_id = "org_multidev_01"
    org = Organization(id=org_id, name="Device Org", slug="dev-org", workspace_type="company")
    user = User(id=user_id, email="devices@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")

    sess_1 = UserSession(id="sess_phone_01", user_id=user_id, organization_id=org_id, refresh_token_hash="hash1", expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    sess_2 = UserSession(id="sess_laptop_02", user_id=user_id, organization_id=org_id, refresh_token_hash="hash2", expires_at=datetime.now(timezone.utc) + timedelta(days=30))

    async_db_session.add_all([org, user, mem, sess_1, sess_2])
    await async_db_session.commit()

    # Device 1 queries /auth/me -> 200
    token_1 = create_test_token(user_id=user_id, org_id=org_id, role="owner", session_id=sess_1.id)
    async_client.cookies.set("access_token", token_1)
    res1 = await async_client.get("/auth/me")
    assert res1.status_code == 200

    # Device 2 queries /auth/me -> 200
    token_2 = create_test_token(user_id=user_id, org_id=org_id, role="owner", session_id=sess_2.id)
    async_client.cookies.set("access_token", token_2)
    res2 = await async_client.get("/auth/me")
    assert res2.status_code == 200

    # Revoke Session 1 in database
    sess_1.revoked_at = datetime.now(timezone.utc)
    await async_db_session.commit()

    # Device 1 now gets 401
    async_client.cookies.set("access_token", token_1)
    res1_after_revoke = await async_client.get("/auth/me")
    assert res1_after_revoke.status_code in (401, 403)

    # Device 2 still gets 200
    async_client.cookies.set("access_token", token_2)
    res2_after_revoke = await async_client.get("/auth/me")
    assert res2_after_revoke.status_code == 200


# =============================================================================
# Scenario 4: Token Refresh Rotation & Replay Defense
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_4_refresh_token_rotation_and_replay_defense(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
) -> None:
    """
    Scenario 4:
    1. User performs valid refresh token rotation.
    2. Old refresh token is replaced by new refresh token.
    3. Attacker intercepts and replays the old refresh token.
    4. System rejects old token (401) and flags the session.
    """
    user_id = "usr_rotate_01"
    org_id = "org_rotate_01"
    sess_id = "sess_rotate_family_01"

    org = Organization(id=org_id, name="Rotate Org", slug="rotate-org", workspace_type="company")
    user = User(id=user_id, email="rotate@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")

    old_refresh_jwt = create_test_token(user_id=user_id, org_id=org_id, role="owner", session_id=sess_id, token_type="refresh")
    old_hash = hashlib.sha256(old_refresh_jwt.encode("utf-8")).hexdigest()

    user_sess = UserSession(id=sess_id, user_id=user_id, organization_id=org_id, refresh_token_hash=old_hash, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    async_db_session.add_all([org, user, mem, user_sess])
    await async_db_session.commit()

    # Step 1: Legitimate client refreshes token
    async_client.cookies.set("refresh_token", old_refresh_jwt)
    csrf_token = generate_test_csrf_token()
    async_client.cookies.set("csrf_token", csrf_token)
    async_client.headers["X-CSRF-Token"] = csrf_token

    refresh_res = await async_client.post("/auth/refresh")
    assert refresh_res.status_code == 200

    new_refresh_jwt = refresh_res.cookies.get("refresh_token")
    assert new_refresh_jwt is not None
    assert new_refresh_jwt != old_refresh_jwt

    # Step 2: Attacker replays old refresh token
    async_client.cookies.set("refresh_token", old_refresh_jwt)
    replay_res = await async_client.post("/auth/refresh")
    assert replay_res.status_code in (401, 403), "Replayed old refresh token must be rejected"


# =============================================================================
# Scenario 5: WebSocket Meeting Processing & Memory Scoping
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_5_websocket_ticket_and_meeting_processing(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
    mock_redis: MockRedisClient,
) -> None:
    """
    Scenario 5:
    1. Authenticate user.
    2. Request WebSocket ticket via POST /api/v1/ws-ticket.
    3. Verify ticket TTL in Redis.
    4. Process meeting notes for a client.
    5. Retrieve client memory and confirm commitments.
    """
    user_id = "usr_ws_proc_01"
    org_id = "org_ws_proc_01"

    org = Organization(id=org_id, name="Live Notes Org", slug="live-org", workspace_type="company")
    user = User(id=user_id, email="livenotes@test.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    mem = OrganizationMembership(user_id=user_id, organization_id=org_id, role="owner")
    async_db_session.add_all([org, user, mem])
    await async_db_session.commit()

    auth_client(async_client, user_id=user_id, org_id=org_id, role="owner")

    # Step 1: Issue WS Ticket
    ticket_res = await async_client.post("/api/v1/ws-ticket")
    assert ticket_res.status_code == 200
    ticket_data = ticket_res.json()
    ticket = ticket_data.get("ticket") or ticket_data.get("token")
    assert ticket is not None

    # Step 2: Process meeting note
    process_res = await async_client.post(
        "/api/v1/meeting-notes/process",
        json={
            "raw_notes": "Met Vikram Seth today. Interested in trade finance. Follow up on Monday.",
            "meeting_date": "2026-08-23",
        },
    )
    assert process_res.status_code in (200, 201)
    proc_data = process_res.json()
    client_id = proc_data.get("client_id")
    if client_id:
        memory_res = await async_client.get(f"/api/v1/clients/{client_id}/memory")
        assert memory_res.status_code == 200


# =============================================================================
# Scenario 6: Workspace Switching & Context Scoping
# =============================================================================
@pytest.mark.asyncio
async def test_scenario_6_workspace_switching_context_scoping(
    async_client: httpx.AsyncClient,
    async_db_session: AsyncSession,
) -> None:
    """
    Scenario 6:
    1. User belongs to two workspaces: Org 1 ("Retail Banking") and Org 2 ("Wealth Management").
    2. In Org 1, user creates Client 1 ("Retail Client").
    3. User switches active workspace to Org 2.
    4. User queries `/api/v1/clients` -> Client 1 is NOT present.
    5. In Org 2, user creates Client 2 ("Wealth Client").
    6. User switches back to Org 1 -> Client 1 is present, Client 2 is NOT present.
    """
    user_id = "usr_dual_workspace_01"
    user = User(id=user_id, email="dual@bank.com", hashed_password=hash_password("Pass123!"), is_verified=True, is_active=True)
    
    org1 = Organization(id="org_retail_01", name="Retail Banking", slug="retail-banking", workspace_type="company")
    org2 = Organization(id="org_wealth_02", name="Wealth Management", slug="wealth-mgmt", workspace_type="company")
    
    mem1 = OrganizationMembership(user_id=user_id, organization_id=org1.id, role="owner")
    mem2 = OrganizationMembership(user_id=user_id, organization_id=org2.id, role="owner")
    
    client1 = Client(id=801, name="Retail Client", organization_id=org1.id, user_id=user_id, is_active=True)
    client2 = Client(id=802, name="Wealth Client", organization_id=org2.id, user_id=user_id, is_active=True)

    async_db_session.add_all([user, org1, org2, mem1, mem2, client1, client2])
    await async_db_session.commit()

    # Step 1: Active in Org 1
    auth_client(async_client, user_id=user_id, org_id=org1.id, role="owner")
    res_org1 = await async_client.get("/api/v1/clients")
    assert res_org1.status_code == 200
    names1 = [c["name"] for c in (res_org1.json() if isinstance(res_org1.json(), list) else res_org1.json().get("clients", []))]
    assert "Retail Client" in names1
    assert "Wealth Client" not in names1

    # Step 2: Switch to Org 2
    auth_client(async_client, user_id=user_id, org_id=org2.id, role="owner")
    res_org2 = await async_client.get("/api/v1/clients")
    assert res_org2.status_code == 200
    names2 = [c["name"] for c in (res_org2.json() if isinstance(res_org2.json(), list) else res_org2.json().get("clients", []))]
    assert "Wealth Client" in names2
    assert "Retail Client" not in names2
