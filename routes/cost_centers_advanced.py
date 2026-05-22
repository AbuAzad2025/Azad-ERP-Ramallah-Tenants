from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (CostCenter, CostCenterAlert, CostCenterAlertLog,
                   CostAllocationRule, CostAllocationLine, 
                   CostAllocationExecution, CostAllocationExecutionLine,
                   CostCenterAllocation, User, GLBatch)
from sqlalchemy import func, and_, or_, desc, text as sa_text
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
from utils import permission_required

cost_centers_advanced_bp = Blueprint('cost_centers_advanced', __name__, url_prefix='/cost-centers')

@cost_centers_advanced_bp.before_request
@login_required
def restrict_cost_centers_access():
    # الحماية: فقط للمالك والمطور (Level 0)
    from permissions_config.role_policy import is_platform_owner_role

    if not is_platform_owner_role(current_user):
        flash('⛔ غير مصرح لك بالوصول لمراكز التكلفة المتقدمة', 'danger')
        return redirect(url_for('main.dashboard'))


@cost_centers_advanced_bp.route('/dashboard')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def dashboard():
    total_centers = CostCenter.query.filter_by(is_active=True).count()
    
    total_budget = db.session.query(func.sum(CostCenter.budget_amount)).filter_by(is_active=True).scalar() or 0
    
    total_allocated = db.session.query(func.sum(CostCenterAllocation.amount)).join(
        CostCenter, CostCenter.id == CostCenterAllocation.cost_center_id
    ).filter(CostCenter.is_active == True).scalar() or 0
    
    budget_usage = (float(total_allocated) / float(total_budget or 1)) * 100
    
    active_alerts = CostCenterAlert.query.filter_by(is_active=True).count()
    
    triggered_today = CostCenterAlertLog.query.filter(
        CostCenterAlertLog.triggered_at >= date.today()
    ).count()
    
    top_consumers = db.session.query(
        CostCenter,
        func.sum(CostCenterAllocation.amount).label('total')
    ).join(
        CostCenterAllocation, CostCenter.id == CostCenterAllocation.cost_center_id
    ).filter(
        CostCenter.is_active == True
    ).group_by(CostCenter.id).order_by(desc('total')).limit(5).all()
    
    over_budget = []
    for center in CostCenter.query.filter(
        CostCenter.is_active == True,
        CostCenter.budget_amount > 0
    ).all():
        allocated = db.session.query(func.sum(CostCenterAllocation.amount)).filter_by(
            cost_center_id=center.id
        ).scalar() or 0
        
        if allocated > center.budget_amount:
            over_budget.append({
                'center': center,
                'budget': float(center.budget_amount),
                'allocated': float(allocated),
                'excess': float(allocated - center.budget_amount),
                'excess_percent': ((allocated - center.budget_amount) / center.budget_amount) * 100
            })
    
    stats = {
        'total_centers': total_centers,
        'total_budget': float(total_budget),
        'total_allocated': float(total_allocated),
        'budget_remaining': float(total_budget - total_allocated),
        'budget_usage': budget_usage,
        'active_alerts': active_alerts,
        'triggered_today': triggered_today,
        'over_budget_count': len(over_budget)
    }
    
    return render_template('cost_centers/dashboard.html',
                         stats=stats,
                         top_consumers=top_consumers,
                         over_budget=over_budget)

@cost_centers_advanced_bp.route('/alerts')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def alerts_list():
    cost_center_id = request.args.get('cost_center', type=int)
    alert_type = request.args.get('type')
    
    query = CostCenterAlert.query
    
    if cost_center_id:
        query = query.filter_by(cost_center_id=cost_center_id)
    
    if alert_type:
        query = query.filter_by(alert_type=alert_type)
    
    alerts = query.order_by(CostCenterAlert.is_active.desc(), CostCenterAlert.id.desc()).all()
    
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    return render_template('cost_centers/alerts.html',
                         alerts=alerts,
                         cost_centers=cost_centers,
                         selected_center=cost_center_id,
                         selected_type=alert_type)

