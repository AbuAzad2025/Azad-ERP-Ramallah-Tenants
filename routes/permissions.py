# -*- coding: utf-8 -*-
from flask import Blueprint, flash, redirect, render_template, url_for, abort, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import re

from extensions import db
from forms import PermissionForm
from models import Permission, AuditLog
import utils
from permissions_config.enums import SystemPermissions
from permissions_config.permissions import PermissionsRegistry
from utils import _get_or_404

permissions_bp = Blueprint("permissions", __name__, url_prefix="/permissions", template_folder="templates/permissions")


_RESERVED_CODES = PermissionsRegistry.get_protected_permissions()


def _normalize_code(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or None

def _unique_violation(name: str | None, code: str | None, exclude_id: int | None = None) -> str | None:
    name_l = (name or "").strip().lower()
    code_l = (code or "").strip().lower() if code else None
    q = Permission.query
    if exclude_id:
        q = q.filter(Permission.id != exclude_id)
    if name_l:
        by_name = q.filter(func.lower(Permission.name) == name_l).first()
        if by_name:
            return "هذا الاسم مستخدم بالفعل!"
    if code_l:
        q2 = Permission.query
        if exclude_id:
            q2 = q2.filter(Permission.id != exclude_id)
        by_code = q2.filter(
            Permission.code.isnot(None),
            func.lower(Permission.code) == code_l,
        ).first()
        if by_code:
            return "هذا الكود مستخدم بالفعل!"
    return None

def _clear_affected_caches(perm: Permission):
    try:
        roles = list(getattr(perm, "roles", []) or [])
    except Exception:
        roles = []
    try:
        users_extra = list(perm.users_extra.all())
    except Exception:
        users_extra = []
    for r in roles:
        try:
            utils.clear_role_permission_cache(r.id)
        except Exception:
            current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)
        try:
            utils.clear_users_cache_by_role(r.id)
        except Exception:
            current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)
    for u in users_extra:
        try:
            utils.clear_user_permission_cache(u.id)
        except Exception:
            current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)

def _ensure_code_from_inputs(name: str | None, code: str | None) -> str | None:
    return _normalize_code(code) or _normalize_code(name)

def _parse_aliases(raw: str | None):
    return [a.strip().lower() for a in (raw or "").split(",") if a.strip()]

@permissions_bp.route("/", methods=["GET"], endpoint="list")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_PERMISSIONS)
def list_permissions():
    search = (request.args.get("search") or "").strip()
    q = Permission.query
    if search:
        needle = f"%{search}%"
        q = q.filter(
            (func.lower(Permission.name).like(func.lower(needle))) |
            (func.lower(Permission.code).like(func.lower(needle)))
        )
    permissions = q.order_by(func.lower(Permission.name)).all()
    return render_template("permissions/list.html", permissions=permissions, search=search)

@permissions_bp.route("/create", methods=["GET", "POST"], endpoint="create")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_PERMISSIONS)
def create_permission():
    form = PermissionForm()
    if form.validate_on_submit():
        name = (form.name.data or "").strip()
        code = _ensure_code_from_inputs(name, getattr(form, "code", None) and form.code.data)
        if not name:
            flash("الاسم مطلوب.", "danger")
            return render_template("permissions/form.html", form=form, protected_codes=_RESERVED_CODES)
        if not code:
            flash("الكود مطلوب (تمّ توليده من الاسم لكن نتج فارغ). عدّل الاسم أو أدخل كودًا صالحًا.", "danger")
            return render_template("permissions/form.html", form=form, protected_codes=_RESERVED_CODES)
        msg = _unique_violation(name, code)
        if msg:
            flash(msg, "danger")
        else:
            try:
                with db.session.begin():
                    perm = Permission(
                        name=name,
                        code=code,
                        name_ar=(form.name_ar.data or "").strip() or None,
                        module=(form.module.data or "").strip() or None,
                        aliases=_parse_aliases(form.aliases.data),
                        is_protected=bool(form.is_protected.data),
                        description=(form.description.data or "").strip() or None,
                    )
                    db.session.add(perm)
                    db.session.flush()
                    db.session.add(AuditLog(
                        model_name="Permission",
                        record_id=perm.id,
                        user_id=current_user.id,
                        action="CREATE",
                        old_data="",
                        new_data=f"name={perm.name},code={perm.code or ''}"
                    ))
                _clear_affected_caches(perm)
                flash("تم إضافة الإذن بنجاح.", "success")
                return redirect(url_for("permissions.list"))
            except IntegrityError:
                db.session.rollback()
                flash("اسم/كود الإذن مستخدم بالفعل.", "danger")
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception('internal error')
                flash('خطأ أثناء الإضافة', 'danger')
    return render_template("permissions/form.html", form=form, protected_codes=_RESERVED_CODES)

