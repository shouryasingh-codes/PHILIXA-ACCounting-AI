"""Durable common agent tasks, runs and tool execution evidence."""
from alembic import op
import sqlalchemy as sa

revision = 'd6w3x4y5z6a7'
down_revision = 'c5v2w3x4y5z6'
branch_labels = None
depends_on = None


def create_checked(name, *parts):
    # Existing regression fixtures use metadata.create_all. Adopt only an exact
    # compatible table; never silently accept a different pre-existing schema.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        return op.create_table(name, *parts)
    expected = {p.name:p for p in parts if isinstance(p,sa.Column)}
    actual = {p['name']:p for p in inspector.get_columns(name)}
    if set(actual) != set(expected):
        raise RuntimeError('Existing '+name+' schema differs from migration')
    for key,col in expected.items():
        reflected = actual[key]['type']
        compatible = reflected._type_affinity == col.type._type_affinity
        if isinstance(col.type,sa.String):
            compatible = compatible and reflected.length == col.type.length
        if isinstance(col.type,sa.DateTime):
            compatible = compatible and reflected.timezone == col.type.timezone
        if not compatible or actual[key]['nullable'] != col.nullable:
            raise RuntimeError('Existing '+name+'.'+key+' differs from migration')
    if set(inspector.get_pk_constraint(name)['constrained_columns']) != {k for k,c in expected.items() if c.primary_key}:
        raise RuntimeError('Existing primary key differs: '+name)
    for constraint in parts:
        if isinstance(constraint,sa.UniqueConstraint):
            columns = set(constraint.columns.keys()) or set(constraint._pending_colargs)
            if not any(set(c['column_names']) == columns for c in inspector.get_unique_constraints(name)):
                raise RuntimeError('Existing unique constraint differs: '+name)


def upgrade():
    create_checked('agent_tasks',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('organization_id', sa.String(100), nullable=False, index=True),
        sa.Column('user_id', sa.String(100), nullable=False, index=True),
        sa.Column('company_id', sa.String(32)),
        sa.Column('request_id', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, index=True),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('lease_token', sa.String(32)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('organization_id', 'user_id', 'request_id'))
    create_checked('agent_runs',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('task_id', sa.String(32), nullable=False, index=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    create_checked('agent_executions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('task_id', sa.String(32), nullable=False, index=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('call_key', sa.String(64), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('task_id', 'revision', 'call_key'))


def downgrade():
    for table in ('agent_executions', 'agent_runs', 'agent_tasks'):
        op.drop_table(table)
