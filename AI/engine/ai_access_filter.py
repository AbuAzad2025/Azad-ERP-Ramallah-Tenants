"""Small access filter helpers for AI service outputs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from AI.engine.ai_permission_guard import can_access_module, filter_search_results, get_permission_context, require_any_permission, require_module

CONTEXT_KEYS = {
    "roles_count": "users",
    "roles": "users",
    "total_users": "users",
    "active_users": "users",
    "failed_logins": "audit",
    "total_audit_logs": "audit",
    "recent_actions": "audit",
    "total_services": "services",
    "pending_services": "services",
    "completed_services": "services",
    "total_customers": "customers",
    "active_customers": "customers",
    "total_vendors": "suppliers",
    "total_suppliers": "suppliers",
    "total_products": "products",
    "products_in_stock": "inventory",
    "total_warehouses": "warehouses",
    "total_payments": "payments",
    "payments_today": "payments",
    "total_expenses": "expenses",
    "latest_usd_ils_rate": "reports",
}

ENTITY_MODULES = {
    "Customer": "customers",
    "ServiceRequest": "services",
    "Product": "products",
    "Supplier": "suppliers",
    "Warehouse": "warehouses",
    "Expense": "expenses",
    "Invoice": "sales",
    "Payment": "payments",
    "Sale": "sales",
}

QUERY_MODULES = {
    "customer_balance": "customers",
    "supplier_balance": "suppliers",
    "gl_account_summary": "ledger",
    "account_balance": "ledger",
    "financial_summary": "reports",
}


def current_access() -> Dict[str, Any]:
    return get_permission_context()


def filter_context(data: Dict[str, Any], access: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    access = access or current_access()
    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    hidden = []
    for key, module in CONTEXT_KEYS.items():
        if key in cleaned and not can_access_module(module, access):
            cleaned.pop(key, None)
            hidden.append(key)
    if hidden:
        cleaned["permission_filtered"] = sorted(hidden)
    labels = {
        "total_users": "المستخدمون",
        "active_users": "النشطون",
        "total_services": "الصيانة",
        "total_customers": "الزبائن",
        "total_suppliers": "الموردون",
        "total_products": "المنتجات",
        "products_in_stock": "منتجات بالمخزون",
        "total_warehouses": "المخازن",
        "total_payments": "الدفعات",
        "payments_today": "دفعات اليوم",
        "total_expenses": "المصاريف",
    }
    lines = [f"{label}: {cleaned[key]}" for key, label in labels.items() if key in cleaned]
    if "cpu_usage" in cleaned or "memory_usage" in cleaned:
        lines.append(f"CPU: {cleaned.get('cpu_usage', 'N/A')}% | RAM: {cleaned.get('memory_usage', 'N/A')}%")
    cleaned["current_stats"] = "\n".join(lines) if lines else "لا توجد إحصائيات متاحة ضمن صلاحياتك الحالية."
    return cleaned


def filter_results(data: Dict[str, Any], access: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return filter_search_results(data or {}, access or current_access())


def filter_entities(intent_or_context: Dict[str, Any], access: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    access = access or current_access()
    data = dict(intent_or_context or {})
    data["entities"] = [entity for entity in data.get("entities", []) or [] if can_access_module(ENTITY_MODULES.get(entity, entity), access)]
    return data


def check_query_type(query_type: str, access: Optional[Dict[str, Any]] = None):
    module = QUERY_MODULES.get(str(query_type or ""))
    if not module:
        return None
    return require_module(module, access or current_access())


def check_ai_entry(access: Optional[Dict[str, Any]] = None):
    return require_any_permission(("access_ai_assistant", "manage_ai", "access_owner_dashboard"), access or current_access(), module="ai")


def check_reports_entry(access: Optional[Dict[str, Any]] = None):
    return require_any_permission(("view_reports", "manage_reports", "view_ledger", "manage_ledger", "access_owner_dashboard"), access or current_access(), module="reports")


__all__ = ["current_access", "filter_context", "filter_results", "filter_entities", "check_query_type", "check_ai_entry", "check_reports_entry"]
