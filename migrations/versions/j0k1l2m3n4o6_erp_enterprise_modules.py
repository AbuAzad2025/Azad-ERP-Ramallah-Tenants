"""ERP enterprise: GL branch, chart parent, AP invoices, payroll, POS channel, 2FA

Revision ID: j0k1l2m3n4o6
Revises: i9j0k2l3m4n5
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "j0k1l2m3n4o6"
down_revision = "i9j0k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_accounts_parent", "accounts", ["parent_id"], ["id"])
        batch_op.create_index("ix_accounts_parent_id", ["parent_id"], unique=False)

    with op.batch_alter_table("gl_batches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_gl_batches_branch", "branches", ["branch_id"], ["id"])
        batch_op.create_index("ix_gl_batches_branch_id", ["branch_id"], unique=False)

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("totp_secret", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("totp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
        batch_op.add_column(sa.Column("login_schedule_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("allowed_stations_json", sa.Text(), nullable=True))

    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sale_channel", sa.String(length=20), server_default="STANDARD", nullable=False)
        )
        batch_op.create_index("ix_sales_sale_channel", ["sale_channel"], unique=False)

    op.create_table(
        "supplier_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=10), server_default="ILS", nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("vat_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index("ix_supplier_invoices_supplier", "supplier_invoices", ["supplier_id"])
    op.create_index("ix_supplier_invoices_po", "supplier_invoices", ["purchase_order_id"])
    op.create_index("ix_supplier_invoices_status", "supplier_invoices", ["status"])

    op.create_table(
        "supplier_invoice_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("supplier_invoice_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["supplier_invoice_id"], ["supplier_invoices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("period_key", sa.String(length=7), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("total_gross", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_deductions", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total_net", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="ILS", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_key", "branch_id", name="uq_payroll_period_branch"),
    )

    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("payroll_run_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("base_salary", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("allowances", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("deductions", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("net_pay", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["payroll_run_id"], ["payroll_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "document_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("level_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_doc_approval_type_id",
        "document_approvals",
        ["document_type", "document_id"],
    )


def downgrade():
    op.drop_index("ix_doc_approval_type_id", table_name="document_approvals")
    op.drop_table("document_approvals")
    op.drop_table("payroll_lines")
    op.drop_table("payroll_runs")
    op.drop_table("supplier_invoice_lines")
    op.drop_index("ix_supplier_invoices_status", table_name="supplier_invoices")
    op.drop_index("ix_supplier_invoices_po", table_name="supplier_invoices")
    op.drop_index("ix_supplier_invoices_supplier", table_name="supplier_invoices")
    op.drop_table("supplier_invoices")
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.drop_index("ix_sales_sale_channel")
        batch_op.drop_column("sale_channel")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("allowed_stations_json")
        batch_op.drop_column("login_schedule_json")
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")
    with op.batch_alter_table("gl_batches", schema=None) as batch_op:
        batch_op.drop_constraint("fk_gl_batches_branch", type_="foreignkey")
        batch_op.drop_index("ix_gl_batches_branch_id")
        batch_op.drop_column("branch_id")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_constraint("fk_accounts_parent", type_="foreignkey")
        batch_op.drop_index("ix_accounts_parent_id")
        batch_op.drop_column("parent_id")
