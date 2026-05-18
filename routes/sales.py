
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, Optional, List, Tuple
from flask import Blueprint, flash, jsonify, redirect, render_template, render_template_string, request, url_for, abort, current_app, Response
from flask_login import current_user, login_required
from sqlalchemy import func, or_, desc, extract, case, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload, load_only
from extensions import db, cache
from models import Sale, SaleLine, Invoice, Customer, Product, AuditLog, Warehouse, User, Payment, StockLevel, Employee, CostCenter, SaleStatus, PaymentStatus, PaymentMethod
from models import convert_amount, run_sale_gl_sync_after_commit


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
from forms import SaleForm
import utils
from utils import D, _get_or_404, line_total_decimal, money_fmt, archive_record, restore_record
from decimal import Decimal, ROUND_HALF_UP
from permissions_config.enums import SystemPermissions

# تعريف TWOPLACES للتقريب العشري
TWOPLACES = Decimal('0.01')

sales_bp = Blueprint("sales_bp", __name__, url_prefix="/sales", template_folder="templates/sales")

STATUS_MAP = {
    SaleStatus.DRAFT.value: ("مسودة", "bg-warning text-dark"),
    SaleStatus.CONFIRMED.value: ("مؤكدة", "bg-primary"),
    SaleStatus.CANCELLED.value: ("ملغاة", "bg-secondary"),
    SaleStatus.REFUNDED.value: ("مرتجعة", "bg-info"),
}
PAYMENT_STATUS_MAP = {
    PaymentStatus.PENDING.value: ("معلّق", "bg-warning"),
    PaymentStatus.COMPLETED.value: ("مكتمل", "bg-success"),
    PaymentStatus.FAILED.value: ("فشل", "bg-danger"),
    PaymentStatus.REFUNDED.value: ("مرتجع", "bg-info"),
}
PAYMENT_METHOD_MAP = {
    PaymentMethod.CASH.value: "نقدي",
    PaymentMethod.CHEQUE.value: "شيك",
    PaymentMethod.CARD.value: "بطاقة",
    PaymentMethod.BANK.value: "تحويل بنكي",
    PaymentMethod.ONLINE.value: "دفع إلكتروني"
}

def _format_sale(s: Sale) -> None:
    s.customer_name = s.customer.name if s.customer else "-"
    if getattr(s, "seller_employee", None):
        s.seller_name = s.seller_employee.name or "-"
    elif getattr(s, "seller", None):
        s.seller_name = getattr(s.seller, "username", None) or getattr(s.seller, "name", None) or "-"
    else:
        s.seller_name = "-"
    s.date = s.sale_date
    s.date_iso = s.sale_date.strftime("%Y-%m-%d") if s.sale_date else "-"
    s.total_fmt = f"{float(getattr(s, 'total_amount', 0) or 0):,.2f}"
    s.paid_fmt = f"{float(getattr(s, 'total_paid', 0) or 0):,.2f}"
    s.balance_fmt = f"{float(getattr(s, 'balance_due', 0) or 0):,.2f}"
    lbl, cls = STATUS_MAP.get(s.status, (s.status, ""))
    s.status_label, s.status_class = lbl, cls

def sale_to_dict(s: Sale) -> Dict[str, Any]:
    return {
        "id": s.id,
        "sale_number": s.sale_number,
        "customer_id": s.customer_id,
        "seller_id": s.seller_id,
        "seller_employee_id": s.seller_employee_id,
        "sale_date": s.sale_date.strftime("%Y-%m-%d") if s.sale_date else None,
        "status": s.status,
        "currency": s.currency,
        "tax_rate": float(s.tax_rate or 0),
        "shipping_cost": float(getattr(s, "shipping_cost", 0) or 0),
        "discount_total": float(getattr(s, "discount_total", 0) or 0),
        "notes": s.notes,
        "lines": [
            {
                "product_id": ln.product_id,
                "warehouse_id": ln.warehouse_id,
                "quantity": ln.quantity,
                "unit_price": float(ln.unit_price or 0),
                "discount_rate": float(ln.discount_rate or 0),
                "tax_rate": float(ln.tax_rate or 0),
            }
            for ln in s.lines
        ],
    }

def _log(s: Sale, action: str, old: Optional[dict] = None, new: Optional[dict] = None) -> None:
    log = AuditLog(
        model_name="Sale",
        record_id=s.id,
        action=action,
        old_data=json.dumps(old, ensure_ascii=False) if old else None,
        new_data=json.dumps(new, ensure_ascii=False) if new else None,
        user_id=current_user.id if current_user.is_authenticated else None,
    )
    now = _utc_now_naive()
    for fld in ("timestamp", "created_at", "logged_at"):
        if hasattr(AuditLog, fld):
            setattr(log, fld, now)
            break
    db.session.add(log)
    db.session.flush()

def _available_expr():
    return (StockLevel.quantity - func.coalesce(StockLevel.reserved_quantity, 0))

def _available_qty(product_id: int, warehouse_id: int) -> int:
    row = (
        db.session.query(_available_expr().label("avail"))
        .filter(StockLevel.product_id == product_id, StockLevel.warehouse_id == warehouse_id)
        .first()
    )
    return int(row.avail or 0) if row else 0

def _auto_pick_warehouse(product_id: int, required_qty: int, preferred_wid: Optional[int] = None) -> Optional[int]:
    if preferred_wid:
        if _available_qty(product_id, preferred_wid) >= required_qty:
            return preferred_wid
    order_expr = case(
        (Warehouse.warehouse_type == "MAIN", 0),
        (Warehouse.warehouse_type == "INVENTORY", 1),
        (Warehouse.warehouse_type == "PARTNER", 2),
        (Warehouse.warehouse_type == "EXCHANGE", 3),
        else_=9,
    )
    row = (
        db.session.query(StockLevel.warehouse_id, Warehouse.warehouse_type, _available_expr().label("avail"))
        .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
        .filter(StockLevel.product_id == product_id)
        .filter(_available_expr() >= required_qty)
        .order_by(order_expr.asc(), Warehouse.id.asc())
        .first()
    )
    return int(row.warehouse_id) if row else None

def _lock_stock_rows(pairs: List[Tuple[int, int]]) -> None:
    if not pairs:
        return
    conds = [and_(StockLevel.product_id == pid, StockLevel.warehouse_id == wid) for (pid, wid) in pairs]
    db.session.query(StockLevel).filter(or_(*conds)).with_for_update(nowait=False).all()

def _collect_requirements_from_lines(lines: Iterable[SaleLine]) -> Dict[Tuple[int, int], int]:
    req: Dict[Tuple[int, int], int] = {}
    for ln in lines:
        pid = int(ln.product_id or 0)
        wid = int(ln.warehouse_id or 0)
        qty = int(ln.quantity or 0)
        if pid and wid and qty > 0:
            key = (pid, wid)
            req[key] = req.get(key, 0) + qty
    return req

def _reserve_stock(sale: Sale) -> None:
    if (getattr(sale, "status", "") or "").upper() != SaleStatus.CONFIRMED.value:
        return
    req = _collect_requirements_from_lines(sale.lines or [])
    if not req:
        return
    _lock_stock_rows(list(req.keys()))
    for (pid, wid), qty in req.items():
        rec = (
            db.session.query(StockLevel)
            .filter_by(product_id=pid, warehouse_id=wid)
            .with_for_update(nowait=False)
            .first()
        )
        if not rec:
            # إنشاء StockLevel جديد إذا لم يكن موجوداً
            rec = StockLevel(product_id=pid, warehouse_id=wid, quantity=0, reserved_quantity=0)
            db.session.add(rec)
            try:
                db.session.flush()
            except Exception as e:
                current_app.logger.error(f"خطأ في إنشاء StockLevel: {str(e)}")
                raise ValueError(f"لا يمكن حجز المخزون للمنتج {pid} في المستودع {wid}")
        available = int(rec.quantity or 0) - int(rec.reserved_quantity or 0)
        if available < qty:
            raise ValueError(f"الكمية غير متوفرة للمنتج ID={pid} في المخزن {wid}.")
        rec.reserved_quantity = int(rec.reserved_quantity or 0) + qty
        db.session.flush()

