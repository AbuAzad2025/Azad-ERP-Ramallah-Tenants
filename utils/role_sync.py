"""
مزامنة أدوار النظام مع PermissionsRegistry ودمج المرادفات (super → super_admin).
"""
from __future__ import annotations

from permissions_config.permissions import PermissionsRegistry
from permissions_config.role_policy import (
    CANONICAL_SUPER_ROLE,
    TENANT_SYNC_STANDARD_ROLES,
    canonical_role_name_str,
    is_deprecated_role_name,
)


def _role_key_to_name(role_key) -> str:
    if hasattr(role_key, "value"):
        return str(role_key.value).strip().lower()
    return canonical_role_name_str(str(role_key))


def registry_permission_codes(role_name: str) -> set[str]:
    name = canonical_role_name_str(role_name)
    if name not in PermissionsRegistry.ROLES:
        return set()
    return {str(c).strip().lower() for c in PermissionsRegistry.get_role_permissions(name) if c}


def _assign_role_permissions(session, role, codes: set[str]) -> int:
    from sqlalchemy import delete, insert

    from models import Permission, role_permissions

    code_set = {str(c).strip().lower() for c in (codes or set()) if c}
    perms = [
        p
        for p in session.query(Permission).all()
        if str(getattr(p, "code", "") or "").strip().lower() in code_set
    ]
    session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
    if perms:
        session.execute(
            insert(role_permissions),
            [{"role_id": role.id, "permission_id": p.id} for p in perms],
        )
    session.expire(role, ["permissions"])
    session.flush()
    return len(perms)


def consolidate_super_roles(session) -> dict:
    """
    دمج دور super في super_admin: نقل المستخدمين ثم حذف super من DB.
    """
    from models import Role, User

    legacy_name = "super"
    target_name = CANONICAL_SUPER_ROLE
    stats = {"migrated_users": 0, "removed_role": False, "skipped": False}

    legacy = session.query(Role).filter_by(name=legacy_name).one_or_none()
    target = session.query(Role).filter_by(name=target_name).one_or_none()
    if not legacy:
        stats["skipped"] = True
        return stats
    if not target:
        target = Role(name=target_name, description="المدير الأعلى (موحّد)")
        session.add(target)
        session.flush()

    migrated = (
        session.query(User)
        .filter(User.role_id == legacy.id)
        .update({User.role_id: target.id}, synchronize_session=False)
    )
    stats["migrated_users"] = int(migrated or 0)

    codes = registry_permission_codes(target_name)
    if codes:
        _assign_role_permissions(session, target, codes)

    remaining = session.query(User).filter(User.role_id == legacy.id).count()
    if remaining == 0:
        session.delete(legacy)
        stats["removed_role"] = True
    session.flush()
    return stats


_PLATFORM_SYNC_SKIP = frozenset({"owner", "developer", "super_admin", "super"})


_PRIVILEGED_PLATFORM_ROLES = frozenset({"owner", "developer", "super_admin"})


def sync_privileged_platform_roles(session) -> list[dict]:
    """مزامنة owner / developer / super_admin (صلاحيات * مع استثناءات)."""
    from models import Permission, Role, role_permissions
    from sqlalchemy import delete, insert

    out = []
    all_perms = session.query(Permission).all()
    for role_name in sorted(_PRIVILEGED_PLATFORM_ROLES):
        role = session.query(Role).filter_by(name=role_name).one_or_none()
        if not role:
            role = Role(name=role_name)
            session.add(role)
            session.flush()
        info = PermissionsRegistry.ROLES.get(role_name, {})
        exclude = {PermissionsRegistry.permission_code_str(x) for x in info.get("exclude", [])}
        exclude.discard("")
        if info.get("permissions") == "*":
            desired = [p for p in all_perms if str(p.code or "").strip().lower() not in exclude]
        else:
            codes = registry_permission_codes(role_name)
            desired = [p for p in all_perms if str(p.code or "").strip().lower() in codes]
        session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
        if desired:
            session.execute(
                insert(role_permissions),
                [{"role_id": role.id, "permission_id": p.id} for p in desired],
            )
        session.expire(role, ["permissions"])
        session.flush()
        out.append({"role": role_name, "permissions": len(desired)})
    return out


def sync_platform_standard_roles(session) -> list[dict]:
    """مزامنة admin/manager/staff/mechanic/... على المنصة من السجل."""
    from models import Role

    out = []
    for role_key in sorted(PermissionsRegistry.ROLES.keys(), key=lambda k: _role_key_to_name(k)):
        role_name = _role_key_to_name(role_key)
        if role_name in _PLATFORM_SYNC_SKIP:
            continue
        info = PermissionsRegistry.ROLES.get(role_key) or PermissionsRegistry.ROLES.get(role_name, {})
        if info.get("deprecated") or is_deprecated_role_name(role_name):
            continue
        role = session.query(Role).filter_by(name=role_name).one_or_none()
        if not role:
            role = Role(name=role_name)
            session.add(role)
            session.flush()
        codes = registry_permission_codes(role_name)
        count = _assign_role_permissions(session, role, codes)
        out.append({"role": role_name, "permissions": count})
    return out


def sync_tenant_role_from_registry(session, role_name: str) -> dict:
    """مزامنة دور واحد داخل schema التينانت (مع استبعاد صلاحيات المنصة)."""
    from utils.tenant_permissions import (
        filter_permissions_for_tenant,
        permission_codes_for_tenant_owner,
        sync_tenant_owner_role_permissions,
    )

    name = canonical_role_name_str(role_name)
    if name == "owner":
        return sync_tenant_owner_role_permissions(session)

    from models import Role

    role = session.query(Role).filter_by(name=name).one_or_none()
    if not role:
        return {"role": name, "skipped": True, "reason": "role_missing"}

    if name in PermissionsRegistry.ROLES and PermissionsRegistry.ROLES[name].get("permissions") == "*":
        codes = set(permission_codes_for_tenant_owner())
    else:
        codes = filter_permissions_for_tenant(registry_permission_codes(name))

    count = _assign_role_permissions(session, role, codes)
    return {"role": name, "permissions": count}


def ensure_standard_roles_exist(session, role_names: tuple[str, ...] | None = None) -> None:
    from models import Role

    names = role_names or TENANT_SYNC_STANDARD_ROLES
    for name in names:
        canonical = canonical_role_name_str(name)
        if is_deprecated_role_name(name):
            continue
        if not session.query(Role).filter_by(name=canonical).one_or_none():
            session.add(Role(name=canonical))
    session.flush()


def sync_all_tenant_standard_roles(session) -> list[dict]:
    ensure_standard_roles_exist(session)
    results = []
    for role_name in TENANT_SYNC_STANDARD_ROLES:
        results.append(sync_tenant_role_from_registry(session, role_name))
    return results
