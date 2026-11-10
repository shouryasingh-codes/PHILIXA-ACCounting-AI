"""Durable chat document associations; no cascades into accounting history."""
from alembic import op
from sqlalchemy import inspect
from app.models.chat_attachment import ChatBillMessage,ChatBillAttachment
revision='g9z6a7b8c9d0'
down_revision='f8y5z6a7b8c9'
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    for table in (ChatBillMessage.__table__,ChatBillAttachment.__table__):
        if not inspect(bind).has_table(table.name):table.create(bind)
        elif set(c['name'] for c in inspect(bind).get_columns(table.name))!=set(table.columns.keys()):
            raise RuntimeError('Chat attachment schema mismatch')


def downgrade():
    op.drop_table('chat_bill_attachments');op.drop_table('chat_bill_messages')
