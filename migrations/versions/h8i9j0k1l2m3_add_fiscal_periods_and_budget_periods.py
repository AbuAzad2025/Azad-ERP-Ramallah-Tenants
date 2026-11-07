"""add fiscal periods, period closes, entity snapshots, budget period columns

Revision ID: h8i9j0k1l2m3
Revises: 94948c531c03
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "h8i9j0k1l2m3"
down_revision = "94948c531c03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fiscal_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("period_key", sa.String(length=32), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_key"),
        sa.CheckConstraint("end_date >= start_date", name="ck_fiscal_period_dates"),
    )
    op.create_index("ix_fiscal_periods_period_key", "fiscal_periods", ["period_key"])
    op.create_index("ix_fiscal_periods_fiscal_year", "fiscal_periods", ["fiscal_year"])
    op.create_index("ix_fiscal_period_year_type", "fiscal_periods", ["fiscal_year", "period_type"])

    op.create_table(
        "period_closes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("fiscal_period_id", sa.Integer(), nullable=False),
        sa.Column("close_scope", sa.String(length=20), nullable=False),
        sa.Column("net_income", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_revenue", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_expenses", sa.Numeric(14, 2), nullable=True),
        sa.Column("gl_batch_ids", sa.Text(), nullable=True),
        sa.Column("carry_forward_done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reopened_at", sa.DateTime(), nullable=True),
        sa.Column("reopened_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_period_id"], ["fiscal_periods.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reopened_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_period_closes_fiscal_period_id", "period_closes", ["fiscal_period_id"])

    op.create_table(
        "entity_period_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("period_close_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_period_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("closing_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("applied_to_opening", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("next_period_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["fiscal_period_id"], ["fiscal_periods.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["next_period_id"], ["fiscal_periods.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["period_close_id"], ["period_closes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fiscal_period_id", "entity_type", "entity_id", name="uq_entity_period_balance"),
    )

    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("period_type", sa.String(length=20), server_default="ANNUAL", nullable=False)
        )
        batch_op.add_column(
            sa.Column("period_number", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("period_end", sa.Date(), nullable=True))

    try:
        op.drop_constraint("uq_budget_year_account_branch_site", "budgets", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint(
        "uq_budget_period_account_branch_site",
        "budgets",
        ["fiscal_year", "period_type", "period_number", "account_code", "branch_id", "site_id"],
    )


def downgrade():
    try:
        op.drop_constraint("uq_budget_period_account_branch_site", "budgets", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint(
        "uq_budget_year_account_branch_site",
        "budgets",
        ["fiscal_year", "account_code", "branch_id", "site_id"],
    )
    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.drop_column("period_end")
        batch_op.drop_column("period_start")
        batch_op.drop_column("period_number")
        batch_op.drop_column("period_type")

    op.drop_table("entity_period_balances")
    op.drop_table("period_closes")
    op.drop_table("fiscal_periods")
