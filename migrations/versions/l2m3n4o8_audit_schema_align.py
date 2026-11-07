"""مواءمة GRN مع الموديل

Revision ID: l2m3n4o8
Revises: k1l2m3n4o7
"""
from alembic import op
import sqlalchemy as sa


revision = "l2m3n4o8"
down_revision = "k1l2m3n4o7"
branch_labels = None
depends_on = None


def _table_columns(inspector, table_name):
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    line_cols = _table_columns(inspector, "goods_receipt_lines")
    if line_cols:
        with op.batch_alter_table("goods_receipt_lines", schema=None) as batch_op:
            if "created_at" not in line_cols:
                batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
            if "updated_at" not in line_cols:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    receipt_cols = _table_columns(inspector, "goods_receipts")
    if receipt_cols:
        with op.batch_alter_table("goods_receipts", schema=None) as batch_op:
            if "created_by" in receipt_cols:
                batch_op.drop_column("created_by")
            if "updated_by" in receipt_cols:
                batch_op.drop_column("updated_by")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    receipt_cols = _table_columns(inspector, "goods_receipts")
    if receipt_cols:
        with op.batch_alter_table("goods_receipts", schema=None) as batch_op:
            if "created_by" not in receipt_cols:
                batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
            if "updated_by" not in receipt_cols:
                batch_op.add_column(sa.Column("updated_by", sa.Integer(), nullable=True))

    line_cols = _table_columns(inspector, "goods_receipt_lines")
    if line_cols:
        with op.batch_alter_table("goods_receipt_lines", schema=None) as batch_op:
            if "updated_at" in line_cols:
                batch_op.drop_column("updated_at")
            if "created_at" in line_cols:
                batch_op.drop_column("created_at")
