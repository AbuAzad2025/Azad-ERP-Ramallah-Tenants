from enum import Enum

class SystemPermissions(str, Enum):
    # System
    ACCESS_DASHBOARD = 'access_dashboard'
    BACKUP_DATABASE = 'backup_database'
    RESTORE_DATABASE = 'restore_database'
    HARD_DELETE = 'hard_delete'
    VIEW_AUDIT_LOGS = 'view_audit_logs'
    MANAGE_TENANTS = 'manage_tenants'
    MANAGE_SYSTEM_CONFIG = 'manage_system_config'
    MANAGE_SYSTEM_HEALTH = 'manage_system_health'
    MANAGE_MOBILE_APP = 'manage_mobile_app'

    # Owner Only (منصة أزاد)
    ACCESS_OWNER_DASHBOARD = 'access_owner_dashboard'
    # لوحة مالك الشركة داخل /t/<slug>/console
    ACCESS_TENANT_CONSOLE = 'access_tenant_console'
    MANAGE_ADVANCED_ACCOUNTING = 'manage_advanced_accounting'
    MANAGE_ANY_USER_PERMISSIONS = 'manage_any_user_permissions'

    # AI
    MANAGE_AI = 'manage_ai'
    ACCESS_AI_ASSISTANT = 'access_ai_assistant'
    TRAIN_AI = 'train_ai'

    # Users
    MANAGE_USERS = 'manage_users'
    MANAGE_ROLES = 'manage_roles'
    MANAGE_PERMISSIONS = 'manage_permissions'

    # Customers
    MANAGE_CUSTOMERS = 'manage_customers'
    ADD_CUSTOMER = 'add_customer'
    VIEW_CUSTOMERS = 'view_customers'

    # Sales
    MANAGE_SALES = 'manage_sales'
    ARCHIVE_SALE = 'archive_sale'
    VIEW_SALES = 'view_sales'

    # Service
    MANAGE_SERVICE = 'manage_service'
    VIEW_SERVICE = 'view_service'

    # Warehouses
    MANAGE_WAREHOUSES = 'manage_warehouses'
    VIEW_WAREHOUSES = 'view_warehouses'
    MANAGE_INVENTORY = 'manage_inventory'
    VIEW_INVENTORY = 'view_inventory'
    WAREHOUSE_TRANSFER = 'warehouse_transfer'
    VIEW_PARTS = 'view_parts'

    # Vendors
    MANAGE_VENDORS = 'manage_vendors'
    ADD_SUPPLIER = 'add_supplier'
    ADD_PARTNER = 'add_partner'

    # Accounting
    MANAGE_ACCOUNTING_DOCS = 'manage_accounting_docs'
    VALIDATE_ACCOUNTING = 'validate_accounting'
    MANAGE_LEDGER = 'manage_ledger'
    VIEW_LEDGER = 'view_ledger'
    MANAGE_PAYMENTS = 'manage_payments'
    VIEW_PAYMENTS = 'view_payments'
    MANAGE_EXPENSES = 'manage_expenses'
    VIEW_REPORTS = 'view_reports'
    MANAGE_REPORTS = 'manage_reports'
    EXPORT_DATA = 'export_data'
    MANAGE_EXCHANGE = 'manage_exchange'
    MANAGE_CURRENCIES = 'manage_currencies'

    # Shipments
    MANAGE_SHIPMENTS = 'manage_shipments'

    # Branches
    MANAGE_BRANCHES = 'manage_branches'

    # SaaS
    MANAGE_SAAS = 'manage_saas'

    # Shop
    VIEW_SHOP = 'view_shop'
    BROWSE_PRODUCTS = 'browse_products'
    MANAGE_SHOP = 'manage_shop'
    PLACE_ONLINE_ORDER = 'place_online_order'
    VIEW_PREORDERS = 'view_preorders'
    ADD_PREORDER = 'add_preorder'
    EDIT_PREORDER = 'edit_preorder'
    DELETE_PREORDER = 'delete_preorder'

    # Other
    ACCESS_API = 'access_api'
    MANAGE_API = 'manage_api'
    VIEW_NOTES = 'view_notes'
    MANAGE_NOTES = 'manage_notes'
    VIEW_BARCODE = 'view_barcode'
    MANAGE_BARCODE = 'manage_barcode'
    USE_SCANNER = 'use_scanner'
    VIEW_OWN_ORDERS = 'view_own_orders'
    VIEW_OWN_ACCOUNT = 'view_own_account'

    # Bank
    MANAGE_BANK = 'manage_bank'
    VIEW_BANK = 'view_bank'
    ADD_BANK_TRANSACTION = 'add_bank_transaction'

    # Projects
    MANAGE_PROJECTS = 'manage_projects'
    VIEW_PROJECTS = 'view_projects'

    # Workflows
    MANAGE_WORKFLOWS = 'manage_workflows'
    VIEW_WORKFLOWS = 'view_workflows'

    # Archive
    RESTORE_ARCHIVE = 'restore_archive'

    # Engineering
    MANAGE_ENGINEERING = 'manage_engineering'

    # Cost Centers
    MANAGE_COST_CENTERS = 'manage_cost_centers'


class SystemRoles(str, Enum):
    OWNER = 'owner'
    DEVELOPER = 'developer'
    SUPER_ADMIN = 'super_admin'
    SUPER = 'super'
    ADMIN = 'admin'
    MANAGER = 'manager'
    STAFF = 'staff'
    MECHANIC = 'mechanic'
    REGISTERED_CUSTOMER = 'registered_customer'
    GUEST = 'guest'
