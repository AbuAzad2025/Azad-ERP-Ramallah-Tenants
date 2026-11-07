"""سياق الشركة/الفرع للواجهة والنماذج — افتراضي آمن عند الإنشاء."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import abort, session
from flask_login import current_user


def sync_login_tenant_session(user) -> None:
    """بعد تسجيل الدخول: حفظ الفروع المسموحة والفرع النشط."""
    from services.user_branch_service import get_branch_ids_for_user, get_primary_branch_id
    from utils.company_scope import can_view_all_branches

    if not user or not getattr(user, "id", None):
        session.pop("accessible_branch_ids", None)
        session.pop("active_branch_id", None)
        return
    ids = get_branch_ids_for_user(int(user.id))
    session["accessible_branch_ids"] = ids
    primary = get_primary_branch_id(int(user.id))
    if primary and primary in ids:
        session["active_branch_id"] = primary
    elif ids:
        session["active_branch_id"] = ids[0]
    elif can_view_all_branches():
        from models import Branch

        first = (
            Branch.query.filter_by(is_active=True)
            .order_by(Branch.company_id.asc(), Branch.id.asc())
            .first()
        )
        session["active_branch_id"] = int(first.id) if first else None
    else:
        session["active_branch_id"] = None


def clear_tenant_session() -> None:
    session.pop("accessible_branch_ids", None)
    session.pop("active_branch_id", None)


def get_active_branch_id() -> Optional[int]:
    """الفرع النشط للإنشاء والعرض الافتراضي."""
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids

    if can_view_all_branches():
        raw = session.get("active_branch_id")
        if raw:
            return int(raw)
        return None
    ids = get_accessible_branch_ids() or []
    if not ids:
        return None
    raw = session.get("active_branch_id")
    if raw and int(raw) in ids:
        return int(raw)
    return int(ids[0])


def set_active_branch_id(branch_id: int) -> bool:
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids

    bid = int(branch_id)
    if can_view_all_branches():
        session["active_branch_id"] = bid
        return True
    allowed = get_accessible_branch_ids() or []
    if bid not in allowed:
        return False
    session["active_branch_id"] = bid
    return True


def accessible_branches_query():
    from models import Branch
    from utils.company_scope import filter_branches_query

    return filter_branches_query(Branch.query.filter_by(is_active=True)).order_by(Branch.name)


def branch_choices_for_form(
    *,
    include_empty: bool = False,
    empty_label: str = "-- اختر الفرع --",
    with_company: bool = True,
) -> List[Tuple[int, str]]:
    choices: List[Tuple[int, str]] = []
    if include_empty:
        choices.append((0, empty_label))
    for b in accessible_branches_query().all():
        co = getattr(b, "company", None) if with_company else None
        if co and with_company:
            label = f"{b.name} — {co.name}"
        else:
            label = b.name
        choices.append((int(b.id), label))
    return choices


def default_branch_id_for_create() -> Optional[int]:
    """فرع افتراضي عند الإنشاء."""
    active = get_active_branch_id()
    if active:
        return active
    from utils.company_scope import get_accessible_branch_ids

    ids = get_accessible_branch_ids()
    if ids and len(ids) == 1:
        return int(ids[0])
    return None


def resolve_branch_id(submitted: Any, *, required: bool = False) -> Optional[int]:
    """
    يتحقق أن الفرع ضمن المسموح.
    submitted: قيمة من النموذج (0 أو None = الافتراضي).
    """
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


def switchable_branches_for_user() -> List[Any]:
    """
    فروع يُسمح بعرضها في محوّل النافبار فقط.
    لا نعرض كل الشركات لمن يرى الكل — فقط فروعه المربوطة صراحةً.
    """
    from models import Branch
    from services.user_branch_service import get_branch_ids_for_user

    linked = sorted({int(b) for b in get_branch_ids_for_user(int(current_user.id)) if b})
    if len(linked) <= 1:
        return []

    rows = (
        Branch.query.filter(Branch.id.in_(linked), Branch.is_active.is_(True))
        .order_by(Branch.name)
        .all()
    )
    return rows if len(rows) > 1 else []


def build_tenant_context() -> Dict[str, Any]:
    from models import Branch, Company
    from utils.company_scope import can_view_all_branches, get_accessible_branch_ids, get_accessible_company_ids

    ctx: Dict[str, Any] = {
        "tenant_company_name": "",
        "tenant_branch_name": "",
        "tenant_branch_id": None,
        "tenant_company_id": None,
        "tenant_branches": [],
        "tenant_can_switch_branch": False,
        "tenant_show_nav_scope": False,
        "tenant_view_all": False,
        "tenant_isolated": True,
    }
    if not getattr(current_user, "is_authenticated", False):
        return ctx

    ctx["tenant_view_all"] = can_view_all_branches()
    branches = accessible_branches_query().all()
    switchable = switchable_branches_for_user()
    ctx["tenant_branches"] = switchable
    ctx["tenant_can_switch_branch"] = len(switchable) > 1
    ctx["tenant_show_nav_scope"] = ctx["tenant_can_switch_branch"]

    active_id = get_active_branch_id()
    active_branch = None
    if active_id:
        active_branch = next((b for b in branches if b.id == active_id), None)
        if not active_branch:
            active_branch = Branch.query.filter_by(id=active_id).first()
    elif branches:
        active_branch = branches[0]

    if active_branch:
        ctx["tenant_branch_id"] = int(active_branch.id)
        ctx["tenant_branch_name"] = active_branch.name
        co = getattr(active_branch, "company", None) or (
            Company.query.get(active_branch.company_id) if active_branch.company_id else None
        )
        if co:
            ctx["tenant_company_id"] = int(co.id)
            ctx["tenant_company_name"] = co.name

    co_ids = get_accessible_company_ids()
    if co_ids is not None and len(co_ids) == 1:
        co = Company.query.get(co_ids[0])
        if co and not ctx["tenant_company_name"]:
            ctx["tenant_company_name"] = co.name
            ctx["tenant_company_id"] = co.id

    return ctx


def assign_branch_field(form_field, *, default: bool = True) -> None:
    """تعبئة خيارات فرع النموذج + الافتراضي."""
    branches = accessible_branches_query().all()
    include_empty = len(branches) != 1
    form_field.choices = branch_choices_for_form(include_empty=include_empty)
    if default:
        d = default_branch_id_for_create()
        if d:
            form_field.data = d


def branch_choices_with_prefix(zero_label: str = "") -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    if zero_label:
        out.append((0, zero_label))
    for b in accessible_branches_query().all():
        out.append((int(b.id), f"{b.code} - {b.name}"))
    return out


def login_company_hints() -> List[Dict[str, str]]:
    """أسماء الشركات والفروع للعرض في صفحة الدخول (بدون بيانات حساسة)."""
    from models import Branch, Company

    rows: List[Dict[str, str]] = []
    q = (
        Branch.query.filter_by(is_active=True)
        .join(Company, Company.id == Branch.company_id)
        .filter(Company.is_active.is_(True))
        .order_by(Company.name, Branch.name)
        .limit(50)
    )
    for b in q.all():
        co = getattr(b, "company", None)
        rows.append(
            {
                "company": (co.name if co else "") or "",
                "branch": b.name or "",
            }
        )
    return rows


def guard_posted_branch_ids() -> None:
    """رفض فرع غير مسموح في POST (نماذج عادية)."""
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
