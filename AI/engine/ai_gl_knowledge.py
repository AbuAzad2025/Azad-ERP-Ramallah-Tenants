"""GL knowledge helpers for the AI assistant.

This file contains explanatory accounting knowledge only. It must not execute
posting/reversal logic and must avoid hard-coded tax rates or account meanings
when those values can differ by installation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


GL_SYSTEM_KNOWLEDGE = {
    "description": "نظام دفتر الأستاذ في نظام أزاد يعتمد مبدأ القيد المزدوج: كل حركة لها طرف مدين وطرف دائن، ويجب أن يتساوى إجمالي المدين مع إجمالي الدائن.",
    "models": {
        "GLBatch": {
            "description": "مجموعة قيود محاسبية مرتبطة بمصدر واحد مثل بيع أو دفعة أو مصروف.",
            "fields": {
                "id": "المعرّف الفريد",
                "batch_date": "تاريخ المجموعة",
                "source_type": "نوع المصدر",
                "source_id": "معرّف المصدر",
                "purpose": "الغرض",
                "currency": "العملة",
                "memo": "الوصف",
                "reference": "المرجع الخارجي",
                "entity_type": "نوع الكيان",
                "entity_id": "معرّف الكيان",
                "total_debit": "إجمالي المدين",
                "total_credit": "إجمالي الدائن",
            },
            "relationships": {"entries": "قيود GLEntry المرتبطة بالمجموعة"},
        },
        "GLEntry": {
            "description": "سطر قيد محاسبي واحد داخل GLBatch.",
            "fields": {
                "id": "المعرّف",
                "gl_batch_id": "معرّف المجموعة",
                "account_code": "رمز الحساب",
                "debit_amount": "المبلغ المدين",
                "credit_amount": "المبلغ الدائن",
                "description": "الوصف",
                "entity_type": "نوع الكيان المرتبط",
                "entity_id": "معرّف الكيان المرتبط",
            },
        },
    },
    "accounts": {
        "description": "دليل الحسابات، وقد تختلف الرموز الدقيقة حسب إعدادات النظام.",
        "structure": {
            "1xxx": "أصول",
            "2xxx": "خصوم",
            "3xxx": "حقوق ملكية",
            "4xxx": "إيرادات",
            "5xxx": "مصروفات",
        },
        "main_accounts": {
            "1000_CASH": "النقدية",
            "1010_BANK": "البنك",
            "1020_CARD_CLEARING": "مقاصة البطاقات",
            "1100_AR": "ذمم الزبائن",
            "1200_INVENTORY": "المخزون",
            "1300_CHECKS_RECEIVABLE": "شيكات تحت التحصيل",
            "2000_AP": "ذمم الموردين",
            "2100_CHECKS_PAYABLE": "شيكات تحت الدفع",
            "3000_EQUITY": "رأس المال",
            "3100_RETAINED_EARNINGS": "الأرباح المحتجزة",
            "4000_SALES": "إيرادات المبيعات",
            "4100_SERVICE_REVENUE": "إيرادات الخدمات",
            "5000_EXPENSES": "المصاريف العامة",
            "5100_COGS": "تكلفة البضاعة المباعة",
        },
    },
    "auto_gl_creation": {
        "description": "إنشاء GL قد يتم تلقائياً عبر listeners أو خدمات sync داخل النظام.",
        "modules": [
            {"module": "Opening Balance", "entries": "ذمم/رأس مال حسب نوع الكيان واتجاه الرصيد"},
            {"module": "Sale", "entries": "ذمم الزبائن ↔ إيرادات/ضريبة/تكلفة حسب الإعدادات"},
            {"module": "Payment", "entries": "نقدية/بنك ↔ ذمم حسب اتجاه الدفعة"},
            {"module": "Expense", "entries": "مصروف ↔ نقدية/بنك أو ذمم"},
            {"module": "Check", "entries": "قيود دورة حياة الشيك حسب حالته"},
            {"module": "Shipment", "entries": "مخزون/تكاليف ↔ ذمم أو موردين حسب السيناريو"},
            {"module": "Service", "entries": "ذمم ↔ إيراد خدمة عند تحقق شروط الخدمة"},
        ],
    },
}


GL_BUSINESS_RULES = {
    "double_entry": {"rule": "كل قيد يجب أن يكون متوازنًا: Total Debit = Total Credit", "example": "مدين طرف، ودائن طرف آخر بنفس المبلغ."},
    "opening_balance": {"rule": "الرصيد الافتتاحي يسجل حسب سياسة النظام واتجاه الرصيد ونوع الكيان."},
    "sale_accounting": {"rule": "المبيعات تسجل عند تحقق شروط الاعتماد/التأكيد في النظام.", "basic": "ذمم الزبائن مدين، والإيرادات/الضريبة دائن حسب الإعدادات."},
    "payment_accounting": {"rule": "الدفعات تسجل عند اكتمالها.", "incoming": "نقدية/بنك مدين مقابل ذمم دائن عادةً.", "outgoing": "ذمم/مصروف مدين مقابل نقدية/بنك دائن عادةً."},
    "check_lifecycle": {"rule": "الشيكات لها دورة حياة، وكل انتقال حالة قد يحتاج قيدًا مختلفًا."},
}


GL_REPORTS_KNOWLEDGE = {
    "trial_balance": {"name_ar": "ميزان المراجعة", "name_en": "Trial Balance", "description": "قائمة بجميع الحسابات مع أرصدتها المدينة والدائنة", "purpose": "التحقق من توازن القيود", "formula": "إجمالي المدين = إجمالي الدائن", "columns": ["رمز الحساب", "اسم الحساب", "المدين", "الدائن", "الرصيد"]},
    "balance_sheet": {"name_ar": "الميزانية العمومية", "name_en": "Balance Sheet", "description": "بيان المركز المالي في تاريخ معين", "formula": "الأصول = الخصوم + حقوق الملكية", "sections": {"assets": "الأصول", "liabilities": "الخصوم", "equity": "حقوق الملكية"}},
    "income_statement": {"name_ar": "قائمة الدخل", "name_en": "Income Statement", "description": "بيان الأرباح والخسائر عن فترة معينة", "formula": "صافي الربح = الإيرادات - المصروفات", "sections": {"revenue": "الإيرادات", "cogs": "تكلفة البضاعة المباعة", "gross_profit": "إجمالي الربح", "expenses": "المصروفات", "net_profit": "صافي الربح"}},
    "cash_flow": {"name_ar": "قائمة التدفقات النقدية", "name_en": "Cash Flow Statement", "description": "بيان حركة النقد خلال فترة معينة", "sections": {"operating": "الأنشطة التشغيلية", "investing": "الأنشطة الاستثمارية", "financing": "الأنشطة التمويلية"}},
}


def _amount(entry: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = float(entry.get(key, 0) or 0)
            if value:
                return value
        except Exception:
            continue
    return 0.0


def explain_gl_entry(gl_entry_data: Dict[str, Any]) -> str:
    account_code = gl_entry_data.get("account_code") or gl_entry_data.get("account") or ""
    debit = _amount(gl_entry_data, "debit_amount", "debit")
    credit = _amount(gl_entry_data, "credit_amount", "credit")
    description = gl_entry_data.get("description", "")
    account_name = GL_SYSTEM_KNOWLEDGE["accounts"]["main_accounts"].get(account_code, account_code or "حساب غير محدد")
    entry_type = "مدين" if debit > 0 else "دائن" if credit > 0 else "بدون مبلغ"
    amount = debit if debit > 0 else credit
    effect = _explain_account_effect(account_code, entry_type, amount)
    return f"""📝 **قيد محاسبي**
