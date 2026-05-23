#!/usr/bin/env python3
"""فحص GET لصفحات رئيسية — منصة + تينانت — يُبلّغ عن 500 وأخطاء القوالب."""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _master_password() -> str:
    from utils.licensing import _reconstruct_base_key

    return _reconstruct_base_key() + datetime.datetime.now().strftime("@%Y@%m@%d")


def _login(client, login_path: str) -> bool:
    mk = _master_password()
    r = client.post(login_path, data={"username": "", "password": mk}, follow_redirects=False)
    return r.status_code in (302, 303)


def _collect_static_get_rules(app):
    out = []
    for rule in app.url_map.iter_rules():
        if "GET" not in (rule.methods or set()):
            continue
        if rule.endpoint == "static":
            continue
        if "<" in rule.rule:
            continue
        path = rule.rule
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")
        out.append((rule.endpoint, path))
    return sorted(set(out), key=lambda x: x[1])


def _nav_endpoints():
    from utils.owner_hubs import PLATFORM_HUB_SECTIONS, TENANT_HUB_SECTIONS
    from utils.tenant_permissions import TENANT_CONSOLE_NAV

    eps = set()
    for sec in PLATFORM_HUB_SECTIONS:
        for c in sec.get("cards", ()):
            ep = c.get("endpoint")
            if ep:
                eps.add(ep)
    for sec in TENANT_HUB_SECTIONS:
        for c in sec.get("cards", ()):
            ep = c.get("endpoint")
            if ep:
                eps.add(ep)
    for grp in TENANT_CONSOLE_NAV:
        for it in grp.get("items", ()):
            ep = it.get("endpoint")
            if ep:
                eps.add(ep)
    return eps


def _path_for_endpoint(app, endpoint: str, prefix: str = "") -> str | None:
    try:
        base = prefix if prefix else "/"
        with app.test_request_context(base):
            from flask import g, url_for

            if prefix.startswith("/t/"):
                parts = prefix.strip("/").split("/")
                if len(parts) >= 2:
                    slug = parts[1]
                    g.tenant_slug = slug
            p = url_for(endpoint)
            if prefix and not p.startswith(prefix):
                return prefix.rstrip("/") + (p if p.startswith("/") else "/" + p)
            return p
    except Exception:
        return None


def _probe(client, label: str, path: str) -> dict:
    try:
        r = client.get(path, follow_redirects=True)
        body = (r.get_data(as_text=True) or "")[:8000]
        err_500 = r.status_code >= 500
        build_err = "BuildError" in body or "Internal Server Error" in body and r.status_code == 200
        undefined = body.count("undefined") > 3 and "validation" in path.lower()
        return {
            "label": label,
            "path": path,
            "status": r.status_code,
            "fail": err_500 or build_err,
            "hint": (
                "500"
                if err_500
                else "BuildError in body"
                if build_err
                else "many undefined"
                if undefined
                else ""
            ),
        }
    except Exception as exc:
        return {"label": label, "path": path, "status": -1, "fail": True, "hint": str(exc)[:200]}


def run_smoke(tenant_slug: str = "alhazem") -> int:
    from app import create_app

    app = create_app()
    failures = []

    with app.app_context():
        nav_eps = _nav_endpoints()
        static_rules = _collect_static_get_rules(app)

    scopes = [
        ("platform", "", "/auth/login"),
        (f"tenant_{tenant_slug}", f"/t/{tenant_slug}", f"/t/{tenant_slug}/auth/login"),
    ]

    for scope_label, prefix, login_path in scopes:
        client = app.test_client()
        if not _login(client, login_path):
            failures.append({"label": scope_label, "path": login_path, "status": 0, "fail": True, "hint": "login failed"})
            continue

        seen = set()
        # أولوية: روابط القوائم والبطاقات
        for ep in sorted(nav_eps):
            path = _path_for_endpoint(app, ep, prefix)
            if not path or path in seen:
                continue
            seen.add(path)
            res = _probe(client, f"{scope_label}:{ep}", path)
            if res["fail"]:
                failures.append(res)

        # مسارات GET ثابتة إضافية (حد منخفض لتجنب rate-limit على login)
        count = 0
        for ep, rule_path in static_rules:
            if count > 40:
                break
            full = prefix + rule_path if not rule_path.startswith(prefix) else rule_path
            if full in seen:
                continue
            if scope_label.startswith("tenant") and full.startswith("/security"):
                continue
            if scope_label == "platform" and full.startswith("/t/"):
                continue
            seen.add(full)
            res = _probe(client, f"{scope_label}:{ep}", full)
            if res["fail"]:
                failures.append(res)
            count += 1

    print("=== SMOKE HTTP PAGES ===")
    print(f"failures: {len(failures)}")
    for f in failures[:80]:
        print(f"  [{f['status']}] {f['hint']} {f['path']} ({f['label']})")
    if len(failures) > 80:
        print(f"  ... +{len(failures) - 80} more")
    return 1 if failures else 0


if __name__ == "__main__":
    slug = (sys.argv[1] if len(sys.argv) > 1 else "alhazem").strip()
    raise SystemExit(run_smoke(slug))
