"""
مركز المحاسبة — لوحة سريعة، تحصيل، إعدادات سياسة، تقارير شركة.
"""
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required

from extensions import db
from models import Company, Customer, Payment, SystemSettings, FiscalPeriod
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.company_reports import company_dashboard
from utils.company_scope import default_company, get_accessible_company_ids
from utils.payment_allocation_policy import payment_auto_allocate_enabled
from utils.payment_allocation_service import list_open_documents_for_customer, apply_manual_allocations
from utils.balance_calculator import build_customer_balance_view

accounting_hub_bp = Blueprint("accounting_hub_bp", __name__, url_prefix="/accounting-hub")


@accounting_hub_bp.route("/")
@login_required
@permission_required(SystemPermissions.VIEW_REPORTS)
def index():
    from utils.company_scope import get_accessible_company_ids

    companies_q = Company.query.filter_by(is_active=True).order_by(Company.name)
    allowed_co = get_accessible_company_ids()
    if allowed_co is not None:
        if not allowed_co:
            companies = []
        else:
            companies = companies_q.filter(Company.id.in_(allowed_co)).all()
    else:
        companies = companies_q.all()
    cid = request.args.get("company_id", type=int)
    if cid and allowed_co is not None and cid not in allowed_co:
        cid = None
    if not cid and companies:
        cid = companies[0].id
    dash = None
    if cid:
        try:
            dash = company_dashboard(cid)
        except Exception:
            dash = None
    open_periods = FiscalPeriod.query.filter_by(status="OPEN").order_by(FiscalPeriod.end_date.desc()).limit(5).all()
    return render_template(
        "accounting_hub/index.html",
        companies=companies,
        company_id=cid,
        dashboard=dash,
        open_periods=open_periods,
        auto_allocate=payment_auto_allocate_enabled(),
    )


@accounting_hub_bp.route("/collect", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def collect():
    """تحصيل سريع — زبون + عرض رصيد + رابط دفعة."""
    customer = None
    balance_view = None
    if request.method == "GET":
        cid = request.args.get("customer_id", type=int)
        if cid:
            customer = db.session.get(Customer, cid)
            if customer:
                balance_view = build_customer_balance_view(cid, db.session)
    return render_template(
        "accounting_hub/collect.html",
        customer=customer,
        balance_view=balance_view,
    )


@accounting_hub_bp.route("/settings", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def settings():
    if request.method == "POST":
        SystemSettings.set_setting(
            "auto_allocate",
            bool(request.form.get("auto_allocate")),
            data_type="boolean",
        )
        SystemSettings.set_setting(
            "annual_carry_updates_opening_balance",
            bool(request.form.get("annual_carry_updates_opening_balance")),
            data_type="boolean",
        )
        flash("تم حفظ إعدادات المحاسبة", "success")
        return redirect(url_for("accounting_hub_bp.settings"))
    return render_template(
        "accounting_hub/settings.html",
        auto_allocate=bool(SystemSettings.get_setting("auto_allocate", False)),
        annual_carry=bool(SystemSettings.get_setting("annual_carry_updates_opening_balance", False)),
        payment_allocation_env=payment_auto_allocate_enabled(),
    )


@accounting_hub_bp.route("/allocate/<int:payment_id>", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def allocate_payment(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        flash("الدفعة غير موجودة", "danger")
        return redirect(url_for("accounting_hub_bp.index"))
    customer_id = payment.customer_id
    if not customer_id:
        flash("الدفعة غير مرتبطة بزبون", "warning")
        return redirect(url_for("payments.index"))

    open_docs = list_open_documents_for_customer(customer_id)

    if request.method == "POST":
        lines = []
        for key in request.form:
            if key.startswith("alloc_") and request.form.get(key):
                parts = key.split("_")
                if len(parts) >= 3:
                    lines.append({
                        "entity_type": parts[1],
                        "entity_id": int(parts[2]),
                        "amount": request.form.get(key),
                    })
        try:
            apply_manual_allocations(payment_id, lines)
            flash("تم حفظ التوزيع اليدوي", "success")
            return redirect(url_for("accounting_hub_bp.allocate_payment", payment_id=payment_id))
        except ValueError as e:
            flash(str(e), "danger")

    existing = [
        {
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "amount": float(a.amount),
        }
        for a in payment.allocations.all()
    ]
    return render_template(
        "accounting_hub/allocate.html",
        payment=payment,
        open_docs=open_docs,
        existing=existing,
    )


@accounting_hub_bp.route("/company/<int:company_id>/api")
@login_required
@permission_required(SystemPermissions.VIEW_REPORTS)
def company_api(company_id):
    try:
        return jsonify({"success": True, **company_dashboard(company_id)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
