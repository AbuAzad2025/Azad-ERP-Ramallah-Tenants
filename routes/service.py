
import io
import json
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, Response, send_file, current_app
)
from flask_login import login_required, current_user, login_user
from sqlalchemy import func, or_, desc, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db, cache
from stock_audit_system import (
    StockTransactionType, StockAuditLogger,
    log_service_part_add, log_service_part_remove,
    log_service_complete, log_service_reopen
)
from models import (
    ServiceRequest, ServicePart, ServiceTask, Customer, Product,
    run_service_gl_sync_after_commit,
    build_service_reversal_snapshot,
    run_service_gl_reversal_after_delete,
    Warehouse, AuditLog, User, EquipmentType, StockLevel, Partner,
    Permission, Role, ServiceStatus, _service_consumes_stock, ServicePriority, WarehouseType,
    Payment, PaymentStatus, PaymentDirection, PaymentEntityType
)
from forms import (
    ServiceRequestForm, CustomerForm, ServiceTaskForm,
    ServicePartForm
)
import utils
from utils import _get_or_404, archive_record, restore_record
from permissions_config.enums import SystemPermissions

service_bp = Blueprint('service', __name__, url_prefix='/service')

# ثوابت النظام
STATUS_LABELS = {
    ServiceStatus.PENDING.value: "معلق",
    ServiceStatus.DIAGNOSIS.value: "تشخيص",
    ServiceStatus.IN_PROGRESS.value: "قيد التنفيذ",
    ServiceStatus.COMPLETED.value: "مكتمل",
    ServiceStatus.CANCELLED.value: "ملغي",
    ServiceStatus.ON_HOLD.value: "مؤجل",
    ServiceStatus.DELIVERED.value: "تم التسليم"
}

PRIORITY_LABELS = {
    ServicePriority.LOW.value: "منخفضة",
    ServicePriority.MEDIUM.value: "متوسطة",
    ServicePriority.HIGH.value: "عالية",
    ServicePriority.URGENT.value: "عاجلة"
}

PRIORITY_COLORS = {
    ServicePriority.LOW.value: "info",
    ServicePriority.MEDIUM.value: "warning",
    ServicePriority.HIGH.value: "danger",
    ServicePriority.URGENT.value: "dark"
}

def _log_service_stock_action(service, action: str, items: list[dict]) -> None:
    try:
        payload = {"items": items or []}
        # استخدام قيم افتراضية إذا لم يكن هناك request context
        try:
            ip = request.remote_addr
            ua = request.headers.get("User-Agent","")
        except RuntimeError:
            ip = None
            ua = None
        entry = AuditLog(created_at=datetime.now(timezone.utc).replace(tzinfo=None), model_name="ServiceRequest", record_id=service.id, customer_id=getattr(service,"customer_id",None), user_id=(current_user.id if getattr(current_user,"is_authenticated",False) else None), action=(action or "").strip().upper(), old_data=None, new_data=json.dumps(payload, ensure_ascii=False, default=str), ip_address=ip, user_agent=ua)
        db.session.add(entry)
        db.session.flush()
        current_app.logger.info(f"audit_log.created: {action} for service {service.id}")
    except Exception as e:
        current_app.logger.error(f"audit_log.failed: {e}")
        raise

def _ensure_partner_warehouse(warehouse_id: int) -> Warehouse:
    wid = int(warehouse_id or 0)
    if not wid:
        raise ValueError("❌ يجب تحديد المستودع")
    wh = db.session.get(Warehouse, wid)
    if not wh:
        raise ValueError("❌ المستودع غير موجود")
    if wh.warehouse_type == WarehouseType.PARTNER.value and not wh.partner_id:
        raise ValueError("❌ مستودع الشريك غير مربوط بشريك")
    return wh

def _update_service_totals(service):
    """تحديث parts_total, labor_total, و total_amount في ServiceRequest"""
    sid = None
    try:
        sid = int(getattr(service, "id", 0) or 0)
        if sid <= 0:
            return
        parts_sum = db.session.query(
            func.coalesce(
                func.sum(
                    func.coalesce(ServicePart.quantity, 0) * func.coalesce(ServicePart.unit_price, 0) -
                    func.coalesce(ServicePart.discount, 0)
                ),
                0
            )
        ).filter(ServicePart.service_id == sid).scalar() or 0
        tasks_sum = db.session.query(
            func.coalesce(
                func.sum(
                    func.coalesce(ServiceTask.quantity, 0) * func.coalesce(ServiceTask.unit_price, 0) -
                    func.coalesce(ServiceTask.discount, 0)
                ),
                0
            )
        ).filter(ServiceTask.service_id == sid).scalar() or 0

        parts_total = Decimal(str(parts_sum or 0))
        labor_total = Decimal(str(tasks_sum or 0))
        
        service.parts_total = parts_total
        service.labor_total = labor_total
        
        subtotal = parts_total + labor_total
        discount = Decimal(str(service.discount_total or 0))
        service.total_amount = subtotal - discount
        if service.total_amount < 0:
            service.total_amount = Decimal('0.00')
    except Exception as e:
        current_app.logger.warning(f"خطأ في تحديث totals للصيانة {sid or 'unknown'}: {e}")

def _refresh_service_related_balances(service) -> None:
    try:
        customer_id = getattr(service, "customer_id", None)
        if customer_id:
            from utils.customer_balance_updater import update_customer_balance_components
            update_customer_balance_components(int(customer_id))
    except Exception:
        current_app.logger.warning(f'Failed to update customer balance')
    try:
        partner_ids = set()
        for sp in (list(getattr(service, "parts", []) or []) + list(getattr(service, "tasks", []) or [])):
            pid = getattr(sp, "partner_id", None)
            if pid:
                partner_ids.add(int(pid))
        for pid in partner_ids:
            utils.update_entity_balance("PARTNER", int(pid))
    except Exception:
        current_app.logger.warning('balance calculation failed silently in service.py', exc_info=True)

def _flash_error(message: str) -> None:
    flash(f'❌ {message}', 'danger')

def _friendly_error(exc, fallback=None):
    if isinstance(exc, IntegrityError):
        return "لا يمكن حفظ السجل بسبب تعارض في البيانات."
    text=str(exc or "").strip()
    lower=text.lower()
    if "insufficient stock" in lower:
        return "المخزون غير كافٍ لبعض القطع."
    if "discount" in lower and ("exceed" in lower or "less than" in lower or "greater than" in lower or "must be between"):
        return "قيمة الخصم غير مقبولة بالنسبة للإجمالي."
    if "not a valid choice" in lower or "foreign key" in lower or "violates foreign key" in lower:
        return "القيم المختارة غير صالحة."
    if "unique constraint" in lower or "already exists" in lower or "duplicate" in lower:
        return "السجل موجود مسبقاً ولا يمكن تكراره."
    if "value too long" in lower or "data too long" in lower:
        return "النص المدخل أطول من الحد المسموح."
    if "null value" in lower or "not null" in lower:
        return "يجب تعبئة جميع الحقول الإلزامية."
    if "could not convert" in lower or "invalid literal" in lower or "decimal" in lower or "invalid input syntax" in lower:
        return "القيم المدخلة غير صالحة."
    if "permission" in lower:
        return "غير مصرح لك بتنفيذ هذه العملية."
    return fallback or "حدث خطأ غير متوقع."

def _log_and_flash(log_key: str, exc: Exception, message: str) -> None:
    current_app.logger.error(log_key, exc_info=exc)
    _flash_error(message)

def _service_stock_targets(service):
    totals={}
    for p in list(service.parts or []):
        key=(int(p.part_id),int(p.warehouse_id))
        qty=-int(p.quantity or 0)
        totals[key]=totals.get(key,0)+qty
    return totals

def _service_stock_movements(service):
    # Support both legacy STOCK_* actions and current SERVICE_* actions.
    actions=(
        "STOCK_CONSUME","STOCK_RELEASE","STOCK_CONSUME_PART","STOCK_RELEASE_PART",
        "SERVICE_CONSUME","SERVICE_RELEASE","SERVICE_ADD_PART","SERVICE_REMOVE_PART",
    )
    rows=db.session.query(AuditLog).filter(AuditLog.model_name=="ServiceRequest",AuditLog.record_id==service.id,AuditLog.action.in_(actions)).all()
    totals={}
    consume_actions = {"STOCK_CONSUME", "STOCK_CONSUME_PART", "SERVICE_CONSUME", "SERVICE_ADD_PART"}
    release_actions = {"STOCK_RELEASE", "STOCK_RELEASE_PART", "SERVICE_RELEASE", "SERVICE_REMOVE_PART"}
    for row in rows:
        payload=None
        try:
            payload=json.loads(row.new_data or "{}")
        except Exception:
            payload=None
        if not isinstance(payload,dict): continue
        items=payload.get("items") if isinstance(payload.get("items"),list) else []
        for item in items:
            try:
                part_id=int(item.get("part_id"))
                warehouse_id=int(item.get("warehouse_id"))
                qty=int(item.get("qty") or 0)
            except Exception:
                continue
            # Normalize sign by action to protect against historical bad log payloads.
            action = str(getattr(row, "action", "") or "").upper()
            if action in consume_actions:
                qty = -abs(qty)
            elif action in release_actions:
                qty = abs(qty)
            key=(part_id,warehouse_id)
            totals[key]=totals.get(key,0)+qty
    return totals

