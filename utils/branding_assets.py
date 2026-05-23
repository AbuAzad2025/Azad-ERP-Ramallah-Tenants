"""
أصول الهوية البصرية — منصة أزاد (platform) مقابل تينانت (tenants/<slug>).

كل المسارات المخزّنة في DB نسبية من static/ بدون نطاق:
  branding/platform/logos/primary.png
  branding/tenants/nasrallah/logos/primary.png

لا تُخزَّن روابط مطلقة (https://...) في الإعدادات.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from sqlalchemy.engine.url import make_url
from werkzeug.utils import secure_filename

ALLOWED_DATABASES = frozenset({"garage_manager"})

BRANDING_ROOT = "branding"
PLATFORM_SLUG = "platform"
TENANTS_DIR = "tenants"

ASSET_LOGOS = "logos"
ASSET_FAVICONS = "favicons"
ASSET_HEADERS = "headers"
ASSET_AUTH = "auth"

LOGO_PRIMARY = "primary.png"
LOGO_EMBLEM = "emblem.png"
LOGO_WHITE = "white.png"
PLATFORM_LOGO_ALIASES = (LOGO_PRIMARY, "azad_logo.png")
LOGO_SECONDARY = "secondary.png"
FAVICON_FILE = "favicon.png"
HEADER_LETTERHEAD = "letterhead.png"
HEADER_BANNER = "banner.png"
LOGIN_BG_FILE = "login_bg.webp"
AUTH_FAVICON_ALT = "favicon_alt.png"

# مسارات قديمة → مسار نسبي جديد (لتطبيع DB والقوالب)
LEGACY_PATH_ALIASES: dict[str, str] = {
    "static/img/logo.png": f"{BRANDING_ROOT}/{TENANTS_DIR}/nasrallah/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "img/logo.png": f"{BRANDING_ROOT}/{TENANTS_DIR}/nasrallah/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "static/img/logo_main.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "img/logo_main.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "static/img/logo_emblem.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_EMBLEM}",
    "img/logo_emblem.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_EMBLEM}",
    "static/img/logo_white.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_WHITE}",
    "img/logo_white.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_WHITE}",
    "static/img/favicon.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_FAVICONS}/{FAVICON_FILE}",
    "img/favicon.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_FAVICONS}/{FAVICON_FILE}",
    "static/img/azad_logo.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "img/azad_logo.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/{LOGO_PRIMARY}",
    "static/img/azad_favicon.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/{AUTH_FAVICON_ALT}",
    "img/azad_favicon.png": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/{AUTH_FAVICON_ALT}",
    "static/img/azad_login_bg.webp": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/{LOGIN_BG_FILE}",
    "img/azad_login_bg.webp": f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/{LOGIN_BG_FILE}",
}

# ملفات مكررة في static/img — تُنقل إلى _deprecated بعد التأكد من وجود نسخة في branding
IMG_DUPLICATE_CANDIDATES = (
    "logo_main.png",
    "logo_emblem.png",
    "logo_white.png",
    "favicon.png",
    "azad_logo.png",
    "azad_logo--.png",
    "azad_favicon.png",
    "azad_login_bg.webp",
    "azad_logo_emblem.png",
    "azad_logo_white_on_dark.png",
)

IMG_AUTH_FILES = {
    "azad_login_bg.webp": (ASSET_AUTH, LOGIN_BG_FILE),
    "azad_favicon.png": (ASSET_AUTH, AUTH_FAVICON_ALT),
}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,58}$")


def assert_garage_manager_only(db_uri: str | None = None) -> str:
    uri = (db_uri or os.environ.get("DATABASE_URL") or "").strip()
    if not uri:
        raise RuntimeError("DATABASE_URL غير معرّف")
    dbname = (make_url(uri).database or "").strip().lower()
    if dbname not in ALLOWED_DATABASES:
        raise RuntimeError(f"مسموح فقط قاعدة garage_manager، وليس: {dbname}")
    return dbname


def _safe_slug(slug: str) -> str:
    s = (slug or "").strip().lower().replace(" ", "-")
    if not s or not _SLUG_RE.match(s):
        raise ValueError(f"slug غير صالح: {slug!r}")
    return s


def static_root(app=None) -> Path:
    if app is not None:
        return Path(app.static_folder or "static")
    from flask import current_app
    return Path(current_app.static_folder or "static")


def rel_path_platform(asset_type: str, filename: str) -> str:
    return f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{asset_type}/{filename}"


def rel_path_tenant(slug: str, asset_type: str, filename: str) -> str:
    return f"{BRANDING_ROOT}/{TENANTS_DIR}/{_safe_slug(slug)}/{asset_type}/{filename}"


def abs_path(app, rel: str) -> Path:
    rel = normalize_rel_path(rel)
    return static_root(app) / Path(*rel.split("/"))


def normalize_rel_path(value: str | None, *, default: str | None = None) -> str:
    s = str(value or "").strip().replace("\\", "/")
    if not s:
        return normalize_rel_path(default, default="") if default else ""
    low = s.lower()
    if low.startswith(("http://", "https://", "//")):
        return normalize_rel_path(default, default="") if default else ""
    s = s.lstrip("/")
    if s.startswith("static/"):
        s = s[len("static/") :]
    if s in LEGACY_PATH_ALIASES:
        s = LEGACY_PATH_ALIASES[s]
    parts = [p for p in s.split("/") if p and p not in {".", ".."}]
    if not parts:
        return normalize_rel_path(default, default="") if default else ""
    return "/".join(parts)


def file_exists(rel: str, app=None) -> bool:
    rel = normalize_rel_path(rel)
    if not rel:
        return False
    try:
        if app is None:
            from flask import current_app
            app = current_app
    except Exception:
        return False
    return abs_path(app, rel).is_file()


def is_tenant_request() -> bool:
    try:
        from flask import g
        return bool(getattr(g, "tenant_slug", None))
    except Exception:
        return False


def is_tenant_session_user() -> bool:
    try:
        from flask import session
        return str(session.get("_user_id") or "").startswith("t:")
    except Exception:
        return False


def is_platform_owner_user(user=None) -> bool:
    """مالك المنصة (أزاد) — ليس مالك تينант."""
    try:
        from flask import session
        if is_tenant_session_user():
            return False
        u = user
        if u is None:
            from flask_login import current_user
            u = current_user
        if not getattr(u, "is_authenticated", False):
            return False
        from permissions_config.role_policy import is_platform_owner_role

        if is_platform_owner_role(u):
            return True
        if hasattr(u, "has_permission") and u.has_permission("access_owner_dashboard"):
            return True
        return False
    except Exception:
        return False


def ensure_branding_tree(app=None, *, tenant_slugs: list[str] | None = None) -> None:
    root = static_root(app)
    dirs = [
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS,
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_FAVICONS,
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_HEADERS,
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_AUTH,
        root / "img" / "banners",
        root / "img" / "uploads",
        root / "img" / "_deprecated" / "logos",
    ]
    for slug in tenant_slugs or []:
        for kind in (ASSET_LOGOS, ASSET_FAVICONS, ASSET_HEADERS):
            dirs.append(root / BRANDING_ROOT / TENANTS_DIR / _safe_slug(slug) / kind)
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    try:
        if src.resolve() == dst.resolve():
            return dst.is_file()
    except OSError:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def ensure_legacy_img_aliases(app=None) -> list[str]:
    """مرآة favicon.ico فقط — لا ننسخ شعارات ضخمة إلى static/img."""
    root = static_root(app)
    linked: list[str] = []
    fav = abs_path(app, rel_path_platform(ASSET_FAVICONS, FAVICON_FILE))
    if fav.is_file():
        ico = root / "favicon.ico"
        try:
            needs = (not ico.is_file()) or (ico.stat().st_mtime < fav.stat().st_mtime)
        except OSError:
            needs = True
        if needs and _copy_if_exists(fav, ico):
            linked.append("favicon.ico")
    return linked


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _asset_role(rel: str) -> str:
    r = rel.replace("\\", "/").lower()
    if f"/{ASSET_LOGOS}/" in r:
        return "logo"
    if f"/{ASSET_FAVICONS}/" in r:
        return "favicon"
    if f"/{ASSET_HEADERS}/" in r:
        return "header"
    if f"/{ASSET_AUTH}/" in r:
        return "auth"
    return "other"


def _asset_keep_priority(rel: str) -> int:
    r = rel.replace("\\", "/").lower()
    if r.endswith(f"/{ASSET_LOGOS}/{LOGO_PRIMARY}"):
        return 0
    if f"/{ASSET_FAVICONS}/{FAVICON_FILE}" in r:
        return 1
    if r.endswith(f"/{ASSET_LOGOS}/{LOGO_EMBLEM}"):
        return 2
    if r.endswith(f"/{ASSET_HEADERS}/{HEADER_LETTERHEAD}"):
        return 3
    if r.endswith(f"/{ASSET_LOGOS}/{LOGO_WHITE}"):
        return 4
    if r.endswith(f"/{ASSET_AUTH}/{LOGIN_BG_FILE}"):
        return 5
    if r.endswith(f"/{ASSET_LOGOS}/{LOGO_SECONDARY}"):
        return 6
    if r.endswith(f"/{ASSET_HEADERS}/{HEADER_BANNER}"):
        return 20
    if "azad_logo" in r or r.endswith(f"/{AUTH_FAVICON_ALT}"):
        return 25
    return 10


def prune_branding_redundancy(app=None, *, dry_run: bool = False) -> dict[str, Any]:
    """
    تنظيف المكررات: نسخ img القديمة، ملفات متطابقة الحجم، بانرات غير مستخدمة، كاش القوالب.
    """
    from utils.branding_generate import cleanup_redundant_copies
    from utils.print_branding import invalidate_branding_caches

    root = static_root(app)
    report: dict[str, Any] = {
        "archived_img": [],
        "removed_files": [],
        "removed_dirs": [],
        "cache_cleared": False,
        "assets_version": None,
    }

    report["archived_img"] = archive_img_duplicates(app, dry_run=dry_run)
    if not dry_run:
        report["archived_img"].extend(cleanup_redundant_copies(app))

    branding_root = root / BRANDING_ROOT
    if branding_root.is_dir():
        by_hash: dict[str, tuple[int, str, Path]] = {}
        for f in branding_root.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(root)).replace("\\", "/")
            if rel.lower().endswith(".md"):
                continue
            try:
                digest = _file_md5(f)
            except OSError:
                continue
            pri = _asset_keep_priority(rel)
            prev = by_hash.get(digest)
            if prev is None:
                by_hash[digest] = (pri, rel, f)
                continue
            # لا نحذف أدوار مختلفة (emblem/favicon) إن كانت الملف الوحيد لهذا الدور
            if _asset_role(rel) != _asset_role(prev[1]):
                continue
            if pri < prev[0]:
                drop = prev[2]
                by_hash[digest] = (pri, rel, f)
            elif pri > prev[0]:
                drop = f
            else:
                drop = f if len(rel) >= len(prev[1]) else prev[2]
                if drop is f:
                    by_hash[digest] = (prev[0], prev[1], prev[2])
                else:
                    by_hash[digest] = (pri, rel, f)
            drop_rel = str(drop.relative_to(root)).replace("\\", "/")
            if dry_run:
                report["removed_files"].append(drop_rel)
            else:
                try:
                    drop.unlink()
                    report["removed_files"].append(drop_rel)
                except OSError:
                    pass

        for rel_banner in list(branding_root.rglob(HEADER_BANNER)):
            if not rel_banner.is_file():
                continue
            rel = str(rel_banner.relative_to(root)).replace("\\", "/")
            if dry_run:
                report["removed_files"].append(rel)
            else:
                try:
                    rel_banner.unlink()
                    report["removed_files"].append(rel)
                except OSError:
                    pass

    tenants_root = branding_root / TENANTS_DIR
    if tenants_root.is_dir():
        from models import TenantRegistry

        active = set()
        try:
            active = {r.slug for r in TenantRegistry.query.filter_by(is_active=True).all() if r.slug}
        except Exception:
            active = set()
        for slug_dir in tenants_root.iterdir():
            if not slug_dir.is_dir():
                continue
            if slug_dir.name not in active and not any(slug_dir.rglob("*")):
                rel = str(slug_dir.relative_to(root)).replace("\\", "/")
                if dry_run:
                    report["removed_dirs"].append(rel)
                else:
                    shutil.rmtree(slug_dir, ignore_errors=True)
                    report["removed_dirs"].append(rel)

    loose = root / "img"
    for name in IMG_DUPLICATE_CANDIDATES:
        p = loose / name
        if p.is_file():
            rel = f"img/{name}"
            if dry_run:
                report["removed_files"].append(rel)
            else:
                try:
                    p.unlink()
                    report["removed_files"].append(rel)
                except OSError:
                    pass

    dep_logos = loose / "_deprecated" / "logos"
    if dep_logos.is_dir():
        rel = "img/_deprecated/logos"
        if dry_run:
            for f in dep_logos.rglob("*"):
                if f.is_file():
                    report["removed_files"].append(str(f.relative_to(root)).replace("\\", "/"))
        else:
            shutil.rmtree(dep_logos, ignore_errors=True)
            report["removed_dirs"].append(rel)

    fav_alt = abs_path(app, rel_path_platform(ASSET_AUTH, AUTH_FAVICON_ALT))
    if fav_alt.is_file():
        rel = str(fav_alt.relative_to(root)).replace("\\", "/")
        if dry_run:
            report["removed_files"].append(rel)
        else:
            try:
                fav_alt.unlink()
                report["removed_files"].append(rel)
            except OSError:
                pass

    try:
        from models import SystemSettings

        db_secondary = {
            str(r.key or "")
            for r in SystemSettings.query.filter(SystemSettings.key.like("%_logo_secondary%")).all()
            if r.value
        }
    except Exception:
        db_secondary = set()
    if branding_root.is_dir():
        for sec in branding_root.rglob(LOGO_SECONDARY):
            if not sec.is_file():
                continue
            slug = ""
            parts = sec.parts
            if TENANTS_DIR in parts:
                try:
                    idx = parts.index(TENANTS_DIR)
                    slug = parts[idx + 1]
                except (ValueError, IndexError):
                    pass
            key = f"tenant_{slug}_logo_secondary" if slug else "custom_logo_secondary"
            if key in db_secondary:
                continue
            rel = str(sec.relative_to(root)).replace("\\", "/")
            if dry_run:
                report["removed_files"].append(rel)
            else:
                try:
                    sec.unlink()
                    report["removed_files"].append(rel)
                except OSError:
                    pass

    dev_artifacts = [
        root.parent / "instance" / "audit_endpoints_report.json",
    ]
    for art in dev_artifacts:
        if art.is_file():
            rel = str(art.relative_to(root.parent)).replace("\\", "/")
            if dry_run:
                report["removed_files"].append(rel)
            else:
                try:
                    art.unlink()
                    report["removed_files"].append(rel)
                except OSError:
                    pass

    if not dry_run:
        try:
            invalidate_branding_caches()
            from extensions import cache

            cache.delete("system_settings:template_settings:v1")
            report["cache_cleared"] = True
        except Exception:
            pass
        try:
            from extensions import db

            report["assets_version"] = bump_assets_version(db.session)
            db.session.flush()
        except Exception:
            pass

    return report


def _platform_logo_source_path(app=None) -> Path | None:
    root = static_root(app)
    candidates = [
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / LOGO_PRIMARY,
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / "azad_logo.png",
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_AUTH / "azad_logo.png",
        root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_AUTH / LOGO_PRIMARY,
        root / "img" / "logo_main.png",
        root / "img" / "azad_logo.png",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def ensure_branding_canonical_files(app=None) -> dict[str, Any]:
    """
    توحيد أسماء الملفات (primary/emblem/favicon) من أي صورة وضعها المستخدم.
    لا يكرر إن كان الملف القياسي موجوداً ومحدّثاً.
    """
    report: dict[str, Any] = {"platform": {}, "tenants": {}}
    src = _platform_logo_source_path(app)
    if src:
        from utils.branding_generate import (
            generate_emblem_from_logo,
            generate_favicon_from_logo,
            generate_white_logo_from_primary,
        )

        primary_rel = rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY)
        primary_p = abs_path(app, primary_rel)
        _copy_if_exists(src, primary_p)
        generate_emblem_from_logo(primary_p, abs_path(app, rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM)))
        generate_white_logo_from_primary(primary_p, abs_path(app, rel_path_platform(ASSET_LOGOS, LOGO_WHITE)))
        generate_favicon_from_logo(primary_p, abs_path(app, rel_path_platform(ASSET_FAVICONS, FAVICON_FILE)))
        report["platform"]["logo"] = primary_rel

    from models import TenantRegistry

    try:
        slugs = [r.slug for r in TenantRegistry.query.filter_by(is_active=True).all() if r.slug]
    except Exception:
        slugs = ["alhazem", "nasrallah"]

    for slug in slugs:
        slug = _safe_slug(slug)
        primary = abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, LOGO_PRIMARY))
        if not primary.is_file():
            for alt in ("azad_logo.png", LOGO_EMBLEM, LOGO_SECONDARY):
                alt_p = abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, alt))
                if alt_p.is_file():
                    _copy_if_exists(alt_p, primary)
                    break
        if primary.is_file():
            from utils.branding_generate import generate_emblem_from_logo, generate_favicon_from_logo

            generate_emblem_from_logo(primary, abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, LOGO_EMBLEM)))
            generate_favicon_from_logo(primary, abs_path(app, rel_path_tenant(slug, ASSET_FAVICONS, FAVICON_FILE)))
            report["tenants"][slug] = rel_path_tenant(slug, ASSET_LOGOS, LOGO_PRIMARY)
    return report


def wire_database_branding_paths(session, *, app=None) -> dict[str, str]:
    """ربط مفاتيح system_settings بمسارات الملفات الموجودة فعلياً."""
    from models import SystemSettings, TenantRegistry
    from utils.branding_scope import PLATFORM_DEFAULT_COMPANY_NAME, PLATFORM_DEFAULT_SYSTEM_NAME, TENANT_KNOWN_PROFILES

    changes: dict[str, str] = {}
    primary = rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY)
    if file_exists(primary, app):
        SystemSettings.set_setting("custom_logo", primary, commit=False)
        changes["custom_logo"] = primary
    if file_exists(rel_path_platform(ASSET_FAVICONS, FAVICON_FILE), app):
        SystemSettings.set_setting("custom_favicon", rel_path_platform(ASSET_FAVICONS, FAVICON_FILE), commit=False)
        changes["custom_favicon"] = rel_path_platform(ASSET_FAVICONS, FAVICON_FILE)

    polluted_system = {
        "نظام الحازم",
        "المهندس الفلسطيني للمعدات الثقيلة",
        "الحازم لقطع السيارات",
        "أزاد لإدارة الكراج",
        "نظام أزاد لإدارة الكراج",
        "أزاد ERP رم الله",
    }
    cur_sys = str(SystemSettings.get_setting("system_name", "") or "").strip()
    if not cur_sys or cur_sys in polluted_system:
        SystemSettings.set_setting("system_name", PLATFORM_DEFAULT_SYSTEM_NAME, commit=False)
        changes["system_name"] = PLATFORM_DEFAULT_SYSTEM_NAME
    cur_co = str(SystemSettings.get_setting("company_name", "") or "").strip()
    if not cur_co or cur_co in {"الحازم لقطع السيارات", "شركة الحازم للأنظمة الذكية"}:
        SystemSettings.set_setting("company_name", PLATFORM_DEFAULT_COMPANY_NAME, commit=False)
        changes["company_name"] = PLATFORM_DEFAULT_COMPANY_NAME

    for row in TenantRegistry.query.filter_by(is_active=True).all():
        slug = _safe_slug(row.slug or "")
        if not slug:
            continue
        tlogo = rel_path_tenant(slug, ASSET_LOGOS, LOGO_PRIMARY)
        if file_exists(tlogo, app):
            SystemSettings.set_setting(f"tenant_{slug}_logo", tlogo, commit=False)
            changes[f"tenant_{slug}_logo"] = tlogo
        thdr = rel_path_tenant(slug, ASSET_HEADERS, HEADER_LETTERHEAD)
        if file_exists(thdr, app):
            SystemSettings.set_setting(f"tenant_{slug}_header", thdr, commit=False)
            changes[f"tenant_{slug}_header"] = thdr
        prof = TENANT_KNOWN_PROFILES.get(slug, {})
        if prof.get("company_name"):
            SystemSettings.set_setting(f"tenant_{slug}_company_name", prof["company_name"], commit=False)
            changes[f"tenant_{slug}_company_name"] = prof["company_name"]
        if prof.get("system_name"):
            SystemSettings.set_setting(f"tenant_{slug}_system_name", prof["system_name"], commit=False)

    session.flush()
    return changes


def init_platform_from_legacy(app=None) -> dict[str, str]:
    ensure_branding_canonical_files(app)
    root = static_root(app)
    mapping = {
        rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY): [
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / LOGO_PRIMARY,
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / "azad_logo.png",
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_AUTH / "azad_logo.png",
            root / "img" / "logo_main.png",
            root / "img" / "azad_logo.png",
        ],
        rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM): [
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / LOGO_EMBLEM,
            root / "img" / "logo_emblem.png",
        ],
        rel_path_platform(ASSET_LOGOS, LOGO_WHITE): [
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_LOGOS / LOGO_WHITE,
            root / "img" / "logo_white.png",
        ],
        rel_path_platform(ASSET_FAVICONS, FAVICON_FILE): [
            root / BRANDING_ROOT / PLATFORM_SLUG / ASSET_FAVICONS / FAVICON_FILE,
            root / "img" / "favicon.png",
        ],
    }
    out: dict[str, str] = {}
    for rel, sources in mapping.items():
        dst = abs_path(app, rel)
        if dst.is_file():
            out[rel] = rel
            continue
        for src in sources:
            if _copy_if_exists(src, dst):
                out[rel] = rel
                break
    for src_name, (atype, dest) in IMG_AUTH_FILES.items():
        rel = rel_path_platform(atype, dest)
        dst = abs_path(app, rel)
        if not dst.is_file():
            _copy_if_exists(root / "img" / src_name, dst)
        if dst.is_file():
            out[rel] = rel
    fav = abs_path(app, rel_path_platform(ASSET_FAVICONS, FAVICON_FILE))
    if fav.is_file():
        _copy_if_exists(fav, root / "favicon.ico")
    return out


ALHAZEM_SOURCE_MAP = {
    "1.png": (ASSET_LOGOS, LOGO_PRIMARY),
    "2.png": (ASSET_LOGOS, LOGO_EMBLEM),
    "3.png": (ASSET_HEADERS, HEADER_LETTERHEAD),
    "4.png": (ASSET_HEADERS, HEADER_BANNER),
    "6.png": (ASSET_LOGOS, LOGO_SECONDARY),
}


def sync_tenant_from_source_folder(
    slug: str,
    source_dir: str | Path,
    *,
    app=None,
    file_map: dict[str, tuple[str, str]] | None = None,
) -> dict[str, str]:
    slug = _safe_slug(slug)
    src_root = Path(source_dir)
    if not src_root.is_dir():
        raise FileNotFoundError(f"مجلد المصدر غير موجود: {src_root}")

    file_map = file_map or ALHAZEM_SOURCE_MAP
    ensure_branding_tree(app, tenant_slugs=[slug])
    imported: dict[str, str] = {}

    for src_name, (asset_type, dest_name) in file_map.items():
        src_file = src_root / src_name
        rel = rel_path_tenant(slug, asset_type, dest_name)
        if _copy_if_exists(src_file, abs_path(app, rel)):
            imported[rel] = rel

    primary = abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, LOGO_PRIMARY))
    fav_rel = rel_path_tenant(slug, ASSET_FAVICONS, FAVICON_FILE)
    if primary.is_file():
        _copy_if_exists(primary, abs_path(app, fav_rel))
        imported[fav_rel] = fav_rel

    return imported


def archive_img_duplicates(app=None, *, dry_run: bool = False) -> list[str]:
    """نقل شعارات مكررة من static/img إلى img/_deprecated/logos."""
    root = static_root(app)
    dep = root / "img" / "_deprecated" / "logos"
    dep.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for name in IMG_DUPLICATE_CANDIDATES:
        src = root / "img" / name
        if not src.is_file():
            continue
        dst = dep / name
        if dry_run:
            moved.append(str(src.relative_to(root)))
            continue
        if dst.exists():
            src.unlink()
        else:
            shutil.move(str(src), str(dst))
        moved.append(name)
    return moved


def audit_branding_tree(app=None) -> dict[str, Any]:
    root = static_root(app)
    report: dict[str, Any] = {
        "platform_files": [],
        "tenant_files": {},
        "img_loose": [],
        "deprecated": [],
        "legacy_db_paths": [],
    }
    plat = root / BRANDING_ROOT / PLATFORM_SLUG
    if plat.is_dir():
        for f in plat.rglob("*"):
            if f.is_file():
                report["platform_files"].append(str(f.relative_to(root)).replace("\\", "/"))
    tenants_root = root / BRANDING_ROOT / TENANTS_DIR
    if tenants_root.is_dir():
        for slug_dir in tenants_root.iterdir():
            if slug_dir.is_dir():
                report["tenant_files"][slug_dir.name] = [
                    str(f.relative_to(root)).replace("\\", "/")
                    for f in slug_dir.rglob("*")
                    if f.is_file()
                ]
    img = root / "img"
    if img.is_dir():
        for f in img.iterdir():
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".webp", ".ico"}:
                report["img_loose"].append(f.name)
    dep = root / "img" / "_deprecated"
    if dep.is_dir():
        for f in dep.rglob("*"):
            if f.is_file():
                report["deprecated"].append(str(f.relative_to(root)).replace("\\", "/"))
    return report


def normalize_branding_settings(session) -> int:
    """تطبيع مسارات الإعدادات القديمة إلى branding/..."""
    from models import SystemSettings

    branding_keys = (
        "custom_logo",
        "custom_logo_emblem",
        "custom_logo_white",
        "custom_favicon",
    )
    count = 0
    for key in branding_keys:
        row = SystemSettings.query.filter_by(key=key).first()
        if not row or not row.value:
            continue
        new_val = normalize_rel_path(row.value)
        if new_val and new_val != str(row.value).strip():
            row.value = new_val
            count += 1
    for row in SystemSettings.query.filter(SystemSettings.key.like("tenant\\_%")).all():
        k = str(row.key or "")
        if not row.value:
            continue
        if k.endswith(("_logo", "_favicon", "_header", "_banner", "_logo_emblem", "_logo_white")):
            new_val = normalize_rel_path(row.value)
            if new_val and new_val != str(row.value).strip():
                row.value = new_val
                count += 1
    session.flush()
    return count


def bump_assets_version(session=None) -> int:
    from models import SystemSettings

    v = int(time.time())
    SystemSettings.set_setting("assets_version", v, data_type="number", commit=False)
    if session is not None:
        session.flush()
    else:
        try:
            from extensions import db
            db.session.commit()
        except Exception:
            pass
    return v


ALLOWED_BRANDING_UPLOAD_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})


def save_branding_upload(
    *,
    slug: str | None,
    asset_type: str,
    target_filename: str,
    file_storage,
    app=None,
) -> str:
    """حفظ ملف هوية (منصة أو تينانت) وإرجاع المسار النسبي."""
    import os

    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("لم يُرفع ملف")
    safe = secure_filename(file_storage.filename)
    ext = os.path.splitext(safe)[1].lower()
    if ext not in ALLOWED_BRANDING_UPLOAD_EXT:
        raise ValueError("نوع الملف غير مدعوم")
    name = (target_filename or safe).strip()
    if not os.path.splitext(name)[1]:
        name = f"{name}{ext}"
    if slug:
        rel = rel_path_tenant(slug, asset_type, name)
    else:
        rel = rel_path_platform(asset_type, name)
    dest = abs_path(app, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    file_storage.save(str(dest))
    return normalize_rel_path(rel)


def apply_platform_settings(session, paths: dict[str, str] | None = None) -> None:
    from models import SystemSettings
    from utils.branding_scope import PLATFORM_DEFAULT_COMPANY_NAME, PLATFORM_DEFAULT_SYSTEM_NAME

    defaults = {
        "custom_logo": rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY),
        "custom_logo_emblem": rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM),
        "custom_logo_white": rel_path_platform(ASSET_LOGOS, LOGO_WHITE),
        "custom_favicon": rel_path_platform(ASSET_FAVICONS, FAVICON_FILE),
    }
    for key, fallback in defaults.items():
        val = (paths or {}).get(fallback) or fallback
        row = SystemSettings.query.filter_by(key=key).first()
        if not row:
            row = SystemSettings(key=key, data_type="string")
            session.add(row)
        row.value = str(val)
        row.data_type = "string"
    SystemSettings.set_setting("multi_tenancy_enabled", True, data_type="boolean", commit=False)
    if not SystemSettings.query.filter_by(key="system_name").first():
        SystemSettings.set_setting(
            "system_name", PLATFORM_DEFAULT_SYSTEM_NAME, description="اسم المنصة (أزاد)", commit=False
        )
    if not SystemSettings.query.filter_by(key="company_name").first():
        SystemSettings.set_setting(
            "company_name", PLATFORM_DEFAULT_COMPANY_NAME, description="مالك المنصة (أزاد)", commit=False
        )
    session.flush()


def repair_platform_identity_settings(session) -> dict[str, str]:
    """تصحيح أسماء المنصة إذا خُلِطت مع تينانت أو نصوص «إدارة الكراج»."""
    from models import SystemSettings
    from utils.branding_scope import PLATFORM_DEFAULT_COMPANY_NAME, PLATFORM_DEFAULT_SYSTEM_NAME

    polluted_system = {
        "نظام الحازم",
        "المهندس الفلسطيني للمعدات الثقيلة",
        "الحازم لقطع السيارات",
        "أزاد لإدارة الكراج",
        "نظام أزاد لإدارة الكراج",
        "نظام أزاد لإدارة الكراج والمحاسبة",
        "نظام إدارة الكراج",
        "أزاد ERP رم الله",
    }
    polluted_company = {
        "شركة الحازم للأنظمة الذكية",
        "الحازم لقطع السيارات",
        "شركة أزاد للأنظمة الذكية — رم الله",
    }
    changed: dict[str, str] = {}
    row = SystemSettings.query.filter_by(key="system_name").first()
    cur = str((row.value if row else "") or "").strip()
    if not cur or cur in polluted_system:
        SystemSettings.set_setting("system_name", PLATFORM_DEFAULT_SYSTEM_NAME, commit=False)
        changed["system_name"] = PLATFORM_DEFAULT_SYSTEM_NAME
    row = SystemSettings.query.filter_by(key="company_name").first()
    cur = str((row.value if row else "") or "").strip()
    if not cur or cur in polluted_company:
        SystemSettings.set_setting("company_name", PLATFORM_DEFAULT_COMPANY_NAME, commit=False)
        changed["company_name"] = PLATFORM_DEFAULT_COMPANY_NAME
    if changed:
        session.flush()
    return changed


def apply_tenant_settings(
    session,
    slug: str,
    *,
    app=None,
    company_name: str | None = None,
    system_name: str | None = None,
    domain: str | None = None,
    imported: dict[str, str] | None = None,
) -> None:
    from models import SystemSettings

    slug = _safe_slug(slug)
    imported = imported or {}

    def _pick(asset_type: str, filename: str, setting_suffix: str) -> None:
        rel = rel_path_tenant(slug, asset_type, filename)
        if rel in imported or file_exists(rel, app):
            SystemSettings.set_setting(f"tenant_{slug}_{setting_suffix}", rel, data_type="string", commit=False)

    _pick(ASSET_LOGOS, LOGO_PRIMARY, "logo")
    _pick(ASSET_LOGOS, LOGO_EMBLEM, "logo_emblem")
    _pick(ASSET_LOGOS, LOGO_WHITE, "logo_white")
    _pick(ASSET_FAVICONS, FAVICON_FILE, "favicon")
    _pick(ASSET_HEADERS, HEADER_LETTERHEAD, "header")
    _pick(ASSET_HEADERS, HEADER_BANNER, "banner")

    if company_name:
        SystemSettings.set_setting(f"tenant_{slug}_company_name", company_name, commit=False)
    if system_name:
        SystemSettings.set_setting(f"tenant_{slug}_system_name", system_name, commit=False)
    if domain:
        SystemSettings.set_setting(f"tenant_{slug}_domain", domain.lower(), commit=False)
    session.flush()


def build_static_url(rel: str, *, assets_version: str = "") -> str:
    from flask import url_for

    rel = normalize_rel_path(rel)
    if not rel:
        return ""
    url = url_for("static", filename=rel)
    v = str(assets_version or "").strip()
    if v:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}v={v}"
    return url


def _resolve_emblem_rel(
    *,
    slug: str,
    logo_rel: str,
    raw: dict,
    app=None,
) -> str:
    """شعار واجهة مضغوط — emblem أولاً، ثم favicon، وليس primary (بطاقة عمل كاملة)."""
    candidates: list[str] = []
    if slug and slug != PLATFORM_SLUG:
        candidates.append(normalize_rel_path(raw.get(f"tenant_{slug}_logo_emblem") or ""))
        try:
            from models import SystemSettings

            candidates.append(
                normalize_rel_path(SystemSettings.get_setting(f"tenant_{slug}_logo_emblem", "") or "")
            )
        except Exception:
            pass
        if logo_rel:
            base = logo_rel.rsplit("/", 1)[0]
            candidates.append(normalize_rel_path(f"{base}/{LOGO_EMBLEM}"))
    else:
        candidates.append(normalize_rel_path(raw.get("custom_logo_emblem") or ""))
        candidates.append(rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM))
    for rel in candidates:
        if rel and file_exists(rel, app):
            return rel
    return ""


def _resolve_ui_logo_rel(
    *,
    slug: str,
    logo_rel: str,
    favicon_rel: str,
    raw: dict,
    app=None,
) -> str:
    emblem = _resolve_emblem_rel(slug=slug, logo_rel=logo_rel, raw=raw, app=app)
    if emblem:
        return emblem
    if favicon_rel and file_exists(favicon_rel, app):
        return favicon_rel
    return logo_rel


def resolve_active_branding(
    *,
    tenant_slug: str | None = None,
    raw_settings: dict | None = None,
    assets_version: str = "",
    app=None,
) -> dict[str, Any]:
    raw = raw_settings or {}
    platform_logo = normalize_rel_path(
        raw.get("custom_logo"), default=rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY)
    )
    platform_favicon = normalize_rel_path(
        raw.get("custom_favicon"), default=rel_path_platform(ASSET_FAVICONS, FAVICON_FILE)
    )
    platform_header = normalize_rel_path(raw.get("platform_header") or "")
    if not platform_header or not file_exists(platform_header, app):
        platform_header = rel_path_platform(ASSET_HEADERS, HEADER_LETTERHEAD)

    logo_rel = platform_logo
    favicon_rel = platform_favicon
    header_rel = platform_header if file_exists(platform_header, app) else ""

    slug = (tenant_slug or "").strip().lower()
    if slug and slug != PLATFORM_SLUG:
        try:
            from models import SystemSettings
        except Exception:
            SystemSettings = None
        t_logo = normalize_rel_path(raw.get(f"tenant_{slug}_logo") or "")
        t_fav = normalize_rel_path(raw.get(f"tenant_{slug}_favicon") or "")
        t_hdr = normalize_rel_path(raw.get(f"tenant_{slug}_header") or "")
        if SystemSettings:
            if not t_logo:
                t_logo = normalize_rel_path(SystemSettings.get_setting(f"tenant_{slug}_logo", "") or "")
            if not t_fav:
                t_fav = normalize_rel_path(SystemSettings.get_setting(f"tenant_{slug}_favicon", "") or "")
            if not t_hdr:
                t_hdr = normalize_rel_path(SystemSettings.get_setting(f"tenant_{slug}_header", "") or "")
        if t_logo and file_exists(t_logo, app):
            logo_rel = t_logo
        if t_fav and file_exists(t_fav, app):
            favicon_rel = t_fav
        if t_hdr and file_exists(t_hdr, app):
            header_rel = t_hdr

    from utils.branding_scope import SCOPE_PLATFORM, SCOPE_TENANT

    emblem_rel = _resolve_emblem_rel(slug=slug, logo_rel=logo_rel, raw=raw, app=app)
    ui_logo_rel = _resolve_ui_logo_rel(
        slug=slug, logo_rel=logo_rel, favicon_rel=favicon_rel, raw=raw, app=app
    )

    # النطاق يُحدَّد من سياق الطلب (slug التينانت)، وليس بمقارنة مسار الشعار
    scope = SCOPE_TENANT if slug else SCOPE_PLATFORM
    return {
        "scope": scope,
        "tenant_slug": slug or None,
        "logo_rel": logo_rel,
        "logo_emblem_rel": emblem_rel,
        "logo_ui_rel": ui_logo_rel,
        "favicon_rel": favicon_rel,
        "header_rel": header_rel,
        "logo_url": build_static_url(ui_logo_rel, assets_version=assets_version),
        "logo_primary_url": build_static_url(logo_rel, assets_version=assets_version),
        "logo_emblem_url": build_static_url(emblem_rel, assets_version=assets_version) if emblem_rel else "",
        "favicon_url": build_static_url(favicon_rel, assets_version=assets_version),
        "header_url": build_static_url(header_rel, assets_version=assets_version) if header_rel else "",
        "platform_logo_url": build_static_url(platform_logo, assets_version=assets_version),
        "login_bg_rel": rel_path_platform(ASSET_AUTH, LOGIN_BG_FILE),
        "login_bg_url": build_static_url(rel_path_platform(ASSET_AUTH, LOGIN_BG_FILE), assets_version=assets_version),
    }


def seed_saas_platform_defaults(session) -> None:
    from models import SaaSPlan

    if SaaSPlan.query.count() > 0:
        return
    plans = [
        SaaSPlan(
            name="أساسي",
            description="للمحلات الصغيرة",
            price_monthly=49,
            price_yearly=490,
            currency="ILS",
            max_users=3,
            max_invoices=500,
            storage_gb=5,
            is_active=True,
            sort_order=1,
        ),
        SaaSPlan(
            name="احترافي",
            description="لورش ومحلات متوسطة",
            price_monthly=99,
            price_yearly=990,
            currency="ILS",
            max_users=10,
            max_invoices=5000,
            storage_gb=20,
            is_active=True,
            is_popular=True,
            sort_order=2,
        ),
        SaaSPlan(
            name="مؤسسات",
            description="فروع متعددة وتينانت",
            price_monthly=199,
            price_yearly=1990,
            currency="ILS",
            max_users=50,
            storage_gb=100,
            is_active=True,
            sort_order=3,
        ),
    ]
    for p in plans:
        session.add(p)
    session.flush()


def reorganize_and_wire(session, *, app=None, archive_dupes: bool = True) -> dict:
    """تنظيم الملفات + تطبيع الإعدادات + ربط المنصة والتينانتات."""
    from flask import current_app
    from models import TenantRegistry

    app = app or current_app._get_current_object()
    slugs = [r.slug for r in TenantRegistry.query.filter_by(is_active=True).all() if r.slug]
    ensure_branding_tree(app, tenant_slugs=slugs)
    ensure_branding_canonical_files(app)
    platform_paths = init_platform_from_legacy(app)
    wire_database_branding_paths(session, app=app)
    moved = archive_img_duplicates(app) if archive_dupes else []
    normalized = normalize_branding_settings(session)
    apply_platform_settings(session, platform_paths)
    for row in TenantRegistry.query.all():
        if not row.slug or row.schema_name == "public":
            continue
        apply_tenant_settings(session, row.slug, app=app, company_name=row.display_name)
    bump_assets_version(session)
    return {
        "platform": platform_paths,
        "archived_duplicates": moved,
        "settings_normalized": normalized,
        "audit": audit_branding_tree(app),
    }


def bootstrap_dev_branding(session, *, alhazem_source: str | Path | None = None, app=None) -> dict:
    from flask import current_app

    app = app or current_app._get_current_object()
    report = reorganize_and_wire(session, app=app, archive_dupes=False)

    src = alhazem_source or os.environ.get("ALHAZEM_BRANDING_SOURCE", r"C:\Users\azad1\OneDrive\Desktop\انس")
    if Path(src).is_dir():
        imp = sync_tenant_from_source_folder("alhazem", src, app=app)
        from utils.branding_scope import TENANT_KNOWN_PROFILES

        prof = TENANT_KNOWN_PROFILES.get("alhazem", {})
        apply_tenant_settings(
            session,
            "alhazem",
            app=app,
            company_name=prof.get("company_name", "شركة الحازم لقطع السيارات"),
            system_name=prof.get("system_name", "نظام الحازم"),
            domain="alhazem.local",
            imported=imp,
        )
        report.setdefault("tenants", {})["alhazem"] = imp

    seed_saas_platform_defaults(session)
    repair_platform_identity_settings(session)

    nasr_legacy = static_root(app) / "img" / "logo.png"
    if nasr_legacy.is_file():
        imp_n = sync_tenant_from_source_folder(
            "nasrallah",
            nasr_legacy.parent,
            app=app,
            file_map={"logo.png": (ASSET_LOGOS, LOGO_PRIMARY)},
        )
        try:
            nasr_legacy.unlink()
        except Exception:
            pass
    else:
        imp_n = {}
        if file_exists(rel_path_tenant("nasrallah", ASSET_LOGOS, LOGO_PRIMARY), app):
            imp_n[rel_path_tenant("nasrallah", ASSET_LOGOS, LOGO_PRIMARY)] = rel_path_tenant(
                "nasrallah", ASSET_LOGOS, LOGO_PRIMARY
            )
    if imp_n:
        from utils.branding_scope import TENANT_KNOWN_PROFILES

        prof = TENANT_KNOWN_PROFILES.get("nasrallah", {})
        apply_tenant_settings(
            session,
            "nasrallah",
            app=app,
            company_name=prof.get("company_name", "شركة المهندس الفلسطيني للمعدات الثقيلة"),
            system_name=prof.get("system_name", "نظام المهندس الفلسطيني"),
            domain="nasrallah.local",
            imported=imp_n,
        )
        report.setdefault("tenants", {})["nasrallah"] = imp_n

    bump_assets_version(session)
    return report


def ensure_tenant_registry_row(session, *, slug: str, schema_name: str, display_name: str, domain: str | None = None):
    from models import TenantRegistry

    row = TenantRegistry.query.filter_by(slug=slug).first()
    if not row:
        row = TenantRegistry(slug=slug)
        session.add(row)
    row.schema_name = schema_name
    row.display_name = display_name
    row.domain = domain
    row.is_active = True
    session.flush()
    return row
