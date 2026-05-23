#!/usr/bin/env python3
"""
فحص روابط مطلقة قد تكسر مسار التينانت /t/<slug>/.
تشغيل: python scripts/audit_gm_urls.py

ملاحظة: gm-tenant-network.js يعالج وقت التشغيل: fetch, XHR, jQuery, location, form.action.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = [
    (re.compile(r"""href\s*=\s*["']/(?!static|t/)[a-z]""", re.I), "href=/absolute"),
    (re.compile(r"""fetch\s*\(\s*["']/(?!static)[a-z]""", re.I), "fetch(/absolute)"),
    (re.compile(r"""\$\.(get|post|ajax)\s*\(\s*["']/(?!static)[a-z]""", re.I), "jquery(/absolute)"),
    (re.compile(r"""\.open\s*\(\s*["']/(?!static)[a-z]""", re.I), "window.open(/absolute)"),
    (re.compile(r"""XMLHttpRequest.*["']/(?!static)""", re.I), "xhr(/absolute)"),
    (re.compile(r"""submitPost\s*\(\s*["']/"""), "submitPost(/absolute)"),
    (re.compile(r"""window\.location\.(href|assign|replace)\s*=\s*["'`]/"""), "location=/absolute"),
    (re.compile(r"""\.action\s*=\s*["'`]/"""), "form.action=/absolute"),
    (re.compile(r"""url:\s*["'`]/"""), "ajax.url=/absolute"),
]

PLATFORM_ONLY_DIRS = {
    "templates/security",
    "templates/advanced",
    "templates/ai",
    "static/js/security",
}

# يُعالَج تلقائياً عبر static/js/gm-tenant-network.js
RUNTIME_SHIM_OK = {
    "static/js/gm-tenant-network.js",
    "static/js/permissions.js",
    "static/js/archive.js",
    "static/js/payments.js",
    "static/js/payment_form.js",
    "static/js/reporting.js",
    "static/js/shop.js",
    "static/js/checks.js",
    "static/js/app.js",
    "static/js/sales.js",
    "static/js/service.js",
    "static/js/warehouses.js",
    "static/js/customers.js",
    "static/js/vendors.js",
    "static/js/notes.js",
    "static/js/expenses.js",
    "static/js/shipments.js",
    "static/js/barcode.js",
    "static/js/branch-site-filter.js",
    "static/js/balance-loading.js",
    "static/js/module_specific_enhancements.js",
    "templates/barcode_scanner",
    "templates/ledger/",
    "templates/vendors/",
    "templates/warehouses/",
    "templates/payments/",
    "templates/shop/",
    "templates/customers/",
    "templates/recurring/",
    "templates/reports/",
    "templates/sale_returns/",
    "templates/parts/",
    "templates/expenses/",
}

SKIP_FILES = {"audit_gm_urls.py", "fix_template_gm_paths.py", "fix_static_gm_paths.py"}
SKIP_PATH_PARTS = (
    "static/adminlte",
    "static/plugins",
    "node_modules",
    ".venv",
)

# قوالب مستقلة (لا ترث base.html) يجب أن تضمّن gm_tenant_runtime أو gm-tenant-network.js
STANDALONE_TENANT_LAYOUTS = (
    "templates/shop/base.html",
    "templates/auth/auth_base.html",
    "templates/reports/financial/index.html",
    "templates/validation/accounting/index.html",
    "templates/docs/accounting/index.html",
    "templates/admin/reports/cards.html",
)


def is_platform_only(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(s.startswith(str(ROOT / d).replace("\\", "/")) for d in PLATFORM_ONLY_DIRS)


def is_runtime_shim_ok(rel_s: str, label: str) -> bool:
    if any(rel_s.startswith(p) for p in RUNTIME_SHIM_OK):
        return True
    if label in (
        "fetch(/absolute)",
        "jquery(/absolute)",
        "xhr(/absolute)",
        "location=/absolute",
        "form.action=/absolute",
        "ajax.url=/absolute",
    ):
        if rel_s.startswith("static/js/") and "security" not in rel_s:
            return True
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue
        if "gmPath(" in line or "gmU(" in line or "gm_path(" in line or "url_for(" in line:
            continue
        if "{{ url_for" in line or "{{ gm_path" in line:
            continue
        if "submitPost(" in line:
            continue
        if "function submitPost" in line:
            continue
        if "_gmUrl(" in line or "gmRewriteUrl" in line:
            continue
        if "(window.gmPath||window.gmU||" in line:
            continue
        for rx, label in PATTERNS:
            if rx.search(line):
                hits.append((i, label, line.strip()[:140]))
                break
    return hits


def check_standalone_layouts() -> list[str]:
    missing: list[str] = []
    for rel in STANDALONE_TENANT_LAYOUTS:
        path = ROOT / rel.replace("/", "\\") if "\\" in str(ROOT) else ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(rel)
            continue
        if "gm-tenant-network" not in text and "gm_tenant_runtime" not in text:
            missing.append(rel)
    return missing


def main() -> int:
    exts = {".html", ".js", ".jinja", ".jinja2"}
    issues: list[tuple[str, int, str, str]] = []
    scan_roots = [ROOT / "templates", ROOT / "static" / "js"]
    paths: list[Path] = []
    for base in scan_roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() in exts:
                paths.append(path)
    for path in sorted(paths):
        if path.name in SKIP_FILES:
            continue
        rel_s = str(path.relative_to(ROOT)).replace("\\", "/")
        if any(part in rel_s for part in SKIP_PATH_PARTS):
            continue
        rel = path.relative_to(ROOT)
        for line_no, label, snippet in scan_file(path):
            rel_s = str(rel).replace("\\", "/")
            if is_platform_only(path):
                tier = "platform-only"
            elif is_runtime_shim_ok(rel_s, label):
                tier = "shim-ok"
            else:
                tier = "tenant-risk"
            issues.append((rel_s, line_no, f"[{tier}] {label}", snippet))

    tenant_risk = [x for x in issues if "tenant-risk" in x[2]]
    platform = [x for x in issues if "platform-only" in x[2]]
    shim_ok = [x for x in issues if "shim-ok" in x[2]]
    layout_missing = check_standalone_layouts()

    print(f"=== GM URL Audit ({ROOT.name}) ===")
    print(f"Standalone layouts missing tenant runtime: {len(layout_missing)}")
    for rel in layout_missing:
        print(f"  {rel}")
    print(f"Tenant-risk (review/fix source): {len(tenant_risk)}")
    print(f"Runtime shim OK: {len(shim_ok)}")
    print(f"Platform-only (expected): {len(platform)}")
    for rel, ln, label, snip in tenant_risk[:100]:
        print(f"  {rel}:{ln} {label}")
        try:
            print(f"    {snip}")
        except UnicodeEncodeError:
            print(f"    {snip.encode('ascii', 'replace').decode()}")
    if len(tenant_risk) > 100:
        print(f"  ... +{len(tenant_risk) - 100} more")

    return 1 if (tenant_risk or layout_missing) else 0


if __name__ == "__main__":
    sys.exit(main())
