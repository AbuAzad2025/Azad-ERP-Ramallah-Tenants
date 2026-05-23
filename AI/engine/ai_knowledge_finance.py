"""Finance knowledge helpers for the AI assistant.

Operational guidance only. Rates and brackets are read from live system settings;
no statutory numeric fallbacks are calculated in this module.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

FINANCE_KNOWLEDGE = {
    "accounting_principles": {
        "استحقاق": "الإيرادات تُسجّل عند تحققها لا عند قبضها فقط.",
        "مطابقة": "تُطابق المصروفات مع الإيرادات المرتبطة بها.",
        "وحدة_محاسبية": "الكيان المالي منفصل عن مالكه.",
        "استمرارية": "المنشأة مستمرة ما لم يثبت العكس.",
        "حيطة_حذر": "عدم المبالغة في تقدير الأصول والإيرادات.",
    },
    "policy": {
        "warning": "أي نسبة أو شريحة يجب أن تأتي من إعدادات النظام أو مصدر رسمي حديث قبل الاعتماد.",
        "vat": "تحسب من إعدادات النظام فقط عند توفرها.",
        "income": "يجب ضبط الشرائح في SystemSettings قبل الاحتساب.",
    },
    "customs_codes": {
        "8703": {"description": "سيارات ركاب وعربات أخرى", "rate": "varies", "notes": "الرسوم تعتمد على النوع والسنة والسعة والوقود ومصدر الاستيراد."},
        "8704": {"description": "شاحنات نقل البضائع", "rate": "varies", "notes": "المركبات التجارية لها معاملة مختلفة حسب التصنيف."},
        "8708": {"description": "قطع غيار للسيارات", "rate": "varies", "notes": "راجع التعرفة الرسمية قبل الاحتساب."},
        "8507": {"description": "بطاريات كهربائية", "rate": "varies", "notes": "قد تخضع لرسوم تنظيمية إضافية."},
    },
    "financial_formulas": {
        "gross_profit": "الربح الإجمالي = الإيرادات - تكلفة البضاعة المباعة",
        "net_profit": "صافي الربح = الربح الإجمالي - المصروفات التشغيلية - الالتزامات المستحقة",
        "vat_calculation": "VAT = المبلغ الأساسي × (النسبة المقروءة من الإعدادات / 100)",
        "gross_up": "إذا كان السعر شامل الضريبة: الصافي = الإجمالي / (1 + النسبة)",
        "roi": "العائد على الاستثمار = (الربح / رأس المال) × 100",
    },
    "accounting_terms": {
        "دائن": "Credit - حسب السياق: طرف دائن أو حساب يزيد بالدائن.",
        "مدين": "Debit - حسب السياق: طرف مدين أو حساب يزيد بالمدين.",
        "أصول": "Assets - ممتلكات المنشأة وحقوقها.",
        "خصوم": "Liabilities - التزامات المنشأة.",
        "حقوق_ملكية": "Equity - صافي حق المالك/الشركاء.",
        "إيرادات": "Revenue - الدخل من النشاط.",
        "مصروفات": "Expenses - التكاليف التشغيلية.",
        "قيود_يومية": "Journal Entries - تسجيل العمليات المحاسبية.",
        "ميزان_مراجعة": "Trial Balance - للتحقق من التوازن.",
    },
    "currency_exchange": {
        "ILS": {"name": "شيقل", "symbol": "₪", "base": True},
        "USD": {"name": "دولار أمريكي", "symbol": "$"},
        "JOD": {"name": "دينار أردني", "symbol": "د.أ"},
        "EUR": {"name": "يورو", "symbol": "€"},
        "notes": ["أسعار الصرف تتغير؛ استخدم آخر سعر مسجل في ExchangeRate أو إعدادات النظام.", "لا توجد أسعار صرف ثابتة داخل هذا الملف."],
    },
}

TAX_KNOWLEDGE_PALESTINE = {"country": "فلسطين", "warning": "تحقق من الإعدادات أو مصدر رسمي حديث قبل اعتماد النسب.", "vat": {"name": "ضريبة القيمة المضافة", "rate_source": "SystemSettings/utils.get_vat_rate"}, "income_tax": {"name": "ضريبة الدخل", "brackets_source": "SystemSettings"}, "customs_duties": {"description": "تختلف حسب كود HS والاتفاقيات والتصنيف."}}
TAX_KNOWLEDGE_ISRAEL = {"country": "إسرائيل", "warning": "تحقق من الإعدادات أو مصدر رسمي حديث قبل اعتماد النسب.", "vat": {"name": "VAT", "rate_source": "SystemSettings"}, "income_tax": {"name": "Income Tax", "brackets_source": "SystemSettings أو مصدر رسمي حديث"}}


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _get_setting_value(*keys: str) -> Optional[str]:
    try:
        from models import SystemSettings
        for key in keys:
            setting = SystemSettings.query.filter_by(key=key).first()
            if setting and setting.value not in (None, ""):
                return str(setting.value)
    except Exception:
        return None
    return None


def _get_json_setting(*keys: str) -> Optional[Any]:
    value = _get_setting_value(*keys)
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _get_vat_rate(country: str) -> tuple[Optional[Decimal], str, str]:
    country = str(country or "palestine").lower()
    if country == "palestine":
        try:
            from utils import get_vat_rate, is_vat_enabled
            if not is_vat_enabled():
                return Decimal("0"), "system_settings", "VAT disabled in system settings"
            return _decimal(get_vat_rate()), "system_settings", "VAT read from system settings"
        except Exception:
            setting_rate = _get_setting_value("vat_rate", "VAT_RATE", "palestine_vat_rate")
            if setting_rate is not None:
                return _decimal(setting_rate), "system_settings", "VAT read from SystemSettings"
            return None, "not_configured", "VAT rate is not configured; no fallback rate was used"
    setting_rate = _get_setting_value(f"{country}_vat_rate", "vat_rate")
    if setting_rate is not None:
        return _decimal(setting_rate), "system_settings", "VAT read from SystemSettings"
    return None, "not_configured", "VAT rate is not configured; no fallback rate was used"


def get_finance_knowledge():
    return FINANCE_KNOWLEDGE


def get_tax_knowledge_detailed():
    return {"palestine": TAX_KNOWLEDGE_PALESTINE, "israel": TAX_KNOWLEDGE_ISRAEL, "comparison": {"vat": "اقرأ من الإعدادات أو مصدر رسمي حديث.", "corporate_tax": "اقرأ من الإعدادات أو مصدر رسمي حديث.", "personal_tax": "اقرأ من الإعدادات أو مصدر رسمي حديث."}, "tax_planning_tips": ["وثق المصروفات", "التزم بالمواعيد", "احتفظ بسجلات منظمة", "استشر مختصاً عند الحاجة"], "warning": "هذه معرفة تشغيلية عامة وليست فتوى ضريبية أو قانونية."}


def _normalise_brackets(raw_brackets: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_brackets, list):
        return []
    brackets = []
    for item in raw_brackets:
        if not isinstance(item, dict):
            continue
        start = item.get("from", item.get("من", 0))
        end = item.get("to", item.get("إلى"))
        rate = item.get("rate", item.get("نسبة"))
        if rate is None:
            continue
        brackets.append({"from": _decimal(start), "to": None if end in (None, "") else _decimal(end), "rate": _decimal(rate)})
    return brackets


def calculate_palestine_income_tax(income):
    income_dec = _decimal(income)
    if income_dec <= 0:
        return 0.0
    brackets = _normalise_brackets(_get_json_setting("palestine_income_tax_brackets", "income_tax_brackets_palestine"))
    if not brackets:
        return None
    total_tax = Decimal("0")
    for bracket in brackets:
        start = bracket["from"]
        end = bracket["to"]
        rate = bracket["rate"]
        if income_dec <= start:
            continue
        taxable = (income_dec - start) if end is None else min(income_dec, end) - start
        if taxable > 0:
            total_tax += taxable * (rate / Decimal("100"))
    return float(total_tax)


def calculate_vat(amount, country="palestine"):
    amount_dec = _decimal(amount)
    rate, source, warning = _get_vat_rate(country)
    if rate is None:
        return {"base_amount": float(amount_dec), "vat_rate": None, "vat_amount": None, "total_with_vat": None, "rate_source": source, "warning": warning}
    vat_amount = amount_dec * (rate / Decimal("100"))
    total_with_vat = amount_dec + vat_amount
    return {"base_amount": float(amount_dec), "vat_rate": float(rate), "vat_amount": float(vat_amount), "total_with_vat": float(total_with_vat), "rate_source": source, "warning": warning}


def get_customs_info(hs_code):
    return FINANCE_KNOWLEDGE["customs_codes"].get(str(hs_code), None)


def get_all_system_modules():
    return {"auth": {"name": "المصادقة", "route_hint": "/auth"}, "customers": {"name": "الزبائن", "route_hint": "/customers"}, "service": {"name": "الصيانة", "route_hint": "/service أو /services حسب التسجيل الفعلي"}, "sales": {"name": "المبيعات", "route_hint": "/sales"}, "shop": {"name": "المتجر", "route_hint": "/shop"}, "warehouses": {"name": "المستودعات", "route_hint": "/warehouses"}, "expenses": {"name": "النفقات", "route_hint": "/expenses"}, "payments": {"name": "المدفوعات", "route_hint": "/payments"}, "vendors": {"name": "الموردين", "route_hint": "/vendors أو /suppliers حسب التسجيل الفعلي"}, "ledger": {"name": "دفتر الأستاذ", "route_hint": "/gl أو /ledger حسب التسجيل الفعلي"}, "security": {"name": "الأمان", "route_hint": "/security"}, "note": "هذه خريطة fallback؛ خريطة المسارات الفعلية تأتي من ai_auto_discovery."}


__all__ = ["FINANCE_KNOWLEDGE", "TAX_KNOWLEDGE_PALESTINE", "TAX_KNOWLEDGE_ISRAEL", "get_finance_knowledge", "get_tax_knowledge_detailed", "calculate_palestine_income_tax", "calculate_vat", "get_customs_info", "get_all_system_modules"]
