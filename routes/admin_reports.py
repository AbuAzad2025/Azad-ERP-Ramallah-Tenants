
from datetime import datetime, date as _date, time as _time, timedelta, timezone
from flask import Blueprint, render_template, request, abort, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func, case
from sqlalchemy.orm import joinedload, selectinload
from extensions import db, limiter, csrf, cache
from models import OnlinePayment, OnlinePreOrder, Customer, OnlinePaymentStatus, PreOrderStatus
from permissions_config.enums import SystemPermissions
import utils

admin_reports_bp = Blueprint(
    "admin_reports",
    __name__,
    url_prefix="/admin/reports",
    template_folder="templates/admin/reports",
)

@admin_reports_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def admin_reports_index():
    """صفحة التقارير الإدارية الرئيسية"""
    from sqlalchemy import func
    from models import OnlinePayment, OnlinePreOrder
    
    stats_cache_key = "admin_reports_stats"
    stats = cache.get(stats_cache_key)
    
    if stats is None:
        try:
            total_payments = OnlinePayment.query.count()
            successful_payments = OnlinePayment.query.filter_by(status=OnlinePaymentStatus.SUCCESS.value).count()
            total_preorders = OnlinePreOrder.query.count()
            pending_preorders = OnlinePreOrder.query.filter_by(status=PreOrderStatus.PENDING.value).count()
            
            today_start = datetime.combine(_date.today(), _time.min)
            today_payments = OnlinePayment.query.filter(
                OnlinePayment.created_at >= today_start,
                OnlinePayment.status == OnlinePaymentStatus.SUCCESS.value
            ).count()
            
            today_revenue = db.session.query(func.sum(OnlinePayment.amount)).filter(
                OnlinePayment.created_at >= today_start,
                OnlinePayment.status == OnlinePaymentStatus.SUCCESS.value
            ).scalar() or 0
            
            stats = {
                'total_payments': total_payments,
                'successful_payments': successful_payments,
                'total_preorders': total_preorders,
                'pending_preorders': pending_preorders,
                'today_payments': today_payments,
                'today_revenue': float(today_revenue or 0),
                'success_rate': round((successful_payments / total_payments * 100) if total_payments > 0 else 0, 2)
            }
            cache.set(stats_cache_key, stats, timeout=300)
        except Exception as e:
            current_app.logger.error(f"Error loading admin reports stats: {e}")
            stats = {
                'total_payments': 0,
                'successful_payments': 0,
                'total_preorders': 0,
                'pending_preorders': 0,
                'today_payments': 0,
                'today_revenue': 0,
                'success_rate': 0
            }
    
    return render_template("admin/reports/index.html", stats=stats)

def _mask_pan(pan: str) -> str:
    if not pan:
        return ""
    digits = "".join(ch for ch in pan if ch.isdigit())
    if len(digits) <= 4:
        return "*" * max(0, len(digits) - 1) + digits[-1:]
    return "**** **** **** " + digits[-4:]

def _parse_yyyy_mm_dd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

@admin_reports_bp.route("/cards", methods=["GET"], endpoint="cards")
@login_required
@limiter.limit("30/minute")
def cards():
    start = request.args.get("start")
    end = request.args.get("end")
    status = request.args.get("status")
    search = (request.args.get("q") or "").strip()
    sd = _parse_yyyy_mm_dd(start) if start else None
    ed = _parse_yyyy_mm_dd(end) if end else None
    
    cache_key = f"admin_cards_{start}_{end}_{status}_{search}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return render_template("admin/reports/cards.html", rows=cached_result)
    
    q = (
        OnlinePayment.query
        .options(
            joinedload(OnlinePayment.order).joinedload(OnlinePreOrder.customer)
        )
        .join(OnlinePreOrder, OnlinePayment.order_id == OnlinePreOrder.id)
        .join(Customer, OnlinePreOrder.customer_id == Customer.id)
    )
    
    if sd:
        q = q.filter(OnlinePayment.created_at >= datetime.combine(sd, _time.min))
    if ed:
        q = q.filter(OnlinePayment.created_at < datetime.combine(ed + timedelta(days=1), _time.min))
    if status and status in [s.value for s in OnlinePaymentStatus]:
        q = q.filter(OnlinePayment.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(OnlinePayment.payment_ref.ilike(like), Customer.name.ilike(like), Customer.phone.ilike(like)))
    
    rows = q.order_by(OnlinePayment.created_at.desc()).limit(500).all()
    cache.set(cache_key, rows, timeout=60)
    return render_template("admin/reports/cards.html", rows=rows)