def _release_stock(sale: Sale) -> None:
    req = _collect_requirements_from_lines(sale.lines or [])
    if not req:
        return
    _lock_stock_rows(list(req.keys()))
    for (pid, wid), qty in req.items():
        rec = (
            db.session.query(StockLevel)
            .filter_by(product_id=pid, warehouse_id=wid)
            .with_for_update(nowait=False)
            .first()
        )
        if not rec:
            continue
        current_reserved = int(rec.reserved_quantity or 0)
        new_reserved = max(0, current_reserved - qty)
        rec.reserved_quantity = new_reserved
        db.session.flush()

def _deduct_stock(sale: Sale) -> None:
    """
    خصم المخزون الفعلي عند اكتمال البيع/الدفع.
    يتحقق من stock_deducted لمنع الخصم المزدوج.
    يخصم من quantity و reserved_quantity معاً.
    """
    if getattr(sale, 'stock_deducted', False):
        return
    req = _collect_requirements_from_lines(sale.lines or [])
    if not req:
        return
    _lock_stock_rows(list(req.keys()))
    for (pid, wid), qty in req.items():
        rec = (
            db.session.query(StockLevel)
            .filter_by(product_id=pid, warehouse_id=wid)
            .with_for_update(nowait=False)
            .first()
        )
        if not rec:
            continue
        
        current_qty = int(rec.quantity or 0)
        current_reserved = int(rec.reserved_quantity or 0)
        
        if current_reserved >= qty:
            if current_qty < qty:
                raise ValueError(f"الكمية الفعلية غير كافية للمنتج {pid} في المستودع {wid}: الفعلية {current_qty}، المطلوب {qty}")
            new_quantity = current_qty - qty
            new_reserved = current_reserved - qty
        else:
            available = current_qty - current_reserved
            if available < qty:
                raise ValueError(f"الكمية المتاحة غير كافية للمنتج {pid} في المستودع {wid}: المتاح {available}، المطلوب {qty}")
            new_quantity = current_qty - qty
            new_reserved = max(0, current_reserved - qty)
        
        rec.quantity = new_quantity
        rec.reserved_quantity = new_reserved
        db.session.flush()
    sale.stock_deducted = True
    db.session.flush()

def _resolve_lines_from_form(form: SaleForm, require_stock: bool) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    lines_payload: List[Dict[str, Any]] = []
    for ent in form.lines.entries:
        ln = ent.form
        pid = int(ln.product_id.data) if ln.product_id.data else 0
        wid = int(ln.warehouse_id.data) if ln.warehouse_id.data else 0
        qty = int(ln.quantity.data or 0)
        if not (pid and qty > 0):
            continue
        chosen_wid = wid or _auto_pick_warehouse(pid, qty, preferred_wid=None)
        if wid and _available_qty(pid, wid) < qty:
            auto_wid = _auto_pick_warehouse(pid, qty, preferred_wid=None)
            chosen_wid = auto_wid or wid
        if require_stock:
            if not chosen_wid:
                return [], f"لا يوجد مخزن مناسب متاح للمنتج ID={pid} بالكمية المطلوبة."
            if _available_qty(pid, chosen_wid) < qty:
                return [], f"الكمية غير متوفرة للمنتج ID={pid} في المخازن بالكمية: {qty}."
        line_dict = dict(
            product_id=pid,
            warehouse_id=int(chosen_wid) if chosen_wid else (wid or None),
            quantity=qty,
            unit_price=float(ln.unit_price.data or 0),
            discount_rate=float(ln.discount_rate.data or 0),
            tax_rate=float(ln.tax_rate.data or 0),
            line_receiver=(ln.line_receiver.data or "").strip() or None,
            note=(ln.note.data or "").strip() or None,
        )
        lines_payload.append(line_dict)
    if require_stock and not lines_payload:
        return [], "لا توجد أسطر صالحة للحفظ."
    return lines_payload, None

def _attach_lines(sale: Sale, lines_payload: List[Dict[str, Any]]) -> None:
    if getattr(sale, "id", None):
        SaleLine.query.filter_by(sale_id=sale.id).delete(synchronize_session=False)
        db.session.flush()
    sale_tax = getattr(sale, "tax_rate", None) or 0
    for d in lines_payload:
        line_tax = d.get("tax_rate") or 0
        if line_tax == 0 and sale_tax:
            line_tax = float(sale_tax)
        db.session.add(SaleLine(
            sale_id=sale.id,
            product_id=d["product_id"],
            warehouse_id=d.get("warehouse_id"),
            quantity=d["quantity"],
            unit_price=d["unit_price"],
            discount_rate=d.get("discount_rate", 0),
            tax_rate=line_tax,
            line_receiver=d.get("line_receiver"),
            note=d.get("note"),
        ))
    db.session.flush()

def _safe_generate_number_after_flush(sale: Sale) -> None:
    if not sale.sale_number:
        sale.sale_number = f"INV-{_utc_now_naive():%Y%m%d}-{sale.id:04d}"
        db.session.flush()

@sales_bp.route("/<int:id>/archive", methods=["POST"])
@login_required
def archive_sale(id):
    if not current_user.has_permission(SystemPermissions.ARCHIVE_SALE):
        return jsonify({"status": "error", "message": "ليس لديك صلاحية لأرشفة المبيعات"}), 403
    
    sale = db.get_or_404(Sale, id)
    reason = request.form.get("reason")
    
    try:
        archive_record(sale, Sale, reason=reason)
        return jsonify({"status": "success", "message": "تم أرشفة عملية البيع بنجاح"})
    except Exception as e:
        db.session.rollback()
        try:
            sale.is_archived = True
            db.session.commit()
            return jsonify({"status": "success", "message": "تم أرشفة عملية البيع بنجاح (يدوي)"})
        except:
            db.session.rollback()
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 500

@sales_bp.route("/<int:id>/restore", methods=["POST"])
@login_required
def restore_sale(id):
    if not current_user.has_permission(SystemPermissions.ARCHIVE_SALE):
        return jsonify({"status": "error", "message": "ليس لديك صلاحية لاستعادة المبيعات"}), 403
        
    try:
        restore_record(id, Sale)
        return jsonify({"status": "success", "message": "تم استعادة عملية البيع بنجاح"})
    except Exception as e:
        db.session.rollback()
        sale = db.session.get(Sale, id)
        if sale:
            sale.is_archived = False
            db.session.commit()
            return jsonify({"status": "success", "message": "تم استعادة عملية البيع بنجاح (يدوي)"})
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500

