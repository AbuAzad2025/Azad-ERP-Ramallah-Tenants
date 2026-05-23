#!/usr/bin/env python3
"""تطبيق flask db upgrade على كل schema تينانت مسجّل.

الاستخدام (من جذر المشروع):
  python scripts/upgrade_all_tenant_schemas.py
  python scripts/upgrade_all_tenant_schemas.py --slug demo

يتطلب اتصال PostgreSQL ووجود جدول public.tenants.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade Alembic on tenant schemas")
    parser.add_argument("--slug", help="Upgrade single tenant slug only")
    parser.add_argument("--dry-run", action="store_true", help="List schemas only")
    args = parser.parse_args()

    from flask_migrate import upgrade

    from app import create_app
    from extensions import db
    from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path

    app = create_app()
    failures: list[str] = []
    upgraded = 0

    with app.app_context():
        targets = list(iter_tenant_schemas(db.session))
        if args.slug:
            targets = [(s, sch) for s, sch in targets if s == args.slug]
            if not targets:
                print(f"No tenant found for slug={args.slug!r}", file=sys.stderr)
                return 1

        if args.dry_run:
            for slug, schema in targets:
                print(f"would upgrade: {slug} -> {schema}")
            return 0

        for slug, schema in targets:
            print(f"Upgrading {slug} ({schema})...")
            try:
                os.environ["TENANT_SCHEMA"] = schema
                set_local_search_path(db.session, schema)
                db.session.commit()
                upgrade()
                db.session.commit()
                upgraded += 1
            except Exception as exc:
                db.session.rollback()
                msg = str(exc)
                if "uq_branch_company_code" in msg and "already exists" in msg.lower():
                    from sqlalchemy import text as sa_text

                    has_co = db.session.execute(
                        sa_text(
                            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema = :s AND table_name = 'companies')"
                        ),
                        {"s": schema},
                    ).scalar()
                    if has_co:
                        db.session.execute(
                            sa_text(f"UPDATE {schema}.alembic_version SET version_num = 'k1l2m3n4o5p6'")
                        )
                        db.session.commit()
                        print(f"  already migrated; stamped {schema}")
                        upgraded += 1
                        continue
                failures.append(f"{slug} ({schema}): {exc}")
                print(f"  FAILED: {exc}", file=sys.stderr)
            finally:
                os.environ.pop("TENANT_SCHEMA", None)

    print(f"Done. upgraded={upgraded} failed={len(failures)}")
    if failures:
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
