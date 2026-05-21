from flask import Blueprint, render_template, g, abort, url_for, redirect
from flask_login import login_required, current_user


tenant_console_bp = Blueprint("tenant_console", __name__, url_prefix="/console")


@tenant_console_bp.route("/", endpoint="index")
@login_required
def index():
    if not getattr(g, "tenant_slug", None):
        return abort(404)
    if not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login"))
    return render_template("tenant_console/index.html")

