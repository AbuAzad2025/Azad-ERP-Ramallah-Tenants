"""
مصدر واحد: endpoint Flask → صلاحية مطلوبة (التوجيه، القوائم، بطاقات اللوحات).
"""
from __future__ import annotations

from permissions_config.enums import SystemPermissions as SP

# تشغيل تينانت + لوحات الدخول (الصلاحية الأساسية للعرض في القوائم)
TENANT_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "tenant_console.index": SP.ACCESS_TENANT_CONSOLE.value,
    "tenant_console.control": SP.ACCESS_TENANT_CONSOLE.value,
    "main.dashboard": SP.ACCESS_DASHBOARD.value,
    "sales_bp.list_sales": SP.VIEW_SALES.value,
    "returns.list_returns": SP.VIEW_SALES.value,
    "customers_bp.list_customers": SP.VIEW_CUSTOMERS.value,
    "payments.index": SP.VIEW_PAYMENTS.value,
    "vendors_bp.suppliers_list": SP.MANAGE_VENDORS.value,
    "expenses_bp.list_expenses": SP.MANAGE_EXPENSES.value,
    "branches_bp.list_branches": SP.MANAGE_BRANCHES.value,
    "companies_bp.index": SP.MANAGE_BRANCHES.value,
    "companies_bp.add": SP.MANAGE_BRANCHES.value,
    "companies_bp.edit": SP.MANAGE_BRANCHES.value,
    "warehouse_bp.list": SP.VIEW_WAREHOUSES.value,
    "shipments_bp.list_shipments": SP.MANAGE_SHIPMENTS.value,
    "service.list_requests": SP.VIEW_SERVICE.value,
    "parts_bp.parts_list": SP.VIEW_PARTS.value,
    "checks.index": SP.VIEW_PAYMENTS.value,
    "ledger_control.index": SP.VIEW_LEDGER.value,
    "ledger.index": SP.VIEW_LEDGER.value,
    "tenant_fiscal_bp.index": SP.MANAGE_LEDGER.value,
    "budgets.index": SP.MANAGE_LEDGER.value,
    "accounting_validation.index": SP.VALIDATE_ACCOUNTING.value,
    "accounting_docs.index": SP.MANAGE_ACCOUNTING_DOCS.value,
    "financial_reports.index": SP.VIEW_REPORTS.value,
    "reports_bp.index": SP.VIEW_REPORTS.value,
    "currencies.list": SP.MANAGE_CURRENCIES.value,
    "bank.accounts": SP.VIEW_BANK.value,
    "cost_centers.index": SP.MANAGE_COST_CENTERS.value,
    "engineering.dashboard": SP.MANAGE_ENGINEERING.value,
    "projects.index": SP.VIEW_PROJECTS.value,
    "workflows.index": SP.VIEW_WORKFLOWS.value,
    "tenant_console.branding": SP.ACCESS_TENANT_CONSOLE.value,
    "tenant_console.business_settings": SP.ACCESS_TENANT_CONSOLE.value,
    "tenant_console.activity": SP.ACCESS_TENANT_CONSOLE.value,
    "users_bp.list_users": SP.MANAGE_USERS.value,
    "users_bp.create_user": SP.MANAGE_USERS.value,
    "roles.list_roles": SP.MANAGE_ROLES.value,
    "shop.catalog": SP.VIEW_SHOP.value,
    "notes.list_notes": SP.VIEW_NOTES.value,
    "sales_bp.sale_detail": SP.VIEW_SALES.value,
    "customers_bp.customer_detail": SP.VIEW_CUSTOMERS.value,
    "service.view_request": SP.VIEW_SERVICE.value,
    "checks.detail": SP.VIEW_PAYMENTS.value,
    "payments.view_payment": SP.VIEW_PAYMENTS.value,
    "warehouse_bp.detail": SP.VIEW_WAREHOUSES.value,
    "returns.view_return": SP.VIEW_SALES.value,
}

