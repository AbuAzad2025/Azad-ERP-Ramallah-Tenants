"""امتثال ضريبي — تسوية VAT وإقرار."""
import csv
import io
from datetime import date, datetime

from flask import Blueprint, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import login_required

from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.vat_settlement_service import (
    vat_settlement_for_period,
    post_vat_settlement_gl,
    vat_declaration_rows,
)

tax_compliance_bp = Blueprint("tax_compliance_bp", __name__, url_prefix="/tax-compliance")


@tax_compliance_bp.route("/vat-settlement")
@login_required
@permission_required(SystemPermissions.MANAGE_TAX_COMPLIANCE)
def vat_settlement():
    start = request.args.get("start_date") or date.today().replace(day=1).isoformat()
    end = request.args.get("end_date") or date.today().isoformat()
    start_dt = datetime.combine(date.fromisoformat(start), datetime.min.time())
    end_dt = datetime.combine(date.fromisoformat(end), datetime.max.time())
    data = vat_settlement_for_period(start_dt, end_dt)
    if request.args.get("format") == "json":
        return jsonify({"success": True, "period": {"start": start, "end": end}, **data})
    return render_template(
        "tax_compliance/vat_settlement.html",
        start_date=start,
        end_date=end,
        data=data,
    )


@tax_compliance_bp.route("/vat-settlement/export")
@login_required
@permission_required(SystemPermissions.MANAGE_TAX_COMPLIANCE)
def vat_export():
    start = request.args.get("start_date") or date.today().replace(day=1).isoformat()
    end = request.args.get("end_date") or date.today().isoformat()
    start_dt = datetime.combine(date.fromisoformat(start), datetime.min.time())
    end_dt = datetime.combine(date.fromisoformat(end), datetime.max.time())
    rows = vat_declaration_rows(start_dt, end_dt)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["البيان", "المبلغ"])
    for r in rows:
        w.writerow([r["field"], r["amount"]])
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = f'attachment; filename="vat_declaration_{start}_{end}.csv"'
    return resp


@tax_compliance_bp.route("/vat-settlement/post", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_TAX_COMPLIANCE)
def vat_post_gl():
    start = request.form.get("start_date") or date.today().replace(day=1).isoformat()
    end = request.form.get("end_date") or date.today().isoformat()
    start_dt = datetime.combine(date.fromisoformat(start), datetime.min.time())
    end_dt = datetime.combine(date.fromisoformat(end), datetime.max.time())
    branch_id = request.form.get("branch_id", type=int)
    try:
        batch_id = post_vat_settlement_gl(start_dt, end_dt, branch_id=branch_id)
        flash(f"تم ترحيل تسوية VAT — قيد #{batch_id}", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("tax_compliance_bp.vat_settlement", start_date=start, end_date=end))
