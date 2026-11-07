"""مجاميع التوزيع اليدوي على المستندات."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func


def sum_allocations(entity_type: str, entity_id: int, session=None) -> Decimal:
    from extensions import db
    from models import PaymentAllocation

    sess = session or db.session
    total = (
        sess.query(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .filter(
            PaymentAllocation.entity_type == entity_type.upper(),
            PaymentAllocation.entity_id == int(entity_id),
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def recompute_sale_after_allocations(sale_id: int, session=None) -> None:
    """تحديث total_paid/balance_due مع احتساب PaymentAllocation (دون ربط sale_id على الدفعة)."""
    from extensions import db
    from models import Sale, Payment, PaymentStatus, PaymentDirection, convert_amount, DEFAULT_CURRENCY
    from decimal import ROUND_HALF_UP

    sess = session or db.session
    sale = sess.get(Sale, int(sale_id))
    if not sale:
        return
    Q = Decimal("0.01")
    paid = Decimal("0.00")
    sale_curr = (getattr(sale, "currency", None) or DEFAULT_CURRENCY).upper()
    for p in sale.payments or []:
        if getattr(p, "status", None) != PaymentStatus.COMPLETED.value:
            continue
        if getattr(p, "direction", None) != PaymentDirection.IN.value:
            continue
        amt = Decimal(str(getattr(p, "total_amount", 0) or 0))
        cur = (getattr(p, "currency", None) or sale_curr).upper()
        if cur != sale_curr:
            try:
                amt = Decimal(str(convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None))))
            except Exception:
                pass
        paid += amt
    paid += sum_allocations("SALE", sale.id, sess)
    total = Decimal(str(sale.total_amount or 0))
    sale.total_paid = float(paid.quantize(Q, rounding=ROUND_HALF_UP))
    sale.balance_due = float((total - paid).quantize(Q, rounding=ROUND_HALF_UP))
    if hasattr(sale, "update_payment_status"):
        try:
            sale.update_payment_status()
        except Exception:
            pass
    sess.add(sale)


def recompute_allocations_for_payment(payment_id: int) -> None:
    from models import PaymentAllocation

    rows = PaymentAllocation.query.filter_by(payment_id=payment_id).all()
    seen_sale = set()
    seen_inv = set()
    for row in rows:
        et = (row.entity_type or "").upper()
        if et == "SALE" and row.entity_id not in seen_sale:
            seen_sale.add(row.entity_id)
            recompute_sale_after_allocations(row.entity_id)
        elif et == "INVOICE" and row.entity_id not in seen_inv:
            seen_inv.add(row.entity_id)