def _consume_service_stock_once(service) -> bool:
    """استهلاك المخزون مرة واحدة فقط - تحقق من عدم التكرار"""
    if not _service_consumes_stock(service): return False
    
    # التحقق مما إذا كان قد تم استهلاك المخزون بالفعل
    # استخدام with_for_update لتجنب race conditions
    existing_consume = db.session.query(AuditLog).filter(
        AuditLog.model_name == "ServiceRequest",
        AuditLog.record_id == service.id,
        AuditLog.action.in_(["STOCK_CONSUME", "SERVICE_CONSUME"])
    ).first()
    
    if existing_consume:
        # تم استهلاك المخزون بالفعل
        current_app.logger.info(f"service.stock_consume.skipped service_id={service.id} - already consumed")
        return False
    
    targets=_service_stock_targets(service)
    currents=_service_stock_movements(service)
    for key in list(currents.keys()):
        if key not in targets: targets[key]=0
    items=[]
    for key,target in targets.items():
        current=currents.get(key,0)
        delta=target-current
        if delta:
            _ensure_partner_warehouse(key[1])
            new_qty=utils._apply_stock_delta(key[0],key[1],delta)
            items.append({"part_id":key[0],"warehouse_id":key[1],"qty":delta,"stock_after":int(new_qty)})
    if not items:
        return False
    # استخدام النظام المحسّن للتوثيق
    log_service_complete(
        service=service,
        items=items,
        reason="إكمال الصيانة - خصم المخزون النهائي"
    )
    db.session.flush()  # ✅ تأكد من كتابة AuditLog قبل أي استدعاء لاحق
    current_app.logger.info("service.stock_consume",extra={"event":"service.stock.consume","service_id":service.id,"items":[{"part_id":i["part_id"],"warehouse_id":i["warehouse_id"],"qty":i["qty"]} for i in items]})
    return True

def _release_service_stock_once(service) -> bool:
    """إرجاع المخزون مرة واحدة فقط - تحقق من عدم التكرار"""
    if not _service_consumes_stock(service): return False
    
    # التحقق من آخر عملية مخزون - يجب أن تكون استهلاك (CONSUME) لإرجاع المخزون
    last_log = db.session.query(AuditLog).filter(
        AuditLog.model_name == "ServiceRequest",
        AuditLog.record_id == service.id,
        AuditLog.action.in_([
            "STOCK_CONSUME", "STOCK_CONSUME_PART", "STOCK_RELEASE",
            "SERVICE_CONSUME", "SERVICE_ADD_PART", "SERVICE_RELEASE",
        ])
    ).order_by(AuditLog.id.desc()).first()
    
    # نُرجع المخزون فقط إذا كانت آخر عملية هي استهلاك (وليست إعادة)
    if not last_log or last_log.action not in [
        "STOCK_CONSUME", "STOCK_CONSUME_PART",
        "SERVICE_CONSUME", "SERVICE_ADD_PART",
    ]:
        current_app.logger.info(f"service.stock_release.skipped service_id={service.id} - last_action={last_log.action if last_log else 'none'}")
        return False
    
    currents=_service_stock_movements(service)
    if not currents: return False
    items=[]
    for key,current in currents.items():
        if not current: continue
        delta=-current
        _ensure_partner_warehouse(key[1])
        new_qty=utils._apply_stock_delta(key[0],key[1],delta)
        items.append({"part_id":key[0],"warehouse_id":key[1],"qty":delta,"stock_after":int(new_qty)})
    if not items: return False
    # استخدام النظام المحسّن للتوثيق
    log_service_reopen(
        service=service,
        items=items,
        reason="إعادة فتح الصيانة - إرجاع المخزون"
    )
    db.session.flush()  # ✅ تأكد من كتابة AuditLog قبل أي استدعاء لاحق
    current_app.logger.info("service.stock_release",extra={"event":"service.stock.release","service_id":service.id,"items":[{"part_id":i["part_id"],"warehouse_id":i["warehouse_id"],"qty":i["qty"]} for i in items]})
    return True

@service_bp.context_processor
def inject_service_constants():
    return {"STATUS_LABELS":STATUS_LABELS,"PRIORITY_COLORS":PRIORITY_COLORS}

def _enum_results_with_counts(enum_cls, labels_map, column):
    rows=db.session.query(column, func.count(ServiceRequest.id)).group_by(column).all()
    counts={}
    for k,c in rows:
        key=getattr(k,"value",k); counts[str(key)]=int(c or 0)
    out=[]
    for m in enum_cls: out.append({"id":m.value,"text":labels_map.get(m.value,m.value),"count":counts.get(m.value,0)})
    return out

@service_bp.get("/api/statuses")
@login_required
def api_service_statuses():
    return jsonify({"results":_enum_results_with_counts(ServiceStatus, STATUS_LABELS, ServiceRequest.status)})

@service_bp.get("/api/priorities")
@login_required
def api_service_priorities():
    return jsonify({"results":_enum_results_with_counts(ServicePriority, PRIORITY_LABELS, ServiceRequest.priority)})

@service_bp.get("/api/options")
@login_required
def api_service_options():
    return jsonify({"statuses":_enum_results_with_counts(ServiceStatus, STATUS_LABELS, ServiceRequest.status),"priorities":_enum_results_with_counts(ServicePriority, PRIORITY_LABELS, ServiceRequest.priority)})

def _status_list(values):
    out=[]
    for v in values:
        key=(v or "").strip().upper()
        if hasattr(ServiceStatus,key): out.append(getattr(ServiceStatus,key))
    return out

def _priority_list(values):
    out=[]
    for v in values:
        key=(v or "").strip().upper()
        if hasattr(ServicePriority,key): out.append(getattr(ServicePriority,key))
    return out

def _col(name:str):
    mapping={"request_date":"received_at","start_time":"started_at","end_time":"completed_at","received_at":"received_at","started_at":"started_at","completed_at":"completed_at","priority":"priority","status":"status"}
    attr=mapping.get(name,"received_at")
    return getattr(ServiceRequest,attr)

def _fmt_dt(dt):
    try: return dt.strftime('%Y-%m-%d %H:%M') if dt else ''
    except Exception: return str(dt or '')

def _row_dict(sr:ServiceRequest)->dict:
    cust=getattr(sr,"customer",None); mech=getattr(sr,"mechanic",None)
    return {"ID":getattr(sr,"id",""),"رقم الطلب":getattr(sr,"service_number","") or getattr(sr,"code",""),"العميل":getattr(cust,"name","") if cust else "","هاتف":getattr(cust,"phone","") if cust else "","الحالة":getattr(getattr(sr,"status",""),"value",getattr(sr,"status","")) or "","الأولوية":getattr(getattr(sr,"priority",""),"value",getattr(sr,"priority","")) or "","لوحة المركبة":getattr(sr,"vehicle_vrn","") or "","الميكانيكي":getattr(mech,"username","") if mech else "","تاريخ الاستلام":_fmt_dt(getattr(sr,"received_at",None)),"تاريخ البدء":_fmt_dt(getattr(sr,"started_at",None)),"تاريخ الإكمال":_fmt_dt(getattr(sr,"completed_at",None)),"التكلفة التقديرية":float(getattr(sr,"estimated_cost",0) or 0),"المبلغ المستحق":float(getattr(sr,"balance_due",None) or getattr(sr,"total_cost",0) or 0),"الوصف":(getattr(sr,"description","") or "")[:120]}

def _build_list_query():
    status_filter=request.args.getlist('status'); priority_filter=request.args.getlist('priority'); customer_filter=request.args.get('customer',''); mechanic_filter=request.args.get('mechanic',''); vrn_filter=request.args.get('vrn',''); date_filter=request.args.get('date','')
    query=ServiceRequest.query.options(joinedload(ServiceRequest.customer))
    sts=_status_list(status_filter)
    if sts: query=query.filter(ServiceRequest.status.in_(sts))
    pris=_priority_list(priority_filter)
    if pris: query=query.filter(ServiceRequest.priority.in_(pris))
    if customer_filter: query=query.join(Customer).filter(or_(Customer.name.ilike(f'%{customer_filter}%'),Customer.phone.ilike(f'%{customer_filter}%')))
    if mechanic_filter: query=query.join(User, ServiceRequest.mechanic_id==User.id).filter(User.username.ilike(f'%{mechanic_filter}%'))
    if vrn_filter: query=query.filter(ServiceRequest.vehicle_vrn.ilike(f'%{vrn_filter}%'))
    if date_filter:
        today=datetime.today(); col=_col('received_at')
        if date_filter=='today': query=query.filter(func.date(col)==today.date())
        elif date_filter=='week':
            start_week=today-timedelta(days=today.weekday()); query=query.filter(col>=start_week)
        elif date_filter=='month':
            start_month=today.replace(day=1); query=query.filter(col>=start_month)
    sort_by=request.args.get('sort','request_date'); sort_order=request.args.get('order','desc'); field=_col(sort_by)
    query=query.order_by(field.asc() if sort_order=='asc' else field.desc())
    return query

