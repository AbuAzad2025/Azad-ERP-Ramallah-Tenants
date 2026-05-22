"""
تطبيع أكواد سجل التدقيق — طول آمن ومرادفات قصيرة للأحداث الطويلة.
"""
from __future__ import annotations

import hashlib
import re

AUDIT_ACTION_MAX_LEN = 64

# أحداث طويلة → رموز ثابتة (≤20 حرفاً للتوافق مع قواعد قديمة)
_AUDIT_ACTION_ALIASES: dict[str, str] = {
    "login.master_key_success_tenant": "MK_OK_TENANT",
    "login.master_key_success": "MK_OK",
    "login.master_key_no_tenant_owner": "MK_NO_TENANT",
    "login.master_key_no_active_owner": "MK_NO_OWNER",
    "login.success.customer": "LOGIN_OK_CUST",
    "customer.password_reset": "CUST_PWD_RST",
    "customer.register": "CUST_REGISTER",
    "login.blocked": "LOGIN_BLOCKED",
    "login.failed": "LOGIN_FAILED",
    "login.success": "LOGIN_OK",
    "logout": "LOGOUT",
    "reveal_card_attempt": "CARD_REVEAL_TRY",
    "reveal_card_mismatch": "CARD_REVEAL_MM",
    "reveal_card": "CARD_REVEAL_OK",
    "data_quality_fix": "DATA_QUALITY_FIX",
    "advanced_check_linking": "ADV_CHK_LINK",
    "python_exec": "PYTHON_EXEC",
}


def normalize_audit_action(action: str, *, max_len: int = AUDIT_ACTION_MAX_LEN) -> str:
    raw = (action or "").strip()
    if not raw:
        return "UNKNOWN"
    key = raw.lower()
    if key in _AUDIT_ACTION_ALIASES:
        return _AUDIT_ACTION_ALIASES[key]
    compact = re.sub(r"[^A-Z0-9_]+", "_", raw.upper()).strip("_")
    if not compact:
        return "UNKNOWN"
    if len(compact) <= max_len:
        return compact
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    head = compact[: max(1, max_len - 9)]
    return f"{head}_{digest}"
