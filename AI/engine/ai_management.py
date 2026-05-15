"""AI management utilities.

Training lifecycle, model status, health, and statistics helpers. This module
avoids fabricated model accuracy or fixed performance numbers.
"""

from __future__ import annotations

import copy
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from AI.engine.ai_storage import file_metadata, read_json, sync_training_manifest, utc_now, write_json

TRAINING_JOBS_FILE = "training_jobs.json"
MODEL_STATUS_FILE = "model_training_status.json"
INTERACTIONS_FILE = "ai_interactions.json"
API_PROVIDER_STATUS_FILE = "api_provider_status.json"

DEFAULT_MODELS = {
    "نموذج التنبؤ بالمبيعات": {"status": "pending", "accuracy": None, "last_update": None, "last_trained": None, "training_jobs": [], "metric_source": None},
    "نموذج إدارة المخزون": {"status": "pending", "accuracy": None, "last_update": None, "last_trained": None, "training_jobs": [], "metric_source": None},
    "نموذج تحليل العملاء": {"status": "pending", "accuracy": None, "last_update": None, "last_trained": None, "training_jobs": [], "metric_source": None},
}

AVAILABLE_MODELS = [
    {"id": "sales_predictor", "name": "نموذج التنبؤ بالمبيعات", "description": "تنبؤ بالمبيعات المستقبلية بناءً على البيانات التاريخية", "icon": "fa-chart-line", "status": "pending", "accuracy": None, "last_trained": None},
    {"id": "inventory_optimizer", "name": "نموذج إدارة المخزون", "description": "التنبؤ بالنقص في المخزون وتحسين الطلبات", "icon": "fa-boxes", "status": "pending", "accuracy": None, "last_trained": None},
    {"id": "customer_analyzer", "name": "نموذج تحليل العملاء", "description": "تحليل سلوك العملاء والتنبؤ بالاحتياجات", "icon": "fa-users", "status": "pending", "accuracy": None, "last_trained": None},
]


def save_api_key_encrypted(api_name: str, api_key: str) -> bool:
    """Keep public API stable; secret storage is intentionally not handled here."""
    provider = (api_name or "").strip().lower()
    if not provider or not (api_key or "").strip():
        return False
    data = read_json(API_PROVIDER_STATUS_FILE, {})
    data = data if isinstance(data, dict) else {}
    data[provider] = {"configured": True, "updated_at": utc_now(), "storage": "external_or_runtime"}
    write_json(API_PROVIDER_STATUS_FILE, data)
    sync_training_manifest(extra_files=[API_PROVIDER_STATUS_FILE])
    return True


def get_api_key_decrypted(api_name: str) -> Optional[str]:
    provider = (api_name or "").strip().upper()
    if not provider:
        return None
    return os.environ.get(f"{provider}_API_KEY")


def test_api_key(api_name: str) -> dict:
    provider = (api_name or "").strip().lower()
    configured = bool(get_api_key_decrypted(provider))
    if not configured:
        return {"success": False, "message": "المفتاح غير موجود في متغيرات البيئة"}
    return {"success": True, "message": "المفتاح موجود في متغيرات البيئة", "provider": provider}


def list_configured_apis() -> list:
    data = read_json(API_PROVIDER_STATUS_FILE, {})
    rows = []
    if isinstance(data, dict):
        for name, item in data.items():
            if isinstance(item, dict):
                rows.append({"name": name, "status": "configured" if item.get("configured") else "unknown", "created_at": item.get("updated_at", "unknown")})
    for key, value in os.environ.items():
        if key.endswith("_API_KEY") and value:
            provider = key[:-8].lower()
            if not any(row.get("name") == provider for row in rows):
                rows.append({"name": provider, "status": "configured", "created_at": "environment"})
    return rows


def _save_training_job(job: Dict[str, Any]) -> None:
    jobs = read_json(TRAINING_JOBS_FILE, [])
    jobs = jobs if isinstance(jobs, list) else []
    for idx, existing in enumerate(jobs):
        if existing.get("job_id") == job.get("job_id"):
            jobs[idx] = job
            break
    else:
        jobs.append(job)
    write_json(TRAINING_JOBS_FILE, jobs[-200:])
    sync_training_manifest()


