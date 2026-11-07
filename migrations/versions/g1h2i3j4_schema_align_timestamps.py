"""Align timestamp nullability with ORM metadata (safe when no NULL rows).

Revision ID: g1h2i3j4_schema_align
Revises: fix_audit_action_length
"""
from alembic import op
import sqlalchemy as sa

revision = "g1h2i3j4_schema_align"
down_revision = "fix_audit_action_length"
branch_labels = None
depends_on = None

_TIMESTAMP_TABLES = (
    "companies",
    "document_approvals",
    "entity_period_balances",
    "fiscal_periods",
    "goods_receipt_lines",
    "goods_receipts",
    "payment_allocations",
    "payroll_lines",
    "payroll_runs",
    "period_closes",
    "purchase_order_lines",
    "purchase_orders",
    "supplier_invoice_lines",
    "supplier_invoices",
)


def _set_not_null(table: str, column: str) -> None:
    bind = op.get_bind()
    nulls = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
    ).scalar()
    if nulls:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {column} = CURRENT_TIMESTAMP "
                f"WHERE {column} IS NULL"
            )
        )
    op.alter_column(table, column, existing_type=sa.DateTime(), nullable=False)


def upgrade():
    for table in _TIMESTAMP_TABLES:
        _set_not_null(table, "created_at")
        _set_not_null(table, "updated_at")

    bind = op.get_bind()
    wh_nulls = bind.execute(
        sa.text("SELECT COUNT(*) FROM warehouses WHERE branch_id IS NULL")
    ).scalar()
    if not wh_nulls:
        op.alter_column(
            "warehouses",
            "branch_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade():
    for table in _TIMESTAMP_TABLES:
        op.alter_column(table, "created_at", existing_type=sa.DateTime(), nullable=True)
        op.alter_column(table, "updated_at", existing_type=sa.DateTime(), nullable=True)
    op.alter_column(
        "warehouses",
        "branch_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
