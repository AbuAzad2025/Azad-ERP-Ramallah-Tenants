"""Security binding for AI management helper outputs."""

from __future__ import annotations

_BOUND = False


def bind_ai_management_security() -> bool:
    global _BOUND
    if _BOUND:
        return False

    import AI.engine.ai_management as mgmt
    from AI.engine import ai_input_filter as sf

    base_test = mgmt.test_api_key
    base_list = mgmt.list_configured_apis
    base_stats = mgmt.get_live_ai_stats
    base_job = mgmt.get_training_job_status
    base_jobs = mgmt.list_training_jobs
    base_models = mgmt.get_model_status

    def test_api_key(api_name):
        return sf.clean_data(base_test(sf.clean_text(api_name)))

    def list_configured_apis():
        return sf.clean_data(base_list())

    def get_live_ai_stats():
        return sf.clean_data(base_stats())

    def get_training_job_status(job_id):
        return sf.clean_data(base_job(sf.clean_text(job_id)))

    def list_training_jobs(limit=10):
        return sf.clean_data(base_jobs(limit))

    def get_model_status(model_name=None):
        return sf.clean_data(base_models(model_name))

    mgmt.test_api_key = test_api_key
    mgmt.list_configured_apis = list_configured_apis
    mgmt.get_live_ai_stats = get_live_ai_stats
    mgmt.get_training_job_status = get_training_job_status
    mgmt.list_training_jobs = list_training_jobs
    mgmt.get_model_status = get_model_status

    _BOUND = True
    return True


__all__ = ["bind_ai_management_security"]
