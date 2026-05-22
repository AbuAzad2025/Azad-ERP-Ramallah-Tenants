from flask import Blueprint, render_template, g, abort, redirect, request, flash, url_for
from flask_login import login_required, current_user

from utils.branding_scope import SCOPE_TENANT, require_tenant_owner_console
from utils.owner_hubs import TENANT_HUB_SECTIONS, TENANT_OWNER_TAGLINE
from utils.print_branding import (
    load_tenant_branding_form,
    save_tenant_branding_from_form,
    resolve_print_settings,
    LETTERHEAD_MODE_KEY,
)


tenant_console_bp = Blueprint("tenant_console", __name__, url_prefix="/console")


def _tenant_hub_sections():
    from utils.branding_assets import is_tenant_session_user

    if is_tenant_session_user():
        return TENANT_HUB_SECTIONS
    filtered = []
    for section in TENANT_HUB_SECTIONS:
        if section["id"] == "brand":
            continue
        filtered.append(section)
    return tuple(filtered)


@tenant_console_bp.route("/", endpoint="index")
@login_required
def index():
    if not getattr(g, "tenant_slug", None):
        abort(404)
    if not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login"))
    return render_template(
        "tenant_console/index.html",
        hub_sections=_tenant_hub_sections(),
        hub_tagline=TENANT_OWNER_TAGLINE,
    )


@tenant_console_bp.route("/branding", methods=["GET", "POST"], endpoint="branding")
@login_required
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
            flash("حدث خطأ أثناء الحفظ.", "danger")
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
