"""
Blueprint لإدارة الفروع والمواقع (PBAC Protected)
مزايا متطورة: CRUD، بحث، فلاتر، أرشفة، نقل جماعي، استيراد/تصدير
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import joinedload
from datetime import datetime, timezone
import csv
import io

from extensions import db
from models import Branch, Site, Employee, Expense, Warehouse, User
from utils import _get_or_404, permission_required
import utils
from permissions_config.enums import SystemPermissions


branches_bp = Blueprint('branches_bp', __name__, url_prefix='/branches')


def _branch_or_404(branch_id: int) -> Branch:
    from utils.company_scope import assert_branch_access

    assert_branch_access(branch_id)
    return _get_or_404(Branch, branch_id)


# ═══════════════════════════════════════════════════════════════
# إدارة الفروع - Branches Management
# ═══════════════════════════════════════════════════════════════

@branches_bp.route('/', methods=['GET'], endpoint='list_branches')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def list_branches():
    """قائمة الفروع مع فلاتر وإحصائيات"""
    search = request.args.get('q', '').strip()
    active_filter = request.args.get('active', '')
    
    from utils.company_scope import filter_branches_query

    query = filter_branches_query(Branch.query)
    
    if search:
        query = query.filter(
            db.or_(
                Branch.name.ilike(f'%{search}%'),
                Branch.code.ilike(f'%{search}%'),
                Branch.city.ilike(f'%{search}%')
            )
        )
    
    if active_filter == '1':
        query = query.filter_by(is_active=True)
    elif active_filter == '0':
        query = query.filter_by(is_active=False)
    
    branches = query.order_by(Branch.is_active.desc(), Branch.name).all()
    
    from utils.company_scope import branch_expenses_query, branch_warehouses_query

    # إحصائيات
    for b in branches:
        b.employees_count = Employee.query.filter_by(branch_id=b.id).count()
        b.expenses_count = branch_expenses_query(b.id).count()
        b.warehouses_count = branch_warehouses_query(b.id).count()
        b.sites_count = Site.query.filter_by(branch_id=b.id).count()
    
    return render_template('branches/list.html', branches=branches, search=search, active_filter=active_filter)


@branches_bp.route('/create', methods=['GET', 'POST'], endpoint='create_branch')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def create_branch():
    """إنشاء فرع جديد"""
    if request.method == 'POST':
        try:
            from utils.branch_context import resolve_branch_id
            from utils.company_scope import assert_company_access, default_company

            company_id = request.form.get('company_id', type=int)
            if not company_id:
                dc = default_company()
                company_id = dc.id if dc else None
            if company_id:
                assert_company_access(int(company_id))
            b = Branch(
                company_id=int(company_id) if company_id else None,
                name=request.form.get('name', '').strip(),
                code=request.form.get('code', '').strip().upper(),
                address=request.form.get('address', '').strip() or None,
                city=request.form.get('city', '').strip() or None,
                phone=request.form.get('phone', '').strip() or None,
                email=request.form.get('email', '').strip() or None,
                currency=request.form.get('currency', 'ILS').upper(),
                tax_id=request.form.get('tax_id', '').strip() or None,
                notes=request.form.get('notes', '').strip() or None,
                is_active=bool(request.form.get('is_active')),
            )
            
            # حفظ إحداثيات GPS
            geo_lat = request.form.get('geo_lat', '').strip()
            geo_lng = request.form.get('geo_lng', '').strip()
            if geo_lat and geo_lng:
                try:
                    b.geo_lat = float(geo_lat)
                    b.geo_lng = float(geo_lng)
                except (ValueError, TypeError):
                    current_app.logger.debug('numeric conversion failed in branches.py', exc_info=True)
            
            manager_employee_id = request.form.get('manager_employee_id')
            if manager_employee_id and manager_employee_id != '0':
                b.manager_employee_id = int(manager_employee_id)
            
            db.session.add(b)
            db.session.commit()
            utils.flash_success(f"تم إنشاء الفرع: {b.name}", "success")
            return redirect(url_for('branches_bp.list_branches'))
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("رمز الفرع مستخدم مسبقاً")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error("خطأ في إنشاء الفرع")
    
    from models import Company
    from utils.company_scope import default_company, filter_companies_query

    employees = Employee.query.order_by(Employee.name).all()
    companies = filter_companies_query(Company.query.filter_by(is_active=True).order_by(Company.name)).all()
    dc = default_company()
    return render_template(
        'branches/form.html',
        branch=None,
        employees=employees,
        companies=companies,
        default_company_id=dc.id if dc else None,
    )


@branches_bp.route('/<int:branch_id>/edit', methods=['GET', 'POST'], endpoint='edit_branch')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def edit_branch(branch_id):
    """تعديل فرع"""
    b = _branch_or_404(branch_id)
    
    if request.method == 'POST':
        try:
            from utils.company_scope import assert_company_access

            company_id = request.form.get('company_id', type=int)
            if company_id and b.code != 'MAIN':
                assert_company_access(int(company_id))
                b.company_id = int(company_id)
            b.name = request.form.get('name', '').strip()
            b.code = request.form.get('code', '').strip().upper()
            
            # حفظ إحداثيات GPS
            geo_lat = request.form.get('geo_lat', '').strip()
            geo_lng = request.form.get('geo_lng', '').strip()
            if geo_lat and geo_lng:
                try:
                    b.geo_lat = float(geo_lat)
                    b.geo_lng = float(geo_lng)
                except (ValueError, TypeError):
                    b.geo_lat = None
                    b.geo_lng = None
            else:
                b.geo_lat = None
                b.geo_lng = None
            b.address = request.form.get('address', '').strip() or None
            b.city = request.form.get('city', '').strip() or None
            b.phone = request.form.get('phone', '').strip() or None
            b.email = request.form.get('email', '').strip() or None
            b.currency = request.form.get('currency', 'ILS').upper()
            b.tax_id = request.form.get('tax_id', '').strip() or None
            b.notes = request.form.get('notes', '').strip() or None
            b.is_active = bool(request.form.get('is_active'))
            
            manager_employee_id = request.form.get('manager_employee_id')
            if manager_employee_id and manager_employee_id != '0':
                b.manager_employee_id = int(manager_employee_id)
            else:
                b.manager_employee_id = None
            
            db.session.commit()
            utils.flash_success(f"تم تحديث الفرع: {b.name}", "success")
            return redirect(url_for('branches_bp.list_branches'))
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("رمز الفرع مستخدم مسبقاً")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error("خطأ في تحديث الفرع")
    
    from models import Company
    from utils.company_scope import filter_companies_query

    employees = Employee.query.order_by(Employee.name).all()
    companies = filter_companies_query(Company.query.filter_by(is_active=True).order_by(Company.name)).all()
    return render_template('branches/form.html', branch=b, employees=employees, companies=companies, default_company_id=b.company_id)


@branches_bp.route('/<int:branch_id>/archive', methods=['POST'], endpoint='archive_branch')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def archive_branch(branch_id):
    """أرشفة فرع (soft delete)"""
    b = _branch_or_404(branch_id)
    
    if b.code == 'MAIN':
        utils.flash_error("لا يمكن أرشفة الفرع الرئيسي")
        return redirect(url_for('branches_bp.list_branches'))
    
    b.is_archived = True
    b.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    b.archived_by = current_user.id
    b.archive_reason = request.form.get('reason', '').strip() or None
    b.is_active = False
    
    try:
        db.session.commit()
        utils.flash_success(f"تم أرشفة الفرع: {b.name}", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error("خطأ في الأرشفة")
    
    return redirect(url_for('branches_bp.list_branches'))


@branches_bp.route('/<int:branch_id>/restore', methods=['POST'], endpoint='restore_branch')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def restore_branch(branch_id):
    """استعادة فرع من الأرشيف"""
    b = _branch_or_404(branch_id)
    b.is_archived = False
    b.archived_at = None
    b.archived_by = None
    b.archive_reason = None
    b.is_active = True
    
    try:
        db.session.commit()
        utils.flash_success(f"تم استعادة الفرع: {b.name}", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error("خطأ في الاستعادة")
    
    return redirect(url_for('branches_bp.list_branches'))


@branches_bp.route('/<int:branch_id>/dashboard', methods=['GET'], endpoint='branch_dashboard')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def branch_dashboard(branch_id):
    """لوحة تحكم متقدمة للفرع"""
    from utils.company_scope import branch_expenses_query, branch_warehouses_query

    branch = _branch_or_404(branch_id)
    
    # إحصائيات
    stats = {
        'employees_count': Employee.query.filter_by(branch_id=branch_id).count(),
        'sites_count': Site.query.filter_by(branch_id=branch_id).count(),
        'warehouses_count': branch_warehouses_query(branch_id).count(),
        'monthly_expenses': 0.0
    }
    
    # حساب مصاريف الشهر الحالي مع تحويل العملات
    from datetime import datetime, timedelta
    from decimal import Decimal
    from models import convert_amount
    
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_expenses = branch_expenses_query(branch_id).filter(
        Expense.date >= start_of_month
    ).all()
    
    monthly_expenses = Decimal('0.00')
    for exp in month_expenses:
        amt = Decimal(str(exp.amount or 0))
        if exp.currency == "ILS":
            monthly_expenses += amt
        else:
            try:
                monthly_expenses += convert_amount(amt, exp.currency, "ILS", exp.date)
            except Exception:
                current_app.logger.debug('Currency conversion skipped')
    
    stats['monthly_expenses'] = float(monthly_expenses)
    
    # قوائم
    employees = Employee.query.filter_by(branch_id=branch_id).order_by(Employee.name).all()
    recent_expenses = branch_expenses_query(branch_id).order_by(Expense.date.desc()).limit(10).all()
    
    return render_template('branches/dashboard.html', 
                         branch=branch, 
                         stats=stats,
                         employees=employees,
                         recent_expenses=recent_expenses)


# ═══════════════════════════════════════════════════════════════
# إدارة المواقع - Sites Management
# ═══════════════════════════════════════════════════════════════

@branches_bp.route('/<int:branch_id>/sites', methods=['GET'], endpoint='list_sites')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def list_sites(branch_id):
    """قائمة المواقع لفرع معين"""
    from utils.company_scope import branch_expenses_query

    branch = _branch_or_404(branch_id)
    sites = Site.query.filter_by(branch_id=branch_id).order_by(Site.is_active.desc(), Site.name).all()
    
    for s in sites:
        s.employees_count = Employee.query.filter_by(site_id=s.id).count()
        s.expenses_count = branch_expenses_query(branch_id).filter_by(site_id=s.id).count()
    
    return render_template('branches/sites_list.html', branch=branch, sites=sites)


@branches_bp.route('/<int:branch_id>/sites/create', methods=['GET', 'POST'], endpoint='create_site')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def create_site(branch_id):
    """إنشاء موقع جديد"""
    branch = _branch_or_404(branch_id)
    
    if request.method == 'POST':
        try:
            s = Site(
                branch_id=branch_id,
                name=request.form.get('name', '').strip(),
                code=request.form.get('code', '').strip().upper(),
                address=request.form.get('address', '').strip() or None,
                notes=request.form.get('notes', '').strip() or None,
                is_active=bool(request.form.get('is_active')),
            )
            
            # حفظ إحداثيات GPS
            geo_lat = request.form.get('geo_lat', '').strip()
            geo_lng = request.form.get('geo_lng', '').strip()
            if geo_lat and geo_lng:
                try:
                    s.geo_lat = float(geo_lat)
                    s.geo_lng = float(geo_lng)
                except (ValueError, TypeError):
                    current_app.logger.debug('numeric conversion failed in branches.py', exc_info=True)
            
            manager_employee_id = request.form.get('manager_employee_id')
            if manager_employee_id and manager_employee_id != '0':
                s.manager_employee_id = int(manager_employee_id)
            
            db.session.add(s)
            db.session.commit()
            utils.flash_success(f"تم إنشاء الموقع: {s.name}", "success")
            return redirect(url_for('branches_bp.list_sites', branch_id=branch_id))
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("رمز الموقع مستخدم مسبقاً في هذا الفرع")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error("خطأ في إنشاء الموقع")
    
    employees = Employee.query.filter_by(branch_id=branch_id).order_by(Employee.name).all()
    return render_template('branches/site_form.html', branch=branch, site=None, employees=employees)


@branches_bp.route('/sites/<int:site_id>/edit', methods=['GET', 'POST'], endpoint='edit_site')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def edit_site(site_id):
    """تعديل موقع"""
    s = _get_or_404(Site, site_id, load_options=[joinedload(Site.branch)])
    
    if request.method == 'POST':
        try:
            s.name = request.form.get('name', '').strip()
            s.code = request.form.get('code', '').strip().upper()
            s.address = request.form.get('address', '').strip() or None
            s.notes = request.form.get('notes', '').strip() or None
            s.is_active = bool(request.form.get('is_active'))
            
            # حفظ إحداثيات GPS
            geo_lat = request.form.get('geo_lat', '').strip()
            geo_lng = request.form.get('geo_lng', '').strip()
            if geo_lat and geo_lng:
                try:
                    s.geo_lat = float(geo_lat)
                    s.geo_lng = float(geo_lng)
                except (ValueError, TypeError):
                    s.geo_lat = None
                    s.geo_lng = None
            else:
                s.geo_lat = None
                s.geo_lng = None
            
            manager_employee_id = request.form.get('manager_employee_id')
            if manager_employee_id and manager_employee_id != '0':
                s.manager_employee_id = int(manager_employee_id)
            else:
                s.manager_employee_id = None
            
            db.session.commit()
            utils.flash_success(f"تم تحديث الموقع: {s.name}", "success")
            return redirect(url_for('branches_bp.list_sites', branch_id=s.branch_id))
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("رمز الموقع مستخدم مسبقاً")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error("خطأ في تحديث الموقع")
    
    employees = Employee.query.filter_by(branch_id=s.branch_id).order_by(Employee.name).all()
    return render_template('branches/site_form.html', branch=s.branch, site=s, employees=employees)


@branches_bp.route('/sites/<int:site_id>/archive', methods=['POST'], endpoint='archive_site')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def archive_site(site_id):
    """أرشفة موقع"""
    s = _get_or_404(Site, site_id)
    s.is_archived = True
    s.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    s.archived_by = current_user.id
    s.archive_reason = request.form.get('reason', '').strip() or None
    s.is_active = False
    
    try:
        db.session.commit()
        utils.flash_success(f"تم أرشفة الموقع: {s.name}", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error("خطأ في الأرشفة")
    
    return redirect(url_for('branches_bp.list_sites', branch_id=s.branch_id))


# ═══════════════════════════════════════════════════════════════
# تقارير وإحصائيات حسب الفرع/الموقع
# ═══════════════════════════════════════════════════════════════

@branches_bp.route('/<int:branch_id>/report', methods=['GET'], endpoint='branch_report')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def branch_report(branch_id):
    """تقرير مفصل لفرع: نفقات، موظفين، مستودعات، مواقع"""
    from sqlalchemy import func
    
    from utils.company_scope import branch_expenses_query, branch_warehouses_query

    branch = _branch_or_404(branch_id)
    
    # إحصائيات
    from decimal import Decimal
    from models import convert_amount
    
    # حساب إجمالي المصاريف مع تحويل العملات
    all_branch_expenses = branch_expenses_query(branch_id).all()
    expenses_total_ils = Decimal('0.00')
    for exp in all_branch_expenses:
        amt = Decimal(str(exp.amount or 0))
        if exp.currency == "ILS":
            expenses_total_ils += amt
        else:
            try:
                expenses_total_ils += convert_amount(amt, exp.currency, "ILS", exp.date)
            except Exception:
                current_app.logger.debug('Currency conversion skipped')
    
    stats = {
        'employees_count': Employee.query.filter_by(branch_id=branch_id).count(),
        'sites_count': Site.query.filter_by(branch_id=branch_id, is_active=True).count(),
        'warehouses_count': branch_warehouses_query(branch_id).count(),
        'expenses_count': len(all_branch_expenses),
        'expenses_total': float(expenses_total_ils),
    }
    
    # أعلى 5 نفقات
    top_expenses = branch_expenses_query(branch_id).order_by(Expense.amount.desc()).limit(5).all()
    
    # نفقات حسب النوع مع تحويل العملات
    from models import ExpenseType
    from collections import defaultdict
    
    expense_types_dict = defaultdict(lambda: {'count': 0, 'total': Decimal('0.00')})
    
    for exp in all_branch_expenses:
        type_name = exp.type.name if exp.type else 'غير محدد'
        amt = Decimal(str(exp.amount or 0))
        
        if exp.currency == "ILS":
            amt_ils = amt
        else:
            try:
                amt_ils = convert_amount(amt, exp.currency, "ILS", exp.date)
            except Exception:
                amt_ils = Decimal('0.00')
        
        expense_types_dict[type_name]['count'] += 1
        expense_types_dict[type_name]['total'] += amt_ils
    
    # تحويل للصيغة المتوقعة من التمبلت
    from collections import namedtuple
    ExpenseByType = namedtuple('ExpenseByType', ['name', 'count', 'total'])
    expense_by_type = [
        ExpenseByType(name=k, count=v['count'], total=float(v['total']))
        for k, v in expense_types_dict.items()
    ]
    
    return render_template(
        'branches/report.html',
        branch=branch,
        stats=stats,
        top_expenses=top_expenses,
        expense_by_type=expense_by_type,
    )


# ═══════════════════════════════════════════════════════════════
# استيراد/تصدير
# ═══════════════════════════════════════════════════════════════

@branches_bp.route('/export', methods=['GET'], endpoint='export_branches')
@login_required
@permission_required(SystemPermissions.MANAGE_BRANCHES)
def export_branches():
    """تصدير الفروع إلى CSV"""
    branches = Branch.query.order_by(Branch.name).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['الرمز', 'الاسم', 'المدينة', 'العنوان', 'الهاتف', 'البريد', 'العملة', 'نشط', 'ملاحظات'])
    
    for b in branches:
        writer.writerow([
            b.code, b.name, b.city or '', b.address or '', b.phone or '', 
            b.email or '', b.currency, 'نعم' if b.is_active else 'لا', b.notes or ''
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'branches_{datetime.now().strftime("%Y%m%d")}.csv'
    )


# ═══════════════════════════════════════════════════════════════
# API للبحث والاختيار
# ═══════════════════════════════════════════════════════════════

@branches_bp.route('/api/search', methods=['GET'], endpoint='api_search_branches')
@login_required
def api_search_branches():
    """API بحث الفروع (للاستخدام في قوائم الاختيار)"""
    q = request.args.get('q', '').strip()
    try:
        limit = int(request.args.get('limit', 50))
    except (ValueError, TypeError):
        limit = 50
    
    query = Branch.query.filter_by(is_active=True)
    if q:
        query = query.filter(
            db.or_(
                Branch.name.ilike(f'%{q}%'),
                Branch.code.ilike(f'%{q}%')
            )
        )
    
    branches = query.order_by(Branch.name).limit(limit).all()
    return jsonify({
        'results': [{'id': b.id, 'text': f"{b.code} - {b.name}", 'name': b.name, 'code': b.code} for b in branches]
    })


@branches_bp.route('/api/sites/<int:branch_id>', methods=['GET'], endpoint='api_branch_sites')
@login_required
def api_branch_sites(branch_id):
    """API قائمة مواقع فرع معين (للفلترة الديناميكية)"""
    q = request.args.get('q', '').strip()
    
    query = Site.query.filter_by(branch_id=branch_id, is_active=True)
    if q:
        query = query.filter(
            db.or_(
                Site.name.ilike(f'%{q}%'),
                Site.code.ilike(f'%{q}%')
            )
        )
    
    sites = query.order_by(Site.name).all()
    return jsonify({
        'results': [{'id': s.id, 'text': f"{s.code} - {s.name}", 'name': s.name, 'code': s.code} for s in sites]
    })