- الحساب: {account_name} ({account_code})
- النوع: {entry_type}
- المبلغ: {amount:,.2f} شيقل
- الوصف: {description}

💡 **الأثر**
{effect}""".strip()


def _explain_account_effect(account_code: str, entry_type: str, amount: float) -> str:
    if not account_code or entry_type == "بدون مبلغ":
        return "لا يمكن تحديد الأثر بدون رمز حساب ومبلغ."
    account_category = account_code[:1]
    effects = {
        "1": {"مدين": f"زيادة في الأصول بمبلغ {amount:,.2f}", "دائن": f"نقص في الأصول بمبلغ {amount:,.2f}"},
        "2": {"مدين": f"نقص في الخصوم بمبلغ {amount:,.2f}", "دائن": f"زيادة في الخصوم بمبلغ {amount:,.2f}"},
        "3": {"مدين": f"نقص في حقوق الملكية بمبلغ {amount:,.2f}", "دائن": f"زيادة في حقوق الملكية بمبلغ {amount:,.2f}"},
        "4": {"مدين": f"تخفيض إيراد أو عكس إيراد بمبلغ {amount:,.2f}", "دائن": f"زيادة إيراد بمبلغ {amount:,.2f}"},
        "5": {"مدين": f"زيادة مصروف بمبلغ {amount:,.2f}", "دائن": f"تخفيض/عكس مصروف بمبلغ {amount:,.2f}"},
    }
    return effects.get(account_category, {}).get(entry_type, "تأثير غير معروف؛ راجع دليل الحسابات الفعلي.")


def analyze_gl_batch(gl_batch_data: Dict[str, Any]) -> Dict[str, Any]:
    entries = gl_batch_data.get("entries", []) or []
    total_debit = sum(_amount(entry, "debit_amount", "debit") for entry in entries)
    total_credit = sum(_amount(entry, "credit_amount", "credit") for entry in entries)
    is_balanced = abs(total_debit - total_credit) < 0.01
    analysis = {
        "balanced": is_balanced,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": total_debit - total_credit,
        "entries_count": len(entries),
        "source_type": gl_batch_data.get("source_type"),
        "purpose": gl_batch_data.get("purpose"),
        "explanation": _explain_gl_batch_purpose(gl_batch_data),
    }
    if not is_balanced:
        analysis["warning"] = f"⚠️ القيد غير متوازن؛ الفرق: {analysis['difference']:,.2f}"
    return analysis


def _explain_gl_batch_purpose(gl_batch_data: Dict[str, Any]) -> str:
    source_type = str(gl_batch_data.get("source_type", "") or "").upper()
    purpose = str(gl_batch_data.get("purpose", "") or "").upper()
    memo = gl_batch_data.get("memo", "")
    explanations = {
        "SALE_REVENUE": "قيد إيرادات مبيعات",
        "OPENING_BALANCE": "قيد رصيد افتتاحي",
        "PAYMENT": "قيد دفعة",
        "EXPENSE": "قيد مصروف",
        "CHECK": "قيد شيك",
        "SHIPMENT": "قيد شحنة",
        "SERVICE": "قيد خدمة",
    }
    combined = f"{source_type}_{purpose}".strip("_")
    return explanations.get(combined) or explanations.get(source_type) or explanations.get(purpose) or memo or "قيد محاسبي عام"


def get_gl_knowledge_for_ai() -> Dict[str, Any]:
    return {
        "system_knowledge": GL_SYSTEM_KNOWLEDGE,
        "business_rules": GL_BUSINESS_RULES,
        "reports_knowledge": GL_REPORTS_KNOWLEDGE,
        "capabilities": ["فهم دفتر الأستاذ", "شرح القيود", "تحليل GLBatch", "كشف أخطاء التوازن", "شرح التقارير المالية", "تتبع المعاملات بشكل وصفي"],
        "can_answer": ["ما هو دفتر الأستاذ؟", "كيف يتم إنشاء GL؟", "فسّر لي هذا القيد", "لماذا الرصيد غير متوازن؟", "ما هو ميزان المراجعة؟", "ما الفرق بين AR و AP؟"],
    }


def detect_gl_error(gl_batch_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    entries = gl_batch_data.get("entries", []) or []
    if not entries:
        return {"error": "empty_batch", "message": "⚠️ لا توجد قيود في هذه المجموعة", "solution": "تأكد من إنشاء قيود محاسبية مرتبطة بالمصدر"}
    total_debit = sum(_amount(entry, "debit_amount", "debit") for entry in entries)
    total_credit = sum(_amount(entry, "credit_amount", "credit") for entry in entries)
    if abs(total_debit - total_credit) > 0.01:
        return {"error": "unbalanced", "message": f"⚠️ القيد غير متوازن\nالمدين: {total_debit:,.2f}\nالدائن: {total_credit:,.2f}\nالفرق: {total_debit - total_credit:,.2f}", "solution": "راجع القيود وتأكد أن إجمالي المدين = إجمالي الدائن"}
    for idx, entry in enumerate(entries, 1):
        debit = _amount(entry, "debit_amount", "debit")
        credit = _amount(entry, "credit_amount", "credit")
        if debit == 0 and credit == 0:
            return {"error": "zero_entry", "message": f"⚠️ القيد رقم {idx} فارغ", "solution": "احذف القيد الفارغ أو أضف مبلغًا"}
        if debit > 0 and credit > 0:
            return {"error": "double_entry", "message": f"⚠️ القيد رقم {idx} يحتوي على مدين ودائن معاً", "solution": "كل سطر قيد يجب أن يكون مدينًا أو دائنًا فقط"}
    return None


def suggest_gl_correction(error_info: Dict[str, Any]) -> str:
    suggestions = {
        "unbalanced": "💡 احسب الفرق، راجع السطور الناقصة أو المضاعفة، ثم تأكد من تساوي إجمالي المدين والدائن.",
        "empty_batch": "💡 تحقق من أن المعاملة استوفت شروط إنشاء القيد وأن listener/service الخاص بها عمل بنجاح.",
        "zero_entry": "💡 احذف السطر الفارغ أو أضف المبلغ الصحيح في طرف واحد فقط.",
        "double_entry": "💡 اجعل السطر مدينًا أو دائنًا فقط، ولا تجمع الطرفين في نفس السطر.",
    }
    return suggestions.get(error_info.get("error", ""), "راجع البيانات ودليل الحسابات الفعلي.")


def explain_any_number(number_value: float, context: str) -> str:
    val = float(number_value or 0)
    if context == "customer_balance":
        direction = "موجب" if val > 0 else "سالب" if val < 0 else "صفر"
        return f"""📊 **رصيد الزبون: {val:,.2f} ₪**

