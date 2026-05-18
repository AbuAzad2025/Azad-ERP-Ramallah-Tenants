from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (CostCenter, CostCenterAllocation, Payment, Expense, Sale, ServiceRequest,
                   GLEntry, Account, Branch, SystemSettings)
from sqlalchemy import func, and_, or_, desc
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from utils import permission_required
from permissions_config.enums import SystemPermissions

cost_centers_bp = Blueprint('cost_centers', __name__, url_prefix='/cost-centers')


@cost_centers_bp.route('/')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def index():
    parent_id = request.args.get('parent', type=int)
    
    if parent_id:
        parent_center = db.get_or_404(CostCenter, parent_id)
        cost_centers = CostCenter.query.filter_by(parent_id=parent_id).order_by(CostCenter.code).all()
    else:
        parent_center = None
        cost_centers = CostCenter.query.filter_by(parent_id=None).order_by(CostCenter.code).all()
    
    center_ids = [c.id for c in cost_centers]
    alloc_stats = {}
    if center_ids:
        alloc_rows = (
            db.session.query(
                CostCenterAllocation.cost_center_id.label("center_id"),
                func.coalesce(func.sum(CostCenterAllocation.amount), 0).label("total_allocated"),
                func.count(CostCenterAllocation.id).label("allocations_count"),
            )
            .filter(CostCenterAllocation.cost_center_id.in_(center_ids))
            .group_by(CostCenterAllocation.cost_center_id)
            .all()
        )
        for r in alloc_rows:
            cid = int(getattr(r, "center_id", 0) or 0)
            alloc_stats[cid] = (
                float(getattr(r, "total_allocated", 0) or 0),
                int(getattr(r, "allocations_count", 0) or 0),
            )

    children_counts = {}
    if center_ids:
        child_rows = (
            db.session.query(
                CostCenter.parent_id.label("parent_id"),
                func.count(CostCenter.id).label("children_count"),
            )
            .filter(CostCenter.parent_id.in_(center_ids))
            .group_by(CostCenter.parent_id)
            .all()
        )
        for r in child_rows:
            pid = int(getattr(r, "parent_id", 0) or 0)
            children_counts[pid] = int(getattr(r, "children_count", 0) or 0)

    centers_data = []
    for center in cost_centers:
        total_allocated, allocations_count = alloc_stats.get(center.id, (0.0, 0))
        children_count = children_counts.get(center.id, 0)
        
        centers_data.append({
            'center': center,
            'total_allocated': float(total_allocated),
            'children_count': children_count,
            'allocations_count': allocations_count,
            'budget_usage': (float(total_allocated) / float(center.budget_amount or 1)) * 100 if center.budget_amount else 0
        })
    
    return render_template('cost_centers/index.html',
                         centers=centers_data,
                         parent_center=parent_center)


