"""

عزل مسارات المنصة وروابط القوالب تحت /t/<slug>/.

"""

from __future__ import annotations



# مسارات محجوبة داخل التينانت (404) — يُستثنى ما في TENANT_SECURITY_ALLOW

TENANT_PLATFORM_BLOCKED_PREFIXES: tuple[str, ...] = (

    "/advanced",

    "/security",

    "/ai",

    "/ai-admin",

    "/pricing",

    "/other-systems",

)



TENANT_SECURITY_ALLOW: tuple[str, ...] = ("/security/ledger-control",)





def tenant_path_blocked(path: str) -> bool:

    p = (path or "").split("?")[0].rstrip("/") or "/"

    if any(p.startswith(allow) for allow in TENANT_SECURITY_ALLOW):

        return False

    return any(p.startswith(prefix) for prefix in TENANT_PLATFORM_BLOCKED_PREFIXES)





def gm_url_prefix() -> str:

    """بادئة SCRIPT_NAME — فارغة على المنصة، /t/<slug> داخل التينانت."""

    try:

        from flask import has_request_context, request



        if not has_request_context():

            return ""

        return (request.script_root or "").rstrip("/")

    except Exception:

        return ""





def gm_path(path: str) -> str:

    """مسار مطلق يحترم بادئة التينانت."""

    p = (path or "").strip()

    if not p:

        return gm_url_prefix() or "/"

    if p.startswith(("http://", "https://", "//")):

        return p

    if p.startswith("/static/"):

        return p

    if not p.startswith("/"):

        p = "/" + p

    prefix = gm_url_prefix()

    return f"{prefix}{p}" if prefix else p





def template_context() -> dict:

    """قيم عامة للقوالب — روابط متوافقة مع بادئة التينانت."""

    try:

        from flask import has_request_context, url_for



        if not has_request_context():

            return {}

    except Exception:

        return {}



    prefix = gm_url_prefix()

    out: dict = {"gm_url_prefix": prefix, "gm_path": gm_path}



    try:

        from flask import g



        if getattr(g, "tenant_slug", None):

            out["gm_in_tenant"] = True

    except Exception:

        pass



    _safe = (

        ("ledger_api_base", "ledger_control.index"),

        ("financial_hub_url", "financial_reports.index"),

        ("accounting_validation_url", "accounting_validation.index"),

        ("accounting_docs_url", "accounting_docs.index"),

        ("returns_list_url", "returns.list_returns"),

        ("checks_new_url", "checks.add_check"),

        ("checks_reports_url", "checks.reports"),

        ("fr_income_statement_url", "financial_reports.income_statement"),

        ("fr_balance_sheet_url", "financial_reports.balance_sheet"),

        ("fr_cash_flow_url", "financial_reports.cash_flow"),

        ("fr_aging_ar_url", "financial_reports.aging_report", {"type": "ar"}),

        ("fr_aging_ap_url", "financial_reports.aging_report", {"type": "ap"}),

        ("fr_trial_balance_url", "financial_reports.trial_balance"),

        ("api_exchange_rates_url", "api.get_exchange_rates"),

        ("api_balances_summary_url", "balances_api.get_balances_summary"),
        ("api_balances_clear_cache_url", "balances_api.clear_balance_cache"),

    )

    for item in _safe:

        key = item[0]

        endpoint = item[1]

        kwargs = item[2] if len(item) > 2 else {}

        try:

            out[key] = url_for(endpoint, **kwargs).rstrip("/")

        except Exception:

            out[key] = ""



    return out


