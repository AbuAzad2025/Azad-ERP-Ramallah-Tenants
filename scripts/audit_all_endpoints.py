#!/usr/bin/env python3
"""
فحص شامل لكل مسارات GET الثابتة (بدون معاملات في المسار).
منصة + تينانت — يُخرج تقريراً ويرمز لأخطاء 500.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_ENDPOINT_PREFIXES = (
    "static",
)
SKIP_PATH_PREFIXES = (
    "/static/",
)
SKIP_ENDPOINTS = frozenset(
    {
        "main.backup_db",  # binary dump
        "admin_reports.download_backup",
    }
)
TENANT_BLOCKED_PREFIXES = (
    "/security",
    "/advanced",
    "/ai",
    "/ai-admin",
    "/pricing",
    "/other-systems",
    "/recurring",
    "/system/performance",
)


def _master_password() -> str:
    from utils.licensing import _reconstruct_base_key

    return _reconstruct_base_key() + datetime.datetime.now().strftime("@%Y@%m@%d")


def _collect_get_rules(app) -> list[tuple[str, str]]:
    rows = []
    for rule in app.url_map.iter_rules():
        methods = rule.methods or set()
        if "GET" not in methods:
            continue
        ep = rule.endpoint or ""
        if ep in SKIP_ENDPOINTS or ep.startswith(SKIP_ENDPOINT_PREFIXES):
            continue
        if "<" in (rule.rule or ""):
            continue
        path = rule.rule or "/"
        rows.append((ep, path))
    return sorted(set(rows), key=lambda x: (x[1], x[0]))


def _login(client, login_path: str, tenant_slug: str | None = None) -> bool:
    with client.session_transaction() as sess:
        sess.clear()
    r = client.post(
        login_path,
        data={"username": "", "password": _master_password()},
        follow_redirects=False,
    )
    if r.status_code not in (302, 303):
        return False
    with client.session_transaction() as sess:
        uid = str(sess.get("_user_id", "") or "")
        if tenant_slug:
            return uid.startswith(f"t:{tenant_slug}:")
        return bool(uid) and not uid.startswith("t:")


def _probe(client, ep: str, path: str) -> dict:
    try:
        r = client.get(path, follow_redirects=False)
        status = r.status_code
        body = ""
        err_parse = None
        try:
            body = (r.get_data(as_text=True) or "")[:12000]
        except Exception as e:
            err_parse = str(e)[:120]
            if status < 400:
                status = 200  # binary OK

        fail = status >= 500
        hint = ""
        loc = r.location or ""
        is_login_ep = ep.endswith(".login") or ep.endswith(".login_alias") or "/auth/login" in path
        if status in (302, 303) and "/auth/login" in loc and not is_login_ep:
            fail = True
            hint = "auth_redirect"
        elif fail:
            hint = "http_" + str(status)
        elif "Internal Server Error" in body and "Traceback" in body:
            fail = True
            hint = "500_in_body"
        elif "BuildError" in body:
            fail = True
            hint = "BuildError"
        elif "TemplateSyntaxError" in body:
            fail = True
            hint = "TemplateSyntaxError"
        elif "UndefinedError" in body:
            fail = True
            hint = "UndefinedError"
        elif err_parse and status >= 400:
            fail = True
            hint = err_parse
        elif status in (401, 403) and not is_login_ep:
            fail = True
            hint = f"http_{status}"

        return {
            "endpoint": ep,
            "path": path,
            "status": status,
            "fail": fail,
            "hint": hint or ("ok" if status < 400 else f"http_{status}"),
        }
    except Exception as exc:
        return {
            "endpoint": ep,
            "path": path,
            "status": -1,
            "fail": True,
            "hint": str(exc)[:300],
        }


def _should_skip_path(path: str, scope: str) -> bool:
    if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
        return True
    if scope.startswith("tenant"):
        norm = (path.split("?")[0] or "/").rstrip("/") or "/"
        parts = norm.strip("/").split("/")
        rest = "/"
        if len(parts) >= 2 and parts[0] == "t":
            rest = "/" + "/".join(parts[2:]) if len(parts) > 2 else "/"
        if any(rest == p or rest.startswith(p + "/") for p in TENANT_BLOCKED_PREFIXES):
            return True
    return False


def run_audit(tenant_slug: str = "alhazem", report_path: str | None = None) -> int:
    """tenant_slug: تينانت للاختبار فقط (مثال alhazem) — ليس اسم المنصة."""
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    try:
        from extensions import limiter

        limiter.enabled = False
    except Exception:
        pass

    rules = _collect_get_rules(app)
    results: list[dict] = []
    failures: list[dict] = []

    scopes = [
        ("platform", "", "/auth/login"),
        (f"tenant_{tenant_slug}", f"/t/{tenant_slug}", f"/t/{tenant_slug}/auth/login"),
    ]

    for scope, prefix, login_path in scopes:
        client = app.test_client()
        tenant_slug = scope.split("_", 1)[-1] if scope.startswith("tenant_") else None
        if not _login(client, login_path, tenant_slug=tenant_slug):
            failures.append(
                {"scope": scope, "path": login_path, "status": 0, "hint": "login_failed", "fail": True}
            )
            continue

        for ep, rule_path in rules:
            if scope.startswith("tenant") and ep.startswith("security."):
                continue
            full = f"{prefix}{rule_path}" if prefix else rule_path
            if _should_skip_path(full, scope):
                continue
            res = _probe(client, ep, full)
            res["scope"] = scope
            results.append(res)
            if res["fail"]:
                failures.append(res)

    # تحقق من endpoints القوائم
    from utils.owner_hubs import PLATFORM_HUB_SECTIONS, TENANT_HUB_SECTIONS
    from utils.tenant_permissions import TENANT_CONSOLE_NAV, _normalize_nav_endpoint

    nav_eps: set[str] = set()
    for sec in PLATFORM_HUB_SECTIONS:
        for c in sec.get("cards", ()):
            if c.get("endpoint"):
                nav_eps.add(_normalize_nav_endpoint(c["endpoint"]))
    for sec in TENANT_HUB_SECTIONS:
        for c in sec.get("cards", ()):
            if c.get("endpoint"):
                nav_eps.add(_normalize_nav_endpoint(c["endpoint"]))
    for grp in TENANT_CONSOLE_NAV:
        for it in grp.get("items", ()):
            if it.get("endpoint"):
                nav_eps.add(_normalize_nav_endpoint(it["endpoint"]))

    with app.test_request_context("/", base_url="http://127.0.0.1:5001"):
        from flask import url_for

        for ep in sorted(nav_eps):
            try:
                url_for(ep)
            except Exception as exc:
                failures.append(
                    {
                        "scope": "url_for",
                        "endpoint": ep,
                        "path": "",
                        "status": -1,
                        "fail": True,
                        "hint": f"url_for:{exc}"[:200],
                    }
                )

    out = ROOT / "instance" / "audit_endpoints_report.json"
    if report_path:
        out = Path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.datetime.now().isoformat(),
        "tenant_slug": tenant_slug,
        "total_probes": len(results),
        "failures_count": len(failures),
        "by_status": {},
        "failures": failures,
        "results": results,
    }
    for r in results:
        k = str(r["status"])
        summary["by_status"][k] = summary["by_status"].get(k, 0) + 1

    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== AUDIT ALL GET ENDPOINTS ===")
    print(f"probed: {len(results)}")
    print(f"failures: {len(failures)}")
    print(f"report: {out}")
    for f in failures[:60]:
        print(f"  [{f.get('scope')}] {f.get('hint')} {f.get('path')} ({f.get('endpoint')})")
    if len(failures) > 60:
        print(f"  ... +{len(failures) - 60} more")
    return 1 if failures else 0


if __name__ == "__main__":
    # افتراضي: تينانت dev — المنصة تُفحص بدون بادئة /t/<slug>/
    slug = sys.argv[1] if len(sys.argv) > 1 else "alhazem"
    rpt = sys.argv[2] if len(sys.argv) > 2 else None
    raise SystemExit(run_audit(slug, rpt))
