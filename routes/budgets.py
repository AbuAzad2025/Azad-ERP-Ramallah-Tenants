from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Budget, BudgetCommitment, Account, Branch, Site, SystemSettings, Expense, ExpenseType
from utils.branch_context import accessible_branches_query, resolve_branch_id
from utils.company_scope import filter_by_branches
from sqlalchemy import func, extract
from datetime import datetime, date
from decimal import Decimal
import utils

budgets_bp = Blueprint('budgets', __name__, url_prefix='/budgets')


def check_budget_enabled():
    if not SystemSettings.get_setting('enable_budget_module', False):
        flash('وحدة الميزانية غير مفعلة. يرجى تفعيلها من لوحة التحكم المالي', 'warning')
        return False
    return True


@budgets_bp.route('/')
@login_required
def index():
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    fiscal_year = request.args.get('year', datetime.now().year, type=int)
    branch_id = request.args.get('branch', None, type=int)
    
    query = filter_by_branches(
        Budget.query.filter_by(fiscal_year=fiscal_year, is_active=True),
        Budget.branch_id,
    )
    if branch_id:
        resolve_branch_id(branch_id, required=False)
        query = query.filter_by(branch_id=branch_id)
    
    budgets = query.all()
    
    branches = accessible_branches_query().all()
    
    budget_data = []
    for budget in budgets:
        actual = budget.get_actual_amount()
        committed = budget.get_committed_amount()
        available = budget.get_available_amount()
        utilization = ((actual + committed) / float(budget.allocated_amount) * 100) if budget.allocated_amount > 0 else 0
        
        budget_data.append({
            'budget': budget,
            'actual': actual,
            'committed': committed,
            'available': available,
            'utilization': utilization
        })
    
    return render_template('budgets/index.html',
                         budgets=budget_data,
                         fiscal_year=fiscal_year,
                         branches=branches,
                         selected_branch=branch_id)


