from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (Project, ProjectTask, ProjectResource, ProjectMilestone, ProjectRisk,
                   ProjectChangeOrder, ResourceTimeLog, Employee, Product, User, Invoice)
from sqlalchemy import func, and_, or_, desc, case
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from utils import permission_required

project_advanced_bp = Blueprint('project_advanced', __name__, url_prefix='/projects')


@project_advanced_bp.route('/dashboard')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def advanced_dashboard():
    """
    لوحة تحكم المشاريع المتقدمة (Global Dashboard)
    تعرض ملخصاً لجميع المشاريع النشطة ومؤشرات الأداء العامة
    """
    # 1. إحصائيات عامة
    projects = Project.query.all()
    total_projects = len(projects)
    active_projects = sum(1 for p in projects if p.status in ('ACTIVE', 'PLANNED'))
    completed_projects = sum(1 for p in projects if p.status == 'COMPLETED')
    
    # حساب نسبة الإنجاز الكلية (متوسط نسب إنجاز المشاريع النشطة)
    active_progress_sum = sum(float(p.completion_percentage or 0) for p in projects if p.status == 'ACTIVE')
    active_count = sum(1 for p in projects if p.status == 'ACTIVE')
    avg_progress = (active_progress_sum / active_count) if active_count else 0
    
    # 2. المخاطر (risk_level hybrid — نستخدم risk_score في SQL)
    high_risks = ProjectRisk.query.filter(
        ProjectRisk.status != 'CLOSED',
        ProjectRisk.risk_score >= 10,
    ).count()
    
    # 3. الميزانية (تجاوز الميزانية)
    # مشروع يعتبر متجاوزاً إذا كانت التكلفة الفعلية > الميزانية
    over_budget_count = 0
    for p in projects:
        budget = float(p.budget_amount or 0)
        cost = float(p.actual_cost or 0)
        if budget > 0 and cost > budget:
            over_budget_count += 1

    # 4. قائمة المشاريع (لجدول الحالة)
    # نحتاج تفاصيل إضافية مثل المدير، الموعد النهائي، الحالة
    projects_list = []
    for p in projects:
        # حساب التقدم (موجود في المودل عادة أو يحسب)
        progress = float(p.completion_percentage or 0)
        
        # تحديد حالة الخطر للمشروع (بناءً على المخاطر المفتوحة)
        project_risks = ProjectRisk.query.filter_by(project_id=p.id).all()
        risk_status = 'normal'
        for r in project_risks:
            if r.status == 'CLOSED':
                continue
            score = float(r.risk_score or 0)
            if score >= 15:
                risk_status = 'critical'
                break
            if score >= 10:
                risk_status = 'high'
            
        # المدير
        manager_name = p.manager.username if p.manager else 'غير محدد'
        
        projects_list.append({
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'manager': manager_name,
            'end_date': p.end_date,
            'progress': progress,
            'status': p.status,
            'risk_status': risk_status
        })
    
    # 5. توزيع الموارد (Mock logic replaced with real aggregation)
    # تجميع تكاليف الموارد حسب النوع عبر كل المشاريع
    resource_stats = db.session.query(
        ProjectResource.resource_type,
        func.count(ProjectResource.id)
    ).group_by(ProjectResource.resource_type).all()
    
    resource_distribution = {
        'labels': [],
        'data': []
    }
    type_map = {'EMPLOYEE': 'موظفين', 'MATERIAL': 'مواد', 'EQUIPMENT': 'معدات', 'SUBCONTRACTOR': 'مقاولين'}
    
    for r_type, count in resource_stats:
        resource_distribution['labels'].append(type_map.get(r_type, r_type))
        resource_distribution['data'].append(count)
        
    dashboard_data = {
        'total_active': active_projects,
        'avg_progress': round(avg_progress, 1),
        'high_risks': high_risks,
        'over_budget': over_budget_count,
        'projects': projects_list,
        'resources': resource_distribution
    }

    return render_template('projects/advanced/dashboard.html', data=dashboard_data)


