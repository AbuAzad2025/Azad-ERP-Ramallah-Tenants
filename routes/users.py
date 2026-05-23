import json
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for, abort, current_app
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import db
from forms import UserForm
from models import Permission, Role, User, AuditLog, Customer
import utils
from utils import _get_or_404
from permissions_config.enums import SystemPermissions, SystemRoles
from permissions_config.permissions import PermissionsRegistry
from permissions_config.role_policy import (
    canonical_role_name_str,
    effective_role_level,
    is_custom_role,
    is_deprecated_role_name,
)

users_bp = Blueprint("users_bp", __name__, url_prefix="/users", template_folder="templates/users")


def _actor_role_name() -> str:
    try:
        return str(getattr(getattr(current_user, "role", None), "name", "") or "").strip().lower()
    except Exception:
        return ""

def _role_level_by_name(role_name: str) -> int:
    try:
        return effective_role_level(role_name)
    except Exception:
        current_app.logger.debug('numeric conversion failed in users.py', exc_info=True)
    return 999

def _actor_level() -> int:
    return _role_level_by_name(_actor_role_name())

def _actor_can_manage_users() -> bool:
    # Access is controlled by permission 'manage_users'
    return True

def _actor_can_manage_super_level() -> bool:
    try:
        info = PermissionsRegistry.ROLES.get(_actor_role_name(), {}) or {}
        caps = info.get("capabilities") or {}
        return bool(caps.get("can_manage_super_admins")) or _actor_level() == 0
    except Exception:
        return _actor_level() == 0

def _role_is_assignable_by_actor(role: Role | None) -> bool:
    if not role:
        return False
    try:
        name = canonical_role_name_str(role.name)
        if is_deprecated_role_name(role.name):
            return False
        if _actor_level() == 0:
            return True
        if is_custom_role(name):
            return _actor_level() <= 2
        if name not in PermissionsRegistry.ROLES:
            return False
        tgt_level = _role_level_by_name(name)
        
        # Allow super_admin (Level 1) to assign same-level roles
        if _actor_level() == 1 and tgt_level >= 1:
            return True
            
        return tgt_level >= _actor_level()
    except Exception:
        return False

def _filter_permissions_assignable_by_actor(perms: list[Permission]) -> list[Permission]:
    try:
        if _actor_level() == 0:
            return perms
        actor_perms = utils._get_user_permissions(current_user) or set()
        actor_perms = {str(x).strip().lower() for x in actor_perms}
        out: list[Permission] = []
        for p in perms:
            k = str(p.key() if hasattr(p, "key") else (p.code or p.name or "")).strip().lower()
            if k and k in actor_perms:
                out.append(p)
        return out
    except Exception:
        return []

def _selected_permissions_allowed(selected_perm_ids: list[int]) -> bool:
    if not selected_perm_ids:
        return True
    try:
        if _actor_level() == 0:
            return True
        actor_perms = utils._get_user_permissions(current_user) or set()
        actor_perms = {str(x).strip().lower() for x in actor_perms}
        selected = Permission.query.filter(Permission.id.in_(selected_perm_ids)).all()
        selected_keys = {str(p.key() if hasattr(p, "key") else (p.code or p.name or "")).strip().lower() for p in selected}
        selected_keys.discard("")
        return selected_keys.issubset(actor_perms)
    except Exception:
        return False

def _is_super_admin_user(user: User) -> bool:
    try:
        return bool(user.role and PermissionsRegistry.is_role_super(user.role.name))
    except Exception:
        return False

@users_bp.route("/profile", methods=["GET"], endpoint="profile")
@login_required
def profile():
    try:
        raw = current_user.extra_permissions
        perms = list(raw.all() if hasattr(raw, "all") else (raw or []))
    except Exception:
        perms = []
    visible_extra_permissions = _filter_permissions_assignable_by_actor(perms)
    return render_template(
        "users/profile.html",
        user=current_user,
        visible_extra_permissions=visible_extra_permissions,
    )

