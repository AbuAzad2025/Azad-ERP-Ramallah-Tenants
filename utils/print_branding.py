"""
إعدادات الهوية والطباعة — مصدر واحد.
منصة: مفاتيح عامة + branding/platform/
تينانت: tenant_<slug>_* + branding/tenants/<slug>/
"""
from __future__ import annotations

from typing import Any

from utils.branding_scope import (
    PLATFORM_UI_KEYS,
    SCOPE_PLATFORM,
    SCOPE_TENANT,
    active_tenant_slug,
    require_platform_console,
    require_tenant_owner_console,
)

TEMPLATE_SETTINGS_CACHE = "system_settings:template_settings:v1"

COMPANY_KEYS = (
    "company_name",
    "system_name",
    "COMPANY_ADDRESS",
    "COMPANY_PHONE",
    "COMPANY_EMAIL",
    "TAX_NUMBER",
    "footer_text",
)

INVOICE_KEYS = (
    "invoice_header_title",
    "invoice_header_color",
    "invoice_footer_text",
    "invoice_terms_text",
    "invoice_paper_size",
    "invoice_show_logo",
    "invoice_show_tax",
    "invoice_show_qr",
    "invoice_show_tax_number",
    "invoice_show_contact",
)

LETTERHEAD_MODE_KEY = "letterhead_mode"

INVOICE_DEFAULTS: dict[str, str] = {
    "invoice_header_title": "فاتورة ضريبية",
    "invoice_paper_size": "A4",
    "invoice_header_color": "#3c8dbc",
    "invoice_footer_text": "",
    "invoice_terms_text": "",
    "invoice_show_logo": "True",
    "invoice_show_tax": "True",
    "invoice_show_qr": "False",
    "invoice_show_tax_number": "True",
    "invoice_show_contact": "True",
}

PLATFORM_UI_DEFAULTS: dict[str, str] = {
    "login_title": "مرحباً بك",
    "login_subtitle": "سجل دخولك للمتابعة",
    "primary_color": "#007bff",
    "secondary_color": "#1f2937",
    "sidebar_bg": "#111827",
    "sidebar_text": "#f9fafb",
}


def tenant_db_key(slug: str, field: str) -> str:
    s = (slug or "").strip().lower()
    f = (field or "").strip()
    if f.startswith("tenant_"):
        return f
    return f"tenant_{s}_{f}" if s else f


def invalidate_branding_caches() -> None:
    try:
        from extensions import cache

        cache.delete(TEMPLATE_SETTINGS_CACHE)
    except Exception:
        pass


def _get_raw(key: str, default: str | None = None) -> str:
    from models import SystemSettings

    v = SystemSettings.get_setting(key, default)
    if v is None:
        return default if default is not None else ""
    return str(v).strip() if isinstance(v, str) else str(v)


def get_scoped_setting(key: str, default=None, *, tenant_slug: str | None = None):
    """قراءة آمنة: على المنصة لا تُقرأ مفاتيح tenant_*."""
    k = (key or "").strip()
    try:
        from flask import g, has_request_context

        if tenant_slug is None and has_request_context():
            tenant_slug = getattr(g, "tenant_slug", None)
    except Exception:
        pass

    slug = (tenant_slug or "").strip().lower()
    if not slug:
        if k.startswith("tenant_"):
            return default
        return _get_raw(k, default)

    tv = _get_raw(tenant_db_key(slug, k), None)
    if tv not in (None, ""):
        return tv
    if k.startswith("tenant_"):
        return default
    return _get_raw(k, default)


def _default_invoice(key: str) -> str:
    return INVOICE_DEFAULTS.get(key, "True" if key.startswith("invoice_show_") else "")


def _load_company_fields(*, slug: str | None, out: dict[str, Any]) -> None:
    for k in COMPANY_KEYS:
        if slug:
            if k == "company_name":
                plat = _get_raw("company_name", "") or _get_raw("CompanyName", "")
            elif k == "system_name":
                plat = _get_raw("system_name", "") or _get_raw("SystemName", "")
            else:
                plat = _get_raw(k, "")
            out[k] = _get_raw(tenant_db_key(slug, k), plat) or plat
        else:
            if k == "company_name":
                out[k] = _get_raw("company_name", "") or _get_raw("CompanyName", "")
            elif k == "system_name":
                out[k] = _get_raw("system_name", "") or _get_raw("SystemName", "")
            else:
                out[k] = _get_raw(k, "")


