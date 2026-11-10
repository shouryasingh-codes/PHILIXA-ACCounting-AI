"""Add scoped intent-routing journal."""
from alembic import op
from app.models.business_route import BusinessRoute
revision='f8y5z6a7b8c9'
down_revision='e7x4y5z6a7b8'
branch_labels=None
depends_on=None


def upgrade():
    # Dev startup creates metadata tables. Adopt only an exactly compatible table.
    from sqlalchemy import inspect
    table=BusinessRoute.__table__;bind=op.get_bind();inspector=inspect(bind)
    if not inspector.has_table(table.name):
        table.create(bind);return
    actual={c['name']:c for c in inspector.get_columns(table.name)}
    if set(actual)!=set(table.columns.keys()):raise RuntimeError('Routing schema mismatch')
    for col in table.columns:
        a=actual[col.name]
        if (a['nullable']!=col.nullable or a['type']._type_affinity!=col.type._type_affinity
                or getattr(a['type'],'length',None)!=getattr(col.type,'length',None)):
            raise RuntimeError('Routing column mismatch')
    unique={tuple(c['column_names']) for c in inspector.get_unique_constraints(table.name)}
    if ('organization_id','user_id','request_id') not in unique:raise RuntimeError('Routing request uniqueness missing')
    if inspector.get_pk_constraint(table.name)['constrained_columns']!=['id']:raise RuntimeError('Routing primary key mismatch')


def downgrade():
    op.drop_table('business_routes')