@cost_centers_advanced_bp.route('/alerts/add', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def add_alert():
    try:
        cost_center_id = request.form.get('cost_center_id', type=int)
        alert_type = request.form.get('alert_type')
        threshold_type = request.form.get('threshold_type', 'PERCENTAGE')
        threshold_value = Decimal(request.form.get('threshold_value') or 0)
        if threshold_value <= 0:
            flash('قيمة العتبة يجب أن تكون أكبر من صفر', 'danger')
            return redirect(url_for('cost_centers_advanced.alerts_list'))
        notify_manager = request.form.get('notify_manager') == 'on'
        
        alert = CostCenterAlert(
            cost_center_id=cost_center_id,
            alert_type=alert_type,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
            notify_manager=notify_manager,
            is_active=True,
            trigger_count=0,
            created_by=current_user.id,
            updated_by=current_user.id
        )
        
        db.session.add(alert)
        db.session.commit()
        
        flash('✅ تم إضافة التنبيه بنجاح', 'success')
        return redirect(url_for('cost_centers_advanced.alerts_list'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('cost_centers_advanced.alerts_list'))

@cost_centers_advanced_bp.route('/alerts/<int:alert_id>/toggle', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def toggle_alert(alert_id):
    try:
        alert = db.get_or_404(CostCenterAlert, alert_id)
        alert.is_active = not alert.is_active
        alert.updated_by = current_user.id
        alert.updated_at = datetime.now()
        
        db.session.commit()
        
        status = 'مفعل' if alert.is_active else 'معطل'
        flash(f'✅ التنبيه الآن {status}', 'success')
        return redirect(url_for('cost_centers_advanced.alerts_list'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('cost_centers_advanced.alerts_list'))

@cost_centers_advanced_bp.route('/allocation-rules')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def allocation_rules():
    rules = CostAllocationRule.query.order_by(CostAllocationRule.is_active.desc(), CostAllocationRule.code).all()
    
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    rules_data = []
    for rule in rules:
        lines_count = CostAllocationLine.query.filter_by(rule_id=rule.id).count()
        executions_count = CostAllocationExecution.query.filter_by(rule_id=rule.id).count()
        
        last_exec = CostAllocationExecution.query.filter_by(
            rule_id=rule.id
        ).order_by(CostAllocationExecution.execution_date.desc()).first()
        
        rules_data.append({
            'rule': rule,
            'lines_count': lines_count,
            'executions_count': executions_count,
            'last_execution': last_exec
        })
    
    return render_template('cost_centers/allocation_rules.html',
                         rules_data=rules_data,
                         cost_centers=cost_centers)

@cost_centers_advanced_bp.route('/allocation-rules/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def add_allocation_rule():
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            source_cost_center_id = request.form.get('source_cost_center_id', type=int)
            allocation_method = request.form.get('allocation_method')
            frequency = request.form.get('frequency')
            auto_execute = request.form.get('auto_execute') == 'on'
            description = request.form.get('description', '')
            
            if CostAllocationRule.query.filter_by(code=code).first():
                flash(f'رمز القاعدة {code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            rule = CostAllocationRule(
                code=code,
                name=name,
                source_cost_center_id=source_cost_center_id,
                allocation_method=allocation_method,
                frequency=frequency,
                auto_execute=auto_execute,
                description=description,
                is_active=True,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(rule)
            db.session.flush()
            
            target_centers = request.form.getlist('target_center_id[]')
            percentages = request.form.getlist('percentage[]')
            
            for i, target_id in enumerate(target_centers):
                if target_id:
                    line = CostAllocationLine(
                        rule_id=rule.id,
                        target_cost_center_id=int(target_id),
                        percentage=Decimal(percentages[i]) if i < len(percentages) and percentages[i] else None
                    )
                    db.session.add(line)
            
            db.session.commit()
            
            flash(f'✅ تم إضافة قاعدة التوزيع {code} - {name} بنجاح', 'success')
            return redirect(url_for('cost_centers_advanced.allocation_rules'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    return render_template('cost_centers/allocation_rule_form.html',
                         cost_centers=cost_centers,
                         rule=None)

@cost_centers_advanced_bp.route('/allocation-rules/<int:rule_id>/execute', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def execute_allocation_rule(rule_id):
    try:
        rule = db.get_or_404(CostAllocationRule, rule_id)
        
        if not rule.is_active:
            flash('⚠️ لا يمكن تنفيذ قاعدة غير مفعلة', 'warning')
            return redirect(url_for('cost_centers_advanced.allocation_rules'))
        
        execution_date = datetime.strptime(request.form.get('execution_date'), '%Y-%m-%d').date()
        total_amount = Decimal(request.form.get('total_amount') or 0)
        if total_amount <= 0:
            flash('مبلغ التوزيع يجب أن يكون أكبر من صفر', 'danger')
            return redirect(url_for('cost_centers_advanced.allocation_rules'))
        
        execution = CostAllocationExecution(
            rule_id=rule.id,
            execution_date=execution_date,
            total_amount=total_amount,
            status='DRAFT',
            created_by=current_user.id,
            updated_by=current_user.id
        )
        
        db.session.add(execution)
        db.session.flush()
        
        lines = CostAllocationLine.query.filter_by(rule_id=rule.id).all()
        
        for line in lines:
            if rule.allocation_method == 'PERCENTAGE' and line.percentage:
                amount = total_amount * (line.percentage / 100)
            elif rule.allocation_method == 'EQUAL':
                amount = total_amount / len(lines)
            else:
                amount = line.fixed_amount or Decimal('0')
            
            exec_line = CostAllocationExecutionLine(
                execution_id=execution.id,
                source_cost_center_id=rule.source_cost_center_id,
                target_cost_center_id=line.target_cost_center_id,
                amount=amount,
                percentage=line.percentage
            )
            
            db.session.add(exec_line)
            
            alloc = CostCenterAllocation(
                cost_center_id=line.target_cost_center_id,
                source_type='ALLOCATION',
                source_id=execution.id,
                amount=amount,
                allocation_date=execution_date,
                notes=f'توزيع تلقائي: {rule.name}'
            )
            db.session.add(alloc)
        
        execution.status = 'EXECUTED'
        rule.last_executed_at = datetime.now()
        
        db.session.commit()
        
        flash(f'✅ تم تنفيذ التوزيع بنجاح: {total_amount} ₪', 'success')
        return redirect(url_for('cost_centers_advanced.allocation_rules'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('cost_centers_advanced.allocation_rules'))

@cost_centers_advanced_bp.route('/reports/trends')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def report_trends():
    cost_center_id = request.args.get('cost_center', type=int)
    months = request.args.get('months', 12, type=int)
    
    if cost_center_id:
        center = db.get_or_404(CostCenter, cost_center_id)
        centers = [center]
    else:
        centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).limit(10).all()
    
    trends_data = []
    
    for center in centers:
        monthly_data = []
        
        for i in range(months):
            month_date = date.today().replace(day=1) - timedelta(days=30 * i)
            month_start = month_date.replace(day=1)
            
            if month_date.month == 12:
                month_end = month_date.replace(year=month_date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
            
            total = db.session.query(func.sum(CostCenterAllocation.amount)).filter(
                CostCenterAllocation.cost_center_id == center.id,
                CostCenterAllocation.allocation_date >= month_start,
                CostCenterAllocation.allocation_date <= month_end
            ).scalar() or 0
            
            monthly_data.append({
                'month': month_date.strftime('%Y-%m'),
                'month_name': month_date.strftime('%B %Y'),
                'amount': float(total)
            })
        
        monthly_data.reverse()
        
        avg_monthly = sum(m['amount'] for m in monthly_data) / len(monthly_data) if monthly_data else 0
        
        last_month = monthly_data[-1]['amount'] if monthly_data else 0
        second_last = monthly_data[-2]['amount'] if len(monthly_data) > 1 else 0
        
        trend = 'up' if last_month > second_last else 'down' if last_month < second_last else 'stable'
        
        trends_data.append({
            'center': center,
            'monthly_data': monthly_data,
            'avg_monthly': avg_monthly,
            'trend': trend
        })
    
    cost_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    
    return render_template('cost_centers/report_trends.html',
                         trends_data=trends_data,
                         cost_centers=cost_centers,
                         selected_center=cost_center_id,
                         months=months)


