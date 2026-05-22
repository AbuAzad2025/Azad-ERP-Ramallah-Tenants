"""
مصدر واحد: endpoint Flask → صلاحية مطلوبة (التوجيه، القوائم، بطاقات اللوحات).
"""
from __future__ import annotations

from permissions_config.enums import SystemPermissions as SP

# تشغيل تينانت + لوحات الدخول
TENANT_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "tenant_console.index": SP.ACCESS_TENANT_CONSOLE.value,
    "main.dashboard": SP.ACCESS_DASHBOARD.value,
    "sales_bp.list_sales": SP.MANAGE_SALES.value,
    "returns.list_returns": SP.MANAGE_SALES.value,
    "customers_bp.list_customers": SP.MANAGE_CUSTOMERS.value,
    "payments.index": SP.MANAGE_PAYMENTS.value,
    "vendors_bp.suppliers_list": SP.MANAGE_VENDORS.value,
    "expenses_bp.list_expenses": SP.MANAGE_EXPENSES.value,
    "branches_bp.list_branches": SP.MANAGE_BRANCHES.value,
    "warehouse_bp.list": SP.VIEW_WAREHOUSES.value,
    "shipments_bp.list_shipments": SP.MANAGE_SHIPMENTS.value,
    "service.list_requests": SP.MANAGE_SERVICE.value,
    "parts_bp.parts_list": SP.VIEW_PARTS.value,
    "checks.index": SP.MANAGE_PAYMENTS.value,
    "ledger_control.index": SP.MANAGE_LEDGER.value,
    "ledger.index": SP.MANAGE_LEDGER.value,
    "tenant_fiscal_bp.index": SP.MANAGE_LEDGER.value,
    "budgets.index": SP.MANAGE_LEDGER.value,
    "accounting_validation.index": SP.VALIDATE_ACCOUNTING.value,
    "accounting_docs.index": SP.MANAGE_ACCOUNTING_DOCS.value,
    "financial_reports.index": SP.VIEW_REPORTS.value,
    "reports_bp.index": SP.VIEW_REPORTS.value,
    "currencies.list": SP.MANAGE_CURRENCIES.value,
    "bank.accounts": SP.MANAGE_BANK.value,
    "cost_centers.index": SP.MANAGE_COST_CENTERS.value,
    "engineering.dashboard": SP.MANAGE_ENGINEERING.value,
    "projects.index": SP.MANAGE_PROJECTS.value,
    "workflows.index": SP.MANAGE_WORKFLOWS.value,
    "tenant_console.branding": SP.ACCESS_TENANT_CONSOLE.value,
    "tenant_console.business_settings": SP.ACCESS_TENANT_CONSOLE.value,
    "users_bp.list_users": SP.MANAGE_USERS.value,
    "users_bp.create_user": SP.MANAGE_USERS.value,
    "roles_bp.list_roles": SP.MANAGE_ROLES.value,
    "shop.catalog": SP.VIEW_SHOP.value,
    "notes.list_notes": SP.VIEW_NOTES.value,
}

# لوحة مالك المنصة (أزاد)
PLATFORM_OWNER_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "security.index": SP.ACCESS_OWNER_DASHBOARD.value,
    "security.settings_center": SP.ACCESS_OWNER_DASHBOARD.value,
    "advanced.owner_hub": SP.ACCESS_OWNER_DASHBOARD.value,
    "security.monitoring_dashboard": SP.MANAGE_SYSTEM_HEALTH.value,
    "security.owner_branding": SP.ACCESS_OWNER_DASHBOARD.value,
    "security.users_center": SP.MANAGE_USERS.value,
    "security.saas_manager": SP.MANAGE_SAAS.value,
    "security.audit_log_viewer": SP.VIEW_AUDIT_LOGS.value,
    "advanced.multi_tenant": SP.MANAGE_TENANTS.value,
}


def permission_for_endpoint(endpoint: str | None) -> str | None:
    ep = (endpoint or "").strip()
    if not ep:
        return None
    if ep in TENANT_ENDPOINT_PERMISSIONS:
        return TENANT_ENDPOINT_PERMISSIONS[ep]
    return PLATFORM_OWNER_ENDPOINT_PERMISSIONS.get(ep)


def all_mapped_endpoints() -> frozenset[str]:
    return frozenset(TENANT_ENDPOINT_PERMISSIONS) | frozenset(PLATFORM_OWNER_ENDPOINT_PERMISSIONS)


def audit_hub_endpoint_coverage(hub_sections: tuple) -> list[str]:
    """endpoints في owner_hubs بدون تعريف صلاحية."""
    missing = []
    for section in hub_sections or ():
        for card in section.get("cards", ()) or section.get("items", ()):
            ep = (card.get("endpoint") or "").strip()
            if ep and permission_for_endpoint(ep) is None:
                missing.append(ep)
    return missing
