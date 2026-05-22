"""
توجيه كل نوع مستخدم إلى لوحة الداشبورد المناسبة ضمن صلاحياته.
"""
from __future__ import annotations

from permissions_config.endpoint_access import permission_for_endpoint
from permissions_config.enums import SystemPermissions as SP
from permissions_config.role_policy import (
    PLATFORM_ROLE_HOME,
    TENANT_ROLE_HOME,
    normalize_role_name,
)

# ترتيب احتياطي حسب الصلاحية (بعد دور المستخدم)
_PERMISSION_HOME_CHAIN: tuple[tuple[str, str], ...] = (
    (SP.ACCESS_OWNER_DASHBOARD.value, "security.index"),
    (SP.ACCESS_TENANT_CONSOLE.value, "tenant_console.index"),
    (SP.ACCESS_DASHBOARD.value, "main.dashboard"),
    (SP.MANAGE_LEDGER.value, "ledger_control.index"),
    (SP.VALIDATE_ACCOUNTING.value, "accounting_validation.index"),
    (SP.MANAGE_SALES.value, "sales_bp.list_sales"),
    (SP.MANAGE_SERVICE.value, "service.list_requests"),
    (SP.MANAGE_CUSTOMERS.value, "customers_bp.list_customers"),
    (SP.MANAGE_PAYMENTS.value, "payments.index"),
    (SP.MANAGE_EXPENSES.value, "expenses_bp.list_expenses"),
    (SP.VIEW_WAREHOUSES.value, "warehouse_bp.list"),
    (SP.MANAGE_WAREHOUSES.value, "warehouse_bp.list"),
    (SP.MANAGE_VENDORS.value, "vendors_bp.suppliers_list"),
    (SP.VIEW_REPORTS.value, "financial_reports.index"),
    (SP.MANAGE_USERS.value, "users_bp.list_users"),
    (SP.VIEW_SHOP.value, "shop.catalog"),
)


def _role_name(user) -> str:
    return normalize_role_name(user)


def _user_has(user, code: str) -> bool:
    if not user or not code:
        return False
    try:
        if hasattr(user, "has_permission") and user.has_permission(code):
            return True
    except Exception:
        pass
    return False


def _endpoint_exists(endpoint: str) -> bool:
    try:
        from flask import current_app

        return endpoint in current_app.view_functions
    except Exception:
        return True


def user_can_access_endpoint(user, endpoint: str) -> bool:
    """هل يملك المستخدم صلاحية الوصول لهذا endpoint؟"""
    if not user or not endpoint:
        return False
    if not _endpoint_exists(endpoint):
        return False

    needed = permission_for_endpoint(endpoint)
    if needed:
        return _user_has(user, needed)

    if endpoint.startswith("shop."):
        return not hasattr(user, "has_permission")
    return hasattr(user, "has_permission")


def preferred_dashboard_endpoint(user, tenant_slug: str | None = None) -> str:
    """
    endpoint اللوحة الرئيسية للمستخدم — يُستخدم بعد الدخول وعند النقر على «الرئيسية».
    """
    if user is None:
        return "auth.login"

    slug = (tenant_slug or "").strip()

    if not hasattr(user, "has_permission"):
        return "shop.catalog"

    role = _role_name(user)
    role_table = TENANT_ROLE_HOME if slug else PLATFORM_ROLE_HOME
    if role and role in role_table:
        ep = role_table[role]
        if user_can_access_endpoint(user, ep):
            return ep

    for _perm, ep in _PERMISSION_HOME_CHAIN:
        if slug and ep == "security.index":
            continue
        if not slug and ep == "tenant_console.index":
            continue
        if _user_has(user, _perm) and user_can_access_endpoint(user, ep):
            return ep

    return "auth.login"


def home_url_for_user(user, tenant_slug: str | None = None) -> str:
    from flask import url_for

    ep = preferred_dashboard_endpoint(user, tenant_slug)
    try:
        return url_for(ep)
    except Exception:
        return url_for("auth.login")


def dashboard_label_for_user(user, tenant_slug: str | None = None) -> str:
    """عنوان عربي قصير للوحة الرئيسية."""
    ep = preferred_dashboard_endpoint(user, tenant_slug)
    labels = {
        "security.index": "لوحة مالك المنصة",
        "tenant_console.index": "لوحة مالك التينانت",
        "main.dashboard": "لوحة التشغيل",
        "ledger_control.index": "دفتر الأستاذ",
        "service.list_requests": "الصيانة",
        "sales_bp.list_sales": "المبيعات",
        "customers_bp.list_customers": "العملاء",
        "warehouse_bp.list": "المستودعات",
        "payments.index": "الدفعات",
        "financial_reports.index": "التقارير المالية",
        "shop.catalog": "المتجر",
    }
    return labels.get(ep, "الرئيسية")


def redirect_if_wrong_home(view_endpoint: str, user, tenant_slug: str | None = None) -> str | None:
    """
    إن كانت الصفحة الحالية ليست لوحة هذا المستخدم، أرجع endpoint التوجيه.
    """
    preferred = preferred_dashboard_endpoint(user, tenant_slug)
    if not preferred or preferred == view_endpoint:
        return None
    if view_endpoint == "main.dashboard" and preferred != "main.dashboard":
        return preferred
    return None


def dashboard_widgets_for_user(user) -> dict[str, bool]:
    """أعلام لعرض أقسام لوحة التشغيل — تُطابق القالب والخادم."""
    return {
        "sales": _user_has(user, SP.MANAGE_SALES.value) or _user_has(user, SP.VIEW_SALES.value),
        "customers": _user_has(user, SP.MANAGE_CUSTOMERS.value) or _user_has(user, SP.VIEW_CUSTOMERS.value),
        "service": _user_has(user, SP.MANAGE_SERVICE.value) or _user_has(user, SP.VIEW_SERVICE.value),
        "warehouses": _user_has(user, SP.MANAGE_WAREHOUSES.value) or _user_has(user, SP.VIEW_WAREHOUSES.value),
        "shipments": _user_has(user, SP.MANAGE_SHIPMENTS.value),
        "payments": _user_has(user, SP.MANAGE_PAYMENTS.value) or _user_has(user, SP.VIEW_PAYMENTS.value),
        "ledger": _user_has(user, SP.MANAGE_LEDGER.value) or _user_has(user, SP.VIEW_LEDGER.value),
        "expenses": _user_has(user, SP.MANAGE_EXPENSES.value) or _user_has(user, SP.VIEW_EXPENSES.value),
        "reports": _user_has(user, SP.VIEW_REPORTS.value) or _user_has(user, SP.MANAGE_REPORTS.value),
        "checks": _user_has(user, SP.MANAGE_PAYMENTS.value),
        "vendors": _user_has(user, SP.MANAGE_VENDORS.value),
    }
