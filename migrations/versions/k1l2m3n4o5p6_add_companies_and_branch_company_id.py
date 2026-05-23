"""add companies table and branch.company_id

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-23

شركات داخل كل schema تينانت + ربط الفروع.
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def _backfill_companies(connection):
    sch = _tenant_schema()
    meta = sa.MetaData()
    companies = sa.Table("companies", meta, schema=sch, autoload_with=connection)
    branches = sa.Table("branches", meta, schema=sch, autoload_with=connection)

    existing = connection.execute(sa.select(companies.c.id).limit(1)).first()
    if existing:
        default_co_id = existing[0]
    else:
        connection.execute(
            companies.insert().values(
                name="الشركة الافتراضية",
                code="DEFAULT",
                legal_name="الشركة الافتراضية",
                currency="ILS",
                fiscal_year_start_month=1,
                is_active=True,
            )
        )
        default_co_id = connection.execute(
            sa.select(companies.c.id).where(companies.c.code == "DEFAULT").limit(1)
        ).scalar_one()

    connection.execute(
        branches.update()
        .where(branches.c.company_id.is_(None))
        .values(company_id=default_co_id)
    )


def _dedupe_branch_codes(connection):
    """إزالة تعارض (company_id, code) قبل فرض القيد الفريد."""
    sch = _tenant_schema()
    meta = sa.MetaData()
    branches = sa.Table("branches", meta, schema=sch, autoload_with=connection)
    rows = connection.execute(
        sa.select(branches.c.id, branches.c.company_id, branches.c.code).order_by(
            branches.c.company_id, branches.c.code, branches.c.id
        )
    ).all()
    seen = {}
    for row in rows:
        co_id = row.company_id
        base_code = (row.code or f"BR{row.id}").strip().upper() or f"BR{row.id}"
        key = (co_id, base_code)
        if key not in seen:
            seen[key] = row.id
            if row.code != base_code:
                connection.execute(
                    branches.update().where(branches.c.id == row.id).values(code=base_code)
                )
            continue
        suffix = 2
        while True:
            candidate = f"{base_code}_{suffix}"
            if (co_id, candidate) not in seen:
                connection.execute(
                    branches.update().where(branches.c.id == row.id).values(code=candidate)
                )
                seen[(co_id, candidate)] = row.id
                break
            suffix += 1


def _tenant_schema() -> str:
    sch = (os.getenv("TENANT_SCHEMA") or "").strip()
    if not sch:
        return "public"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if len(sch) > 63 or any(ch not in allowed for ch in sch):
        raise ValueError("invalid TENANT_SCHEMA")
    return sch


def _upgrade_postgresql(bind):
    sch = _tenant_schema()
    bind.execute(text(f"SET search_path TO {sch}"))

    bind.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {sch}.companies (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                code VARCHAR(32) NOT NULL,
                legal_name VARCHAR(250),
                tax_id VARCHAR(64),
                currency VARCHAR(10) NOT NULL DEFAULT 'ILS',
                fiscal_year_start_month INTEGER NOT NULL DEFAULT 1,
                address VARCHAR(300),
                phone VARCHAR(32),
                email VARCHAR(120),
                is_active BOOLEAN NOT NULL DEFAULT true,
                notes TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                created_by INTEGER,
                updated_by INTEGER,
                CONSTRAINT uq_companies_code UNIQUE (code)
            )
            """
        )
    )
    bind.execute(text(f"CREATE INDEX IF NOT EXISTS ix_companies_name ON {sch}.companies (name)"))
    bind.execute(text(f"CREATE INDEX IF NOT EXISTS ix_companies_is_active ON {sch}.companies (is_active)"))
    bind.execute(text(f"CREATE INDEX IF NOT EXISTS ix_companies_tax_id ON {sch}.companies (tax_id)"))

    bind.execute(text(f"ALTER TABLE {sch}.branches ADD COLUMN IF NOT EXISTS company_id INTEGER"))
    _backfill_companies(bind)
    _dedupe_branch_codes(bind)
    bind.execute(text(f"ALTER TABLE {sch}.branches ALTER COLUMN company_id SET NOT NULL"))

    bind.execute(text(f"ALTER TABLE {sch}.branches DROP CONSTRAINT IF EXISTS branches_code_key"))
    bind.execute(text(f"ALTER TABLE {sch}.branches DROP CONSTRAINT IF EXISTS uq_branches_code"))
    bind.execute(text(f"DROP INDEX IF EXISTS {sch}.ix_branches_code"))

    bind.execute(
        text(
            f"""
            DO $$ BEGIN
              ALTER TABLE {sch}.branches ADD CONSTRAINT uq_branch_company_code UNIQUE (company_id, code);
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )
    bind.execute(
        text(
            f"""
            DO $$ BEGIN
              ALTER TABLE {sch}.branches ADD CONSTRAINT fk_branches_company_id
                FOREIGN KEY (company_id) REFERENCES {sch}.companies(id) ON DELETE RESTRICT;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )
    bind.execute(text(f"CREATE INDEX IF NOT EXISTS ix_branches_company_id ON {sch}.branches (company_id)"))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _upgrade_postgresql(bind)
        return

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=250), nullable=True),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default=sa.text("'ILS'"), nullable=False),
        sa.Column("fiscal_year_start_month", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_companies_code"),
    )
    op.create_index("ix_companies_name", "companies", ["name"], unique=False)
    op.create_index("ix_companies_is_active", "companies", ["is_active"], unique=False)
    op.create_index("ix_companies_tax_id", "companies", ["tax_id"], unique=False)

    op.add_column("branches", sa.Column("company_id", sa.Integer(), nullable=True))
    _backfill_companies(bind)
    _dedupe_branch_codes(bind)
    op.alter_column("branches", "company_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "fk_branches_company_id", "branches", "companies", ["company_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_branches_company_id", "branches", ["company_id"], unique=False)

    insp = inspect(bind)
    for uc in insp.get_unique_constraints("branches") or []:
        if uc.get("name") in ("branches_code_key", "uq_branches_code") or uc.get("column_names") == ["code"]:
            op.drop_constraint(uc["name"], "branches", type_="unique")
    op.create_unique_constraint("uq_branch_company_code", "branches", ["company_id", "code"])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sch = _tenant_schema()
        bind.execute(text(f"ALTER TABLE {sch}.branches DROP CONSTRAINT IF EXISTS uq_branch_company_code"))
        bind.execute(text(f"ALTER TABLE {sch}.branches DROP CONSTRAINT IF EXISTS fk_branches_company_id"))
        bind.execute(text(f"DROP INDEX IF EXISTS {sch}.ix_branches_company_id"))
        bind.execute(text(f"ALTER TABLE {sch}.branches DROP COLUMN IF EXISTS company_id"))
        bind.execute(text(f"DROP TABLE IF EXISTS {sch}.companies"))
        bind.execute(
            text(
                f"""
                DO $$ BEGIN
                  ALTER TABLE {sch}.branches ADD CONSTRAINT uq_branches_code UNIQUE (code);
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
                """
            )
        )
        return

    op.drop_constraint("uq_branch_company_code", "branches", type_="unique")
    op.create_unique_constraint("branches_code_key", "branches", ["code"])
    op.drop_constraint("fk_branches_company_id", "branches", type_="foreignkey")
    op.drop_index("ix_branches_company_id", table_name="branches")
    op.drop_column("branches", "company_id")
    op.drop_table("companies")
