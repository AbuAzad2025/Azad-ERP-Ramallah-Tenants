from collections import defaultdict
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from utils import permission_required
from permissions_config.enums import SystemPermissions

from AI.engine.ai_service import ai_chat_with_search, gather_system_context
from AI.engine.ai_management import (
    get_live_ai_stats,
    get_model_status,
    get_training_job_status,
    list_configured_apis,
    save_api_key_encrypted,
    start_training_job,
    test_api_key,
)
from AI.engine.ai_storage import append_json_list, read_json


ai_bp = Blueprint("ai", __name__, url_prefix="/ai")


def _has_permission(permission: Any) -> bool:
    checker = getattr(current_user, "has_permission", None)
    if not callable(checker):
        return False
    candidates = [getattr(permission, "value", permission), permission]
    for candidate in candidates:
        try:
            if checker(candidate):
                return True
        except Exception:
            continue
    return False


def _normalize_ai_response(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict):
        text = response.get("response") or response.get("answer") or response.get("message") or ""
        return {
            "success": bool(response.get("success", True)),
            "response": str(text),
            "confidence": response.get("confidence", 0),
            "sources": response.get("sources", []) or [],
            "warnings": response.get("warnings", []) or [],
            "tips": response.get("tips", []) or [],
            "raw": response,
        }
    return {"success": True, "response": str(response or ""), "confidence": 0, "sources": [], "warnings": [], "tips": [], "raw": response}


def _chat_for_current_user(message: str) -> Dict[str, Any]:
    raw_response = ai_chat_with_search(message=message, session_id=f"user_{current_user.id}")
    return _normalize_ai_response(raw_response)


