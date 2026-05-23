#!/usr/bin/env python3
"""
تدقيق مسارات Flask: unprotected / login-only / ACL / صلاحيات registry.
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# مسارات عامة مقصودة (بدون تسجيل دخول)
INTENTIONAL_PUBLIC_PREFIXES = (
    "/static/",
    "/auth/login",
    "/auth/register",
    "/auth/forgot",
    "/auth/reset",
    "/health/ping",
    "/health/ready",
    "/health/live",
    "/shop/catalog",
    "/shop/product",
    "/shop/webhook",
)

INTENTIONAL_PUBLIC_EXACT = {
    "auth.login",
    "auth.register",
    "auth.forgot_password",
    "auth.reset_password",
    "health.ping",
    "health.readiness",
    "health.liveness",
}

# blueprints بدون attach_acl في app — حماية يدوية
NO_ACL_BLUEPRINTS = frozenset(
    {
        "auth",
        "health",
        "security",
        "advanced",
        "security_control",
        "security_expenses",
        "ai",
        "ai_admin",
        "user_guide",
        "other_systems",
        "pricing",
        "fiscal_periods",
        "performance",
        "recurring",
        "archive_routes",
    }
)

LOGIN_ONLY_BLUEPRINTS = frozenset({"main"})  # read_perm=None write_perm=None


def _scan_route_files_for_permissions() -> dict[str, set[str]]:
    """استخراج SystemPermissions.X.value و permission_required('...') من routes/."""
    routes_dir = ROOT / "routes"
    perms_from_decorator: set[str] = set()
    perms_from_enum: set[str] = set()
    perm_re = re.compile(
        r"permission_required\s*\(\s*SystemPermissions\.(\w+)",
    )
    enum_re = re.compile(r"SystemPermissions\.(\w+)\.value")
    str_perm_re = re.compile(
        r"permission_required\s*\(\s*['\"]([a-z0-9_]+)['\"]",
    )
    require_any_re = re.compile(
        r"require_any_permission\s*\(\s*\(([^)]+)\)",
    )

    for py in routes_dir.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in perm_re.finditer(text):
            perms_from_enum.add(m.group(1).lower())
        for m in enum_re.finditer(text):
            perms_from_enum.add(m.group(1).lower())
        for m in str_perm_re.finditer(text):
            perms_from_decorator.add(m.group(1).lower())
        for m in require_any_re.finditer(text):
            chunk = m.group(1)
            for sm in re.finditer(r"SystemPermissions\.(\w+)", chunk):
                perms_from_enum.add(sm.group(1).lower())
            for sm in re.finditer(r"['\"]([a-z0-9_]+)['\"]", chunk):
                perms_from_decorator.add(sm.group(1).lower())

    return {
        "decorator_enum": perms_from_enum,
        "decorator_string": perms_from_decorator,
    }


def _view_protection(view_func) -> dict:
    """تحليل decorators على دالة العرض."""
    has_login = False
    explicit_perms: list[str] = []
    if view_func is None:
        return {"login": False, "perms": []}
    for qualname in getattr(view_func, "__qualname__", "").split("."):
        pass
    # unwrap nested wrappers
    f = view_func
    seen = set()
    while f and id(f) not in seen:
        seen.add(id(f))
        name = getattr(f, "__name__", "")
        if name == "login_required" or "login_required" in str(getattr(f, "__wrapped__", "")):
            has_login = True
        closure = getattr(f, "__closure__", None) or ()
        for cell in closure:
            try:
                val = cell.cell_contents
                if isinstance(val, str) and "_" in val:
                    pass
            except ValueError:
                pass
        f = getattr(f, "__wrapped__", None)

    # inspect decorators on __wrapped__ chain
    f = view_func
    seen = set()
    while f and id(f) not in seen:
        seen.add(id(f))
        qual = getattr(f, "__qualname__", "")
        mod = getattr(f, "__module__", "")
        fname = getattr(f, "__name__", "")
        if fname in ("login_required", "_login_required"):
            has_login = True
        # permission_required stores perm in closure sometimes
        defaults = getattr(f, "__defaults__", ()) or ()
        for d in defaults:
            if isinstance(d, str) and len(d) < 80 and d.replace("_", "").isalnum():
                if d.count("_") >= 1:
                    explicit_perms.append(d)
        f = getattr(f, "__wrapped__", None)

    return {"login": has_login, "perms": explicit_perms}


def main() -> int:
    from app import create_app
    from permissions_config.blueprint_guards import get_blueprint_guard_config
    from permissions_config.endpoint_access import (
        PLATFORM_OWNER_ENDPOINT_PERMISSIONS,
        TENANT_ENDPOINT_PERMISSIONS,
        permission_for_endpoint,
    )
    from permissions_config.enums import SystemPermissions
    from permissions_config.permissions import PermissionsRegistry

    app = create_app()
    acl_map = {name: opts for name, opts in get_blueprint_guard_config()}

    registry_codes = {c.lower() for c in PermissionsRegistry.get_all_permission_codes()}
    enum_values = {p.value.lower() for p in SystemPermissions}

    scanned = _scan_route_files_for_permissions()
    used_in_routes = scanned["decorator_enum"] | scanned["decorator_string"]
    # map enum member names to values
    for member in SystemPermissions:
        if member.name.lower() in used_in_routes:
            used_in_routes.add(member.value.lower())
    used_in_routes = {p for p in used_in_routes if not p.isupper()}

    # normalize: enum names -> values
    normalized_used: set[str] = set()
    for p in scanned["decorator_enum"]:
        try:
            normalized_used.add(getattr(SystemPermissions, p.upper()).value.lower())
        except AttributeError:
            normalized_used.add(p.lower())
    for p in scanned["decorator_string"]:
        normalized_used.add(p.lower())
    for p in scanned["decorator_enum"]:
        if hasattr(SystemPermissions, p.upper()):
            normalized_used.add(getattr(SystemPermissions, p.upper()).value.lower())

    # re-scan with .value in files
    routes_dir = ROOT / "routes"
    for py in routes_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"SystemPermissions\.(\w+)\.value", text):
            try:
                normalized_used.add(getattr(SystemPermissions, m.group(1)).value.lower())
            except AttributeError:
                pass

    used_in_endpoint_maps = {
        v.lower() for v in TENANT_ENDPOINT_PERMISSIONS.values()
    } | {v.lower() for v in PLATFORM_OWNER_ENDPOINT_PERMISSIONS.values()}
    used_in_acl = set()
    for opts in acl_map.values():
        for k in ("read_perm", "write_perm"):
            v = opts.get(k)
            if v:
                used_in_acl.add(str(v).lower())

    all_used = normalized_used | used_in_acl | used_in_endpoint_maps

    unused_registry = sorted(registry_codes - all_used)
    missing_registry = sorted(all_used - registry_codes - enum_values)

    unprotected: list[dict] = []
    login_only: list[dict] = []
    acl_protected: list[dict] = []
    explicit_perm: list[dict] = []
    platform_manual: list[dict] = []

    route_dupes: dict[tuple, list[str]] = defaultdict(list)

    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            methods = sorted(m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"})
            path = rule.rule
            ep = rule.endpoint
            bp_name = ep.split(".")[0] if "." in ep else ep

            key = (path.rstrip("/") or "/", tuple(methods))
            route_dupes[key].append(ep)

            view = app.view_functions.get(ep)
            vf = _view_protection(view)

            acl_opts = None
            for acl_bp, opts in acl_map.items():
                if acl_bp.replace("_bp", "") == bp_name or acl_bp == f"{bp_name}_bp":
                    acl_opts = opts
                    break
            if acl_opts is None and bp_name.endswith("_bp"):
                acl_opts = acl_map.get(bp_name)

            classification = "unknown"
            detail = ""

            is_public_exempt = (
                ep in INTENTIONAL_PUBLIC_EXACT
                or any(path.startswith(p) for p in INTENTIONAL_PUBLIC_PREFIXES)
            )

            if bp_name in ("security", "advanced", "security_control", "security_expenses"):
                classification = "platform_manual"
                detail = "before_request: platform_console + route decorators"
                platform_manual.append({"endpoint": ep, "path": path, "methods": methods})
            elif bp_name in NO_ACL_BLUEPRINTS and bp_name not in ("security", "advanced"):
                if is_public_exempt or (not vf["login"] and not vf["perms"]):
                    if ep in ("health.ping", "health.readiness", "health.liveness") or path.startswith("/auth/"):
                        classification = "public_intentional"
                    else:
                        classification = "unprotected"
                        unprotected.append({"endpoint": ep, "path": path, "methods": methods, "bp": bp_name})
                elif vf["login"] and not vf["perms"]:
                    classification = "login_only"
                    login_only.append({"endpoint": ep, "path": path, "methods": methods, "bp": bp_name})
                elif vf["perms"]:
                    classification = "explicit_perm"
                    explicit_perm.append({"endpoint": ep, "path": path, "perms": vf["perms"]})
                else:
                    classification = "unprotected_review"
                    unprotected.append({"endpoint": ep, "path": path, "methods": methods, "bp": bp_name, "note": "no_acl_bp"})
            elif acl_opts:
                rp = acl_opts.get("read_perm")
                wp = acl_opts.get("write_perm")
                pub = acl_opts.get("public_read")
                if rp is None and wp is None:
                    if vf["login"] or True:  # ACL still requires login
                        classification = "login_only_acl"
                        login_only.append(
                            {
                                "endpoint": ep,
                                "path": path,
                                "methods": methods,
                                "bp": bp_name,
                                "note": "ACL login; read/write perm None",
                            }
                        )
                elif pub and "GET" in methods:
                    classification = "acl_public_read"
                else:
                    classification = "acl"
                    acl_protected.append(
                        {
                            "endpoint": ep,
                            "path": path,
                            "read": rp,
                            "write": wp,
                        }
                    )
            elif vf["perms"]:
                classification = "explicit_perm"
                explicit_perm.append({"endpoint": ep, "path": path})

            if vf["perms"] and classification not in ("explicit_perm",):
                explicit_perm.append({"endpoint": ep, "path": path, "extra": vf["perms"]})

    # duplicate routes (same path+methods, different endpoints)
    dup_routes = []
    for key, eps in route_dupes.items():
        if len(set(eps)) > 1:
            dup_routes.append({"path": key[0], "methods": list(key[1]), "endpoints": sorted(set(eps))})

    # duplicate endpoint names pointing to different paths
    from utils.comprehensive_audit import audit_endpoints

    ep_audit = audit_endpoints(app)

    # hub unmapped
    from permissions_config.endpoint_access import audit_hub_endpoint_coverage
    from utils.owner_hubs import PLATFORM_HUB_SECTIONS, TENANT_HUB_SECTIONS

    hub_missing = []
    for label, sections in (("platform", PLATFORM_HUB_SECTIONS), ("tenant", TENANT_HUB_SECTIONS)):
        for ep in audit_hub_endpoint_coverage(sections):
            hub_missing.append(f"{label}:{ep}")

    # overlap tenant/platform maps
    overlap_conflict = []
    overlap = set(TENANT_ENDPOINT_PERMISSIONS) & set(PLATFORM_OWNER_ENDPOINT_PERMISSIONS)
    for ep in overlap:
        if TENANT_ENDPOINT_PERMISSIONS[ep] != PLATFORM_OWNER_ENDPOINT_PERMISSIONS[ep]:
            overlap_conflict.append(ep)

    # print report
    print("=" * 72)
    print("تقرير تدقيق المسارات والصلاحيات")
    print("=" * 72)
    print(f"\nإجمالي المسارات: {sum(1 for _ in app.url_map.iter_rules() if _.endpoint != 'static')}")
    print(f"صلاحيات في Registry: {len(registry_codes)}")
    print(f"صلاحيات مستخدمة (تقدير): {len(all_used)}")

    print("\n## 1) مسارات بدون حماية (تحتاج مراجعة)")
  # filter intentional
    review_unprot = [
        u for u in unprotected
        if u["endpoint"] not in INTENTIONAL_PUBLIC_EXACT
        and not any(u["path"].startswith(p) for p in INTENTIONAL_PUBLIC_PREFIXES)
    ]
    if not review_unprot:
        print("  (لا شيء حرج — أو الكل مقصود)")
    for u in review_unprot[:40]:
        print(f"  - {u['endpoint']}  {u['methods']}  {u['path']}  bp={u.get('bp')}")
    if len(review_unprot) > 40:
        print(f"  ... و {len(review_unprot) - 40} أخرى")

    intentional_public = [
        u for u in unprotected
        if u["endpoint"] in INTENTIONAL_PUBLIC_EXACT
        or any(u["path"].startswith(p) for p in INTENTIONAL_PUBLIC_PREFIXES)
    ]
    print(f"\n  مقصود (عام): {len(intentional_public)} مسار — login/register/health ping/shop public")

    print("\n## 2) login-only (مسجّل دخول بدون صلاحية محددة)")
    print(f"  العدد: {len(login_only)} (أبرزها blueprint main: read_perm=None)")
    by_bp = defaultdict(int)
    for item in login_only:
        by_bp[item.get("bp", "?")] += 1
    for bp, n in sorted(by_bp.items(), key=lambda x: -x[1])[:15]:
        print(f"    {bp}: {n}")
    print("  هل تحتاج صلاحيات؟")
    print("    - main/dashboard: نعم — يُفضّل ACCESS_DASHBOARD (موجود على بعض المسارات صراحة)")
    print("    - advanced/*: محمي بـ platform owner role على مستوى before_request (ليس PBAC دقيق)")
    print("    - ai/shop public_read: مقصود للزبائن")

    print("\n## 3) تكرار مسارات (نفس path+methods → endpoints متعددة)")
    allowed = {("/sales", ("GET",)), ("/reports", ("GET",)), ("/shipments", ("GET",)), ("/barcode/check-product", ("GET",))}
    serious_dupes = []
    for d in dup_routes:
        k = (d["path"], tuple(d["methods"]))
        if k not in allowed:
            serious_dupes.append(d)
    print(f"  إجمالي التكرارات: {len(dup_routes)} (مسموح في app: {len(allowed)})")
    for d in serious_dupes[:20]:
        print(f"  - {d['path']} {d['methods']} -> {d['endpoints']}")
    for iss in ep_audit.get("issues", [])[:10]:
        print(f"  - {iss.get('msg')}")

    print("\n## 4) صلاحيات مستخدمة في routes وغير موجودة في Registry")
    if missing_registry:
        for p in missing_registry[:30]:
            print(f"  - {p}")
    else:
        print("  لا يوجد — جيد")

    print("\n## 5) صلاحيات في Registry غير مستخدمة (routes/ACL/hub maps)")
    print(f"  العدد: {len(unused_registry)}")
    for p in unused_registry[:35]:
        print(f"  - {p}")
    if len(unused_registry) > 35:
        print(f"  ... و {len(unused_registry) - 35}")

    print("\n## 6) Hub endpoints بلا تعريف في endpoint_access")
    if hub_missing:
        for h in hub_missing:
            print(f"  - {h}")
    else:
        print("  لا يوجد")

    if overlap_conflict:
        print("\n## 7) تضارب tenant/platform على نفس endpoint")
        for ep in overlap_conflict:
            print(f"  - {ep}")

    print("\n## 8) Blueprints بدون attach_acl (حماية يدوية)")
    for bp in sorted(NO_ACL_BLUEPRINTS):
        print(f"  - {bp}")

    exit_code = 0
    if review_unprot or serious_dupes or missing_registry or hub_missing:
        exit_code = 1
    print("\n" + ("FAIL — راجع البنود أعلاه" if exit_code else "OK — لا مشاكل حرجة في الفحص الآلي"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
