"""
🔐 System Permissions & Roles Configuration - إعدادات صلاحيات النظام
════════════════════════════════════════════════════════════════════

وظيفة هذا الملف:
- تعريف كل صلاحيات النظام في مكان واحد (Single Source of Truth)
- تعريف الأدوار وصلاحياتها
- سهولة الإضافة والتعديل والصيانة

Created: 2025-11-02
Last Updated: 2026-03-11
"""

from typing import Dict, List, Set, Optional
from .enums import SystemPermissions, SystemRoles


class PermissionsRegistry:
    """
    سجل الصلاحيات المركزي
    جميع صلاحيات النظام مُعرّفة هنا
    """
    
    PERMISSIONS_AR_MAP = {
        SystemPermissions.MANAGE_BRANCHES: 'إدارة_الفروع',
        SystemPermissions.BACKUP_DATABASE: 'نسخ_احتياطي',
        SystemPermissions.RESTORE_DATABASE: 'استعادة_نسخة',
        SystemPermissions.HARD_DELETE: 'حذف_قوي',
        SystemPermissions.VIEW_AUDIT_LOGS: 'عرض_سجلات_التدقيق',
        SystemPermissions.ACCESS_OWNER_DASHBOARD: 'لوحة_المالك',
        SystemPermissions.ACCESS_TENANT_CONSOLE: 'لوحة_مالك_الشركة',
        SystemPermissions.MANAGE_ADVANCED_ACCOUNTING: 'محاسبة_متقدمة',
        SystemPermissions.MANAGE_ANY_USER_PERMISSIONS: 'تعديل_صلاحيات_المستخدمين',
        SystemPermissions.MANAGE_LEDGER: 'إدارة_الدفتر',
        SystemPermissions.VIEW_LEDGER: 'عرض_الدفتر',
        SystemPermissions.ACCESS_AI_ASSISTANT: 'مساعد_ذكي',
        SystemPermissions.TRAIN_AI: 'تدريب_الذكاء',
        SystemPermissions.MANAGE_PERMISSIONS: 'إدارة_الصلاحيات',
        SystemPermissions.MANAGE_ROLES: 'إدارة_الأدوار',
        SystemPermissions.MANAGE_USERS: 'إدارة_المستخدمين',
        SystemPermissions.MANAGE_CUSTOMERS: 'إدارة_العملاء',
        SystemPermissions.ADD_CUSTOMER: 'إضافة_عميل',
        SystemPermissions.VIEW_CUSTOMERS: 'عرض_العملاء',
        SystemPermissions.MANAGE_SALES: 'إدارة_المبيعات',
        SystemPermissions.ARCHIVE_SALE: 'أرشفة_المبيعات',
        SystemPermissions.VIEW_SALES: 'عرض_المبيعات',
        SystemPermissions.MANAGE_SERVICE: 'إدارة_الصيانة',
        SystemPermissions.VIEW_SERVICE: 'عرض_الصيانة',
        SystemPermissions.MANAGE_WAREHOUSES: 'إدارة_المستودعات',
        SystemPermissions.VIEW_WAREHOUSES: 'عرض_المستودعات',
        SystemPermissions.MANAGE_INVENTORY: 'إدارة_الجرد',
        SystemPermissions.VIEW_INVENTORY: 'عرض_الجرد',
        SystemPermissions.WAREHOUSE_TRANSFER: 'تحويل_مخزني',
        SystemPermissions.VIEW_PARTS: 'عرض_القطع',
        SystemPermissions.MANAGE_VENDORS: 'إدارة_الموردين',
        SystemPermissions.ADD_SUPPLIER: 'إضافة_مورد',
        SystemPermissions.ADD_PARTNER: 'إضافة_شريك',
        SystemPermissions.MANAGE_PAYMENTS: 'إدارة_المدفوعات',
        SystemPermissions.VIEW_PAYMENTS: 'عرض_المدفوعات',
        SystemPermissions.MANAGE_EXPENSES: 'إدارة_المصاريف',
        SystemPermissions.VIEW_REPORTS: 'عرض_التقارير',
        SystemPermissions.MANAGE_REPORTS: 'إدارة_التقارير',
        SystemPermissions.EXPORT_DATA: 'تصدير_البيانات',
        SystemPermissions.MANAGE_EXCHANGE: 'إدارة_التحويلات',
        SystemPermissions.MANAGE_CURRENCIES: 'إدارة_العملات',
        SystemPermissions.MANAGE_SHIPMENTS: 'إدارة_الشحن',
        SystemPermissions.VIEW_SHOP: 'عرض_المتجر',
        SystemPermissions.BROWSE_PRODUCTS: 'تصفح_المنتجات',
        SystemPermissions.MANAGE_SHOP: 'إدارة_المتجر',
        SystemPermissions.PLACE_ONLINE_ORDER: 'طلب_أونلاين',
        SystemPermissions.VIEW_PREORDERS: 'عرض_الطلبات_المسبقة',
        SystemPermissions.ADD_PREORDER: 'إضافة_طلب_مسبق',
        SystemPermissions.EDIT_PREORDER: 'تعديل_طلب_مسبق',
        SystemPermissions.DELETE_PREORDER: 'حذف_طلب_مسبق',
        SystemPermissions.ACCESS_API: 'الوصول_API',
        SystemPermissions.MANAGE_API: 'إدارة_API',
        SystemPermissions.VIEW_NOTES: 'عرض_الملاحظات',
        SystemPermissions.MANAGE_NOTES: 'إدارة_الملاحظات',
        SystemPermissions.VIEW_BARCODE: 'عرض_الباركود',
        SystemPermissions.MANAGE_BARCODE: 'إدارة_الباركود',
        SystemPermissions.USE_SCANNER: 'استخدام_الماسح',
        SystemPermissions.VIEW_OWN_ORDERS: 'عرض_طلباتي',
        SystemPermissions.VIEW_OWN_ACCOUNT: 'عرض_حسابي',
        SystemPermissions.ACCESS_DASHBOARD: 'الوصول_للوحة_التحكم',

        # Bank
        SystemPermissions.MANAGE_BANK: 'إدارة_البنك',
        SystemPermissions.VIEW_BANK: 'عرض_البنك',
        SystemPermissions.ADD_BANK_TRANSACTION: 'إضافة_معاملة_بنكية',

        # Projects
        SystemPermissions.MANAGE_PROJECTS: 'إدارة_المشاريع',
        SystemPermissions.VIEW_PROJECTS: 'عرض_المشاريع',

        # Workflows
        SystemPermissions.MANAGE_WORKFLOWS: 'إدارة_سير_العمل',
        SystemPermissions.VIEW_WORKFLOWS: 'عرض_سير_العمل',

        # Engineering & Cost Centers
        SystemPermissions.MANAGE_ENGINEERING: 'إدارة_الهندسة',
        SystemPermissions.MANAGE_COST_CENTERS: 'إدارة_مراكز_التكلفة',
        
        # Additional Accounting
        SystemPermissions.MANAGE_ACCOUNTING_DOCS: 'إدارة_المستندات',
        SystemPermissions.VALIDATE_ACCOUNTING: 'التحقق_المحاسبي',
        
        # AI Admin
        SystemPermissions.MANAGE_AI: 'إدارة_الذكاء_الاصطناعي',
    }
    
    PERMISSIONS = {
        'system': {
            SystemPermissions.ACCESS_DASHBOARD: {
                'name_ar': 'الوصول للوحة التحكم',
                'code_ar': 'الوصول_للوحة_التحكم',
                'description': 'الوصول للوحة التحكم الرئيسية',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.BACKUP_DATABASE: {
                'name_ar': 'نسخ احتياطي للنظام',
                'code_ar': 'نسخ_احتياطي',
                'description': 'إنشاء نسخة احتياطية من قاعدة البيانات',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.RESTORE_DATABASE: {
                'name_ar': 'استعادة نسخة احتياطية',
                'code_ar': 'استعادة_نسخة',
                'description': 'استعادة قاعدة البيانات من نسخة احتياطية',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.HARD_DELETE: {
                'name_ar': 'حذف قوي',
                'code_ar': 'حذف_قوي',
                'description': 'حذف نهائي من قاعدة البيانات',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.VIEW_AUDIT_LOGS: {
                'name_ar': 'عرض سجلات التدقيق',
                'code_ar': 'عرض_سجلات_التدقيق',
                'description': 'عرض كل سجلات النظام',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_TENANTS: {
                'name_ar': 'إدارة المستأجرين',
                'code_ar': 'إدارة_المستأجرين',
                'description': 'إدارة قواعد البيانات والمستأجرين',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_SYSTEM_CONFIG: {
                'name_ar': 'إعدادات النظام',
                'code_ar': 'إعدادات_النظام',
                'description': 'إدارة إعدادات النظام والميزات',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_SYSTEM_HEALTH: {
                'name_ar': 'صحة النظام',
                'code_ar': 'صحة_النظام',
                'description': 'مراقبة أداء وصحة النظام',
                'module': 'system',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_MOBILE_APP: {
                'name_ar': 'إدارة تطبيق الجوال',
                'code_ar': 'إدارة_تطبيق_الجوال',
                'description': 'إنشاء وإدارة تطبيقات الجوال',
                'module': 'system',
                'is_protected': True,
            },
        },
        
        'owner_only': {
            SystemPermissions.ACCESS_OWNER_DASHBOARD: {
                'name_ar': 'الوصول للوحة المالك',
                'code_ar': 'لوحة_المالك',
                'description': 'الوصول للوحة التحكم الخاصة بالمالك',
                'module': 'owner_only',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_ADVANCED_ACCOUNTING: {
                'name_ar': 'إدارة المحاسبة المتقدمة',
                'code_ar': 'محاسبة_متقدمة',
                'description': 'الوصول لوحدات المحاسبة المتقدمة',
                'module': 'owner_only',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_ANY_USER_PERMISSIONS: {
                'name_ar': 'إدارة صلاحيات أي مستخدم',
                'code_ar': 'تعديل_صلاحيات_المستخدمين',
                'description': 'إضافة وتعديل وحذف صلاحيات أي مستخدم',
                'module': 'owner_only',
                'is_protected': True,
            },
            SystemPermissions.ACCESS_TENANT_CONSOLE: {
                'name_ar': 'لوحة مالك الشركة (تينانت)',
                'code_ar': 'لوحة_مالك_الشركة',
                'description': 'الوصول إلى /t/<slug>/console — شركتك فقط',
                'module': 'owner_only',
                'is_protected': True,
            },
        },
        
        'ai': {
            SystemPermissions.MANAGE_AI: {
                'name_ar': 'إدارة الذكاء الاصطناعي',
                'code_ar': 'إدارة_الذكاء_الاصطناعي',
                'description': 'إدارة إعدادات ونماذج الذكاء الاصطناعي',
                'module': 'ai',
                'is_protected': True,
            },
            SystemPermissions.ACCESS_AI_ASSISTANT: {
                'name_ar': 'الوصول للمساعد الذكي',
                'code_ar': 'مساعد_ذكي',
                'description': 'استخدام المساعد الذكي',
                'module': 'ai',
                'is_protected': True,
            },
            SystemPermissions.TRAIN_AI: {
                'name_ar': 'تدريب المساعد الذكي',
                'code_ar': 'تدريب_الذكاء',
                'description': 'تدريب وإدارة المساعد الذكي',
                'module': 'ai',
                'is_protected': True,
            },
        },
        
        'users': {
            SystemPermissions.MANAGE_USERS: {
                'name_ar': 'إدارة المستخدمين',
                'code_ar': 'إدارة_المستخدمين',
                'description': 'إضافة وتعديل وحذف المستخدمين',
                'module': 'users',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_ROLES: {
                'name_ar': 'إدارة الأدوار',
                'code_ar': 'إدارة_الأدوار',
                'description': 'إضافة وتعديل وحذف أدوار المستخدمين',
                'module': 'users',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_PERMISSIONS: {
                'name_ar': 'إدارة الصلاحيات',
                'code_ar': 'إدارة_الصلاحيات',
                'description': 'إضافة وتعديل وحذف الصلاحيات',
                'module': 'users',
                'is_protected': True,
            },
        },
        
        'customers': {
            SystemPermissions.MANAGE_CUSTOMERS: {
                'name_ar': 'إدارة العملاء',
                'code_ar': 'إدارة_العملاء',
                'description': 'إدارة كاملة للعملاء',
                'module': 'customers',
                'is_protected': False,
            },
            SystemPermissions.ADD_CUSTOMER: {
                'name_ar': 'إضافة عميل',
                'code_ar': 'إضافة_عميل',
                'description': 'إضافة عميل جديد',
                'module': 'customers',
                'is_protected': False,
            },
            SystemPermissions.VIEW_CUSTOMERS: {
                'name_ar': 'عرض العملاء',
                'code_ar': 'عرض_العملاء',
                'description': 'عرض قائمة العملاء',
                'module': 'customers',
                'is_protected': False,
            },
        },
        
        'sales': {
            SystemPermissions.MANAGE_SALES: {
                'name_ar': 'إدارة المبيعات',
                'code_ar': 'إدارة_المبيعات',
                'description': 'إدارة كاملة للمبيعات',
                'module': 'sales',
                'is_protected': False,
            },
            SystemPermissions.ARCHIVE_SALE: {
                'name_ar': 'أرشفة المبيعات',
                'code_ar': 'أرشفة_المبيعات',
                'description': 'أرشفة عمليات البيع',
                'module': 'sales',
                'is_protected': False,
            },
            SystemPermissions.VIEW_SALES: {
                'name_ar': 'عرض المبيعات',
                'code_ar': 'عرض_المبيعات',
                'description': 'عرض قائمة المبيعات',
                'module': 'sales',
                'is_protected': False,
            },
        },
        
        'service': {
            SystemPermissions.MANAGE_SERVICE: {
                'name_ar': 'إدارة الصيانة',
                'code_ar': 'إدارة_الصيانة',
                'description': 'إدارة كاملة لطلبات الصيانة',
                'module': 'service',
                'is_protected': False,
            },
            SystemPermissions.VIEW_SERVICE: {
                'name_ar': 'عرض الصيانة',
                'code_ar': 'عرض_الصيانة',
                'description': 'عرض طلبات الصيانة',
                'module': 'service',
                'is_protected': False,
            },
        },
        
        'warehouses': {
            SystemPermissions.MANAGE_WAREHOUSES: {
                'name_ar': 'إدارة المستودعات',
                'code_ar': 'إدارة_المستودعات',
                'description': 'إدارة كاملة للمستودعات',
                'module': 'warehouses',
                'is_protected': False,
            },
            SystemPermissions.VIEW_WAREHOUSES: {
                'name_ar': 'عرض المستودعات',
                'code_ar': 'عرض_المستودعات',
                'description': 'عرض قائمة المستودعات',
                'module': 'warehouses',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_INVENTORY: {
                'name_ar': 'إدارة الجرد',
                'code_ar': 'إدارة_الجرد',
                'description': 'إدارة جرد المخزون',
                'module': 'warehouses',
                'is_protected': False,
            },
            SystemPermissions.VIEW_INVENTORY: {
                'name_ar': 'عرض الجرد',
                'code_ar': 'عرض_الجرد',
                'description': 'عرض جرد المخزون',
                'module': 'warehouses',
                'is_protected': False,
            },
            SystemPermissions.WAREHOUSE_TRANSFER: {
                'name_ar': 'تحويل مخزني',
                'code_ar': 'تحويل_مخزني',
                'description': 'نقل البضائع بين المستودعات',
                'module': 'warehouses',
                'is_protected': False,
            },
            SystemPermissions.VIEW_PARTS: {
                'name_ar': 'عرض القطع',
                'code_ar': 'عرض_القطع',
                'description': 'عرض قطع الغيار',
                'module': 'warehouses',
                'is_protected': False,
            },
        },
        
        'vendors': {
            SystemPermissions.MANAGE_VENDORS: {
                'name_ar': 'إدارة الموردين',
                'code_ar': 'إدارة_الموردين',
                'description': 'إدارة الموردين والشركاء',
                'module': 'vendors',
                'is_protected': False,
            },
            SystemPermissions.ADD_SUPPLIER: {
                'name_ar': 'إضافة مورد',
                'code_ar': 'إضافة_مورد',
                'description': 'إضافة مورد جديد',
                'module': 'vendors',
                'is_protected': False,
            },
            SystemPermissions.ADD_PARTNER: {
                'name_ar': 'إضافة شريك',
                'code_ar': 'إضافة_شريك',
                'description': 'إضافة شريك جديد',
                'module': 'vendors',
                'is_protected': False,
            },
        },
        
        'accounting': {
            SystemPermissions.MANAGE_ACCOUNTING_DOCS: {
                'name_ar': 'إدارة المستندات',
                'code_ar': 'إدارة_المستندات',
                'description': 'إدارة المستندات المحاسبية والأرشيف',
                'module': 'accounting',
                'is_protected': True,
            },
            SystemPermissions.VALIDATE_ACCOUNTING: {
                'name_ar': 'التحقق المحاسبي',
                'code_ar': 'التحقق_المحاسبي',
                'description': 'التحقق من صحة القيود والمراجعة',
                'module': 'accounting',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_LEDGER: {
                'name_ar': 'إدارة الدفتر',
                'code_ar': 'إدارة_الدفتر',
                'description': 'التحكم الكامل بالدفتر العام',
                'module': 'accounting',
                'is_protected': True,
            },
            SystemPermissions.MANAGE_PAYMENTS: {
                'name_ar': 'إدارة المدفوعات',
                'code_ar': 'إدارة_المدفوعات',
                'description': 'إدارة المدفوعات والسندات',
                'module': 'accounting',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_EXPENSES: {
                'name_ar': 'إدارة المصاريف',
                'code_ar': 'إدارة_المصاريف',
                'description': 'إدارة المصاريف والرواتب',
                'module': 'accounting',
                'is_protected': False,
            },
            SystemPermissions.VIEW_REPORTS: {
                'name_ar': 'عرض التقارير',
                'code_ar': 'عرض_التقارير',
                'description': 'عرض التقارير المالية',
                'module': 'accounting',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_REPORTS: {
                'name_ar': 'إدارة التقارير',
                'code_ar': 'إدارة_التقارير',
                'description': 'إنشاء وتعديل التقارير',
                'module': 'accounting',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_EXCHANGE: {
                'name_ar': 'إدارة التحويلات',
                'code_ar': 'إدارة_التحويلات',
                'description': 'إدارة تحويلات العملات',
                'module': 'accounting',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_CURRENCIES: {
                'name_ar': 'إدارة العملات',
                'code_ar': 'إدارة_العملات',
                'description': 'إدارة العملات وأسعار الصرف',
                'module': 'accounting',
                'is_protected': False,
            },
        },
        
        'shipments': {
            SystemPermissions.MANAGE_SHIPMENTS: {
                'name_ar': 'إدارة الشحن',
                'code_ar': 'إدارة_الشحن',
                'description': 'إدارة الشحنات والتوصيل',
                'module': 'shipments',
                'is_protected': False,
            },
        },
        
        'branches': {
            SystemPermissions.MANAGE_BRANCHES: {
                'name_ar': 'إدارة الفروع',
                'code_ar': 'إدارة_الفروع',
                'description': 'إدارة الفروع والمواقع',
                'module': 'branches',
                'is_protected': True,
            },
        },
        
        'saas': {
            SystemPermissions.MANAGE_SAAS: {
                'name_ar': 'إدارة SaaS',
                'code_ar': 'إدارة_SaaS',
                'description': 'إدارة الاشتراكات والباقات',
                'module': 'saas',
                'is_protected': True,
            },
        },
        
        'shop': {
            SystemPermissions.VIEW_SHOP: {
                'name_ar': 'عرض المتجر',
                'code_ar': 'عرض_المتجر',
                'description': 'الدخول للمتجر الإلكتروني',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.BROWSE_PRODUCTS: {
                'name_ar': 'تصفح المنتجات',
                'code_ar': 'تصفح_المنتجات',
                'description': 'تصفح منتجات المتجر',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_SHOP: {
                'name_ar': 'إدارة المتجر',
                'code_ar': 'إدارة_المتجر',
                'description': 'إدارة المتجر الإلكتروني',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.PLACE_ONLINE_ORDER: {
                'name_ar': 'طلب أونلاين',
                'code_ar': 'طلب_أونلاين',
                'description': 'إنشاء طلب من المتجر',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.VIEW_PREORDERS: {
                'name_ar': 'عرض الطلبات المسبقة',
                'code_ar': 'عرض_الطلبات_المسبقة',
                'description': 'عرض الطلبات المسبقة',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.ADD_PREORDER: {
                'name_ar': 'إضافة طلب مسبق',
                'code_ar': 'إضافة_طلب_مسبق',
                'description': 'إضافة طلب مسبق',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.EDIT_PREORDER: {
                'name_ar': 'تعديل طلب مسبق',
                'code_ar': 'تعديل_طلب_مسبق',
                'description': 'تعديل طلب مسبق',
                'module': 'shop',
                'is_protected': False,
            },
            SystemPermissions.DELETE_PREORDER: {
                'name_ar': 'حذف طلب مسبق',
                'code_ar': 'حذف_طلب_مسبق',
                'description': 'حذف طلب مسبق',
                'module': 'shop',
                'is_protected': False,
            },
        },
        
        'other': {
            SystemPermissions.ACCESS_API: {
                'name_ar': 'الوصول إلى API',
                'code_ar': 'الوصول_API',
                'description': 'الوصول لواجهة API',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_API: {
                'name_ar': 'إدارة API',
                'code_ar': 'إدارة_API',
                'description': 'إدارة واجهة API',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.VIEW_NOTES: {
                'name_ar': 'عرض الملاحظات',
                'code_ar': 'عرض_الملاحظات',
                'description': 'عرض الملاحظات',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_NOTES: {
                'name_ar': 'إدارة الملاحظات',
                'code_ar': 'إدارة_الملاحظات',
                'description': 'إضافة وتعديل الملاحظات',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.VIEW_BARCODE: {
                'name_ar': 'عرض الباركود',
                'code_ar': 'عرض_الباركود',
                'description': 'عرض الباركود',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.MANAGE_BARCODE: {
                'name_ar': 'إدارة الباركود',
                'code_ar': 'إدارة_الباركود',
                'description': 'إدارة الباركود',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.VIEW_OWN_ORDERS: {
                'name_ar': 'عرض طلباتي',
                'code_ar': 'عرض_طلباتي',
                'description': 'عرض طلبات المستخدم الشخصية',
                'module': 'other',
                'is_protected': False,
            },
            SystemPermissions.VIEW_OWN_ACCOUNT: {
                'name_ar': 'عرض حسابي',
                'code_ar': 'عرض_حسابي',
                'description': 'عرض الحساب الشخصي',
                'module': 'other',
                'is_protected': False,
            },
        },

        'bank': {
            SystemPermissions.MANAGE_BANK: {
                'name_ar': 'إدارة البنك',
                'code_ar': 'إدارة_البنك',
                'description': 'إدارة الحسابات البنكية والمعاملات',
                'module': 'bank',
                'is_protected': True,
            },
            SystemPermissions.VIEW_BANK: {
                'name_ar': 'عرض البنك',
                'code_ar': 'عرض_البنك',
                'description': 'عرض الحسابات البنكية',
                'module': 'bank',
                'is_protected': False,
            },
            SystemPermissions.ADD_BANK_TRANSACTION: {
                'name_ar': 'إضافة معاملة بنكية',
                'code_ar': 'إضافة_معاملة_بنكية',
                'description': 'إضافة إيداع أو سحب بنكي',
                'module': 'bank',
                'is_protected': True,
            },
        },

        'projects': {
            SystemPermissions.MANAGE_PROJECTS: {
                'name_ar': 'إدارة المشاريع',
                'code_ar': 'إدارة_المشاريع',
                'description': 'إدارة المشاريع بالكامل',
                'module': 'projects',
                'is_protected': True,
            },
            SystemPermissions.VIEW_PROJECTS: {
                'name_ar': 'عرض المشاريع',
                'code_ar': 'عرض_المشاريع',
                'description': 'عرض قائمة المشاريع',
                'module': 'projects',
                'is_protected': False,
            },
        },

        'workflows': {
            SystemPermissions.MANAGE_WORKFLOWS: {
                'name_ar': 'إدارة سير العمل',
                'code_ar': 'إدارة_سير_العمل',
                'description': 'إدارة وتصميم سير العمل',
                'module': 'workflows',
                'is_protected': True,
            },
            SystemPermissions.VIEW_WORKFLOWS: {
                'name_ar': 'عرض سير العمل',
                'code_ar': 'عرض_سير_العمل',
                'description': 'عرض حالات سير العمل',
                'module': 'workflows',
                'is_protected': False,
            },
        },

        'archive': {
            SystemPermissions.RESTORE_ARCHIVE: {
                'name_ar': 'استعادة الأرشيف',
                'code_ar': 'استعادة_أرشيف',
                'description': 'استعادة السجلات المؤرشفة',
                'module': 'archive',
                'is_protected': False,
            },
        },
        
        'engineering': {
            SystemPermissions.MANAGE_ENGINEERING: {
                'name_ar': 'إدارة الهندسة',
                'code_ar': 'إدارة_الهندسة',
                'description': 'إدارة العمليات الهندسية',
                'module': 'engineering',
                'is_protected': True,
            },
        },
        
        'cost_centers': {
            SystemPermissions.MANAGE_COST_CENTERS: {
                'name_ar': 'إدارة مراكز التكلفة',
                'code_ar': 'إدارة_مراكز_التكلفة',
                'description': 'إدارة مراكز التكلفة والمشاريع المالية',
                'module': 'cost_centers',
                'is_protected': True,
            },
        },
    }
    
    
    HIERARCHY = {
        0: [SystemRoles.OWNER, SystemRoles.DEVELOPER],
        1: [SystemRoles.SUPER_ADMIN, SystemRoles.SUPER],
        2: [SystemRoles.ADMIN],
        3: [SystemRoles.MANAGER],
        4: [SystemRoles.STAFF],
        5: [SystemRoles.MECHANIC],
        6: [SystemRoles.REGISTERED_CUSTOMER],
        7: [SystemRoles.GUEST],
    }
    
    ROLES = {
        SystemRoles.OWNER: {
            'name_ar': 'المالك',
            'description': '👑 مالك النظام - صلاحيات كاملة ومطلقة على كل شيء بلا استثناء',
            'permissions': '*',
            'exclude': [],
            'is_protected': True,
            'is_super': True,
            'level': 0,
            'max_accounts': 1,
            'special_access': [
                SystemPermissions.ACCESS_OWNER_DASHBOARD,
                SystemPermissions.MANAGE_ADVANCED_ACCOUNTING,
                SystemPermissions.MANAGE_ANY_USER_PERMISSIONS,
                SystemPermissions.MANAGE_LEDGER,
                SystemPermissions.ACCESS_AI_ASSISTANT,
                SystemPermissions.TRAIN_AI,
                SystemPermissions.HARD_DELETE,
                SystemPermissions.VIEW_AUDIT_LOGS,
            ],
            'capabilities': {
                'can_restore_db': True,
                'can_hard_delete': True,
                'can_manage_super_admins': True,
                'can_view_all_audit_logs': True,
                'can_manage_roles': True,
                'can_manage_permissions': True,
                'can_access_everything': True,
                'can_access_owner_dashboard': True,
                'can_manage_advanced_accounting': True,
                'can_manage_any_user_permissions': True,
            },
        },
        
        SystemRoles.DEVELOPER: {
            'name_ar': 'المطور',
            'description': '💻 مطور النظام - نفس صلاحيات المالك',
            'permissions': '*',
            'exclude': [],
            'is_protected': True,
            'is_super': True,
            'level': 0,
            'max_accounts': 2,
            'special_access': [
                SystemPermissions.ACCESS_OWNER_DASHBOARD,
                SystemPermissions.MANAGE_ADVANCED_ACCOUNTING,
                SystemPermissions.MANAGE_ANY_USER_PERMISSIONS,
                SystemPermissions.MANAGE_LEDGER,
                SystemPermissions.ACCESS_AI_ASSISTANT,
                SystemPermissions.TRAIN_AI,
                SystemPermissions.HARD_DELETE,
                SystemPermissions.VIEW_AUDIT_LOGS,
            ],
            'capabilities': {
                'can_restore_db': True,
                'can_hard_delete': True,
                'can_manage_super_admins': True,
                'can_view_all_audit_logs': True,
                'can_manage_roles': True,
                'can_manage_permissions': True,
                'can_access_everything': True,
                'can_access_owner_dashboard': True,
                'can_manage_advanced_accounting': True,
                'can_manage_any_user_permissions': True,
            },
        },
        
        SystemRoles.SUPER_ADMIN: {
            'name_ar': 'المدير الأعلى',
            'description': '⚡ مدير النظام - صلاحيات كاملة تقريباً ما عدا لوحة المالك والمساعد الذكي',
            'permissions': '*',
            'exclude': [
                SystemPermissions.ACCESS_OWNER_DASHBOARD, 
                SystemPermissions.MANAGE_ANY_USER_PERMISSIONS, 
                SystemPermissions.HARD_DELETE,
                SystemPermissions.MANAGE_API,
                SystemPermissions.ACCESS_AI_ASSISTANT,
                SystemPermissions.TRAIN_AI,
                SystemPermissions.MANAGE_AI
            ],
            'is_protected': True,
            'is_super': True,
            'level': 1,
            'max_accounts': None,
            'special_access': [
                SystemPermissions.MANAGE_ADVANCED_ACCOUNTING,
                SystemPermissions.MANAGE_LEDGER,
                SystemPermissions.MANAGE_SHOP,
            ],
            'capabilities': {
                'can_restore_db': True,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': True,
                'can_manage_roles': True,
                'can_manage_permissions': True,
                'can_access_everything': False,
                'can_access_owner_dashboard': False,
                'can_manage_advanced_accounting': True,
                'can_manage_any_user_permissions': False,
            },
        },
        
        SystemRoles.SUPER: {
            'name_ar': 'سوبر',
            'description': '⚡ سوبر - نفس صلاحيات المدير الأعلى',
            'permissions': '*',
            'exclude': [
                SystemPermissions.ACCESS_OWNER_DASHBOARD, 
                SystemPermissions.MANAGE_ANY_USER_PERMISSIONS, 
                SystemPermissions.HARD_DELETE,
                SystemPermissions.MANAGE_API,
                SystemPermissions.ACCESS_AI_ASSISTANT,
                SystemPermissions.TRAIN_AI,
                SystemPermissions.MANAGE_AI
            ],
            'is_protected': True,
            'is_super': True,
            'level': 1,
            'max_accounts': None,
            'special_access': [
                SystemPermissions.MANAGE_ADVANCED_ACCOUNTING,
                SystemPermissions.MANAGE_LEDGER,
                SystemPermissions.MANAGE_SHOP,
            ],
            'capabilities': {
                'can_restore_db': True,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': True,
                'can_manage_roles': True,
                'can_manage_permissions': True,
                'can_access_everything': False,
                'can_access_owner_dashboard': False,
                'can_manage_advanced_accounting': False,
                'can_manage_any_user_permissions': False,
            },
        },
        
        SystemRoles.ADMIN: {
            'name_ar': 'المدير',
            'description': '🎯 المدير - إدارة يومية كاملة (بدون متجر ومساعد ذكي ولوحة مالك)',
            'permissions': '*',
            'exclude': [
                SystemPermissions.RESTORE_DATABASE, 
                SystemPermissions.ACCESS_OWNER_DASHBOARD, 
                SystemPermissions.MANAGE_ADVANCED_ACCOUNTING, 
                SystemPermissions.MANAGE_ANY_USER_PERMISSIONS, 
                SystemPermissions.HARD_DELETE, 
                SystemPermissions.ACCESS_AI_ASSISTANT, 
                SystemPermissions.TRAIN_AI, 
                SystemPermissions.MANAGE_LEDGER,
                SystemPermissions.MANAGE_SHOP,
                SystemPermissions.VIEW_SHOP,
                SystemPermissions.BROWSE_PRODUCTS,
                SystemPermissions.PLACE_ONLINE_ORDER,
                SystemPermissions.VIEW_PREORDERS,
                SystemPermissions.ADD_PREORDER,
                SystemPermissions.EDIT_PREORDER,
                SystemPermissions.DELETE_PREORDER,
                SystemPermissions.MANAGE_API,
                SystemPermissions.ACCESS_API
            ],
            'is_protected': True,
            'is_super': False,
            'level': 2,
            'max_accounts': None,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': True,
                'can_manage_permissions': False,
                'can_access_everything': False,
                'can_access_owner_dashboard': False,
                'can_manage_advanced_accounting': False,
                'can_manage_any_user_permissions': False,
            },
        },
        
        SystemRoles.MANAGER: {
            'name_ar': 'المشرف',
            'description': '👨‍💼 مشرف - إشراف على العمليات اليومية',
            'permissions': [
                SystemPermissions.ACCESS_DASHBOARD,
                SystemPermissions.MANAGE_CUSTOMERS, SystemPermissions.ADD_CUSTOMER, SystemPermissions.VIEW_CUSTOMERS,
                SystemPermissions.MANAGE_SERVICE, SystemPermissions.VIEW_SERVICE,
                SystemPermissions.MANAGE_SALES, SystemPermissions.VIEW_SALES,
                SystemPermissions.MANAGE_PAYMENTS, SystemPermissions.MANAGE_EXPENSES,
                SystemPermissions.MANAGE_WAREHOUSES, SystemPermissions.VIEW_WAREHOUSES, SystemPermissions.MANAGE_INVENTORY, SystemPermissions.VIEW_INVENTORY, SystemPermissions.WAREHOUSE_TRANSFER,
                SystemPermissions.MANAGE_VENDORS, SystemPermissions.ADD_SUPPLIER, SystemPermissions.ADD_PARTNER,
                SystemPermissions.VIEW_REPORTS, SystemPermissions.MANAGE_REPORTS,
                SystemPermissions.VIEW_PARTS,
                SystemPermissions.VIEW_NOTES, SystemPermissions.MANAGE_NOTES,
                SystemPermissions.VIEW_BARCODE, SystemPermissions.MANAGE_BARCODE,
            ],
            'is_protected': False,
            'is_super': False,
            'level': 3,
            'max_accounts': None,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': False,
                'can_manage_permissions': False,
                'can_access_everything': False,
            },
        },
        
        SystemRoles.STAFF: {
            'name_ar': 'الموظف',
            'description': '👨‍💻 موظف - المبيعات والصيانة والمحاسبة',
            'permissions': [
                SystemPermissions.ACCESS_DASHBOARD,
                SystemPermissions.MANAGE_CUSTOMERS, SystemPermissions.ADD_CUSTOMER, SystemPermissions.VIEW_CUSTOMERS,
                SystemPermissions.MANAGE_SERVICE, SystemPermissions.VIEW_SERVICE,
                SystemPermissions.MANAGE_SALES, SystemPermissions.VIEW_SALES,
                SystemPermissions.MANAGE_PAYMENTS, SystemPermissions.MANAGE_EXPENSES,
                SystemPermissions.VIEW_WAREHOUSES, SystemPermissions.VIEW_INVENTORY, SystemPermissions.VIEW_PARTS,
                SystemPermissions.VIEW_REPORTS,
                SystemPermissions.VIEW_NOTES,
            ],
            'is_protected': False,
            'is_super': False,
            'level': 4,
            'max_accounts': None,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': False,
                'can_manage_permissions': False,
                'can_access_everything': False,
            },
        },
        
        SystemRoles.MECHANIC: {
            'name_ar': 'الميكانيكي',
            'description': '🔧 ميكانيكي - الصيانة والقطع فقط',
            'permissions': [
                SystemPermissions.ACCESS_DASHBOARD,
                SystemPermissions.MANAGE_SERVICE, SystemPermissions.VIEW_SERVICE,
                SystemPermissions.VIEW_WAREHOUSES, SystemPermissions.VIEW_INVENTORY, SystemPermissions.VIEW_PARTS,
                SystemPermissions.VIEW_REPORTS,
            ],
            'is_protected': False,
            'is_super': False,
            'level': 5,
            'max_accounts': None,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': False,
                'can_manage_permissions': False,
                'can_access_everything': False,
            },
        },
        
        SystemRoles.REGISTERED_CUSTOMER: {
            'name_ar': 'عميل مسجل',
            'description': '🛒 عميل - التصفح والطلبات الشخصية',
            'permissions': [
                SystemPermissions.VIEW_SHOP, SystemPermissions.BROWSE_PRODUCTS,
            ],
            'is_protected': False,
            'is_super': False,
            'level': 6,
            'max_accounts': None,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': False,
                'can_manage_permissions': False,
                'can_access_everything': False,
            },
        },
        
        SystemRoles.GUEST: {
            'name_ar': 'ضيف',
            'description': '👤 زائر غير مسجل - تصفح المتجر فقط',
            'permissions': [
                SystemPermissions.VIEW_SHOP,
                SystemPermissions.BROWSE_PRODUCTS,
            ],
            'is_protected': False,
            'is_super': False,
            'level': 7,
            'max_accounts': None,
            'requires_authentication': False,
            'capabilities': {
                'can_restore_db': False,
                'can_hard_delete': False,
                'can_manage_super_admins': False,
                'can_view_all_audit_logs': False,
                'can_manage_roles': False,
                'can_manage_permissions': False,
                'can_access_everything': False,
            },
        },
    }
    
    
    @classmethod
    def get_all_permissions(cls) -> Dict[str, Dict]:
        """
        جلب كل الصلاحيات مع معلوماتها
        
        Returns:
            dict: {code: {name_ar, description, module, is_protected}}
        """
        all_perms = {}
        for module, perms in cls.PERMISSIONS.items():
            all_perms.update(perms)
        return all_perms
    
    
    @classmethod
    def get_all_permission_codes(cls) -> Set[str]:
        """
        جلب كل أكواد الصلاحيات فقط
        
        Returns:
            set: {'manage_users', 'manage_sales', ...}
        """
        return set(cls.get_all_permissions().keys())
    
    
    @classmethod
    def get_permissions_by_module(cls, module: str) -> Dict[str, Dict]:
        """
        جلب صلاحيات وحدة معينة
        
        Args:
            module: اسم الوحدة (users, sales, ...)
        
        Returns:
            dict: الصلاحيات الخاصة بالوحدة
        """
        return cls.PERMISSIONS.get(module, {})
    
    
    @classmethod
    def get_protected_permissions(cls) -> Set[str]:
        """
        جلب الصلاحيات المحمية (لا يمكن حذفها)
        
        Returns:
            set: أكواد الصلاحيات المحمية
        """
        protected = set()
        for perm_code, perm_data in cls.get_all_permissions().items():
            if perm_data.get('is_protected', False):
                protected.add(perm_code)
        return protected
    
    
    @classmethod
    def get_role_permissions(cls, role_name: str) -> Set[str]:
        """
        جلب صلاحيات دور معين
        
        Args:
            role_name: اسم الدور
        
        Returns:
            set: أكواد الصلاحيات
        """
        if role_name not in cls.ROLES:
            return set()
        
        role = cls.ROLES[role_name]
        
        if role['permissions'] == '*':
            all_perms = cls.get_all_permission_codes()
            exclude = set(role.get('exclude', []))
            return all_perms - exclude
        
        return set(role['permissions'])
    
    
    @classmethod
    def is_permission_protected(cls, code: str) -> bool:
        """
        هل الصلاحية محمية؟
        
        Args:
            code: كود الصلاحية
        
        Returns:
            bool
        """
        all_perms = cls.get_all_permissions()
        return all_perms.get(code, {}).get('is_protected', False)
    
    
    @classmethod
    def is_role_protected(cls, role_name: str) -> bool:
        """
        هل الدور محمي؟
        
        Args:
            role_name: اسم الدور
        
        Returns:
            bool
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return False
        return role.get('is_protected', False)
    
    
    @classmethod
    def get_permission_info(cls, code: str) -> Optional[Dict]:
        """
        جلب معلومات صلاحية معينة
        
        Args:
            code: كود الصلاحية
        
        Returns:
            dict أو None
        """
        return cls.get_all_permissions().get(code)
    
    
    @classmethod
    def get_super_roles(cls) -> Set[str]:
        """
        جلب الأدوار التي لها is_super = True
        
        Returns:
            set: {'owner', 'developer', 'super_admin', 'super'}
        """
        return {
            role_name 
            for role_name, role_data in cls.ROLES.items() 
            if role_data.get('is_super', False)
        }
    
    
    @classmethod
    def get_roles_by_level(cls, level: int) -> List[str]:
        """
        جلب الأدوار في مستوى معين
        
        Args:
            level: المستوى (0-7)
        
        Returns:
            list: أسماء الأدوار
        """
        return [
            role_name 
            for role_name, role_data in cls.ROLES.items() 
            if role_data.get('level') == level
        ]
    
    
    @classmethod
    def is_role_super(cls, role_name: str) -> bool:
        """
        هل الدور من الأدوار العليا (Super)؟
        
        Args:
            role_name: اسم الدور
        
        Returns:
            bool
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return False
        return role.get('is_super', False)
    
    
    @classmethod
    def can_role_do(cls, role_name: str, capability: str) -> bool:
        """
        هل الدور يستطيع القيام بإجراء معين؟
        
        Args:
            role_name: اسم الدور
            capability: الإجراء (can_restore_db, can_hard_delete, ...)
        
        Returns:
            bool
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return False
        
        capabilities = role.get('capabilities', {})
        return capabilities.get(capability, False)
    
    
    @classmethod
    def get_role_level(cls, role_name: str) -> int:
        """
        جلب مستوى الدور
        
        Args:
            role_name: اسم الدور
        
        Returns:
            int: المستوى (0 = أعلى، 7 = أدنى)
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return 999
        return role.get('level', 999)
    
    
    @classmethod
    def is_role_higher_than(cls, role1: str, role2: str) -> bool:
        """
        هل role1 أعلى من role2؟
        
        Args:
            role1: الدور الأول
            role2: الدور الثاني
        
        Returns:
            bool
        """
        return cls.get_role_level(role1) < cls.get_role_level(role2)
    
    
    @classmethod
    def requires_authentication(cls, role_name: str) -> bool:
        """
        هل الدور يحتاج تسجيل دخول؟
        
        Args:
            role_name: اسم الدور
        
        Returns:
            bool (افتراضياً True عدا guest)
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return True
        return role.get('requires_authentication', True)
    
    
    @classmethod
    def get_role_max_accounts(cls, role_name: str) -> Optional[int]:
        """
        كم عدد الحسابات المسموح بها لهذا الدور؟
        
        Args:
            role_name: اسم الدور
        
        Returns:
            int أو None (None = غير محدود)
        """
        role = cls.ROLES.get(role_name)
        if not role:
            return None
        return role.get('max_accounts')
    
    
    @classmethod
    def validate_role_creation(cls, role_name: str, current_count: int = 0) -> tuple[bool, str]:
        """
        التحقق من إمكانية إنشاء حساب جديد لهذا الدور
        
        Args:
            role_name: اسم الدور
            current_count: عدد الحسابات الحالية
        
        Returns:
            (bool, str): (هل يمكن الإنشاء؟, رسالة)
        """
        max_accounts = cls.get_role_max_accounts(role_name)
        
        if max_accounts is None:
            return (True, "")
        
        if current_count >= max_accounts:
            role_ar = cls.ROLES.get(role_name, {}).get('name_ar', role_name)
            return (False, f"الحد الأقصى لحسابات {role_ar}: {max_accounts}")
        
        return (True, "")
    
    
    @classmethod
    def get_permission_by_arabic(cls, code_ar: str) -> Optional[str]:
        """
        البحث عن الصلاحية بالكود العربي
        
        Args:
            code_ar: الكود بالعربية (مثل: 'إدارة_المستخدمين')
        
        Returns:
            str: الكود الإنجليزي أو None
        """
        for eng_code, ar_code in cls.PERMISSIONS_AR_MAP.items():
            if ar_code == code_ar:
                return eng_code
        return None
    
    
    @classmethod
    def get_arabic_code(cls, english_code: str) -> Optional[str]:
        """
        الحصول على الكود العربي من الكود الإنجليزي
        
        Args:
            english_code: الكود بالإنجليزية
        
        Returns:
            str: الكود بالعربية أو None
        """
        return cls.PERMISSIONS_AR_MAP.get(english_code)
    
    
    @classmethod
    def supports_arabic_codes(cls) -> bool:
        """هل النظام يدعم الأكواد العربية؟"""
        return True


__all__ = [
    'PermissionsRegistry',
]
