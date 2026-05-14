from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func

from extensions import db

_conversation_memory: Dict[str, Dict[str, Any]] = {}
MAX_MEMORY_MESSAGES = 50


def get_or_create_session_memory(session_id: str) -> Dict[str, Any]:
    session_id = str(session_id or "default")
    if session_id not in _conversation_memory:
        _conversation_memory[session_id] = {"session_id": session_id, "created_at": datetime.now(timezone.utc).isoformat(), "messages": [], "context": {}, "last_entities": []}
        try:
            if session_id.startswith("user_"):
                user_id = int(session_id.split("_", 1)[1])
                path = os.path.join("AI", "data", "conversations.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        rows = json.load(fh)
                    if isinstance(rows, list):
                        for row in [r for r in rows if r.get("user_id") == user_id][-10:]:
                            _conversation_memory[session_id]["messages"].append({"role": "user", "content": str(row.get("query", ""))[:4000], "timestamp": row.get("timestamp")})
                            _conversation_memory[session_id]["messages"].append({"role": "assistant", "content": str(row.get("response", ""))[:4000], "timestamp": row.get("timestamp")})
        except Exception:
            pass
    return _conversation_memory[session_id]


def add_to_memory(session_id: str, role: str, content: str):
    memory = get_or_create_session_memory(session_id)
    memory["messages"].append({"role": role, "content": str(content or "")[:8000], "timestamp": datetime.now(timezone.utc).isoformat()})
    memory["messages"] = memory["messages"][-MAX_MEMORY_MESSAGES:]


def clear_session_memory(session_id: str):
    _conversation_memory.pop(str(session_id or "default"), None)


def get_conversation_context(session_id: str) -> Dict[str, Any]:
    memory = get_or_create_session_memory(session_id)
    return {"message_count": len(memory["messages"]), "last_entities": memory.get("last_entities", []), "context": memory.get("context", {})}


def _company_profile() -> Dict[str, str]:
    try:
        from AI.engine.ai_service import get_company_profile
        return get_company_profile()
    except Exception:
        return {"company_name": "Azad company", "system_name": "نظام أزاد", "owner_display_name": "أحمد غنام", "owner_name": "Ahmad ghannam", "phone": "0562150193"}


def _route_for_keyword(keyword: str) -> Optional[str]:
    try:
        from AI.engine.ai_auto_discovery import find_route_by_keyword
        info = find_route_by_keyword(keyword)
        if info and info.get("matches"):
            match = info["matches"][0]
            return match.get("url") or match.get("path") or match.get("rule")
    except Exception:
        pass
    return None


def get_local_faq_responses() -> Dict[str, str]:
    company = _company_profile()
    return {
        "من أنت": f"أنا المساعد الذكي داخل {company['system_name']}. أجيب من بيانات النظام المتاحة أو أوضح أن البيانات غير كافية.",
        "ما قدراتك": "أبحث في بيانات النظام، أشرح القيود والأرصدة، أساعد في التنقل، وأحلل الأخطاء حسب المعلومات المتوفرة.",
        "اشرح رصيد العميل": "رصيد العميل يُقرأ من النظام. تفسير موجب أو سالب الرصيد يعتمد على سياسة الرصيد المطبقة في شاشة العميل أو دوال تحديث الرصيد.",
        "كيف أحسب الضريبة": "أقرأ نسبة الضريبة من إعدادات النظام عند توفرها، وأعرض تحذيرًا إذا لم تكن الإعدادات متوفرة.",
        "كيف أضيف عميل": f"صفحة العملاء حسب الخريطة الحالية: `{_route_for_keyword('customers create') or _route_for_keyword('customers') or 'غير مفهرس حالياً'}`",
        "شرح الصلاحيات": "الصلاحيات تعتمد على الأدوار والإعدادات الفعلية في النظام، ولا أفترض أسماء أدوار ثابتة.",
    }


def get_local_quick_answers() -> Dict[str, Any]:
    return {
        "greetings": {"patterns": ["مرحبا", "هلا", "السلام", "صباح", "مساء", "hello", "hi"], "responses": ["أهلاً، كيف أساعدك في النظام؟"]},
        "thanks": {"patterns": ["شكرا", "مشكور", "thanks", "thank you"], "responses": ["على الرحب والسعة."]},
        "help": {"patterns": ["مساعدة", "help", "ساعدني"], "responses": ["اسألني عن عميل، مورد، منتج، مبيعة، دفعة، مصروف، صيانة، مخزون، صفحة، أو خطأ."]},
    }


def _count_model(model_name: str) -> Optional[int]:
    try:
        import models
        model = getattr(models, model_name, None)
        return int(model.query.count()) if model is not None else None
    except Exception:
        return None


def _execute_count_command(message: str) -> Optional[str]:
    patterns = {r"عدد العملاء": ("Customer", "العملاء"), r"عدد الموردين": ("Supplier", "الموردين"), r"عدد المستخدمين": ("User", "المستخدمين"), r"عدد المنتجات": ("Product", "المنتجات"), r"عدد الفواتير": ("Invoice", "الفواتير"), r"عدد المبيعات": ("Sale", "المبيعات"), r"عدد الدفعات": ("Payment", "الدفعات")}
    for pattern, (model_name, label) in patterns.items():
        if re.search(pattern, message):
            count = _count_model(model_name)
            if count is not None:
                return f"عدد {label} المسجلين حالياً: **{count}**"
    return None


def _execute_currency_command(message: str) -> Optional[str]:
    match = re.search(r"سعر (?:صرف )?(\w+)", message)
    if not match:
        return None
    currency_map = {"دولار": "USD", "الدولار": "USD", "usd": "USD", "يورو": "EUR", "اليورو": "EUR", "eur": "EUR", "دينار": "JOD", "الدينار": "JOD", "jod": "JOD", "شيكل": "ILS", "الشيكل": "ILS", "ils": "ILS"}
    code = currency_map.get(match.group(1).lower())
    if not code:
        return None
    try:
        from models import ExchangeRate
        row = ExchangeRate.query.filter_by(base_code=code, quote_code="ILS", is_active=True).order_by(ExchangeRate.valid_from.desc()).first()
        if row:
            when = row.valid_from.strftime("%Y-%m-%d") if row.valid_from else "غير مؤرخ"
            return f"آخر سعر مسجل: 1 {code} = **{float(row.rate):.4f}** ILS | المصدر: {row.source or 'system'} | التاريخ: {when}"
    except Exception:
        pass
    return f"لا يوجد سعر صرف مسجل حالياً لـ {code} مقابل ILS."


def _execute_navigation_command(message: str) -> Optional[str]:
    if not re.search(r"(اذهب|انتقل|افتح|رابط|صفحة)", message):
        return None
    keyword_map = {"العملاء": "customers", "الموردين": "suppliers vendors", "الفواتير": "invoices sales", "المبيعات": "sales", "المخزون": "inventory warehouses", "المستودعات": "warehouses", "التقارير": "reports", "الإعدادات": "settings", "المستخدمين": "users"}
    for label, keyword in keyword_map.items():
        if label in message:
            return f"الرابط حسب خريطة النظام: `{_route_for_keyword(keyword) or 'غير مفهرس حالياً'}`"
    return f"الرابط حسب خريطة النظام: `{_route_for_keyword(message) or 'غير مفهرس حالياً'}`"


def _execute_customer_analysis(message: str, session_id: str = None) -> Optional[str]:
    match = re.search(r"(?:تحليل|رصيد|وضع|كشف)\s+عميل\s+(.+)", message)
    name = match.group(1).strip() if match else None
    memory = get_or_create_session_memory(session_id) if session_id else {}
    if not name and re.search(r"(رصيده|حسابه|كشفه|وضعه)", message) and memory.get("context", {}).get("last_customer_id"):
        try:
            from models import Customer
            c = db.session.get(Customer, int(memory["context"]["last_customer_id"]))
            name = c.name if c else None
        except Exception:
            name = None
    if not name:
        return None
    try:
        from models import Customer, Invoice, Payment
        customer = Customer.query.filter(Customer.name.ilike(f"%{name}%")).first()
        if not customer:
            return f"لم أجد عميلاً باسم: **{name}**"
        if session_id:
            memory["context"]["last_customer_id"] = customer.id
            memory["context"]["last_topic"] = "customer_analysis"
        balance = float(getattr(customer, "balance", 0) or 0)
        invoice_count = Invoice.query.filter_by(customer_id=customer.id).count()
        payment_count = Payment.query.filter_by(customer_id=customer.id).count()
        return f"العميل: **{customer.name}**\nالهاتف: {customer.phone or 'غير مسجل'}\nالرصيد المسجل: {balance:.2f} {getattr(customer, 'currency', None) or 'ILS'}\nعدد الفواتير: {invoice_count}\nعدد الدفعات المباشرة: {payment_count}\nتفسير إشارة الرصيد يعتمد على سياسة النظام."
    except Exception as exc:
        return f"تعذر تحليل العميل: {exc}"


def _execute_financial_snapshot(message: str) -> Optional[str]:
    if not re.search(r"(وضع مالي|كيف الشغل|ملخص مالي)", message):
        return None
    try:
        from models import Expense, Invoice, Sale
        today = date.today()
        month_start = today.replace(day=1)
        sales_today = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.sale_date) == today).scalar() or 0
        sales_month = db.session.query(func.sum(Sale.total_amount)).filter(Sale.sale_date >= month_start).scalar() or 0
        invoice_month = db.session.query(func.sum(Invoice.total_amount)).filter(Invoice.invoice_date >= month_start).scalar() or 0
        exp_today = db.session.query(func.sum(Expense.amount)).filter(func.date(Expense.date) == today).scalar() or 0 if hasattr(Expense, "date") else 0
        exp_month = db.session.query(func.sum(Expense.amount)).filter(Expense.date >= month_start).scalar() or 0 if hasattr(Expense, "date") else 0
        return f"مبيعات اليوم: {float(sales_today):.2f}\nمصروفات اليوم: {float(exp_today):.2f}\nمبيعات الشهر: {float(sales_month):.2f}\nفواتير الشهر: {float(invoice_month):.2f}\nمصروفات الشهر: {float(exp_month):.2f}\nصافي تقديري: {float(sales_month - exp_month):.2f}"
    except Exception as exc:
        return f"تعذر جلب الملخص المالي: {exc}"


def _execute_local_command(message: str, session_id: str = None) -> Optional[str]:
    message = str(message or "").lower().strip()
    handlers = [_execute_count_command, _execute_currency_command, _execute_navigation_command, lambda msg: _execute_customer_analysis(msg, session_id), _execute_financial_snapshot]
    for handler in handlers:
        result = handler(message)
        if result:
            return result
    return None


def match_local_response(message: str, session_id: str = None) -> Optional[str]:
    message = str(message or "").strip()
    if not message:
        return None
    command = _execute_local_command(message, session_id=session_id)
    if command:
        return command
    lowered = message.lower()
    for item in get_local_quick_answers().values():
        if any(pattern.lower() in lowered for pattern in item.get("patterns", [])):
            responses = item.get("responses", [])
            return responses[0] if responses else None
    for key, response in get_local_faq_responses().items():
        if key.lower() in lowered:
            return response
    return None


__all__ = ["get_or_create_session_memory", "add_to_memory", "clear_session_memory", "get_conversation_context", "get_local_faq_responses", "get_local_quick_answers", "match_local_response"]
