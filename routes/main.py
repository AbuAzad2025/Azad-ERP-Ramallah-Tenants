
from __future__ import annotations
import os
from datetime import date, datetime, timedelta, time, timezone
from decimal import Decimal
from typing import List, Tuple

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, send_file, send_from_directory, url_for, request
from flask_login import current_user, login_required
from sqlalchemy import func, case, and_
from sqlalchemy.orm import load_only, joinedload
from werkzeug.utils import secure_filename

from extensions import db, cache
from forms import RestoreForm
from models import (
    Check,
    CheckStatus,
    Customer,
    ExchangeTransaction,
    Expense,
    Invoice,
    Note,
    Payment,
    PaymentDirection,
    PaymentStatus,
    Product,
    Sale,
    SaleStatus,
    ServiceRequest,
    Supplier,
    Partner,
    StockLevel,
)
from models import convert_amount, fx_rate
import utils
from reports import sales_report, ar_aging_report
from permissions_config.enums import SystemPermissions

main_bp = Blueprint("main", __name__, template_folder="templates")

@main_bp.route("/favicon.ico")
def favicon():
    return send_from_directory(current_app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")

@main_bp.route("/login", methods=["GET"], endpoint="login_alias")
def login_alias():
    nxt = request.args.get("next")
    if nxt:
        return redirect(url_for("auth.login", next=nxt))
    return redirect(url_for("auth.login"))

@main_bp.route("/", methods=["GET"], endpoint="dashboard")
@login_required
def dashboard():
    try:
        db.session.rollback()
    except Exception:
        pass
    today = date.today()
    start = today - timedelta(days=6)
    end = today

    day_start_dt = datetime.combine(today, time.min)
    day_end_dt = datetime.combine(today + timedelta(days=1), time.min)
    week_start_dt = datetime.combine(start, time.min)
    week_end_dt = datetime.combine(end + timedelta(days=1), time.min)

    perms_set: set[str] = set()
    try:
        fn = getattr(utils, "_get_user_permissions", None)
        if callable(fn):
            perms_set = fn(current_user) or set()
        perms_set = {str(p).strip().lower() for p in (perms_set or set()) if str(p).strip()}
    except Exception:
        perms_set = set()

    def _has_perm(code: str) -> bool:
        if not code:
            return False
        try:
            if utils.is_super():
                return True
        except Exception:
            current_app.logger.debug('operation failed in main.py', exc_info=True)
        try:
            targets = utils._expand_perms(code)
        except Exception:
            targets = {str(code).strip().lower()}
        try:
            targets = {str(t).strip().lower() for t in (targets or set()) if str(t).strip()}
        except Exception:
            targets = {str(code).strip().lower()}
        return bool(perms_set & targets)

    cache_key_inv = 'dashboard_inventory_stats'
    inv_stats = cache.get(cache_key_inv)
    if inv_stats is None:
        subq = (
            db.session.query(
                Product.id.label("pid"),
                func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"),
                func.coalesce(Product.min_qty, 0).label("min_qty"),
            )
            .outerjoin(StockLevel, StockLevel.product_id == Product.id)
            .filter(Product.is_active.is_(True))
            .group_by(Product.id, Product.min_qty)
            .subquery()
        )
        inventory_total = int(db.session.query(func.coalesce(func.sum(subq.c.qty), 0)).scalar() or 0)
        low_stock_count = int(
            db.session.query(func.count())
            .select_from(subq)
            .filter(subq.c.qty <= subq.c.min_qty)
            .scalar()
            or 0
        )
        inv_stats = {'inventory_total': inventory_total, 'low_stock_count': low_stock_count}
        cache.set(cache_key_inv, inv_stats, timeout=300)

    inventory_total = int((inv_stats or {}).get("inventory_total") or 0)
    low_stock_count = int((inv_stats or {}).get("low_stock_count") or 0)
    low_stock: list = []

    cache_key_exch = 'dashboard_exchanges'
    pending_exchanges = cache.get(cache_key_exch)
    if pending_exchanges is None:
        pending_exchanges = ExchangeTransaction.query.filter_by(direction="OUT").count()
        cache.set(cache_key_exch, pending_exchanges, timeout=180)
    
    cache_key_partner = 'dashboard_partner_stock'
    partner_stock = cache.get(cache_key_partner)
    if partner_stock is None:
        partner_stock = (db.session.query(func.count(Product.id)).join(Supplier, Supplier.id == Product.supplier_local_id).scalar() or 0)
        cache.set(cache_key_partner, partner_stock, timeout=300)

    recent_sales = []
    today_sales_rows: List[Tuple] = []
    today_revenue = Decimal('0.00')
    revenue_labels = []
    revenue_values = []
    week_revenue = 0.0

    # حساب الوارد والصادر - يشمل المبيعات + الدفعات
    fx_cache: dict[tuple[str, date | None], Decimal] = {}

    def _to_ils(amount, currency, fx_used, at_dt) -> Decimal:
        value = Decimal(str(amount or 0))
        code = (currency or "ILS").upper()
        if code == "ILS":
            return value
        if fx_used:
            try:
                return value * Decimal(str(fx_used))
            except Exception:
                current_app.logger.debug('numeric conversion failed in main.py', exc_info=True)
        try:
            key = (code, at_dt.date() if isinstance(at_dt, datetime) else None)
            rate = fx_cache.get(key)
            if rate is None:
                rate = fx_rate(code, "ILS", at_dt, raise_on_missing=False)
                if rate and rate > 0:
                    fx_cache[key] = Decimal(str(rate))
                else:
                    rate = None
            if rate and rate > 0:
                return value * Decimal(str(rate))
        except Exception:
            current_app.logger.warning('cache operation failed silently in main.py', exc_info=True)
        try:
            return convert_amount(value, code, "ILS", at_dt)
        except Exception:
            return value

    if _has_perm(SystemPermissions.MANAGE_SALES):
        cache_key_recent = f'dashboard_recent_sales_{today}'
        recent_sales = cache.get(cache_key_recent)
        if recent_sales is None:
            recent_sales = (
                Sale.query.options(
                    load_only(
                        Sale.id,
                        Sale.sale_number,
                        Sale.sale_date,
                        Sale.total_amount,
                        Sale.currency,
                        Sale.customer_id,
                        Sale.status,
                        Sale.payment_status,
                    ),
                    joinedload(Sale.customer).load_only(Customer.name),
                )
                .order_by(Sale.sale_date.desc())
                .limit(5)
                .all()
            )
            cache.set(cache_key_recent, recent_sales, timeout=180)
        
        cache_key_srep = f'dashboard_sales_report_{start}_{end}'
        srep = cache.get(cache_key_srep)
        if srep is None:
            try:
                srep = sales_report(start, end) or {}
            except Exception:
                current_app.logger.warning('sales_report failed in dashboard', exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
                srep = {}
            cache.set(cache_key_srep, srep, timeout=300)
        else:
            srep = srep or {}
        
        revenue_labels = srep.get("daily_labels", [])
        revenue_values = srep.get("daily_values", [])
        week_revenue = float(srep.get("total_revenue", 0) or 0)
        
        cache_key_today_rev = f'dashboard_today_revenue_{today}'
        today_revenue = cache.get(cache_key_today_rev)
        if today_revenue is None:
            today_revenue = Decimal('0.00')
            today_sales_rows = (
                db.session.query(
                    Sale.total_amount,
                    Sale.currency,
                    Sale.fx_rate_used,
                    Sale.sale_date,
                )
                .filter(
                    Sale.status == SaleStatus.CONFIRMED.value,
                    Sale.sale_date >= day_start_dt,
                    Sale.sale_date < day_end_dt,
                )
                .all()
            )

            for amt, currency, fx_used, sale_dt in today_sales_rows:
                today_revenue += _to_ils(amt, currency, fx_used, sale_dt)
            
            cache.set(cache_key_today_rev, float(today_revenue), timeout=300)
        else:
            today_revenue = Decimal(str(today_revenue))

    def _sum_entity_balance(model):
        total = Decimal('0.00')
        try:
            cache_key = f"dashboard_balance_{model.__tablename__}"
            cached_total = cache.get(cache_key)
            if cached_total is not None:
                return float(cached_total)
            
            if model.__name__ == 'Customer':
                try:
                    result = db.session.query(func.coalesce(func.sum(Customer.current_balance), 0)).scalar() or 0.0
                    cache.set(cache_key, float(result), timeout=300)
                    return float(result)
                except Exception:
                    current_app.logger.warning('cache operation failed silently in main.py', exc_info=True)
            
            if model.__name__ == 'Supplier':
                try:
                    result = db.session.query(func.coalesce(func.sum(Supplier.current_balance), 0)).scalar() or 0.0
                    cache.set(cache_key, float(result), timeout=300)
                    return float(result)
                except Exception:
                    current_app.logger.warning('cache operation failed silently in main.py', exc_info=True)
            
            try:
                balance_attr = getattr(model, 'balance', None)
                if balance_attr and hasattr(balance_attr, 'expression'):
                    result = db.session.query(func.coalesce(func.sum(balance_attr), 0)).scalar() or 0.0
                    cache.set(cache_key, float(result), timeout=300)
                    return float(result)
            except Exception:
                current_app.logger.warning('cache operation failed silently in main.py', exc_info=True)
            
            entities = model.query.options(load_only(model.id)).limit(10000).all()
            for entity in entities:
                try:
                    if model.__name__ == 'Supplier':
                        db.session.refresh(entity)
                    balance_val = getattr(entity, "balance", 0) or 0
                    if hasattr(balance_val, '__float__'):
                        total += Decimal(str(float(balance_val)))
                    else:
                        total += Decimal(str(balance_val))
                except Exception:
                    continue
            
            result = float(total)
            cache.set(cache_key, result, timeout=300)
            return result
        except Exception as exc:
            current_app.logger.warning(f"Dashboard balance aggregation failed for {model.__tablename__}: {exc}")
            return 0.0

    def _sum_partner_smart_balance():
        return _sum_entity_balance(Partner)

    total_customer_balance = _sum_entity_balance(Customer)
    total_supplier_balance = _sum_entity_balance(Supplier)
    total_partner_balance = _sum_partner_smart_balance()

    def _aggregate_payments(start_dt, end_dt):
        cache_key_pay = f'dashboard_payments_{start_dt.date()}_{end_dt.date()}'
        cached = cache.get(cache_key_pay)
        if cached is not None:
            return cached['incoming'], cached['outgoing']
        
        incoming = Decimal('0.00')
        outgoing = Decimal('0.00')
        payments = (
            db.session.query(
                Payment.total_amount,
                Payment.currency,
                Payment.fx_rate_used,
                Payment.payment_date,
                Payment.direction,
            )
            .filter(
                Payment.payment_date >= start_dt,
                Payment.payment_date < end_dt,
                Payment.status == PaymentStatus.COMPLETED.value,
            )
            .all()
        )
        for amount, currency, fx_used, pay_dt, direction in payments:
            amt_ils = _to_ils(amount, currency, fx_used, pay_dt or start_dt)
            if direction == PaymentDirection.IN.value:
                incoming += amt_ils
            else:
                outgoing += amt_ils
        
        expenses_without_payments = (
            db.session.query(
                Expense.amount,
                Expense.currency,
                Expense.date,
            )
            .outerjoin(
                Payment,
                and_(
                    Payment.expense_id == Expense.id,
                    Payment.status == PaymentStatus.COMPLETED.value
                )
            )
            .filter(
                Expense.date >= start_dt,
                Expense.date < end_dt,
                Payment.id.is_(None)
            )
            .all()
        )
        
        for amount, currency, exp_dt in expenses_without_payments:
            amt_ils = _to_ils(amount, currency, None, exp_dt or start_dt)
            outgoing += amt_ils
        
        result = {'incoming': float(incoming), 'outgoing': float(outgoing)}
        cache.set(cache_key_pay, result, timeout=300)
        return result['incoming'], result['outgoing']

    today_incoming, today_outgoing = _aggregate_payments(day_start_dt, day_end_dt)
    week_incoming, week_outgoing = _aggregate_payments(week_start_dt, week_end_dt)
    today_revenue = float(today_revenue)
    today_net = today_incoming - today_outgoing
    week_net = week_incoming - week_outgoing

    cache_key_daily_pay = f'dashboard_daily_payments_{week_start_dt.date()}_{week_end_dt.date()}'
    daily_payments_data = cache.get(cache_key_daily_pay)
    if daily_payments_data is None:
        from collections import defaultdict
        daily_payments = defaultdict(lambda: {'incoming': Decimal('0.00'), 'outgoing': Decimal('0.00')})
        
        all_week_payments = (
            db.session.query(
                Payment.total_amount,
                Payment.currency,
                Payment.fx_rate_used,
                Payment.payment_date,
                Payment.direction,
            )
            .filter(
            Payment.payment_date >= week_start_dt,
            Payment.payment_date < week_end_dt,
            Payment.status == PaymentStatus.COMPLETED.value
            )
            .all()
        )
        
        for amount, currency, fx_used, pay_dt, direction in all_week_payments:
            day_key = pay_dt.date() if pay_dt else today
            amt_ils = _to_ils(amount, currency, fx_used, pay_dt)
            
            if direction == PaymentDirection.IN.value:
                daily_payments[day_key]['incoming'] += amt_ils
            else:
                daily_payments[day_key]['outgoing'] += amt_ils
        
        payments_day_labels = sorted([str(d) for d in daily_payments.keys()])
        payments_in_values = [float(daily_payments[datetime.strptime(d, '%Y-%m-%d').date()]['incoming']) for d in payments_day_labels]
        payments_out_values = [float(daily_payments[datetime.strptime(d, '%Y-%m-%d').date()]['outgoing']) for d in payments_day_labels]
        payments_net_values = [i - o for i, o in zip(payments_in_values, payments_out_values)]
        daily_payments_data = {
            'labels': payments_day_labels,
            'in_values': payments_in_values,
            'out_values': payments_out_values,
            'net_values': payments_net_values
        }
        cache.set(cache_key_daily_pay, daily_payments_data, timeout=300)
    
    payments_day_labels = daily_payments_data['labels']
    payments_in_values = daily_payments_data['in_values']
    payments_out_values = daily_payments_data['out_values']
    payments_net_values = daily_payments_data['net_values']

    month_start_today = today.replace(day=1)
    def _shift_month(base, offset):
        year = base.year + (base.month - 1 + offset) // 12
        month = (base.month - 1 + offset) % 12 + 1
        return date(year, month, 1)
    
    cache_key_monthly = f'dashboard_monthly_sales_{month_start_today}'
    monthly_data = cache.get(cache_key_monthly)
    if monthly_data is None:
        month_keys = []
        monthly_labels = []
        monthly_totals = {}
        for offset in range(-5, 1):
            start_month = _shift_month(month_start_today, offset)
            key = start_month.strftime("%Y-%m")
            month_keys.append(key)
            monthly_labels.append(start_month.strftime("%b %Y"))
            monthly_totals[key] = Decimal('0.00')
        sales_period_start = _shift_month(month_start_today, -5)
        sales_period_end = _shift_month(month_start_today, 1)
        monthly_sales_rows = (
            Sale.query.options(
                load_only(
                    Sale.sale_date,
                    Sale.total_amount,
                    Sale.currency,
                    Sale.fx_rate_used,
                )
            )
            .filter(
                Sale.status == SaleStatus.CONFIRMED.value,
                Sale.sale_date >= datetime.combine(sales_period_start, time.min),
                Sale.sale_date < datetime.combine(sales_period_end, time.min),
            )
            .all()
        )
        for sale in monthly_sales_rows:
            key = sale.sale_date.strftime("%Y-%m")
            if key in monthly_totals:
                monthly_totals[key] += _to_ils(sale.total_amount, sale.currency, sale.fx_rate_used, sale.sale_date)
        monthly_data = {
            'labels': monthly_labels,
            'values': [float(monthly_totals[key]) for key in month_keys]
        }
        cache.set(cache_key_monthly, monthly_data, timeout=3600)
    
    monthly_sales_labels = monthly_data['labels']
    monthly_sales_values = monthly_data['values']
    cache_key_customers = f'dashboard_customers_{today}'
    customer_data = cache.get(cache_key_customers)
    if customer_data is None:
        thirty_days_ago = today - timedelta(days=30)
        ninety_days_ago = today - timedelta(days=90)
        new_count = int(
            db.session.query(func.count(Customer.id))
            .filter(
                Customer.created_at.isnot(None),
                Customer.created_at >= datetime.combine(thirty_days_ago, time.min),
            )
            .scalar()
            or 0
        )
        active_count = int(
            db.session.query(func.count(func.distinct(Sale.customer_id)))
            .filter(
                Sale.customer_id.isnot(None),
                Sale.sale_date >= datetime.combine(ninety_days_ago, time.min),
                Sale.status == SaleStatus.CONFIRMED.value,
            )
            .scalar()
            or 0
        )
        active_new_count = int(
            db.session.query(func.count(func.distinct(Sale.customer_id)))
            .join(Customer, Customer.id == Sale.customer_id)
            .filter(
                Sale.customer_id.isnot(None),
                Sale.sale_date >= datetime.combine(ninety_days_ago, time.min),
                Sale.status == SaleStatus.CONFIRMED.value,
                Customer.created_at.isnot(None),
                Customer.created_at >= datetime.combine(thirty_days_ago, time.min),
            )
            .scalar()
            or 0
        )
        total_customers_count = int(db.session.query(func.count(Customer.id)).scalar() or 0)
        active_existing = max(active_count - active_new_count, 0)
        inactive_count = max(total_customers_count - (new_count + active_existing), 0)
        customer_data = {
            'new_count': new_count,
            'active_existing': active_existing,
            'inactive_count': inactive_count
        }
        cache.set(cache_key_customers, customer_data, timeout=1800)
    
    active_existing = customer_data['active_existing']
    inactive_count = customer_data['inactive_count']
    customer_segment_labels = ["عملاء جدد", "عملاء نشطين", "عملاء غير نشطين"]
    customer_segment_values = [
        customer_data['new_count'],
        active_existing,
        inactive_count,
    ]
    dashboard_alerts: List[dict] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    week_ahead = today + timedelta(days=7)

    cache_key_checks = f'dashboard_checks_{today}'
    checks_alerts = cache.get(cache_key_checks)
    if checks_alerts is None:
        checks_alerts = []
        try:
            overdue_filter = (
                Check.is_archived.is_(False),
                Check.status == CheckStatus.PENDING.value,
                Check.check_due_date < now,
            )
            upcoming_filter = (
                Check.is_archived.is_(False),
                Check.status == CheckStatus.PENDING.value,
                Check.check_due_date.between(now, datetime.combine(week_ahead, datetime.max.time())),
            )

            def _sum_ils_amount(base_filter):
                rate = func.coalesce(Check.fx_rate_issue, 0)
                amount_ils = case(
                    (func.upper(func.coalesce(Check.currency, 'ILS')) == 'ILS', func.coalesce(Check.amount, 0)),
                    else_=func.coalesce(Check.amount, 0) * rate,
                )
                return float(db.session.query(func.coalesce(func.sum(amount_ils), 0)).filter(*base_filter).scalar() or 0)

            overdue_count = int(db.session.query(func.count(Check.id)).filter(*overdue_filter).scalar() or 0)
            upcoming_count = int(db.session.query(func.count(Check.id)).filter(*upcoming_filter).scalar() or 0)
            overdue_amount = _sum_ils_amount(overdue_filter)
            upcoming_amount = _sum_ils_amount(upcoming_filter)

            overdue_min_due = db.session.query(func.min(Check.check_due_date)).filter(*overdue_filter).scalar()
            upcoming_min_due = db.session.query(func.min(Check.check_due_date)).filter(*upcoming_filter).scalar()

            if overdue_count:
                checks_alerts.append({
                    "category": "الشيكات",
                    "severity": "danger",
                    "icon": "fas fa-money-check-alt",
                    "title": "شيكات متأخرة تحتاج إجراء",
                    "message": f"عدد الشيكات المتأخرة: {overdue_count}",
                    "amount_display": f"{float(overdue_amount):,.2f} ₪",
                    "link": url_for('checks.index'),
                    "meta": overdue_min_due.strftime('%Y-%m-%d') if overdue_min_due else None,
                })

            if upcoming_count:
                checks_alerts.append({
                    "category": "الشيكات",
                    "severity": "warning",
                    "icon": "fas fa-calendar-check",
                    "title": "شيكات تستحق قريباً (7 أيام)",
                    "message": f"عدد الشيكات القريبة: {upcoming_count}",
                    "amount_display": f"{float(upcoming_amount):,.2f} ₪",
                    "link": url_for('checks.index'),
                    "meta": upcoming_min_due.strftime('%Y-%m-%d') if upcoming_min_due else None,
                })
        except Exception as exc:
            current_app.logger.warning(f"Dashboard check alerts error: {exc}")
        
        cache.set(cache_key_checks, checks_alerts, timeout=600)
    
    dashboard_alerts.extend(checks_alerts)

    try:
        customer_debts = (
            db.session.query(
                Customer.id,
                Customer.name,
                Customer.balance.label("cust_balance"),
                func.count(Sale.id).label("sale_count"),
                func.max(Sale.sale_date).label("last_sale"),
            )
            .outerjoin(
                Sale,
                and_(
                    Sale.customer_id == Customer.id,
                    Sale.status == SaleStatus.CONFIRMED.value,
                    Sale.balance_due > 0,
                )
            )
            .filter(Customer.balance < 0)
            .group_by(Customer.id, Customer.name, Customer.balance)
            .order_by(Customer.balance.asc())
            .limit(5)
            .all()
        )

        id_list = [row[0] for row in customer_debts]
        customers_map = {}
        if id_list:
            customers_map = {
                c.id: c
                for c in Customer.query.filter(Customer.id.in_(id_list)).all()
            }

        for cust_id, cust_name, cust_balance, sale_count, last_sale in customer_debts:
            balance_value = cust_balance or 0
            cust_obj = customers_map.get(cust_id)
            if cust_obj:
                try:
                    balance_value = cust_obj.balance
                except Exception as exc:
                    current_app.logger.warning(
                        f"⚠️ خطأ في حساب رصيد العميل #{cust_id}: {exc}"
                    )
            if balance_value and balance_value < 0:
                amount_due = abs(float(balance_value))
                dashboard_alerts.append({
                    "category": "الذمم",
                    "severity": "warning",
                    "icon": "fas fa-user-clock",
                    "title": f"دين على العميل {cust_name}",
                    "message": f"عدد الفواتير المفتوحة: {sale_count}",
                    "amount_display": f"{amount_due:,.2f} ₪",
                    "link": url_for('customers_bp.list_customers', name=cust_name),
                    "meta": last_sale.strftime('%Y-%m-%d') if last_sale else None,
                })
    except Exception as exc:
        current_app.logger.warning(f"Dashboard customer debt alerts error: {exc}")

    try:
        recent_expenses = (
            db.session.query(
                Expense.id,
                Expense.description,
                Expense.amount,
                Expense.currency,
                Expense.date,
            )
            .filter(
                Expense.date >= today - timedelta(days=7),
                Expense.amount > 0,
            )
            .order_by(Expense.amount.desc(), Expense.date.desc())
            .limit(5)
            .all()
        )

        expense_threshold = Decimal("5000")
        for exp_id, description, amount, currency, exp_date in recent_expenses:
            amount_ils = _to_ils(amount, currency, None, datetime.combine(exp_date, time.min))
            if amount_ils >= expense_threshold:
                dashboard_alerts.append({
                    "category": "المصاريف",
                    "severity": "info",
                    "icon": "fas fa-wallet",
                    "title": "مصروف مرتفع مسجل",
                    "message": description or f"مصروف رقم {exp_id}",
                    "amount_display": f"{float(amount_ils):,.2f} ₪",
                    "link": url_for('expenses_bp.list_expenses'),
                    "meta": exp_date.strftime('%Y-%m-%d'),
                })
    except Exception as exc:
        current_app.logger.warning(f"Dashboard expense alerts error: {exc}")

    severity_order = {"danger": 0, "warning": 1, "info": 2, "primary": 3}
    dashboard_alerts.sort(key=lambda item: (
        severity_order.get(item.get("severity"), 99),
        0 if item.get("category") == "الشيكات" else 1
    ))
    check_alerts = [a for a in dashboard_alerts if a.get("category") == "الشيكات"]
    general_alerts = [a for a in dashboard_alerts if a.get("category") != "الشيكات"]

    recent_services_count = 0
    if _has_perm(SystemPermissions.MANAGE_SERVICE) or _has_perm(SystemPermissions.VIEW_SERVICE):
        q = ServiceRequest.query
        if not any(_has_perm(c) for c in (SystemPermissions.MANAGE_CUSTOMERS, SystemPermissions.MANAGE_SALES, SystemPermissions.MANAGE_USERS)):
            q = q.filter_by(mechanic_id=current_user.id)
        done_statuses = ("COMPLETED", "CANCELLED", "CLOSED", "DELIVERED", "FINISHED")
        q = q.filter(~ServiceRequest.status.in_(done_statuses))
        recent_services_count = int(q.count() or 0)

    recent_notes = []
    service_metrics = {"day_labels": [], "day_counts": []}
    customer_metrics = {}
    if _has_perm(SystemPermissions.VIEW_REPORTS):
        day_expr = func.date(ServiceRequest.start_time)
        rows = (
            db.session.query(day_expr.label("day"), func.count(ServiceRequest.id).label("cnt"))
            .filter(ServiceRequest.start_time >= week_start_dt, ServiceRequest.start_time < week_end_dt)
            .group_by(day_expr)
            .order_by(day_expr)
            .all()
        )
        service_metrics = {
            "day_labels": [str(r.day) for r in rows],
            "day_counts": [int(r.cnt) for r in rows],
        }
        try:
            customer_metrics = ar_aging_report(start, end)
        except Exception:
            customer_metrics = {}

    return render_template(
        "dashboard.html",
        show_charts=True,
        low_stock=low_stock,
        low_stock_count=low_stock_count,
        inventory_total=inventory_total,
        pending_exchanges=pending_exchanges,
        partner_stock=partner_stock,
        today_revenue=today_revenue,
        revenue_labels=revenue_labels,
        revenue_values=revenue_values,
        week_revenue=week_revenue,
        recent_sales=recent_sales,
        recent_services_count=recent_services_count,
        service_metrics=service_metrics,
        recent_notes=recent_notes,
        customer_metrics=customer_metrics,
        today_incoming=today_incoming,
        today_outgoing=today_outgoing,
        today_net=today_net,
        week_incoming=week_incoming,
        week_outgoing=week_outgoing,
        week_net=week_net,
        total_customer_balance=total_customer_balance,
        total_supplier_balance=total_supplier_balance,
        total_partner_balance=total_partner_balance,
        payments_day_labels=payments_day_labels,
        payments_in_values=payments_in_values,
        payments_out_values=payments_out_values,
        payments_net_values=payments_net_values,
        dashboard_alerts=dashboard_alerts,
        check_alerts=check_alerts,
        general_alerts=general_alerts,
        monthly_sales_labels=monthly_sales_labels,
        monthly_sales_values=monthly_sales_values,
        customer_segment_labels=customer_segment_labels,
        customer_segment_values=customer_segment_values,
    )

@main_bp.route("/backup_db", methods=["GET"], endpoint="backup_db")
@login_required
@utils.permission_required(SystemPermissions.BACKUP_DATABASE)
def backup_db():
    is_prod = (current_app.config.get("ENV") == "production" or current_app.config.get("FLASK_ENV") == "production")
    if is_prod and not utils.is_super():
        flash("❌ غير مسموح بالنسخ الاحتياطي في بيئة الإنتاج إلا للمسؤولين (Super/Owner).", "danger")
        return redirect(url_for("main.dashboard"))

    try:
        from extensions import perform_backup_db
        success, message, filepath = perform_backup_db()
        
        if success and filepath and os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
        else:
            flash(f"❌ {message}", "danger")
            return redirect(url_for("main.dashboard"))
            
    except Exception as e:
        current_app.logger.error(f"Backup error: {e}")
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for("main.dashboard"))

@main_bp.route("/restore_db", methods=["GET", "POST"], endpoint="restore_db")
@login_required
@utils.permission_required(SystemPermissions.RESTORE_DATABASE)
def restore_db():
    is_prod = (current_app.config.get("ENV") == "production" or current_app.config.get("FLASK_ENV") == "production")
    if is_prod and not utils.is_super():
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({"success": False, "message": "غير مسموح بالاستعادة في بيئة الإنتاج إلا للمسؤولين"}), 403
        flash("❌ غير مسموح بالاستعادة في بيئة الإنتاج إلا للمسؤولين (Super/Owner).", "danger")
        return redirect(url_for("main.dashboard"))

    form = RestoreForm()
    if form.validate_on_submit() or (request.method == 'POST' and 'db_file' in request.files):
        try:
            db_file = form.db_file.data if form.validate_on_submit() else request.files.get('db_file')
            if not db_file:
                raise ValueError("لم يتم تحديد ملف")

            tmp_dir = current_app.config.get("IMPORT_TMP_DIR") or os.path.join(current_app.instance_path, "imports")
            os.makedirs(tmp_dir, exist_ok=True)
            safe_name = secure_filename(getattr(db_file, "filename", "") or "") or "restore.dump"
            if not safe_name.lower().endswith(".dump"):
                safe_name += ".dump"
            temp_path = os.path.join(tmp_dir, f"restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_name}")
            db_file.save(temp_path)

            from extensions import restore_database
            ok, msg = restore_database(current_app, temp_path)
            if ok:
                if request.is_json or request.headers.get('Accept') == 'application/json':
                    return jsonify({"success": True, "message": msg}), 200
                flash(f"✅ {msg}", "success")
                return redirect(url_for("main.dashboard"))
            if request.is_json or request.headers.get('Accept') == 'application/json':
                return jsonify({"success": False, "message": msg}), 400
            flash(f"❌ {msg}", "danger")
            return redirect(url_for("main.restore_db"))
        except Exception as e:
            if request.is_json or request.headers.get('Accept') == 'application/json':
                current_app.logger.exception('API error')
                return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
            flash("❌ خطأ أثناء الاستعادة.", "danger")
            return redirect(url_for("main.restore_db"))
    return render_template("restore_db.html", form=form)

@main_bp.route("/automated-backup-status", methods=["GET"], endpoint="automated_backup_status")
@login_required
def automated_backup_status():
    if not utils.is_super():
        return jsonify({"enabled": False, "next_run": None, "schedule": "غير متاح"})

    try:
        from extensions import scheduler
        if not scheduler:
            return jsonify({"enabled": False, "next_run": None, "schedule": "غير مفعّل"})
        jobs = scheduler.get_jobs()
        backup_job = next((job for job in jobs if job.id == 'automated_daily_backup'), None)
        if backup_job:
            return jsonify({
                "enabled": True,
                "next_run": backup_job.next_run_time.isoformat() if backup_job.next_run_time else None,
                "schedule": "يومياً الساعة 3:00 صباحاً"
            })
        return jsonify({
            "enabled": False,
            "next_run": None,
            "schedule": "غير مفعّل"
        })
    except Exception:
        return jsonify({"enabled": False, "next_run": None, "schedule": "غير متاح"})

@main_bp.route("/toggle-automated-backup", methods=["POST"], endpoint="toggle_automated_backup")
@login_required
def toggle_automated_backup():
    if not utils.is_super():
        flash("❌ غير مسموح", "danger")
        return redirect(url_for("main.dashboard"))
    
    from extensions import scheduler
    jobs = scheduler.get_jobs()
    backup_job = next((job for job in jobs if job.id == 'automated_daily_backup'), None)
    
    if backup_job:
        scheduler.remove_job('automated_daily_backup')
        flash("✅ تم تعطيل النسخ الاحتياطي التلقائي", "success")
    else:
        scheduler.add_job(
            func=perform_automated_backup,
            trigger='cron',
            hour=3,
            minute=0,
            id='automated_daily_backup',
            name='النسخ الاحتياطي اليومي التلقائي',
            replace_existing=True
        )
        flash("✅ تم تفعيل النسخ الاحتياطي التلقائي (يومياً الساعة 3:00 صباحاً)", "success")
    
    return redirect(url_for("main.dashboard"))

def perform_automated_backup():
    with current_app.app_context():
        try:
            from extensions import perform_backup_db
            success, message, path = perform_backup_db(current_app)
            
            if success:
                current_app.logger.info(f"✅ Automated backup completed successfully: {path}")
            else:
                current_app.logger.error(f"❌ Automated backup failed: {message}")
            
        except Exception as e:
            current_app.logger.error(f"❌ Automated backup failed: {str(e)}")

def cleanup_old_backups(db_dir, sql_dir, keep_days=7, keep_weekly=4, keep_monthly=12):
    import time
    from pathlib import Path
    
    now = time.time()
    one_day = 86400
    one_week = 604800
    one_month = 2592000
    
    for directory in [db_dir, sql_dir]:
        if not os.path.exists(directory):
            continue
        
        files = []
        for f in Path(directory).glob("auto_backup_*"):
            if f.is_file():
                files.append((f, f.stat().st_mtime))
        
        files.sort(key=lambda x: x[1], reverse=True)
        
        daily_backups = []
        weekly_backups = []
        monthly_backups = []
        
        for filepath, mtime in files:
            age_days = (now - mtime) / one_day
            
            if age_days <= keep_days:
                daily_backups.append(filepath)
            elif age_days <= keep_days + (keep_weekly * 7):
                if len(weekly_backups) < keep_weekly:
                    weekly_backups.append(filepath)
                else:
                    try:
                        filepath.unlink()
                    except Exception:
                        current_app.logger.debug('file operation failed in main.py', exc_info=True)
            elif age_days <= keep_days + (keep_weekly * 7) + (keep_monthly * 30):
                if len(monthly_backups) < keep_monthly:
                    monthly_backups.append(filepath)
                else:
                    try:
                        filepath.unlink()
                    except Exception:
                        current_app.logger.debug('file operation failed in main.py', exc_info=True)
            else:
                try:
                    filepath.unlink()
                except Exception:
                    current_app.logger.debug('file operation failed in main.py', exc_info=True)
