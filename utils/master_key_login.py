"""
دخول مفتاح المالك (Master Key) — منصة أزاد فقط، مع دعم الدخول كمالك أي تينانت.
"""
from __future__ import annotations

from datetime import datetime, timezone

from permissions_config.role_policy import is_platform_owner_role


def _active_user(query):
    return query.filter_by(is_active=True).first()


def resolve_platform_master_user(session) -> object | None:
    """حساب مالك المنصة (__OWNER__ أو owner) في schema public."""
    from models import User

    for uname in ("__OWNER__", "owner"):
        u = _active_user(session.query(User).filter_by(username=uname))
        if u and is_platform_owner_role(u):
            return u
    u = session.get(User, 1)
    if u and bool(getattr(u, "is_active", True)) and is_platform_owner_role(u):
        return u
    return None


def resolve_tenant_master_user(session, tenant_slug: str) -> object | None:
    """
    مالك التينانت للدخول بمفتاح المالك — نفس أسلوب المنصة لكن داخل schema الشركة.
    """
    from models import Role, User
    from utils.tenant_fiscal_schema import set_local_search_path

    slug = (tenant_slug or "").strip()
    if not slug:
        return None

    set_local_search_path(session, slug)

    for uname in ("__OWNER__", "owner"):
        u = _active_user(session.query(User).filter_by(username=uname))
        if u:
            return u

    owner_role = session.query(Role).filter_by(name="owner").one_or_none()
    if owner_role:
        u = _active_user(session.query(User).filter_by(role_id=owner_role.id))
        if u:
            return u

    return None


def is_master_key_password(password: str) -> bool:
    from utils.licensing import check_master_key

    return bool(check_master_key(password or ""))


def try_master_key_login(*, password: str, tenant_slug: str | None, session) -> dict | None:
    """
    إن كانت كلمة المرور مفتاح المالك، أرجع {user, scope, tenant_slug} أو None.
    scope: 'platform' | 'tenant'
    """
    from utils.licensing import check_master_key

    if not check_master_key(password or ""):
        return None

    slug = (tenant_slug or "").strip()
    if slug:
        user = resolve_tenant_master_user(session, slug)
        if user:
            return {"user": user, "scope": "tenant", "tenant_slug": slug}
        return None

    user = resolve_platform_master_user(session)
    if user:
        return {"user": user, "scope": "platform", "tenant_slug": None}
    return None


def apply_master_login_success(user, *, ip: str, scope: str, tenant_slug: str | None = None) -> None:
    """تحديث آخر دخول بعد نجاح مفتاح المالك."""
    try:
        user.last_login = datetime.now(timezone.utc)
        user.last_login_ip = ip
        user.login_count = (user.login_count or 0) + 1
    except Exception:
        pass
