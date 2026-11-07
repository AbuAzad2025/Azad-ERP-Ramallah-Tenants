"""ربط المستخدمين بالفروع والشركات."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from extensions import db
from models import UserBranch


def get_branch_ids_for_user(user_id: int) -> List[int]:
    rows = UserBranch.query.filter_by(user_id=int(user_id)).all()
    return [int(r.branch_id) for r in rows if r.branch_id]


def get_primary_branch_id(user_id: int) -> Optional[int]:
    row = (
        UserBranch.query.filter_by(user_id=int(user_id), is_primary=True)
        .order_by(UserBranch.id.asc())
        .first()
    )
    if row:
        return int(row.branch_id)
    ids = get_branch_ids_for_user(user_id)
    return ids[0] if ids else None


def role_can_skip_branch_assignment(role_id: int | None) -> bool:
    """أدوار المنصة (مالك/مدير أعلى/عرض كل الفروع) — الفروع اختيارية."""
    from models import Role
    from permissions_config.permissions import PermissionsRegistry

    if not role_id:
        return False
    role = Role.query.get(int(role_id))
    if not role:
        return False
    name = (role.name or "").strip().lower()
    if name in {"owner", "developer"}:
        return True
    try:
        if PermissionsRegistry.is_role_super(name):
            return True
    except Exception:
        pass
    info = PermissionsRegistry.ROLES.get(name, {})
    if int(info.get("level", 999)) == 0:
        return True
    try:
        return bool(role.has_permission("view_all_branches"))
    except Exception:
        return False


def _resolve_default_branch(branches_by_code: dict) -> "Branch | None":
    """أول فرع نشط حسب أولوية الرموز ثم أي فرع."""
    from models import Branch

    for code in ("MAIN", "RAMALLAH", "SHARJAH", "DEFAULT"):
        br = branches_by_code.get(code.upper())
        if br:
            return br
    first = Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).first()
    return first


def validate_branch_assignment(
    branch_ids: Iterable[int],
    *,
    primary_branch_id: int | None = None,
    role_id: int | None = None,
) -> str | None:
    """None = OK، وإلا رسالة خطأ."""
    wanted = sorted({int(b) for b in branch_ids if b})
    primary = int(primary_branch_id) if primary_branch_id else None
    if not wanted:
        if role_can_skip_branch_assignment(role_id):
            return None
        return "يجب اختيار فرع واحد على الأقل وربطه بالمستخدم."
    if primary and primary not in wanted:
        return "الفرع الرئيسي يجب أن يكون ضمن الفروع المختارة."
    from models import Branch

    rows = Branch.query.filter(Branch.id.in_(wanted)).all()
    if len(rows) != len(wanted):
        return "أحد الفروع المختارة غير موجود."
    return None


def apply_user_branch_assignment(
    user_id: int,
    branch_ids: Iterable[int],
    *,
    primary_branch_id: int | None = None,
    role_id: int | None = None,
) -> str | None:
    err = validate_branch_assignment(
        branch_ids, primary_branch_id=primary_branch_id, role_id=role_id
    )
    if err:
        return err
    wanted = sorted({int(b) for b in branch_ids if b})
    if not wanted:
        sync_user_branches(user_id, [])
        return None
    primary = int(primary_branch_id) if primary_branch_id in wanted else wanted[0]
    sync_user_branches(user_id, wanted, primary_branch_id=primary)
    return None


def load_users_branch_display(user_ids: List[int], users_by_id: dict | None = None) -> Dict[int, dict]:
    """عرض الشركة/الفرع لكل مستخدم في القوائم."""
    from models import Branch, Company

    out: Dict[int, dict] = {
        int(uid): {
            "companies": [],
            "branches": [],
            "primary": "",
            "label": "—",
            "view_all": False,
        }
        for uid in user_ids
    }
    if not user_ids:
        return out

    rows = (
        db.session.query(UserBranch, Branch, Company)
        .join(Branch, Branch.id == UserBranch.branch_id)
        .join(Company, Company.id == Branch.company_id)
        .filter(UserBranch.user_id.in_([int(x) for x in user_ids]))
        .order_by(UserBranch.is_primary.desc(), Company.name, Branch.name)
        .all()
    )
    for ub, br, co in rows:
        uid = int(ub.user_id)
        slot = out.setdefault(
            uid,
            {"companies": [], "branches": [], "primary": "", "label": "—", "view_all": False},
        )
        co_name = co.name or co.code
        br_label = f"{co_name} — {br.name}"
        if co_name not in slot["companies"]:
            slot["companies"].append(co_name)
        slot["branches"].append(br_label)
        if ub.is_primary:
            slot["primary"] = br_label
    users_by_id = users_by_id or {}
    for uid, slot in out.items():
        if slot["branches"]:
            slot["label"] = slot["primary"] or slot["branches"][0]
            if len(slot["branches"]) > 1:
                slot["label"] += f" (+{len(slot['branches']) - 1})"
            continue
        user = users_by_id.get(int(uid))
        role_id = getattr(user, "role_id", None) if user else None
        if role_can_skip_branch_assignment(role_id):
            slot["label"] = "كل الشركات"
            slot["view_all"] = True
        else:
            slot["label"] = "غير مربوط"
            slot["view_all"] = False
    return out


def sync_user_branches(
    user_id: int,
    branch_ids: Iterable[int],
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


def count_unlinked_operational_users() -> int:
    """مستخدمون تشغيليون بدون أي فرع."""
    from models import User

    n = 0
    for u in User.query.filter(User.is_system_account.is_(False), User.is_active.is_(True)).all():
        if role_can_skip_branch_assignment(u.role_id):
            continue
        if not get_branch_ids_for_user(int(u.id)):
            n += 1
    return n


def repair_missing_user_branch_links() -> dict:
    """
    إصلاح الربط الناقص فقط — لا يغيّر مستخدمين مربوطين مسبقاً.
    يُستدعى من لوحة الإدارة عند الحاجة.
    """
    from models import User, Branch

    branches_by_code = {
        (b.code or "").upper(): b for b in Branch.query.filter_by(is_active=True).all()
    }
    default_br = _resolve_default_branch(branches_by_code)
    report: dict = {"fixed": [], "skipped": [], "unlinked": [], "errors": []}

    for u in User.query.filter(User.is_system_account.is_(False)).order_by(User.username).all():
        uname = (u.username or "").strip()
        uname_l = uname.lower()

        if role_can_skip_branch_assignment(u.role_id):
            if uname_l == "owner" and not u.is_active:
                u.is_active = True
                report["fixed"].append(f"{uname}: تم تفعيل حساب المالك")
            report["skipped"].append(uname)
            continue

        if get_branch_ids_for_user(int(u.id)):
            report["skipped"].append(uname)
            continue

        br = default_br
        if not br:
            msg = f"{uname}: لا يوجد فرع نشط في النظام"
            report["errors"].append(msg)
            report["unlinked"].append(uname)
            continue

        sync_user_branches(int(u.id), [int(br.id)], primary_branch_id=int(br.id))
        co = getattr(br, "company", None)
        co_label = co.name if co else ""
        report["fixed"].append(f"{uname} → {co_label} / {br.name}".strip(" /"))

    still = count_unlinked_operational_users()
    report["unlinked_count"] = still
    return report
