"""AI Master Controller.

Central coordinator for the AI subsystems. The controller keeps the existing
public API stable while making subsystem startup resilient: a failure in one
engine must not disable the whole AI stack. If no expert engine can produce a
real answer, the controller returns an empty answer so the service facade can
fall back to live local database/context handling instead of showing a fake
low-quality response.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


SubsystemFactory = Tuple[str, str, str]


class MasterController:
    """Coordinate reasoning, guide, learning, audit, and memory subsystems."""

    SUBSYSTEM_FACTORIES: Tuple[SubsystemFactory, ...] = (
        ("reasoning", "AI.engine.ai_reasoning_engine", "get_reasoning_engine"),
        ("python_expert", "AI.engine.ai_python_expert", "get_python_expert"),
        ("database_expert", "AI.engine.ai_database_expert", "get_database_expert"),
        ("web_expert", "AI.engine.ai_web_expert", "get_web_expert"),
        ("guide_master", "AI.engine.ai_user_guide_master", "get_user_guide_master"),
        ("learning", "AI.engine.ai_learning_system", "get_learning_system"),
        ("evolution", "AI.engine.ai_self_evolution", "get_evolution_engine"),
        ("performance", "AI.engine.ai_performance_tracker", "get_performance_tracker"),
        ("auditor", "AI.engine.ai_accounting_auditor", "get_accounting_auditor"),
        ("continuous_learner", "AI.engine.ai_continuous_learner", "get_continuous_learner"),
        ("book_reader", "AI.engine.ai_book_reader", "get_book_reader"),
        ("deep_memory", "AI.engine.ai_deep_memory", "get_deep_memory"),
        ("comprehension", "AI.engine.ai_comprehension_engine", "get_comprehension_engine"),
    )

    SAFE_COMMANDS = {
        "scan_system",
        "audit_accounting",
        "optimize_performance",
        "self_diagnose",
        "start_learning_session",
        "read_book",
        "comprehend_concept",
        "consolidate_memory",
    }

    def __init__(self):
        self.subsystems: Dict[str, Any] = {}
        self.subsystem_errors: Dict[str, str] = {}
        self.active_operations: List[Dict[str, Any]] = []
        self.system_state: Dict[str, Any] = {}
        self._initialize_subsystems()

    def _initialize_subsystems(self) -> None:
        self.subsystems.clear()
        self.subsystem_errors.clear()

        for name, module_path, factory_name in self.SUBSYSTEM_FACTORIES:
            self.system_state[name] = False
            try:
                module = __import__(module_path, fromlist=[factory_name])
                factory: Callable[[], Any] = getattr(module, factory_name)
                instance = factory()
                self.subsystems[name] = instance
                self.system_state[name] = bool(instance)
            except Exception as exc:
                self.subsystems[name] = None
                self.subsystem_errors[name] = str(exc)
                print(f"Subsystem init error [{name}]: {exc}")

        self.system_state["experts"] = {
            "python": bool(self.subsystems.get("python_expert")),
            "database": bool(self.subsystems.get("database_expert")),
            "web": bool(self.subsystems.get("web_expert")),
            "guide": bool(self.subsystems.get("guide_master")),
        }

    def process_intelligent_query(self, query: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        operation = self._new_operation(query)

        try:
            result = self._try_reasoning(query, context, operation)
            if result:
                return result

            result = self._try_python_expert(query, context, operation)
            if result:
                return result

            result = self._try_database_expert(query, operation)
            if result:
                return result

            result = self._try_user_guide(query, operation)
            if result:
                return result

            fallback = {"answer": "", "confidence": 0.0, "sources": [], "defer_to_service": True}
            operation["result"] = fallback
            self._track_operation(operation)
            return fallback
        except Exception as exc:
            operation["error"] = str(exc)
            self._track_operation(operation)
            raise

    def _new_operation(self, query: str) -> Dict[str, Any]:
        return {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "query": query,
            "start_time": datetime.now(),
            "subsystems_used": [],
            "reasoning_steps": [],
            "confidence_breakdown": {},
            "result": None,
        }

    def _try_reasoning(self, query: str, context: Dict, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        engine = self.subsystems.get("reasoning")
        if not engine:
            return None
        operation["subsystems_used"].append("reasoning")
        result = engine.reason_through_problem(query, context)
        if isinstance(result, dict) and result.get("answer"):
            confidence = float(result.get("confidence", 0) or 0)
            if confidence < 0.45 and not result.get("data_used"):
                return None
            operation["result"] = result
            operation["reasoning_steps"] = result.get("reasoning_steps", [])
            operation["confidence_breakdown"]["reasoning"] = result.get("confidence", 0)
            if result.get("data_used"):
                operation["data_accessed"] = result["data_used"]
            self._track_operation(operation)
            return result
        return None

    def _try_python_expert(self, query: str, context: Dict, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        text = (query or "").lower()
        if not any(word in text for word in ("error", "خطأ", "python", "traceback")):
            return None
        expert = self.subsystems.get("python_expert")
        if not expert:
            return None
        operation["subsystems_used"].append("python_expert")
        result = expert.analyze_error(query, context.get("code", ""))
        if result:
            operation["result"] = result
            self._track_operation(operation)
            return {"answer": self._format_python_error_answer(result), "confidence": 0.9, "sources": ["Python Expert"]}
        return None

    def _try_database_expert(self, query: str, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        text = (query or "").lower()
        if not any(word in text for word in ("جدول", "موديل", "model", "table", "schema", "قاعدة", "استعلام", "query", "sql", "حقل", "field", "علاقة", "relation")):
            return None
        expert = self.subsystems.get("database_expert")
        if not expert:
            return None
        operation["subsystems_used"].append("database_expert")
        result = None
        if "select" in text or "sql" in text:
            result = expert.analyze_query(query)
            answer = self._format_sql_analysis(result)
        else:
            result = expert.describe_business_question(query) if hasattr(expert, "describe_business_question") else None
            answer = self._format_database_expert_answer(result)
        if result and answer:
            operation["result"] = result
            self._track_operation(operation)
            return {"answer": answer, "confidence": 0.86, "sources": ["Database Expert"]}
        return None

    def _try_user_guide(self, query: str, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        guide = self.subsystems.get("guide_master")
        if not guide:
            return None
        operation["subsystems_used"].append("guide_master")
        result = guide.answer_question(query)
        if result and isinstance(result, dict) and result.get("steps"):
            operation["result"] = result
            self._track_operation(operation)
            return {"answer": self._format_guide_answer(result), "confidence": 0.9, "sources": ["Expert User Guide"]}
        return None

    def _format_python_error_answer(self, result: Dict) -> str:
        parts = [f"🐍 نوع الخطأ: {result.get('error_type', 'غير محدد')}", f"\n📌 السبب: {result.get('cause', '')}"]
        if result.get("solutions"):
            parts.append("\n✅ الحلول:")
            for i, sol in enumerate(result["solutions"][:5], 1):
                parts.append(f"{i}. {sol}")
        if result.get("code_fix"):
            parts.append(f"\n💻 الكود الصحيح:\n```python\n{result['code_fix']}\n```")
        if result.get("prevention_tips"):
            parts.append("\n🛡️ الوقاية:")
            for tip in result["prevention_tips"][:3]:
                parts.append(f"  - {tip}")
        return "\n".join(parts)

    def _format_sql_analysis(self, result: Dict) -> str:
        if not result:
            return ""
        parts = ["🗄️ تحليل الاستعلام:", f"درجة الأداء التقديرية: {result.get('performance_score', 'غير معروف')}/100", f"التعقيد: {result.get('estimated_complexity', 'unknown')}"]
        if result.get("issues"):
            parts.append("\n⚠️ مشاكل:")
            for item in result.get("issues", [])[:6]:
                parts.append(f"  • {item.get('message')} — الحل: {item.get('fix', 'راجع الاستعلام')}")
        self._add_list_section(parts, "💡 اقتراحات", result.get("suggestions"), 6)
        return "\n".join(parts)

    def _format_database_expert_answer(self, result: Dict) -> str:
        if not result or not result.get("best_match"):
            return ""
        best = result["best_match"]
        parts = [f"🗄️ فهم قاعدة البيانات للسؤال: {best.get('domain')}"]
        if best.get("models"):
            parts.append("\n📌 الموديلات المرشحة:")
            for model in best.get("models", [])[:8]:
                parts.append(f"  • {model}")
        self._add_list_section(parts, "✅ ما يراجعه المستخدم الخبير", best.get("expert_focus"), 8)
        self._add_list_section(parts, "🔎 فلاتر آمنة ومفيدة", best.get("safe_filters"), 8)
        parts.append("\nملاحظة: هذه خريطة ترشيح ذكية؛ القراءة النهائية يجب أن تتم من الحقول والعلاقات الفعلية في النظام.")
        return "\n".join(parts)

    def _add_list_section(self, parts: List[str], title: str, values, limit: int = 8) -> None:
        if not values:
            return
        parts.append(f"\n{title}:")
        for value in list(values)[:limit]:
            parts.append(f"  • {value}")

    def _format_guide_answer(self, result: Dict) -> str:
        parts: List[str] = []
        if result.get("topic"):
            parts.append(f"📍 {result['topic']}")
        if result.get("description"):
            parts.append(f"\n{result['description']}")
        if result.get("professional_hint"):
            parts.append(f"\n🧠 خبرة عملية:\n  {result['professional_hint']}")
        if result.get("route"):
            parts.append(f"\n🔗 المسار: {result['route']}")
        if result.get("steps"):
            parts.append("\n📋 خطوات العمل:")
            for i, step in enumerate(result["steps"], 1):
                parts.append(f"  {i}. {step}")
        if result.get("fields"):
            parts.append("\n📝 أهم الحقول:")
            for field, desc in list(result["fields"].items())[:10]:
                parts.append(f"  • {field}: {desc}")
        self._add_list_section(parts, "✅ فحص المستخدم المتمرس قبل الحفظ", result.get("expert_checks"), 8)
        self._add_list_section(parts, "🔎 ماذا تراجع بعد الحفظ", result.get("after_save"), 8)
        self._add_list_section(parts, "⚠️ أخطاء شائعة", result.get("common_mistakes"), 8)
        if result.get("calculations"):
            parts.append("\n🧮 الحسابات المرتبطة:")
            for key, desc in result["calculations"].items():
                parts.append(f"  • {key}: {desc}")
        if result.get("stock_effect"):
            parts.append(f"\n📦 أثر المخزون:\n  {result['stock_effect']}")
        if result.get("concepts"):
            parts.append("\n📚 مفاهيم مرتبطة:")
            for key, desc in list(result["concepts"].items())[:8]:
                parts.append(f"  • {key}: {desc}")
        self._add_list_section(parts, "🔗 وحدات مرتبطة", result.get("related_modules"), 8)
        self._add_list_section(parts, "💡 ملاحظات ذكية", result.get("tips"), 8)
        return "\n".join(parts)

    def _track_operation(self, operation: Dict) -> None:
        operation["end_time"] = datetime.now()
        operation["duration"] = (operation["end_time"] - operation["start_time"]).total_seconds()
        self.active_operations.append(operation)
        if len(self.active_operations) > 100:
            self.active_operations = self.active_operations[-100:]

    def get_system_status(self) -> Dict:
        return {
            "state": self.system_state,
            "subsystem_errors": self.subsystem_errors,
            "active_operations": len(self.active_operations),
            "recent_operations": self.active_operations[-10:] if self.active_operations else [],
            "subsystems_count": len([s for s in self.subsystems.values() if s]),
            "all_operational": all(bool(v) for k, v in self.system_state.items() if k != "experts"),
        }

    def execute_system_command(self, command: str, params: Optional[Dict] = None) -> Dict:
        params = params or {}
        command = (command or "").strip()
        if command not in self.SAFE_COMMANDS:
            return {"success": False, "error": "Unknown or unsafe command"}

        if command == "scan_system":
            return self._scan_all_systems()
        if command == "audit_accounting":
            return self._run_accounting_audit()
        if command == "optimize_performance":
            return self._optimize_all_systems()
        if command == "self_diagnose":
            return self._diagnose_system_health()
        if command == "start_learning_session":
            return self._start_learning_session()
        if command == "read_book":
            return self._read_book(params.get("file_path"), params.get("format", "markdown"))
        if command == "comprehend_concept":
            return self._comprehend_concept(params.get("concept"))
        if command == "consolidate_memory":
            return self._consolidate_all_memory()
        return {"success": False, "error": "Unknown command"}

    def _scan_all_systems(self) -> Dict:
        return {"success": True, "results": {"timestamp": datetime.now().isoformat(), "subsystems": {name: {"status": "operational" if subsystem else "offline", "type": type(subsystem).__name__ if subsystem else None, "error": self.subsystem_errors.get(name)} for name, subsystem in self.subsystems.items()}}}

    def _run_accounting_audit(self) -> Dict:
        auditor = self.subsystems.get("auditor")
        if not auditor:
            return {"success": False, "error": "Auditor not available"}
        return {"success": True, "audit_summary": auditor.get_audit_summary()}

    def _optimize_all_systems(self) -> Dict:
        optimizations: List[str] = []
        perf_engine = self.subsystems.get("performance")
        if perf_engine:
            perf = perf_engine.get_performance_report()
            if perf.get("avg_response_time", 0) > 1.0:
                optimizations.append("Response time slow - consider caching")
            if perf.get("success_rate", 0) < 80:
                optimizations.append("Success rate low - review reasoning engine")
        evo_engine = self.subsystems.get("evolution")
        if evo_engine:
            evo = evo_engine.get_evolution_report()
            if evo.get("evolution_level", 0) < 3:
                optimizations.append("Evolution level low - needs more training")
        return {"success": True, "optimizations": optimizations}

    def _diagnose_system_health(self) -> Dict:
        health = {"overall": "healthy", "issues": [], "warnings": []}
        for name, subsystem in self.subsystems.items():
            if not subsystem:
                health["issues"].append(f"{name} is offline: {self.subsystem_errors.get(name, 'unknown error')}")
                health["overall"] = "degraded"
        perf_engine = self.subsystems.get("performance")
        if perf_engine:
            perf = perf_engine.get_performance_report()
            if perf.get("recent_trend") == "declining":
                health["warnings"].append("Performance trend is declining")
        return health

    def _start_learning_session(self) -> Dict:
        learner = self.subsystems.get("continuous_learner")
        if not learner:
            return {"success": False, "error": "Continuous learner not available"}
        return {"success": True, "session": learner.start_learning_session()}

    def _read_book(self, file_path: Optional[str], format: str = "markdown") -> Dict:
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        if os.path.isabs(file_path) or ".." in file_path.replace("\\", "/").split("/"):
            return {"success": False, "error": "Unsafe file path"}
        reader = self.subsystems.get("book_reader")
        if not reader:
            return {"success": False, "error": "Book reader not available"}
        if format == "pdf":
            return reader.read_pdf_book(file_path)
        return reader.read_markdown_book(file_path)

    def _comprehend_concept(self, concept: Optional[str]) -> Dict:
        if not concept:
            return {"success": False, "error": "concept is required"}
        comp = self.subsystems.get("comprehension")
        if not comp:
            return {"success": False, "error": "Comprehension engine not available"}
        return {"success": True, "explanation": comp.explain_fully(concept)}

    def _consolidate_all_memory(self) -> Dict:
        memory = self.subsystems.get("deep_memory")
        if not memory:
            return {"success": False, "error": "Deep memory not available"}
        consolidated = memory.consolidate_memory()
        return {"success": True, "consolidated_items": consolidated, "memory_stats": memory.get_memory_stats()}


_master_controller: Optional[MasterController] = None


def get_master_controller() -> MasterController:
    global _master_controller
    if _master_controller is None:
        _master_controller = MasterController()
    return _master_controller


__all__ = ["MasterController", "get_master_controller"]