@budgets_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        try:
            fiscal_year = request.form.get('fiscal_year', type=int) or 0
            if fiscal_year <= 0:
                flash('السنة المالية مطلوبة', 'danger')
                return redirect(request.url)
            account_code = request.form.get('account_code')
            branch_id = request.form.get('branch_id', type=int)
            site_id = request.form.get('site_id', type=int)
            try:
                allocated_amount = Decimal(request.form.get('allocated_amount') or 0)
            except Exception:
                allocated_amount = Decimal(0)
            if allocated_amount < 0:
                flash('مبلغ الميزانية لا يمكن أن يكون سالباً', 'danger')
                return redirect(request.url)
            notes = request.form.get('notes', '')
            
            budget = Budget(
                fiscal_year=fiscal_year,
                account_code=account_code,
                branch_id=branch_id,
                site_id=site_id,
                allocated_amount=allocated_amount,
                notes=notes,
                is_active=True
            )
            
            db.session.add(budget)
            db.session.commit()
            
            flash('تم إضافة الميزانية بنجاح', 'success')
            return redirect(url_for('budgets.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    accounts = Account.query.filter_by(type='EXPENSE', is_active=True).all()
    branches = Branch.query.filter_by(is_active=True).all()
    sites = Site.query.filter_by(is_active=True).all()
    
    return render_template('budgets/form.html',
                         accounts=accounts,
                         branches=branches,
                         sites=sites,
                         budget=None)


@budgets_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    budget = db.get_or_404(Budget, id)
    
    if request.method == 'POST':
        try:
            try:
                budget.allocated_amount = Decimal(request.form.get('allocated_amount') or 0)
            except Exception:
                budget.allocated_amount = Decimal(0)
            if budget.allocated_amount < 0:
                flash('مبلغ الميزانية لا يمكن أن يكون سالباً', 'danger')
                return redirect(request.url)
            budget.notes = request.form.get('notes', '')
            budget.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            
            flash('تم تحديث الميزانية بنجاح', 'success')
            return redirect(url_for('budgets.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    accounts = Account.query.filter_by(type='EXPENSE', is_active=True).all()
    branches = Branch.query.filter_by(is_active=True).all()
    sites = Site.query.filter_by(is_active=True).all()
    
    return render_template('budgets/form.html',
                         accounts=accounts,
                         branches=branches,
                         sites=sites,
                         budget=budget)


@budgets_bp.route('/report/vs-actual')
@login_required
def budget_vs_actual():
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    fiscal_year = request.args.get('year', datetime.now().year, type=int)
    branch_id = request.args.get('branch', None, type=int)
    
    query = filter_by_branches(
        Budget.query.filter_by(fiscal_year=fiscal_year, is_active=True),
        Budget.branch_id,
    )
    if branch_id:
        resolve_branch_id(branch_id, required=False)
        query = query.filter_by(branch_id=branch_id)
    
    budgets = query.all()
    
    report_data = []
    for budget in budgets:
        actual = budget.get_actual_amount()
        committed = budget.get_committed_amount()
        available = budget.get_available_amount()
        variance = float(budget.allocated_amount) - actual
        utilization = ((actual + committed) / float(budget.allocated_amount) * 100) if budget.allocated_amount > 0 else 0
        
        status = 'success'
        if utilization >= 95:
            status = 'danger'
        elif utilization >= 80:
            status = 'warning'
        
        report_data.append({
            'account': budget.account,
            'branch': budget.branch,
            'allocated': float(budget.allocated_amount),
            'actual': actual,
            'committed': committed,
            'available': available,
            'variance': variance,
            'utilization': utilization,
            'status': status
        })
    
    branches = Branch.query.filter_by(is_active=True).all()
    
    return render_template('budgets/report_vs_actual.html',
                         data=report_data,
                         fiscal_year=fiscal_year,
                         branches=branches,
                         selected_branch=branch_id)


@budgets_bp.route('/report/variance')
@login_required
def variance_analysis():
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    fiscal_year = request.args.get('year', datetime.now().year, type=int)
    
    budgets = Budget.query.filter_by(fiscal_year=fiscal_year, is_active=True).all()
    
    variance_data = []
    for budget in budgets:
        actual = budget.get_actual_amount()
        variance = float(budget.allocated_amount) - actual
        variance_pct = (variance / float(budget.allocated_amount) * 100) if budget.allocated_amount > 0 else 0
        
        variance_data.append({
            'account': budget.account,
            'branch': budget.branch,
            'allocated': float(budget.allocated_amount),
            'actual': actual,
            'variance': variance,
            'variance_pct': variance_pct,
            'status': 'over' if variance < 0 else 'under'
        })
    
    variance_data.sort(key=lambda x: abs(x['variance']), reverse=True)
    
    return render_template('budgets/report_variance.html',
                         data=variance_data,
                         fiscal_year=fiscal_year)


@budgets_bp.route('/dashboard')
@login_required
def dashboard():
    if not check_budget_enabled():
        return redirect(url_for('main.dashboard'))
    
    fiscal_year = datetime.now().year
    
    total_allocated = db.session.query(func.sum(Budget.allocated_amount)).filter_by(
        fiscal_year=fiscal_year,
        is_active=True
    ).scalar() or 0
    
    budgets = Budget.query.filter_by(fiscal_year=fiscal_year, is_active=True).all()
    
    total_actual = sum(b.get_actual_amount() for b in budgets)
    total_committed = sum(b.get_committed_amount() for b in budgets)
    total_available = float(total_allocated) - total_actual - total_committed
    
    utilization = ((total_actual + total_committed) / float(total_allocated) * 100) if total_allocated > 0 else 0
    
    alerts = []
    for budget in budgets:
        actual = budget.get_actual_amount()
        committed = budget.get_committed_amount()
        util = ((actual + committed) / float(budget.allocated_amount) * 100) if budget.allocated_amount > 0 else 0
        
        threshold_warning = SystemSettings.get_setting('budget_threshold_warning', 80)
        threshold_critical = SystemSettings.get_setting('budget_threshold_critical', 95)
        
        if util >= threshold_critical:
            alerts.append({
                'level': 'danger',
                'message': f'{budget.account.name} - {budget.branch.name if budget.branch else "عام"}: {util:.1f}% استخدام',
                'budget': budget
            })
        elif util >= threshold_warning:
            alerts.append({
                'level': 'warning',
                'message': f'{budget.account.name} - {budget.branch.name if budget.branch else "عام"}: {util:.1f}% استخدام',
                'budget': budget
            })
    
    by_branch = db.session.query(
        Branch.name,
        func.sum(Budget.allocated_amount).label('total')
    ).join(Budget).filter(
        Budget.fiscal_year == fiscal_year,
        Budget.is_active == True
    ).group_by(Branch.name).all()
    
    return render_template('budgets/dashboard.html',
                         fiscal_year=fiscal_year,
                         total_allocated=float(total_allocated),
                         total_actual=total_actual,
                         total_committed=total_committed,
                         total_available=total_available,
                         utilization=utilization,
                         alerts=alerts,
                         by_branch=by_branch)

