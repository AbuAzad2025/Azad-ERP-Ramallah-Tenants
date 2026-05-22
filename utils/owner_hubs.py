"""
تعريف لوحتي المالك — روابط غير متداخلة.
"""
from __future__ import annotations

PLATFORM_OWNER_TAGLINE = "لوحة مالك المنصة — شركة أزاد للأنظمة الذكية"
TENANT_OWNER_TAGLINE = "لوحة مالك التينانت — شركتك فقط"

PLATFORM_HUB_SECTIONS = (
    {
        "id": "command",
        "title": "القيادة",
        "icon": "fa-crown",
        "cards": (
            {"endpoint": "security.index", "label": "لوحة المالك", "icon": "fa-home", "color": "warning", "desc": "مركز قيادة المنصة"},
            {"endpoint": "security.settings_center", "label": "مركز العمليات", "icon": "fa-cogs", "color": "info", "desc": "ثوابت ونظام (بدون هوية مكررة)"},
            {"endpoint": "security.monitoring_dashboard", "label": "المراقبة", "icon": "fa-chart-line", "color": "success", "desc": "صحة المنصة"},
        ),
    },
    {
        "id": "brand",
        "title": "الهوية (مصدر واحد)",
        "icon": "fa-palette",
        "cards": (
            {"endpoint": "security.owner_branding", "label": "الهوية والترويسة", "icon": "fa-image", "color": "warning", "desc": "شعار أزاد، ترويسة، فواتير، ألوان — كل شيء هنا"},
        ),
    },
    {
        "id": "tenants",
        "title": "التينانتات",
        "icon": "fa-building",
        "cards": (
            {"endpoint": "advanced.multi_tenant", "label": "إنشاء وإدارة التينانتات", "icon": "fa-plus-circle", "color": "primary", "desc": "schema + مالك شركة + تفعيل /t/slug"},
            {"endpoint": "advanced.owner_hub", "label": "مركز SaaS", "icon": "fa-cloud", "color": "info", "desc": "بنية المنصة والنسخ"},
        ),
    },
    {
        "id": "governance",
        "title": "الحوكمة",
        "icon": "fa-shield-alt",
        "cards": (
            {"endpoint": "security.users_center", "label": "المستخدمون", "icon": "fa-users", "color": "primary", "desc": "فريق المنصة"},
            {"endpoint": "security.saas_manager", "label": "SaaS", "icon": "fa-money-check-alt", "color": "success", "desc": "خطط واشتراكات"},
            {"endpoint": "security.audit_log_viewer", "label": "التدقيق", "icon": "fa-file-signature", "color": "dark", "desc": "سجل العمليات"},
        ),
    },
)

# روابط تعمل تحت /t/<slug>/ مع search_path للتينانت — بدون SaaS أو /advanced
TENANT_HUB_SECTIONS = (
    {
        "id": "ops",
        "title": "التشغيل اليومي",
        "icon": "fa-store",
        "cards": (
            {"endpoint": "main.dashboard", "label": "لوحة التشغيل", "icon": "fa-tachometer-alt", "color": "primary", "desc": "مبيعات، صيانة، مخزون"},
            {"endpoint": "sales_bp.list_sales", "label": "المبيعات", "icon": "fa-shopping-cart", "color": "success", "desc": "فواتير وذمم عملاء"},
            {"endpoint": "customers_bp.list_customers", "label": "العملاء", "icon": "fa-user-friends", "color": "info", "desc": "بطاقات وكشوف حساب"},
            {"endpoint": "payments.index", "label": "الدفعات", "icon": "fa-money-bill-wave", "color": "success", "desc": "تحصيل وصرف"},
            {"endpoint": "vendors_bp.suppliers_list", "label": "الموردون", "icon": "fa-truck", "color": "secondary", "desc": "ذمم الموردين"},
            {"endpoint": "expenses_bp.list_expenses", "label": "المصروفات", "icon": "fa-receipt", "color": "warning", "desc": "مصاريف الشركة"},
        ),
    },
    {
        "id": "accounting",
        "title": "المحاسبة",
        "icon": "fa-calculator",
        "cards": (
            {"endpoint": "ledger_control.index", "label": "دفتر الأستاذ", "icon": "fa-book", "color": "primary", "desc": "حسابات، قيود GL، أرصدة"},
            {"endpoint": "tenant_fiscal_bp.index", "label": "إقفال الفترات", "icon": "fa-calendar-check", "color": "dark", "desc": "شهري / ربع / نصف / سنوي"},
            {"endpoint": "budgets.index", "label": "الموازنات", "icon": "fa-chart-pie", "color": "info", "desc": "تخطيط ومقارنة فعلي"},
            {"endpoint": "accounting_validation.index", "label": "التحقق المحاسبي", "icon": "fa-check-double", "color": "success", "desc": "توازن القيود والأرصدة"},
        ),
    },
    {
        "id": "reports",
        "title": "التقارير",
        "icon": "fa-chart-bar",
        "cards": (
            {"endpoint": "financial_reports.index", "label": "التقارير المالية", "icon": "fa-file-invoice-dollar", "color": "primary", "desc": "أرباح، ميزانية، تدفقات"},
            {"endpoint": "reports_bp.index", "label": "تقارير التشغيل", "icon": "fa-chart-line", "color": "info", "desc": "مبيعات، مخزون، أداء"},
        ),
    },
    {
        "id": "brand",
        "title": "الهوية",
        "icon": "fa-palette",
        "owner_only": True,
        "cards": (
            {"endpoint": "tenant_console.branding", "label": "الهوية والترويسة", "icon": "fa-image", "color": "warning", "desc": "شعار وفواتير شركتك"},
            {"endpoint": "tenant_console.business_settings", "label": "إعدادات المحاسبة", "icon": "fa-sliders-h", "color": "secondary", "desc": "بداية السنة المالية وثوابت شركتك"},
        ),
    },
    {
        "id": "team",
        "title": "الفريق",
        "icon": "fa-users-cog",
        "cards": (
            {"endpoint": "users_bp.list_users", "label": "المستخدمون", "icon": "fa-users", "color": "success", "desc": "فريق الشركة"},
            {"endpoint": "users_bp.create_user", "label": "إضافة مستخدم", "icon": "fa-user-plus", "color": "primary", "desc": "موظفون ومحاسبون — داخل شركتك فقط"},
        ),
    },
)

