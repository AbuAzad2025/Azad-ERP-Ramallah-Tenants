"""Unified AI service facade.

Public API is kept stable for routes and other engines. The service reads live
schema/database data where possible, uses discovered routes, uses encrypted API
provider keys from ai_management, and never fabricates tax rates, page links, or
model metrics.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_, text

from extensions import cache, db
from models import SystemSettings
from AI.engine.ai_auto_discovery import auto_discover_if_needed, find_route_by_keyword, get_route_suggestions
from AI.engine.ai_data_awareness import auto_build_if_needed
from AI.engine.ai_gl_knowledge import get_gl_knowledge_for_ai
from AI.engine.ai_knowledge import analyze_error, format_error_response, get_knowledge_base, get_local_faq_responses, get_local_quick_rules
from AI.engine.ai_knowledge_finance import calculate_palestine_income_tax, calculate_vat
from AI.engine.ai_self_review import generate_self_audit_report, log_interaction
from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

_conversation_memory: Dict[str, Dict[str, Any]] = {}
_last_audit_time = None
_groq_failures: List[datetime] = []
_local_fallback_mode = True
_system_state = "LOCAL_ONLY"

LOCAL_MODE_LOG_FILE = "ai_local_mode_log.json"
MAX_MEMORY_MESSAGES = 50

DEFAULT_COMPANY_PROFILE = {
    "company_name": "Azad company",
    "system_name": "نظام أزاد لإدارة الكراج والمحاسبة",
    "owner_name": "Ahmad ghannam",
    "owner_display_name": "المهندس أحمد غنام",
    "phone": "0562150193",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return default


def _safe_count(model, query_func=None) -> int:
    try:
        return int(query_func() if query_func else model.query.count())
    except Exception:
        return 0


def _cached_count(model, key_suffix: str, query_func=None, ttl: int = 300) -> int:
    cache_key = f"ai_system_context_{key_suffix}"
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return int(cached)
    except Exception:
        pass
    value = _safe_count(model, query_func)
    try:
        cache.set(cache_key, value, timeout=ttl)
    except Exception:
        pass
    return value


def _first_attr(model_or_obj, names: List[str]):
    for name in names:
        value = getattr(model_or_obj, name, None)
        if value is not None:
            return value
    return None


def _sum_column(model, names: List[str], filters: Optional[List[Any]] = None) -> Decimal:
    column = _first_attr(model, names)
    if column is None:
        return Decimal("0")
    try:
        query = db.session.query(func.sum(column))
        for flt in filters or []:
            query = query.filter(flt)
        return Decimal(str(query.scalar() or 0))
    except Exception:
        return Decimal("0")


def _ilike(model, *fields: str, value: str):
    clauses = []
    for field in fields:
        col = getattr(model, field, None)
        if col is not None:
            clauses.append(col.ilike(f"%{value}%"))
    return or_(*clauses) if clauses else None


def _setting(key: str, default: str = "") -> str:
    try:
        setting = SystemSettings.query.filter_by(key=key).first()
        if setting and setting.value not in (None, ""):
            return str(setting.value)
    except Exception:
        pass
    return default


def _knowledge_structure() -> Dict[str, Any]:
    try:
        kb = get_knowledge_base()
        if hasattr(kb, "get_system_structure"):
            return kb.get_system_structure()
        knowledge = getattr(kb, "knowledge", {}) or {}
        templates = knowledge.get("templates", {}) or {}
        return {
            "models_count": len(knowledge.get("models", {})),
            "routes_count": len(knowledge.get("routes", {})),
            "templates_count": sum(len(v) if isinstance(v, list) else 1 for v in templates.values()),
            "relationships_count": len(knowledge.get("relationships", {})),
            "business_rules_count": len(knowledge.get("business_rules", [])),
            "models": list(knowledge.get("models", {}).keys()),
            "routes": knowledge.get("routes", {}),
        }
    except Exception:
        return {"models_count": 0, "routes_count": 0, "templates_count": 0, "relationships_count": 0, "business_rules_count": 0, "models": [], "routes": {}}


def _format_nullable_amount(value: Any) -> str:
    if value is None:
        return "غير محسوب"
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def get_company_profile() -> Dict[str, str]:
    profile = dict(DEFAULT_COMPANY_PROFILE)
    keys = {
        "company_name": ["company_name", "COMPANY_NAME", "business_name"],
        "system_name": ["system_name", "SYSTEM_NAME", "app_name"],
        "owner_name": ["owner_name", "OWNER_NAME", "developer_name"],
        "owner_display_name": ["owner_display_name", "OWNER_DISPLAY_NAME", "developer_display_name"],
        "phone": ["company_phone", "phone", "COMPANY_PHONE", "owner_phone"],
    }
    for out_key, setting_keys in keys.items():
        for setting_key in setting_keys:
            value = _setting(setting_key, "")
            if value:
                profile[out_key] = value
                break
    return profile


def get_system_setting(key, default=""):
    return _setting(str(key), default)


def _latest_usd_ils_rate() -> str:
    try:
        from models import ExchangeRate
        row = ExchangeRate.query.filter_by(base_code="USD", quote_code="ILS", is_active=True).order_by(ExchangeRate.valid_from.desc()).first()
        if row:
            valid_from = row.valid_from.strftime("%Y-%m-%d") if getattr(row, "valid_from", None) else "غير مؤرخ"
            return f"{float(row.rate):.4f} ({valid_from}, {row.source or 'system'})"
    except Exception:
        pass
    return "غير متوفر"


def gather_system_context():
    try:
        import psutil
        from models import AuditLog, Customer, Expense, Note, Payment, Product, Role, ServiceRequest, ServiceStatus, Shipment, StockLevel, Supplier, User, Warehouse
        company = get_company_profile()
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        today = _now().date()
        pending_status = ServiceStatus.PENDING.value
        completed_status = ServiceStatus.COMPLETED.value
        db_size = "غير معروف"
        try:
            result = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
            db_size = f"{float(result or 0) / (1024 ** 2):.2f} MB"
        except Exception:
            pass
        total_users = _cached_count(User, "total_users")
        active_users = _cached_count(User, "active_users", lambda: User.query.filter_by(is_active=True).count())
        total_services = _cached_count(ServiceRequest, "total_services")
        total_customers = _cached_count(Customer, "total_customers")
        total_suppliers = _cached_count(Supplier, "total_suppliers")
        total_products = _cached_count(Product, "total_products")
        total_warehouses = _cached_count(Warehouse, "total_warehouses")
        products_in_stock = _cached_count(StockLevel, "products_in_stock", lambda: db.session.query(func.count(func.distinct(StockLevel.product_id))).scalar() or 0)
        roles = []
        try:
            roles = [r.name for r in Role.query.limit(10).all()]
        except Exception:
            pass
        current_stats = (
            f"المستخدمين: {total_users} | النشطين: {active_users}\n"
            f"الصيانة: {total_services} طلب\n"
            f"الزبائن: {total_customers} | الموردين: {total_suppliers}\n"
            f"المنتجات: {total_products} | منتجات بالمخزون: {products_in_stock}\n"
            f"المخازن: {total_warehouses}\n"
            f"CPU: {cpu_usage:.1f}% | RAM: {memory.percent:.1f}%"
        )
        return {
            **company,
            "version": _setting("SYSTEM_VERSION", "غير محدد"),
            "roles_count": _cached_count(Role, "roles_count"),
            "roles": roles,
            "total_users": total_users,
            "active_users": active_users,
            "total_services": total_services,
            "pending_services": _cached_count(ServiceRequest, "pending_services", lambda: ServiceRequest.query.filter_by(status=pending_status).count()),
            "completed_services": _cached_count(ServiceRequest, "completed_services", lambda: ServiceRequest.query.filter_by(status=completed_status).count()),
            "total_products": total_products,
            "products_in_stock": products_in_stock,
            "total_customers": total_customers,
            "active_customers": _cached_count(Customer, "active_customers", lambda: Customer.query.filter_by(is_active=True).count()),
            "total_vendors": total_suppliers,
            "total_suppliers": total_suppliers,
            "total_payments": _cached_count(Payment, "total_payments"),
            "payments_today": _safe_count(Payment, lambda: Payment.query.filter(func.date(Payment.payment_date) == today).count()),
            "total_expenses": _cached_count(Expense, "total_expenses"),
            "total_warehouses": total_warehouses,
            "total_notes": _cached_count(Note, "total_notes"),
            "total_shipments": _cached_count(Shipment, "total_shipments"),
            "failed_logins": _safe_count(AuditLog, lambda: AuditLog.query.filter(AuditLog.action == "login_failed", AuditLog.created_at >= _now().replace(hour=0, minute=0, second=0, microsecond=0)).count()),
            "total_audit_logs": _cached_count(AuditLog, "total_audit_logs"),
            "recent_actions": _safe_count(AuditLog, lambda: AuditLog.query.order_by(AuditLog.created_at.desc()).limit(5).count()),
            "latest_usd_ils_rate": _latest_usd_ils_rate(),
            "cpu_usage": round(cpu_usage, 1),
            "memory_usage": round(memory.percent, 1),
            "db_size": db_size,
            "db_health": "نشط",
            "current_stats": current_stats,
        }
    except Exception as exc:
        company = get_company_profile()
        return {**company, "version": "غير محدد", "roles_count": 0, "roles": [], "current_stats": f"خطأ في جمع الإحصائيات: {exc}"}


def get_system_navigation_context():
    try:
        system_map = auto_discover_if_needed()
        if system_map:
            return {"total_routes": system_map.get("statistics", {}).get("total_routes", 0), "total_templates": system_map.get("statistics", {}).get("total_templates", 0), "blueprints": system_map.get("blueprints", []), "modules": system_map.get("modules", []), "categories": {k: len(v) for k, v in system_map.get("routes", {}).get("by_category", {}).items()}}
    except Exception:
        pass
    return {}


def get_data_awareness_context():
    try:
        schema = auto_build_if_needed()
        if schema:
            return {"total_models": schema.get("statistics", {}).get("total_tables", 0), "total_columns": schema.get("statistics", {}).get("total_columns", 0), "total_relationships": schema.get("statistics", {}).get("total_relationships", 0), "functional_modules": list((schema.get("functional_mapping") or {}).keys()), "available_models": list((schema.get("models") or {}).keys())}
    except Exception:
        pass
    return {}


def analyze_question_intent(question):
    q = str(question or "").lower()
    intent = {"type": "general", "entities": [], "time_scope": None, "action": "query", "currency": None, "accounting": False, "executable": False, "navigation": False}
    if any(w in q for w in ["أنشئ", "انشئ", "create", "add", "أضف", "اضف", "سجل"]):
        intent.update(type="command", action="create", executable=True)
    elif any(w in q for w in ["احذف", "delete", "remove", "أزل", "ازل"]):
        intent.update(type="command", action="delete", executable=True)
    elif any(w in q for w in ["عدّل", "عدل", "update", "modify", "غيّر", "غير"]):
        intent.update(type="command", action="update", executable=True)
    elif any(w in q for w in ["كم", "عدد", "count", "how many"]):
        intent["type"] = "count"
    elif any(w in q for w in ["كيف", "how", "why", "لماذا", "شرح"]):
        intent["type"] = "explanation"
    elif any(w in q for w in ["تقرير", "report", "تحليل", "analysis", "حلل"]):
        intent["type"] = "report"
    elif any(w in q for w in ["خطأ", "error", "مشكلة", "problem", "bug"]):
        intent["type"] = "troubleshooting"
    if any(w in q for w in ["اذهب", "افتح", "صفحة", "وين", "أين", "اين", "رابط", "عرض", "دلني", "وصلني"]):
        intent.update(type="navigation", navigation=True)
    if any(w in q for w in ["شيقل", "ils", "₪"]):
        intent.update(currency="ILS", accounting=True)
    elif any(w in q for w in ["دولار", "usd", "$"]):
        intent.update(currency="USD", accounting=True)
    elif any(w in q for w in ["دينار", "jod"]):
        intent.update(currency="JOD", accounting=True)
    elif any(w in q for w in ["يورو", "eur", "€"]):
        intent.update(currency="EUR", accounting=True)
    if any(w in q for w in ["ربح", "خسارة", "دخل", "profit", "loss", "revenue", "مالي", "محاسب", "رصيد", "دفتر", "قيد", "vat", "ضريبة"]):
        intent["accounting"] = True
    if any(w in q for w in ["اليوم", "today", "الآن", "الان", "now"]):
        intent["time_scope"] = "today"
    elif any(w in q for w in ["الأسبوع", "الاسبوع", "week", "أسبوع", "اسبوع"]):
        intent["time_scope"] = "week"
    elif any(w in q for w in ["الشهر", "month", "شهر"]):
        intent["time_scope"] = "month"
    elif any(w in q for w in ["السنة", "year", "سنة", "عام"]):
        intent["time_scope"] = "year"
    entity_map = {"Customer": ["زبون", "زبائن", "زبون", "customer", "client"], "ServiceRequest": ["صيانة", "service", "تشخيص", "عطل", "إصلاح", "اصلاح"], "Product": ["منتج", "منتجات", "product", "قطع", "قطعة"], "Warehouse": ["مخزن", "مخازن", "warehouse", "مستودع", "مخزون"], "Invoice": ["فاتورة", "فواتير", "invoice"], "Payment": ["دفع", "دفعة", "مدفوعات", "payment"], "Expense": ["مصروف", "مصاريف", "نفقات", "نفقة", "expense"], "Supplier": ["مورد", "موردين", "supplier", "vendor"], "Sale": ["بيع", "مبيعات", "sale", "sales"]}
    for entity, keywords in entity_map.items():
        if any(k in q for k in keywords):
            intent["entities"].append(entity)
    return intent


def get_or_create_session_memory(session_id):
    session_id = str(session_id or "default")
    if session_id not in _conversation_memory:
        _conversation_memory[session_id] = {"messages": [], "context": {}, "created_at": _now(), "last_updated": _now(), "user_preferences": {}, "topics": [], "entities_mentioned": {}, "last_intent": None}
    _conversation_memory[session_id]["last_updated"] = _now()
    return _conversation_memory[session_id]


def add_to_memory(session_id, role, content, context=None):
    memory = get_or_create_session_memory(session_id)
    entry = {"role": role, "content": str(content or "")[:8000], "timestamp": _now().isoformat()}
    if context:
        entry["context"] = {"intent": context.get("intent"), "entities": context.get("entities"), "sentiment": context.get("sentiment")}
        for entity in context.get("entities", []) or []:
            memory["entities_mentioned"][entity] = memory["entities_mentioned"].get(entity, 0) + 1
        if context.get("intent"):
            memory["last_intent"] = context["intent"]
    memory["messages"].append(entry)
    memory["messages"] = memory["messages"][-MAX_MEMORY_MESSAGES:]


def get_conversation_context(session_id):
    memory = get_or_create_session_memory(session_id)
    return {"message_count": len(memory["messages"]), "duration": (_now() - memory["created_at"]).total_seconds(), "most_mentioned_entities": sorted(memory["entities_mentioned"].items(), key=lambda x: x[1], reverse=True)[:5], "last_intent": memory.get("last_intent"), "recent_topics": memory.get("topics", [])[-5:]}


def _time_range(scope: Optional[str]) -> Tuple[datetime, datetime]:
    end = _now()
    if scope == "today":
        return end.replace(hour=0, minute=0, second=0, microsecond=0), end
    if scope == "week":
        return end - timedelta(days=7), end
    if scope == "month":
        return end - timedelta(days=30), end
    if scope == "year":
        return end - timedelta(days=365), end
    return end - timedelta(days=90), end


def deep_data_analysis(query, context):
    result = {"success": True, "insights": [], "warnings": [], "recommendations": [], "data_summary": {}}
    try:
        from models import Customer, Expense, Invoice
        entities = set(context.get("entities", []) or [])
        start, end = _time_range(context.get("time_scope"))
        if "Customer" in entities:
            total = Customer.query.count()
            active = db.session.query(func.count(func.distinct(Invoice.customer_id))).filter(Invoice.invoice_date >= start).scalar() or 0
            rate = (active / total * 100) if total else 0
            result["data_summary"]["customers"] = {"total": total, "active": active, "activity_rate": round(rate, 1)}
        if "Invoice" in entities or "Sale" in entities or "مبيعات" in str(query):
            current_sales = _sum_column(Invoice, ["total_amount"], [Invoice.invoice_date >= start, Invoice.invoice_date <= end])
            result["data_summary"]["sales"] = {"current": float(current_sales)}
        if "Expense" in entities or "مصروف" in str(query) or "نفقات" in str(query):
            date_col = _first_attr(Expense, ["date", "created_at"])
            filters = [date_col >= start] if date_col is not None else []
            result["data_summary"]["expenses"] = {"total": float(_sum_column(Expense, ["amount", "total_amount"], filters))}
    except Exception as exc:
        result.update(success=False, error=str(exc))
    return result


def analyze_accounting_data(currency=None):
    try:
        from models import Expense, Invoice
        analysis = {"total_revenue": 0.0, "total_expenses": 0.0, "net_profit": 0.0, "by_currency": {}}
        for inv in Invoice.query.limit(10000).all():
            curr = getattr(inv, "currency", None) or "ILS"
            if currency and curr != currency:
                continue
            amount = _safe_float(getattr(inv, "total_amount", 0))
            analysis["by_currency"].setdefault(curr, {"revenue": 0.0, "expenses": 0.0, "profit": 0.0})
            analysis["by_currency"][curr]["revenue"] += amount
            analysis["total_revenue"] += amount
        for exp in Expense.query.limit(10000).all():
            curr = getattr(exp, "currency", None) or "ILS"
            if currency and curr != currency:
                continue
            amount = _safe_float(getattr(exp, "amount", 0) or getattr(exp, "total_amount", 0))
            analysis["by_currency"].setdefault(curr, {"revenue": 0.0, "expenses": 0.0, "profit": 0.0})
            analysis["by_currency"][curr]["expenses"] += amount
            analysis["total_expenses"] += amount
        for values in analysis["by_currency"].values():
            values["profit"] = values["revenue"] - values["expenses"]
        analysis["net_profit"] = analysis["total_revenue"] - analysis["total_expenses"]
        return analysis
    except Exception as exc:
        return {"error": str(exc)}


def generate_smart_report(intent):
    try:
        from models import Customer, Expense, Invoice, Payment, Product, ServiceRequest, ServiceStatus, Supplier, Warehouse
        if intent.get("accounting"):
            return {"type": "accounting_report", "data": analyze_accounting_data(intent.get("currency")), "generated_at": _now().strftime("%Y-%m-%d %H:%M")}
        report = {"title": "تقرير مختصر", "generated_at": _now().strftime("%Y-%m-%d %H:%M"), "sections": []}
        today = _now().date()
        if intent.get("time_scope") == "today":
            report["title"] = "تقرير اليوم"
            report["sections"].append({"name": "الصيانة اليوم", "data": {"total": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today).count()), "completed": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today, ServiceRequest.status == ServiceStatus.COMPLETED.value).count()), "pending": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today, ServiceRequest.status == ServiceStatus.PENDING.value).count())}})
            report["sections"].append({"name": "المدفوعات اليوم", "data": {"count": _safe_count(Payment, lambda: Payment.query.filter(func.date(Payment.payment_date) == today).count()), "total": float(_sum_column(Payment, ["total_amount"], [func.date(Payment.payment_date) == today]))}})
        models = {"Customer": Customer, "ServiceRequest": ServiceRequest, "Product": Product, "Supplier": Supplier, "Warehouse": Warehouse, "Expense": Expense, "Invoice": Invoice}
        for entity in intent.get("entities", []) or []:
            model = models.get(entity)
            if model:
                report["sections"].append({"name": f"إحصائيات {entity}", "data": {"total": _safe_count(model)}})
        return report
    except Exception as exc:
        return {"error": str(exc)}


def build_system_message(system_context):
    identity = get_system_identity()
    company = get_company_profile()
    structure = _knowledge_structure()
    nav_context = get_system_navigation_context()
    data_context = get_data_awareness_context()
    gl_knowledge = get_gl_knowledge_for_ai()
    modules_hint = (nav_context.get("modules") or data_context.get("functional_modules") or [])[:15]
    return f"""أنت {identity['name']} داخل {company['system_name']}.