@sales_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
@login_required
def dashboard():
    from decimal import Decimal
    from models import convert_amount
    
    total_sales = db.session.query(func.count(Sale.id)).scalar() or 0
    
    all_sales = db.session.query(Sale).all()
    total_revenue = Decimal('0.00')
    for s in all_sales:
        amt = Decimal(str(s.total_amount or 0))
        if s.currency == "ILS":
            total_revenue += amt
        else:
            try:
                total_revenue += convert_amount(amt, s.currency, "ILS", s.sale_date)
            except Exception:
                pass
    total_revenue = float(total_revenue)
    
    pending_sales = db.session.query(func.count(Sale.id)).filter(Sale.status == SaleStatus.DRAFT.value).scalar() or 0
    
    customers = db.session.query(Customer).all()
    top_customers_data = []
    for cust in customers:
        cust_sales = db.session.query(Sale).filter(Sale.customer_id == cust.id).all()
        spent = Decimal('0.00')
        for s in cust_sales:
            amt = Decimal(str(s.total_amount or 0))
            if s.currency == "ILS":
                spent += amt
            else:
                try:
                    spent += convert_amount(amt, s.currency, "ILS", s.sale_date)
                except Exception:
                    pass
        if spent > 0:
            top_customers_data.append((cust.name, float(spent)))
    top_customers_data.sort(key=lambda x: x[1], reverse=True)
    top_customers = top_customers_data[:5]
    
    products = db.session.query(Product).all()
    top_products_data = []
    for prod in products:
        lines = db.session.query(SaleLine).join(Sale).filter(
            SaleLine.product_id == prod.id,
            Sale.status == SaleStatus.CONFIRMED
        ).all()
        sold = sum(int(l.quantity or 0) for l in lines)
        revenue_prod = Decimal('0.00')
        for l in lines:
            sale = l.sale
            line_amt = Decimal(str(l.quantity or 0)) * Decimal(str(l.unit_price or 0)) * (Decimal('1') - Decimal(str(l.discount_rate or 0)) / Decimal('100'))
            if sale.currency == "ILS":
                revenue_prod += line_amt
            else:
                try:
                    revenue_prod += convert_amount(line_amt, sale.currency, "ILS", sale.sale_date)
                except Exception:
                    pass
        if sold > 0:
            top_products_data.append((prod.name, sold, float(revenue_prod)))
    top_products_data.sort(key=lambda x: x[1], reverse=True)
    top_products = top_products_data[:5]
    
    y = extract("year", Sale.sale_date)
    m = extract("month", Sale.sale_date)
    monthly_raw = db.session.query(y.label("y"), m.label("m"), func.count(Sale.id)).group_by(y, m).order_by(y, m).all()
    
    monthly_revenue = {}
    for s in all_sales:
        if not s.sale_date:
            continue
        ym = (s.sale_date.year, s.sale_date.month)
        if ym not in monthly_revenue:
            monthly_revenue[ym] = Decimal('0.00')
        amt = Decimal(str(s.total_amount or 0))
        if s.currency == "ILS":
            monthly_revenue[ym] += amt
        else:
            try:
                monthly_revenue[ym] += convert_amount(amt, s.currency, "ILS", s.sale_date)
            except Exception:
                pass
    
    months, counts, revenue = [], [], []
    for yy, mm, cnt in monthly_raw:
        months.append(f"{int(mm)}/{int(yy)}")
        counts.append(int(cnt))
        revenue.append(float(monthly_revenue.get((yy, mm), Decimal('0.00'))))
    return render_template("sales/dashboard.html",
                           total_sales=total_sales, total_revenue=total_revenue, pending_sales=pending_sales,
                           top_customers=top_customers, top_products=top_products,
                           months=months, sales_count=counts, revenue=revenue)

