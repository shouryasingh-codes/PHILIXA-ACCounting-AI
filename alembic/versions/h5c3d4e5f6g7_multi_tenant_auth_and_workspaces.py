"""Multi-tenant auth and workspaces

Revision ID: h5c3d4e5f6g7
Revises: b0da14c0bddb
Create Date: 2026-08-23 04:30:00.000000

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'h5c3d4e5f6g7'
down_revision: Union[str, None] = 'b0da14c0bddb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Extend organizations with nullable columns
    op.add_column('organizations', sa.Column('workspace_type', sa.String(length=20), nullable=True))
    op.add_column('organizations', sa.Column('slug', sa.String(length=80), nullable=True))
    op.add_column('organizations', sa.Column('plan', sa.String(length=20), nullable=True))

    # 2. Add is_verified to users
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), server_default='true', nullable=False))

    # 3. Create organization_memberships table
    op.create_table(
        'organization_memberships',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(length=20), server_default='member', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
        sa.Column('invited_by', sa.String(), nullable=True),
        sa.Column('invited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('user_id', 'organization_id'),
    )
    op.create_index(op.f('ix_organization_memberships_user_id'), 'organization_memberships', ['user_id'], unique=False)
    op.create_index(op.f('ix_organization_memberships_organization_id'), 'organization_memberships', ['organization_id'], unique=False)

    # 4. Create user_sessions table
    op.create_table(
        'user_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('refresh_token_hash', sa.String(length=64), nullable=False),
        sa.Column('device_info', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['user_id', 'organization_id'],
            ['organization_memberships.user_id', 'organization_memberships.organization_id'],
            ondelete='CASCADE',
            name='fk_user_sessions_membership',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_organization_id'), 'user_sessions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_refresh_token_hash'), 'user_sessions', ['refresh_token_hash'], unique=False)
    op.create_index(op.f('ix_user_sessions_expires_at'), 'user_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_user_sessions_revoked_at'), 'user_sessions', ['revoked_at'], unique=False)

    # 5. Create email_verification_tokens table
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_verification_tokens_token_hash'), 'email_verification_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_email_verification_tokens_user_id'), 'email_verification_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_email_verification_tokens_expires_at'), 'email_verification_tokens', ['expires_at'], unique=False)

    # 6. Create password_reset_tokens table
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_password_reset_tokens_token_hash'), 'password_reset_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_password_reset_tokens_expires_at'), 'password_reset_tokens', ['expires_at'], unique=False)

    # 7. Create workspace_invites table
    op.create_table(
        'workspace_invites',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(), nullable=False),
        sa.Column('invited_email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), server_default='member', nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('invited_by_user_id', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workspace_invites_organization_id'), 'workspace_invites', ['organization_id'], unique=False)
    op.create_index(op.f('ix_workspace_invites_invited_email'), 'workspace_invites', ['invited_email'], unique=False)
    op.create_index(op.f('ix_workspace_invites_token_hash'), 'workspace_invites', ['token_hash'], unique=True)
    op.create_index(op.f('ix_workspace_invites_expires_at'), 'workspace_invites', ['expires_at'], unique=False)

    # 8. Add nullable columns to clients, meetings, commitments
    op.add_column('clients', sa.Column('organization_id', sa.String(), nullable=True))
    op.add_column('clients', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('clients', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False))

    op.add_column('meetings', sa.Column('organization_id', sa.String(), nullable=True))
    op.add_column('meetings', sa.Column('user_id', sa.String(), nullable=True))

    op.add_column('commitments', sa.Column('organization_id', sa.String(), nullable=True))
    op.add_column('commitments', sa.Column('user_id', sa.String(), nullable=True))

    # 9. Legacy Backfill
    has_users = bind.execute(sa.text("SELECT id, organization_id, role FROM users")).fetchall()
    has_clients = bind.execute(sa.text("SELECT COUNT(*) FROM clients")).scalar() or 0
    has_meetings = bind.execute(sa.text("SELECT COUNT(*) FROM meetings")).scalar() or 0
    has_commitments = bind.execute(sa.text("SELECT COUNT(*) FROM commitments")).scalar() or 0
    legacy_count = has_clients + has_meetings + has_commitments

    if legacy_count > 0 and len(has_users) == 0:
        raise RuntimeError(
            "Migration aborted: Legacy client/meeting/commitment records exist, but no users exist "
            "to assign ownership. Cannot safely backfill without an owner."
        )

    # Backfill Organizations slugs & types
    existing_orgs = bind.execute(sa.text("SELECT id, name FROM organizations")).fetchall()
    used_slugs = set()
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
        bind.execute(
            sa.text(
                "UPDATE organizations SET workspace_type = COALESCE(workspace_type, 'company'), "
                "slug = :slug, plan = COALESCE(plan, 'free') WHERE id = :id"
            ),
            {"slug": slug, "id": org_id},
        )

    # Backfill Memberships from existing users
    for u in has_users:
        u_id = u[0]
        u_org_id = u[1]
        u_role = (u[2] or "member").lower()
        if u_role in ("admin", "manager"):
            u_role = "owner"
        elif u_role not in ("owner", "admin", "member"):
            u_role = "member"

        if u_org_id:
            org_exists = bind.execute(sa.text("SELECT 1 FROM organizations WHERE id = :id"), {"id": u_org_id}).fetchone()
            if not org_exists:
                org_slug = f"workspace-{u_org_id}"
                idx = 1
                while org_slug in used_slugs:
                    org_slug = f"workspace-{u_org_id}-{idx}"
                    idx += 1
                used_slugs.add(org_slug)
                bind.execute(
                    sa.text(
                        "INSERT INTO organizations (id, name, is_active, workspace_type, slug, plan, created_at, updated_at) "
                        "VALUES (:id, :name, true, 'company', :slug, 'free', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": u_org_id, "name": f"Workspace {u_org_id}", "slug": org_slug},
                )
        else:
            u_org_id = f"org_{u_id}"
            org_slug = f"user-{u_id}"
            idx = 1
            while org_slug in used_slugs:
                org_slug = f"user-{u_id}-{idx}"
                idx += 1
            used_slugs.add(org_slug)
            bind.execute(
                sa.text(
                    "INSERT INTO organizations (id, name, is_active, workspace_type, slug, plan, created_at, updated_at) "
                    "VALUES (:id, :name, true, 'individual', :slug, 'free', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": u_org_id, "name": "Personal Workspace", "slug": org_slug},
            )

        bind.execute(
            sa.text(
                "INSERT INTO organization_memberships (user_id, organization_id, role, status, joined_at, created_at, updated_at) "
                "VALUES (:user_id, :org_id, :role, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (user_id, organization_id) DO NOTHING"
            ),
            {"user_id": u_id, "org_id": u_org_id, "role": u_role},
        )

    if legacy_count > 0:
        first_user = has_users[0]
        first_user_id = first_user[0]
        first_user_org_id = first_user[1]

        legacy_org = bind.execute(sa.text("SELECT id FROM organizations WHERE id = :id"), {"id": first_user_org_id}).fetchone() if first_user_org_id else None
        if legacy_org:
            target_org_id = first_user_org_id
        else:
            target_org_id = "legacy"
            bind.execute(
                sa.text(
                    "INSERT INTO organizations (id, name, is_active, workspace_type, slug, plan, created_at, updated_at) "
                    "VALUES ('legacy', 'Legacy Workspace', true, 'company', 'legacy', 'free', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
            bind.execute(
                sa.text(
                    "INSERT INTO organization_memberships (user_id, organization_id, role, status, joined_at, created_at, updated_at) "
                    "VALUES (:user_id, 'legacy', 'owner', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (user_id, organization_id) DO NOTHING"
                ),
                {"user_id": first_user_id},
            )

        for tbl in ('clients', 'meetings', 'commitments'):
            bind.execute(
                sa.text(
                    f"UPDATE {tbl} SET organization_id = :org_id, user_id = :user_id "
                    f"WHERE organization_id IS NULL OR user_id IS NULL"
                ),
                {"org_id": target_org_id, "user_id": first_user_id},
            )

        for tbl in ('follow_up_tasks', 'risk_signals', 'meeting_evidence', 'notification_preferences', 'notification_deliveries'):
            tbl_exists = bind.execute(
                sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :tbl)"),
                {"tbl": tbl},
            ).scalar()
            if tbl_exists:
                bind.execute(
                    sa.text(
                        f"UPDATE {tbl} SET organization_id = :org_id "
                        f"WHERE organization_id IN ('SYSTEM', 'SYSTEM_ORG', 'default')"
                    ),
                    {"org_id": target_org_id},
                )
                bind.execute(
                    sa.text(
                        f"UPDATE {tbl} SET user_id = :user_id "
                        f"WHERE user_id IN ('SYSTEM', 'SYSTEM_ORG', 'default')"
                    ),
                    {"user_id": first_user_id},
                )

    # 10. Enforce constraints on organizations
    op.alter_column('organizations', 'workspace_type', nullable=False, server_default='company')
    op.alter_column('organizations', 'slug', nullable=False)
    op.alter_column('organizations', 'plan', nullable=False, server_default='free')
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)
    op.alter_column('organizations', 'workspace_type', server_default=None)
    op.alter_column('organizations', 'plan', server_default=None)

    # 11. Enforce NOT NULL and FKs on clients, meetings, commitments
    for tbl in ('clients', 'meetings', 'commitments'):
        op.alter_column(tbl, 'organization_id', nullable=False)
        op.alter_column(tbl, 'user_id', nullable=False)
        op.create_index(op.f(f'ix_{tbl}_organization_id'), tbl, ['organization_id'], unique=False)
        op.create_index(op.f(f'ix_{tbl}_user_id'), tbl, ['user_id'], unique=False)
        op.create_index(f'ix_{tbl}_org_user', tbl, ['organization_id', 'user_id'], unique=False)
        op.create_foreign_key(f'{tbl}_organization_id_fkey', tbl, 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key(f'{tbl}_user_id_fkey', tbl, 'users', ['user_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key(
            f'fk_{tbl}_membership',
            tbl,
            'organization_memberships',
            ['user_id', 'organization_id'],
            ['user_id', 'organization_id'],
            ondelete='CASCADE',
        )

    # 12. Drop single-org columns from users
    op.drop_constraint('users_organization_id_fkey', 'users', type_='foreignkey')
    op.drop_index('ix_users_organization_id', table_name='users')
    op.drop_column('users', 'organization_id')
    op.drop_column('users', 'role')
    op.alter_column('users', 'is_verified', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Re-add organization_id and role to users
    op.add_column('users', sa.Column('organization_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('role', sa.String(), nullable=True))

    # 2. Backfill users.organization_id and users.role from organization_memberships
    bind.execute(
        sa.text(
            "UPDATE users SET organization_id = m.organization_id, role = UPPER(m.role) "
            "FROM organization_memberships m WHERE users.id = m.user_id"
        )
    )
    bind.execute(sa.text("UPDATE users SET organization_id = 'default' WHERE organization_id IS NULL"))
    bind.execute(sa.text("UPDATE users SET role = 'MANAGER' WHERE role IS NULL"))

    op.alter_column('users', 'organization_id', nullable=False)
    op.alter_column('users', 'role', nullable=False)
    op.create_index(op.f('ix_users_organization_id'), 'users', ['organization_id'], unique=False)
    op.create_foreign_key('users_organization_id_fkey', 'users', 'organizations', ['organization_id'], ['id'])

    # 3. Drop FK constraints and columns from clients, meetings, commitments
    for tbl in ('clients', 'meetings', 'commitments'):
        op.drop_constraint(f'fk_{tbl}_membership', tbl, type_='foreignkey')
        op.drop_constraint(f'{tbl}_user_id_fkey', tbl, type_='foreignkey')
        op.drop_constraint(f'{tbl}_organization_id_fkey', tbl, type_='foreignkey')
        op.drop_index(f'ix_{tbl}_org_user', table_name=tbl)
        op.drop_index(op.f(f'ix_{tbl}_user_id'), table_name=tbl)
        op.drop_index(op.f(f'ix_{tbl}_organization_id'), table_name=tbl)
        op.drop_column(tbl, 'user_id')
        op.drop_column(tbl, 'organization_id')

    # 4. Drop new tables
    op.drop_index(op.f('ix_workspace_invites_expires_at'), table_name='workspace_invites')
    op.drop_index(op.f('ix_workspace_invites_token_hash'), table_name='workspace_invites')
    op.drop_index(op.f('ix_workspace_invites_invited_email'), table_name='workspace_invites')
    op.drop_index(op.f('ix_workspace_invites_organization_id'), table_name='workspace_invites')
    op.drop_table('workspace_invites')

    op.drop_index(op.f('ix_password_reset_tokens_expires_at'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_token_hash'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    op.drop_index(op.f('ix_email_verification_tokens_expires_at'), table_name='email_verification_tokens')
    op.drop_index(op.f('ix_email_verification_tokens_user_id'), table_name='email_verification_tokens')
    op.drop_index(op.f('ix_email_verification_tokens_token_hash'), table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')

    op.drop_index(op.f('ix_user_sessions_revoked_at'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_expires_at'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_refresh_token_hash'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_organization_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_table('user_sessions')

    op.drop_index(op.f('ix_organization_memberships_organization_id'), table_name='organization_memberships')
    op.drop_index(op.f('ix_organization_memberships_user_id'), table_name='organization_memberships')
    op.drop_table('organization_memberships')

    # 5. Drop columns from organizations and users
    op.drop_index(op.f('ix_organizations_slug'), table_name='organizations')
    op.drop_column('organizations', 'plan')
    op.drop_column('organizations', 'slug')
    op.drop_column('organizations', 'workspace_type')

    op.drop_column('users', 'is_verified')