@permissions_bp.route("/<int:permission_id>/edit", methods=["GET", "POST"], endpoint="edit")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_PERMISSIONS)
def edit_permission(permission_id):
    perm = _get_or_404(Permission, permission_id)
    form = PermissionForm(obj=perm)
    if form.validate_on_submit():
        incoming_name = (form.name.data or "").strip()
        incoming_code_input = getattr(form, "code", None) and form.code.data
        if perm.code and _normalize_code(perm.code) in _RESERVED_CODES:
            incoming_code = perm.code
        else:
            incoming_code = _ensure_code_from_inputs(incoming_name, incoming_code_input)
        if not incoming_name:
            flash("الاسم مطلوب.", "danger")
            return render_template("permissions/form.html", form=form, perm=perm, protected_codes=_RESERVED_CODES)
        if not incoming_code:
            flash("الكود مطلوب (تمّ توليده من الاسم لكن نتج فارغ). عدّل الاسم أو أدخل كودًا صالحًا.", "danger")
            return render_template("permissions/form.html", form=form, perm=perm, protected_codes=_RESERVED_CODES)
        msg = _unique_violation(incoming_name, incoming_code, exclude_id=perm.id)
        if msg:
            flash(msg, "danger")
        else:
            try:
                old_data = f"name={perm.name},code={perm.code or ''}"
                with db.session.begin():
                    perm.name = incoming_name
                    perm.code = incoming_code
                    perm.name_ar = (form.name_ar.data or "").strip() or None
                    perm.module = (form.module.data or "").strip() or None
                    perm.aliases = _parse_aliases(form.aliases.data)
                    perm.is_protected = bool(form.is_protected.data)
                    perm.description = (form.description.data or "").strip() or None
                    db.session.add(AuditLog(
                        model_name="Permission",
                        record_id=perm.id,
                        user_id=current_user.id,
                        action="UPDATE",
                        old_data=old_data,
                        new_data=f"name={perm.name},code={perm.code or ''}"
                    ))
                _clear_affected_caches(perm)
                flash("تم تحديث الإذن.", "success")
                return redirect(url_for("permissions.list"))
            except IntegrityError:
                db.session.rollback()
                flash("اسم/كود الإذن مستخدم بالفعل.", "danger")
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception('internal error')
                flash('خطأ أثناء التحديث', 'danger')
    return render_template("permissions/form.html", form=form, perm=perm, protected_codes=_RESERVED_CODES)

@permissions_bp.route("/<int:permission_id>/delete", methods=["POST"], endpoint="delete")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_PERMISSIONS)
def delete_permission(permission_id):
    perm = _get_or_404(Permission, permission_id)
    if (perm.code and _normalize_code(perm.code) in _RESERVED_CODES) or (
        perm.name and _normalize_code(perm.name) in _RESERVED_CODES
    ):
        flash("لا يمكن حذف صلاحيات النظام الحرِجة.", "danger")
        return redirect(url_for("permissions.list"))
    try:
        try:
            used_by_roles = bool(getattr(perm, "roles", []) or [])
        except Exception:
            used_by_roles = False
        try:
            used_by_users = perm.users_extra.count() > 0
        except Exception:
            used_by_users = False
        if used_by_roles or used_by_users:
            flash("لا يمكن الحذف: الإذن مرتبط بأدوار/مستخدمين.", "danger")
            return redirect(url_for("permissions.list"))
        try:
            role_ids = [r.id for r in getattr(perm, "roles", []) or []]
        except Exception:
            role_ids = []
        try:
            user_ids = [u.id for u in perm.users_extra.all()]
        except Exception:
            user_ids = []
        old_data = f"name={perm.name},code={perm.code or ''}"
        with db.session.begin():
            db.session.delete(perm)
            db.session.add(AuditLog(
                model_name="Permission",
                record_id=permission_id,
                user_id=current_user.id,
                action="DELETE",
                old_data=old_data,
                new_data=""
            ))
        for rid in role_ids:
            try:
                utils.clear_role_permission_cache(rid)
            except Exception:
                current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)
            try:
                utils.clear_users_cache_by_role(rid)
            except Exception:
                current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)
        for uid in user_ids:
            try:
                utils.clear_user_permission_cache(uid)
            except Exception:
                current_app.logger.warning('cache operation failed silently in permissions.py', exc_info=True)
        flash("تم حذف الإذن.", "warning")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('لا يمكن الحذف', 'danger')
    return redirect(url_for("permissions.list"))

