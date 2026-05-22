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
            {"endpoint": "advanced.owner_hub", "label": "مركز SaaS", "icon": "fa-cloud", "color": "primary", "desc": "التينانتات والبنية"},
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

TENANT_HUB_SECTIONS = (
    {
        "id": "ops",
        "title": "التشغيل",
        "icon": "fa-store",
        "cards": (
            {"endpoint": "main.dashboard", "label": "لوحة التشغيل", "icon": "fa-tachometer-alt", "color": "primary", "desc": "العمل اليومي"},
            {"endpoint": "sales_bp.list_sales", "label": "المبيعات", "icon": "fa-shopping-cart", "color": "success", "desc": "فواتير وذمم"},
            {"endpoint": "customers_bp.list_customers", "label": "العملاء", "icon": "fa-user-friends", "color": "info", "desc": "قاعدة العملاء"},
        ),
    },
    {
        "id": "brand",
        "title": "الهوية (مصدر واحد)",
        "icon": "fa-palette",
        "cards": (
            {"endpoint": "tenant_console.branding", "label": "الهوية والترويسة", "icon": "fa-image", "color": "warning", "desc": "شعار شركتك وفواتيرك فقط"},
        ),
    },
    {
        "id": "team",
        "title": "الفريق",
        "icon": "fa-users-cog",
        "cards": (
            {"endpoint": "users_bp.list_users", "label": "المستخدمون", "icon": "fa-users", "color": "success", "desc": "فريق التينانت"},
        ),
    },
)
