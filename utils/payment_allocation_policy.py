"""
سياسة تخصيص الدفعات — محاسبة ذمم (AR/AP) على مستوى الجهة.

المبدأ (مثل أنظمة ERP العالمية: open-item على حساب العميل):
- الالتزام (بيع/فاتورة/خدمة) = ذمة مستقلة تبقى مفتوحة حتى يُسوّى الرصيد إجمالاً.
- الدفعة الواردة = حق على حساب العميل (تخفيض الذمة الإجمالية)، وليست «إغلاق» لمستند بيع محدد.
- لا توزيع تلقائي للدفعات على مستندات (افتراضياً معطّل).
"""

_CUSTOMER_DOCUMENT_ENTITY_TYPES = frozenset({"SALE", "INVOICE", "SERVICE", "PREORDER"})


def payment_auto_allocate_enabled() -> bool:
    """هل يُسمح بتخصيص الدفعات تلقائياً على مبيعات/فواتير/خدمات مفتوحة؟"""
    try:
        from models import SystemSettings
        return bool(SystemSettings.get_setting("auto_allocate", False))
    except Exception:
        return False


def normalize_customer_payment_booking(
    entity_type: str,
    target_kwargs: dict,
    *,
    customer_id: int | None,
) -> tuple[str, dict]:
    """
    عند تعطيل التوزيع: تُسجَّل الدفعة على حساب العميل فقط (customer_id)
    دون ربط sale_id / invoice_id / service_id / preorder_id.
    """
    if payment_auto_allocate_enabled():
        return entity_type, target_kwargs
    et = str(entity_type or "").upper()
    if et in _CUSTOMER_DOCUMENT_ENTITY_TYPES and customer_id:
        return "CUSTOMER", {"customer_id": int(customer_id)}
    return entity_type, target_kwargs
