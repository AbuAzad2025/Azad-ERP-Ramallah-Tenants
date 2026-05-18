from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (Project, ProjectPhase, ProjectCost, ProjectRevenue, CostCenter,
                   GLEntry, Account, Branch, Customer, SystemSettings)
from sqlalchemy import func, and_, or_, desc, case
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
from utils import permission_required

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')

@projects_bp.before_request
@login_required
def restrict_projects_access():
    # الحماية: فقط للمالك والمطور (Level 0)
    if not (current_user.is_system or current_user.role_name_l in ['owner', 'developer']):
        flash('⛔ غير مصرح لك بالوصول لإدارة المشاريع', 'danger')
        return redirect(url_for('main.dashboard'))


@projects_bp.route('/')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def index():
    status = request.args.get('status')
    customer_id = request.args.get('customer', type=int)
    
    query = Project.query
    
    if status:
        query = query.filter_by(status=status)
    
    if customer_id:
        query = query.filter_by(client_id=customer_id)
    
    projects = query.order_by(Project.start_date.desc()).all()
    
    projects_data = []
    for project in projects:
        total_cost = db.session.query(func.sum(ProjectCost.amount)).filter_by(
            project_id=project.id
        ).scalar() or 0
        
        total_revenue = db.session.query(func.sum(ProjectRevenue.amount)).filter_by(
            project_id=project.id
        ).scalar() or 0
        
        phases_count = ProjectPhase.query.filter_by(project_id=project.id).count()
        completed_phases = ProjectPhase.query.filter_by(
            project_id=project.id,
            status='COMPLETED'
        ).count()
        
        projects_data.append({
            'project': project,
            'total_cost': float(total_cost),
            'total_revenue': float(total_revenue),
            'profit': float(total_revenue) - float(total_cost),
            'profit_margin': ((float(total_revenue) - float(total_cost)) / float(total_revenue or 1)) * 100,
            'phases_count': phases_count,
            'completed_phases': completed_phases,
            'progress': (completed_phases / phases_count * 100) if phases_count else 0
        })
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    
    return render_template('projects/index.html',
                         projects=projects_data,
                         customers=customers,
                         selected_status=status,
                         selected_customer=customer_id)


