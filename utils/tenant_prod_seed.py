"""
إعداد تينانتات تطوير/إنتاج محلي — يعمل على قاعدة garage_manager فقط (لا يلمس قواعد أخرى).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text as sa_text
from sqlalchemy.engine.url import make_url

# قواعد مسموحة فقط — تجنب التعارض مع مساعد/مشاريع أخرى على نفس PostgreSQL
ALLOWED_DATABASES = frozenset({"garage_manager"})

SKIP_TABLES = frozenset({
    "tenants",
    "alembic_version",
    "saas_plans",
    "saas_subscriptions",
    "saas_invoices",
})

# ترتيب تقريبي للجداول المرجعية أولاً (باقي الجداول تُنسخ بعدها)
TABLE_PRIORITY = (
    "permissions",
    "roles",
    "role_permissions",
    "users",
    "branches",
    "warehouses",
    "cost_centers",
    "product_categories",
    "products",
    "customers",
    "suppliers",
    "partners",
    "employees",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def assert_garage_manager_only(db_uri: str | None = None) -> str:
    uri = (db_uri or os.environ.get("DATABASE_URL") or "").strip()
    if not uri:
        raise RuntimeError("DATABASE_URL غير معرّف")
    u = make_url(uri)
    dbname = (u.database or "").strip().lower()
    if dbname not in ALLOWED_DATABASES:
        raise RuntimeError(
            f"رفض التنفيذ: القاعدة '{dbname}' غير مسموحة. "
            f"المسموح فقط: {', '.join(sorted(ALLOWED_DATABASES))}"
        )
    return dbname


def _schema_exists(session, schema: str) -> bool:
    return bool(
        session.execute(
            sa_text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": schema},
        ).scalar()
    )


def _list_public_tables(session) -> list[str]:
    rows = session.execute(
        sa_text(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT LIKE 'pg_%'
            ORDER BY tablename
            """
        )
    ).fetchall()
    names = [str(r[0]) for r in rows if r and r[0]]
    priority = {n: i for i, n in enumerate(TABLE_PRIORITY)}
    names.sort(key=lambda n: (priority.get(n, 999), n))
    return [n for n in names if n not in SKIP_TABLES]


def ensure_tenant_registry_row(session, *, slug: str, schema_name: str, display_name: str, domain: str | None = None):
    from models import TenantRegistry

    slug = (slug or "").strip().lower()
    schema_name = (schema_name or "").strip()
    row = TenantRegistry.query.filter_by(slug=slug).first()
    if not row:
        row = TenantRegistry(slug=slug)
        session.add(row)
    row.schema_name = schema_name
    row.display_name = (display_name or slug).strip()
    row.domain = (domain or None)
    row.is_active = True
    row.updated_at = _utc_now()
    session.flush()
    return row


