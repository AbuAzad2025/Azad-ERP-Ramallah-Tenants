"""تنظيم وتوليد أصول الهوية البصرية (منصة + تينانت)."""
from __future__ import annotations

import os
import re
import shutil
from typing import Callable

from PIL import Image, ImageOps
from flask.cli import with_appcontext

BRANDING_REL = "img/branding"

PLATFORM = {
    "logo": f"{BRANDING_REL}/platform/logos/primary.png",
    "emblem": f"{BRANDING_REL}/platform/logos/emblem.png",
    "white": f"{BRANDING_REL}/platform/logos/white.png",
    "favicon": f"{BRANDING_REL}/platform/favicons/favicon.png",
    "letterhead": f"{BRANDING_REL}/platform/headers/letterhead.png",
    "login_bg": f"{BRANDING_REL}/platform/auth/login_bg.webp",
}

TENANT_SUBPATHS = {
    "logo": "logos/primary.png",
    "emblem": "logos/emblem.png",
    "white": "logos/white.png",
    "favicon": "favicons/favicon.png",
    "letterhead": "headers/letterhead.png",
    "banner": "headers/banner.png",
}

LOGO_UPLOAD_MAP = {
    "main": ("logo", "logos/primary.png"),
    "emblem": ("emblem", "logos/emblem.png"),
    "white": ("white", "logos/white.png"),
    "favicon": ("favicon", "favicons/favicon.png"),
}

CUSTOM_LOGO_KEYS = {
    "logo": "custom_logo",
    "emblem": "custom_logo_emblem",
    "white": "custom_logo_white",
    "favicon": "custom_favicon",
}

# مجلدات قديمة → slug الشركة الحالي
LEGACY_TENANT_DIRS = {
    "phe": ("nasrallah",),
    "nasr": (),
}

_COMPANY_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _abs(root: str, *parts: str) -> str:
    return os.path.join(root, *parts)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def tenant_slug_for_code(code: str | None) -> str | None:
    if not code:
        return None
    slug = str(code).strip().lower()
    if not slug or not _COMPANY_CODE_RE.match(slug):
        return None
    return slug


def tenant_rel_path(slug: str, asset_key: str) -> str:
    return f"{BRANDING_REL}/tenants/{slug}/{TENANT_SUBPATHS[asset_key]}"


def tenant_static_path(slug: str, asset_key: str) -> str:
    return f"static/{tenant_rel_path(slug, asset_key)}"


def tenant_dir(root: str, slug: str) -> str:
    return _abs(root, "static", BRANDING_REL.replace("/", os.sep), "tenants", slug)


def company_setting_keys(code: str) -> dict[str, str]:
    code = code.strip().upper()
    return {
        "logo": f"company_{code}_logo",
        "emblem": f"company_{code}_logo_emblem",
        "white": f"company_{code}_logo_white",
        "favicon": f"company_{code}_favicon",
    }


def ensure_company_branding_dirs(root: str, company_code: str) -> str | None:
    """ينشئ هيكل مجلدات أصول الشركة تلقائياً."""
    slug = tenant_slug_for_code(company_code)
    if not slug:
        return None
    base = tenant_dir(root, slug)
    for sub in ("logos", "favicons", "headers"):
        _ensure_dir(os.path.join(base, sub))
    return base


def tenant_asset_paths(slug: str) -> dict[str, str]:
    return {key: tenant_rel_path(slug, key) for key in TENANT_SUBPATHS}


def normalize_static_rel(value: str | None) -> str:
    s = str(value or "").strip().replace("\\", "/")
    if not s:
        return ""
    if s.lower().startswith(("http://", "https://", "//")):
        return ""
    s = s.lstrip("/")
    if s.startswith("static/"):
        s = s[len("static/") :]
    parts = [p for p in s.split("/") if p and p not in {".", ".."}]
    return "/".join(parts)


