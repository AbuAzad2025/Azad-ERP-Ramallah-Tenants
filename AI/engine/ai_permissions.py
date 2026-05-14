"""AI permissions and safety gates.

This module is the single access-control helper for AI features. It intentionally
keeps the public function names stable for existing routes while making the
policy safer and easier to audit.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from flask_login import current_user

from models import SystemSettings
from permissions_config.enums import SystemPermissions


# Capability map is descriptive. Actual execution is controlled by
# can_ai_execute_action(), which denies unknown and dangerous actions by default.
AI_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "data_access": {
        "read_customers": True,
        "read_suppliers": True,
        "read_products": True,
        "read_sales": True,
        "read_payments": True,
        "read_expenses": True,
        "read_gl": True,
        "read_services": True,
        "read_inventory": True,
        "read_reports": True,
        "read_users": True,
        "read_settings": True,
        "read_audit": True,
    },
    "data_write": {
        "create_customer": True,
        "create_supplier": True,
        "create_product": True,
        "create_sale": True,
        "create_payment": True,
        "create_expense": True,
        "create_service": True,
        "create_warehouse": True,
        "adjust_stock": True,
        "transfer_stock": True,
        "create_invoice": True,
    },
    "data_modify": {
        "update_customer": True,
        "update_supplier": True,
        "update_product": True,
        "update_sale": False,
        "update_payment": False,
        "update_gl": False,
        "delete_any": False,
    },
    "ai_features": {
        "chat": True,
        "realtime_alerts": True,
        "auto_learning": True,
        "suggestions": True,
        "analysis": True,
        "reports": True,
        "predictions": True,
        "training": True,
    },
}


# One canonical map for AI actions. Keep all actions here instead of scattering
# permission strings across AI engines.
ACTION_PERMISSIONS: Dict[str, str] = {
    # Customers
    "add_customer": "add_customer",
    "create_customer": "add_customer",
    "update_customer": "manage_customers",
    "read_customers": "view_customers",

    # Suppliers / partners
    "create_supplier": "add_supplier",
    "update_supplier": "manage_vendors",
    "read_suppliers": "manage_vendors",

    # Products / inventory
    "create_product": "manage_inventory",
    "update_product": "manage_inventory",
    "read_products": "view_parts",
    "adjust_stock": "manage_inventory",
    "transfer_stock": "warehouse_transfer",
    "create_warehouse": "manage_warehouses",

    # Sales / invoices
    "create_sale": "manage_sales",
    "create_invoice": "manage_sales",
    "read_sales": "view_sales",

    # Service
    "create_service": "manage_service",
    "read_services": "view_service",

    # Payments / expenses
    "create_payment": "manage_payments",
    "read_payments": "manage_payments",
    "create_expense": "manage_expenses",
    "read_expenses": "manage_expenses",

    # Reports / ledger
    "read_reports": "view_reports",
    "read_gl": "manage_ledger",
    "read_audit": "view_audit_logs",

    # System
    "read_users": "manage_users",
    "read_settings": "access_owner_dashboard",

    # AI
    "training": "train_ai",
}


# Operations that the AI should never execute directly. They may be suggested as
# a manual workflow, but not performed by AI automation.
AI_NEVER_EXECUTE = {
    "delete_any",
    "delete_payment",
    "delete_split",
    "delete_split_ref",
    "delete_check",
    "delete_expense",
    "delete_sale",
    "archive_sale",
    "archive_check",
    "archive_expense",
    "update_sale",
    "update_payment",
    "update_gl",
    "void_gl_batch",
    "reverse_gl_batch",
    "fix_unbalanced_batches",
    "restore_database",
    "hard_delete",
}


def _setting_to_python(value: Any, dtype: str | None, default: Any) -> Any:
    dtype = dtype or "string"
    if dtype == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "on"}
        return bool(value)
    if dtype in {"integer", "number"}:
        try:
            return int(value) if dtype == "integer" else float(value)
        except (TypeError, ValueError):
            return default
    if dtype == "json":
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if value is not None else default


def get_ai_permission_setting(key: str, default: Any = None) -> Any:
    """Return an AI permission setting from SystemSettings."""
    try:
        setting = SystemSettings.query.filter_by(key=key).first()
        if not setting:
            return default
        return _setting_to_python(setting.value, setting.data_type, default)
    except Exception:
        return default


def is_ai_enabled() -> bool:
    """Return whether the AI assistant is globally enabled."""
    return bool(get_ai_permission_setting("ai_enabled", True))


def _is_authenticated_user() -> bool:
    return bool(getattr(current_user, "is_authenticated", False))


def _has_permission(user: Any, permission: Any) -> bool:
    checker = getattr(user, "has_permission", None)
    if not callable(checker):
        return False
    perm_value = getattr(permission, "value", permission)
    try:
        return bool(checker(perm_value))
    except Exception:
        try:
            return bool(checker(str(perm_value)))
        except Exception:
            return False


def _is_owner_like(user: Any) -> bool:
    return bool(
        getattr(user, "is_system_account", False)
        or getattr(user, "is_system", False)
        or getattr(user, "username", None) == "__OWNER__"
        or _has_permission(user, SystemPermissions.ACCESS_OWNER_DASHBOARD)
    )


def is_ai_visible_to_role(role_name: str) -> bool:
    """Compatibility wrapper: visibility is permission-based, not role-name based."""
    if not _is_authenticated_user():
        return False
    if _is_owner_like(current_user):
        return True
    return _has_permission(current_user, SystemPermissions.ACCESS_AI_ASSISTANT)


def can_ai_execute_action(action_type: str, user_role: str | None = None) -> bool:
    """Return whether AI may execute a specific action for the current user.

    Unknown actions and destructive actions are denied by default. Write actions
    should still require explicit user confirmation in the caller before being
    executed.
    """
    if not _is_authenticated_user():
        return False

    normalized = str(action_type or "").strip().lower()
    if not normalized or normalized in AI_NEVER_EXECUTE:
        return False

    required_perm = ACTION_PERMISSIONS.get(normalized)
    if not required_perm:
        return False

    return _has_permission(current_user, required_perm)


def get_ai_access_level(user: Any) -> str:
    """Return one of: full, limited, readonly, none."""
    if not user or not getattr(user, "is_authenticated", False):
        return "none"

    if _is_owner_like(user) or _has_permission(user, SystemPermissions.MANAGE_AI):
        return "full"

    if not is_ai_enabled():
        return "none"

    if not _has_permission(user, SystemPermissions.ACCESS_AI_ASSISTANT):
        return "none"

    write_perms = (
        SystemPermissions.MANAGE_SALES,
        SystemPermissions.MANAGE_INVENTORY,
        SystemPermissions.MANAGE_CUSTOMERS,
        SystemPermissions.MANAGE_SERVICE,
    )
    if any(_has_permission(user, perm) for perm in write_perms):
        return "limited"
    return "readonly"


__all__ = [
    "AI_CAPABILITIES",
    "ACTION_PERMISSIONS",
    "AI_NEVER_EXECUTE",
    "get_ai_permission_setting",
    "is_ai_enabled",
    "is_ai_visible_to_role",
    "can_ai_execute_action",
    "get_ai_access_level",
]
