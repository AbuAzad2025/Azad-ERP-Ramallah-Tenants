"""Flask integration for AI transaction feedback."""

from __future__ import annotations

_BOUND_APPS = set()
_SIGNAL_BOUND = False


def bind_ai_flask_feedback(app) -> bool:
    app_id = id(app)
    if app_id in _BOUND_APPS:
        return False

    from flask import flash, jsonify, redirect, request
    from AI.engine.ai_erp_transaction_guard import AITransactionBlocked

    @app.errorhandler(AITransactionBlocked)
    def _ai_transaction_blocked(error):
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        message = getattr(error, "user_message", str(error)) or "تم منع حفظ الحركة بسبب ملاحظة حرجة."
        findings = getattr(error, "findings", []) or []
        wants_json = request.path.startswith("/api/") or request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json"
        if wants_json:
            return jsonify({"success": False, "blocked": True, "message": message, "error": message, "findings": findings}), 422
        try:
            flash(message, "danger")
        except Exception:
            pass
        return redirect(request.referrer or "/")

    @app.context_processor
    def _inject_ai_transaction_helpers():
        def ai_transaction_level_class(level):
            mapping = {"danger": "alert-danger", "warning": "alert-warning", "info": "alert-info", "success": "alert-success"}
            return mapping.get(str(level or "info"), "alert-info")

        def ai_transaction_feedback(limit=3):
            try:
                from AI.engine.ai_transaction_feedback import get_recent_transaction_feedback
                return get_recent_transaction_feedback(limit=limit, user_only=True)
            except Exception:
                return []

        def ai_transaction_latest_message():
            try:
                from AI.engine.ai_transaction_feedback import get_latest_transaction_message
                return get_latest_transaction_message(user_only=True)
            except Exception:
                return ""

        def ai_transaction_summary(limit=5):
            try:
                from AI.engine.ai_transaction_feedback import transaction_feedback_summary
                return transaction_feedback_summary(limit=limit)
            except Exception:
                return {"count": 0, "messages": [], "severity_counts": {}, "events": []}

        return {
            "ai_transaction_level_class": ai_transaction_level_class,
            "ai_transaction_feedback": ai_transaction_feedback,
            "ai_transaction_latest_message": ai_transaction_latest_message,
            "ai_transaction_summary": ai_transaction_summary,
        }

    _BOUND_APPS.add(app_id)
    return True


def install_ai_flask_feedback_signal() -> bool:
    global _SIGNAL_BOUND
    if _SIGNAL_BOUND:
        return False
    try:
        from flask import appcontext_pushed
    except Exception:
        return False

    def _on_app_context(sender, **extra):
        try:
            bind_ai_flask_feedback(sender)
        except Exception:
            pass

    try:
        appcontext_pushed.connect(_on_app_context)
        _SIGNAL_BOUND = True
        return True
    except Exception:
        return False


__all__ = ["bind_ai_flask_feedback", "install_ai_flask_feedback_signal"]
