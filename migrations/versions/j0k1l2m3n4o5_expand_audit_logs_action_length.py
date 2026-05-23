"""expand audit_logs.action length to 64

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-23

أحداث التدقيق (مثل login.master_key_success_tenant) أطول من varchar(20).
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def _tenant_schema() -> str:
    sch = (os.getenv("TENANT_SCHEMA") or "").strip() or "public"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if len(sch) > 63 or any(ch not in allowed for ch in sch):
        raise ValueError("invalid TENANT_SCHEMA")
    return sch


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sch = _tenant_schema()
        bind.execute(
            text(f"ALTER TABLE {sch}.audit_logs ALTER COLUMN action TYPE VARCHAR(64)")
        )
        return
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(20),
            type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sch = _tenant_schema()
        bind.execute(
            text(f"ALTER TABLE {sch}.audit_logs ALTER COLUMN action TYPE VARCHAR(20)")
        )
        return
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "action",
            existing_type=sa.String(64),
            type_=sa.String(20),
            existing_nullable=False,
        )
