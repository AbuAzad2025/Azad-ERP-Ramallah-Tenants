
from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_, desc, and_
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import json

from extensions import db
from models import Archive, ServiceRequest, Payment, Sale, Customer, Product, Expense, Check, Supplier, Partner
import utils
from utils import archive_record, restore_record, get_archive_stats, permission_required

archive_bp = Blueprint('archive', __name__, url_prefix='/archive')

def _parse_date(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except Exception:
        return None

@archive_bp.route('/')
@login_required
@permission_required(SystemPermissions.VIEW_AUDIT_LOGS)
def index():
    stats = get_archive_stats()
    recent_archives = Archive.query.order_by(desc(Archive.archived_at)).limit(10).all()
    
    return render_template('archive/index.html',
                         total_archives=stats['total_archives'],
                         type_stats=stats['type_stats'],
                         monthly_archives=stats['monthly_archives'],
                         recent_archives=recent_archives)

@archive_bp.route('/search', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.VIEW_AUDIT_LOGS)
def search():
    """البحث في الأرشيفات"""
    # form = ArchiveSearchForm()
    archives = []
    
    if request.method == 'POST':
        query = Archive.query
        
        # فلترة حسب نوع السجل
        record_type = request.form.get('record_type')
        if record_type:
            query = query.filter(Archive.record_type == record_type)
        
        # فلترة حسب التاريخ
        date_from = request.form.get('date_from')
        if date_from:
            dt_from = _parse_date(date_from)
            if dt_from:
                query = query.filter(Archive.archived_at >= dt_from)
        
        date_to = request.form.get('date_to')
        if date_to:
            dt_to = _parse_date(date_to)
            if dt_to:
                query = query.filter(Archive.archived_at <= dt_to + timedelta(days=1))
        
        # البحث في البيانات
        search_term = request.form.get('search_term')
        if search_term:
            search_term = f"%{search_term}%"
            query = query.filter(
                or_(
                    Archive.archived_data.ilike(search_term),
                    Archive.archive_reason.ilike(search_term)
                )
            )
        
        archives = query.order_by(desc(Archive.archived_at)).all()
    
    return render_template('archive/search.html', archives=archives)

@archive_bp.route('/bulk-archive', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.HARD_DELETE)
def bulk_archive():
    """الأرشفة الجماعية"""
    # form = BulkArchiveForm()
    
    if request.method == 'POST':
        try:
            # تحديد الجدول المناسب
            model_map = {
                'service_requests': ServiceRequest,
                'payments': Payment,
                'sales': Sale,
                'expenses': Expense,
                'checks': Check
            }
            
            record_type = request.form.get('record_type')
            model_class = model_map.get(record_type)
            if not model_class:
                flash('نوع السجل غير مدعوم', 'error')
                return redirect(url_for('archive.bulk_archive'))
            
            # البحث عن السجلات المؤهلة للأرشفة
            date_from = request.form.get('date_from')
            date_to = request.form.get('date_to')
            reason = request.form.get('reason')
            
            dt_from = _parse_date(date_from)
            dt_to = _parse_date(date_to)
            if not dt_from or not dt_to:
                flash('صيغة التاريخ غير صحيحة', 'error')
                return redirect(url_for('archive.bulk_archive'))

            query = model_class.query.filter(
                and_(
                    model_class.created_at >= dt_from,
                    model_class.created_at <= dt_to + timedelta(days=1)
                )
            )
            
            records = query.all()
            archived_count = 0
            
            for record in records:
                # أرشفة السجل
                archive = Archive.archive_record(
                    record=record,
                    reason=reason,
                    user_id=current_user.id
                )
                
                # حذف السجل الأصلي
                db.session.delete(record)
                archived_count += 1
            
            db.session.commit()
            
            flash(f'تم أرشفة {archived_count} سجل بنجاح', 'success')
            return redirect(url_for('archive.index'))
            
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'error')
    
    return render_template('archive/bulk_archive.html')

@archive_bp.route('/view/<int:archive_id>')
@login_required
@permission_required(SystemPermissions.VIEW_AUDIT_LOGS)
def view_archive(archive_id):
    """عرض تفاصيل الأرشيف"""
    archive = db.get_or_404(Archive, archive_id)
    
    # تحليل البيانات المؤرشفة
    try:
        archived_data = json.loads(archive.archived_data)
    except Exception:
        archived_data = {}
    
    return render_template('archive/view.html', archive=archive, archived_data=archived_data)

@archive_bp.route('/restore/<int:archive_id>', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.RESTORE_ARCHIVE)
def restore_archive(archive_id):
    """استعادة الأرشيف - يتطلب صلاحية restore_archive"""
    archive = db.get_or_404(Archive, archive_id)
    
    if request.method == 'POST':
        try:
            restored_record = utils.restore_record(archive_id)
            flash(f'تم استعادة السجل رقم {restored_record.id} بنجاح', 'success')
            return redirect(url_for('archive.index'))
            
        except Exception as e:
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'error')
    
    return render_template('archive/restore.html', archive=archive)

@archive_bp.route('/delete/<int:archive_id>', methods=['POST'])
@login_required
@permission_required(SystemPermissions.HARD_DELETE)
def delete_archive(archive_id):
    """حذف الأرشيف نهائياً - يتطلب صلاحية hard_delete"""
    archive = db.get_or_404(Archive, archive_id)
    
    try:
        db.session.delete(archive)
        db.session.commit()
        flash('تم حذف الأرشيف نهائياً', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
    
    return redirect(url_for('archive.index'))

@archive_bp.route('/export')
@login_required
@permission_required(SystemPermissions.VIEW_AUDIT_LOGS)
def export_archives():
    """تصدير الأرشيفات"""
    # يمكن تطوير هذا لاحقاً لتصدير الأرشيفات
    flash('ميزة التصدير قيد التطوير', 'info')
    return redirect(url_for('archive.index'))

# دوال مساعدة للأرشفة - تم نقلها إلى utils/archive_utils.py
