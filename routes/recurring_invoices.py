from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import RecurringInvoiceTemplate, RecurringInvoiceSchedule, Invoice, InvoiceLine, Customer, Branch, Site, TaxEntry, run_invoice_gl_sync_after_commit
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import or_
import utils

recurring_bp = Blueprint('recurring', __name__, url_prefix='/recurring')

def _dec_from_form(field_name: str, default: str = "0") -> Decimal:
    raw = (request.form.get(field_name, None) or "").strip()
    if raw == "":
        raw = default
    return Decimal(raw)


@recurring_bp.route('/')
@login_required
def index():
    # الحماية: فقط للمالك والمطور (Level 0)
    from permissions_config.role_policy import is_platform_owner_role

    if not is_platform_owner_role(current_user):
        utils.flash_error('غير مصرح لك بالوصول لهذه الصفحة (تتطلب صلاحيات المالك)', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '').strip()
    customer_filter = request.args.get('customer', type=int)
    
    query = RecurringInvoiceTemplate.query
    
    if status_filter:
        if status_filter == 'active':
            query = query.filter_by(is_active=True)
        elif status_filter == 'inactive':
            query = query.filter_by(is_active=False)
    
    if customer_filter:
        query = query.filter_by(customer_id=customer_filter)
    
    templates = query.order_by(RecurringInvoiceTemplate.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    total_active = RecurringInvoiceTemplate.query.filter_by(is_active=True).count()
    total_inactive = RecurringInvoiceTemplate.query.filter_by(is_active=False).count()
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    
    stats = {
        'total_active': total_active,
        'total_inactive': total_inactive,
        'total_templates': total_active + total_inactive
    }
    
    return render_template('recurring/index.html',
                         templates=templates,
                         stats=stats,
                         customers=customers,
                         filters={'status': status_filter, 'customer': customer_filter})


@recurring_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_template():
    if request.method == 'POST':
        try:
            template_name = request.form.get('template_name', '').strip()
            customer_id = request.form.get('customer_id', type=int) or 0
            description = request.form.get('description', '').strip()
            amount = _dec_from_form('amount', default="0")
            currency = request.form.get('currency', 'ILS').strip()
            tax_rate = _dec_from_form('tax_rate', default="0")
            frequency = request.form.get('frequency', '').strip()
            start_date_str = request.form.get('start_date', '').strip()
            end_date_str = request.form.get('end_date', '').strip()
            try:
                branch_id = int(request.form.get('branch_id'))
            except (ValueError, TypeError):
                branch_id = 0
            site_id = request.form.get('site_id', type=int)
            
            if not template_name:
                flash('اسم القالب مطلوب', 'danger')
                return redirect(url_for('recurring.add_template'))
            
            if not customer_id:
                flash('العميل مطلوب', 'danger')
                return redirect(url_for('recurring.add_template'))
            
            if amount <= 0:
                flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
                return redirect(url_for('recurring.add_template'))
            
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
            
            next_date = start_date
            
            new_template = RecurringInvoiceTemplate(
                template_name=template_name,
                customer_id=customer_id,
                description=description,
                amount=amount,
                currency=currency,
                tax_rate=tax_rate,
                frequency=frequency,
                start_date=start_date,
                end_date=end_date,
                next_invoice_date=next_date,
                branch_id=branch_id,
                site_id=site_id,
                is_active=True
            )
            
            db.session.add(new_template)
            db.session.commit()
            
            flash(f'تم إنشاء القالب "{template_name}" بنجاح', 'success')
            return redirect(url_for('recurring.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
            return redirect(url_for('recurring.add_template'))
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    branches = Branch.query.order_by(Branch.name).all()
    sites = Site.query.order_by(Site.name).all()
    
    return render_template('recurring/form.html',
                         customers=customers,
                         branches=branches,
                         sites=sites,
                         is_edit=False)


@recurring_bp.route('/edit/<int:template_id>', methods=['GET', 'POST'])
@login_required
def edit_template(template_id):
    template = db.session.get(RecurringInvoiceTemplate, template_id)
    if not template:
        flash('القالب غير موجود', 'danger')
        return redirect(url_for('recurring.index'))
    
    if request.method == 'POST':
        try:
            template.template_name = request.form.get('template_name', '').strip()
            template.customer_id = request.form.get('customer_id', type=int) or 0
            template.description = request.form.get('description', '').strip()
            template.amount = _dec_from_form('amount', default="0")
            template.currency = request.form.get('currency', 'ILS').strip()
            template.tax_rate = _dec_from_form('tax_rate', default="0")
            template.frequency = request.form.get('frequency', '').strip()
            
            start_date_str = request.form.get('start_date', '').strip()
            end_date_str = request.form.get('end_date', '').strip()
            
            try:
                template.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                template.start_date = None
            try:
                template.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
            except (ValueError, TypeError):
                template.end_date = None
            try:
                template.branch_id = int(request.form.get('branch_id'))
            except (ValueError, TypeError):
                template.branch_id = 0
            template.site_id = request.form.get('site_id', type=int)
            
            db.session.commit()
            flash(f'تم تحديث القالب بنجاح', 'success')
            return redirect(url_for('recurring.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    branches = Branch.query.order_by(Branch.name).all()
    sites = Site.query.order_by(Site.name).all()
    
    return render_template('recurring/form.html',
                         template=template,
                         customers=customers,
                         branches=branches,
                         sites=sites,
                         is_edit=True)


@recurring_bp.route('/toggle/<int:template_id>', methods=['POST'])
@login_required
def toggle_template(template_id):
    template = db.session.get(RecurringInvoiceTemplate, template_id)
    if not template:
        return jsonify({'success': False, 'error': 'القالب غير موجود'}), 404
    
    template.is_active = not template.is_active
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        return jsonify({'success': False, 'error': 'حدث خطأ أثناء الحفظ'}), 500
    
    status_text = 'مفعّل' if template.is_active else 'معطّل'
    return jsonify({'success': True, 'is_active': template.is_active, 'message': f'القالب الآن {status_text}'})


@recurring_bp.route('/delete/<int:template_id>', methods=['POST'])
@login_required
def delete_template(template_id):
    template = db.session.get(RecurringInvoiceTemplate, template_id)
    if not template:
        return jsonify({'success': False, 'error': 'القالب غير موجود'}), 404
    
    try:
        db.session.delete(template)
        db.session.commit()
        flash('تم حذف القالب بنجاح', 'success')
        return redirect(url_for('recurring.index'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 400


@recurring_bp.route('/schedules/<int:template_id>')
@login_required
def view_schedules(template_id):
    template = db.session.get(RecurringInvoiceTemplate, template_id)
    if not template:
        flash('القالب غير موجود', 'danger')
        return redirect(url_for('recurring.index'))
    
    schedules = RecurringInvoiceSchedule.query.filter_by(template_id=template_id).order_by(
        RecurringInvoiceSchedule.scheduled_date.desc()
    ).limit(100).all()
    
    pending_count = RecurringInvoiceSchedule.query.filter_by(template_id=template_id, status='PENDING').count()
    generated_count = RecurringInvoiceSchedule.query.filter_by(template_id=template_id, status='GENERATED').count()
    failed_count = RecurringInvoiceSchedule.query.filter_by(template_id=template_id, status='FAILED').count()
    
    stats = {
        'pending': pending_count,
        'generated': generated_count,
        'failed': failed_count
    }
    
    return render_template('recurring/schedule.html',
                         template=template,
                         schedules=schedules,
                         stats=stats)


def _calculate_next_invoice_date(template, current_date):
    if template.frequency == 'DAILY':
        return current_date + timedelta(days=1)
    elif template.frequency == 'WEEKLY':
        return current_date + timedelta(weeks=1)
    elif template.frequency == 'MONTHLY':
        next_month = current_date.month + 1
        next_year = current_date.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        return date(next_year, next_month, min(template.start_date.day, 28))
    elif template.frequency == 'QUARTERLY':
        return current_date + timedelta(days=90)
    elif template.frequency == 'YEARLY':
        return current_date.replace(year=current_date.year + 1)
    return current_date


def _generate_recurring_invoice(template, invoice_date=None):
    if invoice_date is None:
        invoice_date = date.today()
    
    invoice_datetime = datetime.combine(invoice_date, datetime.min.time())
    
    from time import time
    timestamp_suffix = int(time() * 1000) % 1000000
    invoice_number = f"REC-{invoice_datetime.strftime('%Y%m%d')}-{timestamp_suffix:06d}"
    
    base_amount = Decimal(str(template.amount))
    tax_rate = Decimal(str(template.tax_rate or 0))
    tax_amount = base_amount * (tax_rate / 100)
    total_amount = base_amount + tax_amount
    
    from models import InvoiceSource
    
    new_invoice = Invoice(
        invoice_number=invoice_number,
        invoice_date=invoice_datetime,
        due_date=invoice_datetime + timedelta(days=30),
        customer_id=template.customer_id,
        source=InvoiceSource.MANUAL.value,
        kind='INVOICE',
        currency=template.currency,
        tax_amount=0,
        total_amount=0,
        notes=f'فاتورة متكررة: {template.template_name}'
    )
    
    db.session.add(new_invoice)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('recurring invoice commit error')
        raise
    
    invoice_line = InvoiceLine(
        invoice_id=new_invoice.id,
        description=template.description or template.template_name,
        quantity=1,
        unit_price=float(base_amount),
        tax_rate=float(tax_rate),
        discount=0
    )
    
    db.session.add(invoice_line)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('recurring invoice line commit error')
        raise
    
    if tax_rate > 0:
        fiscal_year = invoice_date.year
        fiscal_month = invoice_date.month
        tax_period = f"{fiscal_year}-{fiscal_month:02d}"
        
        tax_entry = TaxEntry(
            entry_type='OUTPUT_VAT',
            transaction_type='INVOICE',
            transaction_id=new_invoice.id,
            transaction_reference=invoice_number,
            tax_rate=float(tax_rate),
            base_amount=float(base_amount),
            tax_amount=float(tax_amount),
            total_amount=float(total_amount),
            currency=template.currency,
            fiscal_year=fiscal_year,
            fiscal_month=fiscal_month,
            tax_period=tax_period,
            customer_id=template.customer_id,
            notes=f'فاتورة متكررة: {template.template_name}'
        )
        
        db.session.add(tax_entry)
    
    schedule = RecurringInvoiceSchedule(
        template_id=template.id,
        invoice_id=new_invoice.id,
        scheduled_date=invoice_date,
        generated_at=datetime.now(),
        status='GENERATED'
    )
    
    db.session.add(schedule)
    
    template.next_invoice_date = _calculate_next_invoice_date(template, invoice_date)
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('recurring invoice final commit error')
        raise
    try:
        run_invoice_gl_sync_after_commit(new_invoice.id)
    except Exception as e:
        # We log error but don't fail the generation
        from flask import current_app
        if current_app:
            current_app.logger.error(f"GL Sync Failed for Recurring Invoice #{new_invoice.id}: {e}")
        else:
            import logging
            logging.getLogger(__name__).error("GL Sync Failed for Recurring Invoice #%s: %s", new_invoice.id, e)

    return new_invoice


@recurring_bp.route('/generate-now/<int:template_id>', methods=['POST'])
@login_required
def generate_now(template_id):
    template = db.session.get(RecurringInvoiceTemplate, template_id)
    if not template:
        return jsonify({'success': False, 'error': 'القالب غير موجود'}), 404
    
    if not template.is_active:
        return jsonify({'success': False, 'error': 'القالب غير مفعّل'}), 400
    
    try:
        new_invoice = _generate_recurring_invoice(template)
        db.session.commit()
        try:
            run_invoice_gl_sync_after_commit(new_invoice.id)
        except Exception:
            current_app.logger.warning('DB commit failed silently')
        return jsonify({
            'success': True,
            'invoice_id': new_invoice.id,
            'invoice_number': new_invoice.invoice_number
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 400