@users_bp.route("/edit-profile", methods=["GET", "POST"], endpoint="edit_profile")
@login_required
def edit_profile():
    """تعديل الملف الشخصي للمستخدم الحالي"""
    # منع حسابات النظام من التعديل من هنا
    if getattr(current_user, 'is_system_account', False):
        flash("🚫 لا يمكن تعديل هذا الحساب من هنا. استخدم اللوحة السرية.", "danger")
        return redirect(url_for("main.dashboard"))

    from flask_wtf import FlaskForm
    from wtforms import StringField, SubmitField
    from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError
    
    class EditProfileForm(FlaskForm):
        username = StringField('اسم المستخدم', validators=[DataRequired(), Length(min=3, max=50)])
        email = StringField('البريد الإلكتروني', validators=[DataRequired(), Email()])
        submit = SubmitField('حفظ التعديلات')

        def validate_username(self, field):
            name = (field.data or '').strip()
            qry = User.query.filter(func.lower(User.username) == func.lower(name))
            qry = qry.filter(User.id != current_user.id)
            if qry.first():
                raise ValidationError("اسم المستخدم مستخدم بالفعل.")

        def validate_email(self, field):
            email_l = (field.data or '').strip().lower()
            qry = User.query.filter(func.lower(User.email) == email_l)
            qry = qry.filter(User.id != current_user.id)
            if qry.first():
                raise ValidationError("البريد الإلكتروني مستخدم بالفعل.")
            field.data = email_l
    
    form = EditProfileForm(obj=current_user)
    
    if form.validate_on_submit():
        try:
            current_user.username = form.username.data
            current_user.email = form.email.data
            db.session.commit()
            utils.flash_success("تم تحديث الملف الشخصي بنجاح")
            return redirect(url_for("users_bp.profile"))
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("اسم المستخدم أو البريد مستخدم بالفعل")
    
    return render_template("users/edit_profile.html", form=form)

@users_bp.route("/change-password", methods=["GET", "POST"], endpoint="change_password")
@login_required
def change_password():
    """تغيير كلمة المرور للمستخدم الحالي"""
    if getattr(current_user, 'is_system_account', False) or getattr(current_user, 'username', '') == '__OWNER__':
        flash("🚫 لا يمكن تغيير كلمة المرور لهذا الحساب من هنا", "danger")
        return redirect(url_for("main.dashboard"))
    from flask_wtf import FlaskForm
    from wtforms import PasswordField, SubmitField
    from wtforms.validators import DataRequired, Length, EqualTo, Regexp
    
    class ChangePasswordForm(FlaskForm):
        current_password = PasswordField('كلمة المرور الحالية', validators=[DataRequired()])
        new_password = PasswordField('كلمة المرور الجديدة', validators=[
            DataRequired(), 
            Length(min=8, max=128, message='كلمة المرور يجب أن تكون 8 أحرف على الأقل'),
            Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)|(?=.*[a-z])(?=.*\d)(?=.*[@$!%*?&#])|(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&#])', 
                   message='كلمة المرور يجب أن تحتوي على: أحرف وأرقام، أو أحرف ورموز خاصة')
        ])
        confirm_password = PasswordField('تأكيد كلمة المرور', validators=[DataRequired(), EqualTo('new_password', message='كلمات المرور غير متطابقة')])
        submit = SubmitField('تغيير كلمة المرور')
    
    form = ChangePasswordForm()
    
    if form.validate_on_submit():
        # التحقق من كلمة المرور الحالية
        if not current_user.check_password(form.current_password.data):
            utils.flash_error("كلمة المرور الحالية غير صحيحة")
        else:
            # تحديث كلمة المرور
            current_user.set_password(form.new_password.data)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                utils.flash_error(utils.MSG_SAVE_FAILED)
                return render_template("users/change_password.html", form=form)
            utils.flash_success("تم تغيير كلمة المرور بنجاح")
            return redirect(url_for("users_bp.profile"))
    
    return render_template("users/change_password.html", form=form)