@project_advanced_bp.route('/<int:project_id>/tasks')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def tasks(project_id):
    project = db.get_or_404(Project, project_id)
    
    status_filter = request.args.get('status')
    assigned_to = request.args.get('assigned_to', type=int)
    
    query = ProjectTask.query.filter_by(project_id=project_id)
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    if assigned_to:
        query = query.filter_by(assigned_to=assigned_to)
    
    tasks = query.order_by(ProjectTask.due_date).all()
    
    overdue_count = sum(1 for t in tasks if t.is_overdue)
    blocked_count = sum(1 for t in tasks if t.status == 'BLOCKED')
    completed_count = sum(1 for t in tasks if t.status == 'COMPLETED')
    
    stats = {
        'total': len(tasks),
        'overdue': overdue_count,
        'blocked': blocked_count,
        'completed': completed_count,
        'in_progress': sum(1 for t in tasks if t.status == 'IN_PROGRESS'),
        'completion_rate': (completed_count / len(tasks) * 100) if tasks else 0
    }
    
    users = User.query.all()
    from models import ProjectPhase
    phases = ProjectPhase.query.filter_by(project_id=project_id).order_by(ProjectPhase.order).all()
    all_tasks = ProjectTask.query.filter_by(project_id=project_id).all()
    
    return render_template('projects/advanced/tasks.html',
                         project=project,
                         tasks=tasks,
                         stats=stats,
                         users=users,
                         phases=phases,
                         all_tasks=all_tasks,
                         selected_status=status_filter)


