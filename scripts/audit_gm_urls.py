#!/usr/bin/env python3
"""
فحص روابط مطلقة قد تكسر مسار التينانت /t/<slug>/.
تشغيل: python scripts/audit_gm_urls.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# أنماط مشبوهة في قوالب و JS (استثناءات منصة security/advanced)
PATTERNS = [
    (re.compile(r"""href\s*=\s*["']/(?!static|t/)[a-z]""", re.I), "href=/absolute"),
    (re.compile(r"""fetch\s*\(\s*["']/(?!static)[a-z]""", re.I), "fetch(/absolute)"),
    (re.compile(r"""submitPost\s*\(\s*["']/"""), "submitPost(/absolute)"),
    (re.compile(r"""window\.location\.href\s*=\s*["']/"""), "location.href=/absolute"),
    (re.compile(r"""secureFetch\s*\(\s*["']/(advanced|security)/"""), "secureFetch platform"),
]

PLATFORM_ONLY_DIRS = {
    "templates/security",
    "templates/advanced",
    "templates/ai",
    "static/js/security",
}
# fetch() المطلق يُصلَح تلقائياً عبر intercept في base.html
FETCH_SHIM_OK = {
    "static/js/payments.js",
    "static/js/payment_form.js",
    "static/js/reporting.js",
    "static/js/shop.js",
    "templates/barcode_scanner",
    "templates/ledger/",
    "templates/vendors/",
    "templates/warehouses/",
    "templates/payments/",
    "templates/shop/",
    "static/js/module_specific_enhancements.js",
}

SKIP_FILES = {"audit_gm_urls.py"}
SKIP_PATH_PARTS = (
    "static/adminlte",
    "static/plugins",
    "node_modules",
    ".venv",
)


def is_platform_only(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(s.startswith(str(ROOT / d).replace("\\", "/")) for d in PLATFORM_ONLY_DIRS)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        if "gmPath(" in line or "url_for(" in line or "ledger_api_base" in line:
            continue
        if "{{ url_for" in line or "{{ gm_path" in line:
            continue
        if "submitPost(" in line and "function(id){ submitPost" in line:
            continue  # submitPost يضيف GM_PREFIX داخلياً
        for rx, label in PATTERNS:
            if rx.search(line):
                hits.append((i, label, line.strip()[:120]))
                break
    return hits


def main() -> int:
    exts = {".html", ".js", ".jinja", ".jinja2"}
    issues: list[tuple[str, int, str, str]] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix.lower() not in exts:
            continue
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
            elif label == "fetch(/absolute)" and any(rel_s.startswith(p) for p in FETCH_SHIM_OK):
                tier = "shim-ok"
            else:
                tier = "tenant-risk"
            issues.append((rel_s, line_no, f"[{tier}] {label}", snippet))

    tenant_risk = [x for x in issues if "tenant-risk" in x[2]]
    platform = [x for x in issues if "platform-only" in x[2]]
    shim_ok = [x for x in issues if "shim-ok" in x[2]]

    print(f"=== GM URL Audit ({ROOT.name}) ===")
    print(f"Tenant-risk (needs fix): {len(tenant_risk)}")
    print(f"Fetch shim OK (runtime): {len(shim_ok)}")
    for rel, ln, label, snip in tenant_risk[:80]:
        print(f"  {rel}:{ln} {label}")
        try:
            print(f"    {snip}")
        except UnicodeEncodeError:
            print(f"    {snip.encode('ascii', 'replace').decode()}")
    if len(tenant_risk) > 80:
        print(f"  ... +{len(tenant_risk) - 80} more")

    print(f"\nPlatform-only (informational): {len(platform)}")
    for rel, ln, label, snip in platform[:30]:
        print(f"  {rel}:{ln} {label}")
    if len(platform) > 30:
        print(f"  ... +{len(platform) - 30} more")

    return 1 if tenant_risk else 0


if __name__ == "__main__":
    sys.exit(main())
