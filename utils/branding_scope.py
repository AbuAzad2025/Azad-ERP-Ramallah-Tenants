"""
عزل نطاق الهوية: منصة أزاد (عام) مقابل تينانت (tenant_<slug>_*).
لا قراءة ولا كتابة عبر النطاقين.
"""
from __future__ import annotations

from flask import abort, g, redirect, url_for, flash

SCOPE_PLATFORM = "platform"
SCOPE_TENANT = "tenant"

# هوية المنصة: شركة أزاد للأنظمة الذكية (المطوّر/المالك) — ليست تينانت
PLATFORM_DEFAULT_COMPANY_NAME = "شركة أزاد للأنظمة الذكية"
PLATFORM_DEFAULT_SYSTEM_NAME = "منصة أزاد ERP"  # اسم المنتج — الشركة: PLATFORM_DEFAULT_COMPANY_NAME

# تينانتات معروفة (للتهيئة والتحقق فقط — كل slug له مفاتيح tenant_<slug>_*)
TENANT_KNOWN_PROFILES: dict[str, dict[str, str]] = {
    "alhazem": {
        "company_name": "شركة الحازم لقطع السيارات",
        "system_name": "نظام الحازم",
    },
    "nasrallah": {
        "company_name": "شركة المهندس الفلسطيني للمعدات الثقيلة",
        "system_name": "نظام المهندس الفلسطيني",
    },
}

# مفاتيح واجهة المنصة فقط (ألوان + شاشة الدخول)
PLATFORM_UI_KEYS = (
    "login_title",
    "login_subtitle",
    "primary_color",
    "secondary_color",
    "sidebar_bg",
    "sidebar_text",
)


def active_tenant_slug() -> str:
    return (getattr(g, "tenant_slug", None) or "").strip().lower()


def is_platform_request() -> bool:
    return not active_tenant_slug()


def require_platform_console():
    """يُستدعى من مسارات /security فقط — يمنع التسريب داخل /t/slug/."""
    if active_tenant_slug():
        abort(404)
    return None


def require_tenant_owner_console(*, expected_slug: str | None = None):
    from utils.branding_assets import is_tenant_session_user

    slug = (expected_slug or active_tenant_slug()).strip().lower()
    if not slug:
        abort(404)
    if active_tenant_slug() != slug:
        abort(404)
    if not is_tenant_session_user():
        flash("هذه الصفحة لمالك التينانت فقط.", "warning")
        return redirect(url_for("tenant_console.index"))
    return None


def assert_setting_key_for_scope(key: str, *, scope: str, tenant_slug: str | None = None) -> str:
    """يرفض مفاتيح tenant_* على المنصة ومفاتيح عامة على التينانت."""
    k = (key or "").strip()
    if scope == SCOPE_PLATFORM:
        if k.startswith("tenant_"):
            raise ValueError("مفتاح تينانت غير مسموح على المنصة")
        return k
    slug = (tenant_slug or "").strip().lower()
    if not slug:
        raise ValueError("slug التينانت مطلوب")
    if k.startswith("tenant_") and not k.startswith(f"tenant_{slug}_"):
        raise ValueError("مفتاح تينانت لا يخص هذا الـ slug")
    return k


def branding_hub_url():
    """رابط الهوية الموحّد حسب النطاق الحالي."""
    from flask import url_for as _url_for

    if active_tenant_slug():
        return _url_for("tenant_console.branding")
    return _url_for("security.owner_branding")


def build_platform_footer(*, dev_email_default: str = "") -> dict:
    """بيانات فوتر المنصة فقط (أزاد + المطوّر) — لا تستخدم إعدادات التينانت."""
    from datetime import datetime, timezone

    from flask import has_request_context, url_for

    from utils.branding_assets import ASSET_LOGOS, LOGO_EMBLEM, rel_path_platform

    _dev_name = "Eng. Ahmad Ghannam"
    _dev_email = (dev_email_default or "rafideen.ahmadghannam@gmail.com").strip()
    _pf_phone = ""

    if not active_tenant_slug():
        try:
            from models import SystemSettings as _SS

            _pf_phone = (_SS.get_setting("COMPANY_PHONE", "") or "").strip()
            _dev_name = (_SS.get_setting("developer_name", _dev_name) or _dev_name).strip()
            _dev_email = (_SS.get_setting("developer_email", _dev_email) or _dev_email).strip()
        except Exception:
            pass

    logo_url = f"/static/{rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM)}"
    if has_request_context():
        try:
            logo_url = url_for("static", filename=rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM))
        except Exception:
            pass

    return {
        "company_name": PLATFORM_DEFAULT_COMPANY_NAME,
        "system_name": PLATFORM_DEFAULT_SYSTEM_NAME,
        "developer_name_en": _dev_name or "Eng. Ahmad Ghannam",
        "developer_name_ar": "المهندس أحمد غنام",
        "email": _dev_email,
        "phone": _pf_phone,
        "logo_url": logo_url,
        "year": datetime.now(timezone.utc).year,
    }
