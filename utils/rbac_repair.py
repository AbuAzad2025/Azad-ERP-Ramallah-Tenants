"""
تصحيح مستخدمي RBAC وتنظيف الأدوار اليتيمة/الخاطئة في المنصة وكل التينانتات.
"""
from __future__ import annotations

from permissions_config.permissions import PermissionsRegistry
from permissions_config.role_policy import (
    SYSTEM_ROLE_NAMES,
    canonical_role_name_str,
    is_deprecated_role_name,
    is_known_system_role,
)


def _ensure_canonical_role(session, canonical_name: str):
    from models import Role

    name = canonical_role_name_str(canonical_name)
    role = session.query(Role).filter_by(name=name).one_or_none()
    if not role:
        role = Role(name=name)
        session.add(role)
        session.flush()
    return role


def repair_users(session) -> dict:
    """إعادة ربط كل مستخدم بدوره القياسي وتصحيح حسابات النظام."""
    from models import Role, User

    stats = {"users_checked": 0, "users_relinked": 0, "system_flags_set": 0}

    for user in session.query(User).all():
        stats["users_checked"] += 1
        if not user.role_id:
            continue
        role = session.get(Role, user.role_id)
        if not role:
            continue
        old_name = (role.name or "").strip()
        target_name = canonical_role_name_str(old_name)
        if not target_name:
            continue

        if target_name != old_name or is_deprecated_role_name(old_name):
            canonical = _ensure_canonical_role(session, target_name)
            if user.role_id != canonical.id:
                user.role_id = canonical.id
                stats["users_relinked"] += 1

        uname = (user.username or "").strip()
        if uname.upper() == "__OWNER__" or target_name in ("owner", "developer"):
            if not user.is_system_account:
                user.is_system_account = True
                stats["system_flags_set"] += 1

    session.flush()
    return stats


def cleanup_junk_roles(session, *, delete_unused_custom: bool = True) -> dict:
    """حذف أدوار خاطئة/مكررة/يتيمة (بدون مستخدمين)."""
    from sqlalchemy import delete

    from models import Role, User, role_permissions
    from permissions_config.role_policy import JUNK_ROLE_NAMES, JUNK_ROLE_PREFIXES

    stats = {"roles_deleted": 0, "skipped_has_users": 0}

    for role in list(session.query(Role).all()):
        name = (role.name or "").strip()
        if not name:
            continue
        canonical = canonical_role_name_str(name)
        user_count = session.query(User).filter(User.role_id == role.id).count()
        if user_count > 0:
            stats["skipped_has_users"] += 1
            continue

        is_junk = (
            is_deprecated_role_name(name)
            or any(name.startswith(p) for p in JUNK_ROLE_PREFIXES)
            or name in JUNK_ROLE_NAMES
            or name != canonical
            or (delete_unused_custom and not is_known_system_role(canonical))
        )
        if not is_junk:
            continue

        rid = int(role.id)
        session.execute(delete(role_permissions).where(role_permissions.c.role_id == rid))
        session.query(Role).filter(Role.id == rid).delete(synchronize_session=False)
        stats["roles_deleted"] += 1

    session.expire_all()
    session.flush()
    return stats


def repair_schema_rbac(session, *, schema: str = "public", sync_permissions: bool = True) -> dict:
    """تصحيح مستخدمين + تنظيف + مزامنة صلاحيات لـ schema واحد."""
    from utils.role_sync import (
        consolidate_super_roles,
        sync_all_tenant_standard_roles,
        sync_platform_standard_roles,
        sync_privileged_platform_roles,
    )

    user_stats = repair_users(session)
    merge_stats = consolidate_super_roles(session)
    clean_stats = cleanup_junk_roles(session)

    perm_stats = {}
    if sync_permissions:
        is_tenant_schema = (schema or "").strip().lower() not in ("", "public")
        if is_tenant_schema:
            rows = sync_all_tenant_standard_roles(session)
            perm_stats = {"tenant_roles": len(rows)}
        else:
            priv = sync_privileged_platform_roles(session)
            std = sync_platform_standard_roles(session)
            perm_stats = {"privileged": len(priv), "standard": len(std)}

    session.flush()
    return {
        "users": user_stats,
        "super_merge": merge_stats,
        "cleanup": clean_stats,
        "permissions": perm_stats,
    }


def repair_all_schemas(session, *, include_public: bool = True) -> list[dict]:
    """منصة + كل التينانتات."""
    from sqlalchemy import text

    from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path

    results = []

    if include_public:
        session.execute(text("SET search_path TO public"))
        results.append({"schema": "public", "slug": "platform", **repair_schema_rbac(session, schema="public")})

    for slug, schema in iter_tenant_schemas(session):
        if schema.lower() == "public":
            continue
        set_local_search_path(session, schema)
        row = repair_schema_rbac(session, schema=schema)
        row["schema"] = schema
        row["slug"] = slug
        results.append(row)

    session.execute(text("SET search_path TO public"))
    return results
