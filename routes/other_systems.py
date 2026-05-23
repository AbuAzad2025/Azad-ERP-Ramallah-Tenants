
from flask import Blueprint, render_template

from utils.branding_scope import require_platform_console

other_systems_bp = Blueprint("other_systems", __name__, url_prefix="/other-systems")


@other_systems_bp.before_request
def _platform_other_systems_only():
    return require_platform_console()


@other_systems_bp.route("/", methods=["GET"], endpoint="index")
def other_systems_index():
    """صفحة أنظمتنا الأخرى"""
    return render_template("other_systems/index.html")
