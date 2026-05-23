"""
إجراءات تحكم إدارية لمالك التينانت ومالك المنصة — قابلة للاستدعاء من الويب وCLI.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from extensions import db


def sync_entity_balances(
    *,
    entity: str = "all",
    limit: int | None = 200,
    dry_run: bool = False,
    include_archived: bool = False,
    batch_size: int = 200,
) -> dict[str, Any]:
    """مزامنة أرصدة الزبائن/الموردين/الشركاء مع الحاسبة."""
    from models import Customer, Partner, Supplier
    from utils.balance_calculator import build_customer_balance_view
    from utils.customer_balance_updater import update_customer_balance_components
    from utils.partner_balance_updater import (
        build_partner_balance_view,
        update_partner_balance_components,
    )
    from utils.supplier_balance_updater import (
        build_supplier_balance_view,
        update_supplier_balance_components,
    )

    entity = (entity or "all").lower()
    tolerance = Decimal("0.01")
    summary: dict[str, Any] = {"dry_run": dry_run, "groups": {}, "ok": True}

    groups = [
        ("customers", Customer, build_customer_balance_view, update_customer_balance_components),
        ("suppliers", Supplier, build_supplier_balance_view, update_supplier_balance_components),
        ("partners", Partner, build_partner_balance_view, update_partner_balance_components),
    ]

    def _should(label: str) -> bool:
        return entity in ("all", label)

    for label, model_cls, breakdown_fn, updater_fn in groups:
        if not _should(label):
            continue
        bucket = {"total": 0, "mismatches": 0, "fixed": 0, "errors": 0, "samples": []}
        query = model_cls.query
        if hasattr(model_cls, "is_archived") and not include_archived:
            query = query.filter(model_cls.is_archived == False)  # noqa: E712
        query = query.order_by(model_cls.id.asc())
        if limit:
            query = query.limit(limit)
        pending = 0
        for obj in query:
            bucket["total"] += 1
            try:
                breakdown = breakdown_fn(obj.id, db.session)
            except Exception as exc:
                bucket["errors"] += 1
                db.session.rollback()
                if len(bucket["samples"]) < 10:
                    bucket["samples"].append({"id": obj.id, "error": str(exc)[:120]})
                continue
            if not breakdown or not breakdown.get("success"):
                bucket["errors"] += 1
                continue
            expected = Decimal(str(breakdown.get("balance", {}).get("amount", 0)))
            stored = Decimal(str(getattr(obj, "current_balance", 0) or 0))
            diff = (expected - stored).copy_abs()
            if diff <= tolerance:
                continue
            bucket["mismatches"] += 1
            if len(bucket["samples"]) < 15:
                bucket["samples"].append(
                    {
                        "id": obj.id,
                        "expected": float(expected),
                        "stored": float(stored),
                        "diff": float(diff),
                    }
                )
            if dry_run:
                continue
            try:
                updater_fn(obj.id, db.session)
                pending += 1
                bucket["fixed"] += 1
                if pending >= batch_size:
                    db.session.commit()
                    pending = 0
            except Exception as exc:
                db.session.rollback()
                bucket["errors"] += 1
                if len(bucket["samples"]) < 10:
                    bucket["samples"].append({"id": obj.id, "fix_error": str(exc)[:120]})
        if pending and not dry_run:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                bucket["errors"] += 1
                summary["ok"] = False
        summary["groups"][label] = bucket
        if bucket["mismatches"] and dry_run:
            summary["ok"] = False
    return summary


def run_accounting_audit(
    *,
    limit: int = 100,
    fix: bool = False,
    fix_policy: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    from utils.accounting_audit import audit_entity_balances, format_audit_report_text

    report = audit_entity_balances(
        limit=int(limit or 0),
        include_archived=include_archived,
        fix=fix,
        fix_policy=fix_policy,
    )
    report["text"] = format_audit_report_text(report)
    report["ok"] = not any(
        report.get("summary", {}).get(k, 0)
        for k in ("customers_mismatch", "suppliers_mismatch", "partners_mismatch", "policy_issues")
    )
    return report


def run_fix_sale_obligations(*, dry_run: bool = False) -> dict[str, Any]:
    from sqlalchemy import text

    count_sql = text(
        """
        SELECT COUNT(*) FROM sales
        WHERE ABS(COALESCE(balance_due, 0) - COALESCE(total_amount, 0)) > 0.01
        """
    )
    n = int(db.session.execute(count_sql).scalar() or 0)
    if dry_run or n == 0:
        return {"dry_run": dry_run, "count": n, "fixed": 0, "ok": n == 0}
    db.session.execute(
        text(
            """
            UPDATE sales
            SET balance_due = COALESCE(total_amount, 0),
                updated_at = CURRENT_TIMESTAMP
            WHERE ABS(COALESCE(balance_due, 0) - COALESCE(total_amount, 0)) > 0.01
            """
        )
    )
    db.session.commit()
    return {"dry_run": False, "count": n, "fixed": n, "ok": True}


def run_fiscal_period_sync() -> dict[str, Any]:
    from utils.period_close_service import sync_fiscal_periods

    stats = sync_fiscal_periods()
    return {"ok": True, "created": stats.get("created", 0), "updated": stats.get("updated", 0)}


def run_integration_audit_report() -> dict[str, Any]:
    from flask import current_app
    from utils.integration_audit import run_integration_audit

    return run_integration_audit(current_app._get_current_object())


def sync_tenant_owner_permissions() -> dict[str, Any]:
    from utils.tenant_permissions import sync_tenant_owner_role_permissions

    return sync_tenant_owner_role_permissions(db.session)


def clear_rbac_caches() -> dict[str, Any]:
    from models import Role
    from utils import clear_role_permission_cache, clear_users_cache_by_role

    cleared = 0
    for r in Role.query.all():
        try:
            clear_role_permission_cache(r.id)
            clear_users_cache_by_role(r.id)
            cleared += 1
        except Exception:
            pass
    return {"ok": True, "roles_cleared": cleared}


def set_user_active(user_id: int, *, active: bool) -> dict[str, Any]:
    from models import User

    user = db.session.get(User, int(user_id))
    if not user:
        return {"ok": False, "error": "المستخدم غير موجود"}
    if getattr(user, "is_system_account", False):
        return {"ok": False, "error": "لا يمكن تعديل حساب النظام"}
    user.is_active = bool(active)
    db.session.commit()
    return {"ok": True, "user_id": user.id, "username": user.username, "is_active": user.is_active}


def list_tenant_users_for_control(limit: int = 50) -> list[dict[str, Any]]:
    from models import User
    from sqlalchemy.orm import joinedload

    rows = (
        User.query.options(joinedload(User.role))
        .order_by(User.id.asc())
        .limit(limit)
        .all()
    )
    out = []
    for u in rows:
        out.append(
            {
                "id": u.id,
                "username": u.username,
                "email": getattr(u, "email", None),
                "is_active": bool(u.is_active),
                "role": getattr(getattr(u, "role", None), "name", None),
            }
        )
    return out


# ——— منصة أزاد ———


def get_platform_tenants_control_rows() -> list[dict[str, Any]]:
    from models import SystemSettings, TenantRegistry

    rows = TenantRegistry.query.order_by(TenantRegistry.slug.asc()).all()
    out = []
    for r in rows:
        setting = SystemSettings.query.filter_by(key=f"tenant_{r.slug}_active").first()
        active = bool(r.is_active)
        if setting:
            active = str(setting.value).strip().lower() in ("true", "1", "yes")
        out.append(
            {
                "slug": r.slug,
                "display_name": r.display_name or r.slug,
                "schema_name": r.schema_name,
                "is_active": active,
                "path": f"/t/{r.slug}/",
            }
        )
    return out


def toggle_platform_tenant_active(slug: str) -> dict[str, Any]:
    from models import SystemSettings, TenantRegistry

    slug = (slug or "").strip().lower()
    if not slug or not slug.replace("_", "").replace("-", "").isalnum():
        return {"ok": False, "error": "معرّف تينانت غير صالح"}
    registry = TenantRegistry.query.filter_by(slug=slug).first()
    if not registry:
        return {"ok": False, "error": "التينانت غير موجود"}
    setting = SystemSettings.query.filter_by(key=f"tenant_{slug}_active").first()
    if not setting:
        setting = SystemSettings(key=f"tenant_{slug}_active", value="True", data_type="boolean")
        db.session.add(setting)
    new_val = "False" if str(setting.value).strip().lower() in ("true", "1", "yes") else "True"
    setting.value = new_val
    registry.is_active = new_val == "True"
    db.session.commit()
    try:
        from extensions import cache

        cache.delete("all_tenants_list")
        cache.delete("tenant_domains:v1")
    except Exception:
        pass
    return {"ok": True, "slug": slug, "is_active": registry.is_active}


def set_maintenance_mode(enabled: bool) -> dict[str, Any]:
    from models import SystemSettings

    SystemSettings.set_setting("maintenance_mode", bool(enabled), data_type="boolean")
    return {"ok": True, "maintenance_mode": bool(enabled)}


def get_maintenance_mode() -> bool:
    from models import SystemSettings

    try:
        return bool(SystemSettings.get_setting("maintenance_mode", False))
    except Exception:
        return False


def clear_application_cache() -> dict[str, Any]:
    from extensions import cache

    try:
        cache.clear()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_tenant_fiscal_tables() -> dict[str, Any]:
    from utils.tenant_fiscal_schema import ensure_fiscal_tables_for_request

    ensure_fiscal_tables_for_request()
    return {"ok": True, "message": "تم التحقق من جداول إقفال الفترات في schema التينانت"}
