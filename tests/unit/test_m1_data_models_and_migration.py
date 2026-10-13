from __future__ import annotations

import os
import sys
from pathlib import Path
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

# Ensure project root in sys.path
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


class TestEnums:
    def test_user_roles(self) -> None:
        assert UserRole.OWNER.value == "owner"
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.MEMBER.value == "member"

    def test_workspace_enums(self) -> None:
        assert WorkspaceType.INDIVIDUAL.value == "individual"
        assert WorkspaceType.COMPANY.value == "company"
        assert WorkspacePlan.FREE.value == "free"
        assert WorkspacePlan.PRO.value == "pro"
        assert MembershipStatus.ACTIVE.value == "active"
        assert MembershipStatus.INVITED.value == "invited"
        assert MembershipStatus.SUSPENDED.value == "suspended"


class TestModelDeclarations:
    def test_user_model_has_no_single_org_columns(self) -> None:
        user_cols = {c.name for c in User.__table__.columns}
        assert "organization_id" not in user_cols
        assert "role" not in user_cols
        assert "is_verified" in user_cols

    def test_organization_model_columns(self) -> None:
        org_cols = {c.name for c in Organization.__table__.columns}
        assert "workspace_type" in org_cols
        assert "slug" in org_cols
        assert "plan" in org_cols

    def test_organization_membership_composite_pk(self) -> None:
        pk_cols = [c.name for c in OrganizationMembership.__table__.primary_key.columns]
        assert set(pk_cols) == {"user_id", "organization_id"}

    def test_user_session_columns_and_fk(self) -> None:
        sess_cols = {c.name for c in UserSession.__table__.columns}
        assert {"id", "user_id", "organization_id", "refresh_token_hash", "device_info", "expires_at", "revoked_at"}.issubset(sess_cols)
        fk_names = {fk.name for fk in UserSession.__table__.foreign_key_constraints if fk.name}
        assert "fk_user_sessions_membership" in fk_names

    def test_auth_tokens_models(self) -> None:
        email_cols = {c.name for c in EmailVerificationToken.__table__.columns}
        assert {"id", "user_id", "token_hash", "expires_at", "used_at"}.issubset(email_cols)
        reset_cols = {c.name for c in PasswordResetToken.__table__.columns}
        assert {"id", "user_id", "token_hash", "expires_at", "used_at"}.issubset(reset_cols)

    def test_workspace_invite_model(self) -> None:
        invite_cols = {c.name for c in WorkspaceInvite.__table__.columns}
        assert {"id", "organization_id", "invited_email", "role", "token_hash", "invited_by_user_id", "expires_at"}.issubset(invite_cols)

    def test_composite_membership_fks_on_entities(self) -> None:
        for model, fk_name, idx_name in [
            (Client, "fk_clients_membership", "ix_clients_org_user"),
            (Meeting, "fk_meetings_membership", "ix_meetings_org_user"),
            (Commitment, "fk_commitments_membership", "ix_commitments_org_user"),
        ]:
            cols = {c.name for c in model.__table__.columns}
            assert "organization_id" in cols
            assert "user_id" in cols
            fk_names = {fk.name for fk in model.__table__.foreign_key_constraints if fk.name}
            assert fk_name in fk_names
            idx_names = {idx.name for idx in model.__table__.indexes if idx.name}
            assert idx_name in idx_names

    def test_client_model_has_products_interested_and_owned(self) -> None:
        client_cols = {c.name for c in Client.__table__.columns}
        assert "products_owned_json" in client_cols
        assert "products_interested_json" in client_cols



from sqlalchemy.pool import StaticPool
from app.database.base import Base


class TestDatabaseSchemaIntegrity:
    @pytest.fixture(scope="class")
    def db_engine(self):
        settings = get_settings()
        db_url = os.getenv("PHILIXA_TEST_DATABASE_URL")
        if not db_url or "sqlite" in db_url:
            engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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

    def test_database_tables_exist(self, db_engine) -> None:
        insp = inspect(db_engine)
        table_names = set(insp.get_table_names())
        expected = {
            "organizations",
            "users",
            "organization_memberships",
            "user_sessions",
            "email_verification_tokens",
            "password_reset_tokens",
            "workspace_invites",
            "clients",
            "meetings",
            "commitments",
        }
        assert expected.issubset(table_names)

    def test_database_foreign_key_constraints(self, db_engine) -> None:
        insp = inspect(db_engine)
        for tbl, expected_fk in [
            ("clients", "fk_clients_membership"),
            ("meetings", "fk_meetings_membership"),
            ("commitments", "fk_commitments_membership"),
            ("user_sessions", "fk_user_sessions_membership"),
        ]:
            fks = insp.get_foreign_keys(tbl)
            fk_names = {fk.get("name") for fk in fks}
            assert expected_fk in fk_names, f"Missing FK {expected_fk} on table {tbl}"

    def test_foreign_key_cascade_behavior(self, db_engine) -> None:
        with Session(db_engine) as session:
            test_id = str(uuid.uuid4())[:8]
            user = User(
                id=f"usr_test_{test_id}",
                email=f"test_{test_id}@example.com",
                hashed_password="hashed_pw_test",
                is_verified=True,
            )
            org = Organization(
                id=f"org_test_{test_id}",
                name=f"Test Org {test_id}",
                slug=f"test-org-{test_id}",
                workspace_type="company",
                plan="free",
            )
            session.add_all([user, org])
            session.flush()

            membership = OrganizationMembership(
                user_id=user.id,
                organization_id=org.id,
                role="owner",
                status="active",
            )
            session.add(membership)
            session.flush()

            client = Client(
                name=f"Client {test_id}",
                normalized_name=f"client {test_id}",
                organization_id=org.id,
                user_id=user.id,
            )
            session.add(client)
            session.flush()

            client_id = client.id

            # Verify client exists
            loaded_client = session.query(Client).filter_by(id=client_id).first()
            assert loaded_client is not None

            # Delete membership -> cascades to delete client due to fk_clients_membership
            session.delete(membership)
            session.commit()

            # Client should now be cascade deleted
            assert session.query(Client).filter_by(id=client_id).first() is None

            # Clean up user and org
            session.delete(user)
            session.delete(org)
            session.commit()


if __name__ == "__main__":
    t_enum = TestEnums()
    t_enum.test_user_roles()
    t_enum.test_workspace_enums()
    print("TestEnums passed!")

    t_models = TestModelDeclarations()
    t_models.test_user_model_has_no_single_org_columns()
    t_models.test_organization_model_columns()
    t_models.test_organization_membership_composite_pk()
    t_models.test_user_session_columns_and_fk()
    t_models.test_auth_tokens_models()
    t_models.test_workspace_invite_model()
    t_models.test_composite_membership_fks_on_entities()
    print("TestModelDeclarations passed!")

    t_db = TestDatabaseSchemaIntegrity()
    eng = create_engine(get_settings().database_url)
    t_db.test_database_tables_exist(eng)
    t_db.test_database_foreign_key_constraints(eng)
    t_db.test_foreign_key_cascade_behavior(eng)
    print("TestDatabaseSchemaIntegrity passed!")
    print("ALL M1 VERIFICATION TESTS PASSED SUCCESSFULLY!")
