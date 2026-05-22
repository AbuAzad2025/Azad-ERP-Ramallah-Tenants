"""expand audit_logs.action length to 64

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-23

أحداث التدقيق (مثل login.master_key_success_tenant) أطول من varchar(20).
"""
from alembic import op
import sqlalchemy as sa


revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(20),
            type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(64),
            type_=sa.String(20),
            existing_nullable=False,
        )
