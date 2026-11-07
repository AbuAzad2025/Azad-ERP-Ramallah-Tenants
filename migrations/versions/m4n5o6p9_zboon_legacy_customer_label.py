"""تحديث تسمية الزبون الافتراضي في البيانات القديمة

Revision ID: m4n5o6p9
Revises: l2m3n4o8
"""
from alembic import op


revision = "m4n5o6p9"
down_revision = "l2m3n4o8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE customers SET name = 'زبون غير محدد' "
        "WHERE name = 'عميل غير محدد'"
    )


def downgrade():
    op.execute(
        "UPDATE customers SET name = 'عميل غير محدد' "
        "WHERE name = 'زبون غير محدد'"
    )