@permissions_bp.route("/matrix", methods=["GET"], endpoint="matrix")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_PERMISSIONS)
def permissions_matrix():
    mapping = {
        "shop": {"read": SystemPermissions.VIEW_SHOP, "write": SystemPermissions.MANAGE_SHOP, "public_read": True},
        "users": {"read": SystemPermissions.MANAGE_USERS, "write": SystemPermissions.MANAGE_USERS},
        "customers": {"read": SystemPermissions.MANAGE_CUSTOMERS, "write": SystemPermissions.MANAGE_CUSTOMERS},
        "vendors": {"read": SystemPermissions.MANAGE_VENDORS, "write": SystemPermissions.MANAGE_VENDORS},
        "shipments": {"read": SystemPermissions.MANAGE_SHIPMENTS, "write": SystemPermissions.MANAGE_SHIPMENTS},
        "warehouse": {"read": SystemPermissions.VIEW_WAREHOUSES, "write": SystemPermissions.MANAGE_WAREHOUSES},
        "payments": {"read": SystemPermissions.MANAGE_PAYMENTS, "write": SystemPermissions.MANAGE_PAYMENTS},
        "expenses": {"read": SystemPermissions.MANAGE_EXPENSES, "write": SystemPermissions.MANAGE_EXPENSES},
        "sales": {"read": SystemPermissions.MANAGE_SALES, "write": SystemPermissions.MANAGE_SALES},
        "service": {"read": SystemPermissions.MANAGE_SERVICE, "write": SystemPermissions.MANAGE_SERVICE},
        "reports": {"read": SystemPermissions.VIEW_REPORTS, "write": SystemPermissions.MANAGE_REPORTS},
        "roles": {"read": SystemPermissions.MANAGE_ROLES, "write": SystemPermissions.MANAGE_ROLES},
        "permissions": {"read": SystemPermissions.MANAGE_PERMISSIONS, "write": SystemPermissions.MANAGE_PERMISSIONS},
        "parts": {"read": SystemPermissions.VIEW_PARTS, "write": SystemPermissions.MANAGE_INVENTORY},
        "admin_reports": {"read": SystemPermissions.VIEW_REPORTS, "write": SystemPermissions.MANAGE_REPORTS},
        "api": {"read": SystemPermissions.ACCESS_API, "write": SystemPermissions.MANAGE_API},
        "barcode": {"read": SystemPermissions.VIEW_PARTS},
        "barcode_scanner": {"read": SystemPermissions.VIEW_BARCODE, "write": SystemPermissions.MANAGE_BARCODE},
        "ledger": {"read": SystemPermissions.MANAGE_LEDGER, "write": SystemPermissions.MANAGE_LEDGER},
        "currencies": {"read": SystemPermissions.MANAGE_CURRENCIES, "write": SystemPermissions.MANAGE_CURRENCIES},
        "checks": {"read": SystemPermissions.MANAGE_PAYMENTS, "write": SystemPermissions.MANAGE_PAYMENTS},
    }
    roles = {}
    for role_name in PermissionsRegistry.ROLES.keys():
        perms = PermissionsRegistry.get_role_permissions(role_name)
        modules = {}
        for bp_name, req in mapping.items():
            rp = req.get("read")
            wp = req.get("write")
            public_read = bool(req.get("public_read"))
            rp_code = rp.value if hasattr(rp, "value") else rp
            wp_code = wp.value if hasattr(wp, "value") else wp
            read_allowed = public_read or (rp is None) or (rp_code in perms)
            write_allowed = bool(wp and (wp_code in perms))
            modules[bp_name] = {"read": bool(read_allowed), "write": bool(write_allowed)}
        roles[role_name] = {"permissions": sorted(list(perms)), "modules": modules}
    return jsonify({"roles": roles})
