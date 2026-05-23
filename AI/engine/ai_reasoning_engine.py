"""AI Reasoning Engine.

Read-only reasoning helper. It avoids hard failures caused by model column naming
differences and does not execute write operations.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional


class ReasoningEngine:
    def __init__(self):
        self.knowledge_base: Dict[str, Any] = {}
        self.inference_rules: List[Dict[str, Any]] = []
        self._load_inference_rules()

    def reason_through_problem(self, query: str, available_data: Dict) -> Dict[str, Any]:
        steps: List[str] = []
        understanding = self._understand_query(query)
        steps.append(f"فهمت: {understanding['intent']}")
        if understanding["intent"] == "query_balance":
            return self._reason_balance_query(query, available_data or {}, steps)
        if understanding["intent"] == "explain_gl":
            return self._reason_gl_explanation(query, available_data or {}, steps)
        if understanding["intent"] == "explain_calculation":
            return self._reason_calculation(query, available_data or {}, steps)
        if understanding["intent"] == "tutorial":
            return self._reason_tutorial(query, available_data or {}, steps)
        return self._reason_general(query, available_data or {}, steps)

    def _understand_query(self, query: str) -> Dict[str, Any]:
        q_lower = str(query or "").lower()
        if any(w in q_lower for w in ["كم", "رصيد", "balance"]):
            return {"intent": "query_balance", "needs": ["entity_data", "transactions"]}
        if any(w in q_lower for w in ["قيد", "gl", "محاسبي", "ledger"]):
            return {"intent": "explain_gl", "needs": ["accounting_knowledge", "gl_rules"]}
        if any(w in q_lower for w in ["احسب", "calculate", "vat", "ضريبة"]):
            return {"intent": "explain_calculation", "needs": ["formula", "numbers"]}
        if any(w in q_lower for w in ["كيف", "how", "steps", "خطوات"]):
            return {"intent": "tutorial", "needs": ["procedure", "system_knowledge"]}
        return {"intent": "general", "needs": []}

    def _reason_balance_query(self, query: str, data: Dict, steps: List[str]) -> Dict[str, Any]:
        steps.append("استنتجت: سؤال عن رصيد")
        entity_name = self._extract_entity_name(query)
        steps.append(f"استخرجت الاسم: {entity_name if entity_name else 'غير محدد'}")
        if not entity_name:
            return {"answer": "لم أفهم اسم الزبون المطلوب. حدد اسم الزبون حتى أقرأ رصيده من النظام.", "confidence": 0.5, "reasoning_steps": steps}
        customer_data = self._find_in_database("Customer", "name", entity_name)
        if not customer_data:
            steps.append("لم أجد الزبون في قاعدة البيانات")
            route = self._route_for_keyword("customers") or "/customers"
            return {"answer": f"لم أجد زبوناً باسم '{entity_name}' في قاعدة البيانات.\n\nتحقق من الإملاء أو افتح قائمة الزبائن: {route}", "confidence": 0.7, "reasoning_steps": steps}
        steps.append(f"وجدت الزبون في قاعدة البيانات: ID={customer_data['id']}")
        sales = self._get_customer_sales(customer_data["id"])
        payments = self._get_customer_payments(customer_data["id"])
        steps.append(f"جلبت {len(sales)} عملية بيع/فاتورة")
        steps.append(f"جلبت {len(payments)} دفعة")
        total_sales = sum(Decimal(str(s.get("total", 0))) for s in sales)
        payments_in = sum(Decimal(str(p.get("amount", 0))) for p in payments if str(p.get("direction", "IN")).upper() == "IN")
        payments_out = sum(Decimal(str(p.get("amount", 0))) for p in payments if str(p.get("direction", "")).upper() == "OUT")
        stored_balance = customer_data.get("balance")
        calculated_balance = total_sales - payments_in + payments_out
        balance = Decimal(str(stored_balance)) if stored_balance is not None else calculated_balance
        steps.append(f"حسبت من الحركات المقروءة: {total_sales} - قبض {payments_in} + صرف/استرداد {payments_out} = {calculated_balance}")
        if stored_balance is not None:
            steps.append(f"استخدمت الرصيد المخزن على الزبون: {balance}")
        answer_parts = [
            f"🔍 بحثت عن: {entity_name}",
            f"✅ وجدته: زبون #{customer_data['id']}",
            "",
            "📊 تحليل الرصيد من البيانات المتاحة:",
            f"  • إجمالي المبيعات/الفواتير المقروءة: {float(total_sales):.2f}",
            f"  • الدفعات الواردة المقروءة: {float(payments_in):.2f}",
            f"  • الدفعات الصادرة/الاستردادات المقروءة: {float(payments_out):.2f}",
            f"  • الرصيد المسجل/المعتمد: {float(balance):.2f}",
            "",
            "لا أفسر إشارة الرصيد تلقائيًا كـ عليه/له إلا حسب سياسة شاشة الزبون أو دالة تحديث الرصيد في النظام.",
        ]
        return {"answer": "\n".join(answer_parts), "confidence": 0.88, "reasoning_steps": steps, "data_used": {"customer": customer_data, "sales_count": len(sales), "payments_count": len(payments)}}

    def _reason_gl_explanation(self, query: str, data: Dict, steps: List[str]) -> Dict[str, Any]:
        steps.append("استنتجت: سؤال عن قيود محاسبية")
        q_lower = str(query or "").lower()
        if "بيع" in q_lower or "sale" in q_lower:
            steps.append("الموضوع: قيد البيع")
            answer = """🔍 قيد فاتورة البيع - شرح عام:

