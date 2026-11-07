"""
أسعار الشريط العلوي: أونلاين أولاً (محاولة Investing.com ثم سيرفرات مجانية)، ثم يدوي من DB.
المدى اليومي/الأسبوعي: Frankfurter (USD) + سجل exchange_rates عند التوفر.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import requests

INVESTING_CURRENCY_PATHS = {
    ("USD", "ILS"): "usd-ils",
    ("JOD", "ILS"): "jod-ils",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Referer": "https://sa.investing.com/currencies/",
}


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _round2(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), 2)


def _merge_ranges(
    spot: float,
    day_low: Optional[float],
    day_high: Optional[float],
    week_low: Optional[float],
    week_high: Optional[float],
) -> dict[str, Optional[float]]:
    dl = day_low if day_low is not None else spot
    dh = day_high if day_high is not None else spot
    wl = week_low if week_low is not None else min(dl, spot)
    wh = week_high if week_high is not None else max(dh, spot)
    return {
        "day_low": _round2(min(dl, dh, spot)),
        "day_high": _round2(max(dl, dh, spot)),
        "week_low": _round2(min(wl, wh, spot)),
        "week_high": _round2(max(wl, wh, spot)),
    }


def _try_investing(base: str, quote: str) -> Optional[dict[str, Any]]:
    """محاولة sa.investing.com — قد تُحجب من السيرفر (403)."""
    path = INVESTING_CURRENCY_PATHS.get((base.upper(), quote.upper()))
    if not path:
        return None
    try:
        url = f"https://sa.investing.com/currencies/{path}"
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=12)
        if r.status_code != 200 or len(r.text) < 500:
            return None
        text = r.text
        rate = None
        for pat in (
            r'data-test="instrument-price-last"[^>]*>([\d.,]+)',
            r'"last_last":"([\d.]+)"',
            r'"last":"([\d.]+)"',
        ):
            m = re.search(pat, text)
            if m:
                rate = _to_float(m.group(1).replace(",", ""))
                if rate:
                    break
        if not rate:
            return None
        day_low = day_high = week_low = week_high = None
        for pat_low, pat_high in (
            (r'data-test="dailyRangeLow"[^>]*>([\d.,]+)', r'data-test="dailyRangeHigh"[^>]*>([\d.,]+)'),
            (r'"dailyRangeLow":"([\d.]+)"', r'"dailyRangeHigh":"([\d.]+)"'),
        ):
            ml = re.search(pat_low, text)
            mh = re.search(pat_high, text)
            if ml and mh:
                day_low = _to_float(ml.group(1).replace(",", ""))
                day_high = _to_float(mh.group(1).replace(",", ""))
                break
        ranges = _merge_ranges(rate, day_low, day_high, week_low, week_high)
        return {
            "rate": _round2(rate),
            "source": "investing",
            "provider": "sa.investing.com",
            **ranges,
        }
    except Exception:
        return None


def _try_exchangerate_api(base: str, quote: str) -> Optional[float]:
    try:
        r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{base.upper()}", timeout=10)
        data = r.json()
        rates = data.get("rates") or {}
        return _to_float(rates.get(quote.upper()))
    except Exception:
        return None


def _try_exchangerate_host(base: str, quote: str) -> Optional[float]:
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest",
            params={"base": base.upper(), "symbols": quote.upper()},
            timeout=10,
        )
        data = r.json()
        if data.get("success") and data.get("rates"):
            return _to_float(data["rates"].get(quote.upper()))
    except Exception:
        pass
    return None


def _try_online_chain(base: str, quote: str) -> Optional[dict[str, Any]]:
    from models import _fetch_external_fx_rate

    for fn in (_try_exchangerate_api, _try_exchangerate_host):
        rate = fn(base, quote)
        if rate:
            return {
                "rate": _round2(rate),
                "source": "online",
                "provider": fn.__name__.replace("_try_", ""),
            }
    try:
        r = _fetch_external_fx_rate(base, quote, datetime.now(timezone.utc))
        if r and float(r) > 0:
            return {
                "rate": _round2(float(r)),
                "source": "online",
                "provider": "external_chain",
            }
    except Exception:
        pass
    return None


def _frankfurter_ranges(base: str, quote: str, days: int = 7) -> dict[str, Optional[float]]:
    if base.upper() != "USD" or quote.upper() != "ILS":
        return {}
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        url = f"https://api.frankfurter.app/{start.isoformat()}..{end.isoformat()}"
        r = requests.get(url, params={"from": "USD", "to": "ILS"}, timeout=12)
        if r.status_code != 200:
            return {}
        rates = []
        for row in (r.json() or {}).get("rates", {}).values():
            v = _to_float((row or {}).get("ILS"))
            if v:
                rates.append(v)
        if not rates:
            return {}
        today = rates[-1] if rates else None
        yesterday = rates[-2] if len(rates) > 1 else today
        day_vals = [x for x in (today, yesterday) if x is not None]
        return {
            "day_low": _round2(min(day_vals)),
            "day_high": _round2(max(day_vals)),
            "week_low": _round2(min(rates)),
            "week_high": _round2(max(rates)),
        }
    except Exception:
        return {}


def _db_ranges(base: str, quote: str, days: int = 7) -> dict[str, Optional[float]]:
    try:
        from models import ExchangeRate, db

        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            db.session.query(ExchangeRate.rate)
            .filter(
                ExchangeRate.base_code == base.upper(),
                ExchangeRate.quote_code == quote.upper(),
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from >= since,
            )
            .all()
        )
        vals = [_to_float(r[0]) for r in rows]
        vals = [v for v in vals if v]
        if not vals:
            return {}
        return {
            "week_low": _round2(min(vals)),
            "week_high": _round2(max(vals)),
            "day_low": _round2(vals[-1]) if vals else None,
            "day_high": _round2(vals[-1]) if vals else None,
        }
    except Exception:
        return {}


def _enrich_ranges(payload: dict[str, Any], base: str, quote: str) -> dict[str, Any]:
    spot = payload.get("rate")
    if not spot:
        return payload
    fr = _frankfurter_ranges(base, quote)
    db = _db_ranges(base, quote)
    day_low = payload.get("day_low") or fr.get("day_low") or db.get("day_low")
    day_high = payload.get("day_high") or fr.get("day_high") or db.get("day_high")
    week_low = payload.get("week_low") or fr.get("week_low") or db.get("week_low")
    week_high = payload.get("week_high") or fr.get("week_high") or db.get("week_high")
    payload.update(_merge_ranges(float(spot), day_low, day_high, week_low, week_high))
    return payload


def fetch_navbar_pair(
    base: str,
    quote: str = "ILS",
    *,
    online_enabled: bool = True,
) -> dict[str, Any]:
    """عرض النافبار — أونلاين إن مفعّل، وإلا يدوي."""
    from services.fx_resolution import resolve_fx_rate_for_date, resolve_navbar_fx_rate

    base_u, quote_u = base.upper(), quote.upper()
    if online_enabled:
        out = resolve_navbar_fx_rate(base_u, quote_u)
    else:
        out = resolve_fx_rate_for_date(base_u, quote_u)
    out["base"] = base_u
    out["quote"] = quote_u
    if out.get("rate") is not None:
        out["rate"] = _round2(_to_float(out["rate"]))
        out = _enrich_ranges(out, base_u, quote_u)
    return out


def fetch_navbar_fx_bundle(*, online_enabled: bool = True) -> dict[str, Any]:
    usd = fetch_navbar_pair("USD", "ILS", online_enabled=online_enabled)
    jod = fetch_navbar_pair("JOD", "ILS", online_enabled=online_enabled)
    return {
        "success": bool(usd.get("success") or jod.get("success")),
        "online_enabled": online_enabled,
        "USD": usd,
        "JOD": jod,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