هذا الرقم يمثل رصيد الزبون حسب سياسة النظام الحالية.
اتجاه الرصيد: {direction}.

مصادره المحتملة:
- مبيعات أو فواتير على الزبون
- دفعات واردة أو مردودات
- رصيد افتتاحي
- قيود GL مرتبطة بالزبون

لا أفترض هنا أن الموجب يعني عليه أو له دائمًا؛ يجب اعتماد تفسير النظام المعروض في صفحة الزبون أو سياسة الرصيد المحاسبية."""
    if context == "total_sales":
        return f"""💰 **إجمالي المبيعات: {val:,.2f} ₪**

هذا عادةً مجموع المبيعات في فترة محددة وحالة محددة.
للتدقيق: راجع الفترة، حالة الفواتير، العملة، الخصومات، والضريبة من إعدادات النظام."""
    if context == "vat_payable":
        return f"""🧾 **ضريبة مستحقة: {val:,.2f} ₪**

الضريبة المستحقة تحسب من ضريبة المخرجات ناقص ضريبة المدخلات حسب القواعد والإعدادات الفعلية.
لا تعتمد على نسبة ثابتة داخل الكود؛ اقرأ النسبة من إعدادات النظام أو مصدر رسمي حديث."""
    return f"""📊 **القيمة: {val:,.2f} ₪**

