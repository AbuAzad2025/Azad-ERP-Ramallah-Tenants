"""AI service facade.

This module is intentionally conservative: it preserves the public functions used
by routes/controllers while removing brittle hard-coded claims and broken prompt
construction. Database reads are guarded, remote AI is optional, and local mode is
always available.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import psutil
from sqlalchemy import func, text

from extensions import cache, db
from models import SystemSettings
from AI.engine.ai_accounting_professional import get_professional_accounting_knowledge
from AI.engine.ai_auto_discovery import auto_discover_if_needed, find_route_by_keyword, get_route_suggestions
from AI.engine.ai_auto_training import init_auto_training, should_auto_train
from AI.engine.ai_data_awareness import auto_build_if_needed, find_model_by_keyword, load_data_schema
from AI.engine.ai_gl_knowledge import analyze_gl_batch, detect_gl_error, explain_any_number, explain_gl_entry, get_gl_knowledge_for_ai, suggest_gl_correction, trace_transaction_flow
from AI.engine.ai_knowledge import analyze_error, format_error_response, get_knowledge_base, get_local_faq_responses, get_local_quick_rules
from AI.engine.ai_knowledge_finance import calculate_palestine_income_tax, calculate_vat, get_customs_info, get_finance_knowledge, get_tax_knowledge_detailed
from AI.engine.ai_self_review import check_policy_compliance, generate_self_audit_report, get_system_status, log_interaction
from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

_conversation_memory: Dict[str, Dict[str, Any]] = {}
_last_audit_time = None
_groq_failures: List[datetime] = []
_local_fallback_mode = True
_system_state = "LOCAL_ONLY"

LOCAL_MODE_LOG_FILE = "ai_local_mode_log.json"
MAX_MEMORY_MESSAGES = 50


# ─────────────────────────────────────────────────────────────────────────────
# Small safe helpers
# ─────────────────────────────────────────────────────────────────────────────

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
    count = _safe_count(model, query_func)
    try:
        cache.set(cache_key, count, timeout=ttl)
    except Exception:
        pass
    return count


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


def _serialize_basic(obj: Any, fields: List[str]) -> Dict[str, Any]:
    data = {}
    for field in fields:
        value = getattr(obj, field, None)
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        data[field] = value
    return data


def _knowledge_structure() -> Dict[str, Any]:
    try:
        kb = get_knowledge_base()
        if hasattr(kb, "get_system_structure"):
            return kb.get_system_structure()
        knowledge = getattr(kb, "knowledge", {}) or {}
        return {
            "models_count": len(knowledge.get("models", {})),
            "routes_count": len(knowledge.get("routes", {})),
            "templates_count": sum(len(v) if isinstance(v, list) else 1 for v in knowledge.get("templates", {}).values()),
            "relationships_count": len(knowledge.get("relationships", {})),
            "business_rules_count": len(knowledge.get("business_rules", [])),
            "models": list(knowledge.get("models", {}).keys()),
            "routes": knowledge.get("routes", {}),
        }
    except Exception:
        return {"models_count": 0, "routes_count": 0, "templates_count": 0, "relationships_count": 0, "business_rules_count": 0, "models": [], "routes": {}}


# ─────────────────────────────────────────────────────────────────────────────
# Settings and context
# ─────────────────────────────────────────────────────────────────────────────

def get_system_setting(key, default=""):
    try:
        setting = SystemSettings.query.filter_by(key=key).first()
        return setting.value if setting else default
    except Exception:
        return default


def gather_system_context():
    """Collect live system context without fabricated totals."""
    try:
        from models import AuditLog, Customer, Expense, ExchangeTransaction, Note, Payment, Product, Role, ServiceRequest, Shipment, StockLevel, Supplier, User, Warehouse

        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        today = _now().date()

        db_size = "غير معروف"
        db_health = "نشط"
        try:
            result = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
            db_size = f"{float(result or 0) / (1024 ** 2):.2f} MB"
        except Exception:
            pass

        try:
            latest_fx = ExchangeTransaction.query.filter_by(from_currency="USD", to_currency="ILS").order_by(ExchangeTransaction.created_at.desc()).first()
            context_fx_rate = f"{float(latest_fx.rate):.4f} ({latest_fx.created_at.strftime('%Y-%m-%d')})" if latest_fx else "غير متوفر"
        except Exception:
            context_fx_rate = "غير متوفر"

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
            f"العملاء: {total_customers} | الموردين: {total_suppliers}\n"
            f"المنتجات: {total_products} | منتجات بالمخزون: {products_in_stock}\n"
            f"المخازن: {total_warehouses}\n"
            f"CPU: {cpu_usage:.1f}% | RAM: {memory.percent:.1f}%"
        )

        return {
            "system_name": "نظام أزاد لإدارة الكراج",
            "version": get_system_setting("SYSTEM_VERSION", "غير محدد"),
            "roles_count": _cached_count(Role, "roles_count"),
            "roles": roles,
            "total_users": total_users,
            "active_users": active_users,
            "total_services": total_services,
            "pending_services": _cached_count(ServiceRequest, "pending_services", lambda: ServiceRequest.query.filter_by(status="pending").count()),
            "completed_services": _cached_count(ServiceRequest, "completed_services", lambda: ServiceRequest.query.filter_by(status="completed").count()),
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
            "total_exchange_transactions": _cached_count(ExchangeTransaction, "total_exchange_transactions"),
            "latest_usd_ils_rate": context_fx_rate,
            "cpu_usage": round(cpu_usage, 1),
            "memory_usage": round(memory.percent, 1),
            "db_size": db_size,
            "db_health": db_health,
            "current_stats": current_stats,
        }
    except Exception as exc:
        return {"system_name": "نظام أزاد", "version": "غير محدد", "modules_count": 0, "modules": [], "roles_count": 0, "roles": [], "current_stats": f"خطأ في جمع الإحصائيات: {exc}"}


def get_system_navigation_context():
    try:
        system_map = auto_discover_if_needed()
        if system_map:
            return {
                "total_routes": system_map.get("statistics", {}).get("total_routes", 0),
                "total_templates": system_map.get("statistics", {}).get("total_templates", 0),
                "blueprints": system_map.get("blueprints", []),
                "modules": system_map.get("modules", []),
                "categories": {k: len(v) for k, v in system_map.get("routes", {}).get("by_category", {}).items()},
            }
    except Exception:
        pass
    return {}


def get_data_awareness_context():
    try:
        schema = auto_build_if_needed()
        if schema:
            return {
                "total_models": schema.get("statistics", {}).get("total_tables", 0),
                "total_columns": schema.get("statistics", {}).get("total_columns", 0),
                "total_relationships": schema.get("statistics", {}).get("total_relationships", 0),
                "functional_modules": list((schema.get("functional_mapping") or {}).keys()),
                "available_models": list((schema.get("models") or {}).keys()),
            }
    except Exception:
        pass
    return {}


def analyze_question_intent(question):
    question_lower = str(question or "").lower()
    intent = {"type": "general", "entities": [], "time_scope": None, "action": "query", "currency": None, "accounting": False, "executable": False, "navigation": False}

    if any(word in question_lower for word in ["أنشئ", "انشئ", "create", "add", "أضف", "اضف", "سجل"]):
        intent.update(type="command", action="create", executable=True)
    elif any(word in question_lower for word in ["احذف", "delete", "remove", "أزل", "ازل"]):
        intent.update(type="command", action="delete", executable=True)
    elif any(word in question_lower for word in ["عدّل", "عدل", "update", "modify", "غيّر", "غير"]):
        intent.update(type="command", action="update", executable=True)
    elif any(word in question_lower for word in ["كم", "عدد", "count", "how many"]):
        intent["type"] = "count"
    elif any(word in question_lower for word in ["كيف", "how", "why", "لماذا", "شرح"]):
        intent["type"] = "explanation"
    elif any(word in question_lower for word in ["تقرير", "report", "تحليل", "analysis", "حلل"]):
        intent["type"] = "report"
    elif any(word in question_lower for word in ["خطأ", "error", "مشكلة", "problem", "bug"]):
        intent["type"] = "troubleshooting"

    if any(word in question_lower for word in ["اذهب", "افتح", "صفحة", "وين", "أين", "اين", "رابط", "عرض", "دلني", "وصلني"]):
        intent.update(type="navigation", navigation=True)

    if any(word in question_lower for word in ["شيقل", "ils", "₪"]):
        intent.update(currency="ILS", accounting=True)
    elif any(word in question_lower for word in ["دولار", "usd", "$"]):
        intent.update(currency="USD", accounting=True)
    elif any(word in question_lower for word in ["دينار", "jod"]):
        intent.update(currency="JOD", accounting=True)
    elif any(word in question_lower for word in ["يورو", "eur", "€"]):
        intent.update(currency="EUR", accounting=True)

    if any(word in question_lower for word in ["ربح", "خسارة", "دخل", "profit", "loss", "revenue", "مالي", "محاسب", "رصيد", "دفتر", "قيد", "vat", "ضريبة"]):
        intent["accounting"] = True

    if any(word in question_lower for word in ["اليوم", "today", "الآن", "الان", "now"]):
        intent["time_scope"] = "today"
    elif any(word in question_lower for word in ["الأسبوع", "الاسبوع", "week", "أسبوع", "اسبوع"]):
        intent["time_scope"] = "week"
    elif any(word in question_lower for word in ["الشهر", "month", "شهر"]):
        intent["time_scope"] = "month"
    elif any(word in question_lower for word in ["السنة", "year", "سنة", "عام"]):
        intent["time_scope"] = "year"

    entity_map = {
        "Customer": ["عميل", "عملاء", "زبون", "customer", "client"],
        "ServiceRequest": ["صيانة", "service", "تشخيص", "عطل", "إصلاح", "اصلاح"],
        "Product": ["منتج", "منتجات", "product", "قطع", "قطعة"],
        "Warehouse": ["مخزن", "مخازن", "warehouse", "مستودع", "مخزون"],
        "Invoice": ["فاتورة", "فواتير", "invoice"],
        "Payment": ["دفع", "دفعة", "مدفوعات", "payment"],
        "Expense": ["مصروف", "مصاريف", "نفقات", "نفقة", "expense"],
        "Supplier": ["مورد", "موردين", "supplier", "vendor"],
        "Sale": ["بيع", "مبيعات", "sale", "sales"],
    }
    for entity, keywords in entity_map.items():
        if any(k in question_lower for k in keywords):
            intent["entities"].append(entity)
    return intent


# ─────────────────────────────────────────────────────────────────────────────
# Conversation memory
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_session_memory(session_id):
    session_id = str(session_id or "default")
    if session_id not in _conversation_memory:
        _conversation_memory[session_id] = {"messages": [], "context": {}, "created_at": _now(), "last_updated": _now(), "user_preferences": {}, "topics": [], "entities_mentioned": {}, "last_intent": None}
    _conversation_memory[session_id]["last_updated"] = _now()
    return _conversation_memory[session_id]


def add_to_memory(session_id, role, content, context=None):
    memory = get_or_create_session_memory(session_id)
    message_entry = {"role": role, "content": str(content or "")[:8000], "timestamp": _now().isoformat()}
    if context:
        message_entry["context"] = {"intent": context.get("intent"), "entities": context.get("entities"), "sentiment": context.get("sentiment")}
        for entity in context.get("entities", []) or []:
            memory["entities_mentioned"][entity] = memory["entities_mentioned"].get(entity, 0) + 1
        if context.get("intent"):
            memory["last_intent"] = context["intent"]
    memory["messages"].append(message_entry)
    memory["messages"] = memory["messages"][-MAX_MEMORY_MESSAGES:]


def get_conversation_context(session_id):
    memory = get_or_create_session_memory(session_id)
    return {
        "message_count": len(memory["messages"]),
        "duration": (_now() - memory["created_at"]).total_seconds(),
        "most_mentioned_entities": sorted(memory["entities_mentioned"].items(), key=lambda x: x[1], reverse=True)[:5],
        "last_intent": memory.get("last_intent"),
        "recent_topics": memory.get("topics", [])[-5:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Read-only analysis/reporting
# ─────────────────────────────────────────────────────────────────────────────

def _time_range(scope: Optional[str]) -> Tuple[datetime, datetime]:
    end_date = _now()
    if scope == "today":
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif scope == "week":
        start_date = end_date - timedelta(days=7)
    elif scope == "month":
        start_date = end_date - timedelta(days=30)
    elif scope == "year":
        start_date = end_date - timedelta(days=365)
    else:
        start_date = end_date - timedelta(days=90)
    return start_date, end_date


def deep_data_analysis(query, context):
    from models import Customer, Expense, Invoice

    analysis_result = {"success": True, "insights": [], "warnings": [], "recommendations": [], "data_summary": {}}
    try:
        entities = context.get("entities", []) or []
        normalized_entities = {e.lower() for e in entities}
        start_date, end_date = _time_range(context.get("time_scope"))

        if "customer" in normalized_entities or "Customer" in entities:
            total_customers = Customer.query.count()
            active_customers = db.session.query(func.count(func.distinct(Invoice.customer_id))).filter(Invoice.created_at >= start_date).scalar() or 0
            activity_rate = (active_customers / total_customers * 100) if total_customers else 0
            analysis_result["data_summary"]["customers"] = {"total": total_customers, "active": active_customers, "activity_rate": round(activity_rate, 1)}
            if total_customers and activity_rate < 30:
                analysis_result["warnings"].append(f"نشاط العملاء منخفض: {activity_rate:.1f}% ضمن الفترة المحددة")

        if "invoice" in normalized_entities or "sale" in normalized_entities or "sales" in str(query).lower() or "مبيعات" in str(query):
            current_sales = _sum_column(Invoice, ["total_amount"], [Invoice.created_at >= start_date])
            prev_start = start_date - (end_date - start_date)
            prev_sales = _sum_column(Invoice, ["total_amount"], [Invoice.created_at >= prev_start, Invoice.created_at < start_date])
            change = float(current_sales - prev_sales)
            change_percent = (change / float(prev_sales) * 100) if prev_sales else 0
            analysis_result["data_summary"]["sales"] = {"current": float(current_sales), "previous": float(prev_sales), "change": change, "change_percent": round(change_percent, 1)}
            if change_percent > 20:
                analysis_result["insights"].append(f"المبيعات ارتفعت بنسبة {change_percent:.1f}% مقارنة بالفترة السابقة")
            elif change_percent < -10:
                analysis_result["warnings"].append(f"المبيعات انخفضت بنسبة {abs(change_percent):.1f}% مقارنة بالفترة السابقة")

        if "expense" in normalized_entities or "مصروف" in str(query) or "نفقات" in str(query):
            date_col = _first_attr(Expense, ["date", "created_at"])
            filters = [date_col >= start_date] if date_col is not None else []
            total_expenses = _sum_column(Expense, ["amount", "total_amount"], filters)
            analysis_result["data_summary"]["expenses"] = {"total": float(total_expenses)}
            sales = analysis_result["data_summary"].get("sales", {}).get("current", 0)
            if sales:
                expense_ratio = float(total_expenses) / sales * 100
                if expense_ratio > 70:
                    analysis_result["warnings"].append(f"النفقات مرتفعة: {expense_ratio:.1f}% من المبيعات")
    except Exception as exc:
        analysis_result.update(success=False, error=str(exc))
    return analysis_result


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
        for curr, values in analysis["by_currency"].items():
            values["profit"] = values["revenue"] - values["expenses"]
        analysis["net_profit"] = analysis["total_revenue"] - analysis["total_expenses"]
        return analysis
    except Exception as exc:
        return {"error": str(exc)}


def generate_smart_report(intent):
    try:
        from models import Customer, Expense, Invoice, Payment, Product, ServiceRequest, Supplier, Warehouse

        if intent.get("accounting"):
            return {"type": "accounting_report", "data": analyze_accounting_data(intent.get("currency")), "generated_at": _now().strftime("%Y-%m-%d %H:%M")}

        report = {"title": "تقرير مختصر", "generated_at": _now().strftime("%Y-%m-%d %H:%M"), "sections": []}
        today = _now().date()
        if intent.get("time_scope") == "today":
            report["title"] = "تقرير اليوم"
            report["sections"].append({"name": "الصيانة اليوم", "data": {"total": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today).count()), "completed": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today, ServiceRequest.status == "completed").count()), "pending": _safe_count(ServiceRequest, lambda: ServiceRequest.query.filter(func.date(ServiceRequest.created_at) == today, ServiceRequest.status == "pending").count())}})
            report["sections"].append({"name": "المدفوعات اليوم", "data": {"count": _safe_count(Payment, lambda: Payment.query.filter(func.date(Payment.payment_date) == today).count()), "total": float(_sum_column(Payment, ["total_amount", "amount"], [func.date(Payment.payment_date) == today]))}})
        entity_models = {"Customer": Customer, "ServiceRequest": ServiceRequest, "Product": Product, "Supplier": Supplier, "Warehouse": Warehouse, "Expense": Expense, "Invoice": Invoice}
        for entity in intent.get("entities", []) or []:
            model = entity_models.get(entity)
            if model:
                report["sections"].append({"name": f"إحصائيات {entity}", "data": {"total": _safe_count(model)}})
        return report
    except Exception as exc:
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Prompt building and direct accounting queries
# ─────────────────────────────────────────────────────────────────────────────

def build_system_message(system_context):
    identity = get_system_identity()
    structure = _knowledge_structure()
    nav_context = get_system_navigation_context()
    data_context = get_data_awareness_context()
    gl_knowledge = get_gl_knowledge_for_ai()

    modules_hint = []
    if nav_context.get("modules"):
        modules_hint = nav_context.get("modules", [])[:15]
    elif data_context.get("functional_modules"):
        modules_hint = data_context.get("functional_modules", [])[:15]

    return f"""أنت {identity['name']} داخل نظام أزاد لإدارة الكراج.