def default_company_code() -> str:
    from models import Company

    co = Company.query.filter_by(code="PHE").first() or Company.query.order_by(Company.id).first()
    return (co.code or "").strip().upper() if co and co.code else ""


def static_file_exists(root: str, rel_path: str) -> bool:
    rel = normalize_static_rel(rel_path)
    if not rel:
        return False
    return os.path.isfile(_abs(root, "static", rel.replace("/", os.sep)))


def resolve_company_logo_assets(
    root: str,
    company_code: str,
    *,
    get_setting,
) -> dict[str, dict[str, object]]:
    """حل مسارات ومعاينة شعارات شركة محددة (DB ثم الملفات)."""
    slug = tenant_slug_for_code(company_code) or "phe"
    canonical = tenant_asset_paths(slug)
    setting_keys = company_setting_keys(company_code)
    manifest: dict[str, dict[str, object]] = {}

    for logo_type, (asset_key, _subpath) in LOGO_UPLOAD_MAP.items():
        db_val = normalize_static_rel(get_setting(setting_keys[asset_key], "") or "")
        candidates = [db_val, canonical[asset_key]] if db_val else [canonical[asset_key]]
        seen: set[str] = set()
        static_rel = canonical[asset_key]
        exists = False
        for rel in candidates:
            if not rel or rel in seen:
                continue
            seen.add(rel)
            if static_file_exists(root, rel):
                static_rel = rel
                exists = True
                break

        manifest[logo_type] = {
            "static_rel": static_rel,
            "exists": exists,
            "setting_key": setting_keys[asset_key],
            "from_db": bool(db_val and db_val == static_rel),
        }
    return manifest


def persist_tenant_logo_settings(
    company_code: str,
    rel_path: str,
    asset_key: str,
    *,
    set_setting,
    default_code: str | None = None,
) -> None:
    """يحدّث company_{CODE}_* و custom_* للشركة الافتراضية."""
    code = company_code.strip().upper()
    keys = company_setting_keys(code)
    setting_key = keys.get(asset_key)
    if setting_key:
        set_setting(setting_key, rel_path, data_type="string", commit=False)

    default = (default_code or default_company_code()).strip().upper()
    custom_key = CUSTOM_LOGO_KEYS.get(asset_key)
    if custom_key and code == default:
        set_setting(custom_key, rel_path, data_type="string", commit=False)


def clear_tenant_logo_setting(
    company_code: str,
    asset_key: str,
    *,
    delete_setting,
    default_code: str | None = None,
) -> None:
    """يمسح إعداد الشعار من DB (يبقى الملف على القرص)."""
    code = company_code.strip().upper()
    keys = company_setting_keys(code)
    setting_key = keys.get(asset_key)
    if setting_key:
        delete_setting(setting_key)

    default = (default_code or default_company_code()).strip().upper()
    custom_key = CUSTOM_LOGO_KEYS.get(asset_key)
    if custom_key and code == default:
        delete_setting(custom_key)


def _save_png(img: Image.Image, path: str, size: tuple[int, int] | None = None) -> None:
    out = img.convert("RGBA")
    if size:
        out = ImageOps.contain(out, size, method=Image.Resampling.LANCZOS)
    _ensure_dir(os.path.dirname(path))
    out.save(path, format="PNG", optimize=True)


def _save_favicon(img: Image.Image, path: str) -> None:
    _save_png(img, path, size=(64, 64))


def _save_emblem(img: Image.Image, path: str) -> None:
    _save_png(img, path, size=(128, 128))


def _save_letterhead(img: Image.Image, path: str) -> None:
    _save_png(img, path, size=(800, 200))


def _save_white(img: Image.Image, path: str) -> None:
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    white = Image.merge(
        "RGBA",
        (r.point(lambda _: 255), g.point(lambda _: 255), b.point(lambda _: 255), a),
    )
    _save_png(white, path, size=(400, 120))


