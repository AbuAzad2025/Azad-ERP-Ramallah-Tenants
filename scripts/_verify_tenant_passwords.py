"""Verify which default passwords work for tenant users (no secrets printed)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app import create_app
from extensions import db
from models import TenantRegistry, User

CANDIDATES = [
    "MANAGER123",
    "STAFF123",
    "MECH123",
    "CUST123",
    "OWNER123",
    "DEV123",
    "DevTenant2026!",
    "AZ123456",
    "ADMIN123",
    "manager",
    "Manager123",
    "123456",
    "password",
]


def check_user_in_schema(schema: str, username: str, passwords: list[str]) -> tuple[str | None, str]:
    q = text(
        f'SELECT id, username, email, password_hash, is_active, is_system_account '
        f'FROM "{schema}".users WHERE lower(username) = lower(:u) LIMIT 1'
    )
    row = db.session.execute(q, {"u": username}).fetchone()
    if not row:
        return None, "user_not_found"
    uid, uname, email, pw_hash, active, sys_acct = row
    if not pw_hash:
        return None, "no_password_hash"
    if not active:
        return None, "inactive"

    # Load via ORM in tenant schema context
    from utils.tenant_fiscal_schema import set_local_search_path

    set_local_search_path(db.session, schema)
    user = db.session.get(User, uid)
    if not user:
        db.session.rollback()
        return None, "orm_load_failed"

    for pwd in passwords:
        try:
            if user.check_password(pwd):
                return pwd, "ok"
        except Exception:
            pass
    return None, "no_match"


app = create_app()
with app.app_context():
    # public schema (legacy)
    print("\n=== public (platform/legacy) ===")
    for uname in ["manager", "owner", "azad", "admin", "staff"]:
        pwd, status = check_user_in_schema("public", uname, CANDIDATES)
        if status == "ok":
            print(f"  {uname}: OK -> {pwd!r}")
        else:
            print(f"  {uname}: {status}")

    tenants = TenantRegistry.query.filter_by(is_active=True).order_by(TenantRegistry.slug).all()
    usernames = ["owner", "manager", "staff", "mechanic", "customer", "developer", "Naser"]

    for t in tenants:
        print(f"\n=== {t.slug} ({t.schema_name}) ===")
        rows = db.session.execute(
            text(
                f'SELECT username, email, '
                f"CASE WHEN password_hash IS NULL OR password_hash = '' THEN 'EMPTY' ELSE 'SET' END "
                f'FROM "{t.schema_name}".users ORDER BY id'
            )
        ).fetchall()
        for r in rows:
            print(f"  [db] {r[0]!r} {r[1]!r} hash={r[2]}")
        for uname in usernames:
            pwd, status = check_user_in_schema(t.schema_name, uname, CANDIDATES)
            if status == "ok":
                print(f"  {uname}: OK -> {pwd!r}")
            else:
                print(f"  {uname}: {status}")
        db.session.execute(text("SET search_path TO public"))
