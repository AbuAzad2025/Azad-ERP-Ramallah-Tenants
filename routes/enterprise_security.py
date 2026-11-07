"""أمان مؤسسي: 2FA، قفل تواريخ الإدخال."""
import json

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from extensions import db
from models import SystemSettings, User
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.totp_util import generate_secret, totp_code, verify_totp

enterprise_security_bp = Blueprint(
    "enterprise_security_bp", __name__, url_prefix="/security/enterprise"
)


@enterprise_security_bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    user = db.session.get(User, current_user.id)
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        secret = session.get("pending_totp_secret") or user.totp_secret
        if secret and verify_totp(secret, code):
            user.totp_secret = secret
            user.totp_enabled = True
            session.pop("pending_totp_secret", None)
            db.session.commit()
            flash("تم تفعيل المصادقة الثنائية", "success")
            return redirect(url_for("users.edit_profile"))
        flash("رمز غير صحيح", "danger")
    if not user.totp_secret:
        secret = generate_secret()
        session["pending_totp_secret"] = secret
    else:
        secret = session.get("pending_totp_secret") or user.totp_secret
    current_code = totp_code(secret) if secret else ""
    return render_template(
        "security/enterprise_2fa_setup.html",
        secret=secret,
        current_code=current_code,
        enabled=bool(user.totp_enabled),
    )


@enterprise_security_bp.route("/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    user = db.session.get(User, current_user.id)
    code = request.form.get("code", "").strip()
    if user.totp_secret and verify_totp(user.totp_secret, code):
        user.totp_enabled = False
        user.totp_secret = None
        db.session.commit()
        flash("تم إيقاف المصادقة الثنائية", "info")
    else:
        flash("رمز غير صحيح", "danger")
    return redirect(url_for("enterprise_security_bp.setup_2fa"))


@enterprise_security_bp.route("/posting-controls", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def posting_controls():
    if request.method == "POST":
        locked = request.form.get("posting_locked_before") or ""
        SystemSettings.set_setting(
            "posting_locked_before",
            locked or None,
            "آخر تاريخ مسموح للإدخال (قبله مقفول)",
            "date",
        )
        block_print = request.form.get("block_document_print") == "on"
        SystemSettings.set_setting(
            "block_document_print",
            "true" if block_print else "false",
            "منع طباعة المستندات الحساسة بدون صلاحية",
            "boolean",
        )
        SystemSettings.set_setting(
            "password_policy_enabled",
            "true" if request.form.get("password_policy_enabled") == "on" else "false",
            "تفعيل سياسة كلمة المرور",
            "boolean",
        )
        db.session.commit()
        flash("تم حفظ ضوابط الإدخال", "success")
    locked = SystemSettings.get_setting("posting_locked_before", "")
    block_print = str(SystemSettings.get_setting("block_document_print", "false")).lower() in ("true", "1", "yes")
    pwd_policy = str(SystemSettings.get_setting("password_policy_enabled", "true")).lower() in ("true", "1", "yes")
    return render_template(
        "security/posting_controls.html",
        posting_locked_before=locked or "",
        block_document_print=block_print,
        password_policy_enabled=pwd_policy,
    )