@service_bp.route('/', methods=['GET'])
@service_bp.route('/list', methods=['GET'])
@login_required
def list_requests():
    """قائمة طلبات الصيانة مع فلترة وPagination محسّنة"""
    
    # الفلاتر
    status_filter = request.args.getlist('status')
    priority_filter = request.args.getlist('priority')
    customer_filter = request.args.get('customer', '')
    mechanic_filter = request.args.get('mechanic', '')
    vrn_filter = request.args.get('vrn', '')
    date_filter = request.args.get('date', '')
    
    # Pagination - 5 طلبات في كل صفحة للعرض المريح
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    per_page = min(max(1, per_page), 20)  # الحد الأقصى 20 طلب للصفحة الواحدة
    
    # بناء الاستعلام مع joinedload محسّن - فلترة السجلات غير المؤرشفة
    query = ServiceRequest.query.filter(ServiceRequest.is_archived == False).options(
        joinedload(ServiceRequest.customer),
        joinedload(ServiceRequest.mechanic),
        joinedload(ServiceRequest.vehicle_type)
    )
    
    # تطبيق الفلاتر
    sts = _status_list(status_filter)
    if sts:
        query = query.filter(ServiceRequest.status.in_(sts))
    
    pris = _priority_list(priority_filter)
    if pris:
        query = query.filter(ServiceRequest.priority.in_(pris))
    
    if customer_filter:
        query = query.join(Customer).filter(
            or_(
                Customer.name.ilike(f'%{customer_filter}%'),
                Customer.phone.ilike(f'%{customer_filter}%')
            )
        )
    
    if mechanic_filter:
        query = query.join(User, ServiceRequest.mechanic_id == User.id).filter(
            User.username.ilike(f'%{mechanic_filter}%')
        )
    
    if vrn_filter:
        query = query.filter(ServiceRequest.vehicle_vrn.ilike(f'%{vrn_filter}%'))
    
    if date_filter:
        today = datetime.today()
        col = _col('received_at')
        if date_filter == 'today':
            query = query.filter(func.date(col) == today.date())
        elif date_filter == 'week':
            start_week = today - timedelta(days=today.weekday())
            query = query.filter(col >= start_week)
        elif date_filter == 'month':
            start_month = today.replace(day=1)
            query = query.filter(col >= start_month)
    
    # فلترة حسب نطاق تاريخ محدد
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    if date_from or date_to:
        col = _col('received_at')
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(col >= from_date)
            except ValueError:
                current_app.logger.debug('date parsing failed in service.py', exc_info=True)
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(col <= to_date)
            except ValueError:
                current_app.logger.debug('date parsing failed in service.py', exc_info=True)
    
    # الترتيب
    sort_by = request.args.get('sort', 'balance_due')
    sort_order = request.args.get('order', 'desc')
    
    if sort_by == 'balance_due':
        from sqlalchemy import select
        total_paid_subq = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.service_id == ServiceRequest.id)
                & (Payment.entity_type == PaymentEntityType.SERVICE.value)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.IN.value)
            )
            .correlate(ServiceRequest)
            .scalar_subquery()
        )
        balance_due_expr = func.coalesce(ServiceRequest.total_amount, 0) - func.coalesce(total_paid_subq, 0)
        if sort_order == 'asc':
            query = query.order_by(balance_due_expr.asc().nullslast())
        else:
            query = query.order_by(balance_due_expr.desc().nullslast())
    else:
        field = _col(sort_by)
        query = query.order_by(field.asc() if sort_order == 'asc' else field.desc())
    
    # Pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # الإحصائيات (مع Cache)
    cache_key = 'service_stats'
    stats = cache.get(cache_key)
    if stats is None:
        stats = {
            'pending': ServiceRequest.query.filter_by(status=ServiceStatus.PENDING).count(),
            'in_progress': ServiceRequest.query.filter_by(status=ServiceStatus.IN_PROGRESS).count(),
            'completed': ServiceRequest.query.filter_by(status=ServiceStatus.COMPLETED).count(),
            'high_priority': ServiceRequest.query.filter_by(priority=ServicePriority.HIGH).count()
        }
        cache.set(cache_key, stats, timeout=300)  # 5 دقائق
    
    # الميكانيكيين النشطين
    mechanics = User.query.filter_by(is_active=True).order_by(User.username).all()
    
    filter_values = {
        'status': status_filter,
        'priority': priority_filter,
        'customer': customer_filter,
        'mechanic': mechanic_filter,
        'vrn': vrn_filter,
        'date': date_filter,
        'date_from': date_from,
        'date_to': date_to,
        'sort': sort_by,
        'order': sort_order
    }
    
    return render_template(
        'service/list.html',
        requests=pagination.items,
        pagination=pagination,
        status_labels=STATUS_LABELS,
        priority_labels=PRIORITY_LABELS,
        priority_colors=PRIORITY_COLORS,
        stats=stats,
        mechanics=mechanics,
        filter_values=filter_values
    )

@service_bp.route('/archive/<int:id>', methods=['POST'])
@login_required
def archive_service(id):
    service = db.get_or_404(ServiceRequest, id)
    reason = request.form.get("reason")
    
    try:
        archive_record(service, ServiceRequest, reason=reason)
        return jsonify({"status": "success", "message": "تم أرشفة طلب الصيانة بنجاح"})
    except Exception as e:
        db.session.rollback()
        try:
            service.is_archived = True
            db.session.commit()
            return jsonify({"status": "success", "message": "تم أرشفة طلب الصيانة بنجاح (يدوي)"})
        except Exception:
            db.session.rollback()
            current_app.logger.exception("service.archive_service failed", extra={"service_id": id})
            return jsonify({"status": "error", "message": "تعذر أرشفة طلب الصيانة حالياً"}), 500

@service_bp.route('/restore/<int:id>', methods=['POST'])
@login_required
def restore_service(id):
    try:
        restore_record(id, ServiceRequest)
        return jsonify({"status": "success", "message": "تم استعادة طلب الصيانة بنجاح"})
    except Exception:
        db.session.rollback()
        service = db.session.get(ServiceRequest, id)
        if service:
            try:
                service.is_archived = False
                db.session.commit()
                return jsonify({"status": "success", "message": "تم استعادة طلب الصيانة بنجاح (يدوي)"})
            except Exception:
                db.session.rollback()
                current_app.logger.exception('fallback restore_service commit failed')
                return jsonify({"status": "error", "message": "تعذر استعادة طلب الصيانة حالياً"}), 500
        current_app.logger.exception("service.restore_service failed")
        return jsonify({"status": "error", "message": "تعذر استعادة طلب الصيانة حالياً"}), 500

@service_bp.route('/export/csv', methods=['GET'])
@login_required
def export_requests_csv():
    services=_build_list_query().all()
    rows=[_row_dict(sr) for sr in services]
    sio=io.StringIO(newline="")
    fieldnames=list(rows[0].keys()) if rows else ["ID","رقم الطلب","العميل","هاتف","الحالة","الأولوية","لوحة المركبة","الميكانيكي","تاريخ الاستلام","تاريخ البدء","تاريخ الإكمال","التكلفة التقديرية","المبلغ المستحق","الوصف"]
    writer=csv.DictWriter(sio, fieldnames=fieldnames); writer.writeheader()
    for r in rows: writer.writerow(r)
    data=sio.getvalue().encode('utf-8-sig'); bio=io.BytesIO(data); bio.seek(0)
    filename=f"service_export_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return send_file(bio, as_attachment=True, download_name=filename, mimetype="text/csv; charset=utf-8")

