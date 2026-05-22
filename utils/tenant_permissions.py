"""
صلاحيات التينانت — عزل عن لوحة مالك المنصة (أزاد).
"""
from __future__ import annotations

from permissions_config.enums import SystemPermissions as SP

# لا تُمنح لمالك الشركة داخل /t/<slug>/ — خاصة بمنصة أزاد فقط
PLATFORM_ONLY_PERMISSIONS = frozenset(
    {
        SP.ACCESS_OWNER_DASHBOARD.value,
        SP.MANAGE_ADVANCED_ACCOUNTING.value,
        SP.MANAGE_ANY_USER_PERMISSIONS.value,
        SP.MANAGE_TENANTS.value,
        SP.MANAGE_SAAS.value,
        SP.BACKUP_DATABASE.value,
        SP.RESTORE_DATABASE.value,
        SP.MANAGE_SYSTEM_CONFIG.value,
        SP.MANAGE_SYSTEM_HEALTH.value,
        SP.MANAGE_MOBILE_APP.value,
        SP.MANAGE_AI.value,
        SP.TRAIN_AI.value,
    }
)

# لوحة مالك الشركة (تينانت) — ليست access_owner_dashboard
TENANT_CONSOLE_PERMISSION = SP.ACCESS_TENANT_CONSOLE.value

# endpoint → صلاحية مطلوبة لعرض البطاقة في لوحة التينانت
HUB_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "main.dashboard": SP.ACCESS_DASHBOARD.value,
    "sales_bp.list_sales": SP.MANAGE_SALES.value,
    "customers_bp.list_customers": SP.MANAGE_CUSTOMERS.value,
    "payments.index": SP.MANAGE_PAYMENTS.value,
    "vendors_bp.suppliers_list": SP.MANAGE_VENDORS.value,
    "expenses_bp.list_expenses": SP.MANAGE_EXPENSES.value,
    "ledger_control.index": SP.MANAGE_LEDGER.value,
    "tenant_fiscal_bp.index": SP.MANAGE_LEDGER.value,
    "budgets.index": SP.MANAGE_LEDGER.value,
    "accounting_validation.index": SP.VALIDATE_ACCOUNTING.value,
    "financial_reports.index": SP.VIEW_REPORTS.value,
    "reports_bp.index": SP.VIEW_REPORTS.value,
    "tenant_console.branding": TENANT_CONSOLE_PERMISSION,
    "tenant_console.business_settings": TENANT_CONSOLE_PERMISSION,
    "users_bp.list_users": SP.MANAGE_USERS.value,
}


def is_tenant_request() -> bool:
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return False
        return bool(str(getattr(g, "tenant_slug", None) or "").strip())
    except Exception:
        return False


def is_platform_only_permission(code: str) -> bool:
    c = (code or "").strip().lower()
    if not c:
        return False
    if c in PLATFORM_ONLY_PERMISSIONS:
        return True
    try:
        from utils import _expand_perms

        expanded = {str(x).lower() for x in _expand_perms(c)}
        return bool(expanded & PLATFORM_ONLY_PERMISSIONS)
    except Exception:
        return False


def filter_permissions_for_tenant(perms: set[str]) -> set[str]:
    if not perms:
        return set()
    return {p for p in perms if p not in PLATFORM_ONLY_PERMISSIONS}


def tenant_owner_has_permission(user, code: str) -> bool:
    """دور owner/developer داخل التينانت: كل شيء ما عدا صلاحيات المنصة."""
    if is_platform_only_permission(code):
        return False
    return True


def user_has_effective_permission(user, code: str) -> bool:
    if not user or not code:
        return False
    if hasattr(user, "has_permission") and callable(user.has_permission):
        return bool(user.has_permission(code))
    return False


def user_can_access_hub_endpoint(user, endpoint: str) -> bool:
    needed = HUB_ENDPOINT_PERMISSIONS.get(endpoint)
    if not needed:
        return True
    return user_has_effective_permission(user, needed)


def filter_hub_sections(sections, user) -> tuple:
    out = []
    for section in sections:
        cards = tuple(
            c for c in section.get("cards", ())
            if user_can_access_hub_endpoint(user, c.get("endpoint", ""))
        )
        if cards:
            sec = dict(section)
            sec["cards"] = cards
            out.append(sec)
    return tuple(out)


def sync_tenant_owner_role_permissions(session) -> dict:
    """
    يزامن دور owner في schema الحالي: يزيل صلاحيات المنصة ويضيف access_tenant_console.
    """
    from sqlalchemy import delete, insert

    from models import Permission, Role, role_permissions

    allowed = set(permission_codes_for_tenant_owner())
    role = session.query(Role).filter_by(name="owner").one_or_none()
    if not role:
        return {"role": "owner", "skipped": True}
    perms = [p for p in Permission.query.all() if str(p.code or "").strip().lower() in allowed]
    session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
    if perms:
        session.execute(
            insert(role_permissions),
            [{"role_id": role.id, "permission_id": p.id} for p in perms],
        )
    session.expire(role, ["permissions"])
    session.flush()
    return {"role": "owner", "permissions": len(perms)}


def permission_codes_for_tenant_owner() -> list[str]:
    """أكواد تُزرع لدور owner في schema التينانت (بدون صلاحيات المنصة)."""
    from permissions_config.permissions import PermissionsRegistry

    codes = []
    for code in PermissionsRegistry.get_all_permission_codes():
        c = str(code or "").strip().lower()
        if c and c not in PLATFORM_ONLY_PERMISSIONS:
            codes.append(c)
    if TENANT_CONSOLE_PERMISSION not in codes:
        codes.append(TENANT_CONSOLE_PERMISSION)
    return sorted(set(codes))