@users_bp.route("/", methods=["GET"], endpoint="list_users")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def list_users():
    # استثناء حسابات النظام المخفية
    q = User.query.filter(User.is_system_account == False).options(joinedload(User.role))
    
    # Filter users based on role level
    # No user can see roles higher than them (Level < Actor Level)
    actor_level = _actor_level()
    
    if actor_level > 0:
        all_roles = Role.query.all()
        allowed_role_ids = []
        for r in all_roles:
            r_name = (r.name or "").strip()
            if is_deprecated_role_name(r_name):
                continue
            r_level = effective_role_level(r_name)
            
            # Allow seeing users with Same Level or Lower Level (Higher Number)
            if r_level >= actor_level:
                allowed_role_ids.append(r.id)
        
        if allowed_role_ids:
            q = q.filter(User.role_id.in_(allowed_role_ids))
        else:
            # If no roles allowed (shouldn't happen as user has a role), show nothing
            q = q.filter(func.random() < 0)

    term = request.args.get("search", "")
    if term:
        like = f"%{term}%"
        q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = q.order_by(User.username).paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items
    visible_extra_permissions_by_user: dict[int, list[Permission]] = {}
    for u in users:
        try:
            raw = u.extra_permissions
            perms = list(raw.all() if hasattr(raw, "all") else (raw or []))
        except Exception:
            perms = []
        visible_extra_permissions_by_user[u.id] = _filter_permissions_assignable_by_actor(perms)
    if request.args.get("format") == "json" or request.is_json:
        return jsonify({
            "data": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": (u.role.name if u.role else None),
                    "is_active": bool(u.is_active),
                    "created_at": (u.created_at.isoformat() if getattr(u, "created_at", None) else None),
                    "last_login": (u.last_login.isoformat() if getattr(u, "last_login", None) else None),
                    "last_seen": (u.last_seen.isoformat() if getattr(u, "last_seen", None) else None),
                    "last_login_ip": getattr(u, "last_login_ip", None),
                    "login_count": getattr(u, "login_count", None),
                    "extra_permissions": [p.name for p in (visible_extra_permissions_by_user.get(u.id) or [])]
                }
                for u in users
            ],
            "meta": {
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev
            }
        })
    args = request.args.to_dict(flat=True)
    args.pop("page", None)
    return render_template(
        "users/list.html",
        users=users,
        pagination=pagination,
        search=term,
        args=args,
        visible_extra_permissions_by_user=visible_extra_permissions_by_user,
    )


@users_bp.route("/registered-customers", methods=["GET"], endpoint="registered_customers")
@login_required
def registered_customers():
    q = Customer.query
    q = q.filter(Customer.is_online == True)
    term = (request.args.get("search") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(
            (Customer.name.ilike(like)) |
            (Customer.phone.ilike(like)) |
            (Customer.email.ilike(like))
        )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = q.order_by(Customer.name).paginate(page=page, per_page=per_page, error_out=False)
    customers = pagination.items
    if request.args.get("format") == "json" or request.is_json:
        return jsonify({
            "data": [
                {
                    "id": c.id,
                    "name": c.name,
                    "phone": c.phone,
                    "email": c.email,
                    "is_active": bool(c.is_active),
                    "is_online": bool(c.is_online),
                    "created_at": (c.created_at.isoformat() if getattr(c, "created_at", None) else None),
                }
                for c in customers
            ],
            "meta": {
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev
            }
        })
    args = request.args.to_dict(flat=True)
    args.pop("page", None)
    return render_template("users/registered_customers.html", customers=customers, pagination=pagination, search=term, args=args)

@users_bp.route("/<int:user_id>", methods=["GET"], endpoint="user_detail")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def user_detail(user_id):
    user = _get_or_404(User, user_id, load_options=[joinedload(User.role)])
    if getattr(user, 'is_system_account', False) or getattr(user, 'username', '') == '__OWNER__':
        abort(404)
    try:
        raw = user.extra_permissions
        perms = list(raw.all() if hasattr(raw, "all") else (raw or []))
    except Exception:
        perms = []
    visible_extra_permissions = _filter_permissions_assignable_by_actor(perms)
    return render_template(
        "users/detail.html",
        user=user,
        visible_extra_permissions=visible_extra_permissions,
    )

@users_bp.route("/api", methods=["GET"], endpoint="api_users")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def api_users():
    q = User.query.filter(User.is_system_account == False)
    term = request.args.get("q", "")
    if term:
        q = q.filter(User.username.ilike(f"%{term}%"))
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = q.order_by(User.username).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "results": [{"id": u.id, "text": u.username} for u in pagination.items],
        "pagination": {"more": pagination.has_next}
    })

