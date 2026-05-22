"""
إدارة الفترات المحاسبية — منصة أزاد (public فقط).
"""
from flask import Blueprint
from flask_login import login_required

from permissions_config.enums import SystemPermissions
from routes import fiscal_period_shared as shared
from utils import permission_required
from utils.branding_scope import require_platform_console

fiscal_periods_bp = Blueprint(
    "fiscal_periods_bp", __name__, url_prefix="/security/fiscal-periods"
)


@fiscal_periods_bp.before_request
def _platform_only():
    return require_platform_console()


@fiscal_periods_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def index():
    return shared.render_index(endpoint_prefix="fiscal_periods_bp")


@fiscal_periods_bp.route("/api/list")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_list():
    return shared.api_list()


@fiscal_periods_bp.route("/api/sync", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_sync():
    return shared.api_sync()


@fiscal_periods_bp.route("/api/<int:period_id>/preview-close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_preview_close(period_id):
    return shared.api_preview_close(period_id)


@fiscal_periods_bp.route("/api/<int:period_id>/close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_close(period_id):
    return shared.api_close(period_id)


@fiscal_periods_bp.route("/api/<int:period_id>/reopen", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_reopen(period_id):
    return shared.api_reopen(period_id)


@fiscal_periods_bp.route("/api/<int:period_id>/snapshots")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_snapshots(period_id):
    return shared.api_snapshots(period_id)


@fiscal_periods_bp.route("/api/settings", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_settings():
    return shared.api_settings()
