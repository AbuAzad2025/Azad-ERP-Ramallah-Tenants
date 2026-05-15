"""Security binding for AI master controller entry points."""

from __future__ import annotations

_BOUND = False


def bind_ai_controller_security() -> bool:
    global _BOUND
    if _BOUND:
        return False

    from AI.engine import ai_input_filter as sf
    import AI.engine.ai_master_controller as mc

    original_process = mc.MasterController.process_intelligent_query
    original_command = mc.MasterController.execute_system_command

    def process_intelligent_query(self, query, context=None):
        check = sf.inspect_text(query)
        if not check.get("allowed"):
            return {"answer": sf.BLOCK_MESSAGE, "confidence": 1.0, "sources": ["ai_input_filter"], "permission_denied": True, "issues": check.get("issues", [])}
        context = dict(context or {})
        safe_query = sf.clean_text(query)
        safe_result = original_process(self, safe_query, context)
        return sf.clean_data(safe_result)

    def execute_system_command(self, command, params=None):
        check = sf.inspect_text(command)
        if not check.get("allowed"):
            return sf.deny(check.get("issues", []))
        params = sf.clean_data(dict(params or {}))
        return sf.clean_data(original_command(self, sf.clean_text(command), params))

    mc.MasterController.process_intelligent_query = process_intelligent_query
    mc.MasterController.execute_system_command = execute_system_command
    _BOUND = True
    return True


__all__ = ["bind_ai_controller_security"]
