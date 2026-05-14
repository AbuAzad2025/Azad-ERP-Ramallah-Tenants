"""Evolution report data manager."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from AI.engine.ai_storage import read_json, sync_training_manifest, utc_now, write_json

EVOLUTION_DATA_FILE = "evolution_history.json"


def _initial_history() -> Dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "start_date": today,
        "history": [
            {
                "date": today,
                "gii_score": 0.0,
                "error_rate": 0.0,
                "skills": {"data_analysis": 0, "nlp": 0, "pattern_recognition": 0, "recommendations": 0},
            }
        ],
        "stats": {"total_queries": 0, "training_cycles": 0, "uptime_seconds": None, "last_inference_time": 0.0},
        "improvements": [],
        "created_at": utc_now(),
    }


def _load_history():
    data = read_json(EVOLUTION_DATA_FILE, None)
    if isinstance(data, dict) and data.get("history"):
        return data
    initial_data = _initial_history()
    _save_history(initial_data)
    return initial_data


def _save_history(data):
    write_json(EVOLUTION_DATA_FILE, data)
    sync_training_manifest(extra_files=[EVOLUTION_DATA_FILE])


def get_evolution_metrics():
    data = _load_history()
    history = data.get("history", [])
    recent_history = history[-6:]

    labels = [h.get("date", "") for h in recent_history]
    gii_scores = [h.get("gii_score", 0) for h in recent_history]
    error_rates = [h.get("error_rate", 0) for h in recent_history]
    current_skills = history[-1].get("skills", {}) if history else {}
    stats = data.get("stats", {})
    uptime_seconds = stats.get("uptime_seconds")

    return {
        "labels": labels,
        "gii_scores": gii_scores,
        "error_rates": error_rates,
        "skills": current_skills,
        "stats": {
            "data_points": f"{int(stats.get('total_queries', 0) or 0):,}",
            "training_cycles": int(stats.get("training_cycles", 0) or 0),
            "uptime": _format_uptime(uptime_seconds),
            "inference_speed": f"{float(stats.get('last_inference_time', 0) or 0):.3f}s",
        },
        "improvements": data.get("improvements", [])[-5:],
    }


def _format_uptime(uptime_seconds) -> str:
    if uptime_seconds is None:
        return "غير متوفر"
    try:
        seconds = int(uptime_seconds)
    except Exception:
        return "غير متوفر"
    days, rem = divmod(seconds, 86400)
    hours, _ = divmod(rem, 3600)
    if days:
        return f"{days} يوم و {hours} ساعة"
    return f"{hours} ساعة"


def record_learning_event(gii_delta=0, error_delta=0, new_skill: Optional[Tuple[str, float]] = None):
    data = _load_history()
    history = data.setdefault("history", [])
    if not history:
        history.append(_initial_history()["history"][0])
    last_entry = history[-1]

    new_entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "gii_score": min(100, max(0, float(last_entry.get("gii_score", 0)) + float(gii_delta or 0))),
        "error_rate": min(100, max(0, float(last_entry.get("error_rate", 0)) + float(error_delta or 0))),
        "skills": dict(last_entry.get("skills", {})),
    }

    if new_skill:
        skill_name, skill_val = new_skill
        new_entry["skills"][skill_name] = min(100, max(0, float(new_entry["skills"].get(skill_name, 0)) + float(skill_val or 0)))
        data.setdefault("improvements", []).append(
            {
                "title": f"تحسين في {skill_name}",
                "desc": f"تغير بمقدار {skill_val}%",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "icon": "fas fa-arrow-up" if float(skill_val or 0) >= 0 else "fas fa-arrow-down",
                "color": "success" if float(skill_val or 0) >= 0 else "warning",
            }
        )
        data["improvements"] = data["improvements"][-50:]

    if last_entry.get("date") == new_entry["date"]:
        history[-1] = new_entry
    else:
        history.append(new_entry)
    data["history"] = history[-365:]
    _save_history(data)


def update_stats(query_count=1, inference_time=0.0):
    data = _load_history()
    stats = data.setdefault("stats", {})
    stats["total_queries"] = int(stats.get("total_queries", 0) or 0) + int(query_count or 0)
    stats["last_inference_time"] = float(inference_time or 0)
    _save_history(data)


__all__ = ["get_evolution_metrics", "record_learning_event", "update_stats", "_load_history"]