def start_training_job(model_name: str, training_type: str = "quick", data_range: str = "all") -> dict:
    model_name = (model_name or "unknown").strip()
    training_type = (training_type or "quick").strip().lower()
    data_range = (data_range or "all").strip()
    job = {"job_id": f"train_{datetime.now(timezone.utc).timestamp()}", "model_name": model_name, "training_type": training_type, "data_range": data_range, "status": "running", "progress": 0, "started_at": utc_now(), "estimated_completion": None, "error": None, "current_step": "تم إنشاء مهمة التدريب"}
    try:
        _save_training_job(job)
        _update_model_status(model_name, "training", job_id=job["job_id"])
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    def train_in_background() -> None:
        try:
            job.update({"progress": 5, "current_step": "تهيئة تطبيق Flask..."})
            _save_training_job(job)
            from app import create_app
            app_instance = create_app()
            with app_instance.app_context():
                from AI.engine.ai_training_engine import AITrainingEngine
                deep_result = None
                if training_type in {"deep", "custom"}:
                    job.update({"progress": 15, "current_step": "تشغيل التدريب العميق..."})
                    _save_training_job(job)
                    from AI.engine.ai_system_deep_trainer import get_system_deep_trainer
                    deep_result = get_system_deep_trainer().train_system_comprehensive()
                job.update({"progress": 55, "current_step": "تشغيل محرك التدريب..."})
                _save_training_job(job)
                training_result = AITrainingEngine().run_full_training(force=training_type in {"deep", "custom"})
                job.update({"progress": 100, "status": "completed", "completed_at": utc_now(), "current_step": "اكتمل التدريب بنجاح", "result": {"deep_training": deep_result, "detailed_training": training_result}})
                _update_model_status(model_name, "completed", deep_result, training_result, job["job_id"])
                _save_training_job(job)
        except Exception as exc:
            import traceback
            job.update({"status": "failed", "error": str(exc), "traceback": traceback.format_exc(), "completed_at": utc_now(), "current_step": "فشل التدريب"})
            _update_model_status(model_name, "failed", job_id=job["job_id"])
            _save_training_job(job)

    threading.Thread(target=train_in_background, daemon=True).start()
    return {"success": True, "job_id": job["job_id"], "message": f"تم بدء تدريب {model_name}"}


def get_training_job_status(job_id: str) -> Optional[dict]:
    jobs = read_json(TRAINING_JOBS_FILE, [])
    if not isinstance(jobs, list):
        return None
    for job in jobs:
        if job.get("job_id") == job_id:
            return job
    return None


def list_training_jobs(limit: int = 10) -> list:
    jobs = read_json(TRAINING_JOBS_FILE, [])
    return (jobs if isinstance(jobs, list) else [])[-max(1, int(limit or 10)):]


def get_live_ai_stats() -> dict:
    try:
        ping = _get_ping_stats()
        return {"timestamp": utc_now(), "status": ping.get("status", "active"), "latency": ping.get("latency", 0), "queries_today": ping.get("queries_today", 0), "interactions": _get_interactions_stats(), "training": _get_training_stats(), "system": _get_system_health(), "performance": _get_performance_stats(), "manifest": sync_training_manifest().get("summary", {})}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "timestamp": utc_now()}


def _get_ping_stats() -> dict:
    start_time = datetime.now(timezone.utc)
    queries_today = 0
    try:
        from AI.engine.evolution_manager import _load_history
        hist = _load_history()
        queries_today = int(hist.get("stats", {}).get("total_queries", 0) or 0)
    except Exception:
        pass
    return {"status": "active", "latency": round((datetime.now(timezone.utc) - start_time).total_seconds(), 3), "queries_today": queries_today}


def _get_interactions_stats() -> dict:
    interactions = read_json(INTERACTIONS_FILE, [])
    if not isinstance(interactions, list) or not interactions:
        return {"total": 0, "today": 0, "success_rate": None, "avg_confidence": None}
    today = datetime.now(timezone.utc).date().isoformat()
    values = []
    for item in interactions:
        try:
            c = float(item.get("confidence", 0) or 0)
            values.append(c * 100 if c <= 1 else c)
        except Exception:
            continue
    successful = sum(1 for value in values if value >= 70)
    return {"total": len(interactions), "today": sum(1 for i in interactions if str(i.get("timestamp", "")).startswith(today)), "success_rate": round((successful / len(values)) * 100, 1) if values else None, "avg_confidence": round(sum(values) / len(values), 1) if values else None}


def _get_training_stats() -> dict:
    jobs = read_json(TRAINING_JOBS_FILE, [])
    jobs = jobs if isinstance(jobs, list) else []
    return {"total_jobs": len(jobs), "completed": sum(1 for j in jobs if j.get("status") == "completed"), "running": sum(1 for j in jobs if j.get("status") == "running"), "failed": sum(1 for j in jobs if j.get("status") == "failed")}


