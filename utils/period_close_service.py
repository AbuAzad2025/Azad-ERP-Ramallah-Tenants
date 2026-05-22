"""
إقفال الفترات المحاسبية — GL + لقطات ذمم + ترحيل افتتاحي سنوي.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func

from extensions import db
from utils.fiscal_calendar import (
    PERIOD_YEAR,
    generate_all_periods_for_year,
    get_fiscal_year_start_month,
    period_end_datetime,
    period_start_datetime,
)


def assert_posting_allowed(posted_at: datetime) -> None:
    """يرفع ValueError إذا كان تاريخ الترحيل داخل فترة LOCKED."""
    from models import FiscalPeriod

    if posted_at is None:
        return
    if isinstance(posted_at, datetime) and posted_at.tzinfo is not None:
        posted_at = posted_at.replace(tzinfo=None)
    d = posted_at.date() if isinstance(posted_at, datetime) else posted_at
    locked = (
        FiscalPeriod.query.filter(
            FiscalPeriod.status == "LOCKED",
            FiscalPeriod.start_date <= d,
            FiscalPeriod.end_date >= d,
        ).first()
    )
    if locked:
        raise ValueError(
            f"الفترة {locked.name_ar} ({locked.period_key}) مقفلة — لا يمكن الترحيل بتاريخ {d}"
        )


def sync_fiscal_periods(
    from_year: Optional[int] = None,
    to_year: Optional[int] = None,
    *,
    include_monthly: bool = True,
    include_quarterly: bool = True,
    include_half: bool = True,
    include_year: bool = True,
) -> Dict[str, int]:
    from models import FiscalPeriod
    from utils.tenant_fiscal_schema import ensure_fiscal_tables_for_request

    ensure_fiscal_tables_for_request()

    now = datetime.now().year
    fy_start = get_fiscal_year_start_month()
    if from_year is None:
        from_year = now - 2
    if to_year is None:
        to_year = now + 1

    created = 0
    updated = 0
    for fy in range(from_year, to_year + 1):
        for spec in generate_all_periods_for_year(
            fy,
            include_monthly=include_monthly,
            include_quarterly=include_quarterly,
            include_half=include_half,
            include_year=include_year,
            start_month=fy_start,
        ):
            row = FiscalPeriod.query.filter_by(period_key=spec.period_key).first()
            if row:
                if row.status == "OPEN":
                    row.start_date = spec.start_date
                    row.end_date = spec.end_date
                    row.name_ar = spec.name_ar
                    row.period_number = spec.period_number
                    updated += 1
                continue
            db.session.add(
                FiscalPeriod(
                    period_key=spec.period_key,
                    period_type=spec.period_type,
                    fiscal_year=spec.fiscal_year,
                    period_number=spec.period_number,
                    start_date=spec.start_date,
                    end_date=spec.end_date,
                    name_ar=spec.name_ar,
                    status="OPEN",
                )
            )
            created += 1
    db.session.commit()
    return {"created": created, "updated": updated}


def get_period_by_key(period_key: str):
    from models import FiscalPeriod
    return FiscalPeriod.query.filter_by(period_key=period_key).first()


def _period_gl_balances(period, account_prefix: str, revenue: bool) -> List[Tuple[str, Decimal]]:
    from models import GLBatch, GLEntry

    start_dt = period_start_datetime(period.start_date)
    end_dt = period_end_datetime(period.end_date)
    expr = func.sum(GLEntry.credit - GLEntry.debit) if revenue else func.sum(GLEntry.debit - GLEntry.credit)
    rows = (
        db.session.query(GLEntry.account, expr.label("balance"))
        .join(GLBatch)
        .filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLBatch.source_type != "CLOSING_ENTRY",
            GLEntry.account.like(f"{account_prefix}%"),
        )
        .group_by(GLEntry.account)
        .all()
    )
    out = []
    for acc, bal in rows:
        b = Decimal(str(bal or 0))
        if abs(b) > Decimal("0.01"):
            out.append((acc, b))
    return out


def _existing_period_close(period_id: int):
    from models import PeriodClose, FiscalPeriod

    period = db.session.get(FiscalPeriod, period_id)
    if not period:
        return None
    return (
        PeriodClose.query.filter_by(fiscal_period_id=period_id)
        .order_by(PeriodClose.id.desc())
        .first()
    )


def generate_closing_entries_for_period(period_id: int) -> Dict[str, Any]:
    from models import FiscalPeriod
    from utils.tenant_fiscal_schema import ensure_fiscal_tables_for_request

    ensure_fiscal_tables_for_request()
    period = db.session.get(FiscalPeriod, period_id)
    if not period:
        raise ValueError("الفترة غير موجودة")
    if period.status != "OPEN":
        raise ValueError(f"الفترة {period.period_key} ليست مفتوحة")

    prev_close = _existing_period_close(period_id)
    if prev_close and not prev_close.reopened_at:
        raise ValueError("تم إقفال هذه الفترة مسبقاً — أعد فتحها أولاً إن لزم")

    revenues = _period_gl_balances(period, "4", revenue=True)
    expenses = _period_gl_balances(period, "5", revenue=False)
    total_revenue = sum((b for _, b in revenues), Decimal("0"))
    total_expenses = sum((b for _, b in expenses), Decimal("0"))
    net_income = total_revenue - total_expenses

    closing_entries = []
    if revenues:
        closing_entries.append({
            "type": "close_revenue",
            "description": f"إقفال إيرادات — {period.name_ar}",
            "entries": [{"account": a, "debit": float(b), "credit": 0} for a, b in revenues]
            + [{"account": "3200_CURRENT_EARNINGS", "debit": 0, "credit": float(total_revenue)}],
            "total": float(total_revenue),
        })
    if expenses:
        closing_entries.append({
            "type": "close_expenses",
            "description": f"إقفال مصروفات — {period.name_ar}",
            "entries": [{"account": a, "debit": 0, "credit": float(b)} for a, b in expenses]
            + [{"account": "3200_CURRENT_EARNINGS", "debit": float(total_expenses), "credit": 0}],
            "total": float(total_expenses),
        })
    closing_entries.append({
        "type": "transfer_net_income",
        "description": f"نقل صافي الدخل — {period.name_ar}",
        "entries": [
            {
                "account": "3200_CURRENT_EARNINGS",
                "debit": float(net_income) if net_income > 0 else 0,
                "credit": float(-net_income) if net_income < 0 else 0,
            },
            {
                "account": "3100_RETAINED_EARNINGS",
                "debit": float(-net_income) if net_income < 0 else 0,
                "credit": float(net_income) if net_income > 0 else 0,
            },
        ],
        "total": float(abs(net_income)),
    })

    return {
        "period_id": period.id,
        "period_key": period.period_key,
        "period_end": period.end_date.isoformat(),
        "net_income": float(net_income),
        "total_revenue": float(total_revenue),
        "total_expenses": float(total_expenses),
        "closing_entries": closing_entries,
    }


def _post_gl_closing(period, entry_groups: List[dict], user_id: Optional[int]) -> List[int]:
    from models import GLBatch, GLEntry

    end_dt = period_end_datetime(period.end_date)
    batch_ids = []
    for entry_group in entry_groups:
        batch = GLBatch(
            code=f"CLOSE-{period.period_key}-{entry_group['type']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            source_type="CLOSING_ENTRY",
            source_id=period.id,
            purpose=entry_group["description"],
            memo=f"إقفال فترة {period.period_key}",
            currency="ILS",
            status="POSTED",
            posted_at=end_dt,
        )
        db.session.add(batch)
        db.session.flush()
        for line in entry_group["entries"]:
            db.session.add(
                GLEntry(
                    batch_id=batch.id,
                    account=line["account"],
                    debit=Decimal(str(line["debit"])),
                    credit=Decimal(str(line["credit"])),
                    ref=f"CLOSE-{period.period_key}",
                    currency="ILS",
                )
            )
        batch_ids.append(batch.id)
    return batch_ids


def _snapshot_entity_balances(period, period_close_id: int) -> int:
    from models import Customer, Supplier, Partner, EntityPeriodBalance
    from utils.balance_calculator import build_customer_balance_view
    from utils.supplier_balance_updater import build_supplier_balance_view
    from utils.partner_balance_updater import build_partner_balance_view

    before_dt = period_end_datetime(period.end_date)
    count = 0

    for c in Customer.query.filter(Customer.is_archived == False).all():  # noqa: E712
        view = build_customer_balance_view(c.id, db.session)
        bal = Decimal(str((view.get("balance") or {}).get("net", 0) if view.get("success") else 0))
        db.session.add(
            EntityPeriodBalance(
                period_close_id=period_close_id,
                fiscal_period_id=period.id,
                entity_type="CUSTOMER",
                entity_id=c.id,
                closing_balance=bal,
                currency=c.currency or "ILS",
            )
        )
        count += 1

    for s in Supplier.query.filter(Supplier.is_archived == False).all():  # noqa: E712
        view = build_supplier_balance_view(s.id, db.session)
        bal = Decimal(str((view.get("balance") or {}).get("net", 0) if view.get("success") else 0))
        db.session.add(
            EntityPeriodBalance(
                period_close_id=period_close_id,
                fiscal_period_id=period.id,
                entity_type="SUPPLIER",
                entity_id=s.id,
                closing_balance=bal,
                currency=s.currency or "ILS",
            )
        )
        count += 1

    for p in Partner.query.filter(Partner.is_archived == False).all():  # noqa: E712
        view = build_partner_balance_view(p.id, db.session)
        bal = Decimal(str((view.get("balance") or {}).get("net", 0) if view.get("success") else 0))
        db.session.add(
            EntityPeriodBalance(
                period_close_id=period_close_id,
                fiscal_period_id=period.id,
                entity_type="PARTNER",
                entity_id=p.id,
                closing_balance=bal,
                currency=p.currency or "ILS",
            )
        )
        count += 1
    return count


def _next_annual_period(period) -> Optional[int]:
    from models import FiscalPeriod

    if period.period_type != PERIOD_YEAR:
        return None
    nxt = FiscalPeriod.query.filter_by(
        period_type=PERIOD_YEAR,
        fiscal_year=period.fiscal_year + 1,
    ).first()
    return nxt.id if nxt else None


def carry_forward_annual_opening(period, period_close_id: int, user_id: Optional[int]) -> Dict[str, int]:
    """
    ترحيل أرصدة إقفال السنة المالية.
    افتراضياً: لقطات فقط (للكشوف) — بدون تعديل opening_balance لتجنب ازدواج مع الحركات التاريخية.
    عند تفعيل SystemSettings.annual_carry_updates_opening_balance=true يُحدَّث الرصيد الافتتاحي.
    """
    from models import (
        Customer, Supplier, Partner, EntityPeriodBalance, SystemSettings,
    )

    if period.period_type != PERIOD_YEAR:
        return {"skipped": 1, "reason": "not_annual"}

    next_period_id = _next_annual_period(period)
    if not next_period_id:
        sync_fiscal_periods(from_year=period.fiscal_year + 1, to_year=period.fiscal_year + 1)
        next_period_id = _next_annual_period(period)

    update_opening = bool(SystemSettings.get_setting("annual_carry_updates_opening_balance", False))
    applied = {"customers": 0, "suppliers": 0, "partners": 0, "snapshots": 0, "opening_updated": update_opening}
    snapshots = EntityPeriodBalance.query.filter_by(
        period_close_id=period_close_id, fiscal_period_id=period.id
    ).all()

    for snap in snapshots:
        snap.next_period_id = next_period_id
        applied["snapshots"] += 1
        if not update_opening:
            continue
        bal = float(snap.closing_balance or 0)
        if snap.entity_type == "CUSTOMER":
            ent = db.session.get(Customer, snap.entity_id)
            if ent:
                ent.opening_balance = bal
                applied["customers"] += 1
                snap.applied_to_opening = True
        elif snap.entity_type == "SUPPLIER":
            ent = db.session.get(Supplier, snap.entity_id)
            if ent:
                ent.opening_balance = bal
                applied["suppliers"] += 1
                snap.applied_to_opening = True
        elif snap.entity_type == "PARTNER":
            ent = db.session.get(Partner, snap.entity_id)
            if ent:
                ent.opening_balance = bal
                applied["partners"] += 1
                snap.applied_to_opening = True

    return applied


def close_fiscal_period(
    period_id: int,
    *,
    user_id: Optional[int] = None,
    close_scope: str = "FULL",
    post_gl: bool = True,
    carry_forward: bool = True,
    lock_period: bool = True,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    from models import FiscalPeriod, PeriodClose
    from utils.tenant_fiscal_schema import ensure_fiscal_tables_for_request

    ensure_fiscal_tables_for_request()
    period = db.session.get(FiscalPeriod, period_id)
    if not period:
        raise ValueError("الفترة غير موجودة")
    if period.status != "OPEN":
        raise ValueError("الفترة ليست مفتوحة")

    gen = generate_closing_entries_for_period(period_id)
    batch_ids: List[int] = []

    if post_gl and close_scope in ("GL_ONLY", "FULL"):
        batch_ids = _post_gl_closing(period, gen["closing_entries"], user_id)

    pc = PeriodClose(
        fiscal_period_id=period.id,
        close_scope=close_scope,
        net_income=Decimal(str(gen["net_income"])),
        total_revenue=Decimal(str(gen["total_revenue"])),
        total_expenses=Decimal(str(gen["total_expenses"])),
        gl_batch_ids=json.dumps(batch_ids),
        carry_forward_done=False,
        notes=notes,
        created_by_id=user_id,
    )
    db.session.add(pc)
    db.session.flush()

    entity_count = 0
    if close_scope == "FULL":
        entity_count = _snapshot_entity_balances(period, pc.id)

    carry_stats = {}
    if carry_forward and period.period_type == PERIOD_YEAR:
        carry_stats = carry_forward_annual_opening(period, pc.id, user_id)
        pc.carry_forward_done = True

    period.status = "LOCKED" if lock_period else "CLOSED"
    period.closed_at = datetime.now()
    period.closed_by_id = user_id

    db.session.commit()

    return {
        "success": True,
        "period_close_id": pc.id,
        "period_key": period.period_key,
        "status": period.status,
        "gl_batches": batch_ids,
        "entity_snapshots": entity_count,
        "net_income": gen["net_income"],
        "carry_forward": carry_stats,
    }


def reopen_fiscal_period(period_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    from models import FiscalPeriod, PeriodClose

    period = db.session.get(FiscalPeriod, period_id)
    if not period:
        raise ValueError("الفترة غير موجودة")

    pc = _existing_period_close(period_id)
    if pc:
        pc.reopened_at = datetime.now()
        pc.reopened_by_id = user_id

    period.status = "OPEN"
    period.closed_at = None
    period.closed_by_id = None
    db.session.commit()
    return {"success": True, "period_key": period.period_key, "status": "OPEN"}


def get_opening_balance_for_entity(
    entity_type: str,
    entity_id: int,
    period_start: date,
) -> Optional[Decimal]:
    """رصيد افتتاح الفترة من لقطة الإقفال السابقة إن وُجدت."""
    from models import EntityPeriodBalance, FiscalPeriod

    prev = (
        FiscalPeriod.query.filter(FiscalPeriod.end_date < period_start)
        .order_by(FiscalPeriod.end_date.desc())
        .first()
    )
    if not prev:
        return None
    snap = EntityPeriodBalance.query.filter_by(
        fiscal_period_id=prev.id,
        entity_type=entity_type.upper(),
        entity_id=entity_id,
    ).first()
    if snap:
        return Decimal(str(snap.closing_balance or 0))
    return None


def period_to_dict(period) -> Dict[str, Any]:
    from models import PeriodClose, GLBatch, GLEntry

    close = (
        PeriodClose.query.filter_by(fiscal_period_id=period.id)
        .order_by(PeriodClose.id.desc())
        .first()
    )
    start_dt = period_start_datetime(period.start_date)
    end_dt = period_end_datetime(period.end_date)
    batches_count = GLBatch.query.filter(
        GLBatch.status == "POSTED",
        GLBatch.posted_at >= start_dt,
        GLBatch.posted_at <= end_dt,
    ).count()
    totals = (
        db.session.query(
            func.sum(GLEntry.debit).label("total_debit"),
            func.sum(GLEntry.credit).label("total_credit"),
        )
        .join(GLBatch)
        .filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
        )
        .first()
    )
    return {
        "id": period.id,
        "period_id": period.period_key,
        "period_key": period.period_key,
        "period_type": period.period_type,
        "fiscal_year": period.fiscal_year,
        "period_number": period.period_number,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "name_ar": period.name_ar,
        "status": period.status,
        "is_closed": period.is_closed,
        "closed_at": period.closed_at.isoformat() if period.closed_at else None,
        "batches_count": batches_count,
        "total_debit": float(totals.total_debit or 0),
        "total_credit": float(totals.total_credit or 0),
        "has_close_record": close is not None and close.reopened_at is None,
        "net_income": float(close.net_income) if close and close.net_income is not None else None,
        "carry_forward_done": bool(close.carry_forward_done) if close else False,
    }