السياق: {context}
حدد نوع الرقم للحصول على شرح أدق: customer_balance, total_sales, vat_payable, net_profit, inventory_value."""


def trace_transaction_flow(transaction_type: str, transaction_id: int) -> Dict[str, Any]:
    flows = {
        "sale": {
            "step_1": {"title": "تسجيل البيع", "table": "Sale/SaleLine", "data": ["الزبون", "المنتجات", "الكميات", "الأسعار", "الإجمالي"]},
            "step_2": {"title": "تحديث المخزون", "table": "StockLevel", "formula": "الكمية الجديدة = الكمية السابقة - الكمية المباعة"},
            "step_3": {"title": "إنشاء القيد المحاسبي", "table": "GLBatch/GLEntry", "entries": ["ذمم الزبائن مدين", "الإيراد دائن", "الضريبة دائن إذا كانت مفعلة", "التكلفة/المخزون حسب إعدادات النظام"]},
            "step_4": {"title": "تحديث رصيد الزبون", "calculation": "حسب سياسة الرصيد المعتمدة في النظام"},
            "step_5": {"title": "الأثر المالي", "income_statement": "زيادة الإيرادات/التكلفة حسب المعاملة", "balance_sheet": "تأثير على الذمم/المخزون/الضريبة", "cash_flow": "يتأثر عند التحصيل النقدي"},
        },
        "payment_in": {
            "step_1": {"title": "تسجيل الدفعة", "table": "Payment", "data": ["الكيان", "المبلغ", "طريقة الدفع", "التاريخ"]},
            "step_2": {"title": "إنشاء القيد", "entries": ["نقدية/بنك مدين", "ذمم دائن عادةً"]},
            "step_3": {"title": "تحديث الرصيد", "calculation": "حسب اتجاه الدفعة وسياسة رصيد الكيان"},
            "step_4": {"title": "الأثر المالي", "cash_flow": "زيادة تدفق نقدي عند التحصيل"},
        },
    }
    return flows.get(transaction_type, {"error": f"نوع المعاملة '{transaction_type}' غير معروف", "available": list(flows.keys()), "transaction_id": transaction_id})


__all__ = [
    "GL_SYSTEM_KNOWLEDGE",
    "GL_BUSINESS_RULES",
    "GL_REPORTS_KNOWLEDGE",
    "get_gl_knowledge_for_ai",
    "explain_gl_entry",
    "analyze_gl_batch",
    "detect_gl_error",
    "suggest_gl_correction",
    "explain_any_number",
    "trace_transaction_flow",
]