@users_bp.route("/create", methods=["GET", "POST"], endpoint="create_user")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def create_user():
    form = UserForm()
    all_permissions = _filter_permissions_assignable_by_actor(Permission.query.order_by(Permission.name).all())
    selected_perm_ids = []
    if request.method == "POST":
        role_id_raw = request.form.get("role_id")
        if role_id_raw and str(role_id_raw).isdigit():
            posted_role = db.session.get(Role, int(role_id_raw))
            if posted_role is not None and (not _role_is_assignable_by_actor(posted_role)):
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(error="forbidden_role"), 403
                utils.flash_error("لا تملك الصلاحية لتعيين هذا الدور.")
                return redirect(url_for("users_bp.list_users"))
    if form.validate_on_submit():
        try:
            selected_perm_ids = [
                int(x) for x in request.form.getlist("extra_permissions") if str(x).isdigit()
            ]
            if not _actor_can_manage_users():
                abort(403)

            role = db.session.get(Role, form.role_id.data)
            if not _role_is_assignable_by_actor(role):
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(error="forbidden_role"), 403
                utils.flash_error("لا تملك الصلاحية لتعيين هذا الدور.")
                return redirect(url_for("users_bp.list_users"))

            if not _selected_permissions_allowed(selected_perm_ids):
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(error="forbidden_permissions"), 403
                utils.flash_error("لا يمكنك منح صلاحيات إضافية لا تملكها.")
                return redirect(url_for("users_bp.list_users"))

            user = User(
                username=form.username.data,
                email=form.email.data,
                role_id=form.role_id.data,
                is_active=bool(form.is_active.data),
            )
            raw_pwd = (form.password.data or "").strip()
            if raw_pwd:
                user.set_password(raw_pwd)
            else:
                user.set_password("123456")

            db.session.add(user)
            db.session.flush()

            if selected_perm_ids:
                user.extra_permissions = Permission.query.filter(
                    Permission.id.in_(selected_perm_ids)
                ).all()

            db.session.add(AuditLog(
                model_name="User",
                record_id=user.id,
                user_id=current_user.id,
                action="CREATE",
                old_data="",
                new_data=f"username={user.username}"
            ))

            db.session.commit()
            try:
                utils.clear_user_permission_cache(user.id)
            except Exception:
                current_app.logger.warning('DB commit failed silently')

            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(id=user.id, username=user.username), 201

            flash("تم إضافة المستخدم بنجاح.", "success")
            return redirect(url_for("users_bp.list_users"))

        except IntegrityError:
            db.session.rollback()
            flash("اسم المستخدم أو البريد الإلكتروني مستخدم.", "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('خطأ أثناء الإضافة', 'danger')

    return render_template(
        "users/form.html",
        form=form,
        action="create",
        user_id=None,
        all_permissions=all_permissions,
        selected_perm_ids=selected_perm_ids,
    )


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"], endpoint="edit_user")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def edit_user(user_id):
    user = _get_or_404(User, user_id)
    # حماية حسابات النظام من التعديل (كأنها غير موجودة)
    if getattr(user, 'is_system_account', False):
        abort(404)

    actor_level = _actor_level()
    target_role_name = str(getattr(getattr(user, "role", None), "name", "") or "").strip().lower()
    target_level = _role_level_by_name(target_role_name)

    # Allow Level 1 (Super Admin) to edit Level 1 users
    allowed = False
    if actor_level == 0:
        allowed = True
    elif actor_level == 1 and target_level >= 1:
        allowed = True
    elif target_level > actor_level:
        allowed = True
    
    if not allowed:
        abort(403)
    try:
        is_target_super = PermissionsRegistry.is_role_super(target_role_name)
    except Exception:
        is_target_super = False
    if not _actor_can_manage_super_level() and is_target_super:
        abort(403)

    if request.method == "POST":
        role_id_raw = request.form.get("role_id")
        if role_id_raw and str(role_id_raw).isdigit():
            posted_role = db.session.get(Role, int(role_id_raw))
            if posted_role is not None and (not _role_is_assignable_by_actor(posted_role)):
                utils.flash_error("لا يمكنك تعيين دور أعلى أو مساوٍ لصلاحياتك.")
                return redirect(url_for("users_bp.list_users"))

    form = UserForm(obj=user)
    all_permissions = _filter_permissions_assignable_by_actor(Permission.query.order_by(Permission.name).all())
    selected_perm_ids = [p.id for p in user.extra_permissions.all()]

    if request.method == "GET":
        form.role_id.data = user.role_id
        form.is_active.data = bool(user.is_active)

    if form.validate_on_submit():
        try:
            selected_perm_ids = [
                int(x) for x in request.form.getlist("extra_permissions") if str(x).isdigit()
            ]

            role = db.session.get(Role, form.role_id.data)
            if not _role_is_assignable_by_actor(role):
                utils.flash_error("لا يمكنك تعيين دور أعلى أو مساوٍ لصلاحياتك.")
                return redirect(url_for("users_bp.list_users"))

            if not _selected_permissions_allowed(selected_perm_ids):
                utils.flash_error("لا يمكنك منح صلاحيات إضافية لا تملكها.")
                return redirect(url_for("users_bp.list_users"))

            old_data = f"{user.username},{user.email}"

            user.username = form.username.data
            user.email = form.email.data
            user.role_id = form.role_id.data
            user.is_active = bool(form.is_active.data)

            if form.password.data:
                user.set_password(form.password.data)

            user.extra_permissions = Permission.query.filter(
                Permission.id.in_(selected_perm_ids)
            ).all() if selected_perm_ids else []

            db.session.add(AuditLog(
                model_name="User",
                record_id=user.id,
                user_id=current_user.id,
                action="UPDATE",
                old_data=old_data,
                new_data=f"username={user.username}"
            ))

            db.session.commit()
            try:
                utils.clear_user_permission_cache(user.id)
            except Exception:
                current_app.logger.warning('DB commit failed silently')

            flash("تم تحديث المستخدم.", "success")
            return redirect(url_for("users_bp.list_users"))

        except IntegrityError:
            db.session.rollback()
            flash("لا يمكن استخدام هذا البريد/الاسم.", "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('خطأ أثناء التحديث', 'danger')

    return render_template(
        "users/form.html",
        form=form,
        action="edit",
        user_id=user_id,
        all_permissions=all_permissions,
        selected_perm_ids=selected_perm_ids,
    )

@users_bp.route("/<int:user_id>/delete", methods=["POST"], endpoint="delete_user")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_USERS)
def delete_user(user_id):
    user = _get_or_404(User, user_id)
    
    # حماية حسابات النظام من الحذف
    if getattr(user, 'is_system_account', False) or user.username == '__OWNER__':
        utils.flash_error("لا يمكن حذف حساب النظام المحمي!")
        return redirect(url_for("users_bp.list_users"))
    actor_level = _actor_level()
    target_role_name = str(getattr(getattr(user, "role", None), "name", "") or "").strip().lower()
    target_level = _role_level_by_name(target_role_name)
    
    can_delete = False
    if actor_level == 0:
        can_delete = True
    elif actor_level == 1 and target_level >= 1:
        can_delete = True
    elif target_level >= actor_level:
        can_delete = True
        
    if not can_delete:
        abort(403)

    try:
        is_target_super = PermissionsRegistry.is_role_super(target_role_name)
    except Exception:
        is_target_super = False
    if not _actor_can_manage_super_level() and is_target_super:
        if not (actor_level == 1 and target_level >= 1):
             abort(403)
    if user.id == current_user.id:
        utils.flash_error("لا يمكن حذف حسابك الحالي.")
        return redirect(url_for("users_bp.list_users"))
    if user.email == current_app.config.get("DEV_EMAIL", "rafideen.ahmadghannam@gmail.com"):
        utils.flash_error("لا يمكن حذف حساب المطور الأساسي.")
        return redirect(url_for("users_bp.list_users"))

    try:
        old_data = f"{user.username},{user.email}"

        user.extra_permissions = []
        db.session.flush()
        db.session.delete(user)

        db.session.add(AuditLog(
            model_name="User",
            record_id=user_id,
            user_id=current_user.id,
            action="DELETE",
            old_data=old_data,
            new_data=""
        ))

        db.session.commit()
        # clear_user_permission_cache(user_id)  # Commented out - function not available
        flash("تم حذف المستخدم.", "warning")

    except IntegrityError:
        db.session.rollback()
        flash("لا يمكن حذف المستخدم لوجود معاملات مرتبطة به.", "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ أثناء الحذف', 'danger')

    return redirect(url_for("users_bp.list_users"))