@projects_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_project():
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            client_id = request.form.get('customer_id', type=int)
            cost_center_id = request.form.get('cost_center_id', type=int)
            manager_id = request.form.get('manager_id', type=int) or current_user.id
            branch_id = request.form.get('branch_id', type=int)
            start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
            end_date_str = request.form.get('end_date')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
            estimated_cost = Decimal(request.form.get('estimated_cost', 0))
            estimated_revenue = Decimal(request.form.get('estimated_revenue', 0))
            contract_value = Decimal(request.form.get('contract_value', 0))
            description = request.form.get('description', '')
            
            if Project.query.filter_by(code=code).first():
                flash(f'رمز المشروع {code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            project = Project(
                code=code,
                name=name,
                client_id=client_id,
                cost_center_id=cost_center_id,
                manager_id=manager_id,
                branch_id=branch_id,
                start_date=start_date,
                end_date=end_date,
                budget_amount=estimated_cost,
                actual_cost=0,
                actual_revenue=0,
                status='PLANNED',
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(project)
            db.session.commit()
            
            flash(f'✅ تم إضافة المشروع {code} - {name} بنجاح', 'success')
            return redirect(url_for('projects.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    from models import User, Branch
    users = User.query.all()
    branches = Branch.query.all()
    
    return render_template('projects/form.html',
                         customers=customers,
                         cost_centers=cost_centers,
                         users=users,
                         branches=branches,
                         project=None)


@projects_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def edit_project(id):
    project = db.get_or_404(Project, id)
    
    if request.method == 'POST':
        try:
            project.name = request.form.get('name')
            project.client_id = request.form.get('customer_id', type=int)
            project.cost_center_id = request.form.get('cost_center_id', type=int)
            project.manager_id = request.form.get('manager_id', type=int) or project.manager_id
            project.branch_id = request.form.get('branch_id', type=int)
            
            end_date_str = request.form.get('end_date')
            project.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
            
            project.budget_amount = Decimal(request.form.get('estimated_cost', 0))
            project.description = request.form.get('description', '')
            project.status = request.form.get('status')
            project.updated_by = current_user.id
            project.updated_at = datetime.now()
            
            db.session.commit()
            
            flash(f'✅ تم تحديث المشروع بنجاح', 'success')
            return redirect(url_for('projects.view_project', id=id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    from models import User, Branch
    users = User.query.all()
    branches = Branch.query.all()
    
    return render_template('projects/form.html',
                         customers=customers,
                         cost_centers=cost_centers,
                         users=users,
                         branches=branches,
                         project=project)


@projects_bp.route('/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def view_project(id):
    project = db.get_or_404(Project, id)
    
    phases = ProjectPhase.query.filter_by(project_id=id).order_by(ProjectPhase.order).all()
    
    costs_page = request.args.get('costs_page', 1, type=int)
    revenue_page = request.args.get('revenue_page', 1, type=int)
    
    costs = ProjectCost.query.filter_by(project_id=id).order_by(
        ProjectCost.cost_date.desc()
    ).paginate(page=costs_page, per_page=20, error_out=False)
    
    revenues = ProjectRevenue.query.filter_by(project_id=id).order_by(
        ProjectRevenue.revenue_date.desc()
    ).paginate(page=revenue_page, per_page=20, error_out=False)
    
    total_cost = db.session.query(func.sum(ProjectCost.amount)).filter_by(
        project_id=id
    ).scalar() or 0
    
    total_revenue = db.session.query(func.sum(ProjectRevenue.amount)).filter_by(
        project_id=id
    ).scalar() or 0
    
    completed_phases = sum(1 for p in phases if p.status == 'COMPLETED')
    
    days_elapsed = (date.today() - project.start_date).days if project.start_date else 0
    total_days = (project.end_date - project.start_date).days if project.end_date and project.start_date else 1
    
    stats = {
        'total_cost': float(total_cost),
        'total_revenue': float(total_revenue),
        'profit': float(total_revenue) - float(total_cost),
        'profit_margin': ((float(total_revenue) - float(total_cost)) / float(total_revenue or 1)) * 100,
        'cost_variance': float(project.budget_amount) - float(total_cost),
        'revenue_variance': float(total_revenue) - float(project.budget_amount),
        'budget_usage': (float(total_cost) / float(project.budget_amount or 1)) * 100,
        'phases_count': len(phases),
        'completed_phases': completed_phases,
        'progress': (completed_phases / len(phases) * 100) if phases else 0,
        'days_elapsed': days_elapsed,
        'total_days': total_days,
        'time_progress': (days_elapsed / total_days * 100) if total_days > 0 else 0,
        'costs_count': costs.total,
        'revenues_count': revenues.total
    }
    
    return render_template('projects/view.html',
                         project=project,
                         phases=phases,
                         costs=costs,
                         revenues=revenues,
                         stats=stats)


@projects_bp.route('/<int:id>/add-phase', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_phase(id):
    try:
        project = db.get_or_404(Project, id)
        
        last_phase = ProjectPhase.query.filter_by(project_id=id).order_by(
            ProjectPhase.order.desc()
        ).first()
        
        next_number = (last_phase.order + 1) if last_phase else 1
        
        name = request.form.get('name')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end_date_str = request.form.get('end_date')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        estimated_cost = Decimal(request.form.get('estimated_cost', 0))
        description = request.form.get('description', '')
        
        phase = ProjectPhase(
            project_id=id,
            order=next_number,
            name=name,
            start_date=start_date,
            end_date=end_date,
            planned_budget=estimated_cost,
            actual_cost=0,
            description=description,
            status='PENDING'
        )
        
        db.session.add(phase)
        db.session.commit()
        
        flash(f'✅ تم إضافة المرحلة {next_number} بنجاح', 'success')
        return redirect(url_for('projects.view_project', id=id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('projects.view_project', id=id))


@projects_bp.route('/<int:id>/add-cost', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_cost(id):
    try:
        project = db.get_or_404(Project, id)
        
        amount = Decimal(request.form.get('amount'))
        cost_date = datetime.strptime(request.form.get('cost_date'), '%Y-%m-%d').date()
        category = request.form.get('category')
        phase_id = request.form.get('phase_id', type=int)
        description = request.form.get('description', '')
        reference_type = request.form.get('reference_type', '')
        reference_id = request.form.get('reference_id', type=int)
        
        cost = ProjectCost(
            project_id=id,
            phase_id=phase_id,
            amount=amount,
            cost_date=cost_date,
            category=category,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            recorded_by=current_user.id
        )
        
        db.session.add(cost)
        
        project.actual_cost = (project.actual_cost or 0) + amount
        
        if phase_id:
            phase = db.session.get(ProjectPhase, phase_id)
            if phase:
                phase.actual_cost = (phase.actual_cost or 0) + amount
        
        db.session.flush()
        
        if project.cost_center:
            from models import CostCenterAllocation
            allocation = CostCenterAllocation(
                cost_center_id=project.cost_center_id,
                amount=amount,
                allocation_date=cost_date,
                reference_type='PROJECT_COST',
                reference_id=cost.id,
                description=f'تكلفة مشروع: {project.name} - {description}',
                allocated_by=current_user.id
            )
            db.session.add(allocation)
            
            if project.cost_center.gl_account_code:
                gl_entry = GLEntry(
                    entry_date=cost_date,
                    reference_type='PROJECT_COST',
                    reference_id=cost.id,
                    account_code=project.cost_center.gl_account_code,
                    debit=amount,
                    credit=0,
                    description=f'تكلفة مشروع: {project.name} - {description}',
                    created_by=current_user.id
                )
                db.session.add(gl_entry)
        
        db.session.commit()
        
        flash(f'✅ تم تسجيل تكلفة بقيمة {float(amount):.2f} بنجاح', 'success')
        return redirect(url_for('projects.view_project', id=id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('projects.view_project', id=id))


@projects_bp.route('/<int:id>/add-revenue', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_revenue(id):
    try:
        project = db.get_or_404(Project, id)
        
        amount = Decimal(request.form.get('amount'))
        revenue_date = datetime.strptime(request.form.get('revenue_date'), '%Y-%m-%d').date()
        category = request.form.get('category')
        phase_id = request.form.get('phase_id', type=int)
        description = request.form.get('description', '')
        reference_type = request.form.get('reference_type', '')
        reference_id = request.form.get('reference_id', type=int)
        
        revenue = ProjectRevenue(
            project_id=id,
            phase_id=phase_id,
            amount=amount,
            revenue_date=revenue_date,
            category=category,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            recorded_by=current_user.id
        )
        
        db.session.add(revenue)
        
        project.actual_revenue = (project.actual_revenue or 0) + amount
        
        db.session.flush()
        
        revenue_account_code = SystemSettings.get_value('projects_revenue_account', '401000')
        
        gl_entry = GLEntry(
            entry_date=revenue_date,
            reference_type='PROJECT_REVENUE',
            reference_id=revenue.id,
            account_code=revenue_account_code,
            debit=0,
            credit=amount,
            description=f'إيراد مشروع: {project.name} - {description}',
            created_by=current_user.id
        )
        db.session.add(gl_entry)
        
        db.session.commit()
        
        flash(f'✅ تم تسجيل إيراد بقيمة {float(amount):.2f} بنجاح', 'success')
        return redirect(url_for('projects.view_project', id=id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('projects.view_project', id=id))


@projects_bp.route('/reports/pnl')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def report_pnl():
    project_id = request.args.get('project', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = Project.query
    
    if project_id:
        query = query.filter_by(id=project_id)
    
    projects = query.order_by(Project.code).all()
    
    pnl_data = []
    
    for project in projects:
        cost_query = ProjectCost.query.filter_by(project_id=project.id)
        revenue_query = ProjectRevenue.query.filter_by(project_id=project.id)
        
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            cost_query = cost_query.filter(ProjectCost.cost_date >= date_from_obj)
            revenue_query = revenue_query.filter(ProjectRevenue.revenue_date >= date_from_obj)
        
        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            cost_query = cost_query.filter(ProjectCost.cost_date <= date_to_obj)
            revenue_query = revenue_query.filter(ProjectRevenue.revenue_date <= date_to_obj)
        
        total_cost = db.session.query(func.sum(ProjectCost.amount)).filter(
            cost_query.whereclause
        ).scalar() or 0
        
        total_revenue = db.session.query(func.sum(ProjectRevenue.amount)).filter(
            revenue_query.whereclause
        ).scalar() or 0
        
        profit = float(total_revenue) - float(total_cost)
        profit_margin = (profit / float(total_revenue or 1)) * 100
        
        pnl_data.append({
            'project': project,
            'total_cost': float(total_cost),
            'total_revenue': float(total_revenue),
            'profit': profit,
            'profit_margin': profit_margin,
            'estimated_profit': 0
        })
    
    grand_totals = {
        'total_cost': sum(d['total_cost'] for d in pnl_data),
        'total_revenue': sum(d['total_revenue'] for d in pnl_data),
        'total_profit': sum(d['profit'] for d in pnl_data)
    }
    
    grand_totals['profit_margin'] = (grand_totals['total_profit'] / (grand_totals['total_revenue'] or 1)) * 100
    
    all_projects = Project.query.order_by(Project.code).all()
    
    return render_template('projects/report_pnl.html',
                         pnl_data=pnl_data,
                         grand_totals=grand_totals,
                         all_projects=all_projects,
                         selected_project=project_id,
                         date_from=date_from,
                         date_to=date_to)


@projects_bp.route('/reports/profitability')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def report_profitability():
    projects = Project.query.order_by(Project.code).all()
    
    profitability_data = []
    
    for project in projects:
        total_cost = db.session.query(func.sum(ProjectCost.amount)).filter_by(
            project_id=project.id
        ).scalar() or 0
        
        total_revenue = db.session.query(func.sum(ProjectRevenue.amount)).filter_by(
            project_id=project.id
        ).scalar() or 0
        
        profit = float(total_revenue) - float(total_cost)
        profit_margin = (profit / float(total_revenue or 1)) * 100
        
        roi = (profit / float(total_cost or 1)) * 100
        contract_value = float(project.estimated_revenue or project.budget_amount or 0)
        
        profitability_data.append({
            'project': project,
            'total_cost': float(total_cost),
            'total_revenue': float(total_revenue),
            'profit': profit,
            'profit_margin': profit_margin,
            'roi': roi,
            'contract_value': contract_value,
            'contract_delivered': (float(total_revenue) / float(contract_value or 1)) * 100
        })
    
    profitability_data.sort(key=lambda x: x['profit_margin'], reverse=True)
    
    return render_template('projects/report_profitability.html',
                         profitability_data=profitability_data)


@projects_bp.route('/reports/budget-tracking')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def report_budget_tracking():
    project_id = request.args.get('project_id', type=int)
    
    query = Project.query.filter(Project.budget_amount > 0)
    
    if project_id:
        query = query.filter_by(id=project_id)
    
    projects = query.order_by(Project.code).all()
    
    tracking_data = []
    
    for project in projects:
        total_cost = db.session.query(func.sum(ProjectCost.amount)).filter_by(
            project_id=project.id
        ).scalar() or 0
        
        estimated = float(project.budget_amount)
        actual = float(total_cost)
        variance = estimated - actual
        variance_percent = (variance / estimated) * 100 if estimated else 0
        
        phases = ProjectPhase.query.filter_by(project_id=project.id).all()
        completed_phases = sum(1 for p in phases if p.status == 'COMPLETED')
        progress = (completed_phases / len(phases) * 100) if phases else 0
        
        budget_usage = (actual / estimated * 100) if estimated else 0
        tracking_data.append({
            'project_id': project.id,
            'project_code': project.code,
            'project_name': project.name,
            'estimated': estimated,
            'actual': actual,
            'variance': variance,
            'variance_percent': variance_percent,
            'percentage': budget_usage,
            'budget_usage': budget_usage,
            'progress': progress,
            'status': 'under' if variance > 0 else 'over' if variance < 0 else 'on_budget'
        })
    
    tracking_data.sort(key=lambda x: abs(x['variance']), reverse=True)
    
    totals = {
        'estimated': sum(d['estimated'] for d in tracking_data),
        'actual': sum(d['actual'] for d in tracking_data),
        'variance': sum(d['variance'] for d in tracking_data)
    }
    
    all_projects = Project.query.filter(Project.budget_amount > 0).order_by(Project.code).all()
    
    return render_template('projects/report_budget_tracking.html',
                         tracking_data=tracking_data,
                         totals=totals,
                         all_projects=all_projects,
                         selected_project=project_id)


@projects_bp.route('/reports/variance')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def report_variance():
    projects = Project.query.filter(
        Project.budget_amount > 0,
        Project.is_active == True
    ).order_by(Project.code).all()
    
    data = []
    
    for project in projects:
        actual_cost = float(project.actual_cost or 0)
        budget_amount = float(project.budget_amount or 0)
        
        variance = budget_amount - actual_cost
        variance_pct = (variance / budget_amount * 100) if budget_amount > 0 else 0
        status = 'over' if actual_cost > budget_amount else 'under'
        
        data.append({
            'project': project,
            'budget': budget_amount,
            'actual': actual_cost,
            'variance': variance,
            'variance_pct': variance_pct,
            'status': status
        })
    
    data.sort(key=lambda x: abs(x['variance']), reverse=True)
    
    return render_template('projects/report_variance.html',
                         data=data)


@projects_bp.route('/api/dashboard-stats')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def api_dashboard_stats():
    total_projects = Project.query.count()
    active_projects = Project.query.filter(Project.status.in_(['IN_PROGRESS', 'PLANNING'])).count()
    completed_projects = Project.query.filter_by(status='COMPLETED').count()
    
    total_cost = db.session.query(func.sum(ProjectCost.amount)).scalar() or 0
    total_revenue = db.session.query(func.sum(ProjectRevenue.amount)).scalar() or 0
    
    stats = {
        'total_projects': total_projects,
        'active_projects': active_projects,
        'completed_projects': completed_projects,
        'total_cost': float(total_cost),
        'total_revenue': float(total_revenue),
        'total_profit': float(total_revenue) - float(total_cost),
        'overall_margin': ((float(total_revenue) - float(total_cost)) / float(total_revenue or 1)) * 100
    }
    
    return jsonify({'success': True, 'stats': stats})
