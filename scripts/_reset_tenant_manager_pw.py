"""Reset manager password in tenant schemas and verify."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app import create_app
from extensions import db
from models import TenantRegistry, User
from utils.tenant_fiscal_schema import set_local_search_path

NEW_PASSWORD = "MANAGER123"


def reset_manager(schema: str) -> bool:
    row = db.session.execute(
        text(f'SELECT id FROM "{schema}".users WHERE lower(username) = \'manager\' LIMIT 1')
    ).fetchone()
    if not row:
        print(f"  {schema}: manager not found")
        return False
    set_local_search_path(db.session, schema)
    user = db.session.get(User, row[0])
    if not user:
        print(f"  {schema}: ORM load failed")
        db.session.rollback()
        return False
    user.set_password(NEW_PASSWORD)
    db.session.commit()
    ok = user.check_password(NEW_PASSWORD)
    print(f"  {schema}: manager password reset, verify={ok}")
    db.session.execute(text("SET search_path TO public"))
    return ok


app = create_app()
with app.app_context():
    for t in TenantRegistry.query.filter_by(is_active=True).all():
        print(t.slug)
        reset_manager(t.schema_name)
