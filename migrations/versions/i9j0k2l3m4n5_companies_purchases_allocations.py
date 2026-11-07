"""companies, purchase orders, payment allocations

Revision ID: i9j0k2l3m4n5
Revises: h8i9j0k1l2m3
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "i9j0k2l3m4n5"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=250), nullable=True),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="ILS", nullable=False),
        sa.Column("fiscal_year_start_month", sa.Integer(), server_default="1", nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    with op.batch_alter_table("branches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    op.execute(
        """
        INSERT INTO companies (name, code, legal_name, currency, fiscal_year_start_month, is_active, created_at, updated_at)
        VALUES ('الشركة الرئيسية', 'MAIN', 'الشركة الرئيسية', 'ILS', 1, true, NOW(), NOW())
        """
    )
    op.execute("UPDATE branches SET company_id = (SELECT id FROM companies WHERE code = 'MAIN' LIMIT 1) WHERE company_id IS NULL")

    with op.batch_alter_table("branches", schema=None) as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_foreign_key("fk_branches_company_id", "companies", ["company_id"], ["id"], ondelete="RESTRICT")
        batch_op.create_index("ix_branches_company_id", ["company_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("number", sa.String(length=50), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="ILS", nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.CheckConstraint("total_amount >= 0", name="ck_po_total_ge_0"),
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("received_qty", sa.Numeric(12, 3), server_default="0", nullable=False),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "entity_type", "entity_id", name="uq_payment_alloc_target"),
        sa.CheckConstraint("amount > 0", name="ck_payment_alloc_amt_pos"),
    )

    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("purchase_order_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shipments_purchase_order_id", "purchase_orders", ["purchase_order_id"], ["id"], ondelete="SET NULL"
        )


def downgrade():
    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.drop_constraint("fk_shipments_purchase_order_id", type_="foreignkey")
        batch_op.drop_column("purchase_order_id")

    op.drop_table("payment_allocations")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")

    with op.batch_alter_table("branches", schema=None) as batch_op:
        batch_op.drop_constraint("fk_branches_company_id", type_="foreignkey")
        batch_op.drop_index("ix_branches_company_id")
        batch_op.drop_column("company_id")

    op.drop_table("companies")
