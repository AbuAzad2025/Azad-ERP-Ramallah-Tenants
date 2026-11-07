"""عزل الشركات: warehouse.branch_id إلزامي + صلاحية view_all_branches

Revision ID: n7p8q9r0
Revises: m4n5o6p9
"""
from alembic import op
import sqlalchemy as sa


revision = "n7p8q9r0"
down_revision = "m4n5o6p9"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE warehouses SET branch_id = (
                SELECT id FROM branches ORDER BY id ASC LIMIT 1
            ) WHERE branch_id IS NULL
            """
        )
    )
    with op.batch_alter_table("warehouses", schema=None) as batch_op:
        batch_op.alter_column("branch_id", existing_type=sa.Integer(), nullable=False)

    conn.execute(
        sa.text(
            """
            INSERT INTO permissions (name, code, description, name_ar, module, is_protected)
            SELECT 'view_all_branches', 'view_all_branches', 'عرض كل الفروع والشركات', 'عرض كل الفروع', 'branches', true
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'view_all_branches')
            """
        )
    )


def downgrade():
    with op.batch_alter_table("warehouses", schema=None) as batch_op:
        batch_op.alter_column("branch_id", existing_type=sa.Integer(), nullable=True)
    op.execute("DELETE FROM permissions WHERE name = 'view_all_branches'")
