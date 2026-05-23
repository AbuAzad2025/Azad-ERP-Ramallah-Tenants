
from flask import Blueprint, render_template

from utils.branding_scope import require_platform_console

pricing_bp = Blueprint("pricing", __name__, url_prefix="/pricing")


@pricing_bp.before_request
def _platform_pricing_only():
    return require_platform_console()


@pricing_bp.route("/", methods=["GET"], endpoint="index")
def pricing_index():
    """صفحة الأسعار"""
    return render_template("pricing/index.html")
