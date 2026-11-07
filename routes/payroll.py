"""مسيرات الرواتب."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import PayrollRun, PayrollLine, Branch, Employee
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.company_scope import filter_by_branches
from utils.tenant_ui import accessible_branches_query
from utils.payroll_service import build_payroll_run, post_payroll_gl

payroll_bp = Blueprint("payroll_bp", __name__, url_prefix="/payroll")


@payroll_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_PAYROLL)
def index():
    q = PayrollRun.query.order_by(PayrollRun.period_key.desc())
    q = filter_by_branches(q, PayrollRun.branch_id)
    runs = q.limit(100).all()
    branches = accessible_branches_query().all()
    return render_template("payroll/index.html", runs=runs, branches=branches)


@payroll_bp.route("/generate", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYROLL)
def generate():
    period_key = request.form.get("period_key") or date.today().strftime("%Y-%m")
    branch_id = request.form.get("branch_id", type=int)
    if not branch_id:
        flash("اختر الفرع", "warning")
        return redirect(url_for("payroll_bp.index"))
    try:
        run = build_payroll_run(period_key, branch_id)
        db.session.commit()
        flash(f"تم إنشاء مسير {period_key} — صافي {float(run.total_net):,.2f}", "success")
        return redirect(url_for("payroll_bp.detail", id=run.id))
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("payroll_bp.index"))


@payroll_bp.route("/<int:id>")
@login_required
@permission_required(SystemPermissions.MANAGE_PAYROLL)
def detail(id):
    run = db.session.get(PayrollRun, id) or abort(404)
    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
    for ln in lines:
        ln.employee_name = ln.employee.name if ln.employee else ""
    return render_template("payroll/detail.html", run=run, lines=lines)


@payroll_bp.route("/<int:id>/post", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYROLL)
def post_gl(id):
    try:
        post_payroll_gl(id)
        flash("تم ترحيل مسير الرواتب إلى GL", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("payroll_bp.detail", id=id))
