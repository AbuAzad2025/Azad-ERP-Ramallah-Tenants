"""بوابة الموظف — كشف راتب وملخص HR."""
from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from extensions import db
from models import Employee, PayrollLine, PayrollRun
from permissions_config.enums import SystemPermissions
from utils import permission_required

hr_portal_bp = Blueprint("hr_portal_bp", __name__, url_prefix="/hr-portal")


def _employee_for_user():
    email = (getattr(current_user, "email", None) or "").strip().lower()
    if not email:
        return None
    return Employee.query.filter(db.func.lower(Employee.email) == email).first()


@hr_portal_bp.route("/")
@login_required
@permission_required(SystemPermissions.VIEW_PAYROLL)
def index():
    emp = _employee_for_user()
    if not emp:
        return render_template("hr_portal/no_employee.html")
    lines = (
        PayrollLine.query.join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .filter(PayrollLine.employee_id == emp.id)
        .order_by(PayrollRun.period_key.desc())
        .limit(24)
        .all()
    )
    return render_template("hr_portal/index.html", employee=emp, lines=lines)


@hr_portal_bp.route("/payslip/<int:line_id>")
@login_required
@permission_required(SystemPermissions.VIEW_PAYROLL)
def payslip(line_id):
    emp = _employee_for_user()
    if not emp:
        abort(403)
    line = db.session.get(PayrollLine, line_id) or abort(404)
    if line.employee_id != emp.id:
        abort(403)
    run = db.session.get(PayrollRun, line.payroll_run_id) or abort(404)
    return render_template("hr_portal/payslip.html", employee=emp, line=line, run=run)
