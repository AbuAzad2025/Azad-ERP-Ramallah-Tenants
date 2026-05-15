"""Quality scoring for the ERP AI assistant."""

from __future__ import annotations

from typing import Dict, List

CHECKS = (
    ("permission_guard", "AI.engine.ai_permission_guard", "can_access_module", 15),
    ("access_filter", "AI.engine.ai_access_filter", "filter_results", 10),
    ("service_binding", "AI.engine.ai_access_bind", "bind_ai_service_access", 10),
    ("input_filter", "AI.engine.ai_input_filter", "inspect_text", 15),
    ("controller_security", "AI.engine.ai_controller_security_bind", "bind_ai_controller_security", 10),
    ("management_security", "AI.engine.ai_management_security_bind", "bind_ai_management_security", 5),
    ("transaction_guard", "AI.engine.ai_erp_transaction_guard", "bind_erp_transaction_guard", 15),
    ("control_auditor", "AI.engine.ai_accounting_auditor", "get_accounting_auditor", 10),
    ("database_search", "AI.engine.ai_database_search", "search_database_for_query", 5),
    ("expert_guide", "AI.engine.ai_user_guide_master", "get_user_guide_master", 5),
)


def _has(module_path: str, symbol: str) -> bool:
    try:
        module = __import__(module_path, fromlist=[symbol])
        return hasattr(module, symbol)
    except Exception:
        return False


def get_ai_erp_quality_score() -> Dict:
    total = sum(item[3] for item in CHECKS)
    score = 0
    checks: List[Dict] = []
    for name, module_path, symbol, weight in CHECKS:
        ok = _has(module_path, symbol)
        if ok:
            score += weight
        checks.append({"name": name, "ok": ok, "weight": weight})
    percent = round((score / total) * 100, 2) if total else 0
    if percent >= 95:
        level = "world_class_candidate"
    elif percent >= 85:
        level = "strong"
    elif percent >= 70:
        level = "good_needs_testing"
    else:
        level = "incomplete"
    return {
        "score": percent,
        "level": level,
        "checks": checks,
        "required_runtime_tests": [
            "restart server and verify AI import hooks are active",
            "test normal user cannot read users/audit/reports without permissions",
            "test unsafe prompt is blocked and logged",
            "test critical payment/stock transaction is logged by ERP guard",
            "enable ai_erp_guard_block_critical only after confirming no false positives",
        ],
    }


__all__ = ["get_ai_erp_quality_score"]
