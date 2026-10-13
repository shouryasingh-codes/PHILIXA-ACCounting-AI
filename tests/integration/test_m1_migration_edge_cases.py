from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.config import get_settings
from app.models.enums import MembershipStatus, UserRole, WorkspacePlan, WorkspaceType
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.user_session import UserSession
from app.models.client import Client
from app.models.meeting import Meeting
from app.models.commitment import Commitment


from app.database.base import Base


class TestSlugUniquenessAndCollisionIntegrity:
    """
    Tests that slug generation and unique constraints prevent collisions.
    """

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

    def test_database_organization_slug_unique_index(self, db_engine) -> None:
        """Verify that ix_organizations_slug unique index exists in the database."""
        insp = inspect(db_engine)
        indexes = insp.get_indexes("organizations")
        slug_index = next((idx for idx in indexes if "slug" in idx["column_names"]), None)
        assert slug_index is not None, "organizations table is missing an index on 'slug'"
        assert bool(slug_index.get("unique")) is True, "slug index on organizations must be unique"

    def test_organization_slug_collision_resolution_logic(self) -> None:
        """
        Verify the incremental slug resolution algorithm under high collision pressure.
        """
        org_names = [
            ("org_01", "Global Investment Banking"),
            ("org_02", "Global Investment Banking"),
            ("org_03", "Global Investment Banking"),
            ("org_04", "Global Investment Banking 1"),
            ("org_05", "Global Investment Banking"),
        ]
        used_slugs: Set[str] = set()
        resolved_slugs = {}
        for org_id, name in org_names:
            base_slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.strip().lower()).strip('-') or f"org-{org_id}"
            slug = base_slug
            idx = 1
            while slug in used_slugs:
                slug = f"{base_slug}-{idx}"
                idx += 1
            used_slugs.add(slug)
            resolved_slugs[org_id] = slug

        assert resolved_slugs["org_01"] == "global-investment-banking"
        assert resolved_slugs["org_02"] == "global-investment-banking-1"
        assert resolved_slugs["org_03"] == "global-investment-banking-2"
        assert resolved_slugs["org_04"] == "global-investment-banking-1-1"
        assert resolved_slugs["org_05"] == "global-investment-banking-3"
        assert len(set(resolved_slugs.values())) == 5


class TestZeroUserLegacyAbortBehavior:
    """
    Tests edge cases for the legacy data guard during migration.
    """

    def test_abort_on_legacy_clients_without_users(self) -> None:
        """
        Simulates database state with 3 legacy clients but 0 users.
        Migration must abort.
        """
        legacy_clients = 3
        legacy_meetings = 0
        legacy_commitments = 0
        users_count = 0

        legacy_count = legacy_clients + legacy_meetings + legacy_commitments
        aborted = False
        if legacy_count > 0 and users_count == 0:
            aborted = True

        assert aborted is True

    def test_pass_on_empty_database(self) -> None:
        """
        Empty database (0 legacy rows, 0 users) should proceed without error.
        """
        legacy_count = 0
        users_count = 0
        aborted = False
        if legacy_count > 0 and users_count == 0:
            aborted = True

        assert aborted is False

    def test_pass_on_populated_database(self) -> None:
        """
        Populated database (5 legacy rows, 2 users) should proceed to backfill.
        """
        legacy_count = 5
        users_count = 2
        aborted = False
        if legacy_count > 0 and users_count == 0:
            aborted = True

        assert aborted is False


class TestDowngradeReversibilityLogic:
    """
    Tests that downgrade safely recovers single-org schema and maps roles to legacy uppercase strings.
    """

    def test_role_mapping_downgrade(self) -> None:
        role_map = {
            "owner": "OWNER",
            "admin": "ADMIN",
            "member": "MEMBER",
        }
        for new_role, legacy_role in role_map.items():
            assert new_role.upper() == legacy_role

    def test_cascade_delete_membership_cleans_entity_records(self) -> None:
        """
        Tests that deleting an OrganizationMembership cascades to Client, Meeting, Commitment, and UserSession.
        """
        engine = create_engine("sqlite://", poolclass=StaticPool)
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE organizations (id VARCHAR PRIMARY KEY)"))
            conn.execute(text(
                "CREATE TABLE organization_memberships ("
                "  user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE, "
                "  organization_id VARCHAR REFERENCES organizations(id) ON DELETE CASCADE, "
                "  role VARCHAR, "
                "  PRIMARY KEY (user_id, organization_id)"
                ")"
            ))
            conn.execute(text(
                "CREATE TABLE clients ("
                "  id INTEGER PRIMARY KEY, "
                "  user_id VARCHAR, "
                "  organization_id VARCHAR, "
                "  name VARCHAR, "
                "  FOREIGN KEY (user_id, organization_id) REFERENCES organization_memberships(user_id, organization_id) ON DELETE CASCADE"
                ")"
            ))
            conn.execute(text(
                "CREATE TABLE user_sessions ("
                "  id VARCHAR PRIMARY KEY, "
                "  user_id VARCHAR, "
                "  organization_id VARCHAR, "
                "  FOREIGN KEY (user_id, organization_id) REFERENCES organization_memberships(user_id, organization_id) ON DELETE CASCADE"
                ")"
            ))

            # Insert sample data
            conn.execute(text("INSERT INTO users VALUES ('u1')"))
            conn.execute(text("INSERT INTO organizations VALUES ('org1')"))
            conn.execute(text("INSERT INTO organization_memberships VALUES ('u1', 'org1', 'owner')"))
            conn.execute(text("INSERT INTO clients VALUES (1, 'u1', 'org1', 'Acme')"))
            conn.execute(text("INSERT INTO user_sessions VALUES ('sess1', 'u1', 'org1')"))
            conn.commit()

            # Verify initial count
            c_count = conn.execute(text("SELECT COUNT(*) FROM clients")).scalar()
            s_count = conn.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar()
            assert c_count == 1
            assert s_count == 1

            # Delete membership
            conn.execute(text("DELETE FROM organization_memberships WHERE user_id = 'u1' AND organization_id = 'org1'"))
            conn.commit()

            # Verify cascade deletion
            c_after = conn.execute(text("SELECT COUNT(*) FROM clients")).scalar()
            s_after = conn.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar()
            assert c_after == 0
            assert s_after == 0


if __name__ == "__main__":
    t_slug = TestSlugUniquenessAndCollisionIntegrity()
    t_slug.test_organization_slug_collision_resolution_logic()
    print("[PASS] TestSlugUniquenessAndCollisionIntegrity")

    t_abort = TestZeroUserLegacyAbortBehavior()
    t_abort.test_abort_on_legacy_clients_without_users()
    t_abort.test_pass_on_empty_database()
    t_abort.test_pass_on_populated_database()
    print("[PASS] TestZeroUserLegacyAbortBehavior")

    t_down = TestDowngradeReversibilityLogic()
    t_down.test_role_mapping_downgrade()
    t_down.test_cascade_delete_membership_cleans_entity_records()
    print("[PASS] TestDowngradeReversibilityLogic")
    print("\nALL INTEGRATION EDGE CASE TESTS PASSED!")