@admin_reports_bp.route("/cards/<int:pid>/reveal", methods=["POST"], endpoint="cards_reveal")
@login_required
@utils.super_only
@limiter.limit("5/minute;20/hour;50/day")
def cards_reveal(pid: int):
    op = db.session.get(OnlinePayment, pid)
    if not op:
        abort(404)
    pan_decrypted = op.decrypt_card_number() or ""
    pan_masked = _mask_pan(pan_decrypted)
    reveal_enabled = bool(current_app.config.get("REVEAL_PAN_ENABLED", False))
    if not reveal_enabled:
        utils.log_audit("OnlinePayment", op.id, "reveal_card_attempt", None, {"payment_ref": op.payment_ref, "result": "blocked_by_config"})
        resp = jsonify({
            "ok": False,
            "reason": "disabled_by_config",
            "payment_ref": op.payment_ref,
            "pan_masked": pan_masked,
            "brand": op.card_brand,
            "last4": op.card_last4,
            "holder": op.cardholder_name,
            "expiry": op.card_expiry,
            "amount": float(op.amount or 0),
            "currency": op.currency,
            "created_at": op.created_at.isoformat() if getattr(op, "created_at", None) else None,
        })
        resp.headers["Cache-Control"] = "no-store"
        return resp, 403
    data = request.get_json(silent=True) or request.form or {}
    password = (data.get("password") or "").strip()
    if not password:
        utils.log_audit("OnlinePayment", op.id, "reveal_card_attempt", None, {"payment_ref": op.payment_ref, "result": "missing_password"})
        resp = jsonify({"ok": False, "error": "password_required", "pan_masked": pan_masked})
        resp.headers["Cache-Control"] = "no-store"
        return resp, 400
    try:
        check_ok = current_user.check_password(password)
    except Exception:
        check_ok = False
    if not check_ok:
        utils.log_audit("OnlinePayment", op.id, "reveal_card_attempt", None, {"payment_ref": op.payment_ref, "result": "bad_password"})
        resp = jsonify({"ok": False, "error": "invalid_password", "pan_masked": pan_masked})
        resp.headers["Cache-Control"] = "no-store"
        return resp, 403
    digits = "".join(ch for ch in pan_decrypted if ch.isdigit())
    if op.card_last4 and digits[-4:] != (op.card_last4 or ""):
        utils.log_audit("OnlinePayment", op.id, "reveal_card_mismatch", None, {"payment_ref": op.payment_ref, "result": "last4_mismatch"})
        resp = jsonify({"ok": False, "error": "card_data_mismatch", "pan_masked": pan_masked})
        resp.headers["Cache-Control"] = "no-store"
        return resp, 409
    utils.log_audit("OnlinePayment", op.id, "reveal_card", None, {"payment_ref": op.payment_ref, "result": "success"})
    resp = jsonify({
        "ok": True,
        "payment_ref": op.payment_ref,
        "pan": pan_decrypted,
        "pan_masked": pan_masked,
        "brand": op.card_brand,
        "last4": op.card_last4,
        "holder": op.cardholder_name,
        "expiry": op.card_expiry,
        "amount": float(op.amount or 0),
        "currency": op.currency,
        "created_at": op.created_at.isoformat() if getattr(op, "created_at", None) else None,
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp

@admin_reports_bp.route("/preorders", methods=["GET"], endpoint="preorders")
@login_required
@limiter.limit("30/minute")
def preorders():
    """تقرير الحجوزات المسبقة (PreOrders)"""
    start = request.args.get("start")
    end = request.args.get("end")
    status = request.args.get("status")
    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    
    sd = _parse_yyyy_mm_dd(start) if start else None
    ed = _parse_yyyy_mm_dd(end) if end else None
    
    base_q = OnlinePreOrder.query
    
    if sd:
        base_q = base_q.filter(OnlinePreOrder.created_at >= datetime.combine(sd, _time.min))
    if ed:
        base_q = base_q.filter(OnlinePreOrder.created_at < datetime.combine(ed + timedelta(days=1), _time.min))
    if status and status in [s.value for s in PreOrderStatus]:
        base_q = base_q.filter(OnlinePreOrder.status == status)
    if search:
        like = f"%{search}%"
        base_q = base_q.outerjoin(Customer, OnlinePreOrder.customer_id == Customer.id).filter(
            or_(
                OnlinePreOrder.order_number.ilike(like),
                Customer.name.ilike(like),
                Customer.phone.ilike(like)
            )
        )
    
    totals_row = base_q.order_by(None).with_entities(
        func.count(OnlinePreOrder.id).label("total"),
        func.coalesce(func.sum(func.coalesce(OnlinePreOrder.total_amount, 0)), 0).label("total_amount"),
        func.coalesce(func.sum(func.coalesce(OnlinePreOrder.prepaid_amount, 0)), 0).label("prepaid_amount"),
        func.coalesce(func.sum(case((OnlinePreOrder.status == PreOrderStatus.FULFILLED.value, 1), else_=0)), 0).label("fulfilled"),
    ).first()
    totals = {
        "total": int(getattr(totals_row, "total", 0) or 0),
        "fulfilled": int(getattr(totals_row, "fulfilled", 0) or 0),
        "total_amount": float(getattr(totals_row, "total_amount", 0) or 0),
        "prepaid_amount": float(getattr(totals_row, "prepaid_amount", 0) or 0),
    }

    q = base_q.options(
        joinedload(OnlinePreOrder.customer),
        selectinload(OnlinePreOrder.items),
    ).order_by(OnlinePreOrder.created_at.desc(), OnlinePreOrder.id.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    rows = list(pagination.items or [])

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)

    return render_template(
        "admin/reports/preorders.html",
        rows=rows,
        totals=totals,
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
    )


@admin_reports_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
@login_required
@limiter.limit("60/minute")
def admin_dashboard():
    """Dashboard شامل للمالك مع إحصائيات حية"""
    from sqlalchemy import func, and_
    from models import Sale, Payment, Expense, ServiceRequest, Product, StockLevel, SaleStatus, PaymentStatus, PaymentDirection, ServiceStatus
    from decimal import Decimal
    
    cache_key = "admin_dashboard_stats"
    cached_stats = cache.get(cache_key)
    
    if cached_stats is None:
        try:
            today = _date.today()
            today_start = datetime.combine(today, _time.min)
            today_end = datetime.combine(today + timedelta(days=1), _time.min)
            
            week_start = today - timedelta(days=7)
            month_start = today - timedelta(days=30)
            
            today_sales = db.session.query(func.sum(Sale.total_amount)).filter(
                and_(
                    Sale.sale_date >= today_start,
                    Sale.sale_date < today_end,
                    Sale.status == SaleStatus.CONFIRMED.value
                )
            ).scalar() or Decimal("0")
            
            week_sales = db.session.query(func.sum(Sale.total_amount)).filter(
                and_(
                    Sale.sale_date >= datetime.combine(week_start, _time.min),
                    Sale.status == SaleStatus.CONFIRMED.value
                )
            ).scalar() or Decimal("0")
            
            month_sales = db.session.query(func.sum(Sale.total_amount)).filter(
                and_(
                    Sale.sale_date >= datetime.combine(month_start, _time.min),
                    Sale.status == SaleStatus.CONFIRMED.value
                )
            ).scalar() or Decimal("0")
            
            today_payments_in = db.session.query(func.sum(Payment.total_amount)).filter(
                and_(
                    Payment.payment_date >= today_start,
                    Payment.payment_date < today_end,
                    Payment.direction == PaymentDirection.IN.value,
                    Payment.status == PaymentStatus.COMPLETED.value
                )
            ).scalar() or Decimal("0")
            
            today_payments_out = db.session.query(func.sum(Payment.total_amount)).filter(
                and_(
                    Payment.payment_date >= today_start,
                    Payment.payment_date < today_end,
                    Payment.direction == PaymentDirection.OUT.value,
                    Payment.status == PaymentStatus.COMPLETED.value
                )
            ).scalar() or Decimal("0")
            
            pending_services = ServiceRequest.query.filter(
                ~ServiceRequest.status.in_([ServiceStatus.COMPLETED.value, ServiceStatus.CANCELLED.value])
            ).count()
            
            low_stock_count = db.session.query(func.count(Product.id)).join(
                StockLevel, Product.id == StockLevel.product_id
            ).filter(
                and_(
                    Product.is_active.is_(True),
                    func.coalesce(StockLevel.quantity, 0) <= Product.min_qty
                )
            ).scalar() or 0
            
            total_customers = db.session.query(func.count(Customer.id)).scalar() or 0
            total_products = db.session.query(func.count(Product.id)).filter(
                Product.is_active.is_(True)
            ).scalar() or 0
            
            recent_online_payments = OnlinePayment.query.options(
                joinedload(OnlinePayment.order).joinedload(OnlinePreOrder.customer)
            ).filter(
                OnlinePayment.status == OnlinePaymentStatus.SUCCESS.value
            ).order_by(OnlinePayment.created_at.desc()).limit(10).all()
            
            stats = {
                'today_sales': float(today_sales),
                'week_sales': float(week_sales),
                'month_sales': float(month_sales),
                'today_payments_in': float(today_payments_in),
                'today_payments_out': float(today_payments_out),
                'today_net': float(today_payments_in - today_payments_out),
                'pending_services': pending_services,
                'low_stock_count': low_stock_count,
                'total_customers': total_customers,
                'total_products': total_products,
                'recent_online_payments': recent_online_payments
            }
            
            cache.set(cache_key, stats, timeout=120)
        except Exception as e:
            current_app.logger.error(f"Error loading admin dashboard stats: {e}")
            stats = {
                'today_sales': 0,
                'week_sales': 0,
                'month_sales': 0,
                'today_payments_in': 0,
                'today_payments_out': 0,
                'today_net': 0,
                'pending_services': 0,
                'low_stock_count': 0,
                'total_customers': 0,
                'total_products': 0,
                'recent_online_payments': []
            }
    else:
        stats = cached_stats
    
    return render_template("admin/reports/dashboard.html", stats=stats)


@admin_reports_bp.route("/api/stats", methods=["GET"], endpoint="api_stats")
@login_required
@limiter.limit("120/minute")
def api_stats():
    """API للحصول على إحصائيات حية"""
    from sqlalchemy import func, and_
    from models import Sale, Payment, ServiceRequest, SaleStatus, PaymentStatus, ServiceStatus
    
    try:
        today = _date.today()
        today_start = datetime.combine(today, _time.min)
        today_end = datetime.combine(today + timedelta(days=1), _time.min)
        
        today_sales_count = Sale.query.filter(
            and_(
                Sale.sale_date >= today_start,
                Sale.sale_date < today_end,
                Sale.status == SaleStatus.CONFIRMED.value
            )
        ).count()
        
        today_payments_count = Payment.query.filter(
            and_(
                Payment.payment_date >= today_start,
                Payment.payment_date < today_end,
                Payment.status == PaymentStatus.COMPLETED.value
            )
        ).count()
        
        pending_services = ServiceRequest.query.filter(
            ~ServiceRequest.status.in_([ServiceStatus.COMPLETED.value, ServiceStatus.CANCELLED.value])
        ).count()
        
        return jsonify({
            'success': True,
            'stats': {
                'today_sales_count': today_sales_count,
                'today_payments_count': today_payments_count,
                'pending_services': pending_services,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        })
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500

@admin_reports_bp.route("/download-backup", methods=["GET"])
@login_required
def download_backup():
    # ... rest of implementation if exists
    return jsonify({"error": "Not implemented"}), 501

@admin_reports_bp.route("/logs/view", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def view_logs():
    """
    عرض سجلات النظام من الملفات مباشرة
    """
    log_files = ['app.log', 'errors.log', 'access.log', 'worker.log']
    logs_data = {}
    
    base_dir = current_app.root_path
    # Assuming logs are in a 'logs' directory next to app or in root
    logs_dir = os.path.join(os.path.dirname(base_dir), 'logs')
    if not os.path.exists(logs_dir):
        # Fallback to current directory if not found
        logs_dir = base_dir

    for log_file in log_files:
        file_path = os.path.join(logs_dir, log_file)
        if os.path.exists(file_path):
            try:
                # Read last 100 lines
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    # Efficiently read last N lines
                    lines = f.readlines()[-200:]
                    logs_data[log_file] = "".join(lines)
            except Exception as e:
                current_app.logger.exception('Error reading log file')
                logs_data[log_file] = "Error reading log file"
        else:
            logs_data[log_file] = f"File not found: {log_file}"

    return render_template("admin/logs.html", logs=logs_data)
