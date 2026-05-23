#!/usr/bin/env python3
"""التحقق من جدول companies ونسخة alembic لكل تينانت."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from flask_migrate import upgrade

from app import create_app
from extensions import db
from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path


def main() -> int:
    slug_filter = sys.argv[1] if len(sys.argv) > 1 else None
    app = create_app()
    ok = True
    with app.app_context():
        for slug, schema in iter_tenant_schemas(db.session):
            if slug_filter and slug != slug_filter:
                continue
            os.environ["TENANT_SCHEMA"] = schema
            set_local_search_path(db.session, schema)
            db.session.commit()
            v = db.session.execute(text(f"SELECT version_num FROM {schema}.alembic_version")).scalar()
            exists = db.session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = 'companies')"
                ),
                {"s": schema},
            ).scalar()
            if not exists and v != "k1l2m3n4o5p6":
                print(f"upgrading {slug} ({schema}) from {v}...")
                try:
                    upgrade()
                except Exception as exc:
                    import traceback

                    print(f"  upgrade error: {exc}")
                    traceback.print_exc()
                db.session.commit()
                v = db.session.execute(text(f"SELECT version_num FROM {schema}.alembic_version")).scalar()
                exists = db.session.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = :s AND table_name = 'companies')"
                    ),
                    {"s": schema},
                ).scalar()
            n = 0
            if exists:
                n = db.session.execute(text(f"SELECT COUNT(*) FROM {schema}.companies")).scalar()
            status = "OK" if exists and v == "k1l2m3n4o5p6" else "FAIL"
            print(f"{status} {slug} schema={schema} alembic={v} companies={n}")
            if status != "OK":
                ok = False
            os.environ.pop("TENANT_SCHEMA", None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
