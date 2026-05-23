"""
سياسة تخصيص الدفعات — محاسبة ذمم (AR/AP) على مستوى الجهة.

المبدأ (مثل أنظمة ERP العالمية: open-item على حساب الزبون):
- الالتزام (بيع/فاتورة/خدمة) = ذمة مستقلة تبقى مفتوحة حتى يُسوّى الرصيد إجمالاً.
- الدفعة الواردة = حق على حساب الزبون (تخفيض الذمة الإجمالية)، وليست «إغلاق» لمستند بيع محدد.
- لا توزيع تلقائي للدفعات على مستندات (افتراضياً معطّل).
"""

_CUSTOMER_DOCUMENT_ENTITY_TYPES = frozenset({"SALE", "INVOICE", "SERVICE", "PREORDER"})


def payment_auto_allocate_enabled() -> bool:
    """
    هل يُسمح بتخصيص الدفعات تلقائياً على مبيعات/فواتير/خدمات؟
    مفتاح منفصل عن auto_allocate (مراكز التكلفة) — الافتراضي معطّل دائماً.
    """
    try:
        from models import SystemSettings
        return bool(SystemSettings.get_setting("payment_auto_allocate", False))
    except Exception:
        return False


def normalize_customer_payment_booking(
    entity_type: str,
    target_kwargs: dict,
    *,
    customer_id: int | None,
) -> tuple[str, dict]:
    """
    عند تعطيل التوزيع: تُسجَّل الدفعة على حساب الزبون فقط (customer_id)
    دون ربط sale_id / invoice_id / service_id / preorder_id.
    """
    if payment_auto_allocate_enabled():
        return entity_type, target_kwargs
    et = str(entity_type or "").upper()
    if et in _CUSTOMER_DOCUMENT_ENTITY_TYPES and customer_id:
        return "CUSTOMER", {"customer_id": int(customer_id)}
    return entity_type, target_kwargs


_PAYMENT_DOCUMENT_FKS = ("sale_id", "invoice_id", "service_id", "preorder_id")


def enforce_open_item_payment_booking(payment) -> None:
    """
    عند تعطيل التوزيع: لا ربط لاحق للدفعة ببيع/فاتورة/خدمة/حجز —
    تُسجَّل على حساب الزبون فقط (ذمة مفتوحة).
    """
    if payment_auto_allocate_enabled():
        return
    if any(getattr(payment, fk, None) for fk in _PAYMENT_DOCUMENT_FKS):
        customer_id = getattr(payment, "customer_id", None)
        if not customer_id:
            for fk in _PAYMENT_DOCUMENT_FKS:
                doc_id = getattr(payment, fk, None)
                if not doc_id:
                    continue
                if fk == "sale_id":
                    from models import Sale
                    sale = Sale.query.get(int(doc_id))
                    customer_id = getattr(sale, "customer_id", None) if sale else None
                elif fk == "invoice_id":
                    from models import Invoice
                    inv = Invoice.query.get(int(doc_id))
                    customer_id = getattr(inv, "customer_id", None) if inv else None
                elif fk == "service_id":
                    from models import ServiceRequest
                    svc = ServiceRequest.query.get(int(doc_id))
                    customer_id = getattr(svc, "customer_id", None) if svc else None
                elif fk == "preorder_id":
                    from models import PreOrder
                    po = PreOrder.query.get(int(doc_id))
                    customer_id = getattr(po, "customer_id", None) if po else None
                if customer_id:
                    break
        for fk in _PAYMENT_DOCUMENT_FKS:
            setattr(payment, fk, None)
        if customer_id:
            payment.customer_id = int(customer_id)
            payment.entity_type = "CUSTOMER"