def _stamp_tenant_alembic_head(session, schema_name: str) -> None:
    head = session.execute(sa_text("SELECT version_num FROM public.alembic_version")).scalar()
    head = (head or "").strip()
    if not head:
        return
    session.execute(
        sa_text(
            f"CREATE TABLE IF NOT EXISTS {schema_name}.alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
    )
    session.execute(sa_text(f"DELETE FROM {schema_name}.alembic_version"))
    session.execute(
        sa_text(f"INSERT INTO {schema_name}.alembic_version (version_num) VALUES (:v)"),
        {"v": head},
    )


def clone_public_tables_to_schema(session, target_schema: str, *, truncate_first: bool = True) -> dict:
    """
    نسخ بيانات public إلى schema التينانت (نفس قاعدة garage_manager).
    لا يُستخدم pg_terminate على مستوى الكلاستر — فقط جلسة العمل الحالية.
    """
    target_schema = (target_schema or "").strip()
    if not target_schema or target_schema.lower() == "public":
        raise ValueError("target_schema غير صالح")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target_schema) or len(target_schema) > 63:
        raise ValueError("target_schema غير صالح")

    session.execute(sa_text(f"CREATE SCHEMA IF NOT EXISTS {target_schema}"))
    session.commit()

    tables = _list_public_tables(session)
    stats = {"tables": 0, "rows": 0, "skipped": []}

    session.execute(sa_text("SET session_replication_role = replica"))
    try:
        for table in tables:
            try:
                exists_dst = session.execute(
                    sa_text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = :s AND table_name = :t
                        """
                    ),
                    {"s": target_schema, "t": table},
                ).scalar()
                if not exists_dst:
                    session.execute(
                        sa_text(
                            f"CREATE TABLE {target_schema}.{table} "
                            f"(LIKE public.{table} INCLUDING ALL)"
                        )
                    )
                if truncate_first:
                    session.execute(sa_text(f"TRUNCATE TABLE {target_schema}.{table} CASCADE"))
                cnt = session.execute(
                    sa_text(f"INSERT INTO {target_schema}.{table} SELECT * FROM public.{table}")
                ).rowcount
                session.commit()
                stats["tables"] += 1
                stats["rows"] += int(cnt or 0)
                try:
                    session.execute(
                        sa_text(
                            f"""
                            SELECT setval(
                                pg_get_serial_sequence('{target_schema}.{table}', 'id'),
                                COALESCE((SELECT MAX(id) FROM {target_schema}.{table}), 1)
                            )
                            """
                        )
                    )
                    session.commit()
                except Exception:
                    session.rollback()
            except Exception as exc:
                session.rollback()
                stats["skipped"].append({"table": table, "error": str(exc)[:200]})
    finally:
        try:
            session.execute(sa_text("SET session_replication_role = DEFAULT"))
            session.commit()
        except Exception:
            session.rollback()

    return stats


def seed_saas_platform_defaults(session) -> None:
    from models import SaaSPlan

    if SaaSPlan.query.count() > 0:
        return
    plans = [
        SaaSPlan(
            name="أساسي",
            description="للمحلات الصغيرة",
            price_monthly=49,
            price_yearly=490,
            currency="ILS",
            max_users=3,
            max_invoices=500,
            storage_gb=5,
            is_active=True,
            sort_order=1,
        ),
        SaaSPlan(
            name="احترافي",
            description="لورش ومحلات متوسطة",
            price_monthly=99,
            price_yearly=990,
            currency="ILS",
            max_users=10,
            max_invoices=5000,
            storage_gb=20,
            is_active=True,
            is_popular=True,
            sort_order=2,
        ),
        SaaSPlan(
            name="مؤسسات",
            description="فروع متعددة وتينانت",
            price_monthly=199,
            price_yearly=1990,
            currency="ILS",
            max_users=50,
            storage_gb=100,
            is_active=True,
            sort_order=3,
        ),
    ]
    for p in plans:
        session.add(p)
    session.flush()


def _tenant_schema_from_slug(slug: str) -> str:
    base = (slug or "").strip().lower().replace("-", "_")
    base = "".join(ch for ch in base if (ch.isalnum() or ch == "_"))
    if not base:
        raise ValueError("slug غير صالح")
    if base[0].isdigit():
        base = f"t{base}"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    name = f"t_{base}" if not base.startswith("t_") else base
    if len(name) > 63 or any(ch not in allowed for ch in name):
        raise ValueError("schema غير صالح")
    return name


def _seed_tenant_owner(session, *, owner_username: str, owner_email: str, owner_password: str) -> None:
    from sqlalchemy import func
    from models import Permission, Role, User

    from permissions_config.permissions import PermissionsRegistry

    from utils.tenant_permissions import permission_codes_for_tenant_owner

    all_codes = permission_codes_for_tenant_owner()
    existing = {str(p.code or "").strip().lower(): p for p in Permission.query.all()}
    for code in sorted(all_codes):
        c = str(code or "").strip().lower()
        if not c or c in existing:
            continue
        session.add(Permission(code=c, name=c))
    session.flush()

    perms = [p for p in Permission.query.all() if getattr(p, "id", None)]
    role = Role.query.filter_by(name="owner").one_or_none()
    if not role:
        role = Role(name="owner")
        session.add(role)
        session.flush()
    role.permissions = perms

    email_norm = (owner_email or "").strip().lower()
    uname = (owner_username or "owner").strip() or "owner"
    user = User.query.filter((User.username == uname) | (func.lower(User.email) == email_norm)).one_or_none()
    if not user:
        user = User(username=uname, email=email_norm)
        session.add(user)
        session.flush()
    user.username = uname
    user.email = email_norm
    user.role = role
    user.set_password(owner_password)
    user.is_active = True
    session.flush()


def setup_production_dev_tenants(
    *,
    owner_email: str,
    owner_password: str,
    provision_schemas: Iterable[str] | None = None,
    copy_data: bool = True,
) -> dict:
    """
    إعداد كامل:
    - ramallah على public (البيانات الحقيقية المستعادة)
    - nasrallah / alhazem على schemas منفصلة مع نسخ من public
    """
    from extensions import db

    assert_garage_manager_only(db.engine.url.render_as_string(hide_password=False))

    report: dict = {"tenants": [], "errors": []}
    owner_email = (owner_email or "").strip()
    owner_password = (owner_password or "").strip()
    if not owner_email or not owner_password:
        raise ValueError("owner_email و owner_password مطلوبان")

    seed_saas_platform_defaults(db.session)
    db.session.commit()

    # التينانت الرئيسي — البيانات الحالية في public
    ensure_tenant_registry_row(
        db.session,
        slug="ramallah",
        schema_name="public",
        display_name="رم الله — المنصة الرئيسية",
        domain="localhost",
    )
    db.session.commit()
    report["tenants"].append({"slug": "ramallah", "schema": "public", "mode": "legacy"})

    extra = list(provision_schemas or ("nasrallah", "alhazem"))
    head = db.session.execute(sa_text("SELECT version_num FROM public.alembic_version")).scalar()
    head = (head or "").strip()

    for slug in extra:
        slug = (slug or "").strip().lower()
        if not slug or slug == "ramallah":
            continue
        schema_name = _tenant_schema_from_slug(slug)
        try:
            db.session.execute(sa_text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
            db.session.commit()
            db.session.execute(sa_text(f"DROP TABLE IF EXISTS {schema_name}.tenants CASCADE"))
            db.session.commit()

            ensure_tenant_registry_row(
                db.session,
                slug=slug,
                schema_name=schema_name,
                display_name=slug.replace("_", " ").title(),
            )
            db.session.commit()

            stats = (
                clone_public_tables_to_schema(db.session, schema_name)
                if copy_data
                else {"tables": 0, "rows": 0, "skipped": []}
            )
            from utils.tenant_fiscal_schema import ensure_fiscal_tables_in_schema

            ensure_fiscal_tables_in_schema(db.session, schema_name)
            _stamp_tenant_alembic_head(db.session, schema_name)
            db.session.commit()

            db.session.execute(sa_text(f"SET search_path TO {schema_name}, public"))
            _seed_tenant_owner(
                db.session,
                owner_username="owner",
                owner_email=owner_email,
                owner_password=owner_password,
            )
            db.session.execute(sa_text("SET search_path TO public"))
            db.session.commit()

            report["tenants"].append(
                {"slug": slug, "schema": schema_name, "mode": "isolated", "copy": stats}
            )
        except Exception as exc:
            db.session.rollback()
            report["errors"].append({"slug": slug, "error": str(exc)})

    return report