def generate_derivatives(
    primary_path: str,
    tenant_dir_path: str,
    *,
    force: bool = False,
    include_white: bool = False,
) -> list[str]:
    if not os.path.isfile(primary_path):
        return []
    created: list[str] = []
    img = Image.open(primary_path)
    targets: dict[str, Callable[[Image.Image, str], None]] = {
        os.path.join(tenant_dir_path, "favicons", "favicon.png"): _save_favicon,
        os.path.join(tenant_dir_path, "logos", "emblem.png"): _save_emblem,
        os.path.join(tenant_dir_path, "headers", "letterhead.png"): _save_letterhead,
        os.path.join(tenant_dir_path, "headers", "banner.png"): _save_letterhead,
    }
    if include_white:
        targets[os.path.join(tenant_dir_path, "logos", "white.png")] = _save_white
    for path, saver in targets.items():
        if force or not os.path.isfile(path):
            saver(img, path)
            created.append(path)
    return created


def _copy_tree(src: str, dst: str) -> None:
    if not os.path.isdir(src):
        return
    _ensure_dir(dst)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            _copy_tree(s, d)
        elif os.path.isfile(s):
            _ensure_dir(os.path.dirname(d))
            if not os.path.isfile(d):
                shutil.copy2(s, d)


def _migrate_legacy_tenants(root: str) -> None:
    tenants_root = _abs(root, "static", BRANDING_REL.replace("/", os.sep), "tenants")
    if not os.path.isdir(tenants_root):
        return

    for slug, legacy_names in LEGACY_TENANT_DIRS.items():
        target = os.path.join(tenants_root, slug)
        primary = os.path.join(target, "logos", "primary.png")
        if os.path.isfile(primary):
            continue
        for legacy in legacy_names:
            legacy_dir = os.path.join(tenants_root, legacy)
            if os.path.isdir(legacy_dir):
                _copy_tree(legacy_dir, target)
                break

    nasr_primary = os.path.join(tenants_root, "nasr", "logos", "primary.png")
    t_naser = _abs(root, "static", "img", "T-Naser Company.png")
    if os.path.isfile(t_naser) and not os.path.isfile(nasr_primary):
        _ensure_dir(os.path.dirname(nasr_primary))
        shutil.copy2(t_naser, nasr_primary)

    alhazem = os.path.join(tenants_root, "alhazem")
    sample = os.path.join(tenants_root, "_samples", "alhazem")
    if os.path.isdir(alhazem) and not os.path.isdir(sample):
        _copy_tree(alhazem, sample)


def bootstrap_all_company_dirs(app) -> None:
    from models import Company

    root = app.root_path
    for co in Company.query.filter(Company.code.isnot(None)).all():
        ensure_company_branding_dirs(root, co.code)


def bootstrap_tenant_assets(root: str, *, force: bool = False) -> None:
    _migrate_legacy_tenants(root)
    branding = _abs(root, "static", BRANDING_REL.replace("/", os.sep))
    platform_dir = os.path.join(branding, "platform")
    primary = os.path.join(platform_dir, "logos", "primary.png")
    if os.path.isfile(primary):
        generate_derivatives(primary, platform_dir, force=force, include_white=True)

    tenants = os.path.join(branding, "tenants")
    if not os.path.isdir(tenants):
        return
    for name in os.listdir(tenants):
        if name.startswith("_") or name in ("alhazem", "nasrallah", "ramallah"):
            continue
        tenant_path = os.path.join(tenants, name)
        if not os.path.isdir(tenant_path):
            continue
        primary = os.path.join(tenant_path, "logos", "primary.png")
        if os.path.isfile(primary):
            generate_derivatives(primary, tenant_path, force=force, include_white=False)


