"""
سياسة الأدوار الموحّدة — مصدر واحد لأسماء الأدوار، التسلسل، ولوحات الدخول.

لا تُكرّر قوائم الأدوار في routes/models؛ استورد من هنا.
"""
from __future__ import annotations

from permissions_config.enums import SystemRoles
from permissions_config.permissions import PermissionsRegistry

# أدوار النظام المعرفة في PermissionsRegistry (لا تُنشأ أدوار مخصصة بنفس الأسماء إلا عمداً)
SYSTEM_ROLE_NAMES: frozenset[str] = frozenset(r.value for r in SystemRoles)

# مالك المنصة (أزاد) — لوحة security فقط، وليس super_admin
PLATFORM_OWNER_ROLES: frozenset[str] = frozenset(
    {SystemRoles.OWNER.value, SystemRoles.DEVELOPER.value}
)

# أدوار is_super في السجل — صلاحيات واسعة لكن ليست بالضرورة مالك منصة
def super_role_names() -> frozenset[str]:
    return frozenset(PermissionsRegistry.get_super_roles())


def normalize_role_name(user) -> str:
    """اسم الدور بحروف صغيرة؛ حساب __OWNER__ يُعامل كـ owner."""
    if not user:
        return ""
    if (getattr(user, "username", "") or "").strip().upper() == "__OWNER__":
        return SystemRoles.OWNER.value
    try:
        return (getattr(getattr(user, "role", None), "name", None) or "").strip().lower()
    except Exception:
        return ""


def is_system_owner_account(user) -> bool:
    return bool(
        getattr(user, "is_system", False)
        or getattr(user, "is_system_account", False)
        or (getattr(user, "username", "") or "").strip().upper() == "__OWNER__"
    )


def is_platform_owner_role(user) -> bool:
    """مالك/مطور المنصة — لوحة المالك (security) وليس مدير تينانت."""
    if not user:
        return False
    if is_system_owner_account(user):
        return True
    return normalize_role_name(user) in PLATFORM_OWNER_ROLES


def is_super_role_user(user) -> bool:
    if not user:
        return False
    if is_system_owner_account(user):
        return True
    try:
        if getattr(user, "is_super_role", False):
            return True
    except Exception:
        pass
    return normalize_role_name(user) in super_role_names()


def is_tenant_owner_role(user) -> bool:
    """دور owner داخل تينانت (شركة) — ليس مالك المنصة."""
    return normalize_role_name(user) == SystemRoles.OWNER.value and not is_platform_owner_role(user)


def role_level(role_name: str) -> int:
    return PermissionsRegistry.get_role_level((role_name or "").strip().lower())


def is_known_system_role(role_name: str) -> bool:
    return (role_name or "").strip().lower() in SYSTEM_ROLE_NAMES


# لوحة الدخول الافتراضية: (دور, منصة, تينانت)
_ROLE_HOME_ROWS: tuple[tuple[str, str, str], ...] = (
    (SystemRoles.OWNER.value, "security.index", "tenant_console.index"),
    (SystemRoles.DEVELOPER.value, "security.index", "tenant_console.index"),
    (SystemRoles.SUPER_ADMIN.value, "main.dashboard", "main.dashboard"),
    (SystemRoles.SUPER.value, "main.dashboard", "main.dashboard"),
    (SystemRoles.ADMIN.value, "main.dashboard", "main.dashboard"),
    (SystemRoles.MANAGER.value, "main.dashboard", "main.dashboard"),
    (SystemRoles.STAFF.value, "main.dashboard", "main.dashboard"),
    (SystemRoles.MECHANIC.value, "service.list_requests", "service.list_requests"),
    (SystemRoles.REGISTERED_CUSTOMER.value, "shop.catalog", "shop.catalog"),
    (SystemRoles.GUEST.value, "shop.catalog", "shop.catalog"),
)


def role_home_table(*, tenant: bool) -> dict[str, str]:
    idx = 2 if tenant else 1
    return {row[0]: row[idx] for row in _ROLE_HOME_ROWS}


PLATFORM_ROLE_HOME: dict[str, str] = role_home_table(tenant=False)
TENANT_ROLE_HOME: dict[str, str] = role_home_table(tenant=True)


def validate_roles_registry() -> list[str]:
    """تحذيرات داخلية: تكرار super/super_admin، أدوار بلا مستوى، إلخ."""
    issues: list[str] = []
    for name in SYSTEM_ROLE_NAMES:
        if name not in PermissionsRegistry.ROLES:
            issues.append(f"missing_registry:{name}")
    sa = PermissionsRegistry.ROLES.get(SystemRoles.SUPER_ADMIN.value, {})
    su = PermissionsRegistry.ROLES.get(SystemRoles.SUPER.value, {})
    if sa and su:
        if sa.get("level") != su.get("level"):
            issues.append("level_mismatch:super_admin_vs_super")
    return issues
