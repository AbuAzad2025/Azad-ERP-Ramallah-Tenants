"""إدارة الشركات داخل التينانت — كيان قانوني."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from extensions import db
from models import Branch, Company
from permissions_config.enums import SystemPermissions
from utils import permission_required

companies_bp = Blueprint("companies_bp", __name__, url_prefix="/companies")


@companies_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def index():
    from utils.company_scope import filter_companies_query

    q = filter_companies_query(Company.query).order_by(Company.is_active.desc(), Company.name)
    companies = q.all()
    for c in companies:
        c.branches_count = Branch.query.filter_by(company_id=c.id).count()
    return render_template("companies/index.html", companies=companies)


@companies_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def add():
    if request.method == "POST":
        code = (request.form.get("code") or "").strip().upper()
        name = (request.form.get("name") or "").strip()
        if not code or not name:
            flash("الرمز والاسم مطلوبان", "danger")
            return redirect(request.url)
        if Company.query.filter_by(code=code).first():
            flash("رمز الشركة مستخدم", "danger")
            return redirect(request.url)
        c = Company(
            code=code,
            name=name,
            legal_name=request.form.get("legal_name") or name,
            tax_id=request.form.get("tax_id"),
            currency=request.form.get("currency") or "ILS",
            fiscal_year_start_month=request.form.get("fiscal_year_start_month", 1, type=int) or 1,
            address=request.form.get("address"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            notes=request.form.get("notes"),
            is_active=True,
        )
        db.session.add(c)
        db.session.commit()
        flash("تمت إضافة الشركة", "success")
        return redirect(url_for("companies_bp.index"))
    return render_template("companies/form.html", company=None)


@companies_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def edit(id):
    from utils.company_scope import assert_company_access

    assert_company_access(id)
    company = db.session.get(Company, id) or abort(404)
    if request.method == "POST":
        company.name = (request.form.get("name") or company.name).strip()
        company.legal_name = request.form.get("legal_name")
        company.tax_id = request.form.get("tax_id")
        company.currency = request.form.get("currency") or "ILS"
        company.fiscal_year_start_month = request.form.get("fiscal_year_start_month", 1, type=int) or 1
        company.address = request.form.get("address")
        company.phone = request.form.get("phone")
        company.email = request.form.get("email")
        company.notes = request.form.get("notes")
        company.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        flash("تم التحديث", "success")
        return redirect(url_for("companies_bp.index"))
    return render_template("companies/form.html", company=company)
