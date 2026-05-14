"""AI Performance Tracker."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

PERFORMANCE_METRICS_FILE = "performance_metrics.json"


def _to_regular_dict(value):
    if isinstance(value, defaultdict):
        return dict(value)
    if isinstance(value, dict):
        return {k: _to_regular_dict(v) for k, v in value.items()}
    return value


def _normalize_confidence(value: Any) -> float:
    try:
        num = float(value or 0)
    except Exception:
        return 0.0
    if num > 1:
        num = num / 100.0
    return max(0.0, min(1.0, num))


class PerformanceTracker:
    def __init__(self):
        self.metrics = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "avg_confidence": 0.0,
            "avg_response_time": 0.0,
            "queries_by_type": defaultdict(int),
            "errors_by_type": defaultdict(int),
            "expert_usage": defaultdict(int),
        }
        self.performance_log = []
        self._load_metrics()

    def _load_metrics(self):
        data = read_json(PERFORMANCE_METRICS_FILE, {})
        if not isinstance(data, dict):
            return
        saved = data.get("metrics", {})
        if isinstance(saved, dict):
            self.metrics.update(saved)
            self.metrics["queries_by_type"] = defaultdict(int, saved.get("queries_by_type", {}))
            self.metrics["errors_by_type"] = defaultdict(int, saved.get("errors_by_type", {}))
            self.metrics["expert_usage"] = defaultdict(int, saved.get("expert_usage", {}))
        log = data.get("log", [])
        self.performance_log = log[-1000:] if isinstance(log, list) else []

    def record_query(self, query: str, response: Dict, execution_time: float):
        response = response if isinstance(response, dict) else {}
        self.metrics["total_queries"] += 1

        if response.get("answer") or response.get("response"):
            self.metrics["successful_queries"] += 1
        else:
            self.metrics["failed_queries"] += 1

        confidence = _normalize_confidence(response.get("confidence", 0.0))
        total = self.metrics["total_queries"]
        self.metrics["avg_confidence"] = ((self.metrics["avg_confidence"] * (total - 1)) + confidence) / total
        self.metrics["avg_response_time"] = ((self.metrics["avg_response_time"] * (total - 1)) + float(execution_time or 0)) / total

        query_type = self._classify_query(query)
        self.metrics["queries_by_type"][query_type] += 1

        for source in response.get("sources", []) or []:
            self.metrics["expert_usage"][str(source)] += 1

        self.performance_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "query_type": query_type,
                "confidence": confidence,
                "execution_time": float(execution_time or 0),
                "success": bool(response.get("answer") or response.get("response")),
            }
        )
        self.performance_log = self.performance_log[-1000:]
        self._save_metrics()

    def _classify_query(self, query: str) -> str:
        q = str(query or "").lower()
        if any(w in q for w in ["error", "خطأ", "bug"]):
            return "debug"
        if any(w in q for w in ["كيف", "how", "steps"]):
            return "tutorial"
        if any(w in q for w in ["رصيد", "balance"]):
            return "balance_query"
        if any(w in q for w in ["أضف", "اضف", "add", "create"]):
            return "action"
        return "general"

    def _save_metrics(self):
        try:
            write_json(
                PERFORMANCE_METRICS_FILE,
                {
                    "metrics": _to_regular_dict(self.metrics),
                    "log": self.performance_log[-1000:],
                    "last_updated": datetime.now().isoformat(),
                },
            )
            sync_training_manifest(extra_files=[PERFORMANCE_METRICS_FILE])
        except Exception:
            pass

    def get_performance_report(self) -> Dict:
        success_rate = 0.0
        total = self.metrics["total_queries"]
        if total > 0:
            success_rate = (self.metrics["successful_queries"] / total) * 100
        return {
            "total_queries": total,
            "success_rate": round(success_rate, 2),
            "avg_confidence": round(self.metrics["avg_confidence"] * 100, 2),
            "avg_response_time": round(self.metrics["avg_response_time"], 3),
            "top_query_types": dict(sorted(self.metrics["queries_by_type"].items(), key=lambda x: x[1], reverse=True)[:5]),
            "expert_usage": dict(self.metrics["expert_usage"]),
            "recent_trend": self._calculate_trend(),
        }

    def _calculate_trend(self) -> str:
        if len(self.performance_log) < 20:
            return "insufficient_data"
        recent_success = sum(1 for p in self.performance_log[-10:] if p.get("success")) / 10
        older_success = sum(1 for p in self.performance_log[-20:-10] if p.get("success")) / 10
        if recent_success > older_success + 0.1:
            return "improving"
        if recent_success < older_success - 0.1:
            return "declining"
        return "stable"


_performance_tracker = None


def get_performance_tracker():
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker


__all__ = ["PerformanceTracker", "get_performance_tracker"]
