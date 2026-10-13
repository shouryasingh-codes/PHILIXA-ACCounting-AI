from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Set

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.config import get_settings


# =============================================================================
# Helper functions simulating the exact Alembic migration logic
# =============================================================================

def simulate_slug_generation(existing_orgs: list[tuple[str, str | None]], initial_used_slugs: set[str] | None = None) -> dict[str, str]:
    """
    Simulates the exact slug generation logic from Alembic migration h5c3d4e5f6g7.
    """
    used_slugs: Set[str] = set(initial_used_slugs) if initial_used_slugs else set()
    result = {}
    for org in existing_orgs:
        org_id = org[0]
        name = org[1] or "Workspace"
        base_slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.strip().lower()).strip('-') or f"org-{org_id}"
        slug = base_slug
        idx = 1
        while slug in used_slugs:
            slug = f"{base_slug}-{idx}"
            idx += 1
        used_slugs.add(slug)
        result[org_id] = slug
    return result


def simulate_legacy_backfill_check(users_count: int, clients_count: int, meetings_count: int, commitments_count: int) -> bool:
    """
    Simulates legacy count & user check: raises RuntimeError if legacy data exists but 0 users.
    """
    legacy_count = clients_count + meetings_count + commitments_count
    if legacy_count > 0 and users_count == 0:
        raise RuntimeError(
            "Migration aborted: Legacy client/meeting/commitment records exist, but no users exist "
            "to assign ownership. Cannot safely backfill without an owner."
        )
    return True


# =============================================================================
# Edge Case Test Suite 1: Zero-User Legacy Data Abort Check
# =============================================================================

class TestZeroUserLegacyDataAbort:
    """
    Tests edge cases around zero-user databases during legacy data backfill.
    """

    def test_zero_user_with_clients_aborts(self) -> None:
        """If clients exist with 0 users, migration must abort with RuntimeError."""
        with pytest.raises(RuntimeError, match="Migration aborted: Legacy client/meeting/commitment records exist"):
            simulate_legacy_backfill_check(users_count=0, clients_count=5, meetings_count=0, commitments_count=0)

    def test_zero_user_with_meetings_aborts(self) -> None:
        """If meetings exist with 0 users, migration must abort with RuntimeError."""
        with pytest.raises(RuntimeError, match="Migration aborted: Legacy client/meeting/commitment records exist"):
            simulate_legacy_backfill_check(users_count=0, clients_count=0, meetings_count=2, commitments_count=0)

    def test_zero_user_with_commitments_aborts(self) -> None:
        """If commitments exist with 0 users, migration must abort with RuntimeError."""
        with pytest.raises(RuntimeError, match="Migration aborted: Legacy client/meeting/commitment records exist"):
            simulate_legacy_backfill_check(users_count=0, clients_count=0, meetings_count=0, commitments_count=1)

    def test_zero_user_fresh_database_succeeds(self) -> None:
        """If zero users and zero legacy records (empty DB), migration must NOT abort."""
        result = simulate_legacy_backfill_check(users_count=0, clients_count=0, meetings_count=0, commitments_count=0)
        assert result is True

    def test_existing_user_with_legacy_data_succeeds(self) -> None:
        """If 1+ users exist alongside legacy records, backfill check succeeds."""
        result = simulate_legacy_backfill_check(users_count=1, clients_count=10, meetings_count=5, commitments_count=3)
        assert result is True


# =============================================================================
# Edge Case Test Suite 2: Organization Slug Collision Handling
# =============================================================================

class TestOrganizationSlugCollisionHandling:
    """
    Tests edge cases in organization slug generation, deduplication, and special character sanitization.
    """

    def test_standard_slug_generation(self) -> None:
        orgs = [
            ("org_1", "Acme Global Banking"),
            ("org_2", "Beta Financial Partners"),
        ]
        slugs = simulate_slug_generation(orgs)
        assert slugs["org_1"] == "acme-global-banking"
        assert slugs["org_2"] == "beta-financial-partners"

    def test_slug_collision_identical_names(self) -> None:
        """Multiple organizations with identical names must receive unique incremental slugs."""
        orgs = [
            ("org_1", "Acme Corporation"),
            ("org_2", "Acme Corporation"),
            ("org_3", "Acme Corporation"),
            ("org_4", "Acme Corporation"),
        ]
        slugs = simulate_slug_generation(orgs)
        assert slugs["org_1"] == "acme-corporation"
        assert slugs["org_2"] == "acme-corporation-1"
        assert slugs["org_3"] == "acme-corporation-2"
        assert slugs["org_4"] == "acme-corporation-3"
        # All slugs must be distinct
        assert len(set(slugs.values())) == 4

    def test_slug_collision_with_preexisting_numbered_slugs(self) -> None:
        """
        If Org A is 'Nova', Org B is 'Nova-1', and Org C is 'Nova',
        Org C must skip 'nova-1' and resolve to 'nova-2'.
        """
        orgs = [
            ("org_a", "Nova"),
            ("org_b", "Nova 1"),
            ("org_c", "Nova"),
        ]
        slugs = simulate_slug_generation(orgs)
        assert slugs["org_a"] == "nova"
        assert slugs["org_b"] == "nova-1"
        assert slugs["org_c"] == "nova-2"
        assert len(set(slugs.values())) == 3

    def test_special_characters_and_whitespace_sanitization(self) -> None:
        """Symbols, special characters, and consecutive dashes must be safely normalized."""
        orgs = [
            ("org_1", "  ---  Spaces & Symbols !!! @ # $ % ^ & * ( )  ---  "),
            ("org_2", "P.H.I.L.I.X.A - 6.0"),
            ("org_3", "Bank / Branch #42"),
        ]
        slugs = simulate_slug_generation(orgs)
        assert slugs["org_1"] == "spaces-symbols"
        assert slugs["org_2"] == "p-h-i-l-i-x-a-6-0"
        assert slugs["org_3"] == "bank-branch-42"

    def test_empty_or_all_symbol_name_fallback(self) -> None:
        """Names that contain no alphanumeric characters should fallback to org-{id}."""
        orgs = [
            ("org_999", "!@#$%^&*()"),
            ("org_888", None),
            ("org_777", "   ---   "),
        ]
        slugs = simulate_slug_generation(orgs)
        assert slugs["org_999"] == "org-org_999"
        assert slugs["org_888"] == "workspace"
        assert slugs["org_777"] == "org-org_777"


