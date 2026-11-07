"""عزل GL: إضافة company_id إلى gl_batches + لقطة fx على gl_entries

Revision ID: o8q9r0s1
Revises: n7p8q9r0
"""
from alembic import op
import sqlalchemy as sa


revision = "o8q9r0s1"
down_revision = "g1h2i3j4_schema_align"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. إضافة company_id إلى gl_batches (nullable أولاً)
    try:
        op.add_column("gl_batches", sa.Column("company_id", sa.Integer(), nullable=True))
    except Exception:
        pass

    # backfill: company_id=1 لجميع القيود (مستأجر واحد حالياً)
    conn.execute(sa.text("UPDATE gl_batches SET company_id = 1 WHERE company_id IS NULL"))

    # فهرس
    try:
        op.create_index("ix_gl_batches_company_id", "gl_batches", ["company_id"])
    except Exception:
        pass

    # 2. لقطة FX على gl_entries (nullable — تعبئة اختيارية)
    try:
        op.add_column("gl_entries", sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True))
    except Exception:
        pass
    try:
        op.add_column("gl_entries", sa.Column("fx_currency", sa.String(10), nullable=True))
    except Exception:
        pass


def downgrade():
    try:
        op.drop_index("ix_gl_batches_company_id", table_name="gl_batches")
    except Exception:
        pass
    try:
        op.drop_column("gl_batches", "company_id")
    except Exception:
        pass
    try:
        op.drop_column("gl_entries", "fx_rate")
    except Exception:
        pass
    try:
        op.drop_column("gl_entries", "fx_currency")
    except Exception:
        pass