# أي صلاحية من المجموعة تكفي لعرض الرابط في الواجهة (قراءة أو إدارة)
ENDPOINT_PERMISSION_ANY: dict[str, tuple[str, ...]] = {
    "sales_bp.list_sales": (SP.VIEW_SALES.value, SP.MANAGE_SALES.value),
    "returns.list_returns": (SP.VIEW_SALES.value, SP.MANAGE_SALES.value),
    "customers_bp.list_customers": (SP.VIEW_CUSTOMERS.value, SP.MANAGE_CUSTOMERS.value),
    "payments.index": (SP.VIEW_PAYMENTS.value, SP.MANAGE_PAYMENTS.value),
    "service.list_requests": (SP.VIEW_SERVICE.value, SP.MANAGE_SERVICE.value),
    "warehouse_bp.list": (SP.VIEW_WAREHOUSES.value, SP.MANAGE_WAREHOUSES.value),
    "warehouse_bp.preorders_list": (SP.VIEW_WAREHOUSES.value, SP.MANAGE_WAREHOUSES.value),
    "parts_bp.parts_list": (SP.VIEW_PARTS.value, SP.MANAGE_INVENTORY.value),
    "checks.index": (SP.VIEW_PAYMENTS.value, SP.MANAGE_PAYMENTS.value),
    "notes.list_notes": (SP.VIEW_NOTES.value, SP.MANAGE_NOTES.value),
    "reports_bp.universal": (SP.VIEW_REPORTS.value, SP.MANAGE_REPORTS.value),
    "reports_bp.index": (SP.VIEW_REPORTS.value, SP.MANAGE_REPORTS.value),
    "financial_reports.index": (SP.VIEW_REPORTS.value, SP.MANAGE_REPORTS.value),
    "shop.catalog": (SP.VIEW_SHOP.value, SP.MANAGE_SHOP.value),
    "shop.admin_products": (SP.MANAGE_SHOP.value,),
    "shop.admin_preorders": (SP.MANAGE_SHOP.value,),
    "recurring.index": (SP.ACCESS_OWNER_DASHBOARD.value,),
    "ledger_control.index": (SP.VIEW_LEDGER.value, SP.MANAGE_LEDGER.value),
    "ledger.index": (SP.VIEW_LEDGER.value, SP.MANAGE_LEDGER.value),
    "tenant_fiscal_bp.index": (SP.MANAGE_LEDGER.value,),
    "budgets.index": (SP.VIEW_LEDGER.value, SP.MANAGE_LEDGER.value),
    "projects.index": (SP.VIEW_PROJECTS.value, SP.MANAGE_PROJECTS.value),
    "workflows.index": (SP.VIEW_WORKFLOWS.value, SP.MANAGE_WORKFLOWS.value),
    "workflows.definitions": (SP.VIEW_WORKFLOWS.value, SP.MANAGE_WORKFLOWS.value),
    "workflows.instances": (SP.VIEW_WORKFLOWS.value, SP.MANAGE_WORKFLOWS.value),
    "workflows.my_pending": (SP.VIEW_WORKFLOWS.value, SP.MANAGE_WORKFLOWS.value),
    "bank.accounts": (SP.VIEW_BANK.value, SP.MANAGE_BANK.value),
    "engineering.dashboard": (SP.MANAGE_ENGINEERING.value,),
    "engineering.teams": (SP.MANAGE_ENGINEERING.value,),
    "cost_centers.index": (SP.MANAGE_COST_CENTERS.value,),
    "barcode_scanner.index": (SP.VIEW_BARCODE.value, SP.MANAGE_BARCODE.value),
    "users_bp.list_users": (SP.MANAGE_USERS.value,),
    "roles.list_roles": (SP.MANAGE_ROLES.value,),
    "branches_bp.list_branches": (SP.MANAGE_BRANCHES.value,),
    "currencies.list": (SP.MANAGE_CURRENCIES.value,),
    "vendors_bp.suppliers_list": (SP.MANAGE_VENDORS.value,),
    "vendors_bp.partners_list": (SP.MANAGE_VENDORS.value,),
    "expenses_bp.list_expenses": (SP.MANAGE_EXPENSES.value,),
    "shipments_bp.list_shipments": (SP.MANAGE_SHIPMENTS.value,),
    "sales_bp.sale_detail": (SP.VIEW_SALES.value, SP.MANAGE_SALES.value),
    "customers_bp.customer_detail": (SP.VIEW_CUSTOMERS.value, SP.MANAGE_CUSTOMERS.value),
    "service.view_request": (SP.VIEW_SERVICE.value, SP.MANAGE_SERVICE.value),
    "checks.detail": (SP.VIEW_PAYMENTS.value, SP.MANAGE_PAYMENTS.value),
    "payments.view_payment": (SP.VIEW_PAYMENTS.value, SP.MANAGE_PAYMENTS.value),
    "warehouse_bp.detail": (SP.VIEW_WAREHOUSES.value, SP.MANAGE_WAREHOUSES.value),
}

