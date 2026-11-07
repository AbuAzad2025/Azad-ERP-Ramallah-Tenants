"""extend audit_logs.action from 20 to 100 chars

Revision ID: fix_audit_action_length
Revises: n7p8q9r0
"""
from alembic import op
import sqlalchemy as sa

revision = "fix_audit_action_length"
down_revision = "n7p8q9r0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(length=20),
            type_=sa.String(length=100),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(length=100),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
