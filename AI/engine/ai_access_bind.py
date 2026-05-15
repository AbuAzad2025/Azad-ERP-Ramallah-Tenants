"""Bind AI service outputs to the access filter."""

from __future__ import annotations

_BOUND = False


def bind_ai_service_access() -> bool:
    global _BOUND
    if _BOUND:
        return False

    import AI.engine.ai_service as svc
    from AI.engine import ai_access_filter as af

    base_search = svc.search_database_for_query
    base_context = svc.gather_system_context
    base_response = svc.ai_chat_response
    base_fallback = svc.get_local_fallback_response
    base_entry = svc.ai_chat_with_search
    base_report = svc.generate_smart_report
    base_accounting = svc.analyze_accounting_data
    base_query_accounting = svc.query_accounting_data
    base_deep = svc.deep_data_analysis

    def search_database_for_query(query):
        return af.filter_results(base_search(query))

    def gather_system_context():
        return af.filter_context(base_context())

    def get_local_fallback_response(message, search_results):
        return base_fallback(message, af.filter_results(search_results or {}))

    def ai_chat_response(message, search_results=None, session_id="default"):
        return base_response(message, af.filter_results(search_results or {}), session_id)

    def ai_chat_with_search(user_id=None, query=None, message=None, session_id="default", context=None):
        access = af.current_access()
        denied = af.check_ai_entry(access)
        if denied:
            return denied
        context = dict(context or {})
        context["permission_context"] = access
        return base_entry(user_id=user_id or access.get("user_id"), query=query, message=message, session_id=session_id, context=context)

    def generate_smart_report(intent):
        return af.filter_results(base_report(af.filter_entities(intent or {})))

    def analyze_accounting_data(currency=None):
        denied = af.check_reports_entry()
        if denied:
            return denied
        return af.filter_results(base_accounting(currency))

    def query_accounting_data(query_type, filters=None):
        denied = af.check_query_type(query_type)
        if denied:
            return denied
        return af.filter_results(base_query_accounting(query_type, filters))

    def deep_data_analysis(query, context):
        return af.filter_results(base_deep(query, af.filter_entities(context or {})))

    svc.search_database_for_query = search_database_for_query
    svc.gather_system_context = gather_system_context
    svc.get_local_fallback_response = get_local_fallback_response
    svc.ai_chat_response = ai_chat_response
    svc.ai_chat_with_search = ai_chat_with_search
    svc.generate_smart_report = generate_smart_report
    svc.analyze_accounting_data = analyze_accounting_data
    svc.query_accounting_data = query_accounting_data
    svc.deep_data_analysis = deep_data_analysis

    _BOUND = True
    return True


__all__ = ["bind_ai_service_access"]