def _get_system_health() -> dict:
    essential_files = ["ai_knowledge_cache.json", "ai_data_schema.json", "ai_system_map.json"]
    metadata = [file_metadata(filename) for filename in essential_files]
    files_ok = sum(1 for item in metadata if item.get("exists"))
    score = round((files_ok / len(essential_files)) * 100, 1)
    status = "healthy" if score > 66 else "warning" if score > 33 else "critical"
    return {"status": status, "score": score, "files_ok": files_ok, "files_total": len(essential_files), "files": metadata}


def _get_performance_stats() -> dict:
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        report = get_performance_tracker().get_performance_report()
        return {"avg_response_time": report.get("avg_response_time"), "success_rate": report.get("success_rate"), "avg_confidence": report.get("avg_confidence"), "recent_trend": report.get("recent_trend"), "source": "ai_performance_tracker"}
    except Exception as exc:
        return {"avg_response_time": None, "success_rate": None, "avg_confidence": None, "recent_trend": "unknown", "error": str(exc)}


def get_available_models() -> list:
    status = get_model_status().get("models", {})
    output = []
    for model in AVAILABLE_MODELS:
        item = dict(model)
        stored = status.get(item["name"], {})
        item.update({"status": stored.get("status", item.get("status")), "accuracy": stored.get("accuracy", item.get("accuracy")), "last_trained": stored.get("last_trained", item.get("last_trained")), "metric_source": stored.get("metric_source")})
        output.append(item)
    return output


def get_model_info(model_id: str) -> Optional[dict]:
    for model in get_available_models():
        if model.get("id") == model_id:
            return model
    return None


def _default_model_status() -> dict:
    return {"models": copy.deepcopy(DEFAULT_MODELS)}


def get_model_status(model_name: str = None) -> dict:
    model_status = read_json(MODEL_STATUS_FILE, _default_model_status())
    if not isinstance(model_status, dict) or "models" not in model_status:
        model_status = _default_model_status()
    if model_name:
        return model_status.get("models", {}).get(model_name, {"status": "pending", "accuracy": None, "last_update": None, "last_trained": None, "metric_source": None})
    return model_status


def _extract_metric_accuracy(*results) -> Optional[float]:
    for result in results:
        if not isinstance(result, dict):
            continue
        for key in ("accuracy", "validation_accuracy", "score", "success_rate"):
            if result.get(key) is None:
                continue
            try:
                value = float(result.get(key))
                value = value * 100 if value <= 1 else value
                return round(max(0, min(100, value)), 2)
            except Exception:
                continue
    return None


def _update_model_status(model_name: str, status: str, deep_result: dict = None, training_result: dict = None, job_id: str = None) -> None:
    model_status = get_model_status()
    models = model_status.setdefault("models", {})
    info = models.setdefault(model_name, {"status": "pending", "accuracy": None, "last_update": None, "last_trained": None, "training_jobs": [], "metric_source": None})
    info["status"] = "trained" if status == "completed" else status
    info["last_update"] = utc_now()
    if status == "completed":
        info["last_trained"] = utc_now()
        metric = _extract_metric_accuracy(training_result, deep_result)
        info["accuracy"] = metric
        info["metric_source"] = "training_result" if metric is not None else None
    if job_id:
        jobs = info.setdefault("training_jobs", [])
        if job_id not in jobs:
            jobs.append(job_id)
    write_json(MODEL_STATUS_FILE, model_status)
    sync_training_manifest()


def format_timestamp(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso_timestamp).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_timestamp


def calculate_eta(progress: float, started_at: str) -> str:
    try:
        progress = float(progress or 0)
        if progress <= 0:
            return "غير معروف"
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        remaining = max(0, elapsed / (progress / 100) - elapsed)
        if remaining < 60:
            return f"{int(remaining)} ثانية"
        if remaining < 3600:
            return f"{int(remaining / 60)} دقيقة"
        return f"{int(remaining / 3600)} ساعة"
    except Exception:
        return "غير معروف"


__all__ = ["save_api_key_encrypted", "get_api_key_decrypted", "test_api_key", "list_configured_apis", "start_training_job", "get_training_job_status", "list_training_jobs", "get_live_ai_stats", "get_available_models", "get_model_info", "get_model_status", "format_timestamp", "calculate_eta"]
