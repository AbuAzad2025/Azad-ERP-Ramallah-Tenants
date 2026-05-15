"""ERP transaction guard for AI-assisted control.

Runs lightweight checks before database flush. Default mode is monitor-only.
Set SystemSettings key ai_erp_guard_block_critical=true to block critical risks.
Every finding also includes user-facing guidance for smart inline messages.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List

from AI.engine.ai_storage import append_json_list, utc_now

GUARD_LOG_FILE = "ai_erp_guard_events.json"

_CRITICAL_MODE_KEY = "ai_erp_guard_block_critical"
_BOUND = False


class AITransactionBlocked(ValueError):
    """Raised when strict ERP guard mode blocks a critical transaction."""

    def __init__(self, message: str, findings: List[Dict[str, Any]] = None):
        super().__init__(message)
        self.findings = findings or []
        self.user_message = message


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _val(obj: Any, *names: str):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _obj_id(obj: Any) -> Dict[str, Any]:
    return {"model": obj.__class__.__name__, "id": getattr(obj, "id", None)}


def _setting_bool(key: str, default: bool = False) -> bool:
    try:
        from models import SystemSettings
        value = SystemSettings.get_setting(key, default)
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    except Exception:
        return default


def _user_snapshot() -> Dict[str, Any]:
    try:
        from flask_login import current_user
        if current_user and getattr(current_user, "is_authenticated", False):
            return {"user_id": getattr(current_user, "id", None), "username": getattr(current_user, "username", None), "role": getattr(current_user, "role_name_l", None)}
    except Exception:
        pass
    return {"user_id": None, "username": None, "role": None}


def _finding(code: str, severity: str, obj: Any, message: str, advice: str = "راجع الحركة قبل الاعتماد.") -> Dict[str, Any]:
    item = {"code": code, "severity": severity, "message": message, "advice": advice, **_obj_id(obj)}
    try:
        from AI.engine.ai_transaction_copilot import guidance_for_finding
        item["user_guidance"] = guidance_for_finding(item)
    except Exception:
        pass
    return item


def inspect_object(obj: Any, state: str) -> List[Dict[str, Any]]:
    name = obj.__class__.__name__
    findings: List[Dict[str, Any]] = []

    if name in {"Payment", "Expense"}:
        amount = _dec(_val(obj, "total_amount", "amount"))
        if amount <= 0:
            findings.append(_finding(f"{name.upper()}_BAD_AMOUNT", "CRITICAL", obj, "مبلغ مالي غير موجب.", "امنع حفظ مبالغ صفرية أو سالبة."))
        ref = _val(obj, "reference", "ref", "check_number")
        if amount >= Decimal("5000") and not ref:
            findings.append(_finding(f"{name.upper()}_LARGE_NO_REF", "HIGH", obj, "مبلغ كبير بدون مرجع.", "اجعل المرجع أو المرفق إلزامياً للحركات الكبيرة."))
        if name == "Payment":
            direction = str(_val(obj, "direction") or "").upper()
            if direction not in {"IN", "OUT"}:
                findings.append(_finding("PAYMENT_BAD_DIRECTION", "CRITICAL", obj, "اتجاه الدفعة غير صحيح.", "يجب تحديد IN أو OUT بوضوح."))

    if name in {"Sale", "Invoice"}:
        total = _dec(_val(obj, "total_amount", "total", "grand_total"))
        status = str(_val(obj, "status") or "").upper()
        if total < 0:
            findings.append(_finding(f"{name.upper()}_NEGATIVE_TOTAL", "CRITICAL", obj, "إجمالي سالب.", "راجع طريقة المرتجع أو العكس المحاسبي."))
        if total == 0 and status not in {"DRAFT", "CANCELLED", "REFUNDED", "RETURNED"}:
            findings.append(_finding(f"{name.upper()}_ZERO_ACTIVE", "MEDIUM", obj, "حركة نشطة بقيمة صفر.", "تأكد أنها ليست عملية تدريبية أو إدخالاً ناقصاً."))
        subtotal = _dec(_val(obj, "subtotal", "sub_total", "before_discount"))
        discount = _dec(_val(obj, "discount", "discount_total", "discount_amount"))
        if subtotal > 0 and discount > 0 and (discount / subtotal * Decimal("100")) >= Decimal("30"):
            findings.append(_finding(f"{name.upper()}_LARGE_DISCOUNT", "HIGH", obj, "خصم كبير.", "اجعل الخصومات الكبيرة بحاجة موافقة أو سبب موثق."))

    if name == "StockLevel":
        qty = _dec(_val(obj, "quantity", "qty", "available_qty", "on_hand"))
        if qty < 0:
            findings.append(_finding("STOCK_NEGATIVE", "CRITICAL", obj, "مخزون سالب.", "راجع آخر حركة على المنتج والمستودع."))

    if name == "Product":
        sell = _dec(_val(obj, "selling_price", "price"))
        cost = _dec(_val(obj, "purchase_price", "cost"))
        if sell > 0 and cost > 0 and sell < cost:
            findings.append(_finding("PRODUCT_BELOW_COST", "MEDIUM", obj, "سعر البيع أقل من التكلفة.", "تأكد أن هذا مقصود وليس خطأ تسعير."))

    if state == "deleted" and name in {"Payment", "Expense", "Sale", "Invoice", "User", "Role", "Permission"}:
        findings.append(_finding(f"{name.upper()}_REMOVED", "HIGH", obj, "حذف كيان حساس.", "يفضل الأرشفة مع سبب بدل الحذف المباشر."))

    return findings


def _build_user_message(findings: Iterable[Dict[str, Any]]) -> str:
    try:
        from AI.engine.ai_transaction_copilot import compact_user_message
        return compact_user_message(findings)
    except Exception:
        return ""


def _log_findings(findings: Iterable[Dict[str, Any]]) -> None:
    items = list(findings or [])
    if not items:
        return
    user_message = _build_user_message(items)
    try:
        append_json_list(GUARD_LOG_FILE, {"timestamp": utc_now(), "findings": items, "user_message": user_message, **_user_snapshot()}, max_items=1000)
    except Exception:
        pass


def _collect(session) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for obj in list(session.new):
        findings.extend(inspect_object(obj, "new"))
    for obj in list(session.dirty):
        findings.extend(inspect_object(obj, "dirty"))
    for obj in list(session.deleted):
        findings.extend(inspect_object(obj, "deleted"))
    return findings


def bind_erp_transaction_guard() -> bool:
    global _BOUND
    if _BOUND:
        return False
    try:
        from sqlalchemy import event
        from sqlalchemy.orm import Session
    except Exception:
        return False

    def before_flush(session, flush_context, instances):
        findings = _collect(session)
        if not findings:
            return
        _log_findings(findings)
        if _setting_bool(_CRITICAL_MODE_KEY, False):
            critical = [f for f in findings if f.get("severity") == "CRITICAL"]
            if critical:
                message = _build_user_message(critical) or "تم منع حفظ الحركة لأنها تحتوي خطراً حرجاً يحتاج تصحيحاً."
                raise AITransactionBlocked(message, critical)

    try:
        event.listen(Session, "before_flush", before_flush, retval=False)
        _BOUND = True
        return True
    except Exception:
        return False


__all__ = ["AITransactionBlocked", "bind_erp_transaction_guard", "inspect_object"]