def load_branding_form(*, scope: str, tenant_slug: str | None = None) -> dict[str, Any]:
    if scope == SCOPE_PLATFORM:
        require_platform_console()
        slug = None
    elif scope == SCOPE_TENANT:
        slug = (tenant_slug or active_tenant_slug()).strip().lower()
        if not slug:
            raise ValueError("slug التينانت مطلوب")
    else:
        raise ValueError(f"scope غير معروف: {scope}")

    out: dict[str, Any] = {"scope": scope, "slug": slug}
    _load_company_fields(slug=slug, out=out)
    for k in INVOICE_KEYS:
        if slug:
            out[k] = _get_raw(tenant_db_key(slug, k), _get_raw(k, _default_invoice(k))) or _default_invoice(k)
        else:
            out[k] = _get_raw(k, _default_invoice(k)) or _default_invoice(k)
    if slug:
        out[LETTERHEAD_MODE_KEY] = _get_raw(tenant_db_key(slug, LETTERHEAD_MODE_KEY), "auto") or "auto"
    else:
        out[LETTERHEAD_MODE_KEY] = _get_raw(LETTERHEAD_MODE_KEY, "auto") or "auto"
        for uk in PLATFORM_UI_KEYS:
            out[uk] = _get_raw(uk, PLATFORM_UI_DEFAULTS.get(uk, ""))
    return out


def load_platform_branding_form() -> dict[str, Any]:
    return load_branding_form(scope=SCOPE_PLATFORM)


def load_tenant_branding_form(slug: str) -> dict[str, Any]:
    return load_branding_form(scope=SCOPE_TENANT, tenant_slug=slug)


def _save_company_and_invoice(*, slug: str | None, form, saved: list[str]) -> None:
    from models import SystemSettings

    for field in COMPANY_KEYS:
        if field not in form:
            continue
        v = (form.get(field) or "").strip()
        key = tenant_db_key(slug, field) if slug else field
        SystemSettings.set_setting(key, v, commit=False)
        saved.append(field)

    if LETTERHEAD_MODE_KEY in form:
        mode = (form.get(LETTERHEAD_MODE_KEY) or "auto").strip().lower()
        if mode not in ("auto", "image", "built"):
            mode = "auto"
        key = tenant_db_key(slug, LETTERHEAD_MODE_KEY) if slug else LETTERHEAD_MODE_KEY
        SystemSettings.set_setting(key, mode, commit=False)

    for key in INVOICE_KEYS:
        if key not in form and not key.startswith("invoice_show_"):
            continue
        if key.startswith("invoice_show_"):
            v = "True" if form.get(key) == "on" else "False"
        else:
            v = (form.get(key) or "").strip()
        db_key = tenant_db_key(slug, key) if slug else key
        SystemSettings.set_setting(db_key, v, commit=False)
        saved.append(key)


def _save_uploads(*, slug: str | None, files, saved: list[str]) -> None:
    from models import SystemSettings
    from utils.branding_assets import (
        ASSET_FAVICONS,
        ASSET_HEADERS,
        ASSET_LOGOS,
        FAVICON_FILE,
        HEADER_BANNER,
        HEADER_LETTERHEAD,
        LOGO_EMBLEM,
        LOGO_PRIMARY,
        LOGO_WHITE,
        normalize_rel_path,
        save_branding_upload,
    )

    if slug:
        upload_map = {
            "upload_logo": (ASSET_LOGOS, LOGO_PRIMARY, f"tenant_{slug}_logo"),
            "upload_favicon": (ASSET_FAVICONS, FAVICON_FILE, f"tenant_{slug}_favicon"),
            "upload_header": (ASSET_HEADERS, HEADER_LETTERHEAD, f"tenant_{slug}_header"),
            "upload_banner": (ASSET_HEADERS, HEADER_BANNER, f"tenant_{slug}_banner"),
        }
    else:
        upload_map = {
            "upload_logo": (ASSET_LOGOS, LOGO_PRIMARY, "custom_logo"),
            "upload_logo_emblem": (ASSET_LOGOS, LOGO_EMBLEM, "custom_logo_emblem"),
            "upload_logo_white": (ASSET_LOGOS, LOGO_WHITE, "custom_logo_white"),
            "upload_favicon": (ASSET_FAVICONS, FAVICON_FILE, "custom_favicon"),
            "upload_header": (ASSET_HEADERS, HEADER_LETTERHEAD, "platform_header"),
            "upload_banner": (ASSET_HEADERS, HEADER_BANNER, "platform_banner"),
        }

    for form_key, (asset_type, target_name, setting_key) in upload_map.items():
        f = files.get(form_key) if files else None
        if not f or not getattr(f, "filename", None):
            continue
        rel = save_branding_upload(
            slug=slug,
            asset_type=asset_type,
            target_filename=target_name,
            file_storage=f,
        )
        SystemSettings.set_setting(setting_key, normalize_rel_path(rel), commit=False)
        saved.append(form_key)


