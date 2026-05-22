"""
إقفال الفترات المحاسبية — داخل تينانت (/t/<slug>/console/fiscal-periods).
بيانات منفصلة في schema التينانت (ليست public المشتركة).
"""
from flask import Blueprint, g
from flask_login import login_required

from permissions_config.enums import SystemPermissions
from routes import fiscal_period_shared as shared
from utils import permission_required
from utils.branding_scope import require_tenant_owner_console
from utils.tenant_fiscal_schema import ensure_fiscal_tables_for_request

tenant_fiscal_bp = Blueprint(
    "tenant_fiscal_bp",
    __name__,
    url_prefix="/console/fiscal-periods",
)


@tenant_fiscal_bp.before_request
def _tenant_fiscal_guard():
    slug = (getattr(g, "tenant_slug", None) or "").strip().lower()
    guard = require_tenant_owner_console(expected_slug=slug)
    if guard is not None:
        return guard
    ensure_fiscal_tables_for_request()
    return None


@tenant_fiscal_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def index():
    slug = (getattr(g, "tenant_slug", None) or "").strip().lower()
    return shared.render_index(endpoint_prefix="tenant_fiscal_bp", tenant_slug=slug)


@tenant_fiscal_bp.route("/api/list")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_list():
    return shared.api_list()


@tenant_fiscal_bp.route("/api/sync", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_sync():
    return shared.api_sync()


@tenant_fiscal_bp.route("/api/<int:period_id>/preview-close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_preview_close(period_id):
    return shared.api_preview_close(period_id)


@tenant_fiscal_bp.route("/api/<int:period_id>/close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_close(period_id):
    return shared.api_close(period_id)


@tenant_fiscal_bp.route("/api/<int:period_id>/reopen", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_reopen(period_id):
    return shared.api_reopen(period_id)


@tenant_fiscal_bp.route("/api/<int:period_id>/snapshots")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_snapshots(period_id):
    return shared.api_snapshots(period_id)


@tenant_fiscal_bp.route("/api/settings", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_settings():
    return shared.api_settings()
