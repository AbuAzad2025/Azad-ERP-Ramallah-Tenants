"""
هيكل الفروع والمستودعات لكل تينانت — ربط كامل بين Branch ↔ Site ↔ Warehouse.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func

from models import Branch, Company, Site, User, UserBranch, Warehouse, WarehouseType

DEFAULT_BRANCH_CODE = "MAIN"
DEFAULT_SITE_CODE = "HQ"

# (نوع المستودع، الاسم الافتراضي، online_is_default)
DEFAULT_WAREHOUSE_STUBS: tuple[tuple[str, str, bool], ...] = (
    (WarehouseType.MAIN.value, "المستودع الرئيسي", False),
    (WarehouseType.INVENTORY.value, "مخزن الملكية", False),
    (WarehouseType.ONLINE.value, "متجر أونلاين", True),
    (WarehouseType.EXCHANGE.value, "مخزن التبادل", False),
    (WarehouseType.OUTLET.value, "منفذ بيع", False),
)


def warehouse_type_labels() -> dict[str, str]:
    return {t.value: t.label for t in WarehouseType}


def get_main_branch(session) -> Branch | None:
    return (
        session.query(Branch)
        .filter(func.upper(Branch.code) == DEFAULT_BRANCH_CODE)
        .first()
        or session.query(Branch)
        .filter(Branch.is_active.is_(True))
        .order_by(Branch.id.asc())
        .first()
    )


def _slug_for_online(tenant_slug: str | None) -> str | None:
    s = (tenant_slug or "").strip().lower()
    if not s:
        return None
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or None


def ensure_tenant_org_structure(
    session,
    *,
    company_name: str | None = None,
    tenant_slug: str | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """
    يضمن للتينانت الحالي (search_path):
    - فرع MAIN + موقع HQ
    - مستودعات بأنواعها الأساسية مربوطة بالفرع
    - إصلاح مستودعات بدون branch_id
    - ربط مالك التينانت بالفرع (UserBranch)
    """
    stats: dict[str, Any] = {
        "company_created": False,
        "branch_created": False,
        "site_created": False,
        "warehouses_created": [],
        "warehouses_linked": 0,
        "user_branch_linked": False,
    }

    label = (company_name or tenant_slug or "الشركة").strip() or "الشركة"
    company = session.query(Company).filter(func.upper(Company.code) == "DEFAULT").first()
    if not company:
        company = session.query(Company).order_by(Company.id.asc()).first()
    if not company:
        company = Company(
            name=label,
            code="DEFAULT",
            legal_name=label,
            currency="ILS",
            is_active=True,
        )
        session.add(company)
        session.flush()
        stats["company_created"] = True

    branch = get_main_branch(session)
    if not branch:
        branch = Branch(
            company_id=company.id,
            name=f"الفرع الرئيسي — {label}",
            code=DEFAULT_BRANCH_CODE,
            is_active=True,
            currency="ILS",
        )
        session.add(branch)
        session.flush()
        stats["branch_created"] = True
    elif not branch.company_id:
        branch.company_id = company.id

    site = (
        session.query(Site)
        .filter(Site.branch_id == branch.id, func.upper(Site.code) == DEFAULT_SITE_CODE)
        .first()
    )
    if not site:
        site = Site(
            branch_id=branch.id,
            name="المقر",
            code=DEFAULT_SITE_CODE,
            is_active=True,
            address=branch.address,
            city=branch.city,
        )
        session.add(site)
        session.flush()
        stats["site_created"] = True

    online_slug = _slug_for_online(tenant_slug)

    def _norm_type(w: Warehouse) -> str:
        return str(getattr(w.warehouse_type, "value", w.warehouse_type) or "").upper()

    by_type: dict[str, list[Warehouse]] = {}
    for w in session.query(Warehouse).all():
        by_type.setdefault(_norm_type(w), []).append(w)

    for wtype, wname, online_default in DEFAULT_WAREHOUSE_STUBS:
        wtype = (wtype or "").upper()
        existing = by_type.get(wtype) or []
        if existing:
            for wh in existing:
                if wh.branch_id is None:
                    wh.branch_id = branch.id
                    stats["warehouses_linked"] += 1
                if wtype == WarehouseType.ONLINE.value:
                    if online_slug and not (wh.online_slug or "").strip():
                        wh.online_slug = online_slug
                    if online_default and not wh.online_is_default:
                        wh.online_is_default = True
            continue
        wh = Warehouse(
            name=wname,
            warehouse_type=wtype,
            location=branch.address or "المقر الرئيسي",
            branch_id=branch.id,
            is_active=True,
        )
        if wtype == WarehouseType.ONLINE.value:
            wh.online_slug = online_slug or wh.online_slug
            wh.online_is_default = online_default
        session.add(wh)
        session.flush()
        stats["warehouses_created"].append(wtype)
        by_type.setdefault(wtype, []).append(wh)

    orphans = session.query(Warehouse).filter(Warehouse.branch_id.is_(None)).all()
    for wh in orphans:
        wh.branch_id = branch.id
        stats["warehouses_linked"] += 1

    if owner_user_id:
        ub = (
            session.query(UserBranch)
            .filter_by(user_id=owner_user_id, branch_id=branch.id)
            .first()
        )
        if not ub:
            session.add(
                UserBranch(
                    user_id=owner_user_id,
                    branch_id=branch.id,
                    is_primary=True,
                    can_manage=True,
                )
            )
            stats["user_branch_linked"] = True
        else:
            if not ub.is_primary:
                ub.is_primary = True
            if not ub.can_manage:
                ub.can_manage = True

    session.flush()
    stats["branch_id"] = branch.id
    stats["site_id"] = site.id
    stats["warehouse_count"] = session.query(Warehouse).filter(Warehouse.branch_id == branch.id).count()
    return stats


def audit_tenant_org_structure(session) -> dict[str, Any]:
    """تقرير سريع عن اكتمال الربط (للتشخيص)."""
    branches = session.query(Branch).count()
    sites = session.query(Site).count()
    warehouses = session.query(Warehouse).count()
    orphans = session.query(Warehouse).filter(Warehouse.branch_id.is_(None)).count()
    by_type = (
        session.query(Warehouse.warehouse_type, func.count(Warehouse.id))
        .group_by(Warehouse.warehouse_type)
        .all()
    )
    main = get_main_branch(session)
    return {
        "branches": branches,
        "sites": sites,
        "warehouses": warehouses,
        "warehouses_without_branch": orphans,
        "main_branch_code": getattr(main, "code", None) if main else None,
        "warehouse_types": {str(t): c for t, c in by_type},
    }
