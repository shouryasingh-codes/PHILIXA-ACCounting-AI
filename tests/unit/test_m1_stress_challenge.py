from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.config import get_settings
from app.models.enums import (
    CommitmentStatus,
    MeetingSourceType,
    MeetingStatus,
    MembershipStatus,
    UserRole,
    WorkspacePlan,
    WorkspaceType,
)
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.auth_tokens import EmailVerificationToken, PasswordResetToken
from app.models.workspace_invite import WorkspaceInvite
from app.models.client import Client
from app.models.meeting import Meeting
from app.models.commitment import Commitment
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from app.database.base import Base


def get_db_engine():
    settings = get_settings()
    db_url = os.getenv("PHILIXA_TEST_DATABASE_URL")
    if not db_url or "sqlite" in db_url:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        Base.metadata.create_all(bind=engine)
        return engine
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    return engine


class TestCompositeForeignKeyViolations:
    """
    Stress-test composite foreign key constraints at the database level.
    Ensures that records CANNOT be inserted for (user_id, organization_id)
    unless a corresponding (user_id, organization_id) exists in organization_memberships.
    """

    def test_client_insert_without_membership_fails(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(
                id=f"usr_nomem_{test_id}",
                email=f"nomem_{test_id}@example.com",
                hashed_password="hash",
                is_verified=True,
            )
            org = Organization(
                id=f"org_nomem_{test_id}",
                name=f"Org {test_id}",
                slug=f"org-{test_id}",
                workspace_type="company",
                plan="free",
            )
            session.add_all([user, org])
            session.flush()

            # Attempt to create Client with user and org, but NO OrganizationMembership
            client = Client(
                name=f"Illegal Client {test_id}",
                normalized_name=f"illegal client {test_id}",
                organization_id=org.id,
                user_id=user.id,
            )
            session.add(client)
            with pytest.raises(IntegrityError) as exc_info:
                session.flush()

            assert "fk_clients_membership" in str(exc_info.value).lower() or "foreign key" in str(exc_info.value).lower()
            session.rollback()

            # Cleanup
            session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
            session.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id})
            session.commit()

    def test_meeting_insert_without_membership_fails(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(
                id=f"usr_mtg_nomem_{test_id}",
                email=f"mtg_nomem_{test_id}@example.com",
                hashed_password="hash",
                is_verified=True,
            )
            org = Organization(
                id=f"org_mtg_nomem_{test_id}",
                name=f"Org Mtg {test_id}",
                slug=f"org-mtg-{test_id}",
                workspace_type="company",
                plan="free",
            )
            session.add_all([user, org])
            session.flush()

            meeting = Meeting(
                organization_id=org.id,
                user_id=user.id,
                raw_notes="Illegal meeting note without membership",
                meeting_date=datetime.now(timezone.utc).date(),
            )
            session.add(meeting)
            with pytest.raises(IntegrityError) as exc_info:
                session.flush()

            assert "fk_meetings_membership" in str(exc_info.value).lower() or "foreign key" in str(exc_info.value).lower()
            session.rollback()

            session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
            session.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id})
            session.commit()

    def test_commitment_insert_without_membership_fails(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user_valid = User(
                id=f"usr_v_{test_id}",
                email=f"usr_v_{test_id}@example.com",
                hashed_password="hash",
                is_verified=True,
            )
            user_invalid = User(
                id=f"usr_inv_{test_id}",
                email=f"usr_inv_{test_id}@example.com",
                hashed_password="hash",
                is_verified=True,
            )
            org = Organization(
                id=f"org_cmt_{test_id}",
                name=f"Org Cmt {test_id}",
                slug=f"org-cmt-{test_id}",
                workspace_type="company",
                plan="free",
            )
            session.add_all([user_valid, user_invalid, org])
            session.flush()

            # Membership only for user_valid
            mem = OrganizationMembership(user_id=user_valid.id, organization_id=org.id, role="owner")
            session.add(mem)
            session.flush()

            # Valid client created by user_valid
            client = Client(
                name="Valid Client",
                normalized_name="valid client",
                organization_id=org.id,
                user_id=user_valid.id,
            )
            session.add(client)
            session.flush()

            # Attempt commitment created in org by user_invalid (who is NOT a member)
            cmt = Commitment(
                organization_id=org.id,
                user_id=user_invalid.id,
                client_id=client.id,
                description="Illegal commitment",
                normalized_description="illegal commitment",
            )
            session.add(cmt)
            with pytest.raises(IntegrityError) as exc_info:
                session.flush()

            assert "fk_commitments_membership" in str(exc_info.value).lower() or "foreign key" in str(exc_info.value).lower()
            session.rollback()

            session.execute(text("DELETE FROM users WHERE id IN (:u1, :u2)"), {"u1": user_valid.id, "u2": user_invalid.id})
            session.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id})
            session.commit()

    def test_user_session_without_membership_fails(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(
                id=f"usr_sess_{test_id}",
                email=f"sess_{test_id}@example.com",
                hashed_password="hash",
                is_verified=True,
            )
            org = Organization(
                id=f"org_sess_{test_id}",
                name=f"Org Sess {test_id}",
                slug=f"org-sess-{test_id}",
                workspace_type="company",
                plan="free",
            )
            session.add_all([user, org])
            session.flush()

            # Attempt user session with org where user has no membership
            sess = UserSession(
                user_id=user.id,
                organization_id=org.id,
                refresh_token_hash="fake_hash_123",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            session.add(sess)
            with pytest.raises(IntegrityError) as exc_info:
                session.flush()

            assert "fk_user_sessions_membership" in str(exc_info.value).lower() or "foreign key" in str(exc_info.value).lower()
            session.rollback()

            session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
            session.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id})
            session.commit()

    def test_cross_tenant_spoofing_violation(self):
        """
        User A belongs to Org A.
        User B belongs to Org B.
        Attempt: User A tries to insert a Client/Meeting into Org B -> must fail.
        """
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user_a = User(id=f"usr_a_{test_id}", email=f"a_{test_id}@example.com", hashed_password="pw", is_verified=True)
            user_b = User(id=f"usr_b_{test_id}", email=f"b_{test_id}@example.com", hashed_password="pw", is_verified=True)
            org_a = Organization(id=f"org_a_{test_id}", name="Org A", slug=f"org-a-{test_id}", workspace_type="company", plan="free")
            org_b = Organization(id=f"org_b_{test_id}", name="Org B", slug=f"org-b-{test_id}", workspace_type="company", plan="free")

            session.add_all([user_a, user_b, org_a, org_b])
            session.flush()

            mem_a = OrganizationMembership(user_id=user_a.id, organization_id=org_a.id, role="owner")
            mem_b = OrganizationMembership(user_id=user_b.id, organization_id=org_b.id, role="owner")
            session.add_all([mem_a, mem_b])
            session.flush()

            # User A in Org B Client insertion
            spoofed_client = Client(
                name="Spoofed Client",
                normalized_name="spoofed client",
                organization_id=org_b.id,
                user_id=user_a.id,
            )
            session.add(spoofed_client)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

            # Clean up
            session.execute(text("DELETE FROM users WHERE id IN (:ua, :ub)"), {"ua": user_a.id, "ub": user_b.id})
            session.execute(text("DELETE FROM organizations WHERE id IN (:oa, :ob)"), {"oa": org_a.id, "ob": org_b.id})
            session.commit()


