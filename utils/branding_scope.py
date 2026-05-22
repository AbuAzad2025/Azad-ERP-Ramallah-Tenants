"""
عزل نطاق الهوية: منصة أزاد (عام) مقابل تينانت (tenant_<slug>_*).
لا قراءة ولا كتابة عبر النطاقين.
"""
from __future__ import annotations

from flask import abort, g, redirect, url_for, flash

SCOPE_PLATFORM = "platform"
SCOPE_TENANT = "tenant"

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