القيد المعتاد:
مدين: ذمم الزبائن بإجمالي الفاتورة
دائن: المبيعات بالصافي
دائن: ضريبة القيمة المضافة إذا كانت مفعلة

المنطق:
1. الزبون صار عليه ذمة حسب سياسة النظام.
2. الإيراد زاد.
3. الضريبة التزام مستحق إن كانت مطبقة.

ملاحظة: أرقام الحسابات ونسبة الضريبة يجب قراءتها من إعدادات نظامك/دليلك المحاسبي، وليست افتراضًا ثابتًا من المساعد."""
            return {"answer": answer, "confidence": 0.9, "reasoning_steps": steps}
        return {"answer": "القيود المحاسبية تُنشأ حسب نوع المعاملة وإعدادات دليل الحسابات. القاعدة العامة: كل قيد يجب أن يكون متوازنًا، مجموع المدين = مجموع الدائن.", "confidence": 0.8, "reasoning_steps": steps}

    def _reason_calculation(self, query: str, data: Dict, steps: List[str]) -> Dict[str, Any]:
        steps.append("استنتجت: سؤال عن حساب")
        q_lower = str(query or "").lower()
        if "vat" in q_lower or "ضريبة" in q_lower:
            steps.append("الموضوع: حساب VAT")
            answer = """🔢 حساب VAT - شرح عام:

الصيغة:
VAT = الصافي بعد الخصم × نسبة الضريبة
الإجمالي = الصافي + VAT

الخطوات:
1. احسب مجموع البنود.
2. اطرح الخصم.
3. طبّق نسبة الضريبة من إعدادات النظام أو المصدر الرسمي.
4. اجمع الصافي + الضريبة.

مهم: لا أعتمد نسبة ثابتة هنا؛ النسبة يجب أن تأتي من إعدادات النظام أو قانون/مصدر رسمي حديث."""
            return {"answer": answer, "confidence": 0.9, "reasoning_steps": steps}
        return {"answer": "", "confidence": 0, "reasoning_steps": steps}

    def _reason_tutorial(self, query: str, data: Dict, steps: List[str]) -> Dict[str, Any]:
        steps.append("استنتجت: سؤال تعليمي")
        q_lower = str(query or "").lower()
        if "زبون" in q_lower and any(w in q_lower for w in ["أضيف", "اضيف", "add", "إنشاء", "انشاء"]):
            steps.append("الموضوع المطلوب: كيفية إضافة زبون جديد")
            route = self._route_for_keyword("customers create") or self._route_for_keyword("customers") or "صفحة الزبائن غير مفهرسة حالياً"
            answer = f"""📝 كيف تضيف زبون:

المسار حسب خريطة النظام: {route}