هوية النظام والشركة:
- الشركة: {company['company_name']}
- المالك/المطور: {company['owner_display_name']} ({company['owner_name']})
- هاتف التواصل: {company['phone']}

وضع التشغيل: {identity['mode']}
Groq API: {identity['status']['groq_api']}

قواعد الإجابة:
- استخدم البيانات الفعلية من قاعدة البيانات أو من نص السؤال فقط.
- لا تخترع أرقامًا أو أسماء صفحات أو نسبًا.
- إن كانت البيانات غير كافية، قل ذلك بوضوح.
- لا تنفذ حذف/تعديل/إنشاء إلا عبر طبقة الصلاحيات والتنفيذ.
- القيم الضريبية والقانونية المتغيرة يجب قراءتها من الإعدادات أو مصدر رسمي حديث.

ملخص حي من النظام:
{system_context.get('current_stats', 'غير متوفر')}

فهرسة النظام:
- الموديلات: {structure.get('models_count', 0)}
- المسارات: {structure.get('routes_count', 0)}
- القوالب: {structure.get('templates_count', 0)}
- العلاقات: {structure.get('relationships_count', 0)}
- قواعد العمل: {structure.get('business_rules_count', 0)}

وحدات معروفة:
{', '.join(modules_hint) if modules_hint else 'غير متوفرة'}

