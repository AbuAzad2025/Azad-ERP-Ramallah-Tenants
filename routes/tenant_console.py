import json

from flask import Blueprint, render_template, g, abort, redirect, request, flash, url_for, current_app
from flask_login import login_required, current_user

import utils
from extensions import db
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.branding_scope import SCOPE_TENANT, require_tenant_owner_console
from utils.owner_hubs import TENANT_HUB_SECTIONS, TENANT_OWNER_TAGLINE
from utils.print_branding import (
    load_tenant_branding_form,
    save_tenant_branding_from_form,
    resolve_print_settings,
    LETTERHEAD_MODE_KEY,
)
from utils.tenant_permissions import filter_hub_sections


tenant_console_bp = Blueprint("tenant_console", __name__, url_prefix="/console")


def _tenant_hub_sections():
    from utils.branding_assets import is_tenant_session_user

    owner = is_tenant_session_user()
    sections = []
    for section in TENANT_HUB_SECTIONS:
        if section.get("owner_only") and not owner:
            continue
        sections.append(section)
    if getattr(current_user, "is_authenticated", False):
        return filter_hub_sections(tuple(sections), current_user)
    return tuple(sections)


def _log_tenant_control(action: str, meta: dict | None = None) -> None:
    from models import AuditLog

    try:
        db.session.add(
            AuditLog(
                model_name="TenantControl",
                record_id=0,
                user_id=getattr(current_user, "id", None),
                action=f"owner_control.{action}",
                new_data=json.dumps(meta or {}, ensure_ascii=False, default=str)[:4000],
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("tenant control audit log failed")


def _tenant_owner_write_allowed() -> bool:
    from utils.branding_assets import is_tenant_session_user

    if is_tenant_session_user():
        return True
    flash("هذا الإجراء الإداري لمالك التينانت فقط (جلسة owner).", "danger")
    return False


def _dispatch_tenant_control(action: str) -> dict:
    from utils import owner_control_service as ocs

    limit = min(500, max(10, request.form.get("limit", 200, type=int)))
    action = (action or "").strip().lower()

    if action == "integration_audit":
        return ocs.run_integration_audit_report()

    if action == "accounting_audit":
        return ocs.run_accounting_audit(limit=limit, fix=False, fix_policy=False)

    if action == "accounting_audit_fix":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.run_accounting_audit(limit=limit, fix=True, fix_policy=False)

    if action == "fix_payment_policy":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.run_accounting_audit(limit=0, fix=False, fix_policy=True)

    if action == "sync_balances_preview":
        return ocs.sync_entity_balances(entity="all", limit=limit, dry_run=True)

    if action == "sync_balances":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.sync_entity_balances(entity="all", limit=limit, dry_run=False)

    if action == "fix_sale_obligations":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        dry = request.form.get("dry_run") == "1"
        return ocs.run_fix_sale_obligations(dry_run=dry)

    if action == "fiscal_sync":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.run_fiscal_period_sync()

    if action == "ensure_fiscal_tables":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.ensure_tenant_fiscal_tables()

    if action == "sync_owner_permissions":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.sync_tenant_owner_permissions()

    if action == "clear_rbac_cache":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        return ocs.clear_rbac_caches()

    if action == "user_activate":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        uid = request.form.get("user_id", type=int)
        return ocs.set_user_active(uid, active=True)

    if action == "user_block":
        if not _tenant_owner_write_allowed():
            return {"ok": False, "error": "غير مصرح"}
        uid = request.form.get("user_id", type=int)
        return ocs.set_user_active(uid, active=False)

    return {"ok": False, "error": f"إجراء غير معروف: {action}"}


@tenant_console_bp.route("/control", methods=["GET", "POST"], endpoint="control")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def control():
    """مركز التحكم الإداري لمالك التينانت — تنفيذ وليس عرض فقط."""
    if not getattr(g, "tenant_slug", None):
        abort(404)
    from utils.branding_assets import is_tenant_session_user
    from utils.owner_control_service import list_tenant_users_for_control

    control_result = None
    last_action = None

    if request.method == "POST":
        last_action = (request.form.get("control_action") or "").strip()
        try:
            control_result = _dispatch_tenant_control(last_action)
            _log_tenant_control(last_action, {"result": control_result})
            if control_result.get("ok", True) and not control_result.get("error"):
                flash("تم تنفيذ الإجراء بنجاح.", "success")
            else:
                flash(
                    control_result.get("error")
                    or control_result.get("text")
                    or "اكتمل الإجراء مع ملاحظات — راجع التفاصيل.",
                    "warning" if control_result.get("ok") else "danger",
                )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("tenant control action failed: %s", last_action)
            flash(f"فشل الإجراء: {exc}", "danger")
            control_result = {"ok": False, "error": str(exc)}

    return render_template(
        "tenant_console/control.html",
        hub_tagline=TENANT_OWNER_TAGLINE,
        is_owner_session=is_tenant_session_user(),
        team_users=list_tenant_users_for_control(80),
        control_result=control_result,
        last_action=last_action,
    )


@tenant_console_bp.route("/", endpoint="index")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def index():
    if not getattr(g, "tenant_slug", None):
        abort(404)
    slug = g.tenant_slug
    from utils.tenant_owner_dashboard import (
        build_tenant_alerts,
        build_tenant_quick_actions,
        get_tenant_owner_stats,
        get_tenant_recent_audit,
        get_tenant_registry_meta,
    )

    tenant_meta = get_tenant_registry_meta(slug)
    owner_stats = get_tenant_owner_stats(slug)
    owner_stats["is_active"] = tenant_meta.get("is_active", True)
    return render_template(
        "tenant_console/index.html",
        hub_sections=_tenant_hub_sections(),
        hub_tagline=TENANT_OWNER_TAGLINE,
        control_url=url_for("tenant_console.control"),
        owner_stats=owner_stats,
        tenant_meta=tenant_meta,
        tenant_alerts=build_tenant_alerts(owner_stats),
        quick_actions=build_tenant_quick_actions(current_user),
        recent_audit=get_tenant_recent_audit(12),
    )


@tenant_console_bp.route("/activity", endpoint="activity")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def activity():
    if not getattr(g, "tenant_slug", None):
        abort(404)
    from models import AuditLog, User
    from sqlalchemy.orm import joinedload

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 40
    q = AuditLog.query.options(joinedload(AuditLog.user)).order_by(
        AuditLog.created_at.desc()
    )
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "tenant_console/activity.html",
        audit_logs=pagination.items,
        pagination=pagination,
    )


@tenant_console_bp.route("/branding", methods=["GET", "POST"], endpoint="branding")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def branding():
    guard = require_tenant_owner_console(expected_slug=g.tenant_slug)
    if guard is not None:
        return guard
    slug = g.tenant_slug
    if request.method == "POST":
        posted_scope = (request.form.get("branding_scope") or "").strip()
        if posted_scope != SCOPE_TENANT:
            flash("نطاق الحفظ غير صالح.", "danger")
            return redirect(url_for("tenant_console.branding"))
        try:
            save_tenant_branding_from_form(slug, request.form, request.files)
            flash("تم حفظ الهوية والترويسة.", "success")
        except (ValueError, PermissionError) as e:
            flash(str(e), "warning")
        except Exception:
            from flask import current_app
            from extensions import db

            db.session.rollback()
            current_app.logger.exception("tenant branding save failed")
            utils.flash_error(utils.MSG_SAVE_FAILED)
        return redirect(url_for("tenant_console.branding"))

    profile = load_tenant_branding_form(slug)
    preview = resolve_print_settings(tenant_slug=slug)
    return render_template(
        "tenant_console/branding.html",
        profile=profile,
        preview=preview,
        letterhead_mode_key=LETTERHEAD_MODE_KEY,
        branding_scope=SCOPE_TENANT,
    )


@tenant_console_bp.route("/business-settings", methods=["GET", "POST"], endpoint="business_settings")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def business_settings():
    """ثوابت محاسبية للتينانت (سنة مالية، إلخ) — داخل schema الشركة فقط."""
    guard = require_tenant_owner_console(expected_slug=g.tenant_slug)
    if guard is not None:
        return guard
    from models import SystemSettings
    from utils.print_branding import get_scoped_setting

    if request.method == "POST":
        try:
            raw_m = request.form.get("fiscal_year_start_month") or 1
            m = int(float(str(raw_m).strip()))
            m = max(1, min(12, m))
            SystemSettings.set_setting("fiscal_year_start_month", m, data_type="integer")
            flash("تم حفظ إعدادات المحاسبة.", "success")
        except (TypeError, ValueError):
            flash("قيمة شهر بداية السنة غير صالحة.", "danger")
        return redirect(url_for("tenant_console.business_settings"))

    raw_fy = get_scoped_setting("fiscal_year_start_month", 1) or 1
    try:
        fy_month = int(float(str(raw_fy).strip()))
    except (TypeError, ValueError):
        fy_month = 1
    fy_month = max(1, min(12, fy_month))
    return render_template(
        "tenant_console/business_settings.html",
        fiscal_year_start_month=fy_month,
    )