@project_advanced_bp.route('/<int:project_id>/tasks/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_task(project_id):
    try:
        project = db.get_or_404(Project, project_id)
        
        task_count = ProjectTask.query.filter_by(project_id=project_id).count()
        task_number = f"{project.code}-T{task_count + 1:03d}"
        
        try:
            start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = None
        try:
            due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            due_date = None
        try:
            estimated_hours = Decimal(request.form.get('estimated_hours', 0))
        except (InvalidOperation, TypeError, ValueError):
            estimated_hours = Decimal(0)
        
        task = ProjectTask(
            project_id=project_id,
            phase_id=request.form.get('phase_id', type=int),
            task_number=task_number,
            name=request.form.get('name'),
            description=request.form.get('description'),
            assigned_to=request.form.get('assigned_to', type=int),
            priority=request.form.get('priority', 'MEDIUM'),
            start_date=start_date,
            due_date=due_date,
            estimated_hours=estimated_hours
        )
        
        depends_on = request.form.getlist('depends_on')
        if depends_on:
            task.depends_on = [int(tid) for tid in depends_on if tid]
        
        db.session.add(task)
        db.session.commit()
        
        flash(f'تم إضافة المهمة {task_number} بنجاح', 'success')
        return redirect(url_for('project_advanced.tasks', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer or url_for('project_advanced.tasks', project_id=project_id))


@project_advanced_bp.route('/<int:project_id>/resources')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def resources(project_id):
    project = db.get_or_404(Project, project_id)
    
    resource_type = request.args.get('type')
    
    query = ProjectResource.query.filter_by(project_id=project_id)
    
    if resource_type:
        query = query.filter_by(resource_type=resource_type)
    
    resources = query.order_by(ProjectResource.allocation_date.desc()).all()
    
    total_cost = sum(float(r.total_cost or 0) for r in resources)
    
    by_type = db.session.query(
        ProjectResource.resource_type,
        func.count(ProjectResource.id),
        func.sum(ProjectResource.total_cost)
    ).filter_by(project_id=project_id).group_by(ProjectResource.resource_type).all()
    
    stats = {
        'total_resources': len(resources),
        'total_cost': total_cost,
        'by_type': {r[0]: {'count': r[1], 'cost': float(r[2] or 0)} for r in by_type}
    }
    
    employees = Employee.query.all()
    products = Product.query.all()
    tasks = ProjectTask.query.filter_by(project_id=project_id).all()
    
    return render_template('projects/advanced/resources.html',
                         project=project,
                         resources=resources,
                         stats=stats,
                         employees=employees,
                         products=products,
                         tasks=tasks)


@project_advanced_bp.route('/<int:project_id>/resources/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_resource(project_id):
    try:
        resource_type = request.form.get('resource_type')
        try:
            quantity = Decimal(request.form.get('quantity', 1))
        except (InvalidOperation, TypeError, ValueError):
            quantity = Decimal(1)
        try:
            unit_cost = Decimal(request.form.get('unit_cost', 0))
        except (InvalidOperation, TypeError, ValueError):
            unit_cost = Decimal(0)
        total_cost = quantity * unit_cost
        try:
            hours_allocated = Decimal(request.form.get('hours_allocated', 0))
        except (InvalidOperation, TypeError, ValueError):
            hours_allocated = Decimal(0)
        
        resource = ProjectResource(
            project_id=project_id,
            task_id=request.form.get('task_id', type=int),
            resource_type=resource_type,
            employee_id=request.form.get('employee_id', type=int) if resource_type == 'EMPLOYEE' else None,
            product_id=request.form.get('product_id', type=int) if resource_type == 'MATERIAL' else None,
            resource_name=request.form.get('resource_name'),
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            hours_allocated=hours_allocated,
            status='ALLOCATED',
            notes=request.form.get('notes')
        )
        
        db.session.add(resource)
        db.session.commit()
        
        flash('تم تخصيص المورد بنجاح', 'success')
        return redirect(url_for('project_advanced.resources', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/milestones')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def milestones(project_id):
    project = db.get_or_404(Project, project_id)
    
    milestones = ProjectMilestone.query.filter_by(project_id=project_id).order_by(
        ProjectMilestone.due_date
    ).all()
    
    overdue = sum(1 for m in milestones if m.is_overdue)
    completed = sum(1 for m in milestones if m.status == 'COMPLETED')
    billed = sum(1 for m in milestones if m.status in ['BILLED', 'PAID'])
    total_billing = sum(float(m.billing_amount or 0) for m in milestones)
    invoiced = sum(float(m.billing_amount or 0) for m in milestones if m.invoice_id)
    
    stats = {
        'total': len(milestones),
        'overdue': overdue,
        'completed': completed,
        'billed': billed,
        'total_billing': total_billing,
        'invoiced': invoiced,
        'pending_invoice': total_billing - invoiced
    }
    
    from models import ProjectPhase
    phases = ProjectPhase.query.filter_by(project_id=project_id).order_by(ProjectPhase.order).all()
    
    return render_template('projects/advanced/milestones.html',
                         project=project,
                         milestones=milestones,
                         phases=phases,
                         stats=stats)


@project_advanced_bp.route('/<int:project_id>/milestones/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_milestone(project_id):
    try:
        project = db.get_or_404(Project, project_id)
        
        milestone_count = ProjectMilestone.query.filter_by(project_id=project_id).count()
        milestone_number = f"{project.code}-M{milestone_count + 1:02d}"
        
        try:
            due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            due_date = None
        try:
            billing_amount = Decimal(request.form.get('billing_amount', 0))
        except (InvalidOperation, TypeError, ValueError):
            billing_amount = Decimal(0)
        try:
            billing_percentage = Decimal(request.form.get('billing_percentage', 0))
        except (InvalidOperation, TypeError, ValueError):
            billing_percentage = Decimal(0)
        try:
            payment_terms_days = int(request.form.get('payment_terms_days', 30))
        except (ValueError, TypeError):
            payment_terms_days = 30
        
        milestone = ProjectMilestone(
            project_id=project_id,
            phase_id=request.form.get('phase_id', type=int),
            milestone_number=milestone_number,
            name=request.form.get('name'),
            description=request.form.get('description'),
            due_date=due_date,
            billing_amount=billing_amount,
            billing_percentage=billing_percentage,
            payment_terms_days=payment_terms_days,
            completion_criteria=request.form.get('completion_criteria'),
            approval_required=request.form.get('approval_required') == 'on'
        )
        
        deliverables_str = request.form.get('deliverables', '')
        if deliverables_str:
            milestone.deliverables = [d.strip() for d in deliverables_str.split('\n') if d.strip()]
        
        db.session.add(milestone)
        db.session.commit()
        
        flash(f'تم إضافة المحطة {milestone_number} بنجاح', 'success')
        return redirect(url_for('project_advanced.milestones', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/milestones/<int:milestone_id>/complete', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def complete_milestone(project_id, milestone_id):
    try:
        milestone = db.get_or_404(ProjectMilestone, milestone_id)
        
        if milestone.approval_required:
            milestone.status = 'IN_PROGRESS'
            milestone.approved_by = current_user.id
            milestone.approved_at = datetime.now()
        else:
            milestone.status = 'COMPLETED'
            milestone.completed_date = date.today()
        
        db.session.commit()
        
        flash('تم تحديث حالة المحطة بنجاح', 'success')
        return redirect(url_for('project_advanced.milestones', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/risks')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def risks(project_id):
    project = db.get_or_404(Project, project_id)
    
    risks = ProjectRisk.query.filter_by(project_id=project_id).order_by(
        ProjectRisk.risk_score.desc()
    ).all()
    
    critical = sum(1 for r in risks if r.risk_level == 'CRITICAL')
    high = sum(1 for r in risks if r.risk_level == 'HIGH')
    open_risks = sum(1 for r in risks if r.status not in ['CLOSED'])
    
    stats = {
        'total': len(risks),
        'critical': critical,
        'high': high,
        'open': open_risks,
        'total_impact': sum(float(r.actual_impact_cost or 0) for r in risks)
    }
    
    users = User.query.all()
    
    return render_template('projects/advanced/risks.html',
                         project=project,
                         risks=risks,
                         users=users,
                         stats=stats)


@project_advanced_bp.route('/<int:project_id>/risks/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_risk(project_id):
    try:
        project = db.get_or_404(Project, project_id)
        
        risk_count = ProjectRisk.query.filter_by(project_id=project_id).count()
        risk_number = f"{project.code}-R{risk_count + 1:03d}"
        
        probability_map = {'VERY_LOW': 1, 'LOW': 2, 'MEDIUM': 3, 'HIGH': 4, 'VERY_HIGH': 5}
        impact_map = {'NEGLIGIBLE': 1, 'MINOR': 2, 'MODERATE': 3, 'MAJOR': 4, 'CRITICAL': 5}
        
        probability = request.form.get('probability', 'MEDIUM')
        impact = request.form.get('impact', 'MODERATE')
        
        risk_score = probability_map[probability] * impact_map[impact]
        
        risk = ProjectRisk(
            project_id=project_id,
            risk_number=risk_number,
            title=request.form.get('title'),
            description=request.form.get('description'),
            category=request.form.get('category'),
            probability=probability,
            impact=impact,
            risk_score=risk_score,
            mitigation_plan=request.form.get('mitigation_plan'),
            contingency_plan=request.form.get('contingency_plan'),
            owner_id=request.form.get('owner_id', type=int) or current_user.id
        )
        
        db.session.add(risk)
        db.session.commit()
        
        flash(f'تم تسجيل المخاطرة {risk_number} بنجاح', 'success')
        return redirect(url_for('project_advanced.risks', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/change-orders')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def change_orders(project_id):
    project = db.get_or_404(Project, project_id)
    
    change_orders = ProjectChangeOrder.query.filter_by(project_id=project_id).order_by(
        ProjectChangeOrder.requested_date.desc()
    ).all()
    
    pending = sum(1 for co in change_orders if co.status in ['DRAFT', 'SUBMITTED', 'UNDER_REVIEW'])
    approved = sum(1 for co in change_orders if co.status == 'APPROVED')
    total_cost_impact = sum(float(co.cost_impact or 0) for co in change_orders if co.status == 'APPROVED')
    total_schedule_impact = sum(co.schedule_impact_days or 0 for co in change_orders if co.status == 'APPROVED')
    
    stats = {
        'total': len(change_orders),
        'pending': pending,
        'approved': approved,
        'total_cost_impact': total_cost_impact,
        'total_schedule_impact': total_schedule_impact
    }
    
    return render_template('projects/advanced/change_orders.html',
                         project=project,
                         change_orders=change_orders,
                         stats=stats)


@project_advanced_bp.route('/<int:project_id>/change-orders/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def add_change_order(project_id):
    try:
        project = db.get_or_404(Project, project_id)
        
        co_count = ProjectChangeOrder.query.filter_by(project_id=project_id).count()
        change_number = f"{project.code}-CH{co_count + 1:03d}"
        
        try:
            cost_impact = Decimal(request.form.get('cost_impact', 0))
        except (InvalidOperation, TypeError, ValueError):
            cost_impact = Decimal(0)
        try:
            schedule_impact_days = int(request.form.get('schedule_impact_days', 0))
        except (ValueError, TypeError):
            schedule_impact_days = 0
        
        change_order = ProjectChangeOrder(
            project_id=project_id,
            change_number=change_number,
            title=request.form.get('title'),
            description=request.form.get('description'),
            requested_by=current_user.id,
            reason=request.form.get('reason'),
            scope_change=request.form.get('scope_change'),
            cost_impact=cost_impact,
            schedule_impact_days=schedule_impact_days,
            status='SUBMITTED'
        )
        
        db.session.add(change_order)
        db.session.commit()
        
        flash(f'تم تقديم أمر التغيير {change_number} بنجاح', 'success')
        return redirect(url_for('project_advanced.change_orders', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/change-orders/<int:co_id>/approve', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def approve_change_order(project_id, co_id):
    try:
        co = db.get_or_404(ProjectChangeOrder, co_id)
        
        action = request.form.get('action')
        
        if action == 'approve':
            co.status = 'APPROVED'
            co.approved_by = current_user.id
            co.approved_date = date.today()
            flash('تم الموافقة على أمر التغيير', 'success')
        elif action == 'reject':
            co.status = 'REJECTED'
            co.rejection_reason = request.form.get('rejection_reason')
            flash('تم رفض أمر التغيير', 'info')
        
        db.session.commit()
        return redirect(url_for('project_advanced.change_orders', project_id=project_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(request.referrer)


@project_advanced_bp.route('/<int:project_id>/evm')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def earned_value_analysis(project_id):
    project = db.get_or_404(Project, project_id)
    
    # تحويل القيم النقدية إلى float للعمليات الحسابية
    total_budget = float(project.budget_amount or 0)
    actual_cost = float(project.actual_cost or 0)
    
    # حساب القيمة المخططة (PV) بناءً على المهام
    tasks = ProjectTask.query.filter_by(project_id=project_id).all()
    total_tasks = len(tasks)
    
    # حساب نسبة إنجاز المهام
    completed_tasks = sum(1 for t in tasks if t.status == 'COMPLETED')
    
    # PV: القيمة المخططة = الميزانية الكلية * نسبة الإنجاز المخططة (الزمنية)
    # هنا سنستخدم نسبة المهام المنجزة كتقريب
    planned_value = total_budget * (completed_tasks / total_tasks) if total_tasks else 0
    
    # EV: القيمة المكتسبة = الميزانية الكلية * نسبة الإنجاز الفعلية
    completion_pct = float(project.completion_percentage or 0)
    earned_value = total_budget * (completion_pct / 100) if completion_pct else 0
    
    # CV: انحراف التكلفة = EV - AC
    cost_variance = earned_value - actual_cost
    
    # SV: انحراف الجدول الزمني = EV - PV
    schedule_variance = earned_value - planned_value
    
    # CPI: مؤشر أداء التكلفة = EV / AC
    cost_performance_index = earned_value / actual_cost if actual_cost > 0 else 1.0
    
    # SPI: مؤشر أداء الجدول الزمني = EV / PV
    schedule_performance_index = earned_value / planned_value if planned_value > 0 else 1.0
    
    # EAC: التقدير عند الاكتمال = BAC / CPI
    estimate_at_completion = total_budget / cost_performance_index if cost_performance_index > 0 else total_budget
    
    # ETC: التقدير حتى الاكتمال = EAC - AC
    estimate_to_complete = estimate_at_completion - actual_cost
    
    # VAC: التباين عند الاكتمال = BAC - EAC
    variance_at_completion = total_budget - estimate_at_completion
    
    # TCPI: مؤشر الأداء حتى الاكتمال = (BAC - EV) / (BAC - AC)
    remaining_budget = total_budget - actual_cost
    to_complete_performance_index = (total_budget - earned_value) / remaining_budget if remaining_budget > 0 else 0
    
    evm_data = {
        'pv': planned_value,
        'ev': earned_value,
        'ac': actual_cost,
        'bac': total_budget,
        'cv': cost_variance,
        'sv': schedule_variance,
        'cpi': cost_performance_index,
        'spi': schedule_performance_index,
        'eac': estimate_at_completion,
        'etc': estimate_to_complete,
        'vac': variance_at_completion,
        'tcpi': to_complete_performance_index
    }
    
    status = 'healthy'
    if cost_performance_index < 0.9 or schedule_performance_index < 0.9:
        status = 'at_risk'
    if cost_performance_index < 0.8 or schedule_performance_index < 0.8:
        status = 'critical'
    
    evm_data['status'] = status
    
    return render_template('projects/advanced/evm.html',
                         project=project,
                         evm=evm_data)


@project_advanced_bp.route('/<int:project_id>/dashboard')
@login_required
@permission_required(SystemPermissions.MANAGE_PROJECTS)
def dashboard(project_id):
    project = db.get_or_404(Project, project_id)
    
    tasks = ProjectTask.query.filter_by(project_id=project_id).all()
    resources = ProjectResource.query.filter_by(project_id=project_id).all()
    milestones = ProjectMilestone.query.filter_by(project_id=project_id).all()
    risks = ProjectRisk.query.filter_by(project_id=project_id).all()
    change_orders = ProjectChangeOrder.query.filter_by(project_id=project_id).all()
    
    dashboard_data = {
        'tasks': {
            'total': len(tasks),
            'completed': sum(1 for t in tasks if t.status == 'COMPLETED'),
            'overdue': sum(1 for t in tasks if t.is_overdue),
            'blocked': sum(1 for t in tasks if t.status == 'BLOCKED')
        },
        'resources': {
            'total': len(resources),
            'total_cost': sum(float(r.total_cost or 0) for r in resources)
        },
        'milestones': {
            'total': len(milestones),
            'completed': sum(1 for m in milestones if m.status == 'COMPLETED'),
            'billed': sum(1 for m in milestones if m.invoice_id)
        },
        'risks': {
            'total': len(risks),
            'critical': sum(1 for r in risks if r.risk_level == 'CRITICAL'),
            'open': sum(1 for r in risks if r.status not in ['CLOSED'])
        },
        'change_orders': {
            'total': len(change_orders),
            'pending': sum(1 for co in change_orders if co.status in ['SUBMITTED', 'UNDER_REVIEW']),
            'approved': sum(1 for co in change_orders if co.status == 'APPROVED')
        }
    }
    
    return render_template('projects/advanced/single_project_dashboard.html',
                         project=project,
                         data=dashboard_data)

