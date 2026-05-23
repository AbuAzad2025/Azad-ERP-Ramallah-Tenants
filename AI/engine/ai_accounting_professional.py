"""Professional accounting knowledge for the AI assistant.

This module is intentionally static and explanatory. It avoids hard-coded legal
tax rates and avoids assuming that positive/negative entity balances always have
the same meaning across installations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List


ACCOUNTING_EQUATION = """
المعادلة المحاسبية الأساسية:

الأصول = الخصوم + حقوق الملكية
Assets = Liabilities + Equity

الأصول: ما تملكه المنشأة.
الخصوم: ما على المنشأة من التزامات.
حقوق الملكية: صافي حق المالك/الشركاء.
""".strip()


DOUBLE_ENTRY_SYSTEM = {
    "name": "نظام القيد المزدوج",
    "english": "Double-Entry Bookkeeping",
    "principles": {
        "balance": {"rule": "كل قيد يجب أن يتوازن", "formula": "إجمالي المدين = إجمالي الدائن"},
        "debit_credit": {
            "debit": "المدين يزيد الأصول والمصروفات غالبًا",
            "credit": "الدائن يزيد الخصوم وحقوق الملكية والإيرادات غالبًا",
            "rules": {
                "أصول": "المدين يزيد، الدائن ينقص",
                "خصوم": "المدين ينقص، الدائن يزيد",
                "حقوق ملكية": "المدين ينقص، الدائن يزيد",
                "إيرادات": "المدين ينقص، الدائن يزيد",
                "مصروفات": "المدين يزيد، الدائن ينقص",
            },
        },
        "normal_balances": {"assets": "مدين", "liabilities": "دائن", "equity": "دائن", "revenue": "دائن", "expenses": "مدين"},
    },
    "examples": {
        "sale_cash": {"description": "بيع نقدي", "entries": ["مدين: نقدية", "دائن: مبيعات"], "explanation": "زادت النقدية وزاد الإيراد."},
        "sale_credit": {"description": "بيع آجل", "entries": ["مدين: ذمم الزبائن", "دائن: مبيعات/ضريبة حسب الإعدادات"], "explanation": "زاد حق المنشأة على الزبون وزاد الإيراد."},
        "payment_received": {"description": "تحصيل من زبون", "entries": ["مدين: نقدية/بنك", "دائن: ذمم الزبائن"], "explanation": "زادت النقدية وانخفضت الذمم."},
        "purchase_credit": {"description": "شراء على الحساب", "entries": ["مدين: مخزون/مصروف", "دائن: ذمم الموردين"], "explanation": "زاد الأصل/المصروف وزاد الالتزام."},
        "expense_cash": {"description": "مصروف نقدي", "entries": ["مدين: مصروف", "دائن: نقدية/بنك"], "explanation": "زاد المصروف ونقص النقد."},
    },
}


CHART_OF_ACCOUNTS = {
    "structure": {
        "1xxx": "أصول",
        "2xxx": "خصوم",
        "3xxx": "حقوق ملكية",
        "4xxx": "إيرادات",
        "5xxx": "مصروفات",
    },
    "note": "رموز الحسابات الدقيقة يجب أن تؤخذ من دليل الحسابات الفعلي في قاعدة النظام، وليس من أمثلة ثابتة.",
    "accounts": {
        "1000_CASH": {"name": "النقدية", "type": "ASSET", "normal_balance": "DEBIT"},
        "1010_BANK": {"name": "البنك", "type": "ASSET", "normal_balance": "DEBIT"},
        "1100_AR": {"name": "ذمم الزبائن", "type": "ASSET", "normal_balance": "DEBIT"},
        "1200_INVENTORY": {"name": "المخزون", "type": "ASSET", "normal_balance": "DEBIT"},
        "2000_AP": {"name": "ذمم الموردين", "type": "LIABILITY", "normal_balance": "CREDIT"},
        "2100_VAT_PAYABLE": {"name": "ضريبة قيمة مضافة مستحقة", "type": "LIABILITY", "normal_balance": "CREDIT", "note": "النسبة والقواعد تعتمد على الإعدادات والقانون الساري."},
        "3000_CAPITAL": {"name": "رأس المال", "type": "EQUITY", "normal_balance": "CREDIT"},
        "4000_SALES": {"name": "إيرادات المبيعات", "type": "REVENUE", "normal_balance": "CREDIT"},
        "4100_SERVICE_REVENUE": {"name": "إيرادات الخدمات", "type": "REVENUE", "normal_balance": "CREDIT"},
        "5000_COGS": {"name": "تكلفة البضاعة المباعة", "type": "EXPENSE", "normal_balance": "DEBIT"},
        "5200_SALARIES": {"name": "الرواتب والأجور", "type": "EXPENSE", "normal_balance": "DEBIT"},
    },
}


@dataclass
class BalanceFormula:
    entity: str
    formula: str
    components: List[str]
    positive_meaning: str
    negative_meaning: str
    examples: List[Dict[str, Any]]


BALANCE_FORMULAS = {
    "customer": BalanceFormula(
        entity="Customer - الزبون",
        formula="الرصيد = أثر المبيعات/الفواتير/الخدمات ± الدفعات ± القيود الافتتاحية/التسويات حسب سياسة النظام",
        components=["مبيعات", "فواتير", "خدمات", "دفعات", "أرصدة افتتاحية", "قيود GL"],
        positive_meaning="قد يعني عليه أو له حسب سياسة عرض الرصيد في النظام؛ لا تفسره دون الرجوع للصفحة/الدالة المعتمدة.",
        negative_meaning="قد يعني عليه أو له حسب سياسة عرض الرصيد في النظام؛ لا تفسره دون الرجوع للصفحة/الدالة المعتمدة.",
        examples=[{"scenario": "رصيد زبون", "meaning": "اعتمد تفسير النظام، لا افتراض المساعد."}],
    ),
    "supplier": BalanceFormula(
        entity="Supplier - المورد",
        formula="الرصيد = أثر المشتريات/الشحنات/الفواتير ± الدفعات ± التسويات حسب سياسة النظام",
        components=["مشتريات", "شحنات", "فواتير", "دفعات", "تسويات", "قيود GL"],
        positive_meaning="يفسر حسب سياسة رصيد المورد في النظام.",
        negative_meaning="يفسر حسب سياسة رصيد المورد في النظام.",
        examples=[{"scenario": "رصيد مورد", "meaning": "راجع شاشة المورد أو دالة تحديث الرصيد."}],
    ),
    "partner": BalanceFormula(
        entity="Partner - الشريك",
        formula="الرصيد = حصص/أرباح/تسويات الشريك حسب إعدادات الشراكة",
        components=["حصص مبيعات", "أرباح", "تسويات", "قيود GL"],
        positive_meaning="يفسر حسب سياسة رصيد الشريك في النظام.",
        negative_meaning="يفسر حسب سياسة رصيد الشريك في النظام.",
        examples=[{"scenario": "رصيد شريك", "meaning": "راجع تسويات الشركاء."}],
    ),
}


FINANCIAL_STATEMENTS = {
    "income_statement": {
        "name_ar": "قائمة الدخل",
        "name_en": "Income Statement",
        "purpose": "قياس الأداء المالي خلال فترة",
        "formula": "صافي الربح = الإيرادات - المصروفات",
        "sections": ["الإيرادات", "تكلفة المبيعات", "مجمل الربح", "المصروفات", "صافي الربح"],
    },
    "balance_sheet": {
        "name_ar": "الميزانية العمومية / المركز المالي",
        "name_en": "Balance Sheet",
        "purpose": "إظهار المركز المالي في تاريخ محدد",
        "equation": "الأصول = الخصوم + حقوق الملكية",
        "sections": ["الأصول", "الخصوم", "حقوق الملكية"],
    },
    "cash_flow_statement": {
        "name_ar": "قائمة التدفقات النقدية",
        "name_en": "Cash Flow Statement",
        "purpose": "تتبع حركة النقد",
        "sections": ["تشغيلية", "استثمارية", "تمويلية"],
    },
    "trial_balance": {
        "name_ar": "ميزان المراجعة",
        "name_en": "Trial Balance",
        "purpose": "فحص توازن القيود",
        "rule": "إجمالي المدين = إجمالي الدائن",
        "columns": ["رمز الحساب", "اسم الحساب", "المدين", "الدائن"],
    },
}


def get_professional_accounting_knowledge() -> Dict[str, Any]:
    return {
        "fundamentals": {"accounting_equation": ACCOUNTING_EQUATION, "double_entry": DOUBLE_ENTRY_SYSTEM},
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "balance_formulas": {key: asdict(value) for key, value in BALANCE_FORMULAS.items()},
        "financial_statements": FINANCIAL_STATEMENTS,
        "capabilities": [
            "شرح المعادلة المحاسبية",
            "شرح القيد المزدوج",
            "شرح دليل الحسابات كهيكل عام مع الرجوع للدليل الفعلي",
            "شرح أرصدة الزبائن والموردين دون افتراض اتجاه الإشارة",
            "شرح القوائم المالية الأساسية",
            "كشف مفاهيمي لأخطاء التوازن في القيود",
        ],
        "warnings": [
            "النسب الضريبية والقوانين يجب أن تأتي من إعدادات النظام أو مصدر رسمي حديث.",
            "تفسير موجب/سالب الرصيد يجب أن يطابق سياسة النظام الفعلية.",
        ],
    }


__all__ = [
    "get_professional_accounting_knowledge",
    "ACCOUNTING_EQUATION",
    "DOUBLE_ENTRY_SYSTEM",
    "CHART_OF_ACCOUNTS",
    "BALANCE_FORMULAS",
    "FINANCIAL_STATEMENTS",
]