@sales_bp.route("/", endpoint="list_sales")
@sales_bp.route("/", endpoint="index")
@login_required
def list_sales():
    f = request.args
    q = (Sale.query
         .filter(Sale.is_archived == False)
        .options(
            joinedload(Sale.customer).load_only(Customer.id, Customer.name, Customer.phone),
            joinedload(Sale.seller).load_only(User.id, User.username),
            joinedload(Sale.seller_employee).load_only(Employee.id, Employee.name)
        )
         .outerjoin(Customer))
    st = (f.get("status") or "").upper().strip()
    status_filter_enabled = bool(st and st != "ALL")
    if status_filter_enabled:
        q = q.filter(Sale.status == st)
    cust = (f.get("customer") or "").strip()
    if cust:
        q = q.filter(or_(Customer.name.ilike(f"%{cust}%"), Customer.phone.ilike(f"%{cust}%")))
    df = (f.get("date_from") or "").strip()
    dt = (f.get("date_to") or "").strip()
    try:
        if df:
            q = q.filter(Sale.sale_date >= datetime.fromisoformat(df))
        if dt:
            q = q.filter(Sale.sale_date <= datetime.fromisoformat(dt))
    except ValueError:
        pass
    inv = (f.get("invoice_no") or "").strip()
    if inv:
        q = q.filter(Sale.sale_number.ilike(f"%{inv}%"))
    search_term = (f.get("q") or "").strip()
    if search_term:
        like = f"%{search_term}%"
        search_filters = [
            Sale.sale_number.ilike(like),
            Sale.notes.ilike(like),
            Sale.currency.ilike(like),
            Sale.receiver_name.ilike(like),
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
        ]
        if search_term.isdigit():
            search_filters.append(Sale.id == int(search_term))
        q = q.filter(or_(*search_filters))
    sort = f.get("sort", "date")
    order = f.get("order", "desc")
    subtotals = None
    if sort == "total":
        subtotals = (
            db.session.query(
                Sale.id.label("sale_id"),
                func.coalesce(
                    func.sum(
                        SaleLine.quantity * SaleLine.unit_price *
                        (1 - func.coalesce(SaleLine.discount_rate, 0) / 100.0) *
                        (1 + func.coalesce(SaleLine.tax_rate, 0) / 100.0)
                    ),
                    0,
                ).label("calc_total"),
            )
            .outerjoin(SaleLine, SaleLine.sale_id == Sale.id)
            .group_by(Sale.id).subquery()
        )
        q = q.outerjoin(subtotals, subtotals.c.sale_id == Sale.id)
    current_app.logger.info(f"Sales sort: {sort}, order: {order}, request.args: {dict(request.args)}")
    if sort == "total" and subtotals is not None:
        fld = subtotals.c.calc_total
        ordered_query = q.order_by(fld.asc() if order == "asc" else fld.desc())
    elif sort == "customer":
        fld = Customer.name
        ordered_query = q.order_by(fld.asc() if order == "asc" else fld.desc())
    elif sort == "invoice_no":
        fld = Sale.sale_number
        ordered_query = q.order_by(fld.asc().nullslast() if order == "asc" else fld.desc().nullslast())
    elif sort == "paid":
        fld = Sale.total_paid
        ordered_query = q.order_by(fld.asc().nullslast() if order == "asc" else fld.desc().nullslast())
    elif sort == "balance":
        fld = Sale.balance_due
        ordered_query = q.order_by(fld.asc().nullslast() if order == "asc" else fld.desc().nullslast())
    elif sort == "date":
        fld = Sale.sale_date
        ordered_query = q.order_by(fld.asc() if order == "asc" else fld.desc())
    else:
        fld = Sale.sale_date
        ordered_query = q.order_by(fld.asc() if order == "asc" else fld.desc())

    per_page = 10
    page = max(1, int(f.get("page", 1)))

    print_mode = request.args.get("print") == "1"
    scope_param = request.args.get("scope")
    print_scope = scope_param or ("page" if print_mode else "all")
    range_start = request.args.get("range_start", type=int)
    range_end = request.args.get("range_end", type=int)
    target_page = request.args.get("page_number", type=int)
    
    # تعريف القيم الافتراضية
    range_start_value = range_start or 1
    range_end_value = range_end or 10000
    target_page_value = target_page or 1

    per_page = min(max(1, per_page), 500)
    
    # حساب total_filtered و total_pages
    total_filtered = q.count()
    total_pages = math.ceil(total_filtered / per_page) if total_filtered else 1
    
    if print_mode:
        if print_scope == "all":
            pag = ordered_query.paginate(page=1, per_page=10000, error_out=False)
            sales_list = list(pag.items)
            row_offset = 0
        elif print_scope == "range":
            range_start_value = max(1, range_start or 1)
            range_end_value = range_end or 10000
            if range_end_value < range_start_value:
                range_end_value = range_start_value
            range_size = range_end_value - range_start_value + 1
            range_page = math.ceil(range_start_value / per_page)
            pag = ordered_query.paginate(page=range_page, per_page=range_size, error_out=False)
            sales_list = list(pag.items)
            row_offset = range_start_value - 1
        else:
            target_page_value = max(1, target_page or 1)
            pag = ordered_query.paginate(page=target_page_value, per_page=per_page, error_out=False)
            sales_list = list(pag.items)
            row_offset = (pag.page - 1) * pag.per_page if pag else 0
        pag = None
    else:
        pag = ordered_query.paginate(page=page, per_page=per_page, error_out=False)
        sales_list = list(pag.items)
        row_offset = (pag.page - 1) * pag.per_page if pag else 0
    current_app.logger.debug(f"Sales list count: {len(sales_list)}, first sale date: {sales_list[0].sale_date if sales_list else 'N/A'}")
    for s in sales_list:
        _format_sale(s)

    excluded_statuses = {
        SaleStatus.DRAFT.value,
        SaleStatus.CANCELLED.value,
        SaleStatus.REFUNDED.value,
    }

    summary_q = Sale.query.filter(Sale.is_archived.is_(False))
    need_customer_join = bool(cust or search_term)
    if need_customer_join:
        summary_q = summary_q.outerjoin(Customer)
    if status_filter_enabled:
        summary_q = summary_q.filter(Sale.status == st)
    if cust:
        summary_q = summary_q.filter(or_(Customer.name.ilike(f"%{cust}%"), Customer.phone.ilike(f"%{cust}%")))
    if inv:
        summary_q = summary_q.filter(Sale.sale_number.ilike(f"%{inv}%"))
    if search_term:
        like_all = f"%{search_term}%"
        search_filters_all = [
            Sale.sale_number.ilike(like_all),
            Sale.notes.ilike(like_all),
            Sale.currency.ilike(like_all),
            Sale.receiver_name.ilike(like_all),
            Customer.name.ilike(like_all),
            Customer.phone.ilike(like_all),
        ]
        if search_term.isdigit():
            search_filters_all.append(Sale.id == int(search_term))
        summary_q = summary_q.filter(or_(*search_filters_all))
    try:
        if df:
            summary_q = summary_q.filter(Sale.sale_date >= datetime.fromisoformat(df))
        if dt:
            summary_q = summary_q.filter(Sale.sale_date <= datetime.fromisoformat(dt))
    except Exception:
        pass

    fx_mult = case(
        (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Sale.fx_rate_used, 1),
    )

    total_amount_ils = func.coalesce(Sale.total_amount, 0) * fx_mult
    total_paid_ils = func.coalesce(Sale.total_paid, 0) * fx_mult
    balance_due_ils = func.coalesce(Sale.balance_due, 0) * fx_mult
    refunded_total_ils = func.coalesce(Sale.refunded_total, 0) * fx_mult

    contributing_cond = ~func.upper(func.coalesce(Sale.status, SaleStatus.DRAFT.value)).in_({s.upper() for s in excluded_statuses})
    refunded_net_ils = case(
        (total_amount_ils - refunded_total_ils > 0, total_amount_ils - refunded_total_ils),
        else_=0,
    )
    paid_refunded_ils = case(
        (total_paid_ils < refunded_net_ils, total_paid_ils),
        else_=refunded_net_ils,
    )
    balance_due_pos_ils = case(
        (balance_due_ils > 0, balance_due_ils),
        else_=0,
    )

    agg = summary_q.with_entities(
        func.coalesce(
            func.sum(case((contributing_cond, total_amount_ils), else_=0)),
            0,
        ).label("total_sales"),
        func.coalesce(
            func.sum(
                case(
                    (contributing_cond, total_paid_ils),
                    else_=0,
                )
            ),
            0,
        ).label("total_paid_core"),
        func.coalesce(
            func.sum(
                case(
                    (
                        func.upper(func.coalesce(Sale.status, "")) == SaleStatus.REFUNDED.value.upper(),
                        paid_refunded_ils,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("total_paid_refunded"),
        func.coalesce(
            func.sum(
                case(
                    (contributing_cond, balance_due_pos_ils),
                    else_=0,
                )
            ),
            0,
        ).label("total_pending"),
        func.coalesce(
            func.sum(case((contributing_cond, 1), else_=0)),
            0,
        ).label("sales_count"),
    ).first()

    total_sales = float(getattr(agg, "total_sales", 0) or 0)
    total_paid = float((getattr(agg, "total_paid_core", 0) or 0) + (getattr(agg, "total_paid_refunded", 0) or 0))
    total_pending = float(getattr(agg, "total_pending", 0) or 0)
    sales_count = int(getattr(agg, "sales_count", 0) or 0)
    average_sale = (total_sales / sales_count) if sales_count else 0.0

    net_amount_ils = case(
        (
            func.upper(func.coalesce(Sale.status, "")) == SaleStatus.REFUNDED.value.upper(),
            refunded_net_ils,
        ),
        else_=total_amount_ils,
    )
    status_expr = func.upper(func.coalesce(Sale.status, SaleStatus.DRAFT.value))
    by_status_rows = (
        summary_q.with_entities(
            status_expr.label("status"),
            func.count(Sale.id).label("cnt"),
            func.coalesce(func.sum(net_amount_ils), 0).label("amt"),
        )
        .group_by(status_expr)
        .all()
    )
    sales_by_status: dict[str, dict[str, float | int]] = {
        str(stt or SaleStatus.DRAFT.value).upper(): {"count": int(cnt or 0), "amount": float(amt or 0)}
        for stt, cnt, amt in by_status_rows
    }

    summary = {
        'total_sales': total_sales,
        'total_paid': total_paid,
        'total_pending': total_pending,
        'average_sale': average_sale,
        'sales_count': sales_count,
        'sales_by_status': sales_by_status
    }
    
    query_args = request.args.to_dict()
    for key in ["page", "print", "scope", "range_start", "range_end", "page_number", "ajax"]:
        query_args.pop(key, None)

    context = {
        "sales": sales_list,
        "pagination": pag,
        "warehouses": Warehouse.query.options(
            load_only(Warehouse.id, Warehouse.name)
        ).order_by(Warehouse.name).all(),
        "customers": Customer.query.options(
            load_only(Customer.id, Customer.name, Customer.phone)
        ).order_by(Customer.name).limit(100).all(),
        "sellers": User.query.filter_by(is_active=True).order_by(User.username).all(),
        "status_map": STATUS_MAP,
        "summary": summary,
        "query_args": query_args,
        "print_mode": print_mode,
        "print_scope": print_scope,
        "range_start": range_start_value,
        "range_end": range_end_value,
        "target_page": target_page_value,
        "total_filtered": total_filtered,
        "total_pages": total_pages if total_pages else 1,
        "per_page": per_page,
        "row_offset": row_offset,
        "generated_at": _utc_now_naive(),
        "pdf_export": False,
        "show_actions": not print_mode,
    }

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json"
    if is_ajax and not print_mode:
        current_sort = f.get("sort", "date")
        current_order = f.get("order", "desc")
        table_html = render_template_string(
            """
<table id="salesTable" class="table table-hover align-middle">
  <thead class="thead-light">
    <tr>
      <th data-sortable="false">رقم</th>
      <th data-sortable="false">التاريخ</th>
      <th data-sortable="false">العميل</th>
      <th data-sortable="false">الإجمالي</th>
      <th data-sortable="false" class="text-center">العملة</th>
      <th data-sortable="false" class="text-center d-none d-lg-table-cell">سعر الصرف</th>
      <th data-sortable="false">مدفوع</th>
      <th data-sortable="false">متبقي</th>
      <th class="text-center" data-sortable="false">إجراءات</th>
    </tr>
  </thead>
  <tbody>
    {% for sale in sales %}
    <tr>
      <td>{{ sale.sale_number }}</td>
      <td>{{ sale.date_iso }}</td>
      <td>{{ sale.customer_name }}</td>
      <td data-sort-value="{{ sale.total_amount or 0 }}">{{ sale.total_fmt }}</td>
      <td class="text-center"><span class="badge badge-secondary rounded-pill">{{ sale.currency or 'ILS' }}</span></td>
      <td class="text-center d-none d-lg-table-cell">
        {% if sale.fx_rate_used and sale.currency != 'ILS' %}
        <small class="text-muted">
          {{ "%.4f"|format(sale.fx_rate_used) }}
          {% if sale.fx_rate_source %}
            {% if sale.fx_rate_source == 'online' %}🌐{% elif sale.fx_rate_source == 'manual' %}✍️{% else %}⚙️{% endif %}
          {% endif %}
        </small>
        {% else %}
        <span class="text-muted">-</span>
        {% endif %}
      </td>
      <td data-sort-value="{{ sale.total_paid or 0 }}">{{ sale.paid_fmt }}</td>
      <td data-sort-value="{{ sale.balance_due or 0 }}">
        <span class="badge {{ 'bg-success' if (sale.balance_due or 0) == 0 else 'bg-danger' }}">
          {{ sale.balance_fmt }}
        </span>
      </td>
      <td class="text-center">
        <div class="table-actions">
          <a href="{{ url_for('sales_bp.sale_detail', id=sale.id) }}" class="btn btn-action-view btn-action-sm" title="عرض">
            <i class="fas fa-eye"></i>
          </a>
          <a href="{{ url_for('sales_bp.edit_sale', id=sale.id) }}" class="btn btn-action-edit btn-action-sm" title="تعديل">
            <i class="fas fa-edit"></i>
          </a>
          <div class="btn-group">
            <button type="button" class="btn btn-outline-secondary btn-action-sm dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="خيارات">
              <i class="fas fa-ellipsis-v"></i>
            </button>
            <div class="dropdown-menu dropdown-menu-right">
              <a href="{{ url_for('sales_bp.generate_invoice', id=sale.id) }}" class="dropdown-item" target="_blank">
                <i class="fas fa-file-invoice-dollar mr-2"></i> فاتورة ضريبية
              </a>
              {% if sale.balance_due and sale.balance_due > 0 %}
              <a href="{{ url_for('payments.create_payment',
                                   entity_type='SALE',
                                   entity_id=sale.id,
                                   amount=sale.balance_due,
                                   currency=sale.currency if sale.currency else 'ILS',
                                   reference='دفع مبيعة من ' ~ (sale.customer.name if sale.customer else 'عميل') ~ ' - ' ~ (sale.sale_number or sale.id),
                                   notes='دفع مبيعة: ' ~ (sale.sale_number or sale.id) ~ ' - العميل: ' ~ (sale.customer.name if sale.customer else 'غير محدد'),
                                   customer_id=sale.customer_id) }}" class="dropdown-item text-success">
                <i class="fas fa-money-bill-wave mr-2"></i> إضافة دفعة
              </a>
              {% endif %}
              <div class="dropdown-divider"></div>
              {% if sale.is_archived %}
              <button type="button" class="dropdown-item" onclick="restoreSale({{ sale.id }})">
                <i class="fas fa-undo mr-2"></i> استعادة
              </button>
              {% else %}
              <button type="button" class="dropdown-item" onclick="archiveSale({{ sale.id }})">
                <i class="fas fa-archive mr-2"></i> أرشفة
              </button>
              {% endif %}
            </div>
          </div>
        </div>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="9" class="text-center text-muted py-4">لا توجد فواتير</td></tr>
    {% endfor %}
  </tbody>
</table>
            """,
            sales=sales_list,
            current_user=current_user,
            current_sort=current_sort,
            current_order=current_order,
        )
        pagination_html = render_template_string(
            """
{% if pagination and pagination.pages > 1 %}
<nav class="mt-3">
  <ul class="pagination justify-content-center">
    {% if pagination.has_prev %}
    <li class="page-item">
      <a class="page-link" href="{{ url_for('sales_bp.list_sales', page=pagination.prev_num, **query_args) }}">السابق</a>
    </li>
    {% endif %}
    {% for num in pagination.iter_pages() %}
      {% if num %}
      <li class="page-item {% if num == pagination.page %}active{% endif %}">
        <a class="page-link" href="{{ url_for('sales_bp.list_sales', page=num, **query_args) }}">{{ num }}</a>
      </li>
      {% else %}
      <li class="page-item disabled"><span class="page-link">…</span></li>
      {% endif %}
    {% endfor %}
    {% if pagination.has_next %}
    <li class="page-item">
      <a class="page-link" href="{{ url_for('sales_bp.list_sales', page=pagination.next_num, **query_args) }}">التالي</a>
    </li>
    {% endif %}
  </ul>
</nav>
{% endif %}
            """,
            pagination=pag,
            query_args=query_args,
        )
        summary_html = render_template_string(
            """
{% if summary %}
<div class="row g-3 mb-4">
  <div class="col-lg-3 col-md-6">
    <div class="card border-0 shadow-sm bg-primary text-white sales-summary-card">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <h6 class="card-title mb-1">إجمالي المبيعات</h6>
            <h3 class="mb-0 fw-bold">{{ "{:,.2f}".format(summary.total_sales) }} ₪</h3>
            <small class="opacity-75">{{ summary.sales_count }} فاتورة</small>
          </div>
          <div class="align-self-center">
            <i class="fas fa-file-invoice fa-2x opacity-75"></i>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-lg-3 col-md-6">
    <div class="card border-0 shadow-sm bg-success text-white sales-summary-card">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <h6 class="card-title mb-1">المدفوع</h6>
            <h3 class="mb-0 fw-bold">{{ "{:,.2f}".format(summary.total_paid) }} ₪</h3>
            <small class="opacity-75">{{ "{:.1f}".format((summary.total_paid / summary.total_sales * 100) if summary.total_sales > 0 else 0) }}%</small>
          </div>
          <div class="align-self-center">
            <i class="fas fa-check-circle fa-2x opacity-75"></i>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-lg-3 col-md-6">
    <div class="card border-0 shadow-sm bg-warning text-white sales-summary-card">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <h6 class="card-title mb-1">المستحق</h6>
            <h3 class="mb-0 fw-bold">{{ "{:,.2f}".format(summary.total_pending) }} ₪</h3>
            <small class="opacity-75">{{ "{:.1f}".format((summary.total_pending / summary.total_sales * 100) if summary.total_sales > 0 else 0) }}%</small>
          </div>
          <div class="align-self-center">
            <i class="fas fa-clock fa-2x opacity-75"></i>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-lg-3 col-md-6">
    <div class="card border-0 shadow-sm bg-info text-white sales-summary-card">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <h6 class="card-title mb-1">متوسط الفاتورة</h6>
            <h3 class="mb-0 fw-bold">{{ "{:,.2f}".format(summary.average_sale) }} ₪</h3>
            <small class="opacity-75">لكل فاتورة</small>
          </div>
          <div class="align-self-center">
            <i class="fas fa-chart-line fa-2x opacity-75"></i>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
{% endif %}
            """,
            summary=summary,
        )
        return jsonify(
            {
                "table_html": table_html,
                "pagination_html": pagination_html,
                "summary_html": summary_html,
                "total_filtered": total_filtered,
            }
        )

    if print_mode:
        context["pdf_export"] = True
        try:
            from weasyprint import HTML

            html_output = render_template("sales/list.html", **context)
            pdf_bytes = HTML(string=html_output, base_url=request.url_root).write_pdf()
            filename = f"sales_{_utc_now_naive().strftime('%Y%m%d_%H%M')}.pdf"
            return Response(
                pdf_bytes,
                mimetype="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{filename}"'},
            )
        except Exception as exc:
            current_app.logger.error("sales_print_pdf_error: %s", exc)
            context["pdf_export"] = False

    return render_template("sales/list.html", **context)

def _resolve_unit_price(product_id: int, warehouse_id: Optional[int]) -> float:
    prod = db.session.get(Product, product_id)
    try:
        return float(getattr(prod, "price", 0) or 0)
    except Exception:
        return 0.0

@sales_bp.route("/new", methods=["GET", "POST"], endpoint="create_sale")
@login_required
def create_sale():
    form = SaleForm()
    if request.method == "POST" and not form.validate_on_submit():
        current_app.logger.warning("Sale form errors: %s", form.errors)
        current_app.logger.debug("POST data: %r", request.form.to_dict(flat=False))
    if form.validate_on_submit():
        try:
            target_status = "CONFIRMED"
            require_stock = True
            lines_payload, err = _resolve_lines_from_form(form, require_stock=require_stock)
            if err:
                flash(f"❌ {err}", "danger")
                return render_template("sales/form.html", form=form, title="إنشاء فاتورة جديدة",
                                       products=Product.query.options(
                                           load_only(Product.id, Product.name, Product.sku, Product.price, Product.currency, Product.is_active)
                                       ).filter(Product.is_active == True).order_by(Product.name).all(),
                                       warehouses=Warehouse.query.options(
                                           load_only(Warehouse.id, Warehouse.name)
                                       ).order_by(Warehouse.name).all(),
                                       cost_centers=CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all())
            for d in lines_payload:
                if (d.get("unit_price") or 0) <= 0:
                    d["unit_price"] = _resolve_unit_price(d["product_id"], d.get("warehouse_id"))
            if require_stock:
                pairs = [(d["product_id"], d["warehouse_id"]) for d in lines_payload if d.get("warehouse_id")]
                _lock_stock_rows(pairs)

            notes_raw = str(form.notes.data or '').strip()
            if notes_raw in ('[]', '{}', 'null', 'None', ''):
                notes_clean = None
            else:
                notes_clean = notes_raw or None
            sale_tax = form.tax_rate.data or 0
            sale = Sale(
                sale_number=None,
                customer_id=form.customer_id.data,
                seller_id=current_user.id if current_user and current_user.is_authenticated else None,
                seller_employee_id=form.seller_employee_id.data,
                sale_date=form.sale_date.data or _utc_now_naive(),
                status=target_status,
                payment_status="PENDING",
                currency=(form.currency.data or "ILS").upper(),
                tax_rate=sale_tax,
                discount_total=form.discount_total.data or 0,
                shipping_address=(form.shipping_address.data or '').strip() or None,
                billing_address=(form.billing_address.data or '').strip() or None,
                shipping_cost=form.shipping_cost.data or 0,
                notes=notes_clean,
                cost_center_id=int(form.cost_center_id.data) if form.cost_center_id.data else None
            )
            if hasattr(Sale, 'receiver_name'):
                sale.receiver_name = form.receiver_name.data
            db.session.add(sale)
            db.session.flush()
            _safe_generate_number_after_flush(sale)
            _attach_lines(sale, lines_payload)
            db.session.flush()
            if require_stock and target_status == "CONFIRMED":
                _deduct_stock(sale)
            _log(sale, "CREATE", None, sale_to_dict(sale))
            # TaxEntry يُنشأ تلقائياً من حدث _sale_create_tax_entry في models بعد التأكيد
            db.session.commit()
            try:
                run_sale_gl_sync_after_commit(sale.id)
            except Exception as e:
                current_app.logger.error(f"⚠️ GL Sync Failed for Sale #{sale.id}: {e}")
                # Don't flash error to user as the sale is valid, but log it for admin
            flash("✅ تم إنشاء الفاتورة.", "success")
            return redirect(url_for("sales_bp.sale_detail", id=sale.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f"❌ خطأ قاعدة بيانات أثناء الحفظ: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ خطأ أثناء الحفظ: {e}", "danger")
    return render_template("sales/form.html", form=form, title="إنشاء فاتورة جديدة",
                           products=Product.query.order_by(Product.name).all(),
                           warehouses=Warehouse.query.order_by(Warehouse.name).all(),
                           cost_centers=CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all())

@sales_bp.route("/<int:id>", methods=["GET"], endpoint="sale_detail")
@login_required
def sale_detail(id: int):
    options = [
        joinedload(Sale.customer), joinedload(Sale.seller), joinedload(Sale.seller_employee),
        joinedload(Sale.lines).joinedload(SaleLine.product),
        joinedload(Sale.lines).joinedload(SaleLine.warehouse),
        joinedload(Sale.payments),
    ]
    sale = Sale.query.options(*options).filter(Sale.id == id).first()
    if not sale:
        padded = f"{id:04d}"
        alt = (
            Sale.query
            .filter(Sale.sale_number.ilike(f"%-{padded}"))
            .order_by(Sale.sale_date.desc(), Sale.id.desc())
            .first()
        )
        if alt:
            return redirect(url_for("sales_bp.sale_detail", id=alt.id))
        if id > 0:
            return redirect(url_for("sales_bp.list_sales", q=str(id)))
        abort(404)
    _format_sale(sale)
    for ln in sale.lines:
        ln.product_name = ln.product.name if ln.product else "-"
        ln.warehouse_name = ln.warehouse.name if ln.warehouse else "-"
        base_total = line_total_decimal(ln.quantity, ln.unit_price, ln.discount_rate)
        ln.line_total_value = float(base_total)
        ln.line_total_fmt = money_fmt(base_total)
    for p in sale.payments:
        p.date_formatted = p.payment_date.strftime("%Y-%m-%d") if getattr(p, "payment_date", None) else "-"
        lbl, cls = PAYMENT_STATUS_MAP.get(p.status, (p.status, ""))
        p.status_label, p.status_class = lbl, cls
        p.method_label = PAYMENT_METHOD_MAP.get(getattr(p, "method", ""), getattr(p, "method", ""))
    try:
        subtotal = sum(D(getattr(ln, "line_total_value", 0) or 0) for ln in sale.lines)
        sale_tax_rate = D(getattr(sale, "tax_rate", 0))
        sale_shipping = D(getattr(sale, "shipping_cost", 0))
        sale_discount_total = D(getattr(sale, "discount_total", 0))
        base_for_tax = (subtotal - sale_discount_total + sale_shipping).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        invoice_tax_amount = (base_for_tax * sale_tax_rate / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        grand_total = (base_for_tax + invoice_tax_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        sale.total_amount = float(grand_total)
        sale.balance_due = float((grand_total - D(getattr(sale, "total_paid", 0))).quantize(TWOPLACES, rounding=ROUND_HALF_UP))
        # حساب عرض بالشيكل عند الحاجة
        try:
            from models import convert_amount, PaymentStatus
            paid_ils = Decimal('0.00')
            for p in (sale.payments or []):
                if getattr(p, 'status', None) == PaymentStatus.COMPLETED.value:
                    amt = Decimal(str(getattr(p, 'total_amount', 0) or 0))
                    cur = (getattr(p, 'currency', None) or 'ILS').upper()
                    if cur == 'ILS':
                        paid_ils += amt
                    else:
                        try:
                            paid_ils += Decimal(str(convert_amount(amt, cur, 'ILS', getattr(p, 'payment_date', None))))
                        except Exception:
                            pass
            if (sale.currency or 'ILS').upper() == 'ILS':
                grand_total_ils = grand_total
            else:
                try:
                    grand_total_ils = Decimal(str(convert_amount(grand_total, (sale.currency or 'ILS'), 'ILS', getattr(sale, 'sale_date', None))))
                except Exception:
                    grand_total_ils = grand_total
            balance_due_ils = (grand_total_ils - paid_ils).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        except Exception:
            paid_ils = Decimal('0.00'); grand_total_ils = grand_total; balance_due_ils = (grand_total - paid_ils)
    except Exception:
        pass
    invoice = Invoice.query.filter_by(sale_id=id).first()
    return render_template(
        "sales/detail.html",
        sale=sale,
        invoice=invoice,
        status_map=STATUS_MAP,
        payment_method_map=PAYMENT_METHOD_MAP,
        payment_status_map=PAYMENT_STATUS_MAP,
        paid_ils=float(paid_ils.quantize(TWOPLACES, rounding=ROUND_HALF_UP)) if 'paid_ils' in locals() else 0.0,
        grand_total_ils=float(grand_total_ils.quantize(TWOPLACES, rounding=ROUND_HALF_UP)) if 'grand_total_ils' in locals() else float(grand_total),
        balance_due_ils=float(balance_due_ils.quantize(TWOPLACES, rounding=ROUND_HALF_UP)) if 'balance_due_ils' in locals() else float((grand_total - paid_ils).quantize(TWOPLACES, rounding=ROUND_HALF_UP)),
        show_ils_display=((sale.currency or 'ILS').upper() != 'ILS')
    )

@sales_bp.route("/<int:id>/payments", methods=["GET"], endpoint="sale_payments")
@login_required
def sale_payments(id: int):
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    q = (Payment.query.options(joinedload(Payment.splits))
         .filter(Payment.sale_id == id)
         .order_by(Payment.payment_date.desc(), Payment.id.desc()))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    sale = db.session.get(Sale, id) or abort(404)
    total_paid = getattr(sale, "total_paid", 0)
    if request.headers.get("Accept", "").startswith("application/json"):
        return jsonify({
            "payments": [p.to_dict() for p in pagination.items],
            "total_pages": pagination.pages,
            "current_page": pagination.page,
            "entity": {"type": "SALE", "id": id},
            "total_paid": float(total_paid),
        })
    return render_template(
        "payments/list.html",
        payments=pagination.items,
        pagination=pagination,
        entity_type="SALE",
        entity_id=id,
        total_paid=total_paid,
        query_args={"entity_type": "SALE", "entity_id": id}
    )

@sales_bp.route("/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_sale")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_SALES)
def edit_sale(id):
    sale = _get_or_404(Sale, id)
    if sale.status in ("CANCELLED", "REFUNDED"):
        flash("❌ لا يمكن تعديل فاتورة ملغاة/مرتجعة.", "danger")
        return redirect(url_for("sales_bp.sale_detail", id=sale.id))
    old = sale_to_dict(sale)
    form = SaleForm(obj=sale)
    if request.method == "GET":
        while len(form.lines.entries) < len(sale.lines):
            form.lines.append_entry()
        for idx, ln in enumerate(sale.lines):
            e = form.lines.entries[idx].form
            e.product_id.data = ln.product_id
            e.warehouse_id.data = ln.warehouse_id
            e.quantity.data = ln.quantity
            e.unit_price.data = ln.unit_price
            e.discount_rate.data = ln.discount_rate
            e.tax_rate.data = ln.tax_rate
            e.line_receiver.data = ln.line_receiver if hasattr(ln, 'line_receiver') else None
            e.note.data = ln.note
    if request.method == "POST" and not form.validate_on_submit():
        current_app.logger.warning("Sale form errors (edit): %s", form.errors)
        current_app.logger.debug("POST data (edit): %r", request.form.to_dict(flat=False))
    if form.validate_on_submit():
        try:
            was_confirmed = (sale.status == "CONFIRMED")
            if was_confirmed:
                _release_stock(sale)
            # الحالة دائماً CONFIRMED (تم حذف حقل status من الفورم)
            target_status = "CONFIRMED"
            require_stock = True
            lines_payload, err = _resolve_lines_from_form(form, require_stock=require_stock)
            if err:
                if was_confirmed:
                    _reserve_stock(sale)
                flash(f"❌ {err}", "danger")
                return render_template("sales/form.html", form=form, sale=sale, title="تعديل الفاتورة",
                                       products=Product.query.options(
                                           load_only(Product.id, Product.name, Product.sku, Product.price, Product.currency, Product.is_active)
                                       ).filter(Product.is_active == True).order_by(Product.name).all(),
                                       warehouses=Warehouse.query.options(
                                           load_only(Warehouse.id, Warehouse.name)
                                       ).order_by(Warehouse.name).all())
            # جلب السعر التلقائي فقط إذا كان 0 أو سالب
            for d in lines_payload:
                if (d.get("unit_price") or 0) <= 0:
                    d["unit_price"] = _resolve_unit_price(d["product_id"], d.get("warehouse_id"))
            if require_stock:
                pairs = [(d["product_id"], d["warehouse_id"]) for d in lines_payload if d.get("warehouse_id")]
                _lock_stock_rows(pairs)
            sale.customer_id = form.customer_id.data
            sale.seller_employee_id = form.seller_employee_id.data
            sale.sale_date = form.sale_date.data or sale.sale_date
            sale.status = target_status or sale.status
            sale.currency = (form.currency.data or sale.currency or "ILS").upper()
            sale_tax = form.tax_rate.data or 0
            sale.tax_rate = sale_tax
            sale.discount_total = form.discount_total.data or 0
            sale.shipping_address = (form.shipping_address.data or '').strip() or None
            sale.billing_address = (form.billing_address.data or '').strip() or None
            sale.shipping_cost = form.shipping_cost.data or 0
            sale.cost_center_id = int(form.cost_center_id.data) if form.cost_center_id.data else None
            if hasattr(sale, 'receiver_name'):
                sale.receiver_name = form.receiver_name.data
            # تنظيف notes من أي قيم غير صحيحة
            notes_raw = str(form.notes.data or '').strip()
            if notes_raw in ('[]', '{}', 'null', 'None', ''):
                sale.notes = None
            else:
                sale.notes = notes_raw or None
            _attach_lines(sale, lines_payload)
            db.session.flush()
            if require_stock:
                _reserve_stock(sale)
            _log(sale, "UPDATE", old, sale_to_dict(sale))
            db.session.commit()
            try:
                run_sale_gl_sync_after_commit(sale.id)
            except Exception as e:
                current_app.logger.error(f"⚠️ GL Sync Failed for Sale #{sale.id} (Update): {e}")
            # تحديث رصيد العميل
            try:
                from utils.customer_balance_updater import update_customer_balance_components
                update_customer_balance_components(sale.customer_id)
            except Exception as e:
                current_app.logger.error(f"Error updating customer balance: {e}")
                
            flash("✅ تم التعديل بنجاح.", "success")
            return redirect(url_for("sales_bp.sale_detail", id=sale.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f"❌ خطأ قاعدة بيانات أثناء التعديل: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ خطأ أثناء التعديل: {e}", "danger")
    return render_template("sales/form.html", form=form, sale=sale, title="تعديل الفاتورة",
                           products=Product.query.order_by(Product.name).all(),
                           warehouses=Warehouse.query.order_by(Warehouse.name).all(),
                           cost_centers=CostCenter.query.filter_by(is_active=True).order_by(CostCenter.code).all())

@sales_bp.route("/quick", methods=["POST"])
@login_required
def quick_sell():
    try:
        pid = int(request.form.get("product_id") or 0)
        wid = int(request.form.get("warehouse_id") or 0)
        qty = int(float(request.form.get("quantity") or 0))
        price_raw = request.form.get("unit_price")
        price = float(price_raw) if price_raw not in (None, "",) else 0.0
        customer_id = int(request.form.get("customer_id") or 0)
        seller_id = int(request.form.get("seller_id") or (current_user.id or 0))
        seller_employee_id_raw = request.form.get("seller_employee_id")
        seller_employee_id = int(seller_employee_id_raw) if seller_employee_id_raw and seller_employee_id_raw.isdigit() else None
        status = (request.form.get("status") or "DRAFT").upper()
        if not (pid and qty > 0 and customer_id and seller_id):
            flash("بيانات غير مكتملة للبيع السريع.", "danger")
            return redirect(url_for("sales_bp.list_sales"))
        chosen_wid = wid or _auto_pick_warehouse(pid, qty, preferred_wid=None)
        if status == "CONFIRMED":
            if not chosen_wid:
                flash("لا يوجد مخزن مناسب متاح لهذه الكمية.", "danger")
                return redirect(url_for("sales_bp.list_sales"))
            if _available_qty(pid, chosen_wid) < qty:
                flash("الكمية غير متوفرة في المخازن.", "danger")
                return redirect(url_for("sales_bp.list_sales"))
            _lock_stock_rows([(pid, chosen_wid)])
        if price <= 0:
            price = _resolve_unit_price(pid, chosen_wid)
        sale = Sale(
            sale_number=None,
            customer_id=customer_id,
            seller_id=seller_id,
            seller_employee_id=seller_employee_id,
            sale_date=_utc_now_naive(),
            status=status,
            currency="ILS"
        )
        db.session.add(sale)
        db.session.flush()
        _safe_generate_number_after_flush(sale)
        db.session.add(SaleLine(
            sale_id=sale.id, product_id=pid, warehouse_id=chosen_wid, quantity=qty,
            unit_price=price, discount_rate=0, tax_rate=0
        ))
        db.session.flush()
        if status == "CONFIRMED":
            _reserve_stock(sale)
        _log(sale, "CREATE", None, sale_to_dict(sale))
        db.session.commit()
        try:
            run_sale_gl_sync_after_commit(sale.id)
        except Exception:
            pass
        # تحديث رصيد العميل
        try:
            from utils.customer_balance_updater import update_customer_balance_components
            update_customer_balance_components(sale.customer_id)
        except Exception as e:
            current_app.logger.error(f"Error updating customer balance: {e}")
            
        flash("✅ تم إنشاء فاتورة سريعة.", "success")
        return redirect(url_for("sales_bp.sale_detail", id=sale.id))
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f"❌ فشل البيع السريع (قاعدة البيانات): {e}", "danger")
        return redirect(url_for("sales_bp.list_sales"))
    except Exception as e:
        db.session.rollback()
        flash(f"❌ فشل البيع السريع: {e}", "danger")
        return redirect(url_for("sales_bp.list_sales"))

 

@sales_bp.route("/<int:id>/status/<status>", methods=["POST"], endpoint="change_status")
@login_required
def change_status(id: int, status: str):
    sale = _get_or_404(Sale, id)
    status = (status or "").upper()
    valid = {
        "DRAFT": {"CONFIRMED", "CANCELLED"},
        "CONFIRMED": {"CANCELLED", "REFUNDED"},
        "CANCELLED": set(),
        "REFUNDED": set()
    }
    if status not in valid.get(sale.status, set()):
        flash("❌ حالة غير صالحة لهذا السجل.", "danger")
        return redirect(url_for("sales_bp.sale_detail", id=sale.id))
    try:
        if status == "CONFIRMED":
            lines = SaleLine.query.filter_by(sale_id=sale.id).all()
            pairs = []
            for ln in lines:
                pid, wid, qty = ln.product_id, ln.warehouse_id, int(ln.quantity or 0)
                if not wid:
                    wid = _auto_pick_warehouse(pid, qty, preferred_wid=None)
                    if not wid:
                        raise ValueError(f"لا يوجد مخزن مناسب متاح للمنتج ID={pid}.")
                    ln.warehouse_id = wid
                if _available_qty(pid, wid) < qty:
                    raise ValueError(f"الكمية غير متوفرة للمنتج ID={pid} في المخزن المحدد.")
                pairs.append((pid, wid))
            db.session.flush()
            _lock_stock_rows(pairs)
            sale.status = "CONFIRMED"
            db.session.flush()
            _reserve_stock(sale)
        elif status == "CANCELLED":
            _release_stock(sale)
            sale.status = "CANCELLED"
        elif status == "REFUNDED":
            _release_stock(sale)
            sale.status = "REFUNDED"
        db.session.commit()

        # تحديث رصيد العميل فوراً
        try:
            from utils.customer_balance_updater import update_customer_balance_components
            update_customer_balance_components(sale.customer_id)
        except Exception as e:
            current_app.logger.error(f"Error updating customer balance: {e}")

        flash("✅ تم تحديث الحالة.", "success")
    except (SQLAlchemyError, ValueError) as e:
        db.session.rollback()
        flash(f"❌ خطأ أثناء تحديث الحالة: {e}", "danger")
    return redirect(url_for("sales_bp.sale_detail", id=sale.id))

@sales_bp.route("/<int:id>/invoice", methods=["GET"], endpoint="generate_invoice")
@sales_bp.route("/<int:id>/receipt", methods=["GET"], endpoint="sale_receipt")
@login_required
def generate_invoice(id: int):
    sale = _get_or_404(Sale, id, load_options=[
        joinedload(Sale.customer), joinedload(Sale.seller), joinedload(Sale.seller_employee),
        joinedload(Sale.lines).joinedload(SaleLine.product),
        joinedload(Sale.lines).joinedload(SaleLine.warehouse),
    ])
    lines = []
    subtotal = Decimal("0.00")
    for ln in sale.lines:
        qty_dec = D(getattr(ln, "quantity", 0))
        unit_dec = D(getattr(ln, "unit_price", 0))
        rate_dec = D(getattr(ln, "discount_rate", 0))
        gross_total = (qty_dec * unit_dec).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        discount_amount = (gross_total * rate_dec / D(100)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        base_total = line_total_decimal(ln.quantity, ln.unit_price, ln.discount_rate)
        tr = D(getattr(ln, "tax_rate", 0))
        tax_amount = (base_total * tr / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        line_total = base_total
        lines.append({
            "obj": ln,
            "gross_total": gross_total,
            "discount_rate": rate_dec,
            "discount_rate_display": f"{float(rate_dec or 0):.2f}",
            "discount_amount": discount_amount,
            "base_total": base_total,
            "tax_amount": tax_amount,
            "line_total": line_total,
        })
        subtotal += base_total
    sale_tax_rate = D(getattr(sale, "tax_rate", 0))
    sale_shipping = D(getattr(sale, "shipping_cost", 0))
    sale_discount_total = D(getattr(sale, "discount_total", 0))
    subtotal_after_discount = (subtotal - sale_discount_total).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    base_for_tax = (subtotal_after_discount + sale_shipping).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    invoice_tax_amount = (base_for_tax * sale_tax_rate / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    grand_total = (base_for_tax + invoice_tax_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    try:
        sale.total_amount = float(grand_total)
        paid = D(getattr(sale, "total_paid", 0) or 0)
        # إعادة حساب المتبقي بدقة مع تحويل عملات الدفعات إلى عملة البيع عند العرض
        paid_display = D(0)
        sale_curr = (getattr(sale, "currency", None) or "ILS").upper()
        from models import convert_amount as _convert_amount
        for p in getattr(sale, "payments", []) or []:
            if getattr(p, "status", None) == "COMPLETED":
                splits = getattr(p, "splits", None) or []
                if splits:
                    for s in splits:
                        amt = D(str(getattr(s, "converted_amount", 0) or 0))
                        cur = (getattr(s, "converted_currency", None) or getattr(s, "currency", None) or getattr(p, "currency", None) or sale_curr).upper()
                        if amt <= 0:
                            amt = D(str(getattr(s, "amount", 0) or 0))
                            cur = (getattr(s, "currency", None) or getattr(p, "currency", None) or sale_curr).upper()
                        if cur != sale_curr:
                            try:
                                amt = D(str(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None))))
                            except Exception:
                                pass
                        paid_display += amt
                else:
                    amt = D(str(getattr(p, "total_amount", 0) or 0))
                    cur = (getattr(p, "currency", None) or sale_curr).upper()
                    if cur != sale_curr:
                        try:
                            amt = D(str(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None))))
                        except Exception:
                            pass
                    paid_display += amt
        sale.total_paid = float(paid_display.quantize(TWOPLACES, rounding=ROUND_HALF_UP))
        sale.balance_due = float((grand_total - paid_display).quantize(TWOPLACES, rounding=ROUND_HALF_UP))
    except Exception:
        pass
    
    # التحقق من نوع القالب (بسيط أو ملون)
    use_simple = request.args.get('simple', '').strip().lower() in ('1', 'true', 'yes')
    template_name = "sales/receipt_simple.html" if use_simple else "sales/receipt.html"
    
    return render_template(
        template_name,
        sale=sale,
        lines=lines,
        subtotal=subtotal,
        sale_discount_total=sale_discount_total,
        subtotal_after_discount=subtotal_after_discount,
        sale_tax_rate=sale_tax_rate,
        invoice_tax_amount=invoice_tax_amount,
        sale_shipping=sale_shipping,
        grand_total=grand_total,
        money_fmt=money_fmt,
    )
