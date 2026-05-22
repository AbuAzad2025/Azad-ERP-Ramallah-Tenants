#!/usr/bin/env python3
"""تدقيق خرائط الصلاحيات والأدوار — بدون تكرار أو endpoints بلا تعريف."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from permissions_config.endpoint_access import audit_hub_endpoint_coverage
    from permissions_config.permissions import PermissionsRegistry
    from permissions_config.role_policy import validate_roles_registry
    from utils.owner_hubs import PLATFORM_HUB_SECTIONS, TENANT_HUB_SECTIONS

    issues: list[str] = []
    issues.extend(validate_roles_registry())

    for label, sections in (
        ("platform_hub", PLATFORM_HUB_SECTIONS),
        ("tenant_hub", TENANT_HUB_SECTIONS),
    ):
        missing = audit_hub_endpoint_coverage(sections)
        for ep in missing:
            issues.append(f"unmapped_endpoint:{label}:{ep}")

    # تضارب: نفس endpoint بصلاحيتين مختلفتين (لا ينبغي بعد التوحيد)
    from permissions_config.endpoint_access import (
        PLATFORM_OWNER_ENDPOINT_PERMISSIONS,
        TENANT_ENDPOINT_PERMISSIONS,
    )

    overlap = set(TENANT_ENDPOINT_PERMISSIONS) & set(PLATFORM_OWNER_ENDPOINT_PERMISSIONS)
    for ep in overlap:
        t = TENANT_ENDPOINT_PERMISSIONS[ep]
        p = PLATFORM_OWNER_ENDPOINT_PERMISSIONS[ep]
        if t != p:
            issues.append(f"endpoint_perm_conflict:{ep}:{t}!={p}")

    deprecated = [
        name
        for name, data in PermissionsRegistry.ROLES.items()
        if data.get("deprecated") and name in PermissionsRegistry.get_super_roles()
    ]
    if deprecated:
        issues.append(f"deprecated_in_super_roles:{','.join(deprecated)}")

    if issues:
        print("FAIL — permission/role audit:")
        for i in sorted(set(issues)):
            print(f"  - {i}")
        return 1

    print("OK — permission maps and roles registry are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
