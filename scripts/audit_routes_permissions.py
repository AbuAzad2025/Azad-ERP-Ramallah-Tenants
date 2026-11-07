#!/usr/bin/env python
"""Audit Flask routes vs permissions registry. Run: python scripts/audit_routes_permissions.py"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PUBLIC_FILE_HINTS = (
    "auth.py",
    "health.py",
    "user_guide.py",
    "pricing.py",
    "other_systems.py",
)


def _load_registry_codes() -> set[str]:
    from permissions_config.enums import SystemPermissions

    return {p.value for p in SystemPermissions}


def _scan_routes_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    routes: list[dict] = []
    # Match decorator block immediately before def
    pattern = re.compile(
        r"((?:^[ \t]*@\S[^\n]*\n)+)^[ \t]*def\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        dec_block, func_name = m.group(1), m.group(2)
        dec_lines = dec_block.strip().splitlines()
        has_route = any(
            re.search(r"@\w+\.(route|get|post|put|delete|patch)\(", d) for d in dec_lines
        )
        if not has_route:
            continue
        has_login = any("login_required" in d for d in dec_lines)
        perms = []
        for d in dec_lines:
            pm = re.search(r"permission_required\(([^)]+)\)", d)
            if pm:
                perms.append(pm.group(1).strip())
        line_no = text[: m.start()].count("\n") + 1
        routes.append(
            {
                "file": str(path.relative_to(ROOT)),
                "line": line_no,
                "func": func_name,
                "login": has_login,
                "perms": perms,
            }
        )
    return routes


def main() -> int:
    registry = _load_registry_codes()
    route_perm_literals: set[str] = set()
    all_routes: list[dict] = []

    for path in sorted((ROOT / "routes").glob("*.py")):
        all_routes.extend(_scan_routes_file(path))
        for m in re.finditer(
            r"SystemPermissions\.([A-Z_]+)",
            path.read_text(encoding="utf-8", errors="ignore"),
        ):
            from permissions_config.enums import SystemPermissions

            attr = m.group(1)
            if hasattr(SystemPermissions, attr):
                route_perm_literals.add(getattr(SystemPermissions, attr).value)

    unprotected: list[dict] = []
    login_only: list[dict] = []
    protected: list[dict] = []

    for r in all_routes:
        if r["login"] and r["perms"]:
            protected.append(r)
        elif r["login"]:
            login_only.append(r)
        else:
            unprotected.append(r)

    suspicious = [
        r
        for r in unprotected
        if not any(h in r["file"] for h in PUBLIC_FILE_HINTS)
        and r["func"] not in ("catalog", "product_detail", "gateway_webhook", "favicon")
    ]

    print("=" * 60)
    print("ROUTE PERMISSIONS AUDIT")
    print("=" * 60)
    print(f"Total route handlers scanned: {len(all_routes)}")
    print(f"  Protected (login + permission): {len(protected)}")
    print(f"  Login-only (ACL may still apply): {len(login_only)}")
    print(f"  Unprotected: {len(unprotected)}")
    print()

    print(f"Unprotected outside public modules: {len(suspicious)}")
    for r in suspicious[:30]:
        print(f"  {r['file']}:{r['line']} {r['func']}")
    if len(suspicious) > 30:
        print(f"  ... and {len(suspicious) - 30} more")
    print()

    by_file: dict[str, int] = defaultdict(int)
    for r in login_only:
        by_file[r["file"]] += 1
    print("Login-only routes by file (top 15):")
    for f, n in sorted(by_file.items(), key=lambda x: -x[1])[:15]:
        print(f"  {f}: {n}")
    print()

    missing_registry = sorted(route_perm_literals - registry)
    unused_registry = sorted(
        registry
        - route_perm_literals
        - {"manage_saas", "restore_archive", "manage_mobile_app", "manage_tenants"}
    )

    if missing_registry:
        print("Enum permissions used in routes but missing from enum (unexpected):")
        for c in missing_registry:
            print(f"  - {c}")
    else:
        print("All route SystemPermissions exist in enum.")
    print()

    print("Registry permissions not referenced in routes (sample):")
    for c in unused_registry[:25]:
        print(f"  - {c}")
    if len(unused_registry) > 25:
        print(f"  ... and {len(unused_registry) - 25} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
