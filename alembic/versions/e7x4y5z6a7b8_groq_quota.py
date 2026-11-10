"""Shared Groq admission and cooldown ledger."""
from alembic import op
from app.models.groq_quota import GroqQuotaRequest,GroqQuotaCooldown
revision='e7x4y5z6a7b8'
down_revision='d6w3x4y5z6a7'
branch_labels=None
depends_on=None

def upgrade():
    # Reuse the strict compatibility adoption check used by the preceding migration.
    from sqlalchemy import inspect
    for table in (GroqQuotaRequest.__table__,GroqQuotaCooldown.__table__):
        bind=op.get_bind()
        if inspect(bind).has_table(table.name):
            actual={c['name']:c for c in inspect(bind).get_columns(table.name)}
            if set(actual)!=set(table.columns.keys()):raise RuntimeError('Quota schema mismatch')
            for col in table.columns:
                a=actual[col.name]
                if a['nullable']!=col.nullable or a['type']._type_affinity!=col.type._type_affinity:
                    raise RuntimeError('Quota column mismatch')
        else:table.create(bind)

def downgrade():
    op.drop_table('groq_quota_requests');op.drop_table('groq_quota_cooldowns')
