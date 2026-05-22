#!/usr/bin/env python3
"""
اختبار تكامل شامل على القاعدة الحقيقية + تحسين البيانات القديمة.
تشغيل: python scripts/integration_test_rbac.py [--fix]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_permission_map_audit() -> list[str]:
    from permissions_config.endpoint_access import (
        PLATFORM_OWNER_ENDPOINT_PERMISSIONS,
        TENANT_ENDPOINT_PERMISSIONS,
        audit_hub_endpoint_coverage,
    )
    from permissions_config.permissions import PermissionsRegistry
    from permissions_config.role_policy import validate_roles_registry
    from utils.owner_hubs import PLATFORM_HUB_SECTIONS, TENANT_HUB_SECTIONS

    issues: list[str] = list(validate_roles_registry())
    for label, sections in (
        ("platform_hub", PLATFORM_HUB_SECTIONS),
        ("tenant_hub", TENANT_HUB_SECTIONS),
    ):
        for ep in audit_hub_endpoint_coverage(sections):
            issues.append(f"unmapped_endpoint:{label}:{ep}")
    overlap = set(TENANT_ENDPOINT_PERMISSIONS) & set(PLATFORM_OWNER_ENDPOINT_PERMISSIONS)
    for ep in overlap:
        if TENANT_ENDPOINT_PERMISSIONS[ep] != PLATFORM_OWNER_ENDPOINT_PERMISSIONS[ep]:
            issues.append(f"endpoint_perm_conflict:{ep}")
    deprecated = [
        n
        for n, d in PermissionsRegistry.ROLES.items()
        if d.get("deprecated") and n in PermissionsRegistry.get_super_roles()
    ]
    if deprecated:
        issues.append(f"deprecated_in_super_roles:{','.join(deprecated)}")
    return issues


def _audit_schema(session, label: str, schema: str) -> dict:
    from sqlalchemy import text

    from models import Role, User
    from permissions_config.permissions import PermissionsRegistry
    from permissions_config.role_policy import (
        canonical_role_name_str,
        is_deprecated_role_name,
        is_known_system_role,
    )
    from utils.dashboard_routing import preferred_dashboard_endpoint, user_can_access_endpoint
    from utils.tenant_fiscal_schema import set_local_search_path

    if schema.lower() == "public":
        session.execute(text("SET search_path TO public"))
    else:
        set_local_search_path(session, schema)

    issues: list[str] = []
    fixes: list[str] = []
    roles_by_id = {r.id: r for r in session.query(Role).all()}

    for u in session.query(User).all():
        role = roles_by_id.get(u.role_id)
        rn = (role.name if role else "") or ""
        can = canonical_role_name_str(rn)
        if not u.role_id:
            issues.append(f"user_no_role:{u.username}")
        elif rn != can:
            issues.append(f"user_noncanonical_role:{u.username}:{rn}->{can}")
        if (u.username or "").strip().upper() in ("__OWNER__",) or can in ("owner", "developer"):
            if not u.is_system_account:
                issues.append(f"system_flag_missing:{u.username}")
        if can == "mechanic" and u.has_permission("access_dashboard"):
            issues.append(f"mechanic_has_access_dashboard:{u.username}")
        try:
            ep = preferred_dashboard_endpoint(u, label if schema.lower() != "public" else None)
            if ep == "auth.login" and u.is_active:
                issues.append(f"no_home_endpoint:{u.username}")
            elif ep and not user_can_access_endpoint(u, ep):
                issues.append(f"home_inaccessible:{u.username}:{ep}")
        except Exception as exc:
            issues.append(f"routing_error:{u.username}:{exc}")

    for r in session.query(Role).all():
        name = (r.name or "").strip()
        uc = session.query(User).filter(User.role_id == r.id).count()
        if is_deprecated_role_name(name) or name.startswith("systemroles."):
            issues.append(f"junk_role:{name}:users={uc}")
        elif name != canonical_role_name_str(name) and uc == 0:
            issues.append(f"orphan_duplicate_role:{name}")
        elif not is_known_system_role(canonical_role_name_str(name)) and uc == 0:
            issues.append(f"orphan_custom_role:{name}")
        if name == "mechanic" or canonical_role_name_str(name) == "mechanic":
            codes = {str(p.code or "").lower() for p in (r.permissions or [])}
            if "access_dashboard" in codes:
                issues.append(f"mechanic_role_has_dashboard_perm:{label}")

    reg = PermissionsRegistry.get_role_permissions("mechanic")
    if "access_dashboard" in reg:
        issues.append(f"registry_mechanic_has_dashboard:{label}")

    return {
        "label": label,
        "schema": schema,
        "users": session.query(User).count(),
        "roles": session.query(Role).count(),
        "issues": issues,
        "fixes": fixes,
    }


def _improve_old_data(session, schema: str, *, apply: bool) -> list[str]:
    """تحسين بيانات قديمة: أعلام النظام، تفعيل المالك، إزالة super، مزامنة صلاحيات."""
    from sqlalchemy import text

    from models import Role, User
    from permissions_config.role_policy import canonical_role_name_str
    from utils.rbac_repair import cleanup_junk_roles, repair_schema_rbac, repair_users
    from utils.role_sync import consolidate_super_roles

    actions: list[str] = []
    if schema.lower() == "public":
        session.execute(text("SET search_path TO public"))

    for u in session.query(User).all():
        role = session.get(Role, u.role_id) if u.role_id else None
        can = canonical_role_name_str(getattr(role, "name", "") or "")
        uname = (u.username or "").strip()

        if can in ("owner", "developer") or uname.upper() == "__OWNER__":
            if not u.is_system_account:
                if apply:
                    u.is_system_account = True
                actions.append(f"set_system_account:{uname}")
            if u.is_active is False and uname.lower() in ("owner", "__owner__", "developer"):
                if apply:
                    u.is_active = True
                actions.append(f"activate_system_user:{uname}")

    if apply:
        actions.append(f"users:{repair_users(session)}")
        merge = consolidate_super_roles(session)
        if merge.get("removed_role") or merge.get("migrated_users"):
            actions.append(f"super_merge:{merge}")
        actions.append(f"cleanup:{cleanup_junk_roles(session)}")
        repair_schema_rbac(session, schema=schema)
        session.flush()
    return actions


def run(*, fix: bool = False) -> int:

    from app import create_app
    from extensions import db
    from utils.tenant_fiscal_schema import iter_tenant_schemas

    app = create_app()
    all_issues: list[str] = []
    report: list[dict] = []

    with app.app_context():
        map_issues = _run_permission_map_audit()
        all_issues.extend(map_issues)

        schemas = [("platform", "public")]
        for slug, sch in iter_tenant_schemas(db.session):
            if sch.lower() != "public":
                schemas.append((slug, sch))

        for label, schema in schemas:
            row = _audit_schema(db.session, label, schema)
            report.append(row)
            all_issues.extend(f"{label}/{schema}:{x}" for x in row["issues"])
            fixes = _improve_old_data(db.session, schema, apply=fix)
            row["fixes"] = fixes
            if fix:
                print(f"[FIX] {label}/{schema}: {len(fixes)} actions")

        if fix:
            db.session.commit()
            from utils import clear_role_permission_cache, clear_users_cache_by_role
            from models import Role

            for r in Role.query.all():
                try:
                    clear_role_permission_cache(r.id)
                    clear_users_cache_by_role(r.id)
                except Exception:
                    pass
            print("Committed improvements.")
            report = []
            all_issues.clear()
            map_issues = _run_permission_map_audit()
            all_issues.extend(map_issues)
            for label, schema in schemas:
                row = _audit_schema(db.session, label, schema)
                report.append(row)
                all_issues.extend(f"{label}/{schema}:{x}" for x in row["issues"])

        print("\n=== RBAC Integration Report ===")
        for row in report:
            status = "OK" if not row["issues"] else f"{len(row['issues'])} issue(s)"
            print(f"  {row['label']}/{row['schema']}: users={row['users']} roles={row['roles']} -> {status}")
            for issue in row["issues"][:8]:
                print(f"      - {issue}")
            if len(row["issues"]) > 8:
                print(f"      ... +{len(row['issues']) - 8} more")

        if map_issues:
            print("\n  Permission map issues:")
            for i in map_issues:
                print(f"      - {i}")

        # تقرير توجيه المستخدمين
        print("\n=== User home routing ===")
        from sqlalchemy import text

        from models import User
        from utils.dashboard_routing import preferred_dashboard_endpoint
        from utils.tenant_fiscal_schema import set_local_search_path

        for label, schema in schemas:
            if schema.lower() == "public":
                db.session.execute(text("SET search_path TO public"))
                slug = None
            else:
                set_local_search_path(db.session, schema)
                slug = label
            for u in User.query.filter(User.is_active.is_(True)).order_by(User.username).all():
                ep = preferred_dashboard_endpoint(u, slug)
                print(f"  {label}: {u.username} ({u.role.name if u.role else '-'}) -> {ep}")

        if all_issues:
            print(f"\nFAIL — {len(all_issues)} total issue(s)")
            if not fix:
                print("Re-run with --fix to apply data improvements.")
            return 1

        print("\nPASS — all schemas consistent.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true", help="تطبيق تحسينات البيانات تلقائياً")
    args = parser.parse_args()
    return run(fix=bool(args.fix))


if __name__ == "__main__":
    raise SystemExit(main())
