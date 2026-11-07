"""Audit security routes vs templates."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app  # noqa: E402

SECURITY_TPL_DIR = os.path.join(ROOT, "templates", "security")
ROUTE_FILE = os.path.join(ROOT, "routes", "security.py")

RENDER_RE = re.compile(r"render_template\(\s*['\"]security/([^'\"]+)['\"]")
URLFOR_RE = re.compile(
    r"url_for\(\s*['\"]security\.([a-zA-Z0-9_]+)['\"]"
)
DEF_RE = re.compile(r"^def ([a-zA-Z0-9_]+)\(", re.M)


def main():
    with open(ROUTE_FILE, encoding="utf-8") as f:
        route_src = f.read()

    rendered = sorted(set(RENDER_RE.findall(route_src)))
    route_funcs = set(DEF_RE.findall(route_src))

    with app.app_context():
        endpoints = {
            rule.endpoint.split(".", 1)[1]
            for rule in app.url_map.iter_rules()
            if rule.endpoint.startswith("security.")
        }

    tpl_files = sorted(
        f for f in os.listdir(SECURITY_TPL_DIR) if f.endswith(".html")
    )

    missing_endpoints = []
    all_urlfors = set()
    for fn in tpl_files:
        path = os.path.join(SECURITY_TPL_DIR, fn)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for ep in URLFOR_RE.findall(content):
            all_urlfors.add(ep)
            if ep not in endpoints:
                missing_endpoints.append((fn, ep))

    orphan_templates = [
        t for t in tpl_files if t not in rendered and not t.startswith("_")
    ]
    missing_templates = [t for t in rendered if t not in tpl_files]

    # routes that render but endpoint name differs - map html to likely endpoint
    html_to_guess = {
        "index.html": "index",
        "help.html": "help_page",
        "audit_log.html": "audit_log_viewer",
    }

    no_route_html = []
    for t in orphan_templates:
        guess = html_to_guess.get(t, t.replace(".html", ""))
        if guess not in endpoints and t not in (
            "base_security.html",
            "ai_config.html",
            "ledger_control.html",
            "posting_controls.html",
            "enterprise_2fa_setup.html",
        ):
            no_route_html.append((t, guess, guess in endpoints))

    print("=== RENDERED TEMPLATES (%d) ===" % len(rendered))
    for t in rendered:
        print(" ", t)

    print("\n=== ORPHAN HTML (no render_template in security.py) ===")
    for t in orphan_templates:
        print(" ", t)

    print("\n=== MISSING url_for ENDPOINTS ===")
    seen = set()
    for fn, ep in sorted(missing_endpoints):
        key = (fn, ep)
        if key in seen:
            continue
        seen.add(key)
        print(" ", fn, "->", ep)

    print("\n=== render_template missing file ===")
    for t in missing_templates:
        print(" ", t)

    print("\n=== ENDPOINT COUNT ===", len(endpoints))
    print("=== url_for security.* unique ===", len(all_urlfors))

    # Check specific suspected issues
    suspects = [
        "notifications_log",
        "test_notification",
        "toggle_maintenance_mode",
        "clear_system_cache",
        "kill_all_sessions",
        "prometheus_metrics",
        "api_live_metrics",
        "advanced_check_linking",
        "data_quality_center",
        "audit_log_viewer",
        "audit_log_detail",
        "email_manager",
        "logo_manager",
        "data_export",
        "tax_reports",
        "users_center",
        "tools_center",
        "appearance_panel",
        "printing_panel",
        "system_cleanup",
    ]
    print("\n=== KEY ENDPOINT CHECK ===")
    for s in suspects:
        print(f"  {s}: {'OK' if s in endpoints else 'MISSING'}")


if __name__ == "__main__":
    main()