معرفة GL:
{', '.join(gl_knowledge.get('capabilities', [])[:6])}

آخر سعر USD/ILS من النظام: {system_context.get('latest_usd_ils_rate', 'غير متوفر')}
""".strip()


def query_accounting_data(query_type, filters=None):
    results: Dict[str, Any] = {}
    filters = filters or {}
    try:
        from models import Account, Customer, Expense, GLBatch, GLEntry, Payment, Sale, Supplier
        if query_type == "customer_balance":
            customer = db.session.get(Customer, int(filters.get("customer_id"))) if filters.get("customer_id") else None
            if customer:
                results["customer"] = {"id": customer.id, "name": customer.name, "balance": _safe_float(getattr(customer, "balance", 0))}
        elif query_type == "supplier_balance":
            supplier = db.session.get(Supplier, int(filters.get("supplier_id"))) if filters.get("supplier_id") else None
            if supplier:
                results["supplier"] = {"id": supplier.id, "name": supplier.name, "balance": _safe_float(getattr(supplier, "balance", 0))}
        elif query_type in {"gl_account_summary", "account_balance"}:
            account_code = filters.get("account_code")
            account_col = _first_attr(GLEntry, ["account_code", "account"])
            debit_col = _first_attr(GLEntry, ["debit_amount", "debit"])
            credit_col = _first_attr(GLEntry, ["credit_amount", "credit"])
            if account_col is None or debit_col is None or credit_col is None:
                return {"error": "GLEntry columns are not compatible"}
            q = db.session.query(account_col.label("account"), func.sum(debit_col).label("total_debit"), func.sum(credit_col).label("total_credit"))
            batch_fk = _first_attr(GLEntry, ["batch_id", "gl_batch_id"])
            if batch_fk is not None:
                q = q.join(GLBatch, batch_fk == GLBatch.id)
                date_col = _first_attr(GLBatch, ["batch_date", "date", "created_at"])
                if filters.get("date_from") and date_col is not None:
                    q = q.filter(date_col >= filters["date_from"])
                if filters.get("date_to") and date_col is not None:
                    q = q.filter(date_col <= filters["date_to"])
            if account_code:
                q = q.filter(account_col == account_code)
            rows = q.group_by(account_col).all()
            results["gl_summary"] = [{"account": row.account, "total_debit": _safe_float(row.total_debit), "total_credit": _safe_float(row.total_credit), "balance": _safe_float(row.total_debit) - _safe_float(row.total_credit)} for row in rows]
            if query_type == "account_balance" and account_code and results["gl_summary"]:
                account = Account.query.filter_by(code=account_code).first() if hasattr(Account, "code") else None
                results["account_balance"] = {**results["gl_summary"][0], "account_name": getattr(account, "name", account_code), "account_code": account_code}
        elif query_type == "financial_summary":
            start = filters.get("date_from", _now() - timedelta(days=30))
            end = filters.get("date_to", _now())
            sale_date = _first_attr(Sale, ["sale_date", "created_at"])
            expense_date = _first_attr(Expense, ["date", "created_at"])
            payment_date = _first_attr(Payment, ["payment_date", "created_at"])
            sale_filters = [sale_date >= start, sale_date <= end] if sale_date is not None else []
            expense_filters = [expense_date >= start, expense_date <= end] if expense_date is not None else []
            payment_filters = [payment_date >= start, payment_date <= end] if payment_date is not None else []
            total_sales = _sum_column(Sale, ["total_amount"], sale_filters)
            total_expenses = _sum_column(Expense, ["amount", "total_amount"], expense_filters)
            direction_col = getattr(Payment, "direction", None)
            in_filters = list(payment_filters) + ([direction_col == "IN"] if direction_col is not None else [])
            out_filters = list(payment_filters) + ([direction_col == "OUT"] if direction_col is not None else [])
            payments_in = _sum_column(Payment, ["total_amount"], in_filters)
            payments_out = _sum_column(Payment, ["total_amount"], out_filters)
            results["financial_summary"] = {"period": {"from": start.isoformat(), "to": end.isoformat()}, "total_sales": float(total_sales), "total_expenses": float(total_expenses), "payments_in": float(payments_in), "payments_out": float(payments_out), "net_cash_flow": float(payments_in - payments_out), "net_profit": float(total_sales - total_expenses)}
    except Exception as exc:
        results["error"] = str(exc)
    return results


def search_database_for_query(query):
    results: Dict[str, Any] = {}
    query = str(query or "")
    q = query.lower()
    intent = analyze_question_intent(query)
    results["intent"] = intent
    try:
        from AI.engine.ai_database_search import search_database_for_query as external_search
        ext = external_search(query)
        if isinstance(ext, dict):
            results.update(ext)
            results["intent"] = intent
    except Exception:
        pass
    try:
        from models import Customer, Product, Supplier
        if "Customer" in intent.get("entities", []):
            clause = _ilike(Customer, "name", "phone", value=query)
            if clause is not None:
                results["customers"] = [c.to_dict() if hasattr(c, "to_dict") else {"id": c.id, "name": c.name} for c in Customer.query.filter(clause).limit(10).all()]
        if "Supplier" in intent.get("entities", []):
            clause = _ilike(Supplier, "name", "phone", "contact", value=query)
            if clause is not None:
                results["suppliers"] = [s.to_dict() if hasattr(s, "to_dict") else {"id": s.id, "name": s.name} for s in Supplier.query.filter(clause).limit(10).all()]
        if "Product" in intent.get("entities", []):
            clause = _ilike(Product, "name", "sku", "barcode", "part_number", "brand", value=query)
            if clause is not None:
                results["products"] = [{"id": p.id, "name": p.name, "sku": p.sku, "price": _safe_float(getattr(p, "price", 0)), "selling_price": _safe_float(getattr(p, "selling_price", 0))} for p in Product.query.filter(clause).limit(10).all()]
        if intent.get("accounting"):
            results["accounting_knowledge"] = get_gl_knowledge_for_ai()
        numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", query)
        if numbers and any(word in q for word in ["ضريبة", "tax", "vat"]):
            amount = float(numbers[0].replace(",", ""))
            if "دخل" in q or "income" in q:
                tax = calculate_palestine_income_tax(amount)
                if tax is None:
                    results["tax_calculation"] = {"type": "ضريبة دخل", "income": amount, "tax": None, "net": None, "warning": "شرائح ضريبة الدخل غير مهيأة في إعدادات النظام"}
                else:
                    results["tax_calculation"] = {"type": "ضريبة دخل", "income": amount, "tax": tax, "net": amount - float(tax), "warning": "تحقق من الإعدادات أو مصدر رسمي قبل اعتماد الرقم"}
            else:
                country = "israel" if "إسرائيل" in query or "israel" in q else "palestine"
                vat = calculate_vat(amount, country)
                vat["country"] = country
                results["vat_calculation"] = vat
    except Exception as exc:
        results["error"] = str(exc)
    return results


def check_groq_health():
    global _groq_failures, _local_fallback_mode, _system_state
    current = _now()
    _groq_failures = [f for f in _groq_failures if (current - f).total_seconds() < 86400]
    if len(_groq_failures) >= 3:
        _local_fallback_mode = True
        _system_state = "LOCAL_ONLY"
        return False
    _system_state = "HYBRID" if _groq_failures else ("LOCAL_ONLY" if _local_fallback_mode else "API_ONLY")
    return not _local_fallback_mode


def get_system_identity():
    company = get_company_profile()
    return {"name": "المساعد الذكي في نظام أزاد", "version": _setting("AI_SERVICE_VERSION", "stable"), "mode": _system_state, "company": company, "capabilities": {"local_analysis": True, "database_access": True, "knowledge_base": True, "finance_calculations": True, "auto_discovery": True, "self_training": True}, "status": {"groq_api": "offline" if _local_fallback_mode else "online", "groq_failures_24h": len(_groq_failures), "local_mode_active": _local_fallback_mode}, "data_sources": ["AI/data عبر ai_storage", "قاعدة البيانات المحلية SQLAlchemy", "خريطة النظام عند توفرها"]}


def log_local_mode_usage():
    try:
        logs = read_json(LOCAL_MODE_LOG_FILE, [])
        logs = logs if isinstance(logs, list) else []
        logs.append({"timestamp": _now().isoformat(), "mode": "LOCAL_ONLY", "groq_failures": len(_groq_failures)})
        write_json(LOCAL_MODE_LOG_FILE, logs[-100:])
        sync_training_manifest(extra_files=[LOCAL_MODE_LOG_FILE])
    except Exception:
        pass


def get_local_fallback_response(message, search_results):
    try:
        company = get_company_profile()
        response = f"🤖 أعمل الآن بالوضع المحلي داخل {company['system_name']}.\n"
        response += f"🏢 الشركة: {company['company_name']} | المطور: {company['owner_display_name']} | الهاتف: {company['phone']}\n\n"
        if search_results and any(k for k in search_results if k not in {"intent", "error"} and search_results.get(k)):
            response += "📊 البيانات المتوفرة من قاعدة البيانات:\n"
            for key, value in list(search_results.items())[:12]:
                if key in {"intent", "error"} or not value:
                    continue
                if isinstance(value, (int, float, str)):
                    response += f"• {key}: {value}\n"
                elif isinstance(value, list):
                    response += f"• {key}: {len(value)} عنصر\n"
                elif isinstance(value, dict):
                    response += f"• {key}: متوفر\n"
        else:
            response += "لم أجد بيانات مباشرة للسؤال. أستطيع مساعدتك بالبحث في الزبائن، المبيعات، الصيانة، المخزون، النفقات، المدفوعات، والصفحات."
        log_local_mode_usage()
        return response
    except Exception as exc:
        return f"⚠️ خطأ في الوضع المحلي: {exc}"


def _active_llm_config() -> Optional[Dict[str, Any]]:
    try:
        from AI.engine.ai_management import get_api_key_decrypted
        key = get_api_key_decrypted("groq")
        if key:
            return {"provider": "groq", "key": key, "model": _setting("GROQ_MODEL", "llama-3.3-70b-versatile")}
    except Exception:
        pass
    keys_json = _setting("AI_API_KEYS", "[]")
    try:
        keys = json.loads(keys_json) if keys_json else []
        active = next((k for k in keys if k.get("is_active") and k.get("key")), None)
        if active:
            return active
    except Exception:
        pass
    return None


def ai_chat_response(message, search_results=None, session_id="default"):
    config = _active_llm_config()
    if not config:
        return get_local_fallback_response(message, search_results or {})
    try:
        import requests
        if "groq" not in str(config.get("provider", "groq")).lower():
            return get_local_fallback_response(message, search_results or {})
        messages = [{"role": "system", "content": build_system_message(gather_system_context())}]
        memory = get_or_create_session_memory(session_id)
        for msg in memory["messages"][-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        enhanced = str(message or "")
        if search_results:
            enhanced += "\n\nنتائج البحث من قاعدة البيانات:\n" + json.dumps(search_results, ensure_ascii=False, default=str)[:12000]
        messages.append({"role": "user", "content": enhanced})
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {config.get('key')}", "Content-Type": "application/json"}, json={"model": config.get("model", "llama-3.3-70b-versatile"), "messages": messages, "temperature": 0.2, "max_tokens": 2000, "top_p": 0.9}, timeout=30)
        if response.status_code == 200:
            answer = response.json()["choices"][0]["message"]["content"]
            add_to_memory(session_id, "user", message)
            add_to_memory(session_id, "assistant", answer)
            global _local_fallback_mode, _system_state
            _local_fallback_mode = False
            _system_state = "HYBRID"
            return answer
    except Exception:
        pass
    _groq_failures.append(_now())
    check_groq_health()
    return get_local_fallback_response(message, search_results or {})


def handle_error_question(error_text):
    try:
        analysis = analyze_error(error_text)
        return {"is_error": True, "analysis": analysis, "formatted_response": format_error_response(analysis)}
    except Exception as exc:
        return {"is_error": True, "analysis": None, "formatted_response": f"⚠️ لم أستطع تحليل الخطأ: {exc}"}


def validate_search_results(query, search_results):
    validation = {"has_data": False, "data_quality": "unknown", "confidence": 0, "warnings": []}
    if not search_results or len(search_results) <= 1:
        validation["warnings"].append("لم يتم العثور على بيانات")
        return validation
    data_keys = [k for k, v in search_results.items() if k not in {"intent", "error"} and v not in (None, "", [], {})]
    if not data_keys:
        validation["warnings"].append("نتائج البحث فارغة")
        return validation
    validation["has_data"] = True
    if len(data_keys) >= 5:
        validation.update(data_quality="excellent", confidence=95)
    elif len(data_keys) >= 3:
        validation.update(data_quality="good", confidence=80)
    else:
        validation.update(data_quality="fair", confidence=60)
        validation["warnings"].append("البيانات محدودة")
    return validation


def calculate_confidence_score(search_results, validation):
    score = int(validation.get("confidence", 0) or 0)
    if search_results.get("error"):
        score -= 30
    if validation.get("data_quality") == "excellent":
        score = min(95, score + 5)
    return max(0, min(100, score))


def handle_navigation_request(message):
    try:
        suggestions = get_route_suggestions(message)
        if suggestions and suggestions.get("matches"):
            lines = [f"📍 تم العثور على {suggestions.get('count', len(suggestions['matches']))} صفحة مطابقة:\n"]
            for i, route in enumerate(suggestions["matches"][:8], 1):
                lines.append(f"{i}. **{route.get('endpoint', 'صفحة')}**")
                lines.append(f"   🔗 الرابط: `{route.get('url', route.get('path', 'غير متوفر'))}`")
                if route.get("linked_templates"):
                    lines.append(f"   📄 القالب: {route['linked_templates'][0]}")
            return "\n".join(lines)
        route_info = find_route_by_keyword(message)
        if route_info and route_info.get("matches"):
            match = route_info["matches"][0]
            return f"📍 وجدت الصفحة:\n🔗 `{match.get('url', match.get('path', 'غير متوفر'))}`\n📛 {match.get('endpoint', '')}"
    except Exception as exc:
        return f"⚠️ خطأ في البحث عن الصفحة: {exc}"
    return "⚠️ لم أتمكن من العثور على الصفحة المطلوبة."


def enhanced_context_understanding(message):
    try:
        from AI.engine.ai_nlp_engine import understand_text
        nlp = understand_text(message)
        return {"message": message, "normalized": str(message or "").lower(), "intent": nlp["intent"]["primary_intent"], "subintent": (nlp["intent"].get("secondary_intents") or [None])[0], "entities": list(nlp["sentence_structure"].get("entities", {}).keys()), "context_type": nlp["sentence_structure"].get("intent") or "question", "sentiment": nlp["sentence_structure"].get("sentiment", "neutral"), "priority": "urgent" if nlp["sentence_structure"].get("is_urgent") else "normal", "confidence": nlp["intent"].get("confidence", 0.5), "keywords": [], "time_scope": None, "requires_data": bool(nlp["sentence_structure"].get("entities")), "requires_action": nlp["intent"].get("primary_intent") == "executable_command"}
    except Exception:
        pass
    text = str(message or "")
    normalized = re.sub(r"[\u0617-\u061A\u064B-\u0652]", "", text.lower())
    normalized = re.sub("[إأٱآا]", "ا", normalized).replace("ى", "ي").replace("ة", "ه")
    intent = analyze_question_intent(normalized)
    context_type = "question"
    if any(g in normalized for g in ["صباح", "مساء", "مرحبا", "اهلا", "السلام", "hello", "hi"]):
        context_type = "greeting"
    elif any(c in normalized for c in ["مشكله", "خطا", "خلل", "عطل", "problem", "error", "bug"]):
        context_type = "complaint"
    return {"message": message, "normalized": normalized, "intent": intent["type"], "subintent": None, "entities": intent.get("entities", []), "context_type": context_type, "sentiment": "negative" if context_type == "complaint" else "neutral", "priority": "high" if context_type == "complaint" else "normal", "confidence": 0.7, "keywords": [w for w in normalized.split() if len(w) > 2], "time_scope": intent.get("time_scope"), "requires_data": bool(intent.get("entities")), "requires_action": intent.get("executable", False)}


def _format_vat_response(amount: float, vat: Dict[str, Any]) -> str:
    warning = f"\n⚠️ {vat.get('warning')}" if vat.get("warning") else ""
    if vat.get("vat_rate") is None or vat.get("vat_amount") is None or vat.get("total_with_vat") is None:
        return f"💰 حساب VAT:\n• المبلغ: {amount:,.2f}\n• النسبة: غير مهيأة في النظام\n• الضريبة: غير محسوبة\n• الإجمالي: غير محسوب{warning}"
    return f"💰 حساب VAT:\n• المبلغ: {amount:,.2f}\n• النسبة: {vat['vat_rate']}%\n• الضريبة: {_format_nullable_amount(vat['vat_amount'])}\n• الإجمالي: {_format_nullable_amount(vat['total_with_vat'])}{warning}"


def local_intelligent_response(message, session_id=None):
    message = str(message or "")
    q = message.lower()
    context = enhanced_context_understanding(message)
    try:
        from AI.engine.ai_conversation import match_local_response
        rich = match_local_response(message, session_id=session_id)
        if rich:
            return rich
    except Exception:
        pass
    company = get_company_profile()
    if context.get("context_type") == "greeting" or any(w in q for w in ["من انت", "من أنت", "الشركة", "المطور", "رقم الهاتف", "تواصل"]):
        stats = gather_system_context()
        return f"👋 أهلاً. أنا المساعد الذكي داخل {company['system_name']}.\n🏢 الشركة: {company['company_name']}\n👤 المالك/المطور: {company['owner_display_name']} ({company['owner_name']})\n☎️ الهاتف: {company['phone']}\n\n📊 حالة مختصرة:\n{stats.get('current_stats', 'غير متوفر')}"
    if context.get("intent") == "navigation" or any(w in q for w in ["وين", "اين", "أين", "افتح", "رابط", "صفحة"]):
        return handle_navigation_request(message)
    for key, response in get_local_faq_responses().items():
        if key.lower() in q:
            return response
    try:
        from models import Customer, Expense, Product, ServiceRequest, Supplier
        model_map = {"Customer": Customer, "ServiceRequest": ServiceRequest, "Expense": Expense, "Product": Product, "Supplier": Supplier}
        for rule in get_local_quick_rules().values():
            for pattern in rule.get("patterns", []):
                if pattern.lower() in q:
                    model = model_map.get(rule.get("model"))
                    if model:
                        return rule["response_template"].format(count=_safe_count(model))
    except Exception:
        pass
    if any(word in q for word in ["vat", "ضريبة القيمة المضافة", "ضريبة مضافة", "ضريبه"]):
        numbers = re.findall(r"\d+(?:\.\d+)?", message)
        if numbers:
            amount = float(numbers[0])
            country = "israel" if "israel" in q or "إسرائيل" in message else "palestine"
            return _format_vat_response(amount, calculate_vat(amount, country))
    if any(word in q for word in ["خطأ", "error", "traceback", "exception"]):
        return handle_error_question(message).get("formatted_response")
    search_results = search_database_for_query(message)
    validation = validate_search_results(message, search_results)
    if validation.get("has_data"):
        return get_local_fallback_response(message, search_results)
    return "لم أجد بيانات مباشرة كافية. اسألني عن الزبائن، الصيانة، المنتجات، النفقات، المدفوعات، المخزون، الصفحات، أو VAT."


def ai_chat_with_search(user_id: int = None, query: str = None, message: str = None, session_id: str = "default", context: Dict = None):
    if message and not query:
        query = message
    if not query:
        return {"response": "لم يتم تقديم سؤال", "confidence": 0}
    start = time.time()
    context = context or {}
    context["user_id"] = user_id
    context["search_results"] = search_database_for_query(query)
    try:
        from AI.engine.ai_master_controller import get_master_controller
        result = get_master_controller().process_intelligent_query(query, context)
        answer = result.get("answer", "")
        confidence = float(result.get("confidence", 0.7) or 0.7)
        if not answer:
            raise RuntimeError("empty_controller_answer")
    except Exception:
        answer = _ai_chat_original(query, session_id)
        confidence = 0.65
        result = {"answer": answer, "confidence": confidence, "sources": ["local_fallback"], "tips": []}
    elapsed = time.time() - start
    try:
        from AI.engine.ai_self_evolution import get_evolution_engine
        get_evolution_engine().record_interaction(query=query, response=result, success=bool(answer), confidence=confidence, execution_time=elapsed)
    except Exception:
        pass
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        get_performance_tracker().record_query(query, result, elapsed)
    except Exception:
        pass
    try:
        add_to_memory(session_id, "user", query)
        add_to_memory(session_id, "assistant", answer)
        log_interaction(query, answer, int(confidence * 100) if confidence <= 1 else int(confidence), context.get("search_results", {}))
    except Exception:
        pass
    return {"response": answer, "confidence": confidence, "sources": result.get("sources", []), "tips": result.get("tips", [])}


def _ai_chat_original(message, session_id="default"):
    global _last_audit_time
    add_to_memory(session_id, "user", message)
    intent = analyze_question_intent(message)
    if intent.get("navigation"):
        response = handle_navigation_request(message)
    elif intent.get("type") == "troubleshooting":
        response = handle_error_question(message).get("formatted_response", "")
    else:
        search_results = search_database_for_query(message)
        validation = validate_search_results(message, search_results)
        confidence = calculate_confidence_score(search_results, validation)
        response = ai_chat_response(message, search_results, session_id) if validation.get("has_data") else local_intelligent_response(message, session_id=session_id)
        if confidence < 70 and "درجة الثقة" not in response:
            response += f"\n\n⚠️ درجة الثقة التقريبية: {confidence}%"
    add_to_memory(session_id, "assistant", response)
    current = _now()
    if _last_audit_time is None or (current - _last_audit_time) > timedelta(hours=1):
        try:
            generate_self_audit_report()
            _last_audit_time = current
        except Exception:
            pass
    return response


def explain_system_structure():
    try:
        company = get_company_profile()
        structure = _knowledge_structure()
        models = structure.get("models", [])[:15]
        return f"""🏗️ هيكل نظام أزاد

