
import logging
import secrets
import string
from datetime import datetime, timezone
from extensions import db
from models import (
    User, Role, Permission, SystemSettings, Currency, Warehouse, Account,
    ProductCategory, ExpenseType, AccountType, ExchangeRate, WarehouseType
)
from permissions_config.permissions import PermissionsRegistry

class SystemInitializer:
    """
    مسؤول عن ضمان تكامل النظام وبنيته التحتية الأساسية.
    يعمل تلقائياً عند بدء التشغيل لضمان وجود البيانات الأساسية.
    """
    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("SystemInitializer")

    def ensure_integrity(self):
        """تشغيل الفحص الذاتي والتهيئة"""
        self.logger.info("SystemInitializer: Starting integrity check...")
        with self.app.app_context():
            try:
                self._ensure_settings()
                self._ensure_currencies()
                self._ensure_warehouse()
                self._ensure_chart_of_accounts()
                self._ensure_categories()
                self._ensure_roles_and_users()
                self.logger.info("System integrity check passed.")
            except Exception as e:
                self.logger.error(f"System integrity check failed: {e}")
                # لا نوقف النظام، ولكن نسجل الخطأ
    
    def _ensure_settings(self):
        defaults = {
            'system_name': ('نظام الحازم', 'اسم النظام'),
            'company_name': ('شركة الحازم للأنظمة الذكية', 'اسم الشركة'),
            'login_title': ('مرحباً بك', 'عنوان صفحة الدخول'),
            'login_subtitle': ('سجل دخولك للمتابعة', 'وصف صفحة الدخول'),
            'footer_text': ('جميع الحقوق محفوظة © 2026', 'نص التذييل'),
            'primary_color': ('#007bff', 'اللون الأساسي'),
            'secondary_color': ('#1f2937', 'اللون الثانوي'),
            'sidebar_bg': ('#111827', 'لون القائمة الجانبية'),
            'sidebar_text': ('#f9fafb', 'لون نص القائمة'),
            'currency_base': ('ILS', 'العملة الأساسية'),
            'tax_rate': ('16', 'نسبة الضريبة الافتراضية'),
            'online_fx_enabled': ('true', 'تفعيل تحديث أسعار العملات تلقائياً'),
            'developer_name': ('Eng. Ahmad Ghannam', 'اسم المطور'),
            'developer_email': ('rafideen.ahmadghannam@gmail.com', 'ايميل المطور'),
        }

        changes = False
        for key, (val, desc) in defaults.items():
            if not SystemSettings.query.filter_by(key=key).first():
                SystemSettings.set_setting(key, val, description=desc, commit=False)
                changes = True
        
        if changes:
            db.session.commit()
            self.logger.info("🔧 Default settings restored.")

    def _ensure_currencies(self):
        currencies = [
            ('ILS', 'الشيقل الإسرائيلي', '₪', 2, True),
            ('USD', 'الدولار الأمريكي', '$', 2, True),
            ('JOD', 'الدينار الأردني', 'JD', 3, True),
            ('EUR', 'اليورو', '€', 2, True),
            ('AED', 'الدرهم الإماراتي', 'د.إ', 2, True),
        ]

        changes = False
        for code, name, symbol, decimals, active in currencies:
            if not Currency.query.filter_by(code=code).first():
                cur = Currency(code=code, name=name, symbol=symbol, decimals=decimals, is_active=active)
                db.session.add(cur)
                changes = True
        
        if changes:
            db.session.commit()
            
        # Exchange Rates
        if not ExchangeRate.query.first():
             # USD Base
             db.session.add(ExchangeRate(base_code='USD', quote_code='ILS', rate=3.75))
             db.session.add(ExchangeRate(base_code='USD', quote_code='JOD', rate=0.708))
             db.session.add(ExchangeRate(base_code='USD', quote_code='AED', rate=3.67))
             # ILS Base
             db.session.add(ExchangeRate(base_code='ILS', quote_code='USD', rate=1/3.75))
             db.session.add(ExchangeRate(base_code='ILS', quote_code='JOD', rate=1/5.29))
             db.session.commit()
             self.logger.info("Default currencies initialized.")

    def _ensure_warehouse(self):
        from utils.tenant_org_structure import ensure_tenant_org_structure

        stats = ensure_tenant_org_structure(db.session)
        if stats.get("branch_created") or stats.get("warehouses_created"):
            db.session.commit()
            self.logger.info(
                "🏢 Org structure: branch=%s warehouses=%s linked=%s",
                stats.get("branch_created"),
                stats.get("warehouses_created"),
                stats.get("warehouses_linked"),
            )

    def _ensure_chart_of_accounts(self):
        # Basic COA Structure with String Codes
        accounts = [
            # Assets (1xxx)
            ('1000_CASH', 'النقدية في الصندوق', AccountType.ASSET),
            ('1010_BANK_ILS', 'البنك - شيقل', AccountType.ASSET),
            ('1020_BANK_USD', 'البنك - دولار', AccountType.ASSET),
            ('1100_AR', 'الذمم المدينة (العملاء)', AccountType.ASSET),
            ('1200_INVENTORY', 'المخزون', AccountType.ASSET),
            ('1300_FIXED_ASSETS', 'الأصول الثابتة', AccountType.ASSET),
            
            # Liabilities (2xxx)
            ('2000_AP', 'الذمم الدائنة (الموردين)', AccountType.LIABILITY),
            ('2100_VAT_PAYABLE', 'ضريبة القيمة المضافة مستحقة الدفع', AccountType.LIABILITY),
            ('2200_LOANS', 'قروض قصيرة الأجل', AccountType.LIABILITY),
            
            # Equity (3xxx)
            ('3000_CAPITAL', 'رأس المال', AccountType.EQUITY),
            ('3100_RETAINED_EARNINGS', 'الأرباح المحتجزة', AccountType.EQUITY),
            ('3200_PARTNER_EQUITY', 'جاري الشركاء', AccountType.EQUITY),
            
            # Revenue (4xxx)
            ('4000_SALES', 'إيرادات المبيعات', AccountType.REVENUE),
            ('4100_SERVICE_REVENUE', 'إيرادات الخدمات', AccountType.REVENUE),
            ('4200_OTHER_REVENUE', 'إيرادات أخرى', AccountType.REVENUE),
            
            # Expenses (5xxx)
            ('5000_COGS', 'تكلفة البضاعة المباعة', AccountType.EXPENSE),
            ('5100_SALARIES', 'رواتب وأجور', AccountType.EXPENSE),
            ('5200_RENT', 'إيجار', AccountType.EXPENSE),
            ('5300_UTILITIES', 'كهرباء وماء', AccountType.EXPENSE),
            ('5400_MARKETING', 'مصاريف تسويق', AccountType.EXPENSE),
            ('5500_ADMIN', 'مصاريف إدارية وعمومية', AccountType.EXPENSE),
            ('5600_MAINTENANCE', 'مصاريف صيانة', AccountType.EXPENSE),
        ]

        changes = False
        for code, name, type_ in accounts:
            exists = Account.query.filter_by(code=str(code)).first()
            if not exists:
                # Handle type conversion if it's an Enum
                type_val = getattr(type_, "value", type_)
                
                acc = Account(
                    code=str(code),
                    name=name,
                    type=type_val,
                    is_active=True
                )
                db.session.add(acc)
                changes = True
        
        if changes:
            db.session.commit()
            self.logger.info("📊 Chart of Accounts verified.")

    def _ensure_categories(self):
        # Product Categories
        prod_cats = ['قطع غيار', 'زيوت', 'إطارات', 'بطاريات', 'اكسسوارات', 'خدمات']
        for name in prod_cats:
            if not ProductCategory.query.filter_by(name=name).first():
                db.session.add(ProductCategory(name=name, description=f"تصنيف {name}"))
                
        # Expense Types
        exp_types = ['رواتب', 'إيجار', 'كهرباء', 'مياه', 'انترنت', 'ضيافة', 'نثريات', 'صيانة معدات', 'تسويق']
        for name in exp_types:
            if not ExpenseType.query.filter_by(name=name).first():
                db.session.add(ExpenseType(name=name, description=f"مصروف {name}"))
        
        db.session.commit()

    def _ensure_roles_and_users(self):
        # 1. Ensure permissions
        for category, perms in PermissionsRegistry.PERMISSIONS.items():
            for code, info in perms.items():
                if not Permission.query.filter_by(code=code).first():
                    perm = Permission(
                        code=code,
                        name=info['name_ar'],
                        name_ar=info['name_ar'],
                        description=info['description'],
                        module=info['module'],
                        is_protected=info.get('is_protected', False)
                    )
                    db.session.add(perm)
        db.session.commit()
        
        # Reload permissions
        all_db_perms = Permission.query.all()
        perm_lookup = {p.code: p for p in all_db_perms}
        
        # 2. Roles Definitions
        roles_config = self._get_roles_config(perm_lookup, all_db_perms)

        for role_name, description, perms in roles_config:
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name, description=description)
                db.session.add(role)
            else:
                role.description = description
            role.permissions = perms
        
        db.session.commit()

        # 3. Default Admin User
        if not User.query.first():
            admin_role = Role.query.filter_by(name='Owner').first() or Role.query.filter_by(name='Super Admin').first()
            if admin_role:
                user = User(
                    username='admin',
                    email='admin@alhazem.com',
                    role=admin_role,
                    is_active=True,
                    is_system_account=True
                )
                generated_password = ''.join(
                    secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*')
                    for _ in range(16)
                )
                user.set_password(generated_password)
                db.session.add(user)
                db.session.commit()
                self.logger.info(
                    "Default admin user created. "
                    "IMPORTANT: Initial password = %s  — change it immediately.",
                    generated_password,
                )

    def _get_roles_config(self, perm_lookup, all_db_perms):
        """تحديد صلاحيات الأدوار"""
        owner_perms = list(perm_lookup.values())

        excluded_for_admin = {
            'access_owner_dashboard', 'manage_tenants', 'manage_system_config', 
            'manage_any_user_permissions', 'manage_ai', 'access_ai_assistant', 'train_ai',
            'backup_database', 'restore_database', 'hard_delete', 'manage_saas', 
            'manage_mobile_app', 'manage_system_health'
        }
        super_admin_perms = [p for p in all_db_perms if p.code not in excluded_for_admin]

        # Accountant
        accountant_codes = {
            'access_dashboard',
            'manage_accounting_docs', 'validate_accounting', 'manage_ledger',
            'manage_payments', 'manage_expenses', 'view_reports', 'manage_reports',
            'manage_exchange', 'manage_currencies', 'manage_bank', 'view_bank', 'add_bank_transaction',
            'manage_sales', 'archive_sale', 'view_sales',
            'view_customers', 'manage_customers',
            'manage_vendors', 'add_supplier', 'add_partner',
            'view_inventory', 'view_warehouses',
            'view_shop', 'view_preorders', 'view_own_orders', 'view_own_account'
        }
        
        # Service Advisor
        service_advisor_codes = {
            'access_dashboard',
            'manage_service', 'view_service',
            'add_customer', 'view_customers', 'manage_customers',
            'view_inventory', 'view_parts', 'view_warehouses',
            'view_sales', 'view_barcode', 'view_notes', 'manage_notes',
            'view_own_orders', 'view_own_account'
        }

        # Mechanic
        mechanic_codes = {
            'access_dashboard', 'view_service', 'view_parts', 'view_inventory',
            'view_notes', 'view_own_orders', 'view_own_account'
        }

        # Storekeeper
        storekeeper_codes = {
            'access_dashboard', 'manage_warehouses', 'view_warehouses',
            'manage_inventory', 'view_inventory', 'warehouse_transfer',
            'view_parts', 'manage_vendors', 'add_supplier',
            'manage_shipments', 'view_barcode', 'manage_barcode',
            'view_own_orders', 'view_own_account'
        }
        
        # Sales Rep
        sales_rep_codes = {
            'access_dashboard', 'manage_sales', 'view_sales',
            'add_customer', 'view_customers',
            'view_inventory', 'view_shop', 'browse_products', 'place_online_order',
            'view_preorders', 'add_preorder', 'view_own_orders', 'view_own_account'
        }

        return [
            ('Owner', 'المالك', owner_perms),
            ('Super Admin', 'مدير النظام', super_admin_perms),
            ('Accountant', 'محاسب', [perm_lookup[c] for c in accountant_codes if c in perm_lookup]),
            ('Service Advisor', 'مستشار صيانة', [perm_lookup[c] for c in service_advisor_codes if c in perm_lookup]),
            ('Mechanic', 'فني صيانة', [perm_lookup[c] for c in mechanic_codes if c in perm_lookup]),
            ('Storekeeper', 'أمين مستودع', [perm_lookup[c] for c in storekeeper_codes if c in perm_lookup]),
            ('Sales Representative', 'مندوب مبيعات', [perm_lookup[c] for c in sales_rep_codes if c in perm_lookup]),
        ]
