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

TENANT_CONSOLE_PERMISSION = SP.ACCESS_TENANT_CONSOLE.value

from permissions_config.endpoint_access import (  # noqa: E402 — بعد ثوابت SP
    PLATFORM_OWNER_ENDPOINT_PERMISSIONS,
    TENANT_ENDPOINT_PERMISSIONS,
    permission_for_endpoint,
)

# مرادفات للتوافق — المصدر: permissions_config/endpoint_access.py
HUB_ENDPOINT_PERMISSIONS = TENANT_ENDPOINT_PERMISSIONS
PLATFORM_HUB_ENDPOINT_PERMISSIONS = PLATFORM_OWNER_ENDPOINT_PERMISSIONS

TENANT_CONSOLE_NAV: tuple[dict, ...] = (
    {
        "title": "الرئيسية",
        "items": (
            {"endpoint": "tenant_console.index", "label": "لوحة المالك", "icon": "fa-home"},
            {"endpoint": "main.dashboard", "label": "لوحة التشغيل", "icon": "fa-tachometer-alt"},
        ),
    },
    {
        "title": "الهوية والإعدادات",
        "owner_only": True,
        "items": (
            {"endpoint": "tenant_console.branding", "label": "الهوية والترويسة", "icon": "fa-palette"},
            {"endpoint": "tenant_console.business_settings", "label": "إعدادات المحاسبة", "icon": "fa-sliders-h"},
        ),
    },
    {
        "title": "التشغيل",
        "items": (
            {"endpoint": "sales_bp.list_sales", "label": "المبيعات", "icon": "fa-shopping-cart"},
            {"endpoint": "returns.list_returns", "label": "المرتجعات", "icon": "fa-undo"},
            {"endpoint": "customers_bp.list_customers", "label": "العملاء", "icon": "fa-user-friends"},
            {"endpoint": "payments.index", "label": "الدفعات", "icon": "fa-money-bill-wave"},
            {"endpoint": "vendors_bp.suppliers_list", "label": "الموردون", "icon": "fa-truck"},
            {"endpoint": "expenses_bp.list_expenses", "label": "المصروفات", "icon": "fa-receipt"},
            {"endpoint": "service.list_requests", "label": "الصيانة", "icon": "fa-wrench"},
            {"endpoint": "shipments_bp.list_shipments", "label": "الشحنات", "icon": "fa-shipping-fast"},
            {"endpoint": "branches_bp.list_branches", "label": "الفروع والمواقع", "icon": "fa-code-branch"},
            {"endpoint": "warehouse_bp.list", "label": "المستودعات", "icon": "fa-warehouse"},
        ),
    },
    {
        "title": "المحاسبة",
        "items": (
            {"endpoint": "ledger_control.index", "label": "دفتر الأستاذ", "icon": "fa-book"},
            {"endpoint": "tenant_fiscal_bp.index", "label": "إقفال الفترات", "icon": "fa-calendar-check"},
            {"endpoint": "budgets.index", "label": "الموازنات", "icon": "fa-chart-pie"},
            {"endpoint": "accounting_validation.index", "label": "التحقق المحاسبي", "icon": "fa-check-double"},
            {"endpoint": "financial_reports.index", "label": "التقارير المالية", "icon": "fa-file-invoice-dollar"},
            {"endpoint": "currencies.list_currencies", "label": "العملات", "icon": "fa-coins"},
            {"endpoint": "checks.index", "label": "الشيكات", "icon": "fa-money-check"},
        ),
    },
    {
        "title": "التقارير",
        "items": (
            {"endpoint": "reports_bp.index", "label": "تقارير التشغيل", "icon": "fa-chart-line"},
            {"endpoint": "accounting_docs.index", "label": "التوثيق المحاسبي", "icon": "fa-book-open"},
        ),
    },
    {
        "title": "الفريق",
        "items": (
            {"endpoint": "users_bp.list_users", "label": "المستخدمون", "icon": "fa-users"},
            {"endpoint": "users_bp.create_user", "label": "إضافة مستخدم", "icon": "fa-user-plus"},
            {"endpoint": "roles_bp.list_roles", "label": "الأدوار", "icon": "fa-user-tag"},
        ),
    },
)


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
    if is_platform_only_permission(code):
        return False
    return True


def user_has_effective_permission(user, code: str) -> bool:
    if not user or not code:
        return False
    if hasattr(user, "has_permission") and callable(user.has_permission):
        return bool(user.has_permission(code))
    return False


def _tenant_owner_session() -> bool:
    try:
        from utils.branding_assets import is_tenant_session_user

        return is_tenant_session_user()
    except Exception:
        return False


def _user_can_access_endpoint(user, endpoint: str, perm_map: dict[str, str] | None = None) -> bool:
    needed = (perm_map or {}).get(endpoint) if perm_map is not None else permission_for_endpoint(endpoint)
    if not needed:
        return False
    return user_has_effective_permission(user, needed)


def user_can_access_hub_endpoint(user, endpoint: str) -> bool:
    return _user_can_access_endpoint(user, endpoint, HUB_ENDPOINT_PERMISSIONS)


def filter_platform_hub_sections(sections, user) -> tuple:
    return filter_hub_sections(sections, user, endpoint_map=PLATFORM_HUB_ENDPOINT_PERMISSIONS)


def build_tenant_console_nav(user) -> tuple:
    owner_session = _tenant_owner_session()
    out = []
    for group in TENANT_CONSOLE_NAV:
        if group.get("owner_only") and not owner_session:
            continue
        items = tuple(
            it
            for it in group.get("items", ())
            if user_can_access_hub_endpoint(user, it.get("endpoint", ""))
        )
        if items:
            sec = dict(group)
            sec["items"] = items
            out.append(sec)
    return tuple(out)


def filter_hub_sections(sections, user, *, endpoint_map: dict[str, str] | None = None) -> tuple:
    perm_map = endpoint_map or HUB_ENDPOINT_PERMISSIONS
    owner_session = _tenant_owner_session()
    out = []
    for section in sections:
        if section.get("owner_only") and not owner_session:
            continue
        cards = tuple(
            c
            for c in section.get("cards", ())
            if _user_can_access_endpoint(user, c.get("endpoint", ""), perm_map)
        )
        if cards:
            sec = dict(section)
            sec["cards"] = cards
            out.append(sec)
    return tuple(out)


def sync_tenant_owner_role_permissions(session) -> dict:
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
    from permissions_config.permissions import PermissionsRegistry

    codes = []
    for code in PermissionsRegistry.get_all_permission_codes():
        c = str(code or "").strip().lower()
        if c and c not in PLATFORM_ONLY_PERMISSIONS:
            codes.append(c)
    if TENANT_CONSOLE_PERMISSION not in codes:
        codes.append(TENANT_CONSOLE_PERMISSION)
    return sorted(set(codes))
