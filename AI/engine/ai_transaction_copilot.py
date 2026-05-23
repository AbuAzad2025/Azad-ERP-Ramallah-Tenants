"""User-facing transaction copilot for ERP actions.

Turns audit/control findings into clear guidance shown while users work.
The messages are corrective and educational, not accusatory.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

SEVERITY_STYLE = {
    "CRITICAL": {"level": "danger", "prefix": "إجراء مرفوض أو عالي الخطورة"},
    "HIGH": {"level": "warning", "prefix": "تنبيه مهم"},
    "MEDIUM": {"level": "info", "prefix": "ملاحظة ذكية"},
    "LOW": {"level": "info", "prefix": "تلميح"},
}

FIELD_HINTS = {
    "amount": "تأكد أن المبلغ أكبر من صفر ومطابق للسند.",
    "total_amount": "راجع الإجمالي النهائي قبل الحفظ.",
    "direction": "حدد اتجاه الدفعة: IN للقبض و OUT للصرف.",
    "reference": "أدخل رقم سند أو شيك أو مرجع واضح.",
    "discount": "اكتب سبب الخصم الكبير أو اطلب موافقة مسؤول.",
    "quantity": "راجع الكمية والمستودع قبل الحفظ.",
    "customer_id": "اختر الزبون الصحيح قبل إنشاء الحركة.",
    "supplier_id": "اختر المورد الصحيح قبل إنشاء الحركة.",
    "warehouse_id": "اختر المستودع الصحيح حتى لا يتأثر مخزون خاطئ.",
}

CODE_ACTIONS = {
    "PAYMENT_BAD_DIRECTION": ["اختر IN إذا كان قبض من زبون.", "اختر OUT إذا كان صرف لمورد أو مصروف.", "راجع كشف الجهة بعد الحفظ."],
    "PAYMENT_BAD_AMOUNT": ["أدخل مبلغاً أكبر من صفر.", "طابق المبلغ مع السند أو الشيك.", "لا تحفظ دفعة صفرية أو سالبة."],
    "PAYMENT_LARGE_NO_REF": ["أدخل مرجعاً واضحاً للحركة.", "أرفق سنداً أو اكتب رقم الشيك إن وجد.", "اطلب موافقة مسؤول إذا كانت السياسة تتطلب ذلك."],
    "EXPENSE_BAD_AMOUNT": ["أدخل قيمة مصروف أكبر من صفر.", "راجع التصنيف والتاريخ.", "لا تحفظ مصروفاً بلا سبب واضح."],
    "EXPENSE_LARGE_NO_REF": ["أدخل مرجعاً أو مرفقاً للمصروف.", "اكتب وصفاً يوضح سبب الصرف.", "اطلب اعتماد مسؤول للمصاريف الكبيرة."],
    "SALE_NEGATIVE_TOTAL": ["راجع البنود والأسعار والخصومات.", "استخدم مرتجع أو عكس محاسبي بدل إجمالي سالب.", "لا تعتمد الفاتورة قبل تصحيح الإجمالي."],
    "INVOICE_NEGATIVE_TOTAL": ["راجع البنود والأسعار والخصومات.", "استخدم مرتجع أو عكس محاسبي بدل إجمالي سالب.", "لا تعتمد الفاتورة قبل تصحيح الإجمالي."],
    "SALE_LARGE_DISCOUNT": ["اكتب سبب الخصم.", "تأكد أن الخصم مصرح به.", "اطلب موافقة مسؤول إذا تجاوز الحد المعتمد."],
    "INVOICE_LARGE_DISCOUNT": ["اكتب سبب الخصم.", "تأكد أن الخصم مصرح به.", "اطلب موافقة مسؤول إذا تجاوز الحد المعتمد."],
    "STOCK_NEGATIVE": ["راجع الكمية المتوفرة في المستودع.", "أدخل توريداً أو تحويل مخزون قبل البيع/الصرف.", "لا تجعل المخزون سالباً إلا بسياسة واضحة وموافقة."],
    "PRODUCT_BELOW_COST": ["راجع سعر الشراء وسعر البيع.", "اكتب سبب البيع بأقل من التكلفة إذا كان مقصوداً.", "راجع صلاحية الخصم أو العرض."],
}


def _style(severity: str) -> Dict[str, str]:
    return SEVERITY_STYLE.get(str(severity or "LOW").upper(), SEVERITY_STYLE["LOW"])


def guidance_for_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    severity = str(finding.get("severity", "LOW")).upper()
    style = _style(severity)
    code = str(finding.get("code", "UNKNOWN"))
    title = finding.get("message") or finding.get("title") or "ملاحظة على الحركة"
    advice = finding.get("advice") or finding.get("recommendation") or "راجع البيانات قبل الحفظ."
    steps = CODE_ACTIONS.get(code, [advice])
    return {
        "code": code,
        "severity": severity,
        "level": style["level"],
        "title": f"{style['prefix']}: {title}",
        "message": advice,
        "steps": steps,
        "model": finding.get("model"),
        "record_id": finding.get("id") or finding.get("record_id"),
    }


def build_user_guidance(findings: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [guidance_for_finding(item) for item in findings or []]


def compact_user_message(findings: Iterable[Dict[str, Any]], max_items: int = 3) -> str:
    guidance = build_user_guidance(findings)
    if not guidance:
        return ""
    lines = []
    for item in guidance[:max_items]:
        lines.append(f"{item['title']}")
        for step in item.get("steps", [])[:3]:
            lines.append(f"- {step}")
    if len(guidance) > max_items:
        lines.append(f"وهناك {len(guidance) - max_items} ملاحظة إضافية. راجع تفاصيل التدقيق.")
    return "\n".join(lines)


def field_hint(field_name: str) -> str:
    return FIELD_HINTS.get(str(field_name or ""), "راجع هذا الحقل قبل المتابعة.")


def form_error_message(errors: Dict[str, Any]) -> Dict[str, Any]:
    messages = []
    for field, error in (errors or {}).items():
        messages.append({"field": field, "error": str(error), "hint": field_hint(field)})
    return {"title": "لم يتم حفظ الحركة بسبب بيانات تحتاج تصحيحاً", "messages": messages}


def next_best_action(model_name: str, issue_code: str = "") -> str:
    model = str(model_name or "").lower()
    code = str(issue_code or "")
    if "payment" in model:
        return "راجع اتجاه الدفعة، الجهة، المبلغ، والمرجع ثم احفظ مرة أخرى."
    if "expense" in model:
        return "راجع المبلغ، التصنيف، الوصف، والمرجع قبل الحفظ."
    if "sale" in model or "invoice" in model:
        return "راجع الزبون، البنود، الكميات، الأسعار، الخصم، والإجمالي."
    if "stock" in model or "product" in model:
        return "راجع المنتج والمستودع والكمية والتكلفة قبل الاعتماد."
    if code:
        return "صحح الملاحظة الظاهرة ثم حاول الحفظ مرة أخرى."
    return "راجع الحقول المطلوبة ثم تابع."


__all__ = ["build_user_guidance", "compact_user_message", "form_error_message", "field_hint", "next_best_action", "guidance_for_finding"]