الخطوات:
1. افتح صفحة الزبائن.
2. اضغط إضافة زبون جديد إن كان الزر متاحًا حسب صلاحيتك.
3. أدخل الاسم ورقم الهاتف.
4. أدخل البيانات الاختيارية مثل العنوان والملاحظات.
5. راجع الرصيد الافتتاحي قبل الحفظ.
6. اضغط حفظ.

محاسبيًا: الرصيد الافتتاحي يؤثر على الذمم حسب سياسة النظام، لذلك لا تدخله إلا بعد التأكد."""
            return {"answer": answer, "confidence": 0.85, "reasoning_steps": steps}
        return {"answer": "", "confidence": 0, "reasoning_steps": steps}

    def _reason_general(self, query: str, data: Dict, steps: List[str]) -> Dict[str, Any]:
        return {"answer": "", "confidence": 0, "reasoning_steps": steps}

    def _extract_entity_name(self, query: str) -> Optional[str]:
        patterns = [r"رصيد\s+(?:الزبون\s+)?([^\s،.؟?]+)", r"balance\s+of\s+(\w+)", r"customer\s+(\w+)", r"الزبون\s+([^\s،.؟?]+)"]
        for pattern in patterns:
            match = re.search(pattern, str(query or ""), re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _route_for_keyword(self, keyword: str) -> Optional[str]:
        try:
            from AI.engine.ai_auto_discovery import find_route_by_keyword
            info = find_route_by_keyword(keyword)
            if info and info.get("matches"):
                route = info["matches"][0]
                return route.get("url") or route.get("path") or route.get("rule")
        except Exception:
            pass
        return None

    def _find_in_database(self, model_name: str, field: str, value: Any) -> Optional[Dict[str, Any]]:
        try:
            from models import Customer, Product, Supplier
            model_map = {"Customer": Customer, "Supplier": Supplier, "Product": Product}
            model = model_map.get(model_name)
            if not model or not hasattr(model, field):
                return None
            entity = model.query.filter(getattr(model, field).ilike(f"%{value}%")).first()
            if entity:
                return {"id": entity.id, "name": getattr(entity, "name", ""), "balance": float(getattr(entity, "balance", 0) or 0)}
        except Exception:
            pass
        return None

    def _get_customer_sales(self, customer_id: int) -> List[Dict[str, Any]]:
        try:
            from models import Sale, SaleStatus
            query = Sale.query.filter_by(customer_id=customer_id)
            if hasattr(Sale, "status") and hasattr(SaleStatus, "CANCELLED"):
                query = query.filter(Sale.status != SaleStatus.CANCELLED.value)
            sales = query.limit(500).all()
            output = []
            for sale in sales:
                amount = getattr(sale, "total_amount", None)
                date = getattr(sale, "sale_date", None) or getattr(sale, "created_at", None)
                output.append({"id": sale.id, "date": date.isoformat() if date else None, "total": float(amount or 0)})
            return output
        except Exception:
            return []

    def _get_customer_payments(self, customer_id: int) -> List[Dict[str, Any]]:
        try:
            from models import Payment, PaymentStatus
            query = Payment.query.filter_by(customer_id=customer_id) if hasattr(Payment, "customer_id") else None
            if query is None:
                return []
            if hasattr(Payment, "status") and hasattr(PaymentStatus, "FAILED"):
                query = query.filter(Payment.status != PaymentStatus.FAILED.value)
            payments = query.limit(500).all()
            output = []
            for payment in payments:
                amount = getattr(payment, "total_amount", 0)
                date = getattr(payment, "payment_date", None) or getattr(payment, "created_at", None)
                direction = getattr(payment, "direction", "IN")
                output.append({"id": payment.id, "date": date.isoformat() if date else None, "amount": float(amount or 0), "direction": getattr(direction, "value", direction)})
            return output
        except Exception:
            return []

    def _load_inference_rules(self) -> None:
        self.inference_rules = [{"if": "query_about_balance", "then": ["find_entity", "get_transactions", "calculate", "explain"]}, {"if": "query_about_gl", "then": ["identify_transaction_type", "explain_accounts", "show_example"]}]


_reasoning_engine = None


def get_reasoning_engine() -> ReasoningEngine:
    global _reasoning_engine
    if _reasoning_engine is None:
        _reasoning_engine = ReasoningEngine()
    return _reasoning_engine


__all__ = ["ReasoningEngine", "get_reasoning_engine"]
