"""سياق الشركة/الفرع النشط داخل التينانت (لا يخلط مع TenantRegistry SaaS)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import abort, session
from flask_login import current_user

from extensions import db
from models import Branch, Company, UserBranch


def get_branch_ids_for_user(user_id: int) -> List[int]:
    rows = UserBranch.query.filter_by(user_id=int(user_id)).all()
    return [int(r.branch_id) for r in rows if r.branch_id]


def get_primary_branch_id(user_id: int) -> Optional[int]:
    row = (
        UserBranch.query.filter_by(user_id=int(user_id), is_primary=True)
        .order_by(UserBranch.id.asc())
        .first()
    )
    if row and row.branch_id:
        return int(row.branch_id)
    ids = get_branch_ids_for_user(user_id)
    return ids[0] if ids else None


def sync_user_branches(
    user_id: int,
    branch_ids,
    *,
    primary_branch_id: Optional[int] = None,
) -> None:
    wanted = sorted({int(b) for b in branch_ids if b})
    if not wanted:
        UserBranch.query.filter_by(user_id=int(user_id)).delete(synchronize_session=False)
        return

    primary = int(primary_branch_id) if primary_branch_id in wanted else wanted[0]
    existing = {
        int(r.branch_id): r
        for r in UserBranch.query.filter_by(user_id=int(user_id)).all()
    }

    for bid in wanted:
        if bid in existing:
            existing[bid].is_primary = bid == primary
            existing[bid].can_manage = bool(existing[bid].can_manage)
        else:
            db.session.add(
                UserBranch(
                    user_id=int(user_id),
                    branch_id=bid,
                    is_primary=bid == primary,
                    can_manage=False,
                )
            )

    for bid, row in existing.items():
        if bid not in wanted:
            db.session.delete(row)


def sync_login_branch_session(user) -> None:
    if not user or not getattr(user, "id", None):
        session.pop("accessible_branch_ids", None)
        session.pop("active_branch_id", None)
        session.pop("active_company_id", None)
        return
    ids = get_branch_ids_for_user(int(user.id))
    session["accessible_branch_ids"] = ids
    primary = get_primary_branch_id(int(user.id))
    session["active_branch_id"] = primary if primary in ids else (ids[0] if ids else None)
    if session.get("active_branch_id"):
        br = db.session.get(Branch, int(session["active_branch_id"]))
        if br and br.company_id:
            session["active_company_id"] = int(br.company_id)


def clear_branch_session() -> None:
    session.pop("accessible_branch_ids", None)
    session.pop("active_branch_id", None)
    session.pop("active_company_id", None)


def get_active_branch_id() -> Optional[int]:
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids

    if can_view_all_branches():
        raw = session.get("active_branch_id")
        return int(raw) if raw else None
    ids = get_accessible_branch_ids() or []
    if not ids:
        return None
    raw = session.get("active_branch_id")
    if raw and int(raw) in ids:
        return int(raw)
    return int(ids[0])


def get_active_company_id() -> Optional[int]:
    from utils.company_scope import get_accessible_company_ids

    raw = session.get("active_company_id")
    if raw:
        co_id = int(raw)
        allowed = get_accessible_company_ids()
        if allowed is None or co_id in allowed:
            return co_id
    bid = get_active_branch_id()
    if bid:
        br = db.session.get(Branch, bid)
        if br and br.company_id:
            return int(br.company_id)
    return None


def set_active_branch_id(branch_id: int) -> bool:
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids

    bid = int(branch_id)
    if can_view_all_branches():
        session["active_branch_id"] = bid
        br = db.session.get(Branch, bid)
        if br and br.company_id:
            session["active_company_id"] = int(br.company_id)
        return True
    allowed = get_accessible_branch_ids() or []
    if bid not in allowed:
        return False
    session["active_branch_id"] = bid
    br = db.session.get(Branch, bid)
    if br and br.company_id:
        session["active_company_id"] = int(br.company_id)
    return True


def set_active_company_id(company_id: int) -> bool:
    from utils.company_scope import assert_company_access, branch_ids_for_company

    cid = int(company_id)
    assert_company_access(cid)
    session["active_company_id"] = cid
    branch_ids = branch_ids_for_company(cid) or []
    if branch_ids:
        current = get_active_branch_id()
        if not current or current not in branch_ids:
            session["active_branch_id"] = int(branch_ids[0])
    return True


def accessible_branches_query():
    from utils.company_scope import filter_branches_query

    return filter_branches_query(Branch.query.filter_by(is_active=True)).order_by(Branch.name)


def accessible_companies_query():
    from utils.company_scope import filter_companies_query

    return filter_companies_query(Company.query.filter_by(is_active=True)).order_by(Company.name)


def branch_choices_for_form(
    *,
    include_empty: bool = False,
    empty_label: str = "-- اختر الفرع --",
    with_company: bool = True,
    company_id: Optional[int] = None,
) -> List[Tuple[int, str]]:
    choices: List[Tuple[int, str]] = []
    if include_empty:
        choices.append((0, empty_label))
    q = accessible_branches_query()
    if company_id:
        q = q.filter(Branch.company_id == int(company_id))
    for b in q.all():
        co = getattr(b, "company", None) if with_company else None
        if co and with_company:
            label = f"{b.name} — {co.name}"
        else:
            label = b.name
        choices.append((int(b.id), label))
    return choices


def default_branch_id_for_create() -> Optional[int]:
    active = get_active_branch_id()
    if active:
        return active
    from utils.company_scope import get_accessible_branch_ids

    ids = get_accessible_branch_ids()
    if ids and len(ids) == 1:
        return int(ids[0])
    return None


def resolve_branch_id(submitted: Any, *, required: bool = False) -> Optional[int]:
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids

    allowed = get_accessible_branch_ids()
    if allowed is not None and not allowed:
        if required:
            abort(403)
        return None

    bid: Optional[int] = None
    try:
        if submitted not in (None, "", 0, "0"):
            bid = int(submitted)
    except (TypeError, ValueError):
        bid = None

    if bid is None:
        bid = default_branch_id_for_create()

    if bid is None:
        if required and not can_view_all_branches():
            abort(400)
        return None

    if allowed is not None and int(bid) not in allowed:
        abort(403)
    return int(bid)


def build_org_context() -> Dict[str, Any]:
    from utils.company_scope import can_view_all_branches, get_accessible_company_ids

    ctx: Dict[str, Any] = {
        "org_company_name": "",
        "org_branch_name": "",
        "org_branch_id": None,
        "org_company_id": None,
        "org_branches": [],
        "org_companies": [],
        "org_can_switch_branch": False,
        "org_can_switch_company": False,
        "org_view_all_branches": False,
    }
    if not getattr(current_user, "is_authenticated", False):
        return ctx

    ctx["org_view_all_branches"] = can_view_all_branches()
    branches = accessible_branches_query().all()
    companies = accessible_companies_query().all()
    ctx["org_branches"] = branches
    ctx["org_companies"] = companies
    ctx["org_can_switch_branch"] = len(branches) > 1 or ctx["org_view_all_branches"]
    ctx["org_can_switch_company"] = len(companies) > 1 or ctx["org_view_all_branches"]

    active_id = get_active_branch_id()
    active_branch = None
    if active_id:
        active_branch = next((b for b in branches if b.id == active_id), None)
        if not active_branch:
            active_branch = db.session.get(Branch, active_id)
    elif branches:
        active_branch = branches[0]

    if active_branch:
        ctx["org_branch_id"] = int(active_branch.id)
        ctx["org_branch_name"] = active_branch.name
        co = getattr(active_branch, "company", None) or (
            db.session.get(Company, active_branch.company_id) if active_branch.company_id else None
        )
        if co:
            ctx["org_company_id"] = int(co.id)
            ctx["org_company_name"] = co.name

    co_ids = get_accessible_company_ids()
    if co_ids is not None and len(co_ids) == 1:
        co = db.session.get(Company, co_ids[0])
        if co and not ctx["org_company_name"]:
            ctx["org_company_name"] = co.name
            ctx["org_company_id"] = co.id

    return ctx


def guard_posted_branch_ids() -> None:
    from flask import request

    if request.method not in ("POST", "PUT", "PATCH"):
        return
    for key in ("branch_id", "active_branch_id", "set_branch"):
        raw = request.form.get(key)
        if raw is None or raw == "":
            continue
        try:
            resolve_branch_id(int(raw), required=False)
        except Exception:
            abort(403)
