"""تفوق ERP: GRN، عروض أسعار، دفع فواتير مورد، مراكز تكلفة على القيود

Revision ID: k1l2m3n4o7
Revises: j0k1l2m3n4o6
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "k1l2m3n4o7"
down_revision = "j0k1l2m3n4o6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_quotation", sa.Boolean(), server_default=sa.text("false"), nullable=False)
        )
        batch_op.create_index("ix_sales_is_quotation", ["is_quotation"], unique=False)

    with op.batch_alter_table("supplier_invoices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("amount_paid", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False)
        )

    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("supplier_invoice_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_payments_supplier_invoice",
            "supplier_invoices",
            ["supplier_invoice_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_payments_supplier_invoice_id", ["supplier_invoice_id"], unique=False)

    with op.batch_alter_table("gl_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cost_center_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_gl_entries_cost_center", "cost_centers", ["cost_center_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_gl_entries_cost_center_id", ["cost_center_id"], unique=False)

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="POSTED", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index("ix_goods_receipts_po", "goods_receipts", ["purchase_order_id"], unique=False)

    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()
    for key, val in (
        ("enable_fixed_assets", "true"),
        ("enable_budget_module", "true"),
        ("erp_excellence_enabled", "true"),
    ):
        conn.execute(
            sa.text(
                """
                INSERT INTO system_settings (key, value, created_at, updated_at)
                SELECT :k, :v, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE key = :k)
                """
            ),
            {"k": key, "v": val},
        )


def downgrade():
    op.drop_table("goods_receipt_lines")
    op.drop_table("goods_receipts")
    with op.batch_alter_table("gl_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_gl_entries_cost_center_id")
        batch_op.drop_constraint("fk_gl_entries_cost_center", type_="foreignkey")
        batch_op.drop_column("cost_center_id")
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.drop_index("ix_payments_supplier_invoice_id")
        batch_op.drop_constraint("fk_payments_supplier_invoice", type_="foreignkey")
        batch_op.drop_column("supplier_invoice_id")
    with op.batch_alter_table("supplier_invoices", schema=None) as batch_op:
        batch_op.drop_column("amount_paid")
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.drop_index("ix_sales_is_quotation")
        batch_op.drop_column("is_quotation")
