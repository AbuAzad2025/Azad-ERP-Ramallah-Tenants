"""فصل هوية المنصة (أزاد) عن هوية الشركة/التينانت."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import url_for
from flask_login import current_user

from utils.branding_assets import PLATFORM, tenant_rel_path, tenant_slug_for_code


def resolve_branding_bundle(
    *,
    raw_settings: dict,
    get_setting: Callable[[str, Any], Any],
    with_ver: Callable[[str], str],
    safe_static_path: Callable[..., str],
    safe_static_path_allow_root: Callable[..., str],
    static_file_exists: Callable[[str], bool],
) -> Dict[str, Any]:
    """يُرجع platform_* و tenant_* مع الحفاظ على custom_* للتوافق."""

    def _resolve_asset_url(
        setting_value,
        *fallback_paths: str,
        default: str = PLATFORM["logo"],
    ) -> str:
        candidates: list[str] = []
        if setting_value:
            candidates.append(safe_static_path(setting_value, default=""))
        for fb in fallback_paths:
            candidates.append(safe_static_path(fb, default=""))
        candidates.append(safe_static_path(default, default=default))
        seen: set[str] = set()
        for rel in candidates:
            if not rel or rel in seen:
                continue
            seen.add(rel)
            if static_file_exists(rel):
                return with_ver(url_for("static", filename=rel))
        return with_ver(url_for("static", filename=safe_static_path(default, default=default)))

    def _resolve_favicon_url(setting_value, *fallback_paths: str, default: str = PLATFORM["favicon"]) -> str:
        candidates: list[str] = []
        if setting_value:
            candidates.append(safe_static_path_allow_root(setting_value, default=""))
        for fb in fallback_paths:
            candidates.append(safe_static_path(fb, default=""))
        candidates.append(safe_static_path_allow_root(default, default=default))
        seen: set[str] = set()
        favicon_rel = safe_static_path(default, default=default)
        for rel in candidates:
            if not rel or rel in seen:
                continue
            seen.add(rel)
            if static_file_exists(rel):
                favicon_rel = rel
                break
        return with_ver(url_for("static", filename=favicon_rel))

    platform_company_name = (
        get_setting("company_name")
        or get_setting("CompanyName")
        or "شركة أزاد للأنظمة الذكية"
    )
    platform_product_name = get_setting("platform_product_name") or "أزاد لإدارة الكراج"

    platform_logo_url = _resolve_asset_url(
        get_setting("platform_logo"),
        f"static/{PLATFORM['logo']}",
        default=PLATFORM["logo"],
    )
    platform_emblem_url = _resolve_asset_url(
        get_setting("platform_logo_emblem"),
        f"static/{PLATFORM['emblem']}",
        default=PLATFORM["emblem"],
    )
    platform_white_url = _resolve_asset_url(
        get_setting("platform_logo_white"),
        f"static/{PLATFORM['white']}",
        default=PLATFORM["white"],
    )
    platform_favicon_url = _resolve_favicon_url(
        get_setting("platform_favicon"),
        f"static/{PLATFORM['favicon']}",
        default=PLATFORM["favicon"],
    )
    platform_login_bg_url = _resolve_asset_url(
        get_setting("platform_login_bg"),
        f"static/{PLATFORM['login_bg']}",
        default=PLATFORM["login_bg"],
    )

    tenant_system_name = get_setting("system_name") or get_setting("SystemName") or platform_product_name
    tenant_company_name = tenant_system_name
    tenant_company_code: Optional[str] = None
    tenant_slug: Optional[str] = None

    tenant_logo_setting = get_setting("custom_logo")
    tenant_emblem_setting = get_setting("custom_logo_emblem")
    tenant_white_setting = get_setting("custom_logo_white")
    tenant_favicon_setting = get_setting("custom_favicon")

    if getattr(current_user, "is_authenticated", False):
        try:
            from utils.tenant_ui import build_tenant_context

            tctx = build_tenant_context()
            if tctx.get("tenant_company_name"):
                tenant_company_name = str(tctx["tenant_company_name"]).strip()
            company_id = tctx.get("tenant_company_id")
            if company_id:
                from models import Company

                co = Company.query.get(int(company_id))
                if co:
                    tenant_company_code = (co.code or "").strip().upper() or None
                    tenant_slug = tenant_slug_for_code(tenant_company_code)
                    if co.name:
                        tenant_company_name = co.name
        except Exception:
            pass

    if tenant_company_code:
        code = tenant_company_code
        tenant_logo_setting = get_setting(f"company_{code}_logo") or tenant_logo_setting
        tenant_emblem_setting = get_setting(f"company_{code}_logo_emblem") or tenant_emblem_setting
        tenant_white_setting = get_setting(f"company_{code}_logo_white") or tenant_white_setting
        tenant_favicon_setting = get_setting(f"company_{code}_favicon") or tenant_favicon_setting

        if tenant_slug:
            if not tenant_logo_setting and static_file_exists(tenant_rel_path(tenant_slug, "logo")):
                tenant_logo_setting = f"static/{tenant_rel_path(tenant_slug, 'logo')}"
            if not tenant_emblem_setting and static_file_exists(tenant_rel_path(tenant_slug, "emblem")):
                tenant_emblem_setting = f"static/{tenant_rel_path(tenant_slug, 'emblem')}"
            if not tenant_white_setting and static_file_exists(tenant_rel_path(tenant_slug, "white")):
                tenant_white_setting = f"static/{tenant_rel_path(tenant_slug, 'white')}"
            if not tenant_favicon_setting and static_file_exists(tenant_rel_path(tenant_slug, "favicon")):
                tenant_favicon_setting = f"static/{tenant_rel_path(tenant_slug, 'favicon')}"

    default_tenant_logo = tenant_rel_path("phe", "logo")
    default_tenant_emblem = tenant_rel_path("phe", "emblem")
    default_tenant_white = tenant_rel_path("phe", "white")
    default_tenant_favicon = tenant_rel_path("phe", "favicon")

    tenant_logo_url = _resolve_asset_url(
        tenant_logo_setting,
        f"static/{default_tenant_logo}",
        default=default_tenant_logo,
    )
    tenant_emblem_url = _resolve_asset_url(
        tenant_emblem_setting,
        f"static/{default_tenant_emblem}",
        default=default_tenant_emblem,
    )
    tenant_white_url = _resolve_asset_url(
        tenant_white_setting,
        f"static/{default_tenant_white}",
        default=default_tenant_white,
    )
    tenant_favicon_url = _resolve_favicon_url(
        tenant_favicon_setting,
        f"static/{default_tenant_favicon}",
        default=default_tenant_favicon,
    )

    return {
        "platform_company_name": platform_company_name,
        "platform_product_name": platform_product_name,
        "platform_logo_url": platform_logo_url,
        "platform_logo_emblem_url": platform_emblem_url,
        "platform_logo_white_url": platform_white_url,
        "platform_favicon_url": platform_favicon_url,
        "platform_login_bg_url": platform_login_bg_url,
        "tenant_company_name": tenant_company_name,
        "tenant_system_name": tenant_system_name,
        "tenant_logo_url": tenant_logo_url,
        "tenant_logo_emblem_url": tenant_emblem_url,
        "tenant_logo_white_url": tenant_white_url,
        "tenant_favicon_url": tenant_favicon_url,
        "tenant_company_code": tenant_company_code or "",
        "tenant_branding_slug": tenant_slug or "",
        "custom_logo": tenant_logo_setting or "",
        "custom_logo_url": tenant_logo_url,
        "custom_logo_emblem_url": tenant_emblem_url,
        "custom_logo_white_url": tenant_white_url,
        "custom_favicon": tenant_favicon_setting or "",
        "custom_favicon_url": tenant_favicon_url,
        "company_name": platform_company_name,
        "system_name": tenant_system_name,
    }
