"""
توجيه المستخدم إلى اللوحة المناسبة حسب الصلاحيات والنطاق (منصة / تينانت).
"""
from __future__ import annotations

from permissions_config.enums import SystemPermissions as SP


def _user_has(user, code: str) -> bool:
    if not user or not code:
        return False
    try:
        if hasattr(user, "has_permission") and user.has_permission(code):
            return True
    except Exception:
        pass
    return False


def preferred_dashboard_endpoint(user, tenant_slug: str | None = None) -> str:
    """
    endpoint افتراضي بعد تسجيل الدخول.
    """
    slug = (tenant_slug or "").strip()
    if user is None:
        return "auth.login"

    # عميل المتجر
    if not hasattr(user, "has_permission"):
        return "shop.catalog"

    if slug:
        if _user_has(user, SP.ACCESS_DASHBOARD.value):
            return "main.dashboard"
        if _user_has(user, SP.ACCESS_TENANT_CONSOLE.value):
            return "tenant_console.index"
        if _user_has(user, SP.MANAGE_SALES.value):
            return "sales_bp.list_sales"
        if _user_has(user, SP.MANAGE_SERVICE.value):
            return "service.list_requests"
        return "tenant_console.index"

    if _user_has(user, SP.ACCESS_OWNER_DASHBOARD.value):
        return "security.index"
    if _user_has(user, SP.ACCESS_DASHBOARD.value):
        return "main.dashboard"
    if _user_has(user, SP.ACCESS_TENANT_CONSOLE.value):
        return "tenant_console.index"
    return "main.dashboard"


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
