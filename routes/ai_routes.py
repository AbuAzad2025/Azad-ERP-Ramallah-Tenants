from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

API_PROVIDER_CARDS = (
    {"slug": "groq", "name": "Groq", "icon": "fa-bolt", "color": "primary", "model": "llama-3.3-70b-versatile"},
    {"slug": "openai", "name": "OpenAI", "icon": "fa-brain", "color": "success", "model": "gpt-4o-mini"},
    {"slug": "anthropic", "name": "Anthropic", "icon": "fa-robot", "color": "info", "model": "claude-3-5-sonnet"},
)

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import utils
from utils import permission_required
from permissions_config.enums import SystemPermissions
from permissions_config.role_policy import is_platform_owner_role

from AI.engine.ai_service import ai_chat_with_search, gather_system_context
from AI.engine.ai_management import (
    format_timestamp,
    get_available_models,
    get_live_ai_stats,
    get_model_status,
    get_training_job_status,
    list_configured_apis,
    list_training_jobs,
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
            utils.flash_error("يجب تسجيل الدخول أولاً.")
            return redirect(url_for("auth.login"))

        from AI.engine.ai_permissions import is_ai_enabled

        if not is_ai_enabled() and not _has_permission(SystemPermissions.ACCESS_OWNER_DASHBOARD):
            utils.flash_warning("المساعد الذكي معطّل حالياً.")
            return redirect(url_for("main.dashboard"))

        is_owner_like = bool(
            getattr(current_user, "is_system", False)
            or getattr(current_user, "is_system_account", False)
            or is_platform_owner_role(current_user)
            or _has_permission(SystemPermissions.ACCESS_OWNER_DASHBOARD)
        )
        if not is_owner_like:
            utils.flash_error(utils.MSG_NOT_ALLOWED)
            return redirect(url_for("main.dashboard"))

        if _has_permission(SystemPermissions.ACCESS_AI_ASSISTANT):
            return f(*args, **kwargs)

        utils.flash_error(utils.MSG_NOT_ALLOWED)
        return redirect(url_for("main.dashboard"))

    return decorated_function


def _ai_hub_page_context(tab: str) -> Dict[str, Any]:
    model_statuses = get_model_status()
    models_status = model_statuses.get("models", {}) if isinstance(model_statuses, dict) else {}
    training_jobs = _get_training_jobs_newest_first(limit=20)
    live_stats = get_live_ai_stats()
    training_stats = live_stats.get("training", {}) if isinstance(live_stats, dict) else {}
    if not isinstance(training_stats, dict):
        training_stats = {}
    ai_stats = _get_ai_stats()
    analytics = _get_analytics_bundle()
    return {
        "active_tab": tab,
        "ai_stats": ai_stats,
        "system_stats": _get_system_stats(),
        "system_map_summary": _get_system_map_summary(),
        "recent_queries": _get_recent_queries(limit=8),
        "ai_suggestions": _get_ai_suggestions(),
        "hub_predictions": _get_hub_predictions(),
        "analytics_charts": analytics.get("charts", {}),
        "analytics_metrics": analytics.get("metrics", []),
        "api_providers": _get_api_provider_cards(),
        "api_keys_configured": _check_api_keys(),
        "model_statuses": models_status,
        "training_models": _enrich_training_models(),
        "training_jobs": training_jobs,
        "training_stats": training_stats,
        "live_ai_stats": live_stats,
        "active_training_job": next(
            (job for job in training_jobs if job.get("status") == "running"),
            None,
        ),
        "can_train_ai": _has_permission(SystemPermissions.TRAIN_AI),
        "can_manage_ai": _has_permission(SystemPermissions.MANAGE_AI),
        "format_timestamp": format_timestamp,
    }


@ai_bp.route("/hub")
@ai_access
def hub():
    tab = request.args.get("tab", "assistant")
    return render_template("ai/ai_hub.html", **_ai_hub_page_context(tab))


@ai_bp.route("/assistant", methods=["GET", "POST"])
@ai_access
def assistant():
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if not query:
            utils.flash_warning("الرجاء إدخال سؤال")
            return redirect(url_for("ai.assistant"))
        try:
            response = _chat_for_current_user(query)
            _save_conversation(query, response)
            return render_template("ai/ai_assistant.html", **_assistant_page_context())
        except Exception as exc:
            utils.flash_error(utils.user_friendly_error(exc))
            return redirect(url_for("ai.assistant"))
    return render_template("ai/ai_assistant.html", **_assistant_page_context())


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
                utils.flash_success("تم إعادة بناء خريطة النظام بنجاح!")
            except Exception as exc:
                utils.flash_error(utils.user_friendly_error(exc))
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
@ai_access
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
@ai_access
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


def _get_training_jobs_newest_first(limit: int = 20) -> List[Dict[str, Any]]:
    jobs = list_training_jobs(limit=limit)
    if not isinstance(jobs, list):
        return []
    return list(reversed(jobs))


def _enrich_training_models() -> List[Dict[str, Any]]:
    models = get_available_models()
    jobs = _get_training_jobs_newest_first(limit=50)
    latest_by_model: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        name = (job.get("model_name") or "").strip()
        if name and name not in latest_by_model:
            latest_by_model[name] = job
    for model in models:
        latest = latest_by_model.get(model.get("name", ""))
        model["latest_job"] = latest
        if latest and latest.get("status") == "running":
            model["progress"] = int(latest.get("progress") or 0)
            model["current_step"] = latest.get("current_step") or ""
        elif model.get("status") in {"training", "running"}:
            model["progress"] = int(latest.get("progress") or 0) if latest else 0
    return models


@ai_bp.route("/predictions/refresh", methods=["POST"])
@ai_access
def refresh_predictions():
    try:
        return jsonify({"success": True, "predictions": _get_hub_predictions(force_refresh=True)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


def _normalize_query_row(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or item.get("query") or "").strip()
    answer = str(item.get("answer") or item.get("response") or "").strip()
    if not question and not answer:
        return None
    try:
        confidence = float(item.get("confidence") or 0)
        if confidence <= 1:
            confidence *= 100
    except Exception:
        confidence = 0.0
    return {
        "question": question,
        "answer": answer,
        "confidence": round(confidence, 1),
        "timestamp": str(item.get("timestamp") or ""),
        "username": str(item.get("username") or ""),
    }


def _get_recent_queries(limit: int = 8) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source in (read_json("ai_interactions.json", []), read_json("conversations.json", [])):
        if not isinstance(source, list):
            continue
        for item in source:
            row = _normalize_query_row(item)
            if row:
                rows.append(row)
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return rows[: max(1, int(limit or 8))]


def _get_ai_stats() -> Dict[str, Any]:
    live = get_live_ai_stats()
    interactions = live.get("interactions", {}) if isinstance(live, dict) else {}
    performance = live.get("performance", {}) if isinstance(live, dict) else {}
    stats: Dict[str, Any] = {
        "total_queries": 0,
        "success_rate": None,
        "avg_response_time": None,
        "avg_confidence": None,
        "today": 0,
        "evolution_level": 1,
        "learned_queries": 0,
        "recent_trend": "insufficient_data",
        "low_value_rate": None,
    }
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        from AI.engine.ai_self_evolution import get_evolution_engine
        from AI.engine.ai_learning_system import get_learning_system

        report = get_performance_tracker().get_performance_report()
        evo = get_evolution_engine().get_evolution_report()
        learn = get_learning_system().get_learning_stats()
        stats.update(
            {
                "total_queries": int(report.get("total_queries") or 0),
                "success_rate": report.get("success_rate"),
                "avg_response_time": report.get("avg_response_time"),
                "avg_confidence": report.get("avg_confidence"),
                "recent_trend": report.get("recent_trend", "insufficient_data"),
                "low_value_rate": report.get("low_value_rate"),
                "evolution_level": evo.get("evolution_level", 1),
                "learned_queries": learn.get("total_learned_queries", 0),
            }
        )
    except Exception:
        current_app.logger.debug("ai hub stats fallback", exc_info=True)
    if not stats["total_queries"] and isinstance(interactions, dict):
        stats["total_queries"] = int(interactions.get("total") or 0)
        stats["today"] = int(interactions.get("today") or 0)
        if stats["success_rate"] is None:
            stats["success_rate"] = interactions.get("success_rate")
        if stats["avg_confidence"] is None:
            stats["avg_confidence"] = interactions.get("avg_confidence")
    if stats["today"] == 0 and isinstance(interactions, dict):
        stats["today"] = int(interactions.get("today") or 0)
    if stats["avg_response_time"] is None and isinstance(performance, dict):
        stats["avg_response_time"] = performance.get("avg_response_time")
    return stats


def _get_analytics_bundle() -> Dict[str, Any]:
    charts = {
        "success_pie": {"labels": ["ناجح", "فاشل"], "values": [0, 0]},
        "query_types": {"labels": [], "values": []},
        "daily_line": {"labels": [], "values": []},
    }
    metrics: List[Dict[str, Any]] = []
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker

        tracker = get_performance_tracker()
        report = tracker.get_performance_report()
        success = int(tracker.metrics.get("successful_queries") or 0)
        failed = int(tracker.metrics.get("failed_queries") or 0)
        charts["success_pie"] = {"labels": ["ناجح", "فاشل"], "values": [success, failed]}
        top_types = report.get("top_query_types") or {}
        if top_types:
            charts["query_types"] = {
                "labels": list(top_types.keys()),
                "values": list(top_types.values()),
            }
        daily: Dict[str, int] = defaultdict(int)
        for entry in tracker.performance_log:
            day = str(entry.get("timestamp") or "")[:10]
            if day:
                daily[day] += 1
        labels = sorted(daily.keys())[-7:]
        charts["daily_line"] = {"labels": labels, "values": [daily[label] for label in labels]}

        def _trend_text(current: float, previous: float, suffix: str = "") -> str:
            if previous <= 0:
                return "—"
            delta = current - previous
            if delta > 0:
                return f"+{delta:.1f}{suffix}"
            if delta < 0:
                return f"{delta:.1f}{suffix}"
            return "0"

        recent7 = [e for e in tracker.performance_log if str(e.get("timestamp", ""))[:10] >= (datetime.now().date() - timedelta(days=7)).isoformat()]
        prev7 = [e for e in tracker.performance_log if (datetime.now().date() - timedelta(days=14)).isoformat() <= str(e.get("timestamp", ""))[:10] < (datetime.now().date() - timedelta(days=7)).isoformat()]
        recent_success = (sum(1 for e in recent7 if e.get("success")) / len(recent7) * 100) if recent7 else 0
        prev_success = (sum(1 for e in prev7 if e.get("success")) / len(prev7) * 100) if prev7 else 0

        total = int(report.get("total_queries") or 0)
        metrics = [
            {
                "label": "إجمالي الاستعلامات",
                "value": total,
                "change": _trend_text(len(recent7), len(prev7)),
                "status": "نشط" if total else "لا بيانات",
                "badge": "success" if total else "secondary",
            },
            {
                "label": "معدل النجاح",
                "value": f"{report.get('success_rate') if report.get('success_rate') is not None else '—'}{'%' if report.get('success_rate') is not None else ''}",
                "change": _trend_text(recent_success, prev_success, "%"),
                "status": "ممتاز" if (report.get("success_rate") or 0) >= 85 else "يحتاج تحسين",
                "badge": "success" if (report.get("success_rate") or 0) >= 85 else "warning",
            },
            {
                "label": "متوسط وقت الاستجابة",
                "value": f"{report.get('avg_response_time') if report.get('avg_response_time') is not None else '—'}{'s' if report.get('avg_response_time') is not None else ''}",
                "change": "—",
                "status": "جيد" if (report.get("avg_response_time") or 99) <= 2 else "بطيء",
                "badge": "info",
            },
            {
                "label": "متوسط الثقة",
                "value": f"{report.get('avg_confidence') if report.get('avg_confidence') is not None else '—'}{'%' if report.get('avg_confidence') is not None else ''}",
                "change": "—",
                "status": "مقبول" if (report.get("avg_confidence") or 0) >= 60 else "منخفض",
                "badge": "primary",
            },
        ]
    except Exception:
        current_app.logger.debug("analytics bundle failed", exc_info=True)
    return {"charts": charts, "metrics": metrics}


def _get_hub_predictions(force_refresh: bool = False) -> List[Dict[str, Any]]:
    predictions: List[Dict[str, Any]] = []
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker

        report = get_performance_tracker().get_performance_report()
        trend = report.get("recent_trend", "insufficient_data")
        if trend == "improving":
            predictions.append(
                {
                    "type": "أداء المساعد",
                    "period": "آخر 10 استعلامات",
                    "value": "تحسّن ملحوظ",
                    "confidence": report.get("success_rate"),
                    "source": "performance_tracker",
                }
            )
        elif trend == "declining":
            predictions.append(
                {
                    "type": "أداء المساعد",
                    "period": "آخر 10 استعلامات",
                    "value": "تراجع — راجع الأسئلة الفاشلة",
                    "confidence": report.get("success_rate"),
                    "source": "performance_tracker",
                }
            )
    except Exception:
        pass

    try:
        from extensions import db
        from models import Sale
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)
        d60 = now - timedelta(days=60)
        recent = (
            db.session.query(func.coalesce(func.sum(Sale.total_amount), 0))
            .filter(Sale.sale_date >= d30)
            .scalar()
        ) or 0
        previous = (
            db.session.query(func.coalesce(func.sum(Sale.total_amount), 0))
            .filter(Sale.sale_date >= d60, Sale.sale_date < d30)
            .scalar()
        ) or 0
        if float(recent) > 0 or float(previous) > 0:
            if float(previous) > 0:
                pct = ((float(recent) - float(previous)) / float(previous)) * 100
                value = f"{'+' if pct >= 0 else ''}{pct:.1f}%"
            else:
                value = f"₪{float(recent):,.0f}"
            predictions.append(
                {
                    "type": "مبيعات",
                    "period": "30 يوم vs 30 يوم سابق",
                    "value": value,
                    "confidence": None,
                    "source": "sales_db",
                }
            )
    except Exception:
        current_app.logger.debug("sales prediction failed", exc_info=True)

    try:
        from extensions import db
        from models import StockLevel
        from sqlalchemy import func

        low_stock = (
            db.session.query(func.count(StockLevel.id))
            .filter(StockLevel.min_stock.isnot(None), StockLevel.quantity <= StockLevel.min_stock)
            .scalar()
        ) or 0
        if int(low_stock) == 0:
            low_stock = (
                db.session.query(func.count(StockLevel.id))
                .filter(StockLevel.quantity <= 0)
                .scalar()
            ) or 0
        if int(low_stock) > 0:
            predictions.append(
                {
                    "type": "مخزون",
                    "period": "الآن",
                    "value": f"{int(low_stock)} منتج تحت الحد الأدنى",
                    "confidence": None,
                    "source": "stock_db",
                }
            )
    except Exception:
        current_app.logger.debug("stock prediction failed", exc_info=True)

    return predictions


def _get_api_provider_cards() -> List[Dict[str, Any]]:
    configured = {}
    for row in list_configured_apis():
        name = str(row.get("name") or "").strip().lower()
        if name:
            configured[name] = row
    cards = []
    for provider in API_PROVIDER_CARDS:
        slug = provider["slug"]
        cfg = configured.get(slug) or configured.get(f"{slug}_api")
        cards.append(
            {
                **provider,
                "configured": bool(cfg),
                "status": "active" if cfg else "inactive",
                "updated_at": (cfg or {}).get("created_at"),
            }
        )
    return cards


def _get_system_map_summary() -> Dict[str, Any]:
    try:
        from AI.engine.ai_auto_discovery import load_system_map

        data = load_system_map() or {}
        stats = data.get("statistics") if isinstance(data.get("statistics"), dict) else {}
        return {
            "exists": bool(data),
            "generated_at": data.get("generated_at") or "",
            "total_routes": int(stats.get("total_routes") or 0),
            "total_templates": int(stats.get("total_templates") or 0),
            "linked_routes": int(stats.get("linked_routes") or 0),
            "blueprints_count": len(data.get("blueprints") or []),
        }
    except Exception:
        return {
            "exists": False,
            "generated_at": "",
            "total_routes": 0,
            "total_templates": 0,
            "linked_routes": 0,
            "blueprints_count": 0,
        }


def _get_system_stats():
    try:
        return gather_system_context()
    except Exception:
        return {}


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


def _get_assistant_prompts() -> List[Dict[str, str]]:
    prompts: List[Dict[str, str]] = []
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker

        top_types = get_performance_tracker().get_performance_report().get("top_query_types") or {}
        for label in list(top_types.keys())[:3]:
            text = str(label).strip()
            if text:
                prompts.append({"label": text, "query": text, "icon": "fa-comment-dots", "category": "شائع"})
    except Exception:
        pass
    defaults = [
        {"label": "ملخص مبيعات اليوم", "query": "ملخص مبيعات اليوم", "icon": "fa-chart-line", "category": "مبيعات"},
        {"label": "منخفض المخزون", "query": "ما المنتجات منخفضة المخزون؟", "icon": "fa-boxes", "category": "مخزون"},
        {"label": "طلبات الصيانة", "query": "أين صفحة طلبات الصيانة؟", "icon": "fa-tools", "category": "تنقل"},
        {"label": "كشف حساب زبون", "query": "كيف أعرض كشف حساب زبون؟", "icon": "fa-file-invoice", "category": "حسابات"},
        {"label": "حساب VAT", "query": "احسب VAT لـ 1000", "icon": "fa-calculator", "category": "مالية"},
        {"label": "أفضل الزبائن", "query": "من أفضل الزبائن هذا الشهر؟", "icon": "fa-users", "category": "تحليل"},
    ]
    seen = {p["query"] for p in prompts}
    for item in defaults:
        if item["query"] not in seen:
            prompts.append(item)
            seen.add(item["query"])
        if len(prompts) >= 8:
            break
    return prompts


def _get_assistant_history(limit: int = 12) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in _get_recent_conversations(limit=limit):
        row = _normalize_query_row(
            {
                "question": item.get("query"),
                "answer": item.get("response"),
                "confidence": item.get("confidence"),
                "timestamp": item.get("timestamp"),
            }
        )
        if row:
            rows.append(row)
    return rows


def _assistant_page_context() -> Dict[str, Any]:
    from AI.engine.ai_service import get_company_profile

    ai_stats = _get_ai_stats()
    company = get_company_profile()
    return {
        "ai_stats": ai_stats,
        "company": company,
        "api_keys_configured": _check_api_keys(),
        "quick_prompts": _get_assistant_prompts(),
        "chat_history": _get_assistant_history(limit=20),
        "history_snippets": list(reversed(_get_assistant_history(limit=6))),
        "system_alerts": _get_ai_suggestions(),
        "format_timestamp": format_timestamp,
    }


def _get_ai_suggestions():
    suggestions = [{"type": "info", "title": "💡 تلميح", "action": "اسأل عن صفحة أو زبون أو منتج أو قيد، وسأستخدم البيانات المفهرسة والمتاحة فقط."}]
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
