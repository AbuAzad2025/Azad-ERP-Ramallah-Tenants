"""
مصدر موحّد لأسعار الصرف.

قواعد العمل:
- المعاملات المسجّلة: fx_rate_used يُحفظ عند الإنشاء ولا يُعاد حسابه يومياً.
- الحسابات/التحويلات الجديدة: سعر **يوم تاريخ الحركة** (معامل at).
- النافبار: سعر **اليوم** للعرض فقط.

عند تعذّر الأونلاين (معطّل أو فشل الجلب): يدوي من exchange_rates، ثم آخر سعر مسجّل في DB (بدون جلب حي).
عند تفعيل الأونلاين: محاولة أونلاين أولاً للنافبار ولليوم الحالي فقط في الحسابات.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_MANUAL_SOURCES = frozenset({None, "", "Manual", "manual", "يدوي"})


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _pack(
    rate: float,
    source: str,
    base: str,
    quote: str,
    at: datetime,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    return {
        "rate": round(float(rate), 6) if rate else None,
        "source": source,
        "base": base,
        "quote": quote,
        "timestamp": at,
        "success": True,
        "provider": provider,
    }


def _fail(base: str, quote: str, at: datetime) -> dict[str, Any]:
    return {
        "rate": None,
        "source": "unavailable",
        "base": base,
        "quote": quote,
        "timestamp": at,
        "success": False,
        "provider": None,
        "message_ar": (
            f"سعر الصرف غير متوفر لـ {base}/{quote}. "
            "أدخل سعراً يدوياً لتاريخ الحركة أو فعّل الأونلاين من إعدادات العملات."
        ),
    }


FX_UPDATE_INTERVAL_MIN = 300
FX_UPDATE_INTERVAL_MAX = 86400
FX_UPDATE_INTERVAL_DEFAULT = 3600


def get_fx_update_interval_seconds() -> int:
    """فترة تحديث نافبار FX وكاش /api/exchange-rates (من system_settings)."""
    try:
        from models import SystemSettings

        raw = SystemSettings.get_setting("fx_update_interval", FX_UPDATE_INTERVAL_DEFAULT)
        seconds = int(raw)
    except (TypeError, ValueError):
        seconds = FX_UPDATE_INTERVAL_DEFAULT
    return max(FX_UPDATE_INTERVAL_MIN, min(FX_UPDATE_INTERVAL_MAX, seconds))


def clear_fx_navbar_api_cache(app=None) -> None:
    """إبطال كاش أسعار النافبار بعد تغيير الإعدادات."""
    try:
        from flask import current_app

        flask_app = app or current_app
        flask_app.config.pop("_exchange_rates_cache_v4", None)
        flask_app.config.pop("_exchange_rates_cache_v4_time", None)
    except Exception:
        pass


def is_online_fx_enabled() -> bool:
    try:
        from models import SystemSettings

        v = SystemSettings.get_setting("online_fx_enabled", True)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        return bool(v)
    except Exception:
        return True


def _is_manual_source(source: Any) -> bool:
    if source is None:
        return True
    s = str(source).strip()
    if s == "External API":
        return False
    if s.lower() in ("manual", "يدوي", "local"):
        return True
    return s != "External API"


def _calendar_day_bounds(at: datetime) -> tuple[datetime, datetime]:
    start = at.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start, end


def _is_same_calendar_day(a: datetime, b: datetime) -> bool:
    return a.date() == b.date()


def _manual_for_calendar_day(
    base: str, quote: str, at: datetime
) -> Optional[tuple[float, str]]:
    """سعر يدوي مسجّل لنفس يوم التاريخ."""
    from models import ExchangeRate, db, ensure_currency

    b = ensure_currency(base)
    qv = ensure_currency(quote)
    day_start, day_end = _calendar_day_bounds(at)
    try:
        rows = (
            db.session.query(ExchangeRate.rate, ExchangeRate.source)
            .filter(
                ExchangeRate.base_code == b,
                ExchangeRate.quote_code == qv,
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from >= day_start,
                ExchangeRate.valid_from <= day_end,
            )
            .order_by(ExchangeRate.valid_from.desc())
            .all()
        )
        for rate_raw, src in rows:
            if not _is_manual_source(src):
                continue
            rate = _to_float(rate_raw)
            if rate:
                return rate, str(src or "manual")
    except Exception:
        pass
    return None


def _latest_manual_on_or_before(
    base: str, quote: str, at: datetime
) -> Optional[tuple[float, str]]:
    """آخر سعر يدوي لا يتجاوز تاريخ الحركة."""
    from models import ExchangeRate, db, ensure_currency

    b = ensure_currency(base)
    qv = ensure_currency(quote)
    try:
        rows = (
            db.session.query(ExchangeRate.rate, ExchangeRate.source)
            .filter(
                ExchangeRate.base_code == b,
                ExchangeRate.quote_code == qv,
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from <= at,
            )
            .order_by(ExchangeRate.valid_from.desc())
            .limit(50)
            .all()
        )
        for rate_raw, src in rows:
            if not _is_manual_source(src):
                continue
            rate = _to_float(rate_raw)
            if rate:
                return rate, str(src or "manual")
    except Exception:
        pass
    return None


def _latest_any_on_or_before(
    base: str, quote: str, at: datetime
) -> Optional[tuple[float, str]]:
    from models import ExchangeRate, db, ensure_currency

    b = ensure_currency(base)
    qv = ensure_currency(quote)
    try:
        row = (
            db.session.query(ExchangeRate.rate, ExchangeRate.source)
            .filter(
                ExchangeRate.base_code == b,
                ExchangeRate.quote_code == qv,
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from <= at,
            )
            .order_by(ExchangeRate.valid_from.desc())
            .first()
        )
        if row:
            rate = _to_float(row[0])
            if rate:
                src = row[1] or "database"
                label = "manual" if _is_manual_source(src) else "online_cached"
                return rate, label
    except Exception:
        pass
    return None


def _try_online_live(base: str, quote: str, at: datetime) -> Optional[dict[str, Any]]:
    from services.fx_navbar_provider import _try_investing, _try_online_chain

    inv = _try_investing(base, quote)
    if inv and inv.get("rate"):
        return inv
    online = _try_online_chain(base, quote)
    if online and online.get("rate"):
        return online
    try:
        from models import _fetch_external_fx_rate

        r = _fetch_external_fx_rate(base, quote, at)
        if r and float(r) > 0:
            return {
                "rate": round(float(r), 2),
                "source": "online",
                "provider": "external_chain",
                "success": True,
            }
    except Exception:
        pass
    return None


def resolve_fx_rate_for_date(
    base: str,
    quote: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """
    سعر لتاريخ محدد — للمدفوعات/المبيعات/التحويلات عند الإنشاء.
    لا يُستخدم لإعادة تسعير قيود قديمة (fx_rate_used محفوظ).
    """
    from models import ensure_currency

    b = ensure_currency(base)
    qv = ensure_currency(quote)
    t = at or datetime.now(timezone.utc)
    if getattr(t, "tzinfo", None) is None:
        t = t.replace(tzinfo=timezone.utc)

    if b == qv:
        return _pack(1.0, "same_currency", b, qv, t)

    manual_day = _manual_for_calendar_day(b, qv, t)
    if manual_day:
        rate, src = manual_day
        return _pack(rate, "manual", b, qv, t, provider="manual_calendar_day")

    manual_hist = _latest_manual_on_or_before(b, qv, t)
    if manual_hist:
        rate, src = manual_hist
        return _pack(rate, "manual", b, qv, t, provider="manual_historical")

    now = datetime.now(timezone.utc)
    online_on = is_online_fx_enabled()
    if online_on and _is_same_calendar_day(t, now):
        online = _try_online_live(b, qv, t)
        if online and online.get("rate"):
            online.setdefault("base", b)
            online.setdefault("quote", qv)
            online.setdefault("timestamp", t)
            online.setdefault("success", True)
            return online

    # لا جلب حي — آخر سعر مسجّل في DB (يدوي أو محفوظ سابقاً)
    cached = _latest_any_on_or_before(b, qv, t)
    if cached:
        rate, src = cached
        return _pack(rate, src, b, qv, t, provider="database_stored")

    return _fail(b, qv, t)


def resolve_navbar_fx_rate(base: str, quote: str) -> dict[str, Any]:
    """
    عرض النافبار: أونلاين إن وُجد، وإلا يدوي (بدون الاعتماد على قيم افتراضية).
    """
    from models import ensure_currency

    now = datetime.now(timezone.utc)

    if is_online_fx_enabled():
        online = _try_online_live(base, quote, now)
        if online and online.get("rate"):
            online.setdefault("base", ensure_currency(base))
            online.setdefault("quote", ensure_currency(quote))
            online.setdefault("timestamp", now)
            online.setdefault("success", True)
            return online

    return resolve_fx_rate_for_date(base, quote, now)


# توافق مع الاستدعاءات السابقة
def resolve_live_fx_rate(
    base: str,
    quote: str,
    at: datetime | None = None,
    *,
    for_navbar: bool = False,
) -> dict[str, Any]:
    if for_navbar:
        return resolve_navbar_fx_rate(base, quote)
    return resolve_fx_rate_for_date(base, quote, at)