وضع التشغيل: {identity['mode']}
Groq API: {identity['status']['groq_api']}

قواعد الإجابة:
- استخدم البيانات الفعلية المرفقة في السؤال أو من قاعدة البيانات فقط.
- لا تخترع أرقامًا أو أسماء صفحات أو نسبًا.
- إن كانت البيانات غير كافية، قل ذلك بوضوح واقترح أين يبحث المستخدم داخل النظام.
- لا تنفذ أي عملية حذف/تعديل/إنشاء إلا إذا مرّت من طبقة الصلاحيات والتنفيذ.
- للأسئلة القانونية/الضريبية المتغيرة، اذكر أن القيم تحتاج تحققًا من الإعدادات أو مصدر رسمي حديث.

ملخص حي من النظام:
{system_context.get('current_stats', 'غير متوفر')}

فهرسة النظام المتاحة:
- الموديلات: {structure.get('models_count', 0)}
- المسارات: {structure.get('routes_count', 0)}
- القوالب: {structure.get('templates_count', 0)}
- العلاقات: {structure.get('relationships_count', 0)}
- قواعد العمل: {structure.get('business_rules_count', 0)}

وحدات معروفة:
{', '.join(modules_hint) if modules_hint else 'غير متوفرة'}

معرفة GL المتاحة:
{', '.join(gl_knowledge.get('capabilities', [])[:6])}

