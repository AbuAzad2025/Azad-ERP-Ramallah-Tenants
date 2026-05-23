"""AI Self-Evolution Engine.

Tracks interaction quality, learns from failure categories, and suggests
improvements. This module deliberately stores its own evolution state separately
from performance_metrics.json to avoid schema conflicts with ai_performance_tracker.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

EVOLUTION_STATE_FILE = "evolution_state.json"
ERROR_LEARNING_LOG = "error_learning.json"
KNOWLEDGE_GAPS = "knowledge_gaps.json"
EVOLUTION_ARTIFACTS = [EVOLUTION_STATE_FILE, ERROR_LEARNING_LOG, KNOWLEDGE_GAPS]


def _normalize_confidence(value) -> float:
    try:
        num = float(value or 0)
    except Exception:
        return 0.0
    if num > 1:
        num = num / 100.0
    return max(0.0, min(1.0, num))


class SelfEvolutionEngine:
    """Self-evolution metrics and failure learning."""

    def __init__(self):
        self.performance_history: List[Dict[str, Any]] = []
        self.error_patterns: Dict[str, Dict[str, Any]] = {}
        self.knowledge_gaps: List[Dict[str, Any]] = []
        self.evolution_metrics = {
            "total_interactions": 0,
            "successful_responses": 0,
            "failed_responses": 0,
            "average_confidence": 0.0,
            "learning_rate": 0.0,
            "evolution_level": 1,
        }
        self.load_state()

    def load_state(self):
        try:
            data = read_json(EVOLUTION_STATE_FILE, {})
            if isinstance(data, dict):
                metrics = data.get("metrics")
                history = data.get("history")
                if isinstance(metrics, dict):
                    self.evolution_metrics.update(metrics)
                if isinstance(history, list):
                    self.performance_history = history[-1000:]

            error_data = read_json(ERROR_LEARNING_LOG, {})
            if isinstance(error_data, dict) and isinstance(error_data.get("error_patterns"), dict):
                self.error_patterns = error_data.get("error_patterns", {})

            gap_data = read_json(KNOWLEDGE_GAPS, {})
            if isinstance(gap_data, dict) and isinstance(gap_data.get("gaps"), list):
                self.knowledge_gaps = gap_data.get("gaps", [])[-100:]
        except Exception:
            pass

    def save_state(self):
        try:
            write_json(
                EVOLUTION_STATE_FILE,
                {
                    "metrics": self.evolution_metrics,
                    "history": self.performance_history[-1000:],
                    "last_updated": datetime.now().isoformat(),
                },
            )
            sync_training_manifest(extra_files=EVOLUTION_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error saving evolution state: {exc}")

    def record_interaction(self, query: str, response: Dict, success: bool, confidence: float, execution_time: float):
        confidence = _normalize_confidence(confidence)
        self.evolution_metrics["total_interactions"] += 1

        if success:
            self.evolution_metrics["successful_responses"] += 1
        else:
            self.evolution_metrics["failed_responses"] += 1

        total = self.evolution_metrics["total_interactions"]
        old_avg = self.evolution_metrics["average_confidence"]
        self.evolution_metrics["average_confidence"] = round(((old_avg * (total - 1)) + confidence) / total, 4)

        if len(self.performance_history) >= 100:
            recent_success_rate = sum(1 for p in self.performance_history[-100:] if p.get("success")) / 100
            old_success_rate = sum(1 for p in self.performance_history[-200:-100] if p.get("success")) / 100 if len(self.performance_history) >= 200 else 0.5
            self.evolution_metrics["learning_rate"] = round((recent_success_rate - old_success_rate) * 100, 2)

        success_rate = self.evolution_metrics["successful_responses"] / max(1, self.evolution_metrics["total_interactions"])
        if success_rate >= 0.95 and self.evolution_metrics["average_confidence"] >= 0.85:
            self.evolution_metrics["evolution_level"] = 5
        elif success_rate >= 0.90 and self.evolution_metrics["average_confidence"] >= 0.75:
            self.evolution_metrics["evolution_level"] = 4
        elif success_rate >= 0.80 and self.evolution_metrics["average_confidence"] >= 0.65:
            self.evolution_metrics["evolution_level"] = 3
        elif success_rate >= 0.70:
            self.evolution_metrics["evolution_level"] = 2
        else:
            self.evolution_metrics["evolution_level"] = 1

        self.performance_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "query": str(query or "")[:200],
                "success": bool(success),
                "confidence": confidence,
                "execution_time": float(execution_time or 0),
                "response_length": len(str(response)),
            }
        )
        self.performance_history = self.performance_history[-1000:]
        self.save_state()

        if not success:
            self.analyze_failure(query, response)

    def analyze_failure(self, query: str, response: Dict):
        try:
            error_type = self._categorize_error(query, response)
            pattern = self.error_patterns.setdefault(error_type, {"count": 0, "examples": [], "learned": False})
            pattern["count"] += 1
            pattern["examples"].append({"query": str(query or "")[:200], "timestamp": datetime.now().isoformat()})
            pattern["examples"] = pattern["examples"][-10:]
            self._save_error_learning()

            knowledge_gap = self._detect_knowledge_gap(query, error_type)
            if knowledge_gap:
                self.knowledge_gaps.append(knowledge_gap)
                self.knowledge_gaps = self.knowledge_gaps[-100:]
                self._save_knowledge_gaps()
        except Exception as exc:
            print(f"[ERROR] Error analyzing failure: {exc}")

    def _categorize_error(self, query: str, response: Dict) -> str:
        query_lower = str(query or "").lower()
        if any(word in query_lower for word in ["رصيد", "حساب", "مبلغ", "balance"]):
            return "accounting_error"
        if any(word in query_lower for word in ["زبون", "مورد", "شريك", "customer", "supplier"]):
            return "entity_error"
        if any(word in query_lower for word in ["مخزون", "منتج", "قطعة", "stock", "product"]):
            return "inventory_error"
        if any(word in query_lower for word in ["قيد", "محاسبي", "دفتر", "gl", "ledger"]):
            return "gl_error"
        if any(word in query_lower for word in ["ضريبة", "vat", "tax"]):
            return "tax_error"
        return "unknown_error"

    def _detect_knowledge_gap(self, query: str, error_type: str) -> Optional[Dict]:
        gap = {
            "timestamp": datetime.now().isoformat(),
            "query": str(query or "")[:200],
            "error_type": error_type,
            "gap_description": "",
            "priority": "medium",
        }
        if error_type == "accounting_error":
            gap["gap_description"] = "نقص في المعرفة المحاسبية لهذا النوع من العمليات"
            gap["priority"] = "high"
        elif error_type == "tax_error":
            gap["gap_description"] = "نقص في المعرفة الضريبية"
            gap["priority"] = "high"
        elif error_type == "gl_error":
            gap["gap_description"] = "نقص في فهم القيود المحاسبية"
            gap["priority"] = "critical"
        else:
            gap["gap_description"] = "فجوة معرفية غير محددة"
            gap["priority"] = "low"
        return gap

    def _save_error_learning(self):
        try:
            write_json(
                ERROR_LEARNING_LOG,
                {
                    "error_patterns": self.error_patterns,
                    "total_errors": sum(int(p.get("count", 0) or 0) for p in self.error_patterns.values()),
                    "last_updated": datetime.now().isoformat(),
                },
            )
            sync_training_manifest(extra_files=EVOLUTION_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error saving error learning: {exc}")

    def _save_knowledge_gaps(self):
        try:
            write_json(KNOWLEDGE_GAPS, {"gaps": self.knowledge_gaps[-100:], "last_updated": datetime.now().isoformat()})
            sync_training_manifest(extra_files=EVOLUTION_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error saving knowledge gaps: {exc}")

    def get_evolution_report(self) -> Dict[str, Any]:
        success_rate = 0
        if self.evolution_metrics["total_interactions"] > 0:
            success_rate = (self.evolution_metrics["successful_responses"] / self.evolution_metrics["total_interactions"]) * 100

        level_names = {1: "🟡 مبتدئ", 2: "🟠 متوسط", 3: "🔵 متقدم", 4: "🟣 خبير", 5: "🏆 ممتاز"}
        return {
            "evolution_level": self.evolution_metrics["evolution_level"],
            "evolution_level_name": level_names.get(self.evolution_metrics["evolution_level"], "غير محدد"),
            "total_interactions": self.evolution_metrics["total_interactions"],
            "success_rate": round(success_rate, 2),
            "average_confidence": round(self.evolution_metrics["average_confidence"] * 100, 2),
            "learning_rate": self.evolution_metrics["learning_rate"],
            "total_errors": sum(int(p.get("count", 0) or 0) for p in self.error_patterns.values()),
            "error_types": len(self.error_patterns),
            "knowledge_gaps": len(self.knowledge_gaps),
            "recent_performance": self._get_recent_performance(),
        }

    def _get_recent_performance(self) -> Dict:
        if not self.performance_history:
            return {"interactions": 0, "success_rate": 0, "avg_confidence": 0, "avg_response_time": 0}
        cutoff = datetime.now() - timedelta(hours=24)
        recent = []
        for item in self.performance_history:
            try:
                if datetime.fromisoformat(str(item.get("timestamp"))) >= cutoff:
                    recent.append(item)
            except Exception:
                continue
        if not recent:
            return {"interactions": 0, "success_rate": 0, "avg_confidence": 0, "avg_response_time": 0}
        success_count = sum(1 for p in recent if p.get("success"))
        avg_confidence = sum(float(p.get("confidence", 0) or 0) for p in recent) / len(recent)
        avg_time = sum(float(p.get("execution_time", 0) or 0) for p in recent) / len(recent)
        return {
            "interactions": len(recent),
            "success_rate": round((success_count / len(recent)) * 100, 2),
            "avg_confidence": round(avg_confidence * 100, 2),
            "avg_response_time": round(avg_time, 3),
        }

    def suggest_improvements(self) -> List[str]:
        suggestions = []
        if self.error_patterns:
            most_common = sorted(self.error_patterns.items(), key=lambda x: int(x[1].get("count", 0) or 0), reverse=True)[:3]
            for error_type, data in most_common:
                if int(data.get("count", 0) or 0) >= 5 and not data.get("learned"):
                    suggestions.append(f"تحسين المعرفة في: {error_type} ({data['count']} أخطاء)")
        critical_gaps = [g for g in self.knowledge_gaps if g.get("priority") == "critical"]
        if len(critical_gaps) >= 3:
            suggestions.append(f"هناك {len(critical_gaps)} فجوة معرفية حرجة تحتاج معالجة")
        if self.evolution_metrics["average_confidence"] < 0.7:
            suggestions.append("مستوى الثقة منخفض - يحتاج تدريب إضافي")
        if self.evolution_metrics["learning_rate"] < 0:
            suggestions.append("معدل التعلم سلبي - يحتاج مراجعة الاستراتيجية")
        return suggestions


_evolution_engine = None


def get_evolution_engine() -> SelfEvolutionEngine:
    global _evolution_engine
    if _evolution_engine is None:
        _evolution_engine = SelfEvolutionEngine()
    return _evolution_engine


__all__ = ["SelfEvolutionEngine", "get_evolution_engine"]