@service_bp.route('/dashboard')
@login_required
@utils.permission_required(SystemPermissions.VIEW_SERVICE)
def dashboard():
    total_requests=ServiceRequest.query.count()
    completed_this_month=ServiceRequest.query.filter(ServiceRequest.status==ServiceStatus.COMPLETED, _col('completed_at')>=datetime.now().replace(day=1,hour=0,minute=0,second=0,microsecond=0)).count()
    high_priority=ServiceRequest.query.filter_by(priority=ServicePriority.HIGH).order_by(_col('received_at').desc()).limit(5).all()
    in_prog=ServiceRequest.query.filter(ServiceRequest.status.in_([ServiceStatus.DIAGNOSIS,ServiceStatus.IN_PROGRESS])).all()
    now=datetime.now(); overdue=[]
    for s in in_prog:
        start_dt=getattr(s,"started_at",None); est_min=getattr(s,"estimated_duration",None)
        if start_dt and est_min:
            eta=start_dt+timedelta(minutes=int(est_min))
            if eta<now: overdue.append(s)
    status_distribution=db.session.query(ServiceRequest.status, func.count(ServiceRequest.id)).group_by(ServiceRequest.status).all()
    priority_distribution=db.session.query(ServiceRequest.priority, func.count(ServiceRequest.id)).group_by(ServiceRequest.priority).all()
    active_mechanics=db.session.query(User.username, func.count(ServiceRequest.id).label('request_count')).join(ServiceRequest, ServiceRequest.mechanic_id==User.id).group_by(User.id).order_by(desc('request_count')).limit(5).all()
    return render_template('service/dashboard.html', total_requests=total_requests, completed_this_month=completed_this_month, high_priority=high_priority, active_mechanics=active_mechanics, overdue=overdue, status_distribution=status_distribution, priority_distribution=priority_distribution)

@service_bp.route('/new', methods=['GET','POST'])
@login_required
def create_request():
    form=ServiceRequestForm()
    try: form.vehicle_type_id.endpoint='api.search_equipment_types'
    except Exception: pass
    if form.validate_on_submit():
        if not form.customer_id.data:
            flash("⚠️ يجب اختيار عميل قبل إنشاء طلب صيانة.","warning")
            return redirect(url_for("customers_bp.create_form", return_to=url_for("service.create_request")))
        customer=db.session.get(Customer,utils._get_id(form.customer_id.data))
        if not customer:
            flash("⚠️ العميل غير موجود. الرجاء إضافته.","danger")
            return redirect(url_for("customers_bp.create_form", return_to=url_for("service.create_request")))
        # Sanitize priority/status to avoid invalid enum values (e.g., 'NEW')
        _prio_code = (form.priority.data or 'MEDIUM').upper()
        priority_val = getattr(ServicePriority, _prio_code, ServicePriority.MEDIUM)
        _stat_code = (form.status.data or 'PENDING').upper()
        status_val = getattr(ServiceStatus, _stat_code, ServiceStatus.PENDING)

        service=ServiceRequest(service_number=f"SRV-{datetime.now(timezone.utc):%Y%m%d%H%M%S}", customer_id=customer.id, vehicle_vrn=form.vehicle_vrn.data, vehicle_type_id=utils._get_id(form.vehicle_type_id.data) if form.vehicle_type_id.data else None, vehicle_model=form.vehicle_model.data, chassis_number=form.chassis_number.data, problem_description=form.problem_description.data, priority=priority_val, estimated_duration=form.estimated_duration.data, status=status_val, received_at=datetime.now(timezone.utc).replace(tzinfo=None), consume_stock=bool(form.consume_stock.data))
        db.session.add(service)
        try:
            db.session.commit()
            try:
                run_service_gl_sync_after_commit(service.id)
            except Exception:
                current_app.logger.warning('DB add failed silently')
            log_service_action(service,"CREATE")
            _refresh_service_related_balances(service)
            if customer.phone: utils.send_whatsapp_message(customer.phone, f"تم استلام طلب الصيانة رقم {service.service_number}.")
            flash("✅ تم إنشاء طلب الصيانة بنجاح","success")
            return redirect(url_for('service.view_request', rid=service.id))
        except SQLAlchemyError as exc:
            db.session.rollback()
            _log_and_flash("service.create_request", exc, "تعذر إنشاء طلب الصيانة حالياً.")
    return render_template('service/new.html', form=form)