الشركة: {company['company_name']}
المطور: {company['owner_display_name']}
الهاتف: {company['phone']}

📊 قاعدة البيانات:
• {structure.get('models_count', 0)} موديل/جدول مفهرس
{chr(10).join(f'  - {m}' for m in models)}

🔗 المسارات: {structure.get('routes_count', 0)}
📄 القوالب: {structure.get('templates_count', 0)}
🤝 العلاقات: {structure.get('relationships_count', 0)}
📜 قواعد العمل: {structure.get('business_rules_count', 0)}
""".strip()
    except Exception as exc:
        return f"⚠️ خطأ في شرح الهيكل: {exc}"


__all__ = ["get_company_profile", "get_system_setting", "gather_system_context", "get_system_navigation_context", "get_data_awareness_context", "analyze_question_intent", "get_or_create_session_memory", "add_to_memory", "get_conversation_context", "deep_data_analysis", "analyze_accounting_data", "generate_smart_report", "build_system_message", "query_accounting_data", "search_database_for_query", "check_groq_health", "get_system_identity", "get_local_fallback_response", "log_local_mode_usage", "ai_chat_response", "handle_error_question", "validate_search_results", "calculate_confidence_score", "handle_navigation_request", "enhanced_context_understanding", "local_intelligent_response", "ai_chat_with_search", "explain_system_structure"]