def save_branding_from_form(*, scope: str, tenant_slug: str | None, form, files) -> list[str]:
    from extensions import db
    from models import SystemSettings
    from utils.branding_assets import bump_assets_version

    saved: list[str] = []
    if scope == SCOPE_PLATFORM:
        require_platform_console()
        if active_tenant_slug():
            raise PermissionError("لا حفظ منصة داخل مسار تينانت")
        slug = None
        _save_company_and_invoice(slug=None, form=form, saved=saved)
        for uk in PLATFORM_UI_KEYS:
            if uk in form:
                SystemSettings.set_setting(uk, (form.get(uk) or "").strip(), commit=False)
        _save_uploads(slug=None, files=files, saved=saved)
    elif scope == SCOPE_TENANT:
        slug = (tenant_slug or active_tenant_slug()).strip().lower()
        if not slug or active_tenant_slug() != slug:
            raise PermissionError("slug التينانت غير متطابق")
        _save_company_and_invoice(slug=slug, form=form, saved=saved)
        _save_uploads(slug=slug, files=files, saved=saved)
    else:
        raise ValueError(f"scope غير معروف: {scope}")

    db.session.commit()
    bump_assets_version()
    invalidate_branding_caches()
    return saved


def save_platform_branding_from_form(form, files) -> list[str]:
    require_platform_console()
    return save_branding_from_form(scope=SCOPE_PLATFORM, tenant_slug=None, form=form, files=files)


def save_tenant_branding_from_form(slug: str, form, files) -> list[str]:
    return save_branding_from_form(scope=SCOPE_TENANT, tenant_slug=slug, form=form, files=files)


def resolve_print_settings(
    *,
    tenant_slug: str | None = None,
    raw_settings: dict | None = None,
    branding: dict | None = None,
) -> dict[str, Any]:
    slug = (tenant_slug or active_tenant_slug() or "").strip().lower()
    raw = raw_settings or {}

    def plat(key: str, default: str = "") -> str:
        if slug and key.startswith("tenant_"):
            return default
        v = raw.get(key) or raw.get(str(key).upper())
        if v is not None and str(v).strip():
            return str(v).strip()
        return _get_raw(key, default)

    def val(field: str, default: str = "") -> str:
        if slug:
            tk = tenant_db_key(slug, field)
            tv = raw.get(tk) or _get_raw(tk, None)
            if tv not in (None, ""):
                return str(tv).strip()
        return plat(field, default)

    company_name = val("company_name") or plat("company_name") or plat("CompanyName", "الشركة")
    inv = {k: val(k, _default_invoice(k)) for k in INVOICE_KEYS}
    header_url = (branding or {}).get("header_url") or ""
    letterhead_mode = val(LETTERHEAD_MODE_KEY, "auto")
    if letterhead_mode == "auto":
        letterhead_mode = "image" if header_url else "built"

    return {
        "scope": SCOPE_TENANT if slug else SCOPE_PLATFORM,
        "tenant_slug": slug or None,
        "company_name": company_name,
        "system_name": val("system_name") or plat("system_name") or plat("SystemName", ""),
        "COMPANY_ADDRESS": val("COMPANY_ADDRESS", plat("COMPANY_ADDRESS", "")),
        "COMPANY_PHONE": val("COMPANY_PHONE", plat("COMPANY_PHONE", "")),
        "COMPANY_EMAIL": val("COMPANY_EMAIL", plat("COMPANY_EMAIL", "")),
        "TAX_NUMBER": val("TAX_NUMBER", plat("TAX_NUMBER", "")),
        "footer_text": val("footer_text", plat("footer_text", "")),
        "letterhead_mode": letterhead_mode,
        "use_letterhead_image": letterhead_mode == "image" and bool(header_url),
        "use_built_header": letterhead_mode == "built" or (letterhead_mode == "image" and not header_url),
        **inv,
    }
