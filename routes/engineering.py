from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (EngineeringTeam, EngineeringTeamMember, EngineeringSkill, 
                   EmployeeSkill, EngineeringTask, EngineeringTimesheet,
                   Employee, CostCenter, Branch, Customer, Project, ServiceRequest, User)
from sqlalchemy import func, and_, or_, desc
from datetime import datetime, date, timedelta
from decimal import Decimal
from utils import permission_required

engineering_bp = Blueprint('engineering', __name__, url_prefix='/engineering')

@engineering_bp.before_request
@login_required
def restrict_engineering_access():
    # الحماية: فقط للمالك والمطور (Level 0)
    if not (current_user.is_system or current_user.role_name_l in ['owner', 'developer']):
        flash('⛔ غير مصرح لك بالوصول للإدارة الهندسية', 'danger')
        return redirect(url_for('main.dashboard'))


@engineering_bp.route('/')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def dashboard():
    total_teams = EngineeringTeam.query.filter_by(is_active=True).count()
    total_engineers = db.session.query(func.count(func.distinct(EngineeringTeamMember.employee_id))).filter_by(is_active=True).scalar() or 0
    
    active_tasks = EngineeringTask.query.filter(
        EngineeringTask.status.in_(['ASSIGNED', 'IN_PROGRESS'])
    ).count()
    
    overdue_tasks = EngineeringTask.query.filter(
        EngineeringTask.status.in_(['ASSIGNED', 'IN_PROGRESS']),
        EngineeringTask.scheduled_end < datetime.now()
    ).count()
    
    completed_this_month = EngineeringTask.query.filter(
        EngineeringTask.status == 'COMPLETED',
        EngineeringTask.actual_end >= date.today().replace(day=1)
    ).count()
    
    todays_timesheets = EngineeringTimesheet.query.filter_by(
        work_date=date.today()
    ).count()
    
    teams_status = []
    for team in EngineeringTeam.query.filter_by(is_active=True).all():
        members_count = EngineeringTeamMember.query.filter_by(team_id=team.id, is_active=True).count()
        active_tasks_count = EngineeringTask.query.filter_by(assigned_team_id=team.id).filter(
            EngineeringTask.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        status = 'available' if active_tasks_count < team.max_concurrent_tasks else 'busy'
        
        teams_status.append({
            'team': team,
            'members_count': members_count,
            'active_tasks_count': active_tasks_count,
            'status': status
        })
    
    upcoming_tasks = EngineeringTask.query.filter(
        EngineeringTask.status.in_(['PENDING', 'ASSIGNED']),
        EngineeringTask.scheduled_start >= datetime.now(),
        EngineeringTask.scheduled_start <= datetime.now() + timedelta(days=7)
    ).order_by(EngineeringTask.scheduled_start).limit(10).all()
    
    expiring_certs = db.session.query(EmployeeSkill, Employee).join(
        Employee, Employee.id == EmployeeSkill.employee_id
    ).filter(
        EmployeeSkill.expiry_date.isnot(None),
        EmployeeSkill.expiry_date >= date.today(),
        EmployeeSkill.expiry_date <= date.today() + timedelta(days=60)
    ).order_by(EmployeeSkill.expiry_date).limit(5).all()
    
    stats = {
        'total_teams': total_teams,
        'total_engineers': total_engineers,
        'active_tasks': active_tasks,
        'overdue_tasks': overdue_tasks,
        'completed_this_month': completed_this_month,
        'todays_timesheets': todays_timesheets
    }
    
    return render_template('engineering/dashboard.html',
                         stats=stats,
                         teams_status=teams_status,
                         upcoming_tasks=upcoming_tasks,
                         expiring_certs=expiring_certs)

@engineering_bp.route('/teams')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def teams():
    teams = EngineeringTeam.query.order_by(EngineeringTeam.is_active.desc(), EngineeringTeam.code).all()
    
    teams_data = []
    for team in teams:
        members_count = EngineeringTeamMember.query.filter_by(team_id=team.id, is_active=True).count()
        active_tasks = EngineeringTask.query.filter_by(assigned_team_id=team.id).filter(
            EngineeringTask.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        teams_data.append({
            'team': team,
            'members_count': members_count,
            'active_tasks': active_tasks
        })
    
    return render_template('engineering/teams.html', teams_data=teams_data)

@engineering_bp.route('/teams/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def add_team():
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            team_leader_id = request.form.get('team_leader_id', type=int)
            specialty = request.form.get('specialty')
            cost_center_id = request.form.get('cost_center_id', type=int)
            branch_id = request.form.get('branch_id', type=int)
            max_concurrent_tasks = request.form.get('max_concurrent_tasks', 5, type=int)
            description = request.form.get('description', '')
            
            if EngineeringTeam.query.filter_by(code=code).first():
                flash(f'رمز الفريق {code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            team = EngineeringTeam(
                code=code,
                name=name,
                team_leader_id=team_leader_id,
                specialty=specialty,
                cost_center_id=cost_center_id,
                branch_id=branch_id,
                max_concurrent_tasks=max_concurrent_tasks,
                description=description,
                is_active=True
            )
            
            db.session.add(team)
            db.session.commit()
            
            flash(f'✅ تم إضافة الفريق {code} - {name} بنجاح', 'success')
            return redirect(url_for('engineering.teams'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    employees = Employee.query.order_by(Employee.name).all()
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    branches = Branch.query.all()
    
    return render_template('engineering/team_form.html',
                         team=None,
                         employees=employees,
                         cost_centers=cost_centers,
                         branches=branches)

@engineering_bp.route('/tasks')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def tasks():
    status_filter = request.args.get('status')
    team_filter = request.args.get('team', type=int)
    priority_filter = request.args.get('priority')
    
    query = EngineeringTask.query
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if team_filter:
        query = query.filter_by(assigned_team_id=team_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    
    tasks = query.order_by(
        EngineeringTask.priority.desc(),
        EngineeringTask.scheduled_start
    ).all()
    
    teams = EngineeringTeam.query.filter_by(is_active=True).order_by(EngineeringTeam.name).all()
    employees = Employee.query.order_by(Employee.name).all()
    
    stats = {
        'total': len(tasks),
        'pending': sum(1 for t in tasks if t.status == 'PENDING'),
        'in_progress': sum(1 for t in tasks if t.status == 'IN_PROGRESS'),
        'completed': sum(1 for t in tasks if t.status == 'COMPLETED'),
        'overdue': sum(1 for t in tasks if t.scheduled_end and t.scheduled_end < datetime.now() and t.status not in ['COMPLETED', 'CANCELLED'])
    }
    
    return render_template('engineering/tasks.html',
                         tasks=tasks,
                         teams=teams,
                         employees=employees,
                         stats=stats,
                         selected_status=status_filter,
                         selected_team=team_filter)

@engineering_bp.route('/tasks/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def add_task():
    if request.method == 'POST':
        try:
            task_number = request.form.get('task_number')
            title = request.form.get('title')
            description = request.form.get('description', '')
            task_type = request.form.get('task_type')
            priority = request.form.get('priority', 'MEDIUM')
            assigned_team_id = request.form.get('assigned_team_id', type=int)
            assigned_to_id = request.form.get('assigned_to_id', type=int)
            estimated_hours = Decimal(request.form.get('estimated_hours', 0))
            estimated_cost = Decimal(request.form.get('estimated_cost', 0))
            scheduled_start = datetime.strptime(request.form.get('scheduled_start'), '%Y-%m-%dT%H:%M')
            scheduled_end_str = request.form.get('scheduled_end')
            scheduled_end = datetime.strptime(scheduled_end_str, '%Y-%m-%dT%H:%M') if scheduled_end_str else None
            customer_id = request.form.get('customer_id', type=int)
            location = request.form.get('location', '')
            cost_center_id = request.form.get('cost_center_id', type=int)
            
            if EngineeringTask.query.filter_by(task_number=task_number).first():
                flash(f'رقم المهمة {task_number} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            task = EngineeringTask(
                task_number=task_number,
                title=title,
                description=description,
                task_type=task_type,
                priority=priority,
                status='PENDING',
                assigned_team_id=assigned_team_id,
                assigned_to_id=assigned_to_id,
                estimated_hours=estimated_hours,
                estimated_cost=estimated_cost,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                customer_id=customer_id,
                location=location,
                cost_center_id=cost_center_id
            )
            
            db.session.add(task)
            db.session.commit()
            
            flash(f'✅ تم إضافة المهمة {task_number} - {title} بنجاح', 'success')
            return redirect(url_for('engineering.tasks'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    teams = EngineeringTeam.query.filter_by(is_active=True).order_by(EngineeringTeam.name).all()
    employees = Employee.query.order_by(Employee.name).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    return render_template('engineering/task_form.html',
                         task=None,
                         teams=teams,
                         employees=employees,
                         customers=customers,
                         cost_centers=cost_centers)

@engineering_bp.route('/timesheets')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def timesheets():
    employee_filter = request.args.get('employee', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    status_filter = request.args.get('status')
    
    query = EngineeringTimesheet.query
    
    if employee_filter:
        query = query.filter_by(employee_id=employee_filter)
    if date_from:
        query = query.filter(EngineeringTimesheet.work_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(EngineeringTimesheet.work_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    timesheets = query.order_by(EngineeringTimesheet.work_date.desc()).all()
    
    employees = Employee.query.order_by(Employee.name).all()
    
    stats = {
        'total': len(timesheets),
        'draft': sum(1 for t in timesheets if t.status == 'DRAFT'),
        'submitted': sum(1 for t in timesheets if t.status == 'SUBMITTED'),
        'approved': sum(1 for t in timesheets if t.status == 'APPROVED'),
        'total_hours': sum(float(t.actual_work_hours or 0) for t in timesheets),
        'total_cost': sum(float(t.total_cost or 0) for t in timesheets)
    }
    
    return render_template('engineering/timesheets.html',
                         timesheets=timesheets,
                         employees=employees,
                         stats=stats,
                         selected_employee=employee_filter,
                         date_from=date_from,
                         date_to=date_to,
                         selected_status=status_filter)

@engineering_bp.route('/timesheets/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def add_timesheet():
    if request.method == 'POST':
        try:
            employee_id = request.form.get('employee_id', type=int)
            task_id = request.form.get('task_id', type=int)
            work_date = datetime.strptime(request.form.get('work_date'), '%Y-%m-%d').date()
            start_time = datetime.strptime(request.form.get('start_time'), '%H:%M').time()
            end_time = datetime.strptime(request.form.get('end_time'), '%H:%M').time()
            break_duration = request.form.get('break_duration_minutes', 0, type=int)
            
            start_dt = datetime.combine(work_date, start_time)
            end_dt = datetime.combine(work_date, end_time)
            work_minutes = (end_dt - start_dt).total_seconds() / 60 - break_duration
            actual_work_hours = Decimal(work_minutes / 60)
            
            hourly_rate = Decimal(request.form.get('hourly_rate', 0))
            total_cost = actual_work_hours * hourly_rate
            
            work_description = request.form.get('work_description', '')
            cost_center_id = request.form.get('cost_center_id', type=int)
            
            timesheet = EngineeringTimesheet(
                employee_id=employee_id,
                task_id=task_id,
                work_date=work_date,
                start_time=start_time,
                end_time=end_time,
                break_duration_minutes=break_duration,
                actual_work_hours=actual_work_hours,
                billable_hours=actual_work_hours,
                hourly_rate=hourly_rate,
                total_cost=total_cost,
                work_description=work_description,
                cost_center_id=cost_center_id,
                status='DRAFT'
            )
            
            db.session.add(timesheet)
            db.session.commit()
            
            flash(f'✅ تم تسجيل ساعات العمل بنجاح', 'success')
            return redirect(url_for('engineering.timesheets'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    employees = Employee.query.order_by(Employee.name).all()
    tasks = EngineeringTask.query.filter(
        EngineeringTask.status.in_(['ASSIGNED', 'IN_PROGRESS'])
    ).order_by(EngineeringTask.task_number).all()
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    return render_template('engineering/timesheet_form.html',
                         timesheet=None,
                         employees=employees,
                         tasks=tasks,
                         cost_centers=cost_centers)

@engineering_bp.route('/skills')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def skills():
    skills = EngineeringSkill.query.order_by(EngineeringSkill.category, EngineeringSkill.name).all()
    
    return render_template('engineering/skills.html', skills=skills)

@engineering_bp.route('/reports/productivity')
@login_required
@permission_required(SystemPermissions.MANAGE_ENGINEERING)
def report_productivity():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    team_id = request.args.get('team', type=int)
    
    if not date_from:
        date_from = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not date_to:
        date_to = date.today().strftime('%Y-%m-%d')
    
    query = EngineeringTimesheet.query.filter(
        EngineeringTimesheet.work_date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
        EngineeringTimesheet.work_date <= datetime.strptime(date_to, '%Y-%m-%d').date()
    )
    
    if team_id:
        team_members = [m.employee_id for m in EngineeringTeamMember.query.filter_by(team_id=team_id, is_active=True).all()]
        query = query.filter(EngineeringTimesheet.employee_id.in_(team_members))
    
    timesheets = query.all()
    
    productivity_data = []
    
    employees_worked = set(t.employee_id for t in timesheets)
    
    for emp_id in employees_worked:
        employee = db.session.get(Employee, emp_id)
        emp_sheets = [t for t in timesheets if t.employee_id == emp_id]
        
        total_hours = sum(float(t.actual_work_hours or 0) for t in emp_sheets)
        billable_hours = sum(float(t.billable_hours or 0) for t in emp_sheets if t.billable_hours)
        total_cost = sum(float(t.total_cost or 0) for t in emp_sheets)
        
        completed_tasks = len(set(t.task_id for t in emp_sheets if t.task_id and t.task.status == 'COMPLETED'))
        
        avg_rating = 0
        ratings = [t for t in emp_sheets if t.productivity_rating]
        if ratings:
            rating_values = {'POOR': 1, 'FAIR': 2, 'GOOD': 3, 'VERY_GOOD': 4, 'EXCELLENT': 5}
            avg_rating = sum(rating_values.get(t.productivity_rating, 0) for t in ratings) / len(ratings)
        
        productivity_data.append({
            'employee': employee,
            'total_hours': total_hours,
            'billable_hours': billable_hours,
            'total_cost': total_cost,
            'completed_tasks': completed_tasks,
            'avg_rating': avg_rating,
            'working_days': len(set(t.work_date for t in emp_sheets))
        })
    
    productivity_data.sort(key=lambda x: x['total_hours'], reverse=True)
    
    teams = EngineeringTeam.query.filter_by(is_active=True).order_by(EngineeringTeam.name).all()
    
    return render_template('engineering/report_productivity.html',
                         productivity_data=productivity_data,
                         teams=teams,
                         date_from=date_from,
                         date_to=date_to,
                         selected_team=team_id)
