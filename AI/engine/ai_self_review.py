"""AI self-review utilities.

Keeps a compact interaction log, analyzes recent response quality, and writes a
self-audit report. Confidence values are normalized to 0..100 so mixed callers
that send 0.65 or 65 are evaluated consistently.
"""

from __future__ import annotations

from typing import Any, Dict

from AI.engine.ai_storage import append_json_list, read_json, sync_training_manifest, utc_now, write_json

INTERACTIONS_LOG = "ai_interactions.json"
SELF_AUDIT_LOG = "ai_self_audit.json"
TRAINING_POLICY = "ai_training_policy.json"
LOW_VALUE_PHRASES = ("لم أجد بيانات", "لم أتمكن", "غير متوفر", "غير مفهرس", "غير مهيأ", "عذراً", "لا توجد بيانات", "not available", "no data", "sorry")


def _confidence_percent(value: Any) -> float:
    try:
        num = float(value or 0)
    except Exception:
        return 0.0
    if 0 <= num <= 1:
        num *= 100
    return max(0.0, min(100.0, num))


def _is_low_value_answer(answer: str) -> bool:
    text = str(answer or "").lower()
    return any(phrase.lower() in text for phrase in LOW_VALUE_PHRASES)


def log_interaction(question, answer, confidence, search_results):
    try:
        confidence_pct = _confidence_percent(confidence)
        has_data = len(search_results) > 1 if isinstance(search_results, dict) else False
        append_json_list(
            INTERACTIONS_LOG,
            {
                "timestamp": utc_now(),
                "question": str(question or "")[:200],
                "answer": str(answer or "")[:300],
                "confidence": confidence_pct,
                "data_keys": list(search_results.keys()) if isinstance(search_results, dict) else [],
                "has_data": has_data,
                "low_value": _is_low_value_answer(answer) and not has_data,
            },
            max_items=100,
        )
        sync_training_manifest()
    except Exception:
        pass


def analyze_recent_interactions(count=100):
    try:
        interactions = read_json(INTERACTIONS_LOG, [])
        if not isinstance(interactions, list) or not interactions:
            return {"total": 0, "analyzed": 0, "avg_confidence": 0, "weak_areas": [], "weak_count": 0, "low_value_count": 0, "quality_score": "N/A"}

        recent = interactions[-max(1, int(count or 100)):]
        confidences = [_confidence_percent(i.get("confidence", 0)) for i in recent]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        weak_interactions = [i for i in recent if _confidence_percent(i.get("confidence", 0)) < 70 or i.get("low_value")]
        low_value_count = sum(1 for i in recent if i.get("low_value") or _is_low_value_answer(i.get("answer", "")))

        weak_areas = []
        for interaction in weak_interactions:
            question_keywords = str(interaction.get("question", "")).lower()
            if "نفق" in question_keywords or "مصروف" in question_keywords:
                weak_areas.append("expenses")
            elif "فاتورة" in question_keywords:
                weak_areas.append("invoices")
            elif "صيانة" in question_keywords:
                weak_areas.append("services")
            elif "زبون" in question_keywords or "زبون" in question_keywords:
                weak_areas.append("customers")
            elif "مخزون" in question_keywords or "منتج" in question_keywords:
                weak_areas.append("inventory")
            elif "ضريبة" in question_keywords or "vat" in question_keywords:
                weak_areas.append("tax")

        quality = "ممتاز" if avg_confidence >= 90 and low_value_count == 0 else "جيد" if avg_confidence >= 70 and low_value_count <= max(1, len(recent) * 0.1) else "يحتاج تحسين"
        return {
            "total": len(interactions),
            "analyzed": len(recent),
            "avg_confidence": round(avg_confidence, 2),
            "weak_count": len(weak_interactions),
            "low_value_count": low_value_count,
            "weak_areas": sorted(set(weak_areas)),
            "quality_score": quality,
        }
    except Exception as exc:
        return {"error": str(exc)}


def generate_self_audit_report():
    try:
        analysis = analyze_recent_interactions(100)
        policy = load_training_policy()
        report = {
            "generated_at": utc_now(),
            "policy_version": policy.get("policy_version", "N/A") if isinstance(policy, dict) else "N/A",
            "interactions_analysis": analysis,
            "system_health": "healthy",
            "recommendations": [],
        }

        if analysis.get("avg_confidence", 0) < 70 or analysis.get("low_value_count", 0) > 0:
            report["system_health"] = "needs_improvement"
            report["recommendations"].append("تحسين جودة البيانات المرسلة للـ AI ومنع الردود العامة غير المسندة")

        for area in analysis.get("weak_areas", []) or []:
            report["recommendations"].append(f"تحسين البحث في: {area}")

        if not analysis.get("weak_areas") and analysis.get("avg_confidence", 0) >= 90 and analysis.get("low_value_count", 0) == 0:
            report["system_health"] = "excellent"
            report["recommendations"].append("✅ الأداء ممتاز - استمر")

        write_json(SELF_AUDIT_LOG, report)
        sync_training_manifest()
        return report
    except Exception as exc:
        return {"error": str(exc)}


def load_training_policy():
    data = read_json(TRAINING_POLICY, {})
    return data if isinstance(data, dict) else {}


def check_policy_compliance(confidence, has_data):
    policy = load_training_policy()
    min_confidence = _confidence_percent(policy.get("core_rules", {}).get("confidence_threshold", {}).get("minimum", 20))
    confidence_pct = _confidence_percent(confidence)

    compliance = {"passed": True, "violations": [], "allow_partial": False, "confidence_percent": confidence_pct}

    if 20 <= confidence_pct < 50:
        compliance["allow_partial"] = True
    elif confidence_pct < min_confidence:
        compliance["passed"] = False
        compliance["violations"].append(f"Confidence {confidence_pct}% < الحد الأدنى {min_confidence}%")

    if not has_data and confidence_pct < 15 and policy.get("core_rules", {}).get("no_guessing", {}).get("enabled"):
        compliance["passed"] = False
        compliance["violations"].append("لا توجد بيانات كافية للإجابة")

    return compliance


def get_system_status():
    try:
        analysis = analyze_recent_interactions(100)
        policy = load_training_policy()
        manifest = sync_training_manifest()
        return {
            "timestamp": utc_now(),
            "system_name": "Azad Garage Manager AI",
            "version": policy.get("policy_version", "N/A"),
            "knowledge_cache": "loaded" if manifest.get("files", {}).get("ai_knowledge_cache.json", {}).get("exists") else "missing",
            "avg_confidence": analysis.get("avg_confidence", 0),
            "total_interactions": analysis.get("total", 0),
            "low_value_count": analysis.get("low_value_count", 0),
            "quality_score": analysis.get("quality_score", "N/A"),
            "health": analysis.get("avg_confidence", 0) >= 70 and analysis.get("low_value_count", 0) == 0,
            "manifest": manifest.get("summary", {}),
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "log_interaction",
    "analyze_recent_interactions",
    "generate_self_audit_report",
    "load_training_policy",
    "check_policy_compliance",
    "get_system_status",
]
