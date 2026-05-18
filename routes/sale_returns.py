"""
نظام المرتجعات (Sale Returns)
إدارة مرتجعات البيع بشكل كامل مع إرجاع المخزون
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func, desc
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from extensions import db
from models import (
    SaleReturn, SaleReturnLine, Sale, SaleLine,
    run_sale_return_gl_sync_after_commit,
    Customer, Product, Warehouse, User, AuditLog
)
from forms import SaleReturnForm, SaleReturnLineForm
from utils import permission_required

# إنشاء Blueprint
returns_bp = Blueprint('returns', __name__, url_prefix='/returns')

def _refresh_related_balances(customer_id: Optional[int], lines) -> None:
    try:
        if customer_id:
            from utils.customer_balance_updater import update_customer_balance_components
            update_customer_balance_components(int(customer_id))
    except Exception:
        current_app.logger.warning('Failed to refresh customer balance', exc_info=True)
    try:
        partner_ids = set()
        supplier_ids = set()
        warehouse_ids = set()
        product_ids = set()
        for ln in (lines or []):
            wid = getattr(ln, "warehouse_id", None)
            if wid:
                warehouse_ids.add(int(wid))
            pid = getattr(ln, "product_id", None)
            if pid:
                product_ids.add(int(pid))
        wh_to_partner = {}
        if warehouse_ids:
            for wid, partner_id in db.session.query(Warehouse.id, Warehouse.partner_id).filter(Warehouse.id.in_(warehouse_ids)).all():
                if partner_id:
                    wh_to_partner[int(wid)] = int(partner_id)
        for wid in warehouse_ids:
            partner_id = wh_to_partner.get(int(wid))
            if partner_id:
                partner_ids.add(int(partner_id))
        prod_to_supplier = {}
        if product_ids:
            for pid, supplier_id in db.session.query(Product.id, Product.supplier_id).filter(Product.id.in_(product_ids)).all():
                if supplier_id:
                    prod_to_supplier[int(pid)] = int(supplier_id)
        for ln in (lines or []):
            condition = (getattr(ln, "condition", None) or "GOOD").upper()
            liability = (getattr(ln, "liability_party", None) or "").upper()
            if condition in ("DAMAGED", "UNUSABLE") and liability == "SUPPLIER":
                sid = prod_to_supplier.get(int(getattr(ln, "product_id", 0) or 0))
                if sid:
                    supplier_ids.add(int(sid))
        if partner_ids or supplier_ids:
            import utils
            for pid in partner_ids:
                utils.update_entity_balance("PARTNER", int(pid))
            for sid in supplier_ids:
                utils.update_entity_balance("SUPPLIER", int(sid))
    except Exception:
        current_app.logger.warning('Failed to refresh entity balances', exc_info=True)


@returns_bp.route('/')
@login_required
def list_returns():
    """قائمة جميع المرتجعات"""
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Filters
    status = request.args.get('status', '')
    customer_id = request.args.get('customer_id', 0, type=int)
    search = request.args.get('search', '').strip()
    
    # Build query
    query = SaleReturn.query
    
    # Apply filters
    if status and status in ['DRAFT', 'CONFIRMED', 'CANCELLED']:
        query = query.filter_by(status=status)
    
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    
    if search:
        query = query.join(Customer).filter(
            or_(
                SaleReturn.reason.ilike(f'%{search}%'),
                SaleReturn.notes.ilike(f'%{search}%'),
                Customer.name.ilike(f'%{search}%')
            )
        )
    
    # Sort and paginate
    query = query.order_by(desc(SaleReturn.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get all customers for filter
    customers = Customer.query.filter_by(is_archived=False).order_by(Customer.name).all()
    
    return render_template(
        'sale_returns/list.html',
        pagination=pagination,
        returns=pagination.items,
        customers=customers,
        current_status=status,
        current_customer=customer_id,
        search_term=search
    )


@returns_bp.route('/create', methods=['GET', 'POST'])
@returns_bp.route('/create/<int:sale_id>', methods=['GET', 'POST'])
@login_required
def create_return(sale_id=None):
    """إنشاء مرتجع جديد"""
    
    form = SaleReturnForm()
    sale = None
    
    # إذا تم تمرير sale_id، حمل بيانات البيع
    if sale_id:
        sale = db.get_or_404(Sale, sale_id)
        
        if request.method == 'GET':
            form.sale_id.data = sale.id
            form.customer_id.data = sale.customer_id
            
            # تحديد المخزن الافتراضي من أسطر البيع (إذا كان موحداً)
            sale_warehouses = {line.warehouse_id for line in (sale.lines or []) if line.warehouse_id}
            default_warehouse = sale_warehouses.pop() if len(sale_warehouses) == 1 else None
            if default_warehouse:
                form.warehouse_id.data = default_warehouse
            
            form.currency.data = sale.currency or 'ILS'
        
        # تأكد من وجود هذه الفاتورة ضمن خيارات القائمة (حتى لو كانت خارج آخر 100 فاتورة)
        if not any(choice[0] == sale.id for choice in form.sale_id.choices):
            sale_label = f"بيع #{sale.id} - {sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else ''}"
            form.sale_id.choices.insert(1, (sale.id, sale_label))
    
    # تهيئة افتراضي للمخزن من الإعدادات إذا لم يكن هناك بيع محدد
    if request.method == 'GET' and not sale_id and not (form.warehouse_id.data):
        try:
            from models import SystemSettings
            returns_wh = SystemSettings.get_setting('returns_warehouse_id', None)
            if returns_wh:
                form.warehouse_id.data = int(returns_wh)
        except Exception:
            pass

    if form.validate_on_submit():
        try:
            # إنشاء المرتجع
            sale_return = SaleReturn(
                sale_id=form.sale_id.data if form.sale_id.data else None,
                customer_id=form.customer_id.data,
                warehouse_id=form.warehouse_id.data if form.warehouse_id.data else None,
                reason=form.reason.data.strip(),
                notes=form.notes.data.strip() if form.notes.data else None,
                currency=form.currency.data,
                status='CONFIRMED'
            )
            
            db.session.add(sale_return)
            db.session.flush()
            
            returned_dict = {}
            sale_dict = {}
            sale_line_map = {}
            if sale_return.sale_id:
                from sqlalchemy import func
                confirmed_returns = (
                    db.session.query(
                        SaleReturnLine.product_id,
                        func.coalesce(func.sum(SaleReturnLine.quantity), 0).label('returned_qty')
                    )
                    .join(SaleReturn)
                    .filter(
                        SaleReturn.sale_id == sale_return.sale_id,
                        SaleReturn.status == 'CONFIRMED'
                    )
                    .group_by(SaleReturnLine.product_id)
                    .all()
                )
                returned_dict = {int(pid): int(qty) for pid, qty in confirmed_returns}
                sale = db.session.get(Sale, sale_return.sale_id)
                if sale:
                    sale_dict = {line.product_id: int(line.quantity or 0) for line in sale.lines}
                    for ln in (sale.lines or []):
                        try:
                            sale_line_map[(int(ln.product_id), int(ln.warehouse_id))] = ln
                        except Exception:
                            continue
            
            per_product_totals = {}
            total_amount = Decimal('0.00')
            
            # إضافة السطور مع التحقق
            for line_data in form.lines.data:
                if line_data.get('product_id') and line_data.get('quantity'):
                    product_id = line_data['product_id']
                    new_qty = int(line_data['quantity'])
                    
                    if sale_return.sale_id and sale_dict:
                        original_qty = sale_dict.get(product_id, 0)
                        already_returned = returned_dict.get(product_id, 0)
                        cumulative_qty = per_product_totals.get(product_id, 0) + new_qty
                        if original_qty and (already_returned + cumulative_qty) > original_qty:
                            db.session.rollback()
                            product = db.session.get(Product, product_id)
                            product_name = product.name if product else f'المنتج #{product_id}'
                            available = max(0, original_qty - already_returned)
                            flash(
                                f'خطأ: {product_name} - الكمية المطلوبة ({cumulative_qty}) أكبر من المتاح للإرجاع ({available}). '
                                f'الكمية الأصلية: {original_qty}، المرتجع سابقاً: {already_returned}',
                                'danger'
                            )
                            return redirect(url_for('returns.create_return'))
                        per_product_totals[product_id] = cumulative_qty
                    wh_id = int(line_data.get('warehouse_id') or sale_return.warehouse_id or 0)
                    price = Decimal(str(line_data.get('unit_price', 0) or 0))
                    if sale_return.sale_id and sale_line_map and wh_id:
                        sl = sale_line_map.get((int(product_id), int(wh_id)))
                        if sl is not None:
                            base = Decimal(str(sl.unit_price or 0))
                            dr = Decimal(str(getattr(sl, "discount_rate", 0) or 0))
                            price = base * (Decimal("1") - (dr / Decimal("100")))
                    total_amount += Decimal(new_qty) * price
                    
                    line = SaleReturnLine(
                        sale_return_id=sale_return.id,
                        product_id=product_id,
                        warehouse_id=line_data.get('warehouse_id') or sale_return.warehouse_id,
                        quantity=new_qty,
                        unit_price=float(price),
                        condition=line_data.get('condition', 'GOOD') or 'GOOD',
                        liability_party=line_data.get('liability_party') or None,
                        notes=line_data.get('notes', '').strip() or None
                    )
                    db.session.add(line)
            
            sale_return.total_amount = total_amount.quantize(Decimal('0.01'))
            db.session.flush()
            
            db.session.commit()
            try:
                run_sale_return_gl_sync_after_commit(sale_return.id)
            except Exception:
                current_app.logger.warning('GL sync failed for sale return #%s', sale_return.id, exc_info=True)
            # Audit log
            try:
                audit = AuditLog(
                    model_name='SaleReturn',
                    record_id=sale_return.id,
                    action='CREATE',
                    user_id=current_user.id if current_user.is_authenticated else None
                )
                db.session.add(audit)
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.warning('Audit log failed for sale return CREATE', exc_info=True)
            
            _refresh_related_balances(sale_return.customer_id, list(sale_return.lines or []))
            flash('تم إنشاء المرتجع بنجاح', 'success')
            return redirect(url_for('returns.view_return', return_id=sale_return.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    # تحضير choices للـ template
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(500).all()
    product_choices = [(p.id, f"{p.name} ({p.barcode or 'بدون باركود'})") for p in products]
    
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.name).all()
    warehouse_choices = [(w.id, w.name) for w in warehouses]
    
    return render_template(
        'sale_returns/form.html',
        form=form,
        sale=sale,
        product_choices=product_choices,
        warehouse_choices=warehouse_choices,
        title='إنشاء مرتجع جديد'
    )


@returns_bp.route('/<int:return_id>')
@login_required
def view_return(return_id):
    """عرض تفاصيل مرتجع"""
    
    sale_return = db.get_or_404(SaleReturn, return_id)
    breakdown = None
    try:
        if sale_return.sale_id and sale_return.sale:
            sale = sale_return.sale
            sale_subtotal = Decimal("0.00")
            for ln in (sale.lines or []):
                base = Decimal(str(getattr(ln, "unit_price", 0) or 0))
                qty = Decimal(str(getattr(ln, "quantity", 0) or 0))
                dr = Decimal(str(getattr(ln, "discount_rate", 0) or 0))
                sale_subtotal += (base * qty) * (Decimal("1") - (dr / Decimal("100")))
            items_total = Decimal("0.00")
            for ln in (sale_return.lines or []):
                items_total += Decimal(str(getattr(ln, "unit_price", 0) or 0)) * Decimal(str(getattr(ln, "quantity", 0) or 0))
            if sale_subtotal > Decimal("0"):
                ratio = items_total / sale_subtotal
            else:
                ratio = Decimal("1") if items_total > Decimal("0") else Decimal("0")
            if ratio < Decimal("0"):
                ratio = Decimal("0")
            if ratio > Decimal("1"):
                ratio = Decimal("1")
            disc = Decimal(str(getattr(sale, "discount_total", 0) or 0))
            ship = Decimal(str(getattr(sale, "shipping_cost", 0) or 0))
            disc_share = disc * ratio
            ship_share = ship * ratio
            base_after_discount = items_total - disc_share
            if base_after_discount < Decimal("0"):
                base_after_discount = Decimal("0")
            base_for_tax = base_after_discount + ship_share
            tr = Decimal(str(getattr(sale, "tax_rate", 0) or 0))
            tax_amount = base_for_tax * tr / Decimal("100") if tr > 0 else Decimal("0")
            breakdown = {
                "items_total": float(items_total),
                "discount_share": float(disc_share),
                "shipping_share": float(ship_share),
                "tax_rate": float(tr),
                "tax_amount": float(tax_amount),
                "final_total": float((base_for_tax + tax_amount)),
            }
    except Exception:
        breakdown = None
    
    return render_template(
        'sale_returns/detail.html',
        sale_return=sale_return,
        breakdown=breakdown,
    )


@returns_bp.route('/<int:return_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_return(return_id):
    """تعديل مرتجع"""
    
    sale_return = db.get_or_404(SaleReturn, return_id)
    
    if sale_return.status == 'CANCELLED':
        flash('لا يمكن تعديل مرتجع ملغي', 'warning')
        return redirect(url_for('returns.view_return', return_id=return_id))
    
    form = SaleReturnForm(obj=sale_return)
    
    if request.method == 'GET':
        # تحميل السطور
        form.lines.entries.clear()
        for line in sale_return.lines:
            line_form = SaleReturnLineForm()
            line_form.id.data = line.id
            line_form.product_id.data = line.product_id
            line_form.warehouse_id.data = line.warehouse_id
            line_form.quantity.data = line.quantity
            line_form.unit_price.data = line.unit_price
            line_form.notes.data = line.notes
            form.lines.append_entry(line_form)
    
    if form.validate_on_submit():
        try:
            # تحديث البيانات الأساسية
            sale_return.sale_id = form.sale_id.data if form.sale_id.data else None
            sale_return.customer_id = form.customer_id.data
            sale_return.warehouse_id = form.warehouse_id.data if form.warehouse_id.data else None
            sale_return.reason = form.reason.data.strip()
            sale_return.notes = form.notes.data.strip() if form.notes.data else None
            sale_return.currency = form.currency.data
            sale_return.status = 'CONFIRMED'
            
            returned_dict = {}
            sale_dict = {}
            if sale_return.sale_id:
                from sqlalchemy import func
                confirmed_returns = (
                    db.session.query(
                        SaleReturnLine.product_id,
                        func.coalesce(func.sum(SaleReturnLine.quantity), 0).label('returned_qty')
                    )
                    .join(SaleReturn)
                    .filter(
                        SaleReturn.sale_id == sale_return.sale_id,
                        SaleReturn.status == 'CONFIRMED',
                        SaleReturn.id != sale_return.id
                    )
                    .group_by(SaleReturnLine.product_id)
                    .all()
                )
                returned_dict = {int(pid): int(qty) for pid, qty in confirmed_returns}
                sale = db.session.get(Sale, sale_return.sale_id)
                if sale:
                    sale_dict = {line.product_id: int(line.quantity or 0) for line in sale.lines}
            
            per_product_totals = {}
            total_amount = Decimal('0.00')
            sale_line_map = {}
            if sale_return.sale_id:
                sale = db.session.get(Sale, sale_return.sale_id)
                if sale:
                    for ln in (sale.lines or []):
                        try:
                            sale_line_map[(int(ln.product_id), int(ln.warehouse_id))] = ln
                        except Exception:
                            continue
            
            # حذف السطور القديمة
            for line in sale_return.lines:
                db.session.delete(line)
            
            # إضافة السطور الجديدة
            for line_data in form.lines.data:
                if line_data.get('product_id') and line_data.get('quantity'):
                    product_id = line_data['product_id']
                    new_qty = int(line_data['quantity'])
                    
                    if sale_return.sale_id and sale_dict:
                        original_qty = sale_dict.get(product_id, 0)
                        already_returned = returned_dict.get(product_id, 0)
                        cumulative_qty = per_product_totals.get(product_id, 0) + new_qty
                        if original_qty and (already_returned + cumulative_qty) > original_qty:
                            db.session.rollback()
                            product = db.session.get(Product, product_id)
                            product_name = product.name if product else f'المنتج #{product_id}'
                            available = max(0, original_qty - already_returned)
                            flash(
                                f'خطأ: {product_name} - الكمية المطلوبة ({cumulative_qty}) أكبر من المتاح للإرجاع ({available}). '
                                f'الكمية الأصلية: {original_qty}، المرتجع سابقاً: {already_returned}',
                                'danger'
                            )
                            return redirect(url_for('returns.edit_return', return_id=return_id))
                        per_product_totals[product_id] = cumulative_qty
                    wh_id = int(line_data.get('warehouse_id') or sale_return.warehouse_id or 0)
                    price = Decimal(str(line_data.get('unit_price', 0) or 0))
                    if sale_return.sale_id and sale_line_map and wh_id:
                        sl = sale_line_map.get((int(product_id), int(wh_id)))
                        if sl is not None:
                            base = Decimal(str(sl.unit_price or 0))
                            dr = Decimal(str(getattr(sl, "discount_rate", 0) or 0))
                            price = base * (Decimal("1") - (dr / Decimal("100")))
                    total_amount += Decimal(new_qty) * price
                    
                    line = SaleReturnLine(
                        sale_return_id=sale_return.id,
                        product_id=product_id,
                        warehouse_id=line_data.get('warehouse_id') or sale_return.warehouse_id,
                        quantity=new_qty,
                        unit_price=float(price),
                        notes=line_data.get('notes', '').strip() or None
                    )
                    db.session.add(line)
            
            sale_return.total_amount = total_amount.quantize(Decimal('0.01'))
            
            db.session.commit()
            try:
                run_sale_return_gl_sync_after_commit(sale_return.id)
            except Exception:
                current_app.logger.warning('GL sync failed for sale return #%s', sale_return.id, exc_info=True)
            # Audit log
            try:
                audit = AuditLog(
                    model_name='SaleReturn',
                    record_id=sale_return.id,
                    action='UPDATE',
                    user_id=current_user.id if current_user.is_authenticated else None
                )
                db.session.add(audit)
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.warning('Audit log failed for sale return UPDATE', exc_info=True)
            
            _refresh_related_balances(sale_return.customer_id, list(sale_return.lines or []))
            flash('تم تحديث المرتجع بنجاح', 'success')
            return redirect(url_for('returns.view_return', return_id=return_id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    # تحضير choices للـ template
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(500).all()
    product_choices = [(p.id, f"{p.name} ({p.barcode or 'بدون باركود'})") for p in products]
    
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.name).all()
    warehouse_choices = [(w.id, w.name) for w in warehouses]
    
    return render_template(
        'sale_returns/form.html',
        form=form,
        sale_return=sale_return,
        product_choices=product_choices,
        warehouse_choices=warehouse_choices,
        title='تعديل مرتجع'
    )


@returns_bp.route('/<int:return_id>/confirm', methods=['POST'])
@login_required
def confirm_return(return_id):
    """تأكيد المرتجع"""
    
    sale_return = db.get_or_404(SaleReturn, return_id)
    
    if sale_return.status == 'CONFIRMED':
        flash('المرتجع مؤكد مسبقاً', 'info')
        return redirect(url_for('returns.view_return', return_id=return_id))
    
    if sale_return.status == 'CANCELLED':
        flash('لا يمكن تأكيد مرتجع ملغي', 'warning')
        return redirect(url_for('returns.view_return', return_id=return_id))
    
    try:
        sale_return.status = 'CONFIRMED'
        db.session.commit()
        try:
            run_sale_return_gl_sync_after_commit(sale_return.id)
        except Exception:
            current_app.logger.warning('GL sync failed for sale return #%s', sale_return.id, exc_info=True)
        # Audit log
        try:
            audit = AuditLog(
                model_name='SaleReturn',
                record_id=sale_return.id,
                action='CONFIRM',
                user_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(audit)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.warning('Audit log failed for sale return CONFIRM', exc_info=True)
        
        _refresh_related_balances(sale_return.customer_id, list(sale_return.lines or []))
        flash('تم تأكيد المرتجع بنجاح. تم إرجاع المخزون.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
    
    return redirect(url_for('returns.view_return', return_id=return_id))


@returns_bp.route('/<int:return_id>/cancel', methods=['POST'])
@login_required
def cancel_return(return_id):
    """إلغاء المرتجع"""
    
    sale_return = db.get_or_404(SaleReturn, return_id)
    
    if sale_return.status == 'CANCELLED':
        flash('المرتجع ملغي مسبقاً', 'info')
        return redirect(url_for('returns.view_return', return_id=return_id))
    
    try:
        # إذا كان مؤكداً، نحتاج لعكس المخزون
        if sale_return.status == 'CONFIRMED':
            # حذف السطور سيعكس المخزون تلقائياً عبر events
            for line in sale_return.lines[:]:
                db.session.delete(line)
        
        sale_return.status = 'CANCELLED'
        db.session.commit()
        
        # Audit log
        try:
            audit = AuditLog(
                model_name='SaleReturn',
                record_id=sale_return.id,
                action='CANCEL',
                user_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(audit)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.warning('Audit log failed for sale return CANCEL', exc_info=True)
        
        _refresh_related_balances(sale_return.customer_id, list(sale_return.lines or []))
        flash('تم إلغاء المرتجع بنجاح', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
    
    return redirect(url_for('returns.view_return', return_id=return_id))


@returns_bp.route('/<int:return_id>/delete', methods=['POST'])
@login_required
def delete_return(return_id):
    """حذف المرتجع"""
    
    sale_return = db.get_or_404(SaleReturn, return_id)
    
    # فقط المسودات يمكن حذفها
    if sale_return.status != 'DRAFT':
        flash('لا يمكن حذف مرتجع مؤكد أو ملغي. استخدم الإلغاء بدلاً من ذلك.', 'warning')
        return redirect(url_for('returns.view_return', return_id=return_id))
    
    try:
        # Audit log قبل الحذف
        try:
            audit = AuditLog(
                model_name='SaleReturn',
                record_id=sale_return.id,
                action='DELETE',
                user_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(audit)
            db.session.flush()
        except Exception:
            current_app.logger.warning('Audit log failed for sale return DELETE', exc_info=True)
        
        db.session.delete(sale_return)
        db.session.commit()
        _refresh_related_balances(getattr(sale_return, "customer_id", None), list(getattr(sale_return, "lines", []) or []))
        
        flash('تم حذف المرتجع بنجاح', 'success')
        return redirect(url_for('returns.list_returns'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('returns.view_return', return_id=return_id))


# ============================================================================
# API Endpoints
# ============================================================================

@returns_bp.route('/api/sale/<int:sale_id>/items')
@login_required
def get_sale_items(sale_id):
    """الحصول على بنود البيع لتسهيل إنشاء المرتجع"""
    try:
        sale = db.get_or_404(Sale, sale_id)

        # احسب الكمية المتاحة للإرجاع = كمية البيع - مجموع المرتجعات المؤكدة
        confirmed_returns = (
            db.session.query(
                SaleReturnLine.product_id, 
                func.coalesce(func.sum(SaleReturnLine.quantity), 0).label('returned_qty')
            )
            .join(SaleReturn, SaleReturnLine.sale_return_id == SaleReturn.id)
            .filter(
                SaleReturn.sale_id == sale.id, 
                SaleReturn.status == 'CONFIRMED'
            )
            .group_by(SaleReturnLine.product_id)
            .all()
        )
        
        # تحويل لـ dict
        product_id_to_returned = {int(pid): int(qty or 0) for pid, qty in confirmed_returns}

        # بناء قائمة المنتجات
        items = []
        for line in (sale.lines or []):
            original_qty = int(line.quantity or 0)
            returned_qty = product_id_to_returned.get(line.product_id, 0)
            available_qty = max(0, original_qty - returned_qty)
            
            items.append({
                'product_id': line.product_id,
                'product_name': line.product.name if line.product else 'غير معروف',
                'quantity': original_qty,
                'unit_price': float(line.unit_price or 0),
                'warehouse_id': line.warehouse_id,
                'returned_quantity': returned_qty,
                'returnable_quantity': available_qty
            })

        # جلب المخزن من أول سطر (أو None)
        first_warehouse_id = items[0]['warehouse_id'] if items else None
        
        return jsonify({
            'success': True,
            'sale_id': sale.id,
            'customer_id': sale.customer_id,
            'warehouse_id': first_warehouse_id,
            'currency': sale.currency or 'ILS',
            'items': items
        })
        
    except Exception as e:
        
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500


@returns_bp.route('/api/customer/<int:customer_id>/sales')
@login_required
def get_customer_sales(customer_id: int):
    """إرجاع آخر المبيعات المؤكدة لعميل محدد لتصفية قائمة الفواتير في المرتجع"""
    try:
        sales = (
            Sale.query
            .filter_by(customer_id=customer_id, status='CONFIRMED')
            .order_by(Sale.id.desc())
            .limit(100)
            .all()
        )
        data = []
        for s in sales:
            # جلب المخزن من أول سطر بيع
            first_wh = None
            if s.lines and len(s.lines) > 0:
                first_wh = s.lines[0].warehouse_id
            
            data.append({
                'id': s.id,
                'date': (s.created_at.strftime('%Y-%m-%d') if getattr(s, 'created_at', None) else ''),
                'warehouse_id': first_wh,
                'currency': s.currency or 'ILS'
            })
        return jsonify({'success': True, 'sales': data})
    except Exception as e:
        
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