@cost_centers_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def add():
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            parent_id = request.form.get('parent_id', type=int)
            manager_id = request.form.get('manager_id', type=int)
            try:
                budget_amount = Decimal(request.form.get('budget_amount', 0))
            except (InvalidOperation, TypeError, ValueError):
                budget_amount = Decimal(0)
            if budget_amount < 0:
                flash('مبلغ الميزانية لا يمكن أن يكون سالباً', 'danger')
                return redirect(request.url)
            description = request.form.get('description', '')
            
            if CostCenter.query.filter_by(code=code).first():
                flash(f'رمز مركز التكلفة {code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            cost_center = CostCenter(
                code=code,
                name=name,
                parent_id=parent_id,
                manager_id=manager_id,
                budget_amount=budget_amount,
                description=description,
                is_active=True,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(cost_center)
            db.session.commit()
            
            flash(f'✅ تم إضافة مركز التكلفة {code} - {name} بنجاح', 'success')
            return redirect(url_for('cost_centers.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    from models import User
    parent_centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    managers = User.query.filter_by(is_active=True).order_by(User.username).all()
    
    return render_template('cost_centers/form.html',
                         parent_centers=parent_centers,
                         managers=managers,
                         center=None)


@cost_centers_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def edit(id):
    center = db.get_or_404(CostCenter, id)
    
    if request.method == 'POST':
        try:
            center.name = request.form.get('name')
            center.manager_id = request.form.get('manager_id', type=int)
            try:
                center.budget_amount = Decimal(request.form.get('budget_amount', 0))
            except (InvalidOperation, TypeError, ValueError):
                center.budget_amount = Decimal(0)
            if center.budget_amount < 0:
                flash('مبلغ الميزانية لا يمكن أن يكون سالباً', 'danger')
                return redirect(request.url)
            center.description = request.form.get('description', '')
            center.is_active = request.form.get('is_active') == 'on'
            center.updated_by = current_user.id
            center.updated_at = datetime.now()
            
            db.session.commit()
            
            flash(f'✅ تم تحديث مركز التكلفة بنجاح', 'success')
            return redirect(url_for('cost_centers.view', id=id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    from models import User
    parent_centers = CostCenter.query.filter(
        CostCenter.id != id,
        CostCenter.is_active == True
    ).order_by(CostCenter.code).all()
    
    managers = User.query.filter_by(is_active=True).order_by(User.username).all()
    
    return render_template('cost_centers/form.html',
                         parent_centers=parent_centers,
                         managers=managers,
                         center=center)


@cost_centers_bp.route('/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def view(id):
    center = db.get_or_404(CostCenter, id)
    
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    allocations = CostCenterAllocation.query.filter_by(cost_center_id=id).order_by(
        CostCenterAllocation.allocation_date.desc(),
        CostCenterAllocation.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    children = CostCenter.query.filter_by(parent_id=id).order_by(CostCenter.code).all()
    
    total_allocated = db.session.query(func.sum(CostCenterAllocation.amount)).filter_by(
        cost_center_id=id
    ).scalar() or 0
    
    this_month_start = date.today().replace(day=1)
    this_month_allocated = db.session.query(func.sum(CostCenterAllocation.amount)).filter(
        CostCenterAllocation.cost_center_id == id,
        CostCenterAllocation.allocation_date >= this_month_start
    ).scalar() or 0
    
    this_year_start = date.today().replace(month=1, day=1)
    this_year_allocated = db.session.query(func.sum(CostCenterAllocation.amount)).filter(
        CostCenterAllocation.cost_center_id == id,
        CostCenterAllocation.allocation_date >= this_year_start
    ).scalar() or 0
    
    stats = {
        'total_allocated': float(total_allocated),
        'this_month': float(this_month_allocated),
        'this_year': float(this_year_allocated),
        'budget': float(center.budget_amount or 0),
        'budget_remaining': float(center.budget_amount or 0) - float(total_allocated),
        'budget_usage_percent': (float(total_allocated) / float(center.budget_amount or 1)) * 100 if center.budget_amount else 0,
        'children_count': len(children),
        'allocations_count': allocations.total
    }
    
    return render_template('cost_centers/view.html',
                         center=center,
                         allocations=allocations,
                         children=children,
                         stats=stats)


@cost_centers_bp.route('/<int:id>/allocate', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def allocate(id):
    try:
        center = db.get_or_404(CostCenter, id)
        
        amount = Decimal(request.form.get('amount'))
        if amount < 0:
            flash('مبلغ التوزيع لا يمكن أن يكون سالباً', 'danger')
            return redirect(url_for('cost_centers.view', id=id))
        allocation_date = datetime.strptime(request.form.get('allocation_date'), '%Y-%m-%d').date()
        reference_type = request.form.get('reference_type')
        reference_id = request.form.get('reference_id', type=int)
        description = request.form.get('description', '')
        
        allocation = CostCenterAllocation(
            cost_center_id=id,
            source_type=reference_type,
            source_id=reference_id,
            amount=amount,
            allocation_date=allocation_date,
            notes=description
        )
        
        db.session.add(allocation)
        db.session.commit()
        
        flash(f'✅ تم توزيع {float(amount):.2f} على المركز بنجاح', 'success')
        return redirect(url_for('cost_centers.view', id=id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('cost_centers.view', id=id))


@cost_centers_bp.route('/reports/summary')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def report_summary():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    parent_id = request.args.get('parent', type=int)
    
    query = CostCenter.query.filter_by(is_active=True)
    
    if parent_id:
        query = query.filter_by(parent_id=parent_id)
    
    centers = query.order_by(CostCenter.code).all()
    
    date_from_obj = None
    date_to_obj = None
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()

    center_ids = [c.id for c in centers]
    totals_by_center = {}
    if center_ids:
        alloc_filters = [CostCenterAllocation.cost_center_id.in_(center_ids)]
        if date_from_obj:
            alloc_filters.append(CostCenterAllocation.allocation_date >= date_from_obj)
        if date_to_obj:
            alloc_filters.append(CostCenterAllocation.allocation_date <= date_to_obj)
        agg = (
            db.session.query(
                CostCenterAllocation.cost_center_id.label("center_id"),
                func.coalesce(func.sum(CostCenterAllocation.amount), 0).label("total_allocated"),
                func.count(CostCenterAllocation.id).label("allocations_count"),
            )
            .filter(*alloc_filters)
            .group_by(CostCenterAllocation.cost_center_id)
            .all()
        )
        for r in agg:
            cid = int(getattr(r, "center_id", 0) or 0)
            totals_by_center[cid] = (
                float(getattr(r, "total_allocated", 0) or 0),
                int(getattr(r, "allocations_count", 0) or 0),
            )

    summary_data = []
    for center in centers:
        total_allocated, allocations_count = totals_by_center.get(center.id, (0.0, 0))
        summary_data.append({
            'center': center,
            'total_allocated': float(total_allocated),
            'budget': float(center.budget_amount or 0),
            'budget_remaining': float(center.budget_amount or 0) - float(total_allocated),
            'budget_usage': (float(total_allocated) / float(center.budget_amount or 1)) * 100 if center.budget_amount else 0,
            'allocations_count': allocations_count
        })
    
    grand_totals = {
        'total_allocated': sum(d['total_allocated'] for d in summary_data),
        'total_budget': sum(d['budget'] for d in summary_data),
        'total_remaining': sum(d['budget_remaining'] for d in summary_data)
    }
    
    parent_centers = CostCenter.query.filter_by(is_active=True, parent_id=None).order_by(CostCenter.code).all()
    
    return render_template('cost_centers/report_summary.html',
                         summary_data=summary_data,
                         grand_totals=grand_totals,
                         parent_centers=parent_centers,
                         date_from=date_from,
                         date_to=date_to,
                         selected_parent=parent_id)


@cost_centers_bp.route('/reports/comparison')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def report_comparison():
    period1_from = request.args.get('period1_from')
    period1_to = request.args.get('period1_to')
    period2_from = request.args.get('period2_from')
    period2_to = request.args.get('period2_to')
    
    centers = CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all()
    center_ids = [c.id for c in centers]
    
    p1_from = None
    p1_to = None
    p2_from = None
    p2_to = None
    if period1_from and period1_to:
        p1_from = datetime.strptime(period1_from, '%Y-%m-%d').date()
        p1_to = datetime.strptime(period1_to, '%Y-%m-%d').date()
    if period2_from and period2_to:
        p2_from = datetime.strptime(period2_from, '%Y-%m-%d').date()
        p2_to = datetime.strptime(period2_to, '%Y-%m-%d').date()

    p1_totals = {}
    p2_totals = {}
    if center_ids and p1_from and p1_to:
        rows = (
            db.session.query(
                CostCenterAllocation.cost_center_id.label("center_id"),
                func.coalesce(func.sum(CostCenterAllocation.amount), 0).label("total"),
            )
            .filter(
                CostCenterAllocation.cost_center_id.in_(center_ids),
                CostCenterAllocation.allocation_date.between(p1_from, p1_to),
            )
            .group_by(CostCenterAllocation.cost_center_id)
            .all()
        )
        for r in rows:
            cid = int(getattr(r, "center_id", 0) or 0)
            p1_totals[cid] = float(getattr(r, "total", 0) or 0)

    if center_ids and p2_from and p2_to:
        rows = (
            db.session.query(
                CostCenterAllocation.cost_center_id.label("center_id"),
                func.coalesce(func.sum(CostCenterAllocation.amount), 0).label("total"),
            )
            .filter(
                CostCenterAllocation.cost_center_id.in_(center_ids),
                CostCenterAllocation.allocation_date.between(p2_from, p2_to),
            )
            .group_by(CostCenterAllocation.cost_center_id)
            .all()
        )
        for r in rows:
            cid = int(getattr(r, "center_id", 0) or 0)
            p2_totals[cid] = float(getattr(r, "total", 0) or 0)

    comparison_data = []
    
    for center in centers:
        period1_total = p1_totals.get(center.id, 0.0)
        period2_total = p2_totals.get(center.id, 0.0)
        
        variance = float(period2_total) - float(period1_total)
        variance_percent = (variance / float(period1_total or 1)) * 100 if period1_total else 0
        
        comparison_data.append({
            'center': center,
            'period1_total': float(period1_total),
            'period2_total': float(period2_total),
            'variance': variance,
            'variance_percent': variance_percent
        })
    
    grand_totals = {
        'period1': sum(d['period1_total'] for d in comparison_data),
        'period2': sum(d['period2_total'] for d in comparison_data),
        'variance': sum(d['variance'] for d in comparison_data)
    }
    
    return render_template('cost_centers/report_comparison.html',
                         comparison_data=comparison_data,
                         grand_totals=grand_totals,
                         period1_from=period1_from,
                         period1_to=period1_to,
                         period2_from=period2_from,
                         period2_to=period2_to)


@cost_centers_bp.route('/reports/budget-variance')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def report_budget_variance():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    centers = CostCenter.query.filter(
        CostCenter.is_active == True,
        CostCenter.budget_amount > 0
    ).order_by(CostCenter.code).all()
    
    variance_data = []
    
    for center in centers:
        alloc_query = CostCenterAllocation.query.filter_by(cost_center_id=center.id)
        
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            alloc_query = alloc_query.filter(CostCenterAllocation.allocation_date >= date_from_obj)
        
        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            alloc_query = alloc_query.filter(CostCenterAllocation.allocation_date <= date_to_obj)
        
        actual = db.session.query(func.sum(CostCenterAllocation.amount)).filter(
            alloc_query.whereclause
        ).scalar() or 0
        
        budget = float(center.budget_amount)
        variance = budget - float(actual)
        variance_percent = (variance / budget) * 100 if budget else 0
        
        variance_data.append({
            'center': center,
            'budget': budget,
            'actual': float(actual),
            'variance': variance,
            'variance_percent': variance_percent,
            'status': 'under' if variance > 0 else 'over' if variance < 0 else 'on_budget'
        })
    
    variance_data.sort(key=lambda x: abs(x['variance']), reverse=True)
    
    totals = {
        'budget': sum(d['budget'] for d in variance_data),
        'actual': sum(d['actual'] for d in variance_data),
        'variance': sum(d['variance'] for d in variance_data)
    }
    
    return render_template('cost_centers/report_budget_variance.html',
                         variance_data=variance_data,
                         totals=totals,
                         date_from=date_from,
                         date_to=date_to)


@cost_centers_bp.route('/api/hierarchy')
@login_required
@permission_required(SystemPermissions.MANAGE_COST_CENTERS)
def api_hierarchy():
    def build_tree(parent_id=None):
        centers = CostCenter.query.filter_by(parent_id=parent_id, is_active=True).order_by(CostCenter.code).all()
        result = []
        
        for center in centers:
            total_allocated = db.session.query(func.sum(CostCenterAllocation.amount)).filter_by(
                cost_center_id=center.id
            ).scalar() or 0
            
            node = {
                'id': center.id,
                'code': center.code,
                'name': center.name,
                'budget': float(center.budget_amount or 0),
                'total_allocated': float(total_allocated),
                'children': build_tree(center.id)
            }
            result.append(node)
        
        return result
    
    hierarchy = build_tree()
    
    return jsonify({'success': True, 'hierarchy': hierarchy})
