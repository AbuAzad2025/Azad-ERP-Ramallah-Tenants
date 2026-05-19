import logging

from extensions import db
from models import WorkflowDefinition, WorkflowInstance, WorkflowAction, User
from sqlalchemy import text as sa_text
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import json

logger = logging.getLogger(__name__)


class WorkflowEngine:
    
    @staticmethod
    def start_workflow(
        workflow_code: str,
        entity_type: str,
        entity_id: int,
        started_by_id: int,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Optional[WorkflowInstance]:
        try:
            workflow_def = WorkflowDefinition.query.filter_by(
                workflow_code=workflow_code,
                entity_type=entity_type,
                is_active=True
            ).first()
            
            if not workflow_def:
                return None
            
            steps = workflow_def.steps_definition
            if not isinstance(steps, list) or len(steps) == 0:
                return None
            
            instance_code = f"{workflow_code}-{entity_type}-{entity_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            due_date = None
            if workflow_def.timeout_hours:
                due_date = datetime.now(timezone.utc) + timedelta(hours=workflow_def.timeout_hours)
            
            instance = WorkflowInstance(
                workflow_definition_id=workflow_def.id,
                instance_code=instance_code,
                entity_type=entity_type,
                entity_id=entity_id,
                status='INITIATED',
                current_step=1,
                total_steps=len(steps),
                started_by=started_by_id,
                started_at=datetime.now(timezone.utc),
                due_date=due_date,
                context_data=context_data or {}
            )
            
            db.session.add(instance)
            db.session.flush()
            
            first_step = steps[0]
            action = WorkflowAction(
                workflow_instance_id=instance.id,
                step_number=1,
                step_name=first_step.get('name', f'Step 1'),
                action_type='COMMENT',
                actor_id=started_by_id,
                action_date=datetime.now(timezone.utc),
                comments=f"Workflow initiated: {workflow_def.workflow_name}"
            )
            
            db.session.add(action)
            instance.status = 'IN_PROGRESS'
            
            db.session.commit()
            
            return instance
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error starting workflow: %s", e)
            return None
    
    @staticmethod
    def execute_action(
        instance_id: int,
        actor_id: int,
        action_type: str,
        decision: Optional[str] = None,
        comments: Optional[str] = None,
        attachments: Optional[List[Dict]] = None
    ) -> bool:
        try:
            instance = db.session.get(WorkflowInstance, instance_id)
            if not instance:
                return False
            
            if instance.status not in ['IN_PROGRESS', 'PENDING_APPROVAL']:
                return False
            
            workflow_def = instance.workflow_definition
            steps = workflow_def.steps_definition
            
            if instance.current_step > len(steps):
                return False
            
            current_step_def = steps[instance.current_step - 1]
            
            action = WorkflowAction(
                workflow_instance_id=instance.id,
                step_number=instance.current_step,
                step_name=current_step_def.get('name', f'Step {instance.current_step}'),
                action_type=action_type,
                actor_id=actor_id,
                action_date=datetime.now(timezone.utc),
                decision=decision,
                comments=comments,
                attachments=attachments
            )
            
            db.session.add(action)
            
            if action_type == 'APPROVE':
                if instance.current_step < instance.total_steps:
                    instance.current_step += 1
                    instance.status = 'IN_PROGRESS'
                else:
                    instance.status = 'APPROVED'
                    instance.completed_at = datetime.now(timezone.utc)
                    instance.completed_by = actor_id
                    
                    WorkflowEngine._on_workflow_approved(instance)
            
            elif action_type == 'REJECT':
                instance.status = 'REJECTED'
                instance.completed_at = datetime.now(timezone.utc)
                instance.completed_by = actor_id
                
                WorkflowEngine._on_workflow_rejected(instance)
            
            elif action_type == 'DELEGATE':
                pass
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error executing workflow action: %s", e)
            return False
    
    @staticmethod
    def cancel_workflow(instance_id: int, cancelled_by_id: int, reason: Optional[str] = None) -> bool:
        try:
            instance = db.session.get(WorkflowInstance, instance_id)
            if not instance:
                return False
            
            if instance.status in ['COMPLETED', 'APPROVED', 'REJECTED', 'CANCELLED']:
                return False
            
            instance.status = 'CANCELLED'
            instance.cancelled_at = datetime.now(timezone.utc)
            instance.cancelled_by = cancelled_by_id
            instance.cancellation_reason = reason
            
            action = WorkflowAction(
                workflow_instance_id=instance.id,
                step_number=instance.current_step,
                step_name='Cancellation',
                action_type='COMMENT',
                actor_id=cancelled_by_id,
                action_date=datetime.now(timezone.utc),
                comments=f"Workflow cancelled: {reason or 'No reason provided'}"
            )
            
            db.session.add(action)
            db.session.commit()
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error cancelling workflow: %s", e)
            return False
    
    @staticmethod
    def get_pending_actions(user_id: int) -> List[WorkflowInstance]:
        try:
            instances = WorkflowInstance.query.filter(
                WorkflowInstance.status.in_(['IN_PROGRESS', 'PENDING_APPROVAL'])
            ).all()
            
            pending = []
            for instance in instances:
                workflow_def = instance.workflow_definition
                steps = workflow_def.steps_definition
                
                if instance.current_step <= len(steps):
                    current_step_def = steps[instance.current_step - 1]
                    approvers = current_step_def.get('approvers', [])
                    
                    if user_id in approvers or 'ALL' in approvers:
                        pending.append(instance)
            
            return pending
            
        except Exception as e:
            logger.error("Error getting pending actions: %s", e)
            return []
    
    @staticmethod
    def get_workflow_history(instance_id: int) -> List[WorkflowAction]:
        try:
            return WorkflowAction.query.filter_by(
                workflow_instance_id=instance_id
            ).order_by(WorkflowAction.action_date).all()
            
        except Exception as e:
            logger.error("Error getting workflow history: %s", e)
            return []
    
    @staticmethod
    def check_timeouts():
        try:
            overdue_instances = WorkflowInstance.query.filter(
                WorkflowInstance.status.in_(['IN_PROGRESS', 'PENDING_APPROVAL']),
                WorkflowInstance.due_date < datetime.now(timezone.utc)
            ).all()
            
            for instance in overdue_instances:
                instance.status = 'TIMEOUT'
                
                action = WorkflowAction(
                    workflow_instance_id=instance.id,
                    step_number=instance.current_step,
                    step_name='Timeout',
                    action_type='COMMENT',
                    actor_id=instance.started_by,
                    action_date=datetime.now(timezone.utc),
                    comments='Workflow timed out - escalation required'
                )
                
                db.session.add(action)
                
                WorkflowEngine._escalate_workflow(instance)
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error checking timeouts: %s", e)
    
    @staticmethod
    def _on_workflow_approved(instance: WorkflowInstance):
        if instance.entity_type == 'MILESTONE':
            try:
                from models import ProjectMilestone
                milestone = db.session.get(ProjectMilestone, instance.entity_id)
                if milestone:
                    milestone.status = 'COMPLETED'
                    milestone.completed_date = datetime.now(timezone.utc).date()
                    milestone.approved_by = instance.completed_by
                    milestone.approved_at = instance.completed_at
            except Exception:
                pass
        
        elif instance.entity_type == 'CHANGE_ORDER':
            try:
                from models import ProjectChangeOrder
                change_order = db.session.get(ProjectChangeOrder, instance.entity_id)
                if change_order:
                    change_order.status = 'APPROVED'
                    change_order.approved_by = instance.completed_by
                    change_order.approved_date = instance.completed_at.date() if instance.completed_at else None
            except Exception:
                pass
    
    @staticmethod
    def _on_workflow_rejected(instance: WorkflowInstance):
        if instance.entity_type == 'MILESTONE':
            try:
                from models import ProjectMilestone
                milestone = db.session.get(ProjectMilestone, instance.entity_id)
                if milestone:
                    milestone.status = 'PENDING'
            except Exception:
                pass
        
        elif instance.entity_type == 'CHANGE_ORDER':
            try:
                from models import ProjectChangeOrder
                change_order = db.session.get(ProjectChangeOrder, instance.entity_id)
                if change_order:
                    change_order.status = 'REJECTED'
                    
                    last_action = WorkflowAction.query.filter_by(
                        workflow_instance_id=instance.id
                    ).order_by(WorkflowAction.action_date.desc()).first()
                    
                    if last_action and last_action.comments:
                        change_order.rejection_reason = last_action.comments
            except Exception:
                pass
    
    @staticmethod
    def _escalate_workflow(instance: WorkflowInstance):
        try:
            workflow_def = instance.workflow_definition
            escalation_rules = workflow_def.escalation_rules
            
            if not escalation_rules:
                return
            
            if not isinstance(escalation_rules, dict):
                return
            
            escalate_to_manager = escalation_rules.get('escalate_to_manager', False)
            escalate_to_users = escalation_rules.get('escalate_to_users', [])
            send_notification = escalation_rules.get('send_notification', True)
            
            if escalate_to_manager:
                if instance.entity_type == 'MILESTONE':
                    from models import ProjectMilestone
                    milestone = db.session.get(ProjectMilestone, instance.entity_id)
                    if milestone and milestone.project:
                        manager_id = milestone.project.manager_id
                        if manager_id:
                            action = WorkflowAction(
                                workflow_instance_id=instance.id,
                                step_number=instance.current_step,
                                step_name='Escalation',
                                action_type='COMMENT',
                                actor_id=manager_id,
                                action_date=datetime.now(timezone.utc),
                                comments=f"Workflow escalated due to timeout - requires immediate attention"
                            )
                            db.session.add(action)
            
            for user_id in escalate_to_users:
                action = WorkflowAction(
                    workflow_instance_id=instance.id,
                    step_number=instance.current_step,
                    step_name='Escalation Notice',
                    action_type='COMMENT',
                    actor_id=user_id,
                    action_date=datetime.now(timezone.utc),
                    comments=f"Escalation notification - workflow {instance.instance_code} requires attention"
                )
                db.session.add(action)
            
            db.session.commit()
            
        except Exception as e:
            logger.error("Error escalating workflow: %s", e)
            db.session.rollback()
    
    @staticmethod
    def get_workflow_stats(entity_type: Optional[str] = None) -> Dict[str, Any]:
        try:
            query = WorkflowInstance.query
            
            if entity_type:
                query = query.filter_by(entity_type=entity_type)
            
            total = query.count()
            in_progress = query.filter(WorkflowInstance.status.in_(['IN_PROGRESS', 'PENDING_APPROVAL'])).count()
            approved = query.filter_by(status='APPROVED').count()
            rejected = query.filter_by(status='REJECTED').count()
            timeout = query.filter_by(status='TIMEOUT').count()
            
            try:
                _dialect = str(db.engine.url.drivername or "").lower()
            except Exception:
                try:
                    _dialect = str(db.engine.dialect.name or "").lower()
                except Exception:
                    _dialect = ""
            if "postgres" in _dialect:
                _avg_hours_expr = db.func.avg(
                    db.func.extract(
                        "epoch",
                        WorkflowInstance.completed_at - WorkflowInstance.started_at,
                    )
                    / 3600.0
                )
            else:
                _avg_hours_expr = db.func.avg(
                    db.func.julianday(WorkflowInstance.completed_at)
                    - db.func.julianday(WorkflowInstance.started_at)
                ) * 24.0
            avg_completion_time = db.session.query(_avg_hours_expr).filter(
                WorkflowInstance.status == 'APPROVED',
                WorkflowInstance.completed_at.isnot(None),
                WorkflowInstance.started_at.isnot(None),
            ).scalar()
            
            if avg_completion_time:
                avg_completion_time = float(avg_completion_time)
            else:
                avg_completion_time = 0
            
            return {
                'total': total,
                'in_progress': in_progress,
                'approved': approved,
                'rejected': rejected,
                'timeout': timeout,
                'avg_completion_hours': round(avg_completion_time, 2),
                'approval_rate': (approved / total * 100) if total > 0 else 0
            }
            
        except Exception as e:
            logger.error("Error getting workflow stats: %s", e)
            try:
                db.session.rollback()
            except Exception:
                pass
            return {
                'total': 0,
                'in_progress': 0,
                'approved': 0,
                'rejected': 0,
                'timeout': 0,
                'avg_completion_hours': 0,
                'approval_rate': 0
            }

