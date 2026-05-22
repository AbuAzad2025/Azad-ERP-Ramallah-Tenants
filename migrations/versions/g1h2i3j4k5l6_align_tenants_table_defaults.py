"""align tenants table defaults

Revision ID: g1h2i3j4k5l6
Revises: c4d5e6f7a8b9
Create Date: 2026-05-22

يضبط القيم الافتراضية لجدول tenants لتطابق الإنتاج والنماذج.
"""
from alembic import op


revision = "g1h2i3j4k5l6"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE tenants ALTER COLUMN is_active SET DEFAULT true")
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade():
    op.execute("ALTER TABLE tenants ALTER COLUMN is_active DROP DEFAULT")
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at DROP DEFAULT")
