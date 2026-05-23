"""Read-only database search helpers for AI.

Uses actual SQLAlchemy model fields and avoids fabricated/static data. All
results are filtered through ai_permission_guard so the assistant cannot expose
modules outside the current user's permissions.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_

from extensions import db
from AI.engine.ai_permission_guard import can_access_module, filter_search_results, get_permission_context


def _query_text(query: str) -> str:
    return " ".join(str(query or "").lower().strip().split())


def _sum_column(model, *column_names):
    for name in column_names:
        column = getattr(model, name, None)
        if column is not None:
            try:
                return db.session.query(func.sum(column)).scalar() or 0
            except Exception:
                continue
    return 0


def _first_existing(model, names: Iterable[str]):
    for name in names:
        value = getattr(model, name, None)
        if value is not None:
            return value
    return None


def _search_terms(query: str) -> List[str]:
    terms = []
    for token in re.split(r"[\s،,؛;:]+", str(query or "")):
        token = token.strip()
        if len(token) >= 3 and token not in {"كم", "عدد", "رصيد", "زبون", "مورد", "منتج", "قطعة", "مبيعات", "دفع", "دفعة", "مصروف", "صيانة", "customer", "supplier", "product", "sales", "payment", "expense", "service"}:
            terms.append(token)
    return terms[:6]


def _or_ilike(model, fields: Iterable[str], terms: List[str]):
    clauses = []
    for field in fields:
        col = getattr(model, field, None)
        if col is None:
            continue
        for term in terms:
            clauses.append(col.ilike(f"%{term}%"))
    return or_(*clauses) if clauses else None


def _allow(module: str, permission_context: Optional[Dict[str, Any]]) -> bool:
    return can_access_module(module, permission_context or get_permission_context())


def search_database_for_query(query: str, permission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        permission_context = permission_context or get_permission_context()
        results = {"intent": None}
        query_lower = _query_text(query)
        intent = analyze_query_intent(query_lower)
        results["intent"] = intent
        entities = intent.get("entities", [])

        if ("customer" in entities or any(word in query_lower for word in ["زبون", "زبون", "customer"])) and _allow("customers", permission_context):
            results.update(search_customers(query_lower))
        if ("supplier" in entities or any(word in query_lower for word in ["مورد", "vendor", "supplier"])) and _allow("suppliers", permission_context):
            results.update(search_suppliers(query_lower))
        if ("product" in entities or any(word in query_lower for word in ["منتج", "قطعة", "product", "part"])) and _allow("products", permission_context):
            results.update(search_products(query_lower))
        if ("service" in entities or any(word in query_lower for word in ["صيانة", "service", "repair"])) and _allow("services", permission_context):
            results.update(search_services(query_lower))
        if ("sale" in entities or any(word in query_lower for word in ["مبيعات", "بيع", "sales", "sell"])) and _allow("sales", permission_context):
            results.update(search_sales(query_lower))
        if ("payment" in entities or any(word in query_lower for word in ["دفع", "payment", "pay", "دفعة"])) and _allow("payments", permission_context):
            results.update(search_payments(query_lower))
        if ("expense" in entities or any(word in query_lower for word in ["مصروف", "expense", "نفقة"])) and _allow("expenses", permission_context):
            results.update(search_expenses(query_lower))
        if ("inventory" in entities or any(word in query_lower for word in ["مخزون", "inventory", "stock"])) and _allow("inventory", permission_context):
            results.update(search_inventory(query_lower))

        if len(results) <= 1:
            results.update(get_general_statistics(permission_context=permission_context))
        return filter_search_results(results, permission_context)
    except Exception as exc:
        return {"error": str(exc), "intent": None}


def analyze_query_intent(query_lower: str) -> Dict[str, Any]:
    query_lower = _query_text(query_lower)
    intent = {"type": "general", "entities": [], "time_scope": "all", "action": "search"}
    if any(word in query_lower for word in ["كم", "عدد", "how many", "count"]):
        intent.update(type="count", action="calculate")
    elif any(word in query_lower for word in ["رصيد", "balance", "حساب"]):
        intent.update(type="balance", action="calculate")
    elif any(word in query_lower for word in ["قائمة", "list", "أعرض", "اعرض", "show"]):
        intent.update(type="list", action="search")
    elif any(word in query_lower for word in ["تحليل", "analyze", "تقرير", "report"]):
        intent.update(type="analysis", action="report")

    entity_keywords = {
        "customer": ["زبون", "زبون", "customer", "client"],
        "supplier": ["مورد", "vendor", "supplier"],
        "product": ["منتج", "قطعة", "product", "part", "item"],
        "service": ["صيانة", "service", "repair", "خدمة"],
        "sale": ["مبيعات", "بيع", "sales", "sell"],
        "invoice": ["فاتورة", "invoice"],
        "payment": ["دفع", "payment", "دفعة"],
        "expense": ["مصروف", "expense", "نفقة"],
        "inventory": ["مخزون", "inventory", "stock"],
    }
    for entity, keywords in entity_keywords.items():
        if any(kw in query_lower for kw in keywords):
            intent["entities"].append(entity)

    if any(word in query_lower for word in ["اليوم", "today"]):
        intent["time_scope"] = "today"
    elif any(word in query_lower for word in ["هالأسبوع", "this week", "أسبوع", "اسبوع"]):
        intent["time_scope"] = "week"
    elif any(word in query_lower for word in ["هالشهر", "this month", "شهر"]):
        intent["time_scope"] = "month"
    elif any(word in query_lower for word in ["هالسنة", "this year", "سنة"]):
        intent["time_scope"] = "year"
    return intent


def get_time_range(scope: str) -> tuple:
    now = datetime.now(timezone.utc)
    if scope == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if scope == "week":
        return now - timedelta(days=7), now
    if scope == "month":
        return now - timedelta(days=30), now
    if scope == "year":
        return now - timedelta(days=365), now
    return datetime(2000, 1, 1, tzinfo=timezone.utc), now


def search_customers(query: str) -> Dict[str, Any]:
    try:
        from models import Customer
        result = {"customers_count": Customer.query.count(), "customers_active": Customer.query.filter_by(is_active=True).count()}
        terms = _search_terms(query)
        clause = _or_ilike(Customer, ["name", "phone", "email", "whatsapp"], terms)
        if clause is not None:
            found = Customer.query.filter(clause).limit(10).all()
            if found:
                result["customers_found"] = [{"id": c.id, "name": c.name, "phone": c.phone, "balance": float(getattr(c, "balance", 0) or 0)} for c in found]
        samples = Customer.query.order_by(Customer.id.desc()).limit(5).all()
        result["customers_sample"] = [{"id": c.id, "name": c.name, "phone": c.phone} for c in samples]
        return result
    except Exception as exc:
        return {"customers_error": str(exc)}


def search_suppliers(query: str) -> Dict[str, Any]:
    try:
        from models import Supplier
        result = {"suppliers_count": Supplier.query.count()}
        terms = _search_terms(query)
        clause = _or_ilike(Supplier, ["name", "phone", "email", "contact", "identity_number"], terms)
        if clause is not None:
            found = Supplier.query.filter(clause).limit(10).all()
            if found:
                result["suppliers_found"] = [{"id": s.id, "name": s.name, "phone": s.phone, "balance": float(getattr(s, "balance", 0) or 0)} for s in found]
        return result
    except Exception as exc:
        return {"suppliers_error": str(exc)}


def search_products(query: str) -> Dict[str, Any]:
    try:
        from models import Product
        result = {"products_count": Product.query.count()}
        terms = _search_terms(query)
        clause = _or_ilike(Product, ["name", "sku", "barcode", "part_number", "brand", "commercial_name"], terms)
        if clause is not None:
            found = Product.query.filter(clause).limit(10).all()
            if found:
                result["products_found"] = [{"id": p.id, "name": p.name, "sku": p.sku, "price": float(getattr(p, "price", 0) or 0), "selling_price": float(getattr(p, "selling_price", 0) or 0)} for p in found]
        return result
    except Exception as exc:
        return {"products_error": str(exc)}


def search_services(query: str) -> Dict[str, Any]:
    try:
        from models import ServiceRequest, ServiceStatus
        pending = ServiceStatus.PENDING.value
        completed = ServiceStatus.COMPLETED.value
        return {"services_total": ServiceRequest.query.count(), "services_pending": ServiceRequest.query.filter_by(status=pending).count(), "services_completed": ServiceRequest.query.filter_by(status=completed).count()}
    except Exception as exc:
        return {"services_error": str(exc)}


def search_sales(query: str) -> Dict[str, Any]:
    try:
        from models import Sale, SaleStatus
        confirmed = SaleStatus.CONFIRMED.value
        total_count = Sale.query.filter_by(status=confirmed).count()
        total_amount = _sum_column(Sale, "total_amount")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        sale_date = _first_existing(Sale, ["sale_date", "created_at"])
        amount_col = _first_existing(Sale, ["total_amount"])
        today_sales = 0
        if sale_date is not None and amount_col is not None:
            today_sales = db.session.query(func.sum(amount_col)).filter(Sale.status == confirmed, sale_date >= today).scalar() or 0
        return {"sales_count": total_count, "sales_total": float(total_amount), "sales_today": float(today_sales)}
    except Exception as exc:
        return {"sales_error": str(exc)}


def search_payments(query: str) -> Dict[str, Any]:
    try:
        from models import Payment
        return {"payments_count": Payment.query.count(), "payments_total": float(_sum_column(Payment, "total_amount"))}
    except Exception as exc:
        return {"payments_error": str(exc)}


def search_expenses(query: str) -> Dict[str, Any]:
    try:
        from models import Expense
        return {"expenses_count": Expense.query.count(), "expenses_total": float(_sum_column(Expense, "amount", "total_amount"))}
    except Exception as exc:
        return {"expenses_error": str(exc)}


def search_inventory(query: str) -> Dict[str, Any]:
    try:
        from models import StockLevel, Warehouse
        products_in_stock = db.session.query(func.count(func.distinct(StockLevel.product_id))).scalar() or 0
        low_stock = StockLevel.query.filter(StockLevel.min_stock.isnot(None), StockLevel.quantity < StockLevel.min_stock).count() if hasattr(StockLevel, "min_stock") else 0
        return {"inventory_products_count": products_in_stock, "warehouses_count": Warehouse.query.count(), "low_stock_count": low_stock}
    except Exception as exc:
        return {"inventory_error": str(exc)}


def get_general_statistics(permission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from models import Customer, Expense, Product, Sale, ServiceRequest, Supplier, User, Warehouse
        permission_context = permission_context or get_permission_context()
        stats = {}
        if _allow("customers", permission_context):
            stats["general_customers"] = Customer.query.count()
        if _allow("suppliers", permission_context):
            stats["general_suppliers"] = Supplier.query.count()
        if _allow("products", permission_context):
            stats["general_products"] = Product.query.count()
        if _allow("services", permission_context):
            stats["general_services"] = ServiceRequest.query.count()
        if _allow("users", permission_context):
            stats["general_users"] = User.query.count()
        if _allow("warehouses", permission_context):
            stats["general_warehouses"] = Warehouse.query.count()
        if _allow("sales", permission_context):
            stats["general_sales"] = Sale.query.count()
        if _allow("expenses", permission_context):
            stats["general_expenses"] = Expense.query.count()
        if not stats:
            stats["permission_note"] = "لا توجد إحصائيات عامة متاحة ضمن صلاحيات المستخدم الحالي."
        return stats
    except Exception as exc:
        return {"general_error": str(exc)}


def search_in_database(query: str, permission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return search_database_for_query(query, permission_context=permission_context)


__all__ = ["search_database_for_query", "search_in_database", "analyze_query_intent", "get_time_range"]
