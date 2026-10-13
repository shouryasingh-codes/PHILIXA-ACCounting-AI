"""Add read permissions and paired devices without changing pilot write configuration."""
from alembic import op
from app.models.tally import TallyDevice, TallyReadCompany
revision = 'm9f6g7h8i9j0'
down_revision = 'l8e5f6g7h8i9'
branch_labels = depends_on = None

def upgrade():
    TallyDevice.__table__.create(op.get_bind(), checkfirst=True)
    TallyReadCompany.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    op.drop_table('tally_read_companies')
    op.drop_table('tally_devices')
