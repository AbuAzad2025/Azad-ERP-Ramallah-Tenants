#!/usr/bin/env python3
"""تطبيق ترحيل الشركات/الفروع مباشرة على schema التينانت (عند فشل alembic العادي)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app import create_app
from extensions import db
from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path


def _apply_j0(conn, schema: str) -> None:
    conn.execute(text(f"ALTER TABLE {schema}.audit_logs ALTER COLUMN action TYPE VARCHAR(64)"))


def _apply_k1(conn, schema: str) -> None:
    os.environ["TENANT_SCHEMA"] = schema
    from migrations.versions.k1l2m3n4o5p6_add_companies_and_branch_company_id import _upgrade_postgresql

    _upgrade_postgresql(conn)


def main() -> int:
    slug_filter = sys.argv[1] if len(sys.argv) > 1 else None
    app = create_app()
    ok = True
    with app.app_context():
        for slug, schema in iter_tenant_schemas(db.session):
            if slug_filter and slug != slug_filter:
                continue
            exists = db.session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = 'companies')"
                ),
                {"s": schema},
            ).scalar()
            if exists:
                print(f"skip {slug} ({schema}): companies already present")
                continue
            print(f"applying {slug} ({schema})...")
            try:
                with db.engine.begin() as conn:
                    set_local_search_path(conn, schema)
                    v = conn.execute(text(f"SELECT version_num FROM {schema}.alembic_version")).scalar()
                    if v == "i9j0k1l2m3n4":
                        _apply_j0(conn, schema)
                    _apply_k1(conn, schema)
                    conn.execute(
                        text(f"UPDATE {schema}.alembic_version SET version_num = 'k1l2m3n4o5p6'")
                    )
                n = db.session.execute(text(f"SELECT COUNT(*) FROM {schema}.companies")).scalar()
                print(f"  OK companies={n}")
            except Exception as exc:
                ok = False
                print(f"  FAIL: {exc}", file=sys.stderr)
            finally:
                os.environ.pop("TENANT_SCHEMA", None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