آخر سعر USD/ILS من النظام: {system_context.get('latest_usd_ils_rate', 'غير متوفر')}
""".strip()


def query_accounting_data(query_type, filters=None):
    results: Dict[str, Any] = {}
    filters = filters or {}
    try:
        from models import Account, Customer, Expense, GLBatch, GLEntry, Payment, Sale, Supplier

        if query_type == "customer_balance":
            customer_id = filters.get("customer_id")
            customer = db.session.get(Customer, int(customer_id)) if customer_id else None
            if customer:
                balance = _safe_float(getattr(customer, "balance", 0))
                results["customer"] = {"id": customer.id, "name": customer.name, "balance": balance, "meaning": "موجب = عليه حسب إعدادات النظام إن كان الرصيد مدينًا، وسالب/دائن يحتاج قراءة سياسة الرصيد المعتمدة"}

        elif query_type == "supplier_balance":
            supplier_id = filters.get("supplier_id")
            supplier = db.session.get(Supplier, int(supplier_id)) if supplier_id else None
            if supplier:
                results["supplier"] = {"id": supplier.id, "name": supplier.name, "balance": _safe_float(getattr(supplier, "balance", 0))}

        elif query_type in {"gl_account_summary", "account_balance"}:
            account_code = filters.get("account_code")
            account_col = _first_attr(GLEntry, ["account_code", "account"])
            debit_col = _first_attr(GLEntry, ["debit_amount", "debit"])
            credit_col = _first_attr(GLEntry, ["credit_amount", "credit"])
            batch_fk = _first_attr(GLEntry, ["batch_id", "gl_batch_id"])
            batch_pk = getattr(GLBatch, "id", None)
            if account_col is None or debit_col is None or credit_col is None:
                return {"error": "GLEntry columns are not compatible"}
            q = db.session.query(account_col.label("account"), func.sum(debit_col).label("total_debit"), func.sum(credit_col).label("total_credit"))
            if batch_fk is not None and batch_pk is not None:
                q = q.join(GLBatch, batch_fk == batch_pk)
                date_col = _first_attr(GLBatch, ["batch_date", "date", "created_at"])
                if filters.get("date_from") and date_col is not None:
                    q = q.filter(date_col >= filters["date_from"])
                if filters.get("date_to") and date_col is not None:
                    q = q.filter(date_col <= filters["date_to"])
            if account_code:
                q = q.filter(account_col == account_code)
            rows = q.group_by(account_col).all()
            results["gl_summary"] = [{"account": row.account, "total_debit": _safe_float(row.total_debit), "total_credit": _safe_float(row.total_credit), "balance": _safe_float(row.total_debit) - _safe_float(row.total_credit)} for row in rows]
            if query_type == "account_balance" and account_code:
                account = None
                try:
                    account = Account.query.filter_by(code=account_code).first()
                except Exception:
                    pass
                if results["gl_summary"]:
                    first = results["gl_summary"][0]
                    results["account_balance"] = {**first, "account_name": getattr(account, "name", account_code), "account_code": account_code}

        elif query_type == "financial_summary":
            date_from = filters.get("date_from", _now() - timedelta(days=30))
            date_to = filters.get("date_to", _now())
            sale_date = _first_attr(Sale, ["created_at", "sale_date"])
            sale_amount_names = ["total_amount", "sale_total", "total"]
            sale_filters = []
            if sale_date is not None:
                sale_filters = [sale_date >= date_from, sale_date <= date_to]
            expense_date = _first_attr(Expense, ["date", "created_at"])
            expense_filters = []
            if expense_date is not None:
                expense_filters = [expense_date >= date_from, expense_date <= date_to]
            payment_date = _first_attr(Payment, ["payment_date", "created_at"])
            payment_filters_base = []
            if payment_date is not None:
                payment_filters_base = [payment_date >= date_from, payment_date <= date_to]
            total_sales = _sum_column(Sale, sale_amount_names, sale_filters)
            total_expenses = _sum_column(Expense, ["amount", "total_amount"], expense_filters)
            direction_col = getattr(Payment, "direction", None)
            payments_in_filters = list(payment_filters_base)
            payments_out_filters = list(payment_filters_base)
            if direction_col is not None:
                payments_in_filters.append(direction_col == "IN")
                payments_out_filters.append(direction_col == "OUT")
            payments_in = _sum_column(Payment, ["total_amount", "amount"], payments_in_filters)
            payments_out = _sum_column(Payment, ["total_amount", "amount"], payments_out_filters)
            results["financial_summary"] = {"period": {"from": date_from.isoformat(), "to": date_to.isoformat()}, "total_sales": float(total_sales), "total_expenses": float(total_expenses), "payments_in": float(payments_in), "payments_out": float(payments_out), "net_cash_flow": float(payments_in - payments_out), "net_profit": float(total_sales - total_expenses)}
    except Exception as exc:
        results["error"] = str(exc)
    return results


def search_database_for_query(query):
    results: Dict[str, Any] = {}
    query = str(query or "")
    query_lower = query.lower()
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
        if intent.get("accounting"):
            results["accounting_knowledge"] = get_gl_knowledge_for_ai()
            if "رصيد" in query_lower and "عميل" in query_lower:
                from models import Customer
                name = query.split("عميل", 1)[-1].strip() if "عميل" in query else ""
                if name:
                    customer = Customer.query.filter(Customer.name.ilike(f"%{name}%")).first()
                    if customer:
                        results.update(query_accounting_data("customer_balance", {"customer_id": customer.id}))
            if "رصيد" in query_lower and "مورد" in query_lower:
                from models import Supplier
                name = query.split("مورد", 1)[-1].strip() if "مورد" in query else ""
                if name:
                    supplier = Supplier.query.filter(Supplier.name.ilike(f"%{name}%")).first()
                    if supplier:
                        results.update(query_accounting_data("supplier_balance", {"supplier_id": supplier.id}))
            account_code_match = re.search(r"(\d{4}_[A-Z0-9_]+)", query.upper())
            if account_code_match:
                results.update(query_accounting_data("account_balance", {"account_code": account_code_match.group(1)}))
            if "ملخص" in query_lower and ("مالي" in query_lower or "محاسبي" in query_lower):
                results.update(query_accounting_data("financial_summary"))

        if intent.get("type") == "report" or intent.get("accounting"):
            results["report_data"] = generate_smart_report(intent)

        numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", query)
        if numbers and any(word in query_lower for word in ["ضريبة", "tax", "vat"]):
            amount = float(numbers[0].replace(",", ""))
            if "دخل" in query_lower or "income" in query_lower:
                tax = calculate_palestine_income_tax(amount)
                results["tax_calculation"] = {"type": "ضريبة دخل فلسطين", "income": amount, "tax": tax, "net": amount - tax, "effective_rate": round((tax / amount) * 100, 2) if amount else 0}
            else:
                country = "israel" if "إسرائيل" in query or "israel" in query_lower else "palestine"
                vat_info = calculate_vat(amount, country)
                vat_info["country"] = country
                results["vat_calculation"] = vat_info

        if intent.get("currency") or "صرف" in query_lower or "سعر" in query_lower:
            from models import ExchangeTransaction
            recent_fx = ExchangeTransaction.query.order_by(ExchangeTransaction.created_at.desc()).limit(5).all()
            if recent_fx:
                results["recent_exchange_rates"] = [{"from_currency": fx.from_currency, "to_currency": fx.to_currency, "rate": float(fx.rate), "date": fx.created_at.strftime("%Y-%m-%d") if fx.created_at else "N/A"} for fx in recent_fx]
    except Exception as exc:
        results["error"] = str(exc)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Health, identity, local fallback
# ─────────────────────────────────────────────────────────────────────────────

def check_groq_health():
    global _groq_failures, _local_fallback_mode, _system_state
    current_time = _now()
    _groq_failures = [f for f in _groq_failures if (current_time - f).total_seconds() < 86400]
    if len(_groq_failures) >= 3:
        _local_fallback_mode = True
        _system_state = "LOCAL_ONLY"
        return False
    if len(_groq_failures) > 0:
        _system_state = "HYBRID"
    elif _local_fallback_mode:
        _system_state = "LOCAL_ONLY"
    else:
        _system_state = "API_ONLY"
    return not _local_fallback_mode


def get_system_identity():
    return {
        "name": "المساعد الذكي في نظام Garage Manager",
        "version": "AI Service Stable",
        "mode": _system_state,
        "capabilities": {"local_analysis": True, "database_access": True, "knowledge_base": True, "finance_calculations": True, "auto_discovery": True, "self_training": True},
        "status": {"groq_api": "offline" if _local_fallback_mode else "online", "groq_failures_24h": len(_groq_failures), "local_mode_active": _local_fallback_mode},
        "data_sources": ["AI/data عبر ai_storage", "قاعدة البيانات المحلية SQLAlchemy", "خريطة النظام عند توفرها"],
    }


def log_local_mode_usage():
    try:
        logs = read_json(LOCAL_MODE_LOG_FILE, [])
        if not isinstance(logs, list):
            logs = []
        logs.append({"timestamp": _now().isoformat(), "mode": "LOCAL_ONLY", "groq_failures": len(_groq_failures)})
        write_json(LOCAL_MODE_LOG_FILE, logs[-100:])
        sync_training_manifest(extra_files=[LOCAL_MODE_LOG_FILE])
    except Exception:
        pass


def get_local_fallback_response(message, search_results):
    try:
        response = "🤖 أعمل الآن بالوضع المحلي داخل نظام Garage Manager.\n\n"
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
            response += "لم أجد بيانات مباشرة للسؤال. أستطيع مساعدتك بالبحث في العملاء، المبيعات، الصيانة، المخزون، النفقات، المدفوعات، والصفحات."
        log_local_mode_usage()
        return response
    except Exception as exc:
        return f"⚠️ خطأ في الوضع المحلي: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# AI response pipeline
# ─────────────────────────────────────────────────────────────────────────────

def ai_chat_response(message, search_results=None, session_id="default"):
    keys_json = get_system_setting("AI_API_KEYS", "[]")
    try:
        keys = json.loads(keys_json) if keys_json else []
    except Exception:
        keys = []
    active_key = next((k for k in keys if k.get("is_active")), None)
    if not active_key:
        return get_local_fallback_response(message, search_results or {})

    system_context = gather_system_context()
    try:
        import requests

        api_key = active_key.get("key")
        provider = active_key.get("provider", "groq")
        if "groq" not in str(provider).lower():
            return get_local_fallback_response(message, search_results or {})

        messages = [{"role": "system", "content": build_system_message(system_context)}]
        memory = get_or_create_session_memory(session_id)
        for msg in memory["messages"][-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        enhanced_message = str(message or "")
        if search_results:
            enhanced_message += "\n\nنتائج البحث من قاعدة البيانات:\n"
            enhanced_message += json.dumps(search_results, ensure_ascii=False, default=str)[:12000]
        messages.append({"role": "user", "content": enhanced_message})

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": active_key.get("model", "llama-3.3-70b-versatile"), "messages": messages, "temperature": 0.2, "max_tokens": 2000, "top_p": 0.9},
            timeout=30,
        )
        if response.status_code == 200:
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"]
            add_to_memory(session_id, "user", message)
            add_to_memory(session_id, "assistant", ai_response)
            return ai_response

        _groq_failures.append(_now())
        check_groq_health()
        return get_local_fallback_response(message, search_results or {})
    except Exception:
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
    if search_results.get("today_error"):
        score -= 20
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

        nlp_result = understand_text(message)
        return {"message": message, "normalized": str(message or "").lower(), "intent": nlp_result["intent"]["primary_intent"], "subintent": (nlp_result["intent"].get("secondary_intents") or [None])[0], "entities": list(nlp_result["sentence_structure"].get("entities", {}).keys()), "context_type": nlp_result["sentence_structure"].get("intent") or "question", "sentiment": nlp_result["sentence_structure"].get("sentiment", "neutral"), "priority": "urgent" if nlp_result["sentence_structure"].get("is_urgent") else "normal", "confidence": nlp_result["intent"].get("confidence", 0.5), "keywords": [], "time_scope": None, "requires_data": bool(nlp_result["sentence_structure"].get("entities")), "requires_action": nlp_result["intent"].get("primary_intent") == "executable_command"}
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


def local_intelligent_response(message, session_id=None):
    message = str(message or "")
    message_lower = message.lower()
    context = enhanced_context_understanding(message)

    try:
        from AI.engine.ai_conversation import match_local_response
        rich_response = match_local_response(message, session_id=session_id)
        if rich_response:
            return rich_response
    except Exception:
        pass

    if context.get("context_type") == "greeting":
        stats = gather_system_context()
        return f"👋 أهلاً. أنا المساعد الذكي داخل نظام Garage Manager.\n\n📊 حالة مختصرة:\n{stats.get('current_stats', 'غير متوفر')}"

    if context.get("intent") == "navigation" or any(w in message_lower for w in ["وين", "اين", "أين", "افتح", "رابط", "صفحة"]):
        return handle_navigation_request(message)

    faq = get_local_faq_responses()
    for key, response in faq.items():
        if key.lower() in message_lower:
            return response

    quick_rules = get_local_quick_rules()
    model_map = {}
    try:
        from models import Customer, Expense, Product, ServiceRequest, Supplier
        model_map = {"Customer": Customer, "ServiceRequest": ServiceRequest, "Expense": Expense, "Product": Product, "Supplier": Supplier}
    except Exception:
        model_map = {}
    for rule in quick_rules.values():
        for pattern in rule.get("patterns", []):
            if pattern.lower() in message_lower:
                model = model_map.get(rule.get("model"))
                if model:
                    return rule["response_template"].format(count=_safe_count(model))

    if any(word in message_lower for word in ["vat", "ضريبة القيمة المضافة", "ضريبة مضافة", "ضريبه"]):
        numbers = re.findall(r"\d+(?:\.\d+)?", message)
        if numbers:
            amount = float(numbers[0])
            country = "israel" if "israel" in message_lower or "إسرائيل" in message else "palestine"
            vat = calculate_vat(amount, country)
            return f"💰 حساب VAT:\n• المبلغ: {amount:,.2f}\n• النسبة: {vat['vat_rate']}%\n• الضريبة: {vat['vat_amount']:,.2f}\n• الإجمالي: {vat['total_with_vat']:,.2f}"

    if any(word in message_lower for word in ["خطأ", "error", "traceback", "exception"]):
        return handle_error_question(message).get("formatted_response")

    search_results = search_database_for_query(message)
    validation = validate_search_results(message, search_results)
    if validation.get("has_data"):
        return get_local_fallback_response(message, search_results)

    return "لم أجد بيانات مباشرة كافية. اسألني عن العملاء، الصيانة، المنتجات، النفقات، المدفوعات، المخزون، الصفحات، أو VAT."


def ai_chat_with_search(user_id: int = None, query: str = None, message: str = None, session_id: str = "default", context: Dict = None):
    global _last_audit_time
    if message and not query:
        query = message
    if not query:
        return {"response": "لم يتم تقديم سؤال", "confidence": 0}

    start_time = time.time()
    context = context or {}
    context["user_id"] = user_id
    context["search_results"] = search_database_for_query(query)

    try:
        from AI.engine.ai_master_controller import get_master_controller
        controller = get_master_controller()
        result = controller.process_intelligent_query(query, context)
        answer = result.get("answer", "")
        confidence = float(result.get("confidence", 0.7) or 0.7)
        if not answer:
            raise RuntimeError("empty_controller_answer")
    except Exception:
        answer = _ai_chat_original(query, session_id)
        confidence = 0.65
        result = {"answer": answer, "confidence": confidence, "sources": ["local_fallback"], "tips": []}

    execution_time = time.time() - start_time
    try:
        from AI.engine.ai_self_evolution import get_evolution_engine
        get_evolution_engine().record_interaction(query=query, response=result, success=bool(answer), confidence=confidence, execution_time=execution_time)
    except Exception:
        pass
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        get_performance_tracker().record_query(query, result, execution_time)
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
        if validation.get("has_data"):
            response = ai_chat_response(message, search_results, session_id)
        else:
            response = local_intelligent_response(message, session_id=session_id)
        if confidence < 70 and "درجة الثقة" not in response:
            response += f"\n\n⚠️ درجة الثقة التقريبية: {confidence}%"
    add_to_memory(session_id, "assistant", response)
    current_time = _now()
    if _last_audit_time is None or (current_time - _last_audit_time) > timedelta(hours=1):
        try:
            generate_self_audit_report()
            _last_audit_time = current_time
        except Exception:
            pass
    return response


def explain_system_structure():
    try:
        structure = _knowledge_structure()
        models = structure.get("models", [])[:15]
        return f"""🏗️ هيكل نظام أزاد

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


__all__ = [
    "get_system_setting",
    "gather_system_context",
    "get_system_navigation_context",
    "get_data_awareness_context",
    "analyze_question_intent",
    "get_or_create_session_memory",
    "add_to_memory",
    "get_conversation_context",
    "deep_data_analysis",
    "analyze_accounting_data",
    "generate_smart_report",
    "build_system_message",
    "query_accounting_data",
    "search_database_for_query",
    "check_groq_health",
    "get_system_identity",
    "get_local_fallback_response",
    "log_local_mode_usage",
    "ai_chat_response",
    "handle_error_question",
    "validate_search_results",
    "calculate_confidence_score",
    "handle_navigation_request",
    "enhanced_context_understanding",
    "local_intelligent_response",
    "ai_chat_with_search",
    "explain_system_structure",
]
