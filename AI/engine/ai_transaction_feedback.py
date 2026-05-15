"""Read recent AI transaction feedback messages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from AI.engine.ai_storage import read_json

FEEDBACK_FILE = "ai_erp_guard_events.json"


def _current_user_id() -> Optional[int]:
    try:
        from flask_login import current_user
        if current_user and getattr(current_user, "is_authenticated", False):
            return getattr(current_user, "id", None)
    except Exception:
        pass
    return None


def _load_events() -> List[Dict[str, Any]]:
    data = read_json(FEEDBACK_FILE, [])
    if isinstance(data, dict):
        for key in ("items", "events", "log", "data", "control_audit_log"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def get_recent_transaction_feedback(limit: int = 5, user_only: bool = True) -> List[Dict[str, Any]]:
    try:
        limit = max(1, min(20, int(limit or 5)))
    except Exception:
        limit = 5
    user_id = _current_user_id() if user_only else None
    rows = []
    for item in reversed(_load_events()):
        if user_id and item.get("user_id") not in (None, user_id):
            continue
        message = item.get("user_message") or ""
        findings = item.get("findings") or []
        if not message and findings:
            try:
                from AI.engine.ai_transaction_copilot import compact_user_message
                message = compact_user_message(findings)
            except Exception:
                message = ""
        rows.append({"timestamp": item.get("timestamp"), "message": message, "findings": findings[:10], "user_id": item.get("user_id")})
        if len(rows) >= limit:
            break
    return rows


def get_latest_transaction_message(user_only: bool = True) -> str:
    rows = get_recent_transaction_feedback(limit=1, user_only=user_only)
    return rows[0].get("message", "") if rows else ""


def transaction_feedback_summary(limit: int = 5) -> Dict[str, Any]:
    rows = get_recent_transaction_feedback(limit=limit)
    severities = {}
    for row in rows:
        for finding in row.get("findings", []) or []:
            sev = str(finding.get("severity", "LOW")).upper()
            severities[sev] = severities.get(sev, 0) + 1
    return {"count": len(rows), "messages": [r.get("message") for r in rows if r.get("message")], "severity_counts": severities, "events": rows}


__all__ = ["get_recent_transaction_feedback", "get_latest_transaction_message", "transaction_feedback_summary"]