def sync_branding_settings(app) -> dict[str, str]:
    from extensions import db
    from models import Company, SystemSettings

    root = app.root_path
    bootstrap_all_company_dirs(app)
    bootstrap_tenant_assets(root, force=False)

    updates: dict[str, str] = {}
    platform_map = {
        "platform_logo": PLATFORM["logo"],
        "platform_logo_emblem": PLATFORM["emblem"],
        "platform_logo_white": PLATFORM["white"],
        "platform_favicon": PLATFORM["favicon"],
    }
    for key, rel in platform_map.items():
        static_val = f"static/{rel}"
        if os.path.isfile(_abs(root, static_val)):
            SystemSettings.set_setting(key, static_val, data_type="string", commit=False)
            updates[key] = static_val

    for co in Company.query.filter(Company.code.isnot(None)).all():
        slug = tenant_slug_for_code(co.code)
        if not slug:
            continue
        keys = company_setting_keys(co.code)
        for asset_key, setting_key in keys.items():
            rel = tenant_rel_path(slug, asset_key)
            static_val = f"static/{rel}"
            if os.path.isfile(_abs(root, static_val)):
                SystemSettings.set_setting(setting_key, static_val, data_type="string", commit=False)
                updates[setting_key] = static_val

    default_co = Company.query.filter_by(code="PHE").first() or Company.query.order_by(Company.id).first()
    if default_co:
        slug = tenant_slug_for_code(default_co.code)
        if slug:
            for asset_key, custom_key in (
                ("logo", "custom_logo"),
                ("emblem", "custom_logo_emblem"),
                ("white", "custom_logo_white"),
                ("favicon", "custom_favicon"),
            ):
                rel = tenant_rel_path(slug, asset_key)
                static_val = f"static/{rel}"
                if os.path.isfile(_abs(root, static_val)):
                    SystemSettings.set_setting(custom_key, static_val, data_type="string", commit=False)
                    updates[custom_key] = static_val

    db.session.commit()
    return updates


def save_tenant_logo_upload(
    root: str,
    company_code: str,
    logo_type: str,
    source_path: str,
    *,
    regenerate: bool = True,
) -> tuple[str, str] | None:
    """يحفظ ملف شعار في مجلد الشركة ويُرجع (static_path, setting_key)."""
    slug = tenant_slug_for_code(company_code)
    if not slug:
        return None
    mapping = LOGO_UPLOAD_MAP.get(logo_type)
    if not mapping:
        return None
    asset_key, subpath = mapping
    ensure_company_branding_dirs(root, company_code)
    dest = os.path.join(tenant_dir(root, slug), *subpath.split("/"))
    _ensure_dir(os.path.dirname(dest))
    shutil.copy2(source_path, dest)

    if regenerate and logo_type == "main" and os.path.isfile(dest):
        generate_derivatives(dest, tenant_dir(root, slug), force=True, include_white=True)

    setting_key = company_setting_keys(company_code)[asset_key]
    static_path = tenant_static_path(slug, asset_key)
    return static_path, setting_key


def register_company_branding_hooks(app) -> None:
    from sqlalchemy import event
    from models import Company

    @event.listens_for(Company, "after_insert")
    def _company_branding_dir(mapper, connection, target):
        try:
            ensure_company_branding_dirs(app.root_path, target.code or "")
        except Exception:
            pass

    with app.app_context():
        try:
            bootstrap_all_company_dirs(app)
        except Exception:
            pass


def register_branding_cli(app) -> None:
    import click
    from extensions import db

    @app.cli.group("branding")
    def branding_cli():
        """إدارة أصول الهوية البصرية."""

    @branding_cli.command("generate-missing")
    @click.option("--force", is_flag=True, help="إعادة توليد كل المشتقات")
    @with_appcontext
    def generate_missing(force: bool):
        bootstrap_tenant_assets(app.root_path, force=force)
        click.echo("Done: branding derivatives generated.")

    @branding_cli.command("sync-files")
    @with_appcontext
    def sync_files():
        updates = sync_branding_settings(app)
        click.echo(f"Synced {len(updates)} setting(s).")
