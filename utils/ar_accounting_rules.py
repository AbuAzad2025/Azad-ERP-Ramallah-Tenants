"""
قواعد محاسبة الذمم (AR) — مصدر واحد للرصيد المخزّن وكشف الحساب.
"""
from __future__ import annotations

from decimal import Decimal

# مبيعات تُحسب في الالتزام / الكشف
SALE_OBLIGATION_STATUSES = ("CONFIRMED", "COMPLETED")

# فواتير مستقلة فقط (مرتبطة ببيع/خدمة/حجز تُحسب ضمن ذلك الالتزام)
def standalone_invoice_filters():
    from models import Invoice

    return (
        Invoice.cancelled_at.is_(None),
        Invoice.sale_id.is_(None),
        Invoice.service_id.is_(None),
        Invoice.preorder_id.is_(None),
    )


# دفعات تؤثر على الرصيد المخزّن
PAYMENT_STATUSES_BALANCE = ("COMPLETED",)

# دفعات تظهر في كشف الحساب (معلّقة للعرض فقط)
PAYMENT_STATUSES_STATEMENT = (
    "COMPLETED",
    "PENDING",
    "BOUNCED",
    "FAILED",
    "REJECTED",
    "REFUNDED",
)


def payment_affects_running_balance(status: str | None) -> bool:
    s = str(getattr(status, "value", status) or "").upper()
    return s in PAYMENT_STATUSES_BALANCE


def open_preorder_net_obligation(preorder) -> Decimal:
    """ذمة الحجز المفتوح = الإجمالي − العربون المدفوع."""
    total = Decimal(str(getattr(preorder, "total_amount", 0) or 0))
    prepaid = Decimal(str(getattr(preorder, "prepaid_amount", 0) or 0))
    net = total - prepaid
    return net if net > 0 else Decimal("0.00")
