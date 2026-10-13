"""Company-scoped GST tax ledgers."""
from alembic import op
import sqlalchemy as sa
revision='v8o5p6q7r8s9'
down_revision='u7n4o5p6q7r8'
branch_labels=None
depends_on=None

def upgrade():
    if not sa.inspect(op.get_bind()).has_table('purchase_tax_profiles'):
        op.create_table('purchase_tax_profiles',sa.Column('company_id',sa.String(32),sa.ForeignKey('tally_read_companies.id',ondelete='CASCADE'),primary_key=True),sa.Column('data',sa.JSON(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False))
def downgrade():op.drop_table('purchase_tax_profiles')