@service_bp.route('/<int:rid>', methods=['GET'])
@login_required
@utils.permission_required(SystemPermissions.VIEW_SERVICE)
def view_request(rid):
    current_app.logger.info(f"🔍 view_request called with rid={rid}")
    try:
        service=_get_or_404(ServiceRequest, rid, load_options=[joinedload(ServiceRequest.customer), joinedload(ServiceRequest.parts).joinedload(ServicePart.part), joinedload(ServiceRequest.parts).joinedload(ServicePart.warehouse), joinedload(ServiceRequest.tasks)])
        current_app.logger.info(f"✅ Service found: {service.id}, {service.service_number}")
    except Exception as e:
        current_app.logger.error(f"❌ Error getting service {rid}: {e}")
        abort(404)
    warehouses=Warehouse.query.order_by(Warehouse.name.asc()).all()
    
    try:
        _update_service_totals(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
    except Exception:
        db.session.rollback()
    
    try:
        due_amount = float(getattr(service, 'balance_due', 0) or 0)
        if due_amount <= 0:
            total_amt = float(getattr(service, 'total', 0) or 0)
            total_paid = float(getattr(service, 'total_paid', 0) or 0)
            due_amount = max(total_amt - total_paid, 0)
    except Exception:
        due_amount = 0.0
    
    return render_template('service/view.html', service=service, warehouses=warehouses, due_amount=due_amount)

@service_bp.route('/<int:rid>/receipt', methods=['GET'])
@login_required
def view_receipt(rid):
    service=_get_or_404(ServiceRequest, rid, load_options=[joinedload(ServiceRequest.customer), joinedload(ServiceRequest.parts).joinedload(ServicePart.part), joinedload(ServiceRequest.parts).joinedload(ServicePart.warehouse), joinedload(ServiceRequest.tasks)])
    variant = 'simple' if (request.args.get('simple') or '').strip().lower() in ('1','true','yes') else 'pro'
    template_name = 'service/receipt_simple.html' if variant == 'simple' else 'service/receipt.html'
    return render_template(template_name, service=service, variant=variant)

@service_bp.route('/<int:rid>/receipt/download', methods=['GET'])
@login_required
def download_receipt(rid):
    service=_get_or_404(ServiceRequest, rid, load_options=[joinedload(ServiceRequest.customer), joinedload(ServiceRequest.parts).joinedload(ServicePart.part), joinedload(ServiceRequest.parts).joinedload(ServicePart.warehouse), joinedload(ServiceRequest.tasks)])
    pdf_data=generate_service_receipt_pdf(service)
    return send_file(io.BytesIO(pdf_data), as_attachment=True, download_name=f"service_receipt_{service.service_number}.pdf", mimetype='application/pdf')

@service_bp.route('/<int:rid>/diagnosis', methods=['POST'])
@login_required
def update_diagnosis(rid):
    service=_get_or_404(ServiceRequest, rid)
    old={'problem_description':service.problem_description,'diagnosis':service.diagnosis,'resolution':service.resolution,'estimated_duration':service.estimated_duration,'estimated_cost':str(service.estimated_cost or 0),'status':getattr(service.status,"value",service.status)}
    diagnosis=request.form.get('diagnosis','').strip(); problem_description=request.form.get('problem_description',service.problem_description); resolution=request.form.get('resolution',service.resolution); estimated_duration=request.form.get('estimated_duration',service.estimated_duration); estimated_cost=request.form.get('estimated_cost',service.estimated_cost)
    service.problem_description=problem_description; service.diagnosis=diagnosis; service.engineer_notes=diagnosis; service.resolution=resolution; service.estimated_duration=estimated_duration; service.estimated_cost=estimated_cost; service.status=ServiceStatus.IN_PROGRESS.value
    try:
        _consume_service_stock_once(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        log_service_action(service,"DIAGNOSIS", old_data=old, new_data={'problem_description':service.problem_description,'diagnosis':service.diagnosis,'resolution':service.resolution,'estimated_duration':service.estimated_duration,'estimated_cost':str(service.estimated_cost or 0),'status':getattr(service.status,"value",service.status)})
        _refresh_service_related_balances(service)
        if service.customer and service.customer.phone: utils.send_whatsapp_message(service.customer.phone, f"تم تحديث ملاحظات المهندس للمركبة {service.vehicle_vrn}.")
        flash('✅ تم تحديث الملاحظات بنجاح','success')
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.update_diagnosis", e, "تعذر حفظ التعديلات، يرجى المحاولة لاحقاً.")
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/<int:rid>/discount_tax', methods=['POST'])
@login_required
def update_discount_tax(rid):
    """تحديث الخصم الإجمالي والضريبة"""
    service = _get_or_404(ServiceRequest, rid)
    
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    try:
        discount_total = Decimal(request.form.get('discount_total', 0) or 0)
        tax_rate = Decimal(request.form.get('tax_rate', 0) or 0)
        # حساب إجمالي الفاتورة للتحقق
        parts_sum = sum((p.line_total or 0) for p in service.parts)
        tasks_sum = sum((t.line_total or 0) for t in service.tasks)
        invoice_total = parts_sum + tasks_sum
        
        # التحقق من صحة البيانات
        if discount_total < 0:
            _flash_error('الخصم لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        if discount_total > invoice_total:
            _flash_error(f'الخصم ({discount_total:.2f} ₪) لا يمكن أن يتجاوز إجمالي الفاتورة ({invoice_total:.2f} ₪)')
            return redirect(url_for('service.view_request', rid=rid))
        
        if tax_rate < 0 or tax_rate > 100:
            _flash_error('نسبة الضريبة يجب أن تكون بين 0 و 100')
            return redirect(url_for('service.view_request', rid=rid))
        
        # حفظ القيم القديمة للـ audit log
        old_data = {
            'discount_total': str(service.discount_total or 0),
            'tax_rate': str(service.tax_rate or 0)
        }
        
        # تحديث القيم
        service.discount_total = discount_total
        service.tax_rate = tax_rate
        
        _update_service_totals(service)
        
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        # تسجيل في الـ audit log
        log_service_action(service, "UPDATE_DISCOUNT_TAX", 
                          old_data=old_data, 
                          new_data={
                              'discount_total': str(discount_total),
                              'tax_rate': str(tax_rate)
                          })
        _refresh_service_related_balances(service)
        
        flash('✅ تم تحديث الخصم والضريبة بنجاح', 'success')
        
    except ValueError as e:
        _flash_error(_friendly_error(e, "القيم المدخلة غير صالحة."))
        db.session.rollback()
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.update_discount_tax", e, "تعذر حفظ التعديلات، يرجى المحاولة لاحقاً.")
    
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/<int:rid>/<action>', methods=['POST'])
@login_required
def toggle_service(rid, action):
    service=_get_or_404(ServiceRequest, rid)
    try:
        current_status = getattr(service.status, 'value', service.status)
        if action=='start':
            if not getattr(service,"started_at",None): service.started_at=datetime.now(timezone.utc).replace(tzinfo=None)
            service.status=ServiceStatus.IN_PROGRESS.value
        elif action=='complete':
            service.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
            if service.started_at:
                sa = utils.naive_utc_for_delta(service.started_at)
                ca = utils.naive_utc_for_delta(service.completed_at)
                if sa and ca:
                    delta_sec = (ca - sa).total_seconds()
                    service.actual_duration = int(max(0, delta_sec) / 60)
            service.status=ServiceStatus.COMPLETED.value
            # Idempotent vs per-line STOCK_CONSUME_PART in AuditLog (avoids double deduction)
            _consume_service_stock_once(service)
        elif action=='reopen':
            if current_status==ServiceStatus.COMPLETED.value:
                _release_service_stock_once(service)
                service.status=ServiceStatus.IN_PROGRESS.value
                service.completed_at=None
        else: abort(400)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        _refresh_service_related_balances(service)
        
        if action=='complete':
            if service.customer and service.customer.phone:
                utils.send_whatsapp_message(service.customer.phone, f"تم إكمال صيانة المركبة {service.vehicle_vrn}.")
            try:
                from utils import notify_service_completed
                notify_service_completed(service.id)
            except Exception as e:
                current_app.logger.warning(f'⚠️ Notification failed: {e}')
        
        flash('✅ تم تحديث حالة الصيانة','success')
    except ValueError as ve:
        db.session.rollback()
        _flash_error(_friendly_error(ve, "لا يمكن تنفيذ هذه العملية."))
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.toggle_service", e, "تعذر تحديث حالة الصيانة حالياً.")
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/<int:rid>/parts/add', methods=['POST'])
@login_required
def add_part(rid):
    service=_get_or_404(ServiceRequest, rid)
    
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    try:
        warehouse_id = int(request.form.get('warehouse_id'))
        product_id = int(request.form.get('part_id'))
        quantity = int(request.form.get('quantity'))
        unit_price = Decimal(request.form.get('unit_price'))
        discount = Decimal(request.form.get('discount', 0) or 0)
        tax_rate = Decimal(request.form.get('tax_rate', 0) or 0)
        note = (request.form.get('note') or '').strip() or None
        
        # Validation
        if not warehouse_id or not product_id:
            _flash_error('يجب اختيار المستودع والقطعة')
            return redirect(url_for('service.view_request', rid=rid))
        
        _ensure_partner_warehouse(warehouse_id)

        if quantity <= 0:
            _flash_error('الكمية يجب أن تكون أكبر من صفر')
            return redirect(url_for('service.view_request', rid=rid))
        
        if unit_price < 0:
            _flash_error('السعر لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        if discount < 0:
            _flash_error('الخصم لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        # التحقق من أن الخصم لا يتجاوز إجمالي البند
        gross_amount = quantity * unit_price
        if discount > gross_amount:
            _flash_error(f'الخصم ({discount:.2f} ₪) لا يمكن أن يتجاوز إجمالي البند ({gross_amount:.2f} ₪)')
            return redirect(url_for('service.view_request', rid=rid))
        
        if tax_rate < 0 or tax_rate > 100:
            _flash_error('نسبة الضريبة يجب أن تكون بين 0 و 100')
            return redirect(url_for('service.view_request', rid=rid))
        
        # ⚠️ التحقق من توفر المخزون BEFORE إضافة القطعة
        if _service_consumes_stock(service):
            from models import StockLevel, Product
            stock = StockLevel.query.filter_by(
                product_id=product_id,
                warehouse_id=warehouse_id
            ).first()
            available = stock.quantity if stock else 0
            
            if available < quantity:
                product = Product.query.get(product_id)
                product_name = product.name if product else f'#{product_id}'
                flash(f'❌ المخزون غير كافٍ للمنتج "{product_name}". '
                      f'المتوفر: {available}، المطلوب: {quantity}', 'error')
                return redirect(url_for('service.view_request', rid=rid))
        
        part=ServicePart(
            request=service, 
            service_id=rid, 
            part_id=product_id, 
            warehouse_id=warehouse_id, 
            quantity=quantity, 
            unit_price=unit_price, 
            discount=discount, 
            tax_rate=tax_rate, 
            note=note
        )
        db.session.add(part)
        db.session.flush()
        service.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        
        if not service.consume_stock:
            service.consume_stock = True
        if _service_consumes_stock(service):
            _ensure_partner_warehouse(warehouse_id)
            new_qty=utils._apply_stock_delta(product_id, warehouse_id, -quantity)
            # استخدام النظام المحسّن للتوثيق
            log_service_part_add(
                service=service,
                part_id=product_id,
                warehouse_id=warehouse_id,
                qty=quantity,
                stock_after=int(new_qty),
                reason=f"إضافة قطعة: {product.name if 'product' in locals() else product_id}"
            )
            current_app.logger.info("service.part_add",extra={"event":"service.part.add","service_id":service.id,"part_id":product_id,"warehouse_id":warehouse_id,"qty":-quantity})
        
        _update_service_totals(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        _refresh_service_related_balances(service)
        flash('✅ تمت إضافة القطعة بنجاح','success')
        
    except ValueError as ve:
        db.session.rollback()
        error_msg = str(ve).lower()
        if 'insufficient stock' in error_msg:
            flash('❌ المخزون غير كافٍ لهذه القطعة.', 'error')
        elif 'partner warehouse' in error_msg or 'warehouse' in error_msg:
            flash('❌ المستودع المحدد غير صالح أو غير نشط.', 'error')
        else:
            _flash_error(_friendly_error(ve, "القيم المدخلة غير صالحة."))
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.add_part", e, "تعذر حفظ القطعة، يرجى المحاولة لاحقاً.")
    except Exception as e:
        db.session.rollback()
        _log_and_flash("service.add_part_unexpected", e, "حدث خطأ غير متوقع أثناء إضافة القطعة.")
    
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/parts/<int:pid>/delete', methods=['POST'])
@login_required
def delete_part(pid):
    part=_get_or_404(ServicePart, pid)
    rid=part.service_id
    service=_get_or_404(ServiceRequest, rid)
    
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    if not current_user.has_permission(SystemPermissions.MANAGE_SERVICE):
        _flash_error('غير مصرح لك بحذف قطع الغيار')
        return redirect(url_for('service.view_request', rid=rid))
    stock_release_ok = True
    try:
        # التحقق مما إذا كانت القطعة قد خُصمت فعلياً - نتحقق من حركات المخزون
        current_stock_consumed = 0
        if _service_consumes_stock(service):
            currents = _service_stock_movements(service)
            key = (part.part_id, part.warehouse_id)
            current_stock_consumed = currents.get(key, 0)  # قيمة سالبة = مخصوم
        
        # نُرجع المخزون فقط إذا كانت القطعة قد خُصمت فعلياً (current_stock_consumed < 0)
        if current_stock_consumed < 0:
            try:
                _ensure_partner_warehouse(part.warehouse_id)
                qty_to_return = min(int(part.quantity or 0), abs(current_stock_consumed))
                if qty_to_return > 0:
                    new_qty=utils._apply_stock_delta(part.part_id, part.warehouse_id, +qty_to_return)
                    # استخدام النظام المحسّن للتوثيق
                    log_service_part_remove(
                        service=service,
                        part_id=part.part_id,
                        warehouse_id=part.warehouse_id,
                        qty=qty_to_return,
                        stock_after=int(new_qty),
                        reason=f"حذف قطعة من الصيانة"
                    )
                    current_app.logger.info("service.part_delete",extra={"event":"service.part.delete","service_id":service.id,"part_id":part.part_id,"warehouse_id":part.warehouse_id,"qty":+qty_to_return})
            except Exception:
                stock_release_ok = False
                current_app.logger.exception("service.part_delete.stock_release_failed service_id=%s part_id=%s", service.id, part.id)
        db.session.delete(part)
        service.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        _update_service_totals(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        _refresh_service_related_balances(service)
        if stock_release_ok:
            flash('✅ تم حذف القطعة ومعالجة المخزون','success')
        else:
            flash('✅ تم حذف القطعة، لكن تعذر تحديث المخزون تلقائياً. يرجى مراجعة المخزون يدوياً.','warning')
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.delete_part", e, "تعذر حذف القطعة حالياً.")
    except ValueError as ve:
        db.session.rollback()
        _flash_error(_friendly_error(ve, "لا يمكن إرجاع المخزون لهذه القطعة."))
    return redirect(url_for('service.view_request', rid=rid))


@service_bp.route('/<int:rid>/parts/<int:pid>/edit', methods=['POST'])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_SERVICE)
def edit_part(rid, pid):
    """تعديل قطعة موجودة في طلب الصيانة"""
    service = _get_or_404(ServiceRequest, rid)
    part = _get_or_404(ServicePart, pid)
    
    # التحقق من أن القطعة تنتمي لهذا الطلب
    if part.service_id != rid:
        _flash_error('القطعة لا تنتمي لهذا الطلب')
        return redirect(url_for('service.view_request', rid=rid))
    
    # السماح بالتعديل إذا لم يكن مكتملاً
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    try:
        # حفظ القيم القديمة لحساب فرق المخزون
        old_qty = int(part.quantity or 0)
        
        # قراءة القيم من النموذج باستخدام Decimal للدقة
        from decimal import Decimal as Dec
        new_quantity = request.form.get('quantity', old_qty, type=int)
        new_unit_price = Dec(str(request.form.get('unit_price', part.unit_price or 0)))
        new_discount = Dec(str(request.form.get('discount', part.discount or 0)))
        
        # التحقق من صحة البيانات
        if new_quantity <= 0:
            _flash_error('الكمية يجب أن تكون أكبر من صفر')
            return redirect(url_for('service.view_request', rid=rid))
        
        if new_unit_price < 0:
            _flash_error('السعر لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        if new_discount < 0:
            _flash_error('الخصم لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        # التحقق من أن الخصم لا يتجاوز إجمالي البند (مطابق لقاعدة قاعدة البيانات)
        gross_amount = Dec(new_quantity) * new_unit_price
        if new_discount > gross_amount:
            _flash_error(f'الخصم ({new_discount:.2f} ₪) لا يمكن أن يتجاوز إجمالي البند ({gross_amount:.2f} ₪)')
            return redirect(url_for('service.view_request', rid=rid))
        
        # ⚠️ التحقق من المخزون BEFORE تحديث البيانات
        actual_consumed = 0  # تعريف المتغير هنا للاستخدام لاحقاً
        if _service_consumes_stock(service):
            from models import StockLevel, Product
            
            # حساب الكمية المطلوبة فعلياً
            currents = _service_stock_movements(service)
            key = (part.part_id, part.warehouse_id)
            current_consumed = currents.get(key, 0)  # سالب = مخصوم
            actual_consumed = abs(min(current_consumed, 0))
            
            # الكمية التي ستُخصم = الجديدة - المخصومة فعلياً
            qty_to_consume = new_quantity - actual_consumed
            
            if qty_to_consume > 0:
                # التحقق من توفر المخزون
                stock = StockLevel.query.filter_by(
                    product_id=part.part_id,
                    warehouse_id=part.warehouse_id
                ).first()
                available = stock.quantity if stock else 0
                
                if available < qty_to_consume:
                    product = Product.query.get(part.part_id)
                    product_name = product.name if product else f'#{part.part_id}'
                    flash(f'❌ المخزون غير كافٍ للمنتج "{product_name}". '
                          f'المتوفر: {available}، المطلوب: {qty_to_consume}', 'error')
                    return redirect(url_for('service.view_request', rid=rid))
        
        # ✅ الآن يمكن تحديث البيانات بعد التحقق من المخزون
        part.quantity = new_quantity
        part.unit_price = new_unit_price
        part.discount = new_discount
        # لا حاجة لحساب line_total يدوياً -它是 hybrid_property ويُحسّب تلقائياً
        
        # تحديث المخزون بالفرق فقط (delta) لتجنب أي تكرار بالخصم.
        stock_adjusted = False
        if _service_consumes_stock(service):
            try:
                _ensure_partner_warehouse(part.warehouse_id)
                qty_delta = int(new_quantity) - int(actual_consumed)

                # زيادة الكمية: نخصم الفرق فقط.
                if qty_delta > 0:
                    consumed_stock = utils._apply_stock_delta(part.part_id, part.warehouse_id, -qty_delta)
                    log_service_part_add(
                        service=service,
                        part_id=part.part_id,
                        warehouse_id=part.warehouse_id,
                        qty=qty_delta,
                        stock_after=int(consumed_stock),
                        reason="تعديل قطعة: خصم فرق الكمية"
                    )
                # تقليل الكمية: نُرجع الفرق فقط.
                elif qty_delta < 0:
                    qty_to_return = abs(qty_delta)
                    returned_stock = utils._apply_stock_delta(part.part_id, part.warehouse_id, qty_to_return)
                    log_service_part_remove(
                        service=service,
                        part_id=part.part_id,
                        warehouse_id=part.warehouse_id,
                        qty=qty_to_return,
                        stock_after=int(returned_stock),
                        reason="تعديل قطعة: إرجاع فرق الكمية"
                    )
                
                stock_adjusted = True
                
            except ValueError as ve:
                # التحقق من نوع خطأ المخزون
                error_msg = str(ve).lower()
                if 'insufficient stock' in error_msg or 'stock' in error_msg:
                    from models import StockLevel, Product
                    stock = StockLevel.query.filter_by(
                        product_id=part.part_id, 
                        warehouse_id=part.warehouse_id
                    ).first()
                    available = stock.quantity if stock else 0
                    product = Product.query.get(part.part_id)
                    product_name = product.name if product else f'#{part.part_id}'
                    
                    flash(f'❌ المخزون غير كافٍ للمنتج "{product_name}". '
                          f'المتوفر: {available}، المطلوب: {new_quantity}', 'error')
                else:
                    flash(f'❌ خطأ: {ve}', 'error')
                db.session.rollback()
                return redirect(url_for('service.view_request', rid=rid))
            except Exception as stock_e:
                current_app.logger.exception("service.part_edit.stock_adjust_failed")
                flash('⚠️ تم تعديل القطعة، لكن تعذر تحديث المخزون تلقائياً.', 'warning')
        else:
            # المخزون لا يُخصم في هذه الحالة، لا مشكلة
            stock_adjusted = True
        
        # تحديث إجماليات الطلب
        _update_service_totals(service)
        service.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        db.session.commit()
        
        # مزامنة الحسابات
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed: {e}")
        
        _refresh_service_related_balances(service)
        flash('✅ تم تعديل القطعة بنجاح', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        error_msg = str(ve).lower()
        if 'insufficient stock' in error_msg:
            flash('❌ المخزون غير كافٍ لهذه القطعة.', 'error')
        else:
            _flash_error(_friendly_error(ve, "بيانات غير صالحة."))
        return redirect(url_for('service.view_request', rid=rid))
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("service.edit_part.failed")
        flash('❌ تعذر حفظ القطعة، يرجى المحاولة لاحقاً.', 'error')
        return redirect(url_for('service.view_request', rid=rid))
    
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/<int:rid>/tasks/add', methods=['POST'])
@login_required
def add_task(rid):
    service=_get_or_404(ServiceRequest, rid)
    
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    try:
        description = (request.form.get('description') or '').strip()
        quantity = int(request.form.get('quantity', 1))
        unit_price = Decimal(request.form.get('unit_price'))
        discount = Decimal(request.form.get('discount', 0) or 0)
        tax_rate = Decimal(request.form.get('tax_rate', 0) or 0)
        note = (request.form.get('note') or '').strip() or None
        
        # Validation
        if not description:
            _flash_error('يجب إدخال وصف المهمة')
            return redirect(url_for('service.view_request', rid=rid))
        
        if quantity <= 0:
            _flash_error('الكمية يجب أن تكون أكبر من صفر')
            return redirect(url_for('service.view_request', rid=rid))
        
        if unit_price < 0:
            _flash_error('السعر لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        if discount < 0:
            _flash_error('الخصم لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        # التحقق من أن الخصم لا يتجاوز إجمالي البند
        gross_amount = quantity * unit_price
        if discount > gross_amount:
            _flash_error(f'الخصم ({discount:.2f} ₪) لا يمكن أن يتجاوز إجمالي البند ({gross_amount:.2f} ₪)')
            return redirect(url_for('service.view_request', rid=rid))
        
        if tax_rate < 0 or tax_rate > 100:
            _flash_error('نسبة الضريبة يجب أن تكون بين 0 و 100')
            return redirect(url_for('service.view_request', rid=rid))
        
        task=ServiceTask(
            request=service, 
            service_id=rid, 
            description=description, 
            quantity=quantity, 
            unit_price=unit_price, 
            discount=discount, 
            tax_rate=tax_rate, 
            note=note
        )
        db.session.add(task)
        db.session.flush()
        service.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        _update_service_totals(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        _refresh_service_related_balances(service)
        flash('✅ تمت إضافة المهمة بنجاح','success')
        
    except ValueError as ve:
        db.session.rollback()
        _flash_error(_friendly_error(ve, "القيم المدخلة غير صالحة."))
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.add_task", e, "تعذر حفظ المهمة الجديدة، يرجى المحاولة لاحقاً.")
    except Exception as e:
        db.session.rollback()
        _log_and_flash("service.add_task_unexpected", e, "حدث خطأ غير متوقع أثناء إضافة المهمة.")
    
    return redirect(url_for('service.view_request', rid=rid))


@service_bp.route('/<int:rid>/tasks/<int:tid>/edit', methods=['POST'])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_SERVICE)
def edit_task(rid, tid):
    """تعديل مهمة موجودة في طلب الصيانة"""
    service = _get_or_404(ServiceRequest, rid)
    task = _get_or_404(ServiceTask, tid)
    
    # التحقق من أن المهمة تنتمي لهذا الطلب
    if task.service_id != rid:
        _flash_error('المهمة لا تنتمي لهذا الطلب')
        return redirect(url_for('service.view_request', rid=rid))
    
    # السماح بالتعديل إذا لم يكن مكتملاً
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    
    try:
        # قراءة القيم من النموذج
        description = (request.form.get('description') or '').strip()
        quantity = int(request.form.get('quantity', task.quantity or 1))
        unit_price = Decimal(request.form.get('unit_price', task.unit_price or 0))
        discount = Decimal(request.form.get('discount', task.discount or 0) or 0)
        note = (request.form.get('note') or '').strip() or None
        
        # التحقق من صحة البيانات
        if not description:
            _flash_error('يجب إدخال وصف المهمة')
            return redirect(url_for('service.view_request', rid=rid))
        
        if quantity <= 0:
            _flash_error('الكمية يجب أن تكون أكبر من صفر')
            return redirect(url_for('service.view_request', rid=rid))
        
        if unit_price < 0:
            _flash_error('السعر لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        if discount < 0:
            _flash_error('الخصم لا يمكن أن يكون سالباً')
            return redirect(url_for('service.view_request', rid=rid))
        
        # التحقق من أن الخصم لا يتجاوز إجمالي البند
        gross_amount = quantity * unit_price
        if discount > gross_amount:
            _flash_error(f'الخصم ({discount:.2f} ₪) لا يمكن أن يتجاوز إجمالي البند ({gross_amount:.2f} ₪)')
            return redirect(url_for('service.view_request', rid=rid))
        
        # تحديث البيانات
        task.description = description
        task.quantity = quantity
        task.unit_price = unit_price
        task.discount = discount
        task.note = note
        # line_total يُحسّب تلقائياً كـ hybrid_property
        
        # تحديث إجماليات الطلب
        _update_service_totals(service)
        service.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        db.session.commit()
        
        # مزامنة الحسابات
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        
        _refresh_service_related_balances(service)
        flash('✅ تم تعديل المهمة بنجاح', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        _flash_error(_friendly_error(ve, "بيانات غير صالحة."))
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.edit_task", e, "تعذر تعديل المهمة حالياً.")
    
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/tasks/<int:tid>/delete', methods=['POST'])
@login_required
def delete_task(tid):
    task=_get_or_404(ServiceTask, tid); rid=task.service_id; service=_get_or_404(ServiceRequest, rid)
    
    if service.status == ServiceStatus.COMPLETED.value:
        _flash_error('لا يمكن تعديل صيانة مكتملة. يرجى الضغط على "إعادة للصيانه" أولاً')
        return redirect(url_for('service.view_request', rid=rid))
    if not current_user.has_permission(SystemPermissions.MANAGE_SERVICE):
        _flash_error('غير مصرح لك بحذف المهام')
        return redirect(url_for('service.view_request', rid=rid))
    try:
        db.session.delete(task)
        service.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        _update_service_totals(service)
        db.session.commit()
        try:
            run_service_gl_sync_after_commit(service.id)
        except Exception as e:
            current_app.logger.error(f"⚠️ GL Sync Failed for Service #{service.id}: {e}")
        _refresh_service_related_balances(service)
        flash('✅ تم حذف المهمة','success')
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.delete_task", e, "تعذر حذف المهمة حالياً.")
    except Exception as e:
        db.session.rollback()
        _log_and_flash("service.delete_task_unexpected", e, "حدث خطأ غير متوقع أثناء حذف المهمة.")
    return redirect(url_for('service.view_request', rid=rid))

@service_bp.route('/<int:rid>/payments/add', methods=['GET','POST'])
@login_required
def add_payment(rid):
    """إعادة توجيه لإنشاء دفعة للصيانة مع البيانات الكاملة"""
    service = _get_or_404(ServiceRequest, rid)
    
    # حساب المبلغ المتبقي فعلاً
    balance = None
    try:
        balance = float(getattr(service, 'balance_due', None) or 0)
    except Exception:
        balance = None
    if balance is None or balance < 0:
        try:
            total_amt = float(getattr(service, 'total', 0) or 0)
            total_paid = float(getattr(service, 'total_paid', 0) or 0)
            balance = max(total_amt - total_paid, 0)
        except Exception:
            try:
                total_amt = float(getattr(service, 'total', 0) or 0)
                balance = total_amt
            except Exception:
                balance = 0
    if balance <= 0:
        flash('🔔 هذا الطلب مسدد بالكامل، لا يمكن إضافة دفعة جديدة.', 'warning')
        return redirect(url_for('service.view_request', rid=rid))
    
    # جلب العملة
    currency = getattr(service, 'currency', 'ILS') or 'ILS'
    
    # تجهيز المرجع والملاحظات
    customer_name = service.customer.name if service.customer else 'عميل'
    service_number = service.service_number or f'#{service.id}'
    
    return redirect(url_for('payments.create_payment', 
                          entity_type='SERVICE', 
                          entity_id=rid,
                          amount=balance if balance and balance > 0 else None,
                          currency=currency,
                          reference=f'دفع صيانة من {customer_name} - {service_number}',
                          notes=f'دفع طلب صيانة: {service_number} - العميل: {customer_name} - المركبة: {service.vehicle_model or "غير محدد"}',
                          customer_id=service.customer_id if service.customer_id else None))

@service_bp.route('/<int:rid>/invoice', methods=['GET','POST'])
@login_required
def create_invoice(rid):
    svc=_get_or_404(ServiceRequest, rid, load_options=[joinedload(ServiceRequest.parts), joinedload(ServiceRequest.tasks)])
    try: amount=float(getattr(svc,'balance_due',None) or getattr(svc,'total_cost',0) or 0)
    except Exception: amount=0.0
    return redirect(url_for('payments.create_payment', entity_type='SERVICE', entity_id=rid, amount=amount))

@service_bp.route('/<int:rid>/report')
@login_required
def service_report(rid):
    service=_get_or_404(ServiceRequest, rid); pdf=generate_service_receipt_pdf(service)
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename=service_report_{service.service_number or service.id}.pdf'})

@service_bp.route('/<int:rid>/pdf')
@login_required
def export_pdf(rid):
    service=_get_or_404(ServiceRequest, rid); pdf=generate_service_receipt_pdf(service)
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename=service_{service.service_number or service.id}.pdf'})

@service_bp.route('/<int:rid>/delete', methods=['POST'])
@login_required
def delete_request(rid):
    service=_get_or_404(ServiceRequest, rid)
    customer_id = getattr(service, "customer_id", None)
    partner_ids = set()
    try:
        for sp in (list(getattr(service, "parts", []) or []) + list(getattr(service, "tasks", []) or [])):
            pid = getattr(sp, "partner_id", None)
            if pid:
                partner_ids.add(int(pid))
    except Exception:
        partner_ids = set()
    reversal_snapshot = build_service_reversal_snapshot(service)
    try:
        with db.session.begin():
            _release_service_stock_once(service); db.session.delete(service)
        try:
            run_service_gl_reversal_after_delete(reversal_snapshot)
        except Exception:
            current_app.logger.warning('DB delete failed silently')
        flash('✅ تم حذف الطلب ومعالجة المخزون','success')
        try:
            if customer_id:
                from utils.customer_balance_updater import update_customer_balance_components
                update_customer_balance_components(int(customer_id))
            for pid in partner_ids:
                utils.update_entity_balance("PARTNER", int(pid))
        except Exception:
            current_app.logger.warning(f'Failed to update customer balance')
    except SQLAlchemyError as e:
        db.session.rollback()
        _log_and_flash("service.delete_request", e, "تعذر حذف الطلب حالياً.")
    except ValueError as ve:
        db.session.rollback()
        _flash_error(_friendly_error(ve, "لا يمكن حذف الطلب حالياً."))
    return redirect(url_for('service.list_requests'))

@service_bp.route('/api/requests', methods=['GET'])
@login_required
def api_service_requests():
    status=(request.args.get('status','all') or '').upper()
    if status=='ALL' or not hasattr(ServiceStatus,status): reqs=ServiceRequest.query.limit(1000).all()
    else: reqs=ServiceRequest.query.filter_by(status=getattr(ServiceStatus,status)).limit(1000).all()
    result=[{'id':r.id,'service_number':r.service_number,'customer':r.customer.name if r.customer else (getattr(r,'name','') or ''),'vehicle_vrn':r.vehicle_vrn,'status':getattr(r.status,'value',r.status),'priority':getattr(r.priority,'value',r.priority),'request_date':(r.received_at.strftime('%Y-%m-%d %H:%M') if getattr(r,'received_at',None) else ''),'mechanic':r.mechanic.username if getattr(r,'mechanic',None) else ''} for r in reqs]
    return jsonify(result)

@service_bp.route('/search', methods=['GET'])
@login_required
def search_requests():
    query=request.args.get('q','')
    if not query: return jsonify([])
    results=ServiceRequest.query.join(Customer).filter(or_(ServiceRequest.service_number.ilike(f'%{query}%'),ServiceRequest.vehicle_vrn.ilike(f'%{query}%'),Customer.name.ilike(f'%{query}%'),Customer.phone.ilike(f'%{query}%'))).limit(10).all()


@service_bp.route('/analytics')
@login_required
def analytics():
    """تحليلات الصيانة المتقدمة"""
    from datetime import datetime, timedelta
    
    # إحصائيات شاملة
    total_requests = ServiceRequest.query.count()
    completed_this_month = ServiceRequest.query.filter(
        ServiceRequest.status == ServiceStatus.COMPLETED.value,
        ServiceRequest.completed_at >= datetime.now().replace(day=1)
    ).count()
    
    # متوسط وقت الإنجاز
    avg_completion_time = db.session.query(
        func.avg(
            func.julianday(ServiceRequest.completed_at) - 
            func.julianday(ServiceRequest.received_at)
        )
    ).filter(
        ServiceRequest.status == ServiceStatus.COMPLETED.value,
        ServiceRequest.completed_at.isnot(None)
    ).scalar() or 0
    
    # أكثر المشاكل شيوعاً
    common_problems = db.session.query(
        ServiceRequest.problem_description,
        func.count(ServiceRequest.id).label('count')
    ).filter(
        ServiceRequest.problem_description.isnot(None),
        ServiceRequest.problem_description != ''
    ).group_by(ServiceRequest.problem_description).order_by(desc('count')).limit(10).all()
    
    # إحصائيات الأسبوع
    week_ago = datetime.now() - timedelta(days=7)
    weekly_stats = {
        'new': ServiceRequest.query.filter(ServiceRequest.received_at >= week_ago).count(),
        'completed': ServiceRequest.query.filter(
            ServiceRequest.completed_at >= week_ago,
            ServiceRequest.status == ServiceStatus.COMPLETED.value
        ).count(),
        'in_progress': ServiceRequest.query.filter(
            ServiceRequest.status == 'IN_PROGRESS'
        ).count()
    }
    
    return render_template('service/analytics.html', 
                         total_requests=total_requests,
                         completed_this_month=completed_this_month,
                         avg_completion_time=avg_completion_time,
                         common_problems=common_problems,
                         weekly_stats=weekly_stats)


# دوال مساعدة للأرشفة - تم نقلها إلى utils/archive_utils.py

def log_service_action(service, action, old_data=None, new_data=None):
    entry=AuditLog(model_name='ServiceRequest', record_id=service.id, user_id=current_user.id if current_user and getattr(current_user,'id',None) else None, action=action, old_data=json.dumps(old_data, ensure_ascii=False) if old_data else None, new_data=json.dumps(new_data, ensure_ascii=False) if new_data else None)
    db.session.add(entry); db.session.flush()

def generate_service_receipt_pdf(service_request):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception:
        return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    buffer=io.BytesIO(); c=canvas.Canvas(buffer, pagesize=A4); width,height=A4
    c.setFont("Helvetica-Bold",16); c.drawString(20*mm,height-20*mm,"إيصال صيانة")
    c.setFont("Helvetica",10); y=height-30*mm
    c.drawString(20*mm,y,f"رقم الطلب: {service_request.service_number or service_request.id or ''}")
    c.drawString(120*mm,y,f"التاريخ: {service_request.received_at.strftime('%Y-%m-%d') if getattr(service_request,'received_at',None) else ''}")
    y-=8*mm; c.drawString(20*mm,y,f"العميل: {service_request.customer.name if service_request.customer else (getattr(service_request,'name',None) or '-')}")
    c.drawString(120*mm,y,f"لوحة المركبة: {service_request.vehicle_vrn or ''}")
    y-=12*mm; c.setFont("Helvetica-Bold",11); c.drawString(20*mm,y,"القطع المُركّبة"); y-=6*mm; c.setFont("Helvetica",9)
    headers=[("الصنف",20),("المخزن",70),("الكمية",110),("سعر",125),("خصم ₪",145),("ضريبة%",160),("الإجمالي",175)]
    for h,x in headers: c.drawString(x*mm,y,h)
    y-=4*mm; c.line(20*mm,y,200*mm,y); y-=6*mm
    parts_total=0.0
    for part in getattr(service_request,"parts",[]) or []:
        qty=int(part.quantity or 0); u=float(part.unit_price or 0); disc=float(part.discount or 0); taxr=float(part.tax_rate or 0)
        gross=qty*u; disc_amount=disc; taxable=max(0, gross-disc_amount); tax_amount=taxable*(taxr/100.0); line_total=taxable+tax_amount; parts_total+=line_total
        c.drawString(20*mm,y,(getattr(part.part,'name','') or str(part.part_id))[:25]); c.drawString(70*mm,y,getattr(part.warehouse,'name','—') or '—')
        c.drawRightString(120*mm,y,str(qty)); c.drawRightString(140*mm,y,f"{u:.2f}"); c.drawRightString(155*mm,y,f"{disc:.0f}"); c.drawRightString(170*mm,y,f"{taxr:.0f}"); c.drawRightString(195*mm,y,f"{line_total:.2f}")
        y-=6*mm
        if y<40*mm: c.showPage(); y=height-20*mm; c.setFont("Helvetica",9)
    y-=8*mm; c.setFont("Helvetica-Bold",11); c.drawString(20*mm,y,"المهام"); y-=6*mm; c.setFont("Helvetica",9)
    headers=[("الوصف",20),("الكمية",110),("سعر",125),("خصم ₪",145),("ضريبة%",160),("الإجمالي",175)]
    for h,x in headers: c.drawString(x*mm,y,h)
    y-=4*mm; c.line(20*mm,y,200*mm,y); y-=6*mm
    tasks_total=0.0
    for task in getattr(service_request,"tasks",[]) or []:
        qty=int(task.quantity or 1); u=float(task.unit_price or 0); disc=float(task.discount or 0); taxr=float(task.tax_rate or 0)
        gross=qty*u; disc_amount=disc; taxable=max(0, gross-disc_amount); tax_amount=taxable*(taxr/100.0); line_total=taxable+tax_amount; tasks_total+=line_total
        c.drawString(20*mm,y,(task.description or '')[:40]); c.drawRightString(120*mm,y,str(qty)); c.drawRightString(140*mm,y,f"{u:.2f}"); c.drawRightString(155*mm,y,f"{disc:.0f}"); c.drawRightString(170*mm,y,f"{taxr:.0f}"); c.drawRightString(195*mm,y,f"{line_total:.2f}")
        y-=6*mm
        if y<40*mm: c.showPage(); y=height-20*mm; c.setFont("Helvetica",9)
    subtotal=parts_total+tasks_total; y-=10*mm; c.setFont("Helvetica-Bold",11); c.drawRightString(160*mm,y,"الإجمالي الكلي:"); c.drawRightString(195*mm,y,f"{subtotal:.2f}")
    c.showPage(); c.save(); buffer.seek(0); return buffer.getvalue()
