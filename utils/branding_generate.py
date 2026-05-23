"""
توليد المشتقات الناقصة من الشعار الأساسي: favicon، emblem، ترويسة، خلفية دخول.
يُبنى من صور المستخدم دون خلط هويات المنصة والتينانتات.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from utils.branding_assets import (
    ASSET_AUTH,
    ASSET_FAVICONS,
    ASSET_HEADERS,
    ASSET_LOGOS,
    BRANDING_ROOT,
    FAVICON_FILE,
    HEADER_BANNER,
    HEADER_LETTERHEAD,
    LOGIN_BG_FILE,
    LOGO_EMBLEM,
    LOGO_PRIMARY,
    LOGO_WHITE,
    PLATFORM_SLUG,
    TENANTS_DIR,
    abs_path,
    file_exists,
    rel_path_platform,
    rel_path_tenant,
    static_root,
)
from utils.branding_scope import PLATFORM_DEFAULT_COMPANY_NAME, PLATFORM_DEFAULT_SYSTEM_NAME, TENANT_KNOWN_PROFILES

# ألوان الهوية
PLATFORM_ACCENT = (30, 64, 120)
ALHAZEM_ACCENT = (0, 51, 102)
NASRALLAH_ACCENT = (34, 34, 34)


def _shape_arabic(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "tahomabd.ttf"),
                os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arialbd.ttf"),
            ]
        )
    candidates.extend(
        [
            os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "tahoma.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf"),
        ]
    )
    for p in candidates:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _open_rgba(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def _fit_height(img: Image.Image, max_h: int) -> Image.Image:
    w, h = img.size
    if h <= max_h:
        return img
    ratio = max_h / float(h)
    return img.resize((max(1, int(w * ratio)), max_h), Image.Resampling.LANCZOS)


def _fit_box(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    img = _fit_height(img, box_h)
    w, h = img.size
    if w > box_w:
        ratio = box_w / float(w)
        return img.resize((box_w, max(1, int(h * ratio))), Image.Resampling.LANCZOS)
    return img


def _paste_centered(canvas: Image.Image, sprite: Image.Image, x: int, y: int, box_w: int, box_h: int) -> None:
    sprite = _fit_box(sprite, box_w, box_h)
    sw, sh = sprite.size
    ox = x + (box_w - sw) // 2
    oy = y + (box_h - sh) // 2
    canvas.paste(sprite, (ox, oy), sprite)


def _save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode == "RGBA":
        img.save(path, "PNG", optimize=True)
    else:
        img.convert("RGB").save(path, "PNG", optimize=True)


def generate_favicon_from_logo(logo_path: Path, out_path: Path, *, size: int = 512) -> bool:
    if not logo_path.is_file():
        return False
    src = _open_rgba(logo_path)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    _paste_centered(canvas, src, 0, 0, size, size)
    _save_png(canvas, out_path)
    return True


def _extract_mark_from_logo(logo_path: Path) -> Image.Image:
    src = _open_rgba(logo_path)
    w, h = src.size
    if w > h * 2.2:
        return src.crop((0, 0, int(w * 0.38), h))
    if w > h * 1.35:
        return src.crop((0, 0, w, int(h * 0.42)))
    return src


def generate_emblem_from_logo(logo_path: Path, out_path: Path, *, max_h: int = 128) -> bool:
    if not logo_path.is_file():
        return False
    emblem = _fit_height(_extract_mark_from_logo(logo_path), max_h)
    _save_png(emblem, out_path)
    return True


def generate_white_logo_from_primary(logo_path: Path, out_path: Path) -> bool:
    """نسخة فاتحة للشريط الداكن — منطقة الشعار فقط."""
    if not logo_path.is_file():
        return False
    src = _open_rgba(logo_path)
    w, h = src.size
    if w > h * 1.2:
        src = src.crop((0, 0, w, int(h * 0.45)))
    src = _fit_height(src, 96)
    px = src.load()
    nw, nh = src.size
    out = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    opx = out.load()
    for y in range(nh):
        for x in range(nw):
            r, g, b, a = px[x, y]
            if a < 40:
                continue
            if r > 240 and g > 240 and b > 240:
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum < 235:
                opx[x, y] = (255, 255, 255, min(255, a))
    _save_png(out, out_path)
    return True


def generate_letterhead(
    logo_path: Path,
    out_path: Path,
    *,
    company_name: str,
    system_name: str = "",
    accent: tuple[int, int, int] = PLATFORM_ACCENT,
    emblem_path: Path | None = None,
    width: int = 1400,
    height: int = 200,
) -> bool:
    if not logo_path.is_file():
        return False
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    if emblem_path and emblem_path.is_file():
        mark = _open_rgba(emblem_path)
    else:
        mark = _extract_mark_from_logo(logo_path)
    _paste_centered(canvas, mark, 32, 24, 280, 152)

    tx = 340
    title_font = _font(32, bold=True)
    sub_font = _font(20)
    draw.text((tx, 54), _shape_arabic(company_name), fill=accent, font=title_font)
    if system_name:
        draw.text((tx, 104), _shape_arabic(system_name), fill=(90, 90, 90), font=sub_font)

    draw.rectangle([(32, height - 8), (width - 32, height - 4)], fill=accent)
    _save_png(canvas, out_path)
    return True


def generate_banner(
    logo_path: Path,
    out_path: Path,
    *,
    company_name: str,
    tagline: str = "",
    accent: tuple[int, int, int] = PLATFORM_ACCENT,
    emblem_path: Path | None = None,
    width: int = 1200,
    height: int = 300,
) -> bool:
    if not logo_path.is_file():
        return False
    top = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(top)
    mark = _open_rgba(emblem_path) if emblem_path and emblem_path.is_file() else _extract_mark_from_logo(logo_path)
    _paste_centered(top, mark, (width - 420) // 2, 24, 420, 140)

    title_font = _font(28, bold=True)
    company = _shape_arabic(company_name)
    tw = draw.textlength(company, font=title_font)
    draw.text(((width - tw) / 2, 178), company, fill=accent, font=title_font)
    if tagline:
        sub_font = _font(18)
        tag = _shape_arabic(tagline)
        sw = draw.textlength(tag, font=sub_font)
        draw.text(((width - sw) / 2, 218), tag, fill=(100, 100, 100), font=sub_font)

    draw.rectangle([(0, 0), (width, 6)], fill=accent)
    _save_png(top, out_path)
    return True


def generate_login_background(out_path: Path, *, width: int = 1920, height: int = 1080) -> bool:
    """خلفية دخول المنصة — تدرج هادئ بألوان أزاد."""
    base = Image.new("RGB", (width, height), (44, 62, 80))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(height):
        t = i / height
        r = int(44 + (76 - 44) * t)
        g = int(62 + (161 - 62) * t)
        b = int(80 + (175 - 80) * t)
        draw.line([(0, i), (width, i)], fill=(r, g, b, 255))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        base.save(out_path, "WEBP", quality=82, method=6)
        return True
    except Exception:
        _save_png(base, out_path.with_suffix(".png"))
        return out_path.with_suffix(".png").is_file()


def _profile(slug: str) -> dict[str, str]:
    return TENANT_KNOWN_PROFILES.get(slug, {})


def _accent_for_slug(slug: str) -> tuple[int, int, int]:
    if slug == "alhazem":
        return ALHAZEM_ACCENT
    if slug == "nasrallah":
        return NASRALLAH_ACCENT
    return PLATFORM_ACCENT


def generate_scope_assets(app=None, *, scope: str, slug: str | None = None, force: bool = False) -> dict[str, Any]:
    """توليد الملفات الناقصة لنطاق واحد."""
    created: list[str] = []
    skipped: list[str] = []

    if scope == "platform":
        logo = abs_path(app, rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY))
        emblem = abs_path(app, rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM))
        targets = [
            (rel_path_platform(ASSET_FAVICONS, FAVICON_FILE), lambda d: generate_favicon_from_logo(logo, d)),
            (rel_path_platform(ASSET_LOGOS, LOGO_EMBLEM), lambda d: generate_emblem_from_logo(logo, d)),
            (rel_path_platform(ASSET_LOGOS, LOGO_WHITE), lambda d: generate_white_logo_from_primary(logo, d)),
            (
                rel_path_platform(ASSET_HEADERS, HEADER_LETTERHEAD),
                lambda d: generate_letterhead(
                    logo,
                    d,
                    company_name=PLATFORM_DEFAULT_COMPANY_NAME,
                    system_name=PLATFORM_DEFAULT_SYSTEM_NAME,
                    accent=PLATFORM_ACCENT,
                    emblem_path=emblem,
                ),
            ),
            (
                f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/{LOGIN_BG_FILE}",
                lambda d: generate_login_background(d),
            ),
        ]
    else:
        slug = (slug or "").strip().lower()
        prof = _profile(slug)
        logo = abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, LOGO_PRIMARY))
        emblem = abs_path(app, rel_path_tenant(slug, ASSET_LOGOS, LOGO_EMBLEM))
        accent = _accent_for_slug(slug)
        company = prof.get("company_name") or slug
        system = prof.get("system_name") or ""
        targets = [
            (rel_path_tenant(slug, ASSET_FAVICONS, FAVICON_FILE), lambda d: generate_favicon_from_logo(logo, d)),
            (rel_path_tenant(slug, ASSET_LOGOS, LOGO_EMBLEM), lambda d: generate_emblem_from_logo(logo, d)),
            (
                rel_path_tenant(slug, ASSET_HEADERS, HEADER_LETTERHEAD),
                lambda d: generate_letterhead(
                    logo, d, company_name=company, system_name=system, accent=accent, emblem_path=emblem
                ),
            ),
        ]

    for rel, fn in targets:
        dst = abs_path(app, rel)
        if dst.is_file() and not force:
            skipped.append(rel)
            continue
        if fn(dst):
            created.append(rel)
    return {"scope": scope, "slug": slug, "created": created, "skipped": skipped}


def generate_all_missing_branding(app=None, *, force: bool = False) -> dict[str, Any]:
    """منصة + كل التينانتات النشطة."""
    from models import TenantRegistry

    report: dict[str, Any] = {"platform": {}, "tenants": {}}
    report["platform"] = generate_scope_assets(app, scope="platform", force=force)

    try:
        slugs = [r.slug for r in TenantRegistry.query.filter_by(is_active=True).all() if r.slug]
    except Exception:
        slugs = list(TENANT_KNOWN_PROFILES.keys())

    for slug in slugs:
        if not slug or slug.lower() == "public":
            continue
        report["tenants"][slug] = generate_scope_assets(app, scope="tenant", slug=slug, force=force)
    return report


def cleanup_redundant_copies(app=None) -> list[str]:
    """حذف نسخ azad_logo المكررة إذا primary موجود."""
    removed: list[str] = []
    root = static_root(app)
    primary = abs_path(app, rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY))
    if not primary.is_file():
        return removed
    for rel in (
        f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_LOGOS}/azad_logo.png",
        f"{BRANDING_ROOT}/{PLATFORM_SLUG}/{ASSET_AUTH}/azad_logo.png",
    ):
        p = root / rel.replace("/", os.sep)
        if p.is_file():
            try:
                p.unlink()
                removed.append(rel)
            except OSError:
                pass
    return removed
