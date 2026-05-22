"""
تقويم مالي — سنة مالية قابلة للتخصيص وفترات شهرية / ربع سنوية / نصف سنوية / سنوية.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Tuple


PERIOD_MONTH = "MONTH"
PERIOD_QUARTER = "QUARTER"
PERIOD_HALF = "HALF"
PERIOD_YEAR = "YEAR"

PERIOD_TYPES_ORDER = (PERIOD_MONTH, PERIOD_QUARTER, PERIOD_HALF, PERIOD_YEAR)

AR_PERIOD_LABELS = {
    PERIOD_MONTH: "شهري",
    PERIOD_QUARTER: "ربع سنوي",
    PERIOD_HALF: "نصف سنوي",
    PERIOD_YEAR: "سنوي",
}


@dataclass(frozen=True)
class PeriodSpec:
    period_key: str
    period_type: str
    fiscal_year: int
    period_number: int
    start_date: date
    end_date: date
    name_ar: str


def get_fiscal_year_start_month() -> int:
    try:
        from models import SystemSettings
        m = int(SystemSettings.get_setting("fiscal_year_start_month", 1) or 1)
        return max(1, min(12, m))
    except Exception:
        return 1


def fiscal_year_for_date(d: date, start_month: Optional[int] = None) -> int:
    """السنة المالية التي ينتمي إليها التاريخ."""
    sm = start_month or get_fiscal_year_start_month()
    if d.month >= sm:
        return d.year
    return d.year - 1


def fiscal_year_bounds(fiscal_year: int, start_month: Optional[int] = None) -> Tuple[date, date]:
    sm = start_month or get_fiscal_year_start_month()
    start = date(fiscal_year, sm, 1)
    if sm == 1:
        end = date(fiscal_year, 12, 31)
    else:
        end_year = fiscal_year + 1
        end_month = sm - 1
        end = date(end_year, end_month, monthrange(end_year, end_month)[1])
    return start, end


def _month_end(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def generate_monthly_periods(fy: int, start_month: Optional[int] = None) -> List[PeriodSpec]:
    fy_start, fy_end = fiscal_year_bounds(fy, start_month)
    out: List[PeriodSpec] = []
    cur = fy_start
    n = 1
    while cur <= fy_end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        end = min(nxt - timedelta(days=1), fy_end)
        key = f"{fy}-M{cur.month:02d}"
        out.append(
            PeriodSpec(
                period_key=key,
                period_type=PERIOD_MONTH,
                fiscal_year=fy,
                period_number=n,
                start_date=cur,
                end_date=end,
                name_ar=f"شهر {cur.month:02d}/{cur.year}",
            )
        )
        cur = nxt if nxt <= fy_end else fy_end + timedelta(days=1)
        if cur > fy_end:
            break
        n += 1
    return out


def generate_quarterly_periods(fy: int, start_month: Optional[int] = None) -> List[PeriodSpec]:
    fy_start, fy_end = fiscal_year_bounds(fy, start_month)
    out: List[PeriodSpec] = []
    cur = fy_start
    for q in range(1, 5):
        if cur > fy_end:
            break
        end = min(_add_months(cur, 3) - timedelta(days=1), fy_end)
        out.append(
            PeriodSpec(
                period_key=f"{fy}-Q{q}",
                period_type=PERIOD_QUARTER,
                fiscal_year=fy,
                period_number=q,
                start_date=cur,
                end_date=end,
                name_ar=f"الربع {q} — {fy}",
            )
        )
        cur = end + timedelta(days=1)
    return out[:4]


def generate_half_year_periods(fy: int, start_month: Optional[int] = None) -> List[PeriodSpec]:
    fy_start, fy_end = fiscal_year_bounds(fy, start_month)
    mid = min(_add_months(fy_start, 6) - timedelta(days=1), fy_end)
    h2_start = mid + timedelta(days=1)
    return [
        PeriodSpec(
            period_key=f"{fy}-H1",
            period_type=PERIOD_HALF,
            fiscal_year=fy,
            period_number=1,
            start_date=fy_start,
            end_date=mid,
            name_ar=f"النصف الأول — {fy}",
        ),
        PeriodSpec(
            period_key=f"{fy}-H2",
            period_type=PERIOD_HALF,
            fiscal_year=fy,
            period_number=2,
            start_date=h2_start,
            end_date=fy_end,
            name_ar=f"النصف الثاني — {fy}",
        ),
    ]


def generate_annual_period(fy: int, start_month: Optional[int] = None) -> PeriodSpec:
    fy_start, fy_end = fiscal_year_bounds(fy, start_month)
    return PeriodSpec(
        period_key=f"{fy}-FY",
        period_type=PERIOD_YEAR,
        fiscal_year=fy,
        period_number=1,
        start_date=fy_start,
        end_date=fy_end,
        name_ar=f"السنة المالية {fy}",
    )


def generate_all_periods_for_year(
    fy: int,
    *,
    include_monthly: bool = True,
    include_quarterly: bool = True,
    include_half: bool = True,
    include_year: bool = True,
    start_month: Optional[int] = None,
) -> List[PeriodSpec]:
    specs: List[PeriodSpec] = []
    if include_year:
        specs.append(generate_annual_period(fy, start_month))
    if include_half:
        specs.extend(generate_half_year_periods(fy, start_month))
    if include_quarterly:
        specs.extend(generate_quarterly_periods(fy, start_month))
    if include_monthly:
        specs.extend(generate_monthly_periods(fy, start_month))
    return specs


def period_end_datetime(end: date) -> datetime:
    return datetime.combine(end, datetime.max.time().replace(microsecond=0))


def period_start_datetime(start: date) -> datetime:
    return datetime.combine(start, datetime.min.time())


def parse_period_key(period_key: str) -> Tuple[str, int]:
    """مثال: 2025-Q2 → (QUARTER, 2)"""
    if "-FY" in period_key:
        return PERIOD_YEAR, 1
    if "-H" in period_key:
        return PERIOD_HALF, int(period_key.split("-H")[1])
    if "-Q" in period_key:
        return PERIOD_QUARTER, int(period_key.split("-Q")[1])
    if "-M" in period_key:
        return PERIOD_MONTH, int(period_key.split("-M")[1])
    return PERIOD_MONTH, 1


def iter_fiscal_years(from_year: int, to_year: int) -> Iterable[int]:
    for y in range(from_year, to_year + 1):
        yield y
