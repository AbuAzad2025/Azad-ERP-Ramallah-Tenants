from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta, time as _t, timezone
from decimal import Decimal
from typing import Dict
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, func, desc
from sqlalchemy.orm import joinedload

from extensions import db

from models import (
    Customer, Supplier, Product, Warehouse, SaleLine, Expense, Invoice,
    OnlinePreOrder, Payment, PaymentSplit, PaymentDirection, PaymentStatus,
    Sale, SaleStatus, ServiceRequest, ServiceStatus,
    PreOrder, PreOrderStatus,
)

import utils

def age_bucket(days) -> str:
    try:
        d = int(days)
    except Exception:
        d = 0
    d = max(d, 0)
    if d <= 30:
        return "0-30"
    if d <= 60:
        return "31-60"
    if d <= 90:
        return "61-90"
    return "90+"

def _parse_date_like(d):
    if not d:
        return None
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return date.fromisoformat(d)
        except Exception:
            return None
    return None

def _allowed_columns(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def customer_balance_report_ils(customer_ids: list = None) -> Dict:
    """تقرير أرصدة الزبائن بالشيكل"""
    try:
        import utils
        
        if customer_ids is None:
            customers = db.session.query(Customer).all()
            customer_ids = [c.id for c in customers]
        
        report_data = []
        total_balance_ils = Decimal("0.00")
        
        for customer_id in customer_ids:
            customer = db.session.get(Customer, customer_id)
            if not customer:
                continue
            
            balance_ils = utils.get_entity_balance_in_ils("CUSTOMER", customer_id)
            
            report_data.append({
                'customer_id': customer_id,
                'customer_name': customer.name,
                'customer_currency': customer.currency,
                'balance_ils': balance_ils,
                'formatted_balance': utils.format_currency_in_ils(balance_ils),
                'credit_limit': customer.credit_limit,
                'credit_status': customer.credit_status
            })
            
            total_balance_ils += balance_ils
        
        return {
            'report_type': 'customer_balance_report_ils',
            'base_currency': 'ILS',
            'total_customers': len(customer_ids),
            'total_balance_ils': total_balance_ils,
            'formatted_total': utils.format_currency_in_ils(total_balance_ils),
            'customers': report_data,
            'generated_at': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'error': str(e),
            'generated_at': datetime.now(timezone.utc)
        }


def supplier_balance_report_ils(supplier_ids: list = None) -> Dict:
    """تقرير أرصدة الموردين بالشيكل"""
    try:
        import utils
        
        if supplier_ids is None:
            suppliers = db.session.query(Supplier).all()
            supplier_ids = [s.id for s in suppliers]
        
        report_data = []
        total_balance_ils = Decimal("0.00")
        
        for supplier_id in supplier_ids:
            supplier = db.session.get(Supplier, supplier_id)
            if not supplier:
                continue
            
            balance_ils = utils.get_entity_balance_in_ils("SUPPLIER", supplier_id)
            
            report_data.append({
                'supplier_id': supplier_id,
                'supplier_name': supplier.name,
                'supplier_currency': supplier.currency,
                'balance_ils': balance_ils,
                'formatted_balance': utils.format_currency_in_ils(balance_ils),
                'is_local': supplier.is_local
            })
            
            total_balance_ils += balance_ils
        
        return {
            'report_type': 'supplier_balance_report_ils',
            'base_currency': 'ILS',
            'total_suppliers': len(supplier_ids),
            'total_balance_ils': total_balance_ils,
            'formatted_total': utils.format_currency_in_ils(total_balance_ils),
            'suppliers': report_data,
            'generated_at': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'error': str(e),
            'generated_at': datetime.now(timezone.utc)
        }


def payment_summary_report_ils(start_date: date = None, end_date: date = None) -> Dict:
    """تقرير ملخص المدفوعات بالشيكل"""
    try:
        import utils
        from models import convert_amount
        
        if start_date is None:
            start_date = date.min
        if end_date is None:
            end_date = date.today()
        
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        
        payments = db.session.query(Payment).filter(
            and_(
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.payment_date.between(start_dt, end_dt)
            )
        ).all()
        
        total_incoming_ils = Decimal("0.00")
        total_outgoing_ils = Decimal("0.00")
        currency_breakdown = {}
        method_breakdown = {}  # تجميع حسب طريقة الدفع
        
        for payment in payments:
            amount = Decimal(str(payment.total_amount or 0))
            currency = payment.currency or "ILS"
            direction = payment.direction
            method = payment.method or "UNKNOWN"  # طريقة الدفع
            
            # تحويل للشيكل
            if currency == "ILS":
                amount_ils = amount
            else:
                try:
                    amount_ils = convert_amount(amount, currency, "ILS", payment.payment_date)
                except Exception as e:
                    # تسجيل الخطأ وتجاهل المبلغ من التحليل
                    try:
                        from flask import current_app
                        current_app.logger.error(f"❌ خطأ في تحويل العملة في تقرير الدفعات للدفعة #{payment.id}: {str(e)}")
                    except Exception:
                        pass
                    continue
            
            # إضافة للتحليل
            if direction == PaymentDirection.IN.value:
                total_incoming_ils += amount_ils
            else:
                total_outgoing_ils += amount_ils
            
            # تفصيل العملة
            if currency not in currency_breakdown:
                currency_breakdown[currency] = {
                    'total_incoming': Decimal("0.00"),
                    'total_outgoing': Decimal("0.00"),
                    'net_balance': Decimal("0.00"),
                    'converted_to_ils': Decimal("0.00")
                }
            
            if direction == PaymentDirection.IN.value:
                currency_breakdown[currency]['total_incoming'] += amount
            else:
                currency_breakdown[currency]['total_outgoing'] += amount
            
            currency_breakdown[currency]['net_balance'] = (
                currency_breakdown[currency]['total_incoming'] - 
                currency_breakdown[currency]['total_outgoing']
            )
            currency_breakdown[currency]['converted_to_ils'] += amount_ils
            
            # تجميع حسب طريقة الدفع
            if method not in method_breakdown:
                method_breakdown[method] = Decimal("0.00")
            method_breakdown[method] += amount_ils
        
        net_balance_ils = total_incoming_ils - total_outgoing_ils
        
        # تحويل method_breakdown إلى lists للقالب
        methods = list(method_breakdown.keys())
        totals_by_method = [float(method_breakdown[m]) for m in methods]
        
        return {
            'report_type': 'payment_summary_report_ils',
            'base_currency': 'ILS',
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'totals': {
                'total_incoming_ils': total_incoming_ils,
                'total_outgoing_ils': total_outgoing_ils,
                'net_balance_ils': net_balance_ils,
                'formatted_incoming': utils.format_currency_in_ils(total_incoming_ils),
                'formatted_outgoing': utils.format_currency_in_ils(total_outgoing_ils),
                'formatted_net': utils.format_currency_in_ils(net_balance_ils)
            },
            'currency_breakdown': currency_breakdown,
            'methods': methods,
            'totals_by_method': totals_by_method,
            'total_payments': len(payments),
            'generated_at': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'error': str(e),
            'generated_at': datetime.now(timezone.utc)
        }

def advanced_report(
    model,
    joins=None,
    date_field=None,
    start_date: date | None = None,
    end_date: date | None = None,
    filters=None,
    like_filters=None,
    columns=None,
    group_by=None,
    aggregates=None,
):
    q = model.query
    if joins:
        for rel in joins:
            q = q.options(joinedload(rel))
    sd = _parse_date_like(start_date)
    ed = _parse_date_like(end_date)
    if date_field and (sd or ed):
        fld = getattr(model, date_field, None)
        if fld is None:
            raise ValueError(f"Invalid date field: {date_field}")
        if sd and ed:
            sd_dt = datetime.combine(sd, datetime.min.time())
            ed_dt = datetime.combine(ed, datetime.max.time())
            q = q.filter(fld.between(sd_dt, ed_dt))
        elif sd:
            sd_dt = datetime.combine(sd, datetime.min.time())
            q = q.filter(fld >= sd_dt)
        else:
            ed_dt = datetime.combine(ed, datetime.max.time())
            q = q.filter(fld <= ed_dt)
    allowed = _allowed_columns(model)
    if filters:
        for k, v in filters.items():
            if k not in allowed:
                continue
            fld = getattr(model, k, None)
            if fld is not None:
                if hasattr(v, "__iter__") and not isinstance(v, str):
                    q = q.filter(fld.in_(v))
                else:
                    q = q.filter(fld == v)
    if like_filters:
        for k, pat in like_filters.items():
            if k not in allowed:
                continue
            fld = getattr(model, k, None)
            if fld is not None and pat not in (None, ""):
                q = q.filter(fld.ilike(f"%{pat}%"))
    if group_by:
        gb_names = [f for f in group_by if f in allowed]
        gb = [getattr(model, f) for f in gb_names]
        if gb:
            q = q.group_by(*gb)
    if columns:
        cols = [c for c in columns if c in allowed]
    else:
        cols = list(allowed)
    objs = q.all()
    data = [{col: getattr(obj, col, None) for col in cols} for obj in objs]
    summary: Dict[str, float] = {}
    if aggregates:
        for func_name, fields in aggregates.items():
            agg_func = getattr(func, func_name, None)
            if not agg_func:
                continue
            for f in fields:
                if f not in allowed:
                    continue
                fld = getattr(model, f, None)
                if fld is None:
                    continue
                val = q.with_entities(agg_func(fld)).scalar()
                summary[f"{func_name}_{f}"] = float(val or 0)
    return {"data": data, "summary": summary}

def sales_report_ils(start_date: date | None, end_date: date | None, tz_name: str = "Asia/Hebron") -> dict:
    """تقرير المبيعات مع تحويل العملات للشيكل"""
    try:
        import utils
        from models import convert_amount
        
        TZ = ZoneInfo(tz_name)
        sd = _parse_date_like(start_date)
        ed = _parse_date_like(end_date)
        if sd and ed and ed < sd:
            sd, ed = ed, sd
        
        # الحصول على المبيعات في الفترة
        filters = []
        if sd:
            start_dt_local = datetime.combine(sd, _t.min).replace(tzinfo=TZ)
            filters.append(Sale.sale_date >= start_dt_local.replace(tzinfo=None))
        if ed:
            try:
                ed_plus1 = ed + timedelta(days=1)
                end_dt_local = datetime.combine(ed_plus1, _t.min).replace(tzinfo=TZ)
            except OverflowError:
                end_dt_local = datetime.combine(ed, _t.max).replace(tzinfo=TZ)
            filters.append(Sale.sale_date < end_dt_local.replace(tzinfo=None))
        
        allowed_statuses = (SaleStatus.CONFIRMED.value,)
        excluded_statuses = (SaleStatus.CANCELLED.value, SaleStatus.REFUNDED.value)
        
        sales = db.session.query(Sale).filter(*filters).filter(
            Sale.status.in_(allowed_statuses)
        ).filter(~Sale.status.in_(excluded_statuses)).all()
        
        total_revenue_ils = Decimal("0.00")
        currency_breakdown = {}
        daily_revenue = {}
        
        for sale in sales:
            amount = Decimal(str(sale.total_amount or 0))
            currency = sale.currency or "ILS"
            sale_date = sale.sale_date.date()
            
            # تحويل للشيكل
            if currency == "ILS":
                amount_ils = amount
            else:
                try:
                    amount_ils = convert_amount(amount, currency, "ILS", sale.sale_date)
                except Exception as e:
                    # تسجيل الخطأ وتجاهل المبلغ من التحليل
                    try:
                        from flask import current_app
                        current_app.logger.error(f"❌ خطأ في تحويل العملة في تقرير المبيعات للبيع #{sale.id}: {str(e)}")
                    except Exception:
                        pass
                    continue
            
            total_revenue_ils += amount_ils
            
            # تجميع حسب العملة
            if currency not in currency_breakdown:
                currency_breakdown[currency] = {
                    'total_original': Decimal("0.00"),
                    'total_ils': Decimal("0.00"),
                    'count': 0
                }
            currency_breakdown[currency]['total_original'] += amount
            currency_breakdown[currency]['total_ils'] += amount_ils
            currency_breakdown[currency]['count'] += 1
            
            # تجميع يومي
            date_key = sale_date.isoformat()
            if date_key not in daily_revenue:
                daily_revenue[date_key] = Decimal("0.00")
            daily_revenue[date_key] += amount_ils
        
        return {
            'report_type': 'sales_report_ils',
            'base_currency': 'ILS',
            'period': {
                'start_date': sd,
                'end_date': ed
            },
            'totals': {
                'total_revenue_ils': total_revenue_ils,
                'formatted_total': utils.format_currency_in_ils(total_revenue_ils),
                'total_sales': len(sales)
            },
            'currency_breakdown': currency_breakdown,
            'daily_revenue': daily_revenue,
            'generated_at': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'error': str(e),
            'generated_at': datetime.now(timezone.utc)
        }

def sales_report(start_date: date | None, end_date: date | None, tz_name: str = "Asia/Hebron") -> dict:
    TZ = ZoneInfo(tz_name)
    sd = _parse_date_like(start_date)
    ed = _parse_date_like(end_date)
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    engine = db.engine.name
    if engine == "postgresql":
        day_expr = func.to_char(func.timezone(tz_name, Sale.sale_date), "YYYY-MM-DD")
    elif engine in ("mysql", "mariadb"):
        day_expr = func.date_format(Sale.sale_date, "%Y-%m-%d")
    else:
        day_expr = func.strftime("%Y-%m-%d", Sale.sale_date)
    filters = []
    if sd:
        start_dt_local = datetime.combine(sd, _t.min).replace(tzinfo=TZ)
        if engine == "postgresql":
            filters.append(Sale.sale_date >= start_dt_local.astimezone(ZoneInfo("UTC")))
        else:
            filters.append(Sale.sale_date >= start_dt_local.replace(tzinfo=None))
    if ed:
        try:
            ed_plus1 = ed + timedelta(days=1)
            end_dt_local = datetime.combine(ed_plus1, _t.min).replace(tzinfo=TZ)
        except OverflowError:
            end_dt_local = datetime.combine(ed, _t.max).replace(tzinfo=TZ)
        if engine == "postgresql":
            filters.append(Sale.sale_date < end_dt_local.astimezone(ZoneInfo("UTC")))
        else:
            filters.append(Sale.sale_date < end_dt_local.replace(tzinfo=None))
    allowed_statuses = (SaleStatus.CONFIRMED.value,)
    excluded_statuses = (SaleStatus.CANCELLED.value, SaleStatus.REFUNDED.value)
    
    # جلب كل المبيعات مع تحويل العملات
    from models import convert_amount
    
    sales = Sale.query.filter(*filters).filter(
        Sale.status.in_(allowed_statuses),
        ~Sale.status.in_(excluded_statuses)
    ).limit(50000).all()
    
    day_to_sum: dict[str, Decimal] = {}
    for sale in sales:
        amt = Decimal(str(sale.total_amount or 0))
        
        if sale.currency == "ILS":
            amt_ils = amt
        else:
            try:
                amt_ils = convert_amount(amt, sale.currency, "ILS", sale.sale_date)
            except Exception:
                amt_ils = Decimal('0.00')
        
        # تحديد اليوم
        if sale.sale_date:
            day_key = sale.sale_date.date().isoformat() if hasattr(sale.sale_date, 'date') else str(sale.sale_date)
        else:
            day_key = datetime.now().date().isoformat()
        
        if day_key not in day_to_sum:
            day_to_sum[day_key] = Decimal('0.00')
        day_to_sum[day_key] += amt_ils
    
    total = sum(day_to_sum.values(), Decimal("0"))
    labels: list[str] = []
    values: list[float] = []
    if sd and ed:
        cur = sd
        while cur <= ed:
            k = cur.isoformat()
            labels.append(k)
            values.append(float(day_to_sum.get(k, Decimal("0"))))
            cur += timedelta(days=1)
    else:
        for k in sorted(day_to_sum.keys()):
            labels.append(k)
            values.append(float(day_to_sum[k]))
    return {"daily_labels": labels, "daily_values": values, "total_revenue": float(total)}

def expense_report(start_date: date | None, end_date: date | None):
    return advanced_report(
        model=Expense,
        date_field="date",
        start_date=start_date,
        end_date=end_date,
        aggregates={"sum": ["amount"], "count": ["id"]},
    )

def shop_report(start_date: date | None, end_date: date | None):
    return advanced_report(
        model=OnlinePreOrder,
        date_field="created_at",
        start_date=start_date,
        end_date=end_date,
        aggregates={"sum": ["prepaid_amount", "total_amount"], "count": ["id"]},
    )

def payment_summary_report(start_date, end_date):
    """تقرير ملخص المدفوعات مع تحويل العملات"""
    from models import convert_amount
    from collections import defaultdict
    
    sd = _parse_date_like(start_date) or date.min
    ed = _parse_date_like(end_date) or date.max
    if ed < sd:
        sd, ed = ed, sd
    
    sd_dt = datetime.combine(sd, datetime.min.time())
    ed_dt = datetime.combine(ed, datetime.max.time())
    
    base_filters = [
        Payment.status == PaymentStatus.COMPLETED.value,
        Payment.direction == PaymentDirection.IN.value,
        Payment.payment_date.between(sd_dt, ed_dt),
    ]
    
    # جلب الدفعات مع Splits
    payments_with_splits = (
        db.session.query(Payment, PaymentSplit)
        .join(PaymentSplit, PaymentSplit.payment_id == Payment.id)
        .filter(*base_filters)
        .all()
    )
    
    # جلب الدفعات بدون Splits
    payments_no_splits = (
        db.session.query(Payment)
        .outerjoin(PaymentSplit, PaymentSplit.payment_id == Payment.id)
        .filter(*base_filters)
        .filter(PaymentSplit.id.is_(None))
        .all()
    )
    
    agg = defaultdict(lambda: Decimal('0.00'))
    
    # معالجة الدفعات مع Splits
    for payment, split in payments_with_splits:
        method = str(split.method) if split.method else "other"
        amt = Decimal(str(split.amount or 0))
        
        if payment.currency == "ILS":
            amt_ils = amt
        else:
            try:
                amt_ils = convert_amount(amt, payment.currency, "ILS", payment.payment_date)
            except Exception:
                amt_ils = Decimal('0.00')
        
        agg[method] += amt_ils
    
    # معالجة الدفعات بدون Splits
    for payment in payments_no_splits:
        method = str(payment.method) if payment.method else "other"
        amt = Decimal(str(payment.total_amount or 0))
        
        if payment.currency == "ILS":
            amt_ils = amt
        else:
            try:
                amt_ils = convert_amount(amt, payment.currency, "ILS", payment.payment_date)
            except Exception:
                amt_ils = Decimal('0.00')
        
        agg[method] += amt_ils
    
    # تحويل للصيغة النهائية
    methods = sorted(agg.keys())
    totals = [round(float(agg[m]), 2) for m in methods]
    grand_total = round(sum(totals), 2)
    return {"methods": methods, "totals": totals, "grand_total": grand_total}

def service_reports_report(
    start_date: date | None,
    end_date: date | None,
    status: str | None = None,
    mechanic_id: int | None = None,
    customer_id: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    export: bool = False,
    export_limit: int = 20000,
) -> dict:
    start_date = _parse_date_like(start_date) or date.min
    end_date = _parse_date_like(end_date) or date.max
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    from datetime import datetime as dt
    start_dt = dt.combine(start_date, dt.min.time())
    end_dt = dt.combine(end_date, dt.max.time())

    filters = [ServiceRequest.received_at.between(start_dt, end_dt)]
    if status:
        filters.append(ServiceRequest.status == status)
    if mechanic_id:
        filters.append(ServiceRequest.mechanic_id == mechanic_id)
    if customer_id:
        filters.append(ServiceRequest.customer_id == customer_id)

    from sqlalchemy import case

    status_up = func.upper(func.coalesce(ServiceRequest.status, ""))
    fx_mult = case(
        (func.upper(func.coalesce(ServiceRequest.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(ServiceRequest.fx_rate_used, 1),
    )
    total_ils_expr = func.coalesce(ServiceRequest.total_amount, 0) * fx_mult
    parts_ils_expr = func.coalesce(ServiceRequest.parts_total, 0) * fx_mult
    labor_ils_expr = func.coalesce(ServiceRequest.labor_total, 0) * fx_mult

    base_q = ServiceRequest.query.filter(*filters)
    agg = base_q.with_entities(
        func.count(ServiceRequest.id).label("total"),
        func.coalesce(func.sum(case((status_up == ServiceStatus.COMPLETED.value, 1), else_=0)), 0).label("completed"),
        func.coalesce(func.sum(total_ils_expr), 0).label("revenue"),
        func.coalesce(func.sum(parts_ils_expr), 0).label("parts"),
        func.coalesce(func.sum(labor_ils_expr), 0).label("labor"),
    ).first()

    total = int(getattr(agg, "total", 0) or 0)
    completed = int(getattr(agg, "completed", 0) or 0)
    revenue = float(getattr(agg, "revenue", 0) or 0)
    parts = float(getattr(agg, "parts", 0) or 0)
    labor = float(getattr(agg, "labor", 0) or 0)

    rows_q = (
        base_q.with_entities(
            ServiceRequest.service_number.label("number"),
            ServiceRequest.status.label("status"),
            ServiceRequest.priority.label("priority"),
            ServiceRequest.received_at.label("received_at"),
            ServiceRequest.customer_id.label("customer_id"),
            ServiceRequest.mechanic_id.label("mechanic_id"),
            func.coalesce(ServiceRequest.total_amount, 0).label("total"),
            func.coalesce(ServiceRequest.currency, "ILS").label("currency"),
            func.coalesce(ServiceRequest.fx_rate_used, None).label("fx_rate_used"),
        )
        .order_by(ServiceRequest.received_at.desc(), ServiceRequest.id.desc())
    )

    pagination = None
    if export:
        rows = rows_q.limit(int(export_limit or 20000)).all()
    else:
        p = int(page or 1)
        pp = int(per_page or 50)
        pp = min(200, max(10, pp))
        pagination = rows_q.paginate(page=p, per_page=pp, error_out=False)
        rows = list(pagination.items or [])

    customer_ids = {r.customer_id for r in rows if getattr(r, "customer_id", None)}
    mechanic_ids = {r.mechanic_id for r in rows if getattr(r, "mechanic_id", None)}

    from models import Customer, User

    customers_map = {}
    if customer_ids:
        customers = db.session.query(Customer.id, Customer.name).filter(Customer.id.in_(customer_ids)).all()
        customers_map = {c.id: c.name for c in customers}

    mechanics_map = {}
    if mechanic_ids:
        mechanics = db.session.query(User.id, User.username).filter(User.id.in_(mechanic_ids)).all()
        mechanics_map = {m.id: m.username for m in mechanics}

    def _row_total_ils(amount, currency, fx_used):
        try:
            if (currency or "ILS").upper() == "ILS":
                return float(amount or 0)
            if fx_used:
                return float(Decimal(str(amount or 0)) * Decimal(str(fx_used)))
        except Exception:
            pass
        return float(amount or 0)

    data = []
    for r in rows:
        rec_at = r.received_at.isoformat() if r.received_at else None
        total_ils = _row_total_ils(r.total, r.currency, r.fx_rate_used)
        data.append(
            {
                "number": r.number,
                "status": getattr(r.status, "value", r.status),
                "priority": getattr(r.priority, "value", r.priority),
                "received_at": rec_at,
                "customer_id": r.customer_id,
                "customer_name": customers_map.get(r.customer_id, "-"),
                "mechanic_id": r.mechanic_id,
                "mechanic_name": mechanics_map.get(r.mechanic_id, "-"),
                "total": float(r.total or 0),
                "total_ils": float(total_ils or 0),
            }
        )

    return {
        "total": total,
        "completed": completed,
        "revenue": revenue,
        "parts": parts,
        "labor": labor,
        "data": data,
        "pagination": pagination,
    }

def ar_aging_report(start_date=None, end_date=None):
    from decimal import Decimal

    as_of = _parse_date_like(end_date) or date.today()
    bucket_keys = ("0-30", "31-60", "61-90", "90+")

    from models import PreOrder

    customers = db.session.query(Customer.id, Customer.name, Customer.current_balance).filter(
        func.coalesce(Customer.current_balance, 0) > 0
    ).all()

    customer_ids = [c.id for c in customers]
    if not customer_ids:
        return {"as_of": as_of.isoformat(), "data": [], "totals": {k: 0.0 for k in bucket_keys} | {"total": 0.0}}

    sales_min = (
        db.session.query(Sale.customer_id, func.min(Sale.sale_date))
        .filter(Sale.status == SaleStatus.CONFIRMED.value, Sale.customer_id.in_(customer_ids))
        .group_by(Sale.customer_id)
        .all()
    )
    inv_min = (
        db.session.query(Invoice.customer_id, func.min(Invoice.invoice_date))
        .filter(Invoice.cancelled_at.is_(None), Invoice.customer_id.in_(customer_ids))
        .group_by(Invoice.customer_id)
        .all()
    )
    srv_min = (
        db.session.query(ServiceRequest.customer_id, func.min(ServiceRequest.received_at))
        .filter(ServiceRequest.customer_id.in_(customer_ids))
        .group_by(ServiceRequest.customer_id)
        .all()
    )
    po_min = (
        db.session.query(PreOrder.customer_id, func.min(PreOrder.preorder_date))
        .filter(PreOrder.status != PreOrderStatus.CANCELLED.value, PreOrder.customer_id.in_(customer_ids))
        .group_by(PreOrder.customer_id)
        .all()
    )
    online_min = (
        db.session.query(OnlinePreOrder.customer_id, func.min(OnlinePreOrder.created_at))
        .filter(OnlinePreOrder.status != "CANCELLED", OnlinePreOrder.customer_id.in_(customer_ids))
        .group_by(OnlinePreOrder.customer_id)
        .all()
    )

    sales_map = {cid: dt for cid, dt in sales_min}
    inv_map = {cid: dt for cid, dt in inv_min}
    srv_map = {cid: dt for cid, dt in srv_min}
    po_map = {cid: dt for cid, dt in po_min}
    online_map = {cid: dt for cid, dt in online_min}

    acc = {}
    for c in customers:
        outstanding = Decimal(str(c.current_balance or 0))
        if outstanding <= 0:
            continue

        candidates = [
            sales_map.get(c.id),
            inv_map.get(c.id),
            srv_map.get(c.id),
            po_map.get(c.id),
            online_map.get(c.id),
        ]
        candidates = [d for d in candidates if d]
        oldest_date = min(candidates) if candidates else None

        if oldest_date:
            ref_d = oldest_date.date() if isinstance(oldest_date, datetime) else oldest_date
            days = max((as_of - ref_d).days, 0) if (as_of and ref_d) else 0
        else:
            days = 0

        b = age_bucket(days)
        if c.name not in acc:
            acc[c.name] = {k: Decimal("0.00") for k in bucket_keys}
            acc[c.name]["total"] = Decimal("0.00")
        acc[c.name][b] += outstanding
        acc[c.name]["total"] += outstanding
    
    data = []
    for name in sorted(acc.keys()):
        item = {
            "customer": name,
            "balance": float(round(acc[name]["total"], 2)),
            "buckets": {k: float(round(acc[name][k], 2)) for k in bucket_keys},
        }
        data.append(item)
    
    totals = {k: Decimal('0.00') for k in bucket_keys} | {"total": Decimal('0.00')}
    for v in acc.values():
        for k in bucket_keys:
            totals[k] += v[k]
        totals["total"] += v["total"]
    totals = {k: float(round(v, 2)) for k, v in totals.items()}
    
    return {"as_of": as_of.isoformat(), "data": data, "totals": totals}

def ap_aging_report(start_date=None, end_date=None):
    from decimal import Decimal
    
    as_of = _parse_date_like(end_date) or date.today()
    bucket_keys = ("0-30", "31-60", "61-90", "90+")
    
    suppliers = db.session.query(Supplier.id, Supplier.name, Supplier.current_balance).filter(
        func.coalesce(Supplier.current_balance, 0) > 0
    ).all()

    supplier_ids = [s.id for s in suppliers]
    if not supplier_ids:
        return {"as_of": as_of.isoformat(), "data": [], "totals": {k: 0.0 for k in bucket_keys} | {"total": 0.0}}

    inv_min = (
        db.session.query(Invoice.supplier_id, func.min(Invoice.invoice_date))
        .filter(Invoice.cancelled_at.is_(None), Invoice.supplier_id.in_(supplier_ids))
        .group_by(Invoice.supplier_id)
        .all()
    )
    inv_map = {sid: dt for sid, dt in inv_min}

    acc = {}
    for s in suppliers:
        outstanding = Decimal(str(s.current_balance or 0))
        if outstanding <= 0:
            continue
        oldest_date = inv_map.get(s.id)
        if oldest_date:
            ref_d = oldest_date.date() if isinstance(oldest_date, datetime) else oldest_date
            days = max((as_of - ref_d).days, 0) if (as_of and ref_d) else 0
        else:
            days = 0

        b = age_bucket(days)
        if s.name not in acc:
            acc[s.name] = {k: Decimal("0.00") for k in bucket_keys}
            acc[s.name]["total"] = Decimal("0.00")
        acc[s.name][b] += outstanding
        acc[s.name]["total"] += outstanding
    
    data = []
    for name in sorted(acc.keys()):
        item = {
            "supplier": name,
            "balance": float(round(acc[name]["total"], 2)),
            "buckets": {k: float(round(acc[name][k], 2)) for k in bucket_keys},
        }
        data.append(item)
    
    totals = {k: Decimal('0.00') for k in bucket_keys} | {"total": Decimal('0.00')}
    for v in acc.values():
        for k in bucket_keys:
            totals[k] += v[k]
        totals["total"] += v["total"]
    totals = {k: float(round(v, 2)) for k, v in totals.items()}
    
    return {"as_of": as_of.isoformat(), "data": data, "totals": totals}

def top_products_report(
    start_date: date | None,
    end_date: date | None,
    limit: int = 20,
    tz_name: str = "Asia/Hebron",
    warehouse_id: int | None = None,
    group_by_warehouse: bool = False,
) -> dict:
    TZ = ZoneInfo(tz_name)
    today = date.today()
    sd = _parse_date_like(start_date) or (today - timedelta(days=30))
    ed = _parse_date_like(end_date) or today
    if ed < sd:
        sd, ed = ed, sd
    if sd.year < 1970:
        sd = date(1970, 1, 1)
    if ed.year < 1970:
        ed = date(1970, 1, 1)
    start_dt_local = datetime.combine(sd, _t.min).replace(tzinfo=TZ)
    try:
        _ed_plus1 = ed + timedelta(days=1)
        end_dt_local = datetime.combine(_ed_plus1, _t.min).replace(tzinfo=TZ)
        use_lt_end = True
    except OverflowError:
        end_dt_local = datetime.combine(ed, _t.max).replace(tzinfo=TZ)
        use_lt_end = False
    engine = db.engine.name
    if engine == "postgresql":
        lower = Sale.sale_date >= start_dt_local.astimezone(ZoneInfo("UTC"))
        upper = (Sale.sale_date < end_dt_local.astimezone(ZoneInfo("UTC"))) if use_lt_end else (Sale.sale_date <= end_dt_local.astimezone(ZoneInfo("UTC")))
    else:
        lower = Sale.sale_date >= start_dt_local.replace(tzinfo=None)
        upper = (Sale.sale_date < end_dt_local.replace(tzinfo=None)) if use_lt_end else (Sale.sale_date <= end_dt_local.replace(tzinfo=None))
    gross_expr = (SaleLine.quantity * SaleLine.unit_price)
    disc_expr = gross_expr * (func.coalesce(SaleLine.discount_rate, 0) / 100.0)
    net_before_tax_expr = (gross_expr - disc_expr)
    tax_expr = net_before_tax_expr * (func.coalesce(SaleLine.tax_rate, 0) / 100.0)
    net_revenue_expr = net_before_tax_expr + tax_expr
    sum_qty = func.coalesce(func.sum(SaleLine.quantity), 0.0)
    sum_gross = func.coalesce(func.sum(gross_expr), 0.0)
    sum_discount = func.coalesce(func.sum(disc_expr), 0.0)
    sum_net = func.coalesce(func.sum(net_revenue_expr), 0.0)
    weighted_price = func.coalesce(
        func.sum(SaleLine.unit_price * SaleLine.quantity) / func.nullif(func.sum(SaleLine.quantity), 0),
        0.0,
    )
    can_group_by_wh = hasattr(SaleLine, "warehouse_id")
    want_group = bool(group_by_warehouse and can_group_by_wh)
    want_filter = bool(warehouse_id and can_group_by_wh)
    from sqlalchemy import case
    fx_mult = case(
        (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Sale.fx_rate_used, 1),
    )
    sum_net_ils = func.coalesce(func.sum(net_revenue_expr * fx_mult), 0.0)
    select_cols = [
        Product.id.label("product_id"),
        Product.name.label("name"),
        sum_qty.label("qty"),
        sum_gross.label("gross"),
        sum_discount.label("discount"),
        sum_net_ils.label("revenue"),
        sum_net_ils.label("revenue_ils"),
        weighted_price.label("avg_unit_price"),
        func.count(func.distinct(Sale.id)).label("orders_count"),
        func.min(Sale.sale_date).label("first_sale"),
        func.max(Sale.sale_date).label("last_sale"),
    ]
    if want_group:
        select_cols.append(Warehouse.name.label("warehouse_name"))
    q = (
        db.session.query(*select_cols)
        .join(SaleLine, SaleLine.product_id == Product.id)
        .join(Sale, SaleLine.sale_id == Sale.id)
        .filter(lower, upper)
        .filter(Sale.status == SaleStatus.CONFIRMED.value)
    )
    if want_group or want_filter:
        q = q.outerjoin(Warehouse, Warehouse.id == SaleLine.warehouse_id)
    if want_filter:
        q = q.filter(Warehouse.id == int(warehouse_id))
    if want_group:
        q = q.group_by(Product.id, Product.name, Warehouse.name)
    else:
        q = q.group_by(Product.id, Product.name)
    q = q.order_by(desc("revenue_ils")).limit(int(limit or 20))
    rows = q.all()
    
    total_revenue = float(sum(float(getattr(r, "revenue_ils", 0) or 0) for r in rows))
    total_qty = int(sum(float(getattr(r, "qty", 0) or 0) for r in rows))
    max_qty = max((float(getattr(r, "qty", 0) or 0) for r in rows), default=0)
    def _rank_label(idx: int) -> str:
        return ("الأول" if idx == 1 else "الثاني" if idx == 2 else "الثالث" if idx == 3 else f"المرتبة {idx}")
    data: list[dict] = []
    for i, r in enumerate(rows, start=1):
        qty = int(getattr(r, "qty", 0) or 0)
        rev = float(getattr(r, "revenue_ils", getattr(r, "revenue", 0)) or 0)
        gross = float(getattr(r, "gross", 0) or 0)
        discount = float(getattr(r, "discount", 0) or 0)
        orders_count = int(getattr(r, "orders_count", 0) or 0)
        avg_price = float(getattr(r, "avg_unit_price", 0) or 0)
        prod_id = getattr(r, "product_id", None)
        prod_name = getattr(r, "name", None)
        wh_name = getattr(r, "warehouse_name", None) if want_group else None
        first_sale = getattr(r, "first_sale", None)
        last_sale = getattr(r, "last_sale", None)
        share = (rev / total_revenue * 100.0) if total_revenue > 0 else 0.0
        if i <= 3 and rev > 0:
            reason = "ضمن الأعلى إيرادًا"
        elif qty == max_qty and qty > 0:
            reason = "أعلى كمية مباعة"
        elif share >= 10:
            reason = "حصة إيراد كبيرة"
        elif orders_count >= 5:
            reason = "مكرر الطلب من الزبائن"
        else:
            reason = "أداء جيد ضمن الفترة"
        item = {
            "id": i,
            "rank_label": _rank_label(i),
            "product_id": prod_id,
            "name": prod_name,
            "qty": qty,
            "revenue": round(rev, 2),
            "revenue_share": round(share, 2),
            "gross": round(gross, 2),
            "discount": round(discount, 2),
            "avg_unit_price": round(avg_price, 2),
            "orders_count": orders_count,
            "first_sale": (first_sale.isoformat() if first_sale else None),
            "last_sale": (last_sale.isoformat() if last_sale else None),
            "reason": reason,
        }
        if want_group:
            item["warehouse_name"] = wh_name or "—"
        data.append(item)
    return {
        "data": data,
        "can_group_by_warehouse": can_group_by_wh,
        "meta": {
            "start_date": sd.isoformat(),
            "end_date": ed.isoformat(),
            "total_revenue": round(total_revenue, 2),
            "total_qty": total_qty,
            "count": len(data),
            "warehouse_id": int(warehouse_id) if warehouse_id else None,
            "group_by_warehouse": bool(group_by_warehouse and can_group_by_wh),
        },
    }


def partner_balance_report_ils(partner_ids: list = None) -> Dict:
    """تقرير أرصدة الشركاء بالشيكل"""
    try:
        import utils
        from models import Partner

        if partner_ids is None:
            partners = db.session.query(Partner).all()
            partner_ids = [p.id for p in partners]

        report_data = []
        total_balance_ils = Decimal("0.00")

        for partner_id in partner_ids:
            partner = db.session.get(Partner, partner_id)
            if not partner:
                continue

            balance_ils = utils.get_entity_balance_in_ils("PARTNER", partner_id)

            report_data.append({
                'partner_id': partner_id,
                'partner_name': partner.name,
                'partner_currency': partner.currency,
                'balance_ils': balance_ils,
                'formatted_balance': utils.format_currency_in_ils(balance_ils),
                'share_percentage': partner.share_percentage,
                'contact_info': partner.contact_info
            })

            total_balance_ils += balance_ils

        return {
            'report_type': 'partner_balance_report_ils',
            'base_currency': 'ILS',
            'total_partners': len(partner_ids),
            'total_balance_ils': total_balance_ils,
            'formatted_total': utils.format_currency_in_ils(total_balance_ils),
            'partners': report_data,
            'generated_at': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'error': str(e),
            'generated_at': datetime.now(timezone.utc)
        }
