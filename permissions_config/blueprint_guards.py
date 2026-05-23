# مصدر واحد لصلاحيات الـ Blueprints — لا تُعرّف صلاحيات هنا، استخدم SystemPermissions فقط.
# Single source for blueprint ACL: all permission names come from enums.SystemPermissions.

from .enums import SystemPermissions

SP = SystemPermissions


def get_blueprint_guard_config():
    """
    Returns a list of (blueprint_attr_name, kwargs_for_attach_acl).
    Use only SP.XXX.value so the canonical permission names stay in enums.py.
    """
    return [
        (
            "shop_bp",
            {
                "read_perm": SP.VIEW_SHOP.value,
                "write_perm": SP.MANAGE_SHOP.value,
                "public_read": True,
                "exempt_prefixes": [
                    "/shop/admin",
                    "/shop/webhook",
                    "/shop/cart",
                    "/shop/cart/add",
                    "/shop/cart/update",
                    "/shop/cart/item",
                    "/shop/cart/remove",
                    "/shop/checkout",
                    "/shop/order",
                ],
            },
        ),
        ("users_bp", {"read_perm": SP.MANAGE_USERS.value, "write_perm": SP.MANAGE_USERS.value}),
        ("customers_bp", {"read_perm": SP.VIEW_CUSTOMERS.value, "write_perm": SP.MANAGE_CUSTOMERS.value}),
        ("vendors_bp", {"read_perm": SP.MANAGE_VENDORS.value, "write_perm": SP.MANAGE_VENDORS.value}),
        ("shipments_bp", {"read_perm": SP.MANAGE_SHIPMENTS.value, "write_perm": SP.MANAGE_SHIPMENTS.value}),
        ("warehouse_bp", {"read_perm": SP.VIEW_WAREHOUSES.value, "write_perm": SP.MANAGE_WAREHOUSES.value}),
        ("branches_bp", {"read_perm": SP.MANAGE_BRANCHES.value, "write_perm": SP.MANAGE_BRANCHES.value}),
        ("companies_bp", {"read_perm": SP.MANAGE_BRANCHES.value, "write_perm": SP.MANAGE_BRANCHES.value}),
        ("payments_bp", {"read_perm": SP.VIEW_PAYMENTS.value, "write_perm": SP.MANAGE_PAYMENTS.value}),
        ("expenses_bp", {"read_perm": SP.MANAGE_EXPENSES.value, "write_perm": SP.MANAGE_EXPENSES.value}),
        ("sales_bp", {"read_perm": SP.VIEW_SALES.value, "write_perm": SP.MANAGE_SALES.value}),
        ("service_bp", {"read_perm": SP.VIEW_SERVICE.value, "write_perm": SP.MANAGE_SERVICE.value}),
        (
            "reports_bp",
            {
                "read_perm": SP.VIEW_REPORTS.value,
                "write_perm": SP.MANAGE_REPORTS.value,
                "read_like_prefixes": [
                    "/reports/dynamic",
                    "/reports/api/dynamic",
                    "/reports/export/dynamic.csv",
                ],
            },
        ),
        ("financial_reports_bp", {"read_perm": SP.VIEW_REPORTS.value, "write_perm": SP.MANAGE_REPORTS.value}),
        ("roles_bp", {"read_perm": SP.MANAGE_ROLES.value, "write_perm": SP.MANAGE_ROLES.value}),
        ("permissions_bp", {"read_perm": SP.MANAGE_PERMISSIONS.value, "write_perm": SP.MANAGE_PERMISSIONS.value}),
        ("parts_bp", {"read_perm": SP.VIEW_PARTS.value, "write_perm": SP.MANAGE_INVENTORY.value}),
        ("admin_reports_bp", {"read_perm": SP.VIEW_REPORTS.value, "write_perm": SP.MANAGE_REPORTS.value}),
        ("main_bp", {"read_perm": None, "write_perm": None}),
        ("partner_settlements_bp", {"read_perm": SP.MANAGE_VENDORS.value, "write_perm": SP.MANAGE_VENDORS.value}),
        ("supplier_settlements_bp", {"read_perm": SP.MANAGE_VENDORS.value, "write_perm": SP.MANAGE_VENDORS.value}),
        (
            "api_bp",
            {
                "read_perm": SP.ACCESS_API.value,
                "write_perm": SP.MANAGE_API.value,
                "exempt_prefixes": ["/api/exchange-rates"],
            },
        ),
        ("notes_bp", {"read_perm": SP.VIEW_NOTES.value, "write_perm": SP.MANAGE_NOTES.value}),
        ("bp_barcode", {"read_perm": SP.VIEW_PARTS.value, "write_perm": None}),
        ("ledger_bp", {"read_perm": SP.VIEW_LEDGER.value, "write_perm": SP.MANAGE_LEDGER.value}),
        ("ledger_control_bp", {"read_perm": SP.VIEW_LEDGER.value, "write_perm": SP.MANAGE_LEDGER.value}),
        ("tenant_console_bp", {"read_perm": SP.ACCESS_TENANT_CONSOLE.value, "write_perm": SP.ACCESS_TENANT_CONSOLE.value}),
        ("tenant_fiscal_bp", {"read_perm": SP.MANAGE_LEDGER.value, "write_perm": SP.MANAGE_LEDGER.value}),
        ("accounting_validation_bp", {"read_perm": SP.VALIDATE_ACCOUNTING.value, "write_perm": SP.VALIDATE_ACCOUNTING.value}),
        ("budgets_bp", {"read_perm": SP.MANAGE_LEDGER.value, "write_perm": SP.MANAGE_LEDGER.value}),
        ("currencies_bp", {"read_perm": SP.MANAGE_CURRENCIES.value, "write_perm": SP.MANAGE_CURRENCIES.value}),
        ("barcode_scanner_bp", {"read_perm": SP.VIEW_BARCODE.value, "write_perm": SP.MANAGE_BARCODE.value}),
        ("checks_bp", {"read_perm": SP.VIEW_PAYMENTS.value, "write_perm": SP.MANAGE_PAYMENTS.value}),
        ("balances_api_bp", {"read_perm": SP.VIEW_REPORTS.value, "write_perm": SP.MANAGE_REPORTS.value}),
        ("returns_bp", {"read_perm": SP.VIEW_SALES.value, "write_perm": SP.MANAGE_SALES.value}),
        ("bank_bp", {"read_perm": SP.VIEW_BANK.value, "write_perm": SP.MANAGE_BANK.value}),
        ("cost_centers_bp", {"read_perm": SP.MANAGE_COST_CENTERS.value, "write_perm": SP.MANAGE_COST_CENTERS.value}),
        ("cost_centers_advanced_bp", {"read_perm": SP.MANAGE_COST_CENTERS.value, "write_perm": SP.MANAGE_COST_CENTERS.value}),
        ("engineering_bp", {"read_perm": SP.MANAGE_ENGINEERING.value, "write_perm": SP.MANAGE_ENGINEERING.value}),
        ("projects_bp", {"read_perm": SP.VIEW_PROJECTS.value, "write_perm": SP.MANAGE_PROJECTS.value}),
        ("project_advanced_bp", {"read_perm": SP.VIEW_PROJECTS.value, "write_perm": SP.MANAGE_PROJECTS.value}),
        ("workflows_bp", {"read_perm": SP.VIEW_WORKFLOWS.value, "write_perm": SP.MANAGE_WORKFLOWS.value}),
        ("assets_bp", {"read_perm": SP.MANAGE_LEDGER.value, "write_perm": SP.MANAGE_LEDGER.value}),
        ("archive_bp", {"read_perm": SP.MANAGE_USERS.value, "write_perm": SP.MANAGE_USERS.value}),
        ("accounting_docs_bp", {"read_perm": SP.MANAGE_ACCOUNTING_DOCS.value, "write_perm": SP.MANAGE_ACCOUNTING_DOCS.value}),
        (
            "recurring_bp",
            {
                "read_perm": SP.ACCESS_OWNER_DASHBOARD.value,
                "write_perm": SP.ACCESS_OWNER_DASHBOARD.value,
            },
        ),
        (
            "performance_bp",
            {
                "read_perm": SP.MANAGE_SYSTEM_HEALTH.value,
                "write_perm": SP.MANAGE_SYSTEM_HEALTH.value,
            },
        ),
        (
            "ai_admin_bp",
            {
                "read_perm": SP.MANAGE_AI.value,
                "write_perm": SP.MANAGE_AI.value,
            },
        ),
    ]
