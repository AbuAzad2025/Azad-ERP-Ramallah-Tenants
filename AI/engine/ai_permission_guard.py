"""Permission guard for the AI assistant.

The assistant must never become a backdoor around the application's roles and
permissions. This module centralizes permission checks for AI search, guide,
control-audit, and data exposure paths.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

try:
    from flask_login import current_user
except Exception:  # pragma: no cover
    current_user = None

try:
    from permissions_config.enums import SystemPermissions
except Exception:  # pragma: no cover
    SystemPermissions = None

DENIED_MESSAGE = "⛔ لا أملك صلاحية عرض هذه البيانات أو تنفيذ هذا الطلب لحسابك الحالي."

MODULE_PERMISSION_MAP: Dict[str, Sequence[str]] = {
    "customers": ("view_customers", "manage_customers", "access_owner_dashboard"),
    "customer": ("view_customers", "manage_customers", "access_owner_dashboard"),
    "suppliers": ("manage_vendors", "add_supplier", "access_owner_dashboard"),
    "supplier": ("manage_vendors", "add_supplier", "access_owner_dashboard"),
    "vendors": ("manage_vendors", "access_owner_dashboard"),
    "products": ("view_parts", "view_inventory", "manage_inventory", "manage_warehouses", "access_owner_dashboard"),
    "product": ("view_parts", "view_inventory", "manage_inventory", "manage_warehouses", "access_owner_dashboard"),
    "inventory": ("view_inventory", "manage_inventory", "view_warehouses", "manage_warehouses", "access_owner_dashboard"),
    "warehouses": ("view_warehouses", "manage_warehouses", "view_inventory", "access_owner_dashboard"),
    "warehouse": ("view_warehouses", "manage_warehouses", "view_inventory", "access_owner_dashboard"),
    "service": ("view_service", "manage_service", "access_owner_dashboard"),
    "services": ("view_service", "manage_service", "access_owner_dashboard"),
    "sale": ("view_sales", "manage_sales", "access_owner_dashboard"),
    "sales": ("view_sales", "manage_sales", "access_owner_dashboard"),
    "invoice": ("view_sales", "manage_sales", "view_reports", "manage_reports", "access_owner_dashboard"),
    "payments": ("view_payments", "manage_payments", "access_owner_dashboard"),
    "payment": ("view_payments", "manage_payments", "access_owner_dashboard"),
    "expenses": ("manage_expenses", "view_reports", "manage_reports", "access_owner_dashboard"),
    "expense": ("manage_expenses", "view_reports", "manage_reports", "access_owner_dashboard"),
    "reports": ("view_reports", "manage_reports", "access_owner_dashboard"),
    "ledger": ("view_ledger", "manage_ledger", "manage_advanced_accounting", "access_owner_dashboard"),
    "general_ledger": ("view_ledger", "manage_ledger", "manage_advanced_accounting", "access_owner_dashboard"),
    "gl": ("view_ledger", "manage_ledger", "manage_advanced_accounting", "access_owner_dashboard"),
    "users": ("manage_users", "manage_roles", "manage_permissions", "manage_any_user_permissions", "access_owner_dashboard"),
    "audit": ("view_audit_logs", "manage_ai", "access_owner_dashboard"),
    "control_audit": ("view_audit_logs", "manage_ai", "manage_system_config", "access_owner_dashboard"),
    "ai": ("access_ai_assistant", "manage_ai", "access_owner_dashboard"),
}

SENSITIVE_PERMISSIONS = {
    "manage_ai",
    "train_ai",
    "view_audit_logs",
    "manage_system_config",
    "manage_any_user_permissions",
    "manage_permissions",
    "manage_roles",
    "manage_users",
    "access_owner_dashboard",
    "backup_database",
    "restore_database",
    "hard_delete",
    "manage_advanced_accounting",
}

RESULT_KEY_MODULES = {
    "customers": "customers",
    "customers_count": "customers",
    "customers_active": "customers",
    "customers_found": "customers",
    "customers_sample": "customers",
    "suppliers": "suppliers",
    "suppliers_count": "suppliers",
    "suppliers_found": "suppliers",
    "products": "products",
    "products_count": "products",
    "products_found": "products",
    "services_total": "services",
    "services_pending": "services",
    "services_completed": "services",
    "sales_count": "sales",
    "sales_total": "sales",
    "sales_today": "sales",
    "payments_count": "payments",
    "payments_total": "payments",
    "expenses_count": "expenses",
    "expenses_total": "expenses",
    "inventory_products_count": "inventory",
    "warehouses_count": "warehouses",
    "low_stock_count": "inventory",
    "general_users": "users",
    "general_customers": "customers",
    "general_suppliers": "suppliers",
    "general_products": "products",
    "general_services": "services",
    "general_warehouses": "warehouses",
    "general_sales": "sales",
    "general_expenses": "expenses",
    "accounting_knowledge": "ledger",
    "gl_summary": "ledger",
    "financial_summary": "reports",
}

ENTITY_TO_MODULE = {
    "Customer": "customers",
    "customer": "customers",
    "Supplier": "suppliers",
    "supplier": "suppliers",
    "Product": "products",
    "product": "products",
    "Warehouse": "warehouses",
    "warehouse": "warehouses",
    "ServiceRequest": "services",
    "service": "services",
    "Sale": "sales",
    "sale": "sales",
    "Invoice": "invoice",
    "invoice": "invoice",
    "Payment": "payments",
    "payment": "payments",
    "Expense": "expenses",
    "expense": "expenses",
    "GLBatch": "ledger",
    "GLEntry": "ledger",
    "Account": "ledger",
}


def _perm_value(permission: Any) -> str:
    return str(getattr(permission, "value", permission) or "").strip().lower()


def _candidate_permissions(permissions: Iterable[Any]) -> Set[str]:
    return {_perm_value(p) for p in permissions if _perm_value(p)}


def _system_perm_values(names: Iterable[str]) -> Set[str]:
    output = set()
    for name in names:
        output.add(_perm_value(name))
        try:
            if SystemPermissions is not None:
                enum_name = str(name).upper()
                if hasattr(SystemPermissions, enum_name):
                    output.add(_perm_value(getattr(SystemPermissions, enum_name)))
        except Exception:
            pass
    return output


def get_permission_context(user: Any = None) -> Dict[str, Any]:
    """Build a compact, serializable permission context for AI calls."""
    user = user or _current_user_object()
    if not user or not bool(getattr(user, "is_authenticated", False)):
        return {"authenticated": False, "user_id": None, "username": None, "role": None, "permissions": [], "is_owner_like": False, "is_system": False}

    role = (getattr(user, "role_name_l", "") or getattr(getattr(user, "role", None), "name", "") or "").strip().lower()
    is_system = bool(getattr(user, "is_system", False) or getattr(user, "is_system_account", False))
    from permissions_config.role_policy import is_super_role_user

    is_owner_like = bool(is_system or is_super_role_user(user))

    known_perms = set()
    for values in MODULE_PERMISSION_MAP.values():
        known_perms |= _system_perm_values(values)
    known_perms |= _system_perm_values(SENSITIVE_PERMISSIONS)
    known_perms.add("access_ai_assistant")

    granted = set()
    checker = getattr(user, "has_permission", None)
    if callable(checker):
        for perm in sorted(known_perms):
            try:
                if checker(perm):
                    granted.add(perm)
            except Exception:
                continue

    if is_owner_like:
        granted |= known_perms

    return {
        "authenticated": True,
        "user_id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "role": role,
        "permissions": sorted(granted),
        "is_owner_like": is_owner_like,
        "is_system": is_system,
    }


def _current_user_object():
    try:
        if current_user is None:
            return None
        return current_user._get_current_object() if hasattr(current_user, "_get_current_object") else current_user
    except Exception:
        return None


def can_access_permission(permission_context: Optional[Dict[str, Any]], permissions: Iterable[str]) -> bool:
    ctx = permission_context or get_permission_context()
    if ctx.get("is_owner_like") or ctx.get("is_system"):
        return True
    granted = _candidate_permissions(ctx.get("permissions", []))
    required = _system_perm_values(permissions)
    return bool(granted & required)


def required_permissions_for_module(module: str) -> Sequence[str]:
    return MODULE_PERMISSION_MAP.get(str(module or "").strip(), ())


def can_access_module(module: str, permission_context: Optional[Dict[str, Any]] = None) -> bool:
    module = ENTITY_TO_MODULE.get(module, module)
    required = required_permissions_for_module(module)
    if not required:
        return True
    return can_access_permission(permission_context, required)


def denied_response(module: str = None, action: str = None) -> Dict[str, Any]:
    target = f" ({module})" if module else ""
    return {"success": False, "denied": True, "error": DENIED_MESSAGE, "response": f"{DENIED_MESSAGE}{target}", "confidence": 1.0, "sources": ["permission_guard"], "module": module, "action": action}


def filter_intent_entities(intent: Dict[str, Any], permission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    intent = dict(intent or {})
    allowed = []
    denied = []
    for entity in intent.get("entities", []) or []:
        module = ENTITY_TO_MODULE.get(entity, entity)
        if can_access_module(module, permission_context):
            allowed.append(entity)
        else:
            denied.append({"entity": entity, "module": module})
    intent["entities"] = allowed
    if denied:
        intent["permission_denied_entities"] = denied
    return intent


def filter_search_results(results: Dict[str, Any], permission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(results, dict):
        return results
    filtered = {}
    denied = []
    for key, value in results.items():
        if key in {"intent", "error", "warnings"}:
            filtered[key] = value
            continue
        module = RESULT_KEY_MODULES.get(key)
        if module and not can_access_module(module, permission_context):
            denied.append({"key": key, "module": module})
            continue
        filtered[key] = value
    if denied:
        filtered["permission_filtered"] = denied
        warnings = list(filtered.get("warnings", []) or [])
        warnings.append("تم إخفاء بعض النتائج لأنها خارج صلاحيات المستخدم الحالي.")
        filtered["warnings"] = warnings
    return filtered


def require_module(module: str, permission_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if can_access_module(module, permission_context):
        return None
    return denied_response(module=module)


def require_any_permission(permissions: Iterable[str], permission_context: Optional[Dict[str, Any]] = None, module: str = None) -> Optional[Dict[str, Any]]:
    if can_access_permission(permission_context, permissions):
        return None
    return denied_response(module=module)


def explain_allowed_modules(permission_context: Optional[Dict[str, Any]] = None) -> List[str]:
    ctx = permission_context or get_permission_context()
    modules = []
    for module in sorted(MODULE_PERMISSION_MAP):
        if can_access_module(module, ctx):
            modules.append(module)
    return modules


__all__ = [
    "DENIED_MESSAGE",
    "MODULE_PERMISSION_MAP",
    "RESULT_KEY_MODULES",
    "ENTITY_TO_MODULE",
    "get_permission_context",
    "can_access_permission",
    "can_access_module",
    "filter_intent_entities",
    "filter_search_results",
    "require_module",
    "require_any_permission",
    "denied_response",
    "explain_allowed_modules",
]