# لوحة مالك المنصة (أزاد)
_PLATFORM_DEFAULT = SP.ACCESS_OWNER_DASHBOARD.value
PLATFORM_OWNER_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "security.index": _PLATFORM_DEFAULT,
    "security.control_center": _PLATFORM_DEFAULT,
    "security.settings_center": _PLATFORM_DEFAULT,
    "security.owner_branding": _PLATFORM_DEFAULT,
    "security.tools_center": _PLATFORM_DEFAULT,
    "security.reports_center": _PLATFORM_DEFAULT,
    "security.help_page": _PLATFORM_DEFAULT,
    "security.sitemap": _PLATFORM_DEFAULT,
    "security.live_monitoring": _PLATFORM_DEFAULT,
    "security.performance_monitor": SP.MANAGE_SYSTEM_HEALTH.value,
    "security.data_quality_center": _PLATFORM_DEFAULT,
    "security.security_center": _PLATFORM_DEFAULT,
    "security.grafana_setup": _PLATFORM_DEFAULT,
    "security.audit_log_detail": SP.VIEW_AUDIT_LOGS.value,
    "security.user_control": SP.MANAGE_USERS.value,
    "security.permissions_manager": SP.MANAGE_PERMISSIONS.value,
    "permissions.list": SP.MANAGE_PERMISSIONS.value,
    "permissions.create": SP.MANAGE_PERMISSIONS.value,
    "roles.list_roles": SP.MANAGE_ROLES.value,
    "roles.create_role": SP.MANAGE_ROLES.value,
    "security.system_settings": SP.MANAGE_SYSTEM_CONFIG.value,
    "security.theme_editor": _PLATFORM_DEFAULT,
    "security.integrations": _PLATFORM_DEFAULT,
    "security.notifications_log": _PLATFORM_DEFAULT,
    "security.tax_reports": _PLATFORM_DEFAULT,
    "security.database_manager": SP.BACKUP_DATABASE.value,
    "security.data_export": _PLATFORM_DEFAULT,
    "security.advanced_analytics": _PLATFORM_DEFAULT,
    "security.dark_mode_settings": _PLATFORM_DEFAULT,
    "security.emergency_tools": _PLATFORM_DEFAULT,
    "security.system_cleanup": _PLATFORM_DEFAULT,
    "security.block_ip": _PLATFORM_DEFAULT,
    "security.blocked_ips": _PLATFORM_DEFAULT,
    "security.block_country": _PLATFORM_DEFAULT,
    "security.blocked_countries": _PLATFORM_DEFAULT,
    "security.ultimate_control": _PLATFORM_DEFAULT,
    "advanced.owner_hub": SP.MANAGE_TENANTS.value,
    "advanced.multi_tenant": SP.MANAGE_TENANTS.value,
    "advanced.accounting_control": SP.MANAGE_ADVANCED_ACCOUNTING.value,
    "security.monitoring_dashboard": SP.MANAGE_SYSTEM_HEALTH.value,
    "security.users_center": SP.MANAGE_USERS.value,
    "security.saas_manager": SP.MANAGE_SAAS.value,
    "security.audit_log_viewer": SP.VIEW_AUDIT_LOGS.value,
    "fiscal_periods_bp.index": SP.MANAGE_LEDGER.value,
}

ENDPOINT_PERMISSION_ANY.update({
    "security.users_center": (SP.MANAGE_USERS.value, _PLATFORM_DEFAULT),
    "security.user_control": (SP.MANAGE_USERS.value, _PLATFORM_DEFAULT),
    "security.permissions_manager": (SP.MANAGE_PERMISSIONS.value, _PLATFORM_DEFAULT),
    "permissions.list": (SP.MANAGE_PERMISSIONS.value, _PLATFORM_DEFAULT),
    "roles.list_roles": (SP.MANAGE_ROLES.value, _PLATFORM_DEFAULT),
    "security.saas_manager": (SP.MANAGE_SAAS.value, _PLATFORM_DEFAULT),
    "security.audit_log_viewer": (SP.VIEW_AUDIT_LOGS.value, _PLATFORM_DEFAULT),
    "security.monitoring_dashboard": (SP.MANAGE_SYSTEM_HEALTH.value, _PLATFORM_DEFAULT),
    "advanced.owner_hub": (SP.MANAGE_TENANTS.value, _PLATFORM_DEFAULT),
    "security.database_manager": (SP.BACKUP_DATABASE.value, _PLATFORM_DEFAULT),
    "ledger_control.index": (SP.VIEW_LEDGER.value, SP.MANAGE_LEDGER.value),
    "fiscal_periods_bp.index": (SP.MANAGE_LEDGER.value, SP.VIEW_LEDGER.value),
})


def permission_for_endpoint(endpoint: str | None) -> str | None:
    ep = (endpoint or "").strip()
    if not ep:
        return None
    if ep in TENANT_ENDPOINT_PERMISSIONS:
        return TENANT_ENDPOINT_PERMISSIONS[ep]
    return PLATFORM_OWNER_ENDPOINT_PERMISSIONS.get(ep)


def permissions_for_endpoint(endpoint: str | None) -> tuple[str, ...]:
    """صلاحيات مقبولة للوصول (أيّها يكفي)."""
    ep = (endpoint or "").strip()
    if not ep:
        return ()
    if ep in ENDPOINT_PERMISSION_ANY:
        return ENDPOINT_PERMISSION_ANY[ep]
    p = permission_for_endpoint(ep)
    return (p,) if p else ()


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
