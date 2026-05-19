from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (WorkflowDefinition, WorkflowInstance, WorkflowAction, 
                   ProjectMilestone, ProjectChangeOrder, User)
from services.workflow_engine import WorkflowEngine
from sqlalchemy import func, and_, or_, desc
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
import json
from utils import permission_required, naive_utc_for_delta

workflows_bp = Blueprint('workflows', __name__, url_prefix='/workflows')

@workflows_bp.before_request
@login_required
def restrict_workflows_access():
    # الحماية: فقط للمالك والمطور (Level 0)
    if not (current_user.is_system or current_user.role_name_l in ['owner', 'developer']):
        flash('⛔ غير مصرح لك بالوصول لإدارة سير العمل', 'danger')
        return redirect(url_for('main.dashboard'))


@workflows_bp.route('/')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def index():
    try:
        db.session.rollback()
    except Exception:
        pass
    stats = WorkflowEngine.get_workflow_stats()
    try:
        recent_instances = WorkflowInstance.query.order_by(
            WorkflowInstance.started_at.desc()
        ).limit(10).all()
    except Exception as exc:
        current_app.logger.warning("workflows.index recent_instances failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        recent_instances = []
    try:
        active_definitions = WorkflowDefinition.query.filter_by(is_active=True).all()
    except Exception as exc:
        current_app.logger.warning("workflows.index definitions failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        active_definitions = []
    
    return render_template('workflows/index.html',
                         stats=stats,
                         recent_instances=recent_instances,
                         active_definitions=active_definitions)


@workflows_bp.route('/definitions')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def definitions():
    entity_type_filter = request.args.get('entity_type')
    workflow_type_filter = request.args.get('workflow_type')
    
    query = WorkflowDefinition.query
    
    if entity_type_filter:
        query = query.filter_by(entity_type=entity_type_filter)
    
    if workflow_type_filter:
        query = query.filter_by(workflow_type=workflow_type_filter)
    
    definitions = query.order_by(WorkflowDefinition.workflow_code).all()
    
    definitions_data = []
    for definition in definitions:
        instances_count = WorkflowInstance.query.filter_by(
            workflow_definition_id=definition.id
        ).count()
        
        active_instances = WorkflowInstance.query.filter_by(
            workflow_definition_id=definition.id
        ).filter(
            WorkflowInstance.status.in_(['IN_PROGRESS', 'PENDING_APPROVAL'])
        ).count()
        
        definitions_data.append({
            'definition': definition,
            'instances_count': instances_count,
            'active_instances': active_instances
        })
    
    return render_template('workflows/definitions.html',
                         definitions_data=definitions_data,
                         entity_type_filter=entity_type_filter,
                         workflow_type_filter=workflow_type_filter)


@workflows_bp.route('/definitions/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def add_definition():
    if request.method == 'POST':
        try:
            workflow_code = request.form.get('workflow_code')
            workflow_name = request.form.get('workflow_name')
            workflow_name_ar = request.form.get('workflow_name_ar')
            entity_type = request.form.get('entity_type')
            workflow_type = request.form.get('workflow_type', 'APPROVAL')
            description = request.form.get('description')
            auto_start = request.form.get('auto_start') == 'on'
            timeout_hours = request.form.get('timeout_hours', type=int)
            
            if WorkflowDefinition.query.filter_by(workflow_code=workflow_code).first():
                flash(f'رمز Workflow {workflow_code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            steps_json = request.form.get('steps_definition')
            if not steps_json:
                flash('يجب تحديد خطوات Workflow', 'danger')
                return redirect(request.url)
            
            try:
                steps = json.loads(steps_json)
            except Exception:
                flash('خطأ في تنسيق خطوات Workflow', 'danger')
                return redirect(request.url)
            
            definition = WorkflowDefinition(
                workflow_code=workflow_code,
                workflow_name=workflow_name,
                workflow_name_ar=workflow_name_ar,
                description=description,
                workflow_type=workflow_type,
                entity_type=entity_type,
                steps_definition=steps,
                auto_start=auto_start,
                is_active=True,
                timeout_hours=timeout_hours,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(definition)
            db.session.commit()
            
            flash(f'✅ تم إضافة Workflow {workflow_code} بنجاح', 'success')
            return redirect(url_for('workflows.definitions'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    return render_template('workflows/definition_form.html', definition=None)


@workflows_bp.route('/definitions/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def edit_definition(id):
    definition = db.get_or_404(WorkflowDefinition, id)
    
    if request.method == 'POST':
        try:
            definition.workflow_name = request.form.get('workflow_name')
            definition.workflow_name_ar = request.form.get('workflow_name_ar')
            definition.description = request.form.get('description')
            definition.workflow_type = request.form.get('workflow_type', 'APPROVAL')
            definition.auto_start = request.form.get('auto_start') == 'on'
            definition.timeout_hours = request.form.get('timeout_hours', type=int)
            definition.is_active = request.form.get('is_active') == 'on'
            
            steps_json = request.form.get('steps_definition')
            if steps_json:
                try:
                    definition.steps_definition = json.loads(steps_json)
                except Exception:
                    flash('خطأ في تنسيق خطوات Workflow', 'danger')
                    return redirect(request.url)
            
            definition.updated_by = current_user.id
            definition.updated_at = datetime.now()
            
            db.session.commit()
            
            flash('✅ تم تحديث Workflow بنجاح', 'success')
            return redirect(url_for('workflows.definitions'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    return render_template('workflows/definition_form.html', definition=definition)


@workflows_bp.route('/definitions/<int:id>/toggle', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def toggle_definition(id):
    try:
        definition = db.get_or_404(WorkflowDefinition, id)
        definition.is_active = not definition.is_active
        definition.updated_by = current_user.id
        definition.updated_at = datetime.now()
        
        db.session.commit()
        
        status = 'مفعل' if definition.is_active else 'معطل'
        flash(f'✅ Workflow الآن {status}', 'success')
        return redirect(url_for('workflows.definitions'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('workflows.definitions'))


@workflows_bp.route('/instances')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def instances():
    status_filter = request.args.get('status')
    entity_type_filter = request.args.get('entity_type')
    
    query = WorkflowInstance.query
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    if entity_type_filter:
        query = query.filter_by(entity_type=entity_type_filter)
    
    instances = query.order_by(WorkflowInstance.started_at.desc()).all()
    
    return render_template('workflows/instances.html',
                         instances=instances,
                         status_filter=status_filter,
                         entity_type_filter=entity_type_filter)


@workflows_bp.route('/instances/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def view_instance(id):
    instance = db.get_or_404(WorkflowInstance, id)
    
    history = WorkflowEngine.get_workflow_history(id)
    
    workflow_def = instance.workflow_definition
    steps = workflow_def.steps_definition
    
    current_step_def = None
    if instance.current_step <= len(steps):
        current_step_def = steps[instance.current_step - 1]
    
    can_approve = False
    can_reject = False
    if current_step_def and instance.status in ['IN_PROGRESS', 'PENDING_APPROVAL']:
        approvers = current_step_def.get('approvers', [])
        if current_user.id in approvers or 'ALL' in approvers:
            can_approve = True
            can_reject = True
    
    entity = None
    if instance.entity_type == 'MILESTONE':
        entity = db.session.get(ProjectMilestone, instance.entity_id)
    elif instance.entity_type == 'CHANGE_ORDER':
        entity = db.session.get(ProjectChangeOrder, instance.entity_id)
    
    return render_template('workflows/instance_view.html',
                         instance=instance,
                         history=history,
                         workflow_def=workflow_def,
                         current_step_def=current_step_def,
                         can_approve=can_approve,
                         can_reject=can_reject,
                         entity=entity)


@workflows_bp.route('/instances/<int:id>/execute', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def execute_action(id):
    try:
        action_type = request.form.get('action_type')
        decision = request.form.get('decision')
        comments = request.form.get('comments')
        
        success = WorkflowEngine.execute_action(
            instance_id=id,
            actor_id=current_user.id,
            action_type=action_type,
            decision=decision,
            comments=comments
        )
        
        if success:
            action_label = {
                'APPROVE': 'الموافقة',
                'REJECT': 'الرفض',
                'REVIEW': 'المراجعة',
                'COMMENT': 'التعليق'
            }.get(action_type, action_type)
            
            flash(f'✅ تم {action_label} بنجاح', 'success')
        else:
            flash('❌ فشل تنفيذ الإجراء', 'danger')
        
        return redirect(url_for('workflows.view_instance', id=id))
        
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('workflows.view_instance', id=id))


@workflows_bp.route('/instances/<int:id>/cancel', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def cancel_instance(id):
    try:
        reason = request.form.get('reason')
        
        success = WorkflowEngine.cancel_workflow(
            instance_id=id,
            cancelled_by_id=current_user.id,
            reason=reason
        )
        
        if success:
            flash('✅ تم إلغاء Workflow بنجاح', 'success')
        else:
            flash('❌ فشل إلغاء Workflow', 'danger')
        
        return redirect(url_for('workflows.instances'))
        
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('workflows.instances'))


@workflows_bp.route('/my-pending')
@login_required
def my_pending():
    pending_instances = WorkflowEngine.get_pending_actions(current_user.id)
    
    return render_template('workflows/my_pending.html',
                         pending_instances=pending_instances)


@workflows_bp.route('/api/start', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def api_start_workflow():
    try:
        data = request.get_json()
        
        workflow_code = data.get('workflow_code')
        entity_type = data.get('entity_type')
        entity_id = data.get('entity_id')
        context_data = data.get('context_data', {})
        
        instance = WorkflowEngine.start_workflow(
            workflow_code=workflow_code,
            entity_type=entity_type,
            entity_id=entity_id,
            started_by_id=current_user.id,
            context_data=context_data
        )
        
        if instance:
            return jsonify({
                'success': True,
                'instance_id': instance.id,
                'instance_code': instance.instance_code
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to start workflow'}), 400
            
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500


@workflows_bp.route('/reports/summary')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def report_summary():
    entity_type = request.args.get('entity_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = WorkflowInstance.query
    
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(WorkflowInstance.started_at >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        query = query.filter(WorkflowInstance.started_at <= date_to_obj)
    
    instances = query.all()
    
    by_status = {}
    for instance in instances:
        status = instance.status
        if status not in by_status:
            by_status[status] = 0
        by_status[status] += 1
    
    by_definition = {}
    for instance in instances:
        def_name = instance.workflow_definition.workflow_name
        if def_name not in by_definition:
            by_definition[def_name] = 0
        by_definition[def_name] += 1
    
    avg_completion_time = 0
    completed_instances = [i for i in instances if i.status == 'APPROVED' and i.completed_at]
    
    if completed_instances:
        total_time = 0.0
        for i in completed_instances:
            sa = naive_utc_for_delta(i.started_at)
            ca = naive_utc_for_delta(i.completed_at)
            if sa and ca:
                total_time += max(0.0, (ca - sa).total_seconds() / 3600.0)
        avg_completion_time = total_time / len(completed_instances)
    
    stats = {
        'total': len(instances),
        'by_status': by_status,
        'by_definition': by_definition,
        'avg_completion_hours': round(avg_completion_time, 2)
    }
    
    return render_template('workflows/report_summary.html',
                         stats=stats,
                         instances=instances,
                         entity_type=entity_type,
                         date_from=date_from,
                         date_to=date_to)


@workflows_bp.route('/reports/performance')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def report_performance():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = WorkflowInstance.query
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        except (ValueError, TypeError):
            date_from_obj = None
        query = query.filter(WorkflowInstance.started_at >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        query = query.filter(WorkflowInstance.started_at <= date_to_obj)
    
    instances = query.all()
    
    performance_by_user = {}
    for instance in instances:
        actions = WorkflowAction.query.filter_by(workflow_instance_id=instance.id).all()
        
        for action in actions:
            actor_name = action.actor.username if action.actor else 'Unknown'
            
            if actor_name not in performance_by_user:
                performance_by_user[actor_name] = {
                    'total_actions': 0,
                    'approvals': 0,
                    'rejections': 0,
                    'comments': 0,
                    'avg_response_time': 0,
                    'response_times': []
                }
            
            performance_by_user[actor_name]['total_actions'] += 1
            
            if action.action_type == 'APPROVE':
                performance_by_user[actor_name]['approvals'] += 1
            elif action.action_type == 'REJECT':
                performance_by_user[actor_name]['rejections'] += 1
            elif action.action_type == 'COMMENT':
                performance_by_user[actor_name]['comments'] += 1
            
            if action.duration_hours:
                performance_by_user[actor_name]['response_times'].append(float(action.duration_hours))
    
    for user_data in performance_by_user.values():
        if user_data['response_times']:
            user_data['avg_response_time'] = sum(user_data['response_times']) / len(user_data['response_times'])
        else:
            user_data['avg_response_time'] = 0
    
    bottleneck_steps = {}
    for instance in instances:
        actions = WorkflowAction.query.filter_by(workflow_instance_id=instance.id).order_by(WorkflowAction.action_date).all()
        
        for i in range(len(actions) - 1):
            step_name = actions[i].step_name
            ad0 = naive_utc_for_delta(actions[i].action_date)
            ad1 = naive_utc_for_delta(actions[i + 1].action_date)
            time_diff = (max(0.0, (ad1 - ad0).total_seconds()) / 3600.0) if (ad0 and ad1) else 0.0
            
            if step_name not in bottleneck_steps:
                bottleneck_steps[step_name] = {'times': [], 'avg': 0}
            
            bottleneck_steps[step_name]['times'].append(time_diff)
    
    for step_name, data in bottleneck_steps.items():
        if data['times']:
            data['avg'] = sum(data['times']) / len(data['times'])
            data['count'] = len(data['times'])
    
    bottleneck_list = sorted(bottleneck_steps.items(), key=lambda x: x[1]['avg'], reverse=True)[:10]
    
    workflow_efficiency = {}
    for definition in WorkflowDefinition.query.filter_by(is_active=True).all():
        def_instances = [i for i in instances if i.workflow_definition_id == definition.id]
        
        if def_instances:
            approved = len([i for i in def_instances if i.status == 'APPROVED'])
            rejected = len([i for i in def_instances if i.status == 'REJECTED'])
            timeout = len([i for i in def_instances if i.status == 'TIMEOUT'])
            
            workflow_efficiency[definition.workflow_name] = {
                'total': len(def_instances),
                'approved': approved,
                'rejected': rejected,
                'timeout': timeout,
                'approval_rate': (approved / len(def_instances) * 100) if def_instances else 0,
                'efficiency_score': ((approved - timeout) / len(def_instances) * 100) if def_instances else 0
            }
    
    return render_template('workflows/report_performance.html',
                         performance_by_user=performance_by_user,
                         bottleneck_steps=bottleneck_list,
                         workflow_efficiency=workflow_efficiency,
                         date_from=date_from,
                         date_to=date_to)


@workflows_bp.route('/reports/cost-center-analysis')
@login_required
@permission_required(SystemPermissions.MANAGE_WORKFLOWS)
def report_cost_center_analysis():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    from models import CostCenter, CostCenterAllocation
    
    query = CostCenter.query.filter_by(is_active=True)
    centers = query.all()
    
    analysis_data = []
    
    for center in centers:
        alloc_query = CostCenterAllocation.query.filter_by(cost_center_id=center.id)
        
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            alloc_query = alloc_query.filter(CostCenterAllocation.allocation_date >= date_from_obj)
        
        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            alloc_query = alloc_query.filter(CostCenterAllocation.allocation_date <= date_to_obj)
        
        allocations = alloc_query.all()
        
        total_allocated = sum(float(a.amount or 0) for a in allocations)
        
        by_source = {}
        for alloc in allocations:
            source = alloc.source_type
            if source not in by_source:
                by_source[source] = 0
            by_source[source] += float(alloc.amount or 0)
        
        budget = float(center.budget_amount or 0)
        variance = budget - total_allocated
        
        analysis_data.append({
            'center': center,
            'total_allocated': total_allocated,
            'budget': budget,
            'variance': variance,
            'variance_percent': (variance / budget * 100) if budget > 0 else 0,
            'utilization_rate': (total_allocated / budget * 100) if budget > 0 else 0,
            'by_source': by_source,
            'allocation_count': len(allocations)
        })
    
    analysis_data.sort(key=lambda x: x['total_allocated'], reverse=True)
    
    totals = {
        'total_budget': sum(d['budget'] for d in analysis_data),
        'total_allocated': sum(d['total_allocated'] for d in analysis_data),
        'total_variance': sum(d['variance'] for d in analysis_data)
    }
    
    return render_template('workflows/report_cost_center_analysis.html',
                         analysis_data=analysis_data,
                         totals=totals,
                         date_from=date_from,
                         date_to=date_to)