def ai_access(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("⛔ يجب تسجيل الدخول", "danger")
            return redirect(url_for("auth.login"))

        from AI.engine.ai_permissions import is_ai_enabled

        if not is_ai_enabled() and not _has_permission(SystemPermissions.ACCESS_OWNER_DASHBOARD):
            flash("⛔ المساعد الذكي معطّل حالياً", "warning")
            return redirect(url_for("main.dashboard"))

        is_owner_like = bool(
            getattr(current_user, "is_system", False)
            or getattr(current_user, "is_system_account", False)
            or getattr(current_user, "role_name_l", "") in {"owner", "developer"}
            or _has_permission(SystemPermissions.ACCESS_OWNER_DASHBOARD)
        )
        if not is_owner_like:
            flash("⛔ غير مصرح لك بالوصول للمساعد الذكي", "danger")
            return redirect(url_for("main.dashboard"))

        if _has_permission(SystemPermissions.ACCESS_AI_ASSISTANT):
            return f(*args, **kwargs)

        flash("⛔ غير مصرح لك بالوصول للمساعد الذكي", "danger")
        return redirect(url_for("main.dashboard"))

    return decorated_function


@ai_bp.route("/hub")
@ai_access
def hub():
    tab = request.args.get("tab", "assistant")
    model_statuses = get_model_status()
    models_status = model_statuses.get("models", {}) if isinstance(model_statuses, dict) else {}
    return render_template("ai/ai_hub.html", active_tab=tab, ai_stats=_get_ai_stats(), system_stats=_get_system_stats(), recent_queries=_get_recent_queries(limit=5), predictions=_get_predictions(), api_keys_configured=_check_api_keys(), model_statuses=models_status)


@ai_bp.route("/assistant", methods=["GET", "POST"])
@ai_access
def assistant():
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if not query:
            flash("⚠️ الرجاء إدخال سؤال", "warning")
            return redirect(url_for("ai.assistant"))
        try:
            response = _chat_for_current_user(query)
            _save_conversation(query, response)
            return render_template("ai/ai_assistant.html", query=query, response=response, suggestions=_get_ai_suggestions())
        except Exception as exc:
            flash(f"❌ خطأ: {exc}", "danger")
            return redirect(url_for("ai.assistant"))
    return render_template("ai/ai_assistant.html", suggestions=_get_ai_suggestions(), recent_conversations=_get_recent_conversations(limit=5))


@ai_bp.route("/chat", methods=["POST"])
@ai_access
def chat():
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"success": False, "error": "الرسالة فارغة"}), 400
        response = _chat_for_current_user(message)
        _save_conversation(message, response)
        return jsonify({"success": response.get("success", True), "response": response.get("response") or "عذراً، لم أتمكن من الإجابة", "confidence": response.get("confidence", 0), "sources": response.get("sources", []), "warnings": response.get("warnings", []), "timestamp": datetime.now().isoformat()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@ai_bp.route("/system-map", methods=["GET", "POST"])
@permission_required(SystemPermissions.MANAGE_AI)
def system_map():
    from AI.engine.ai_auto_discovery import build_system_map, load_system_map, DISCOVERY_LOG_FILE
    if request.method == "POST":
        action = request.form.get("action")
        if action == "rebuild":
            try:
                build_system_map()
                flash("✅ تم إعادة بناء خريطة النظام بنجاح!", "success")
            except Exception as exc:
                flash(f"⚠️ خطأ: {exc}", "danger")
            return redirect(url_for("ai.system_map"))
    system_map_data = load_system_map()
    map_exists = system_map_data is not None
    if system_map_data is None:
        system_map_data = {"generated_at": "", "system_name": "", "version": "", "statistics": {"total_routes": 0, "total_templates": 0, "linked_routes": 0, "unlinked_routes": 0}, "routes": {"all": [], "by_category": {}}, "templates": {"all": [], "by_module": {}}, "blueprints": [], "modules": []}
    logs = read_json(DISCOVERY_LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    return render_template("ai/system_map.html", system_map=system_map_data, map_exists=map_exists, logs=logs[-10:])


@ai_bp.route("/training/start", methods=["POST"])
@permission_required(SystemPermissions.TRAIN_AI)
def start_training():
    try:
        data = request.get_json(silent=True) or {}
        result = start_training_job(data.get("model_name", "unknown"), data.get("training_type", "quick"), data.get("data_range", "all"))
        return jsonify(result), 200 if result.get("success") else 500
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@ai_bp.route("/training/status/<training_id>")
@permission_required(SystemPermissions.MANAGE_AI)
def training_status(training_id):
    job = get_training_job_status(training_id)
    if job:
        return jsonify({"success": True, "job": job})
    return jsonify({"success": False, "error": "التدريب غير موجود"}), 404


@ai_bp.route("/models/status", methods=["GET"])
@ai_access
def models_status():
    try:
        model_statuses = get_model_status()
        models = model_statuses.get("models", {}) if isinstance(model_statuses, dict) else {}
        return jsonify({"success": True, "models": models})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@ai_bp.route("/api-keys/save", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_AI)
def save_api_key():
    try:
        data = request.get_json(silent=True) or {}
        api_name = data.get("api_name")
        api_key = data.get("api_key")
        if not api_name or not api_key:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400
        success = save_api_key_encrypted(api_name, api_key)
        if success:
            return jsonify({"success": True, "message": f"تم تحديث إعداد {api_name} بنجاح"})
        return jsonify({"success": False, "error": "فشل في تحديث الإعداد"}), 500
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@ai_bp.route("/api-keys/test", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_AI)
def test_api_key_route():
    try:
        data = request.get_json(silent=True) or {}
        api_name = data.get("api_name")
        if not api_name:
            return jsonify({"success": False, "error": "اسم المزود مطلوب"}), 400
        return jsonify(test_api_key(api_name))
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@ai_bp.route("/stats/live")
@ai_access
def live_stats():
    return jsonify({"success": True, "stats": get_live_ai_stats()})


@ai_bp.route("/analytics/queries")
@permission_required(SystemPermissions.MANAGE_AI)
def analytics_queries():
    interactions = read_json("ai_interactions.json", [])
    if isinstance(interactions, list) and interactions:
        daily_counts = defaultdict(int)
        for interaction in interactions[-100:]:
            timestamp = str(interaction.get("timestamp", ""))
            if timestamp:
                daily_counts[timestamp[:10]] += 1
        labels = list(daily_counts.keys())[-7:]
        return jsonify({"success": True, "data": {"labels": labels, "values": [daily_counts[day] for day in labels]}})
    return jsonify({"success": True, "data": {"labels": [], "values": []}})


@ai_bp.route("/evolution-report")
@login_required
@permission_required(SystemPermissions.MANAGE_AI)
def evolution_report():
    try:
        from AI.engine.evolution_manager import get_evolution_metrics
        report_data = get_evolution_metrics()
    except Exception:
        report_data = {"labels": [], "gii_scores": [], "error_rates": [], "skills": {}, "stats": {}, "improvements": []}
    return render_template("ai/evolution_report.html", report=report_data)


def _get_ai_stats():
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        from AI.engine.ai_self_evolution import get_evolution_engine
        from AI.engine.ai_learning_system import get_learning_system
        perf = get_performance_tracker().get_performance_report()
        evo = get_evolution_engine().get_evolution_report()
        learn = get_learning_system().get_learning_stats()
        return {"total_interactions": perf.get("total_queries", 0), "success_rate": perf.get("success_rate", 0), "avg_confidence": perf.get("avg_confidence", 0), "evolution_level": evo.get("evolution_level", 1), "learned_queries": learn.get("total_learned_queries", 0)}
    except Exception:
        return {"total_interactions": 0, "success_rate": 0, "avg_confidence": 0}


def _get_system_stats():
    try:
        return gather_system_context()
    except Exception:
        return {}


def _get_recent_queries(limit: int = 5) -> List[Dict[str, Any]]:
    interactions = read_json("ai_interactions.json", [])
    if not isinstance(interactions, list):
        return []
    return list(reversed(interactions[-limit:]))


def _get_predictions():
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        report = get_performance_tracker().get_performance_report()
        trend = report.get("recent_trend", "stable")
        success_rate = report.get("success_rate", 0) or 0
        predictions = []
        if trend == "improving":
            predictions.append({"type": "positive", "message": "الأداء في تحسن حسب سجل التفاعلات", "icon": "arrow-up"})
        elif trend == "declining":
            predictions.append({"type": "warning", "message": "الأداء في تراجع حسب سجل التفاعلات", "icon": "arrow-down"})
        if success_rate >= 90:
            predictions.append({"type": "success", "message": f"نسبة نجاح مسجلة: {success_rate}%", "icon": "check-circle"})
        return predictions
    except Exception:
        return []


def _check_api_keys():
    return len(list_configured_apis()) > 0


def _save_conversation(query: str, response: Any):
    try:
        normalized = _normalize_ai_response(response)
        append_json_list("conversations.json", {"user_id": current_user.id, "username": current_user.username, "query": query, "response": normalized.get("response", ""), "confidence": normalized.get("confidence", 0), "timestamp": datetime.now().isoformat()}, max_items=1000)
    except Exception as exc:
        current_app.logger.error(f"Error saving conversation: {exc}")


def _get_recent_conversations(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        conversations = read_json("conversations.json", [])
        if not isinstance(conversations, list):
            return []
        user_conversations = [c for c in conversations if c.get("user_id") == current_user.id]
        return user_conversations[-limit:]
    except Exception as exc:
        current_app.logger.error(f"Error loading conversations: {exc}")
        return []


def _get_ai_suggestions():
    suggestions = [{"type": "info", "title": "💡 تلميح", "action": "اسأل عن صفحة أو عميل أو منتج أو قيد، وسأستخدم البيانات المفهرسة والمتاحة فقط."}]
    try:
        live = get_live_ai_stats()
        training = live.get("training", {}) if isinstance(live, dict) else {}
        running = int(training.get("running", 0) or 0)
        failed = int(training.get("failed", 0) or 0)
        if running:
            suggestions.append({"type": "info", "title": "تدريب جارٍ", "action": f"يوجد {running} مهمة تدريب قيد التشغيل."})
        if failed:
            suggestions.append({"type": "warning", "title": "مراجعة مطلوبة", "action": f"يوجد {failed} مهمة تدريب فاشلة في السجل."})
    except Exception:
        current_app.logger.debug('numeric conversion failed in ai_routes.py', exc_info=True)
    return suggestions


def _analyze_query(query):
    try:
        response = _chat_for_current_user(query)
        return {"query": query, "response": response.get("response", ""), "confidence": response.get("confidence", 0), "sources": response.get("sources", []), "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as exc:
        return {"query": query, "response": f"عذراً، حدث خطأ: {exc}", "confidence": 0, "sources": [], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


@ai_bp.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "المسار غير موجود"}), 404


@ai_bp.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "خطأ في الخادم"}), 500
