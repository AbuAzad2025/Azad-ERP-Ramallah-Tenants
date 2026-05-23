from flask import Blueprint, render_template, g, abort, redirect, request, flash, url_for
from flask_login import login_required, current_user

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


@tenant_console_bp.route("/", endpoint="index")
@login_required
@permission_required(SystemPermissions.ACCESS_TENANT_CONSOLE)
def index():
    if not getattr(g, "tenant_slug", None):
        abort(404)
    return render_template(
        "tenant_console/index.html",
        hub_sections=_tenant_hub_sections(),
        hub_tagline=TENANT_OWNER_TAGLINE,
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
            m = int(request.form.get("fiscal_year_start_month") or 1)
            m = max(1, min(12, m))
            SystemSettings.set_setting("fiscal_year_start_month", m, data_type="integer")
            flash("تم حفظ إعدادات المحاسبة.", "success")
        except (TypeError, ValueError):
            flash("قيمة شهر بداية السنة غير صالحة.", "danger")
        return redirect(url_for("tenant_console.business_settings"))

    fy_month = int(get_scoped_setting("fiscal_year_start_month", 1) or 1)
    return render_template(
        "tenant_console/business_settings.html",
        fiscal_year_start_month=fy_month,
    )