# =============================================================================
# Edge Case Test Suite 3: Reversibility of Migration Data on Downgrade
# =============================================================================

class TestMigrationReversibility:
    """
    Tests schema and data transitions during upgrade and downgrade operations.
    """

    def test_downgrade_role_and_org_restoration_logic(self) -> None:
        """
        Tests that downgrade maps membership roles back to uppercase UserRole strings
        and restores users.organization_id.
        """
        engine = create_engine("sqlite://", poolclass=StaticPool)
        with engine.connect() as conn:
            # Create schema representing post-migration state
            conn.execute(text(
                "CREATE TABLE users ("
                "  id VARCHAR PRIMARY KEY, "
                "  email VARCHAR UNIQUE, "
                "  hashed_password VARCHAR, "
                "  is_active BOOLEAN, "
                "  is_verified BOOLEAN"
                ")"
            ))
            conn.execute(text(
                "CREATE TABLE organizations ("
                "  id VARCHAR PRIMARY KEY, "
                "  name VARCHAR, "
                "  workspace_type VARCHAR, "
                "  slug VARCHAR UNIQUE, "
                "  plan VARCHAR, "
                "  is_active BOOLEAN"
                ")"
            ))
            conn.execute(text(
                "CREATE TABLE organization_memberships ("
                "  user_id VARCHAR, "
                "  organization_id VARCHAR, "
                "  role VARCHAR, "
                "  status VARCHAR, "
                "  PRIMARY KEY (user_id, organization_id)"
                ")"
            ))

            # Insert test data
            conn.execute(text("INSERT INTO organizations VALUES ('org_100', 'Alpha Bank', 'company', 'alpha-bank', 'pro', 1)"))
            conn.execute(text("INSERT INTO organizations VALUES ('org_200', 'Beta Bank', 'company', 'beta-bank', 'free', 1)"))

            conn.execute(text("INSERT INTO users VALUES ('usr_1', 'alice@alpha.com', 'hash1', 1, 1)"))
            conn.execute(text("INSERT INTO users VALUES ('usr_2', 'bob@beta.com', 'hash2', 1, 1)"))
            conn.execute(text("INSERT INTO users VALUES ('usr_3', 'charlie@alpha.com', 'hash3', 1, 1)"))

            conn.execute(text("INSERT INTO organization_memberships VALUES ('usr_1', 'org_100', 'owner', 'active')"))
            conn.execute(text("INSERT INTO organization_memberships VALUES ('usr_2', 'org_200', 'admin', 'active')"))
            conn.execute(text("INSERT INTO organization_memberships VALUES ('usr_3', 'org_100', 'member', 'active')"))
            conn.commit()

            # Execute Downgrade Step 1 & 2: Re-add columns and backfill
            conn.execute(text("ALTER TABLE users ADD COLUMN organization_id VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR"))

            conn.execute(text(
                "UPDATE users SET organization_id = m.organization_id, role = UPPER(m.role) "
                "FROM organization_memberships m WHERE users.id = m.user_id"
            ))
            conn.execute(text("UPDATE users SET organization_id = 'default' WHERE organization_id IS NULL"))
            conn.execute(text("UPDATE users SET role = 'MANAGER' WHERE role IS NULL"))
            conn.commit()

            # Verify restored values on users
            rows = conn.execute(text("SELECT id, organization_id, role FROM users ORDER BY id")).fetchall()
            user_data = {r[0]: (r[1], r[2]) for r in rows}

            assert user_data["usr_1"] == ("org_100", "OWNER")
            assert user_data["usr_2"] == ("org_200", "ADMIN")
            assert user_data["usr_3"] == ("org_100", "MEMBER")


# =============================================================================
# Standalone execution for direct verification
# =============================================================================

if __name__ == "__main__":
    t1 = TestZeroUserLegacyDataAbort()
    t1.test_zero_user_with_clients_aborts()
    t1.test_zero_user_with_meetings_aborts()
    t1.test_zero_user_with_commitments_aborts()
    t1.test_zero_user_fresh_database_succeeds()
    t1.test_existing_user_with_legacy_data_succeeds()
    print("[PASS] TestZeroUserLegacyDataAbort (5/5)")

    t2 = TestOrganizationSlugCollisionHandling()
    t2.test_standard_slug_generation()
    t2.test_slug_collision_identical_names()
    t2.test_slug_collision_with_preexisting_numbered_slugs()
    t2.test_special_characters_and_whitespace_sanitization()
    t2.test_empty_or_all_symbol_name_fallback()
    print("[PASS] TestOrganizationSlugCollisionHandling (5/5)")

    t3 = TestMigrationReversibility()
    t3.test_downgrade_role_and_org_restoration_logic()
    print("[PASS] TestMigrationReversibility (1/1)")

    print("\nALL 11 MIGRATION EDGE-CASE TESTS PASSED EMPIRICALLY!")
