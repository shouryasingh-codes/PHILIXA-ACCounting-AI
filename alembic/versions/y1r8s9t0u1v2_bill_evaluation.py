"""Day 9 scoped evaluation measurements."""
from alembic import op
revision='y1r8s9t0u1v2'
down_revision='x0q7r8s9t0u1'
branch_labels=None
depends_on=None
def upgrade():
    from app.models.bill_evaluation import BillEvaluationMetric
    BillEvaluationMetric.__table__.create(op.get_bind(),checkfirst=True)
def downgrade():op.drop_table('bill_evaluation_metrics')