class TestCascadeDeletions:
    """
    Stress-test cascade deletion behaviors across multi-tenancy boundaries.
    """

    def test_membership_deletion_cascades_only_targeted_org_records(self):
        """
        User belongs to both Org 1 and Org 2.
        User has authored records in both Org 1 and Org 2.
        When membership in Org 1 is deleted:
        - Org 1 records are cascade deleted.
        - Org 2 records MUST REMAIN INTACT.
        - User and Orgs remain intact.
        """
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(id=f"usr_multi_{test_id}", email=f"multi_{test_id}@example.com", hashed_password="pw", is_verified=True)
            org1 = Organization(id=f"org1_{test_id}", name="Org 1", slug=f"org-1-{test_id}", workspace_type="company", plan="free")
            org2 = Organization(id=f"org2_{test_id}", name="Org 2", slug=f"org-2-{test_id}", workspace_type="company", plan="free")

            session.add_all([user, org1, org2])
            session.flush()

            mem1 = OrganizationMembership(user_id=user.id, organization_id=org1.id, role="owner")
            mem2 = OrganizationMembership(user_id=user.id, organization_id=org2.id, role="member")
            session.add_all([mem1, mem2])
            session.flush()

            # Create records in Org 1
            client1 = Client(name="Client Org1", normalized_name="client org1", organization_id=org1.id, user_id=user.id)
            session.add(client1)
            session.flush()

            meeting1 = Meeting(
                organization_id=org1.id, user_id=user.id, client_id=client1.id,
                raw_notes="Notes Org1", meeting_date=datetime.now(timezone.utc).date()
            )
            session.add(meeting1)
            session.flush()

            cmt1 = Commitment(
                organization_id=org1.id, user_id=user.id, client_id=client1.id,
                description="Commitment Org1", normalized_description="commitment org1"
            )
            session.add(cmt1)

            sess1 = UserSession(
                user_id=user.id, organization_id=org1.id, refresh_token_hash=f"hash1_{test_id}",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1)
            )
            session.add(sess1)
            session.flush()

            # Create records in Org 2
            client2 = Client(name="Client Org2", normalized_name="client org2", organization_id=org2.id, user_id=user.id)
            session.add(client2)
            session.flush()

            meeting2 = Meeting(
                organization_id=org2.id, user_id=user.id, client_id=client2.id,
                raw_notes="Notes Org2", meeting_date=datetime.now(timezone.utc).date()
            )
            session.add(meeting2)
            session.flush()

            cmt2 = Commitment(
                organization_id=org2.id, user_id=user.id, client_id=client2.id,
                description="Commitment Org2", normalized_description="commitment org2"
            )
            session.add(cmt2)

            sess2 = UserSession(
                user_id=user.id, organization_id=org2.id, refresh_token_hash=f"hash2_{test_id}",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1)
            )
            session.add(sess2)
            session.commit()

            c1_id, m1_id, cmt1_id, s1_id = client1.id, meeting1.id, cmt1.id, sess1.id
            c2_id, m2_id, cmt2_id, s2_id = client2.id, meeting2.id, cmt2.id, sess2.id

            # Delete membership in Org 1
            session.delete(mem1)
            session.commit()

            # Org 1 entities should be cascade deleted
            assert session.query(Client).filter_by(id=c1_id).first() is None
            assert session.query(Meeting).filter_by(id=m1_id).first() is None
            assert session.query(Commitment).filter_by(id=cmt1_id).first() is None
            assert session.query(UserSession).filter_by(id=s1_id).first() is None

            # Org 2 entities MUST REMAIN INTACT!
            assert session.query(Client).filter_by(id=c2_id).first() is not None
            assert session.query(Meeting).filter_by(id=m2_id).first() is not None
            assert session.query(Commitment).filter_by(id=cmt2_id).first() is not None
            assert session.query(UserSession).filter_by(id=s2_id).first() is not None

            # User and Org 1 & Org 2 still exist
            assert session.query(User).filter_by(id=user.id).first() is not None
            assert session.query(Organization).filter_by(id=org1.id).first() is not None
            assert session.query(Organization).filter_by(id=org2.id).first() is not None

            # Cleanup
            session.delete(user)
            session.delete(org1)
            session.delete(org2)
            session.commit()

    def test_organization_deletion_cascades_all_workspace_data(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(id=f"usr_oc_{test_id}", email=f"oc_{test_id}@example.com", hashed_password="pw", is_verified=True)
            org = Organization(id=f"org_oc_{test_id}", name="Org Cascade", slug=f"org-casc-{test_id}", workspace_type="company", plan="free")
            session.add_all([user, org])
            session.flush()

            mem = OrganizationMembership(user_id=user.id, organization_id=org.id, role="owner")
            session.add(mem)
            session.flush()

            invite = WorkspaceInvite(
                organization_id=org.id, invited_email=f"inv_{test_id}@example.com", role="member",
                token_hash=f"inv_hash_{test_id}", invited_by_user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
            client = Client(name="Org Client", normalized_name="org client", organization_id=org.id, user_id=user.id)
            session.add_all([invite, client])
            session.flush()

            invite_id = invite.id
            client_id = client.id

            # Delete organization
            session.delete(org)
            session.commit()

            # Check all workspace data deleted
            assert session.query(OrganizationMembership).filter_by(organization_id=org.id).first() is None
            assert session.query(WorkspaceInvite).filter_by(id=invite_id).first() is None
            assert session.query(Client).filter_by(id=client_id).first() is None

            # User still exists
            assert session.query(User).filter_by(id=user.id).first() is not None

            # Cleanup user
            session.delete(user)
            session.commit()


class TestUniqueConstraintsAndIdempotency:
    def test_organization_slug_uniqueness(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            slug = f"unique-slug-{test_id}"
            org1 = Organization(id=f"org1_{test_id}", name="Org 1", slug=slug, workspace_type="company", plan="free")
            org2 = Organization(id=f"org2_{test_id}", name="Org 2", slug=slug, workspace_type="company", plan="free")
            session.add(org1)
            session.commit()

            session.add(org2)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            session.delete(org1)
            session.commit()

    def test_membership_composite_pk_uniqueness(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(id=f"usr_u_{test_id}", email=f"u_{test_id}@example.com", hashed_password="pw", is_verified=True)
            org = Organization(id=f"org_u_{test_id}", name="Org U", slug=f"org-u-{test_id}", workspace_type="company", plan="free")
            session.add_all([user, org])
            session.commit()

            mem1 = OrganizationMembership(user_id=user.id, organization_id=org.id, role="owner")
            session.add(mem1)
            session.commit()

            mem2 = OrganizationMembership(user_id=user.id, organization_id=org.id, role="admin")
            session.add(mem2)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            session.delete(user)
            session.delete(org)
            session.commit()

    def test_auth_token_hashes_uniqueness(self):
        engine = get_db_engine()
        with Session(engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(id=f"usr_tok_{test_id}", email=f"tok_{test_id}@example.com", hashed_password="pw", is_verified=True)
            session.add(user)
            session.commit()

            token_hash = f"hash_{test_id}"
            t1 = EmailVerificationToken(user_id=user.id, token_hash=token_hash, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
            t2 = EmailVerificationToken(user_id=user.id, token_hash=token_hash, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
            session.add(t1)
            session.commit()

            session.add(t2)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            session.delete(user)
            session.commit()


class TestNoLegacyPlaceholders:
    def test_no_legacy_placeholders_in_tables(self):
        engine = get_db_engine()
        with Session(engine) as session:
            for tbl in ("clients", "meetings", "commitments", "organizations"):
                result = session.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE id IN ('SYSTEM', 'default', 'org_1')")).scalar()
                assert result == 0, f"Table {tbl} contains forbidden legacy id"

            for tbl in ("clients", "meetings", "commitments"):
                result = session.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE organization_id IN ('SYSTEM', 'SYSTEM_ORG', 'default', 'org_1')")).scalar()
                assert result == 0, f"Table {tbl} contains forbidden legacy organization_id"


if __name__ == "__main__":
    print("Running Empirical Stress Challenge Tests...")
    t_fk = TestCompositeForeignKeyViolations()
    t_fk.test_client_insert_without_membership_fails()
    t_fk.test_meeting_insert_without_membership_fails()
    t_fk.test_commitment_insert_without_membership_fails()
    t_fk.test_user_session_without_membership_fails()
    t_fk.test_cross_tenant_spoofing_violation()
    print("[PASS] TestCompositeForeignKeyViolations passed completely!")

    t_casc = TestCascadeDeletions()
    t_casc.test_membership_deletion_cascades_only_targeted_org_records()
    t_casc.test_organization_deletion_cascades_all_workspace_data()
    print("[PASS] TestCascadeDeletions passed completely!")

    t_uniq = TestUniqueConstraintsAndIdempotency()
    t_uniq.test_organization_slug_uniqueness()
    t_uniq.test_membership_composite_pk_uniqueness()
    t_uniq.test_auth_token_hashes_uniqueness()
    print("[PASS] TestUniqueConstraintsAndIdempotency passed completely!")

    t_leg = TestNoLegacyPlaceholders()
    t_leg.test_no_legacy_placeholders_in_tables()
    print("[PASS] TestNoLegacyPlaceholders passed completely!")

    print("ALL EMPIRICAL STRESS CHALLENGE TESTS PASSED 100%!")
