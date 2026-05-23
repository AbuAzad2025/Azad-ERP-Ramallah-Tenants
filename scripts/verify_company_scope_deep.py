#!/usr/bin/env python3
"""تحقق عميق: ترحيل الشركات، company_scope، واستيراد المسارات الحرجة."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def check_imports() -> None:
    print("== imports ==")
    try:
        from utils.company_scope import (  # noqa: F401
            assert_customer_access,
            assert_sale_access,
            filter_customers_query,
            filter_expenses_query,
            filter_partners_query,
            filter_payments_query,
            filter_sales_query,
            filter_suppliers_query,
            filter_warehouses_query,
            scoped_check_query,
            scoped_payment_query,
        )
        ok("company_scope exports")
    except Exception as exc:
        fail(f"company_scope import: {exc}")

    modules = [
        "routes.report_routes",
        "routes.financial_reports",
        "routes.ledger_control",
        "routes.main",
        "routes.sales",
        "routes.payments",
        "routes.companies",
        "routes.branches",
        "routes.partner_settlements",
        "routes.supplier_settlements",
        "routes.checks",
        "routes.balances_api",
        "routes.admin_reports",
    ]
    for mod in modules:
        try:
            __import__(mod)
            ok(mod)
        except Exception as exc:
            fail(f"{mod}: {exc}")


def check_tenant_db() -> None:
    print("== tenant schemas ==")
    from sqlalchemy import text

    from app import create_app
    from extensions import db
    from utils.tenant_fiscal_schema import iter_tenant_schemas

    app = create_app()
    with app.app_context():
        for slug, schema in iter_tenant_schemas(db.session):
            v = db.session.execute(text(f"SELECT version_num FROM {schema}.alembic_version")).scalar()
            has_co = db.session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = 'companies')"
                ),
                {"s": schema},
            ).scalar()
            has_cid = db.session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = 'branches' AND column_name = 'company_id')"
                ),
                {"s": schema},
            ).scalar()
            if v != "k1l2m3n4o5p6" or not has_co or not has_cid:
                fail(f"{slug} ({schema}) alembic={v} companies={has_co} branch.company_id={has_cid}")
            else:
                n_co = db.session.execute(text(f"SELECT COUNT(*) FROM {schema}.companies")).scalar()
                ok(f"{slug} companies={n_co}")


def check_scope_logic() -> None:
    print("== scope logic (smoke) ==")
    from app import create_app

    app = create_app()
    with app.app_context():
        from utils.company_scope import (
            filter_customers_query,
            filter_partners_query,
            filter_sales_query,
            filter_suppliers_query,
        )
        from models import Customer, Partner, Sale, Supplier

        for fn, model in (
            (filter_sales_query, Sale),
            (filter_customers_query, Customer),
            (filter_suppliers_query, Supplier),
            (filter_partners_query, Partner),
        ):
            try:
                q = fn(model.query)
                q.limit(1).all()
                ok(f"{fn.__name__} on {model.__name__}")
            except Exception as exc:
                fail(f"{fn.__name__}: {exc}")


def main() -> int:
    print("=== Deep company_scope verification ===\n")
    check_imports()
    print()
    check_tenant_db()
    print()
    check_scope_logic()
    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
