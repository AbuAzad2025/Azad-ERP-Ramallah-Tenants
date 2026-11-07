"""توزيع يدوي للدفعات على مستندات — لا يُستبدل بالسياسة الافتراضية (دفعة على الزبون)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from extensions import db
from models import Payment, PaymentAllocation, Sale, Invoice, ServiceRequest, PreOrder, PaymentStatus, PaymentDirection


def list_open_documents_for_customer(customer_id: int) -> List[Dict[str, Any]]:
    """مستندات مفتوحة يمكن توزيع دفعة عليها (للعرض فقط)."""
    out: List[Dict[str, Any]] = []
    for s in Sale.query.filter(
        Sale.customer_id == customer_id,
        Sale.status == "CONFIRMED",
    ).order_by(Sale.sale_date.desc()).limit(100).all():
        due = Decimal(str(getattr(s, "balance_due", 0) or getattr(s, "total_amount", 0) or 0))
        if due > Decimal("0.01"):
            out.append({
                "entity_type": "SALE",
                "entity_id": s.id,
                "ref": getattr(s, "sale_number", None) or f"SALE-{s.id}",
                "date": s.sale_date.isoformat() if s.sale_date else None,
                "balance_due": float(due),
            })
    for inv in Invoice.query.filter(
        Invoice.customer_id == customer_id,
        Invoice.cancelled_at.is_(None),
    ).order_by(Invoice.invoice_date.desc()).limit(50).all():
        due = Decimal(str(inv.balance_due or 0))
        if due > Decimal("0.01"):
            out.append({
                "entity_type": "INVOICE",
                "entity_id": inv.id,
                "ref": getattr(inv, "invoice_number", None) or f"INV-{inv.id}",
                "date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "balance_due": float(due),
            })
    return out


def apply_manual_allocations(
    payment_id: int,
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payment = db.session.get(Payment, payment_id)
    if not payment:
        raise ValueError("الدفعة غير موجودة")
    if (payment.status or "").upper() != PaymentStatus.COMPLETED.value:
        raise ValueError("الدفعة يجب أن تكون مكتملة")
    if (payment.direction or "").upper() != PaymentDirection.IN.value:
        raise ValueError("التوزيع للدفعات الواردة فقط")

    PaymentAllocation.query.filter_by(payment_id=payment_id).delete()
    total_alloc = Decimal("0")
    for line in lines:
        et = str(line.get("entity_type", "")).upper()
        eid = int(line.get("entity_id", 0))
        amt = Decimal(str(line.get("amount", 0)))
        if amt <= 0 or not eid:
            continue
        db.session.add(
            PaymentAllocation(
                payment_id=payment_id,
                entity_type=et,
                entity_id=eid,
                amount=amt,
                currency=payment.currency or "ILS",
                notes=line.get("notes"),
            )
        )
        total_alloc += amt

    pay_total = Decimal(str(payment.total_amount or 0))
    if total_alloc > pay_total + Decimal("0.02"):
        raise ValueError("مجموع التوزيع يتجاوز مبلغ الدفعة")

    db.session.commit()
    from utils.allocation_amounts import recompute_allocations_for_payment

    recompute_allocations_for_payment(payment_id)
    db.session.commit()
    return {"success": True, "allocated": float(total_alloc), "payment_total": float(pay_total)}
