"""ربط المبيعة بسجل الفاتورة (ذمة) وتحديث المبالغ."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from extensions import db

TWOPLACES = Decimal("0.01")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_sale_totals(sale) -> dict:
    """حساب إجمالي البيع من البنود (نفس منطق الفاتورة الضريبية)."""
    from utils import D, line_total_decimal

    subtotal = Decimal("0.00")
    for ln in sale.lines or []:
        subtotal += line_total_decimal(
            getattr(ln, "quantity", 0),
            getattr(ln, "unit_price", 0),
            getattr(ln, "discount_rate", 0),
        )
    sale_discount = D(getattr(sale, "discount_total", 0))
    sale_shipping = D(getattr(sale, "shipping_cost", 0))
    sale_tax_rate = D(getattr(sale, "tax_rate", 0))
    subtotal_after_discount = (subtotal - sale_discount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    base_for_tax = (subtotal_after_discount + sale_shipping).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    tax_amount = (base_for_tax * sale_tax_rate / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    grand_total = (base_for_tax + tax_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return {
        "subtotal": subtotal,
        "discount_total": sale_discount,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
    }


def ensure_invoice_for_sale(sale, *, commit: bool = False):
    """
    إنشاء أو تحديث سجل Invoice مرتبط بالمبيعة (مصدر SALE).
    الفاتورة = مستند الذمة؛ التحصيل يتم على حساب العميل وليس بإغلاق البيع مباشرة.
    """
    from models import Invoice, InvoiceLine, InvoiceSource

    if not sale or not getattr(sale, "id", None) or not getattr(sale, "customer_id", None):
        return None

    totals = compute_sale_totals(sale)
    grand_total = totals["grand_total"]
    tax_amount = totals["tax_amount"]
    discount_amount = totals["discount_total"]

    inv = Invoice.query.filter_by(sale_id=int(sale.id)).first()
    inv_number = (getattr(sale, "sale_number", None) or "").strip() or f"SINV-{sale.id}"

    if not inv:
        inv = Invoice(
            invoice_number=inv_number,
            invoice_date=getattr(sale, "sale_date", None) or _utc_now_naive(),
            customer_id=int(sale.customer_id),
            sale_id=int(sale.id),
            source=InvoiceSource.SALE.value,
            kind="INVOICE",
            currency=(getattr(sale, "currency", None) or "ILS").upper(),
            total_amount=float(grand_total),
            tax_amount=float(tax_amount),
            discount_amount=float(discount_amount),
            notes=getattr(sale, "notes", None),
        )
        db.session.add(inv)
        db.session.flush()
    else:
        inv.invoice_number = inv.invoice_number or inv_number
        inv.invoice_date = getattr(sale, "sale_date", None) or inv.invoice_date
        inv.customer_id = int(sale.customer_id)
        inv.currency = (getattr(sale, "currency", None) or inv.currency or "ILS").upper()
        inv.total_amount = float(grand_total)
        inv.tax_amount = float(tax_amount)
        inv.discount_amount = float(discount_amount)
        if getattr(sale, "notes", None):
            inv.notes = sale.notes
        db.session.add(inv)
        db.session.flush()

    InvoiceLine.query.filter_by(invoice_id=inv.id).delete(synchronize_session=False)
    db.session.flush()

    for ln in sale.lines or []:
        product = getattr(ln, "product", None)
        desc = getattr(product, "name", None) if product else None
        if not desc:
            desc = f"منتج #{getattr(ln, 'product_id', '')}"
        db.session.add(
            InvoiceLine(
                invoice_id=inv.id,
                product_id=getattr(ln, "product_id", None),
                description=str(desc)[:200],
                quantity=float(getattr(ln, "quantity", 0) or 0),
                unit_price=float(getattr(ln, "unit_price", 0) or 0),
                tax_rate=float(getattr(ln, "tax_rate", 0) or 0),
                discount=float(getattr(ln, "discount_rate", 0) or 0),
            )
        )
    db.session.flush()

    try:
        sale.total_amount = float(grand_total)
    except Exception:
        pass

    if commit:
        db.session.commit()
        try:
            from models import run_invoice_gl_sync_after_commit
            run_invoice_gl_sync_after_commit(inv.id)
        except Exception:
            pass

    return inv


def refresh_customer_balance_for_sale(sale) -> None:
    if not getattr(sale, "customer_id", None):
        return
    try:
        from utils.customer_balance_updater import update_customer_balance_components
        update_customer_balance_components(int(sale.customer_id), db.session)
    except Exception:
        pass


def compute_sale_paid_display(sale, grand_total=None):
    """
    حساب المدفوع والمتبقي للعرض فقط — بدون تعديل سجل المبيعة.
    يُرجع (paid_display, balance_due_display) كـ Decimal.
    """
    from utils import D
    from utils.ar_accounting_rules import PAYMENT_STATUSES_BALANCE

    if grand_total is None:
        grand_total = compute_sale_totals(sale)["grand_total"]
    grand_total = D(grand_total)
    paid_display = D(0)
    sale_curr = (getattr(sale, "currency", None) or "ILS").upper()
    from models import convert_amount as _convert_amount

    for p in getattr(sale, "payments", []) or []:
        st = str(getattr(getattr(p, "status", None), "value", getattr(p, "status", None)) or "").upper()
        if st not in PAYMENT_STATUSES_BALANCE:
            continue
        splits = getattr(p, "splits", None) or []
        if splits:
            for s in splits:
                amt = D(str(getattr(s, "converted_amount", 0) or 0))
                cur = (
                    getattr(s, "converted_currency", None)
                    or getattr(s, "currency", None)
                    or getattr(p, "currency", None)
                    or sale_curr
                ).upper()
                if amt <= 0:
                    amt = D(str(getattr(s, "amount", 0) or 0))
                    cur = (getattr(s, "currency", None) or getattr(p, "currency", None) or sale_curr).upper()
                if cur != sale_curr:
                    try:
                        amt = D(str(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None))))
                    except Exception:
                        pass
                paid_display += amt
        else:
            amt = D(str(getattr(p, "total_amount", 0) or 0))
            cur = (getattr(p, "currency", None) or sale_curr).upper()
            if cur != sale_curr:
                try:
                    amt = D(str(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None))))
                except Exception:
                    pass
            paid_display += amt
    paid_display = paid_display.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    balance_due = (grand_total - paid_display).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return paid_display, balance_due


def sale_receivable_display(sale) -> dict:
    """
    عرض محاسبي: المبيعة = ذمة على العميل (مبلغ الفاتورة).
    لا نعرض «مفتوحة/متبقي» كحالة تحصيل على مستوى البيع.
    """
    total = float(getattr(sale, "total_amount", 0) or 0)
    if total <= 0.01:
        return {
            "amount": 0.0,
            "amount_fmt": "0.00",
            "label": "—",
            "badge_class": "bg-secondary",
            "is_receivable": False,
        }
    return {
        "amount": total,
        "amount_fmt": f"{total:,.2f}",
        "label": "ذمة",
        "badge_class": "bg-warning text-dark",
        "is_receivable": True,
    }
