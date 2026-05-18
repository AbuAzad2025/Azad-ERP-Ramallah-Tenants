
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from werkzeug.exceptions import BadRequest
from flask import Blueprint, Response, flash, jsonify, render_template, request, current_app, redirect, url_for, stream_with_context
from sqlalchemy.orm import class_mapper, joinedload, load_only
from sqlalchemy import func, Date, desc, or_, and_, case
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import inspect as sa_inspect
from extensions import db
from flask_login import login_required
import utils
from permissions_config.enums import SystemPermissions
from sqlalchemy.exc import SQLAlchemyError
import inspect as pyinspect

from models import (
    Customer, Supplier, Partner, Product, Warehouse, StockLevel, Expense,
    OnlinePreOrder, OnlinePayment, OnlineCart, Sale, SaleLine, SaleReturn, SaleStatus, ServiceRequest, ServiceStatus, Invoice, Payment,
    Shipment, PaymentDirection, PaymentStatus, PaymentSplit, PreOrder, ServicePart, ServiceTask, Employee, User, convert_amount
)
from utils.supplier_balance_updater import build_supplier_balance_view
from utils.partner_balance_updater import build_partner_balance_view
from utils.balance_calculator import build_customer_balance_view
reports_bp = Blueprint('reports_bp', __name__, url_prefix='/reports')

from reports import (
    advanced_report, ap_aging_report, ar_aging_report,
    payment_summary_report_ils, service_reports_report, top_products_report
)

def _parse_date(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _parse_date_like(x):
    if x is None:
        return None
    if isinstance(x, date):
        return x
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, str):
        try:
            return datetime.strptime(x.strip(), "%Y-%m-%d").date()
        except Exception:
            return None
    return None

_MODEL_LOOKUP = {
    "Sale": Sale,
    "Expense": Expense,
    "Invoice": Invoice,
    "Payment": Payment,
    "ServiceRequest": ServiceRequest,
    "OnlinePreOrder": OnlinePreOrder,
    "OnlinePayment": OnlinePayment,
    "Shipment": Shipment,
    "Customer": Customer,
    "Supplier": Supplier,
    "Partner": Partner,
    "Product": Product,
    "Warehouse": Warehouse,
    "StockLevel": StockLevel,
}

_DEFAULT_DATE_FIELD = {
    "Sale": "sale_date",
    "Expense": "date",
    "Invoice": "invoice_date",
    "Payment": "payment_date",
    "ServiceRequest": "received_at",
    "OnlinePreOrder": "created_at",
    "OnlinePayment": "created_at",
    "Shipment": "shipment_date",
    "Customer": "created_at",
    "Supplier": "created_at",
    "Partner": "created_at",
    "Product": "created_at",
    "Warehouse": "created_at",
    "StockLevel": "updated_at",
}

MODEL_LABELS = {
    "Sale": "المبيعات",
    "Expense": "المصاريف",
    "Invoice": "الفواتير",
    "Payment": "المدفوعات",
    "ServiceRequest": "طلبات الصيانة",
    "OnlinePreOrder": "الطلبات المسبقة (أونلاين)",
    "OnlinePayment": "مدفوعات أونلاين",
    "Shipment": "الشحنات",
    "Customer": "العملاء",
    "Supplier": "الموردون",
    "Partner": "الشركاء",
    "Product": "المنتجات",
    "Warehouse": "المستودعات",
    "StockLevel": "المخزون",
}

REPORT_CARDS = [
    {
        "key": "dynamic",
        "title": "تقرير ديناميكي",
        "description": "ابنِ تقريرك حسب الحقول والفلاتر",
        "icon": "fas fa-sliders-h",
        "endpoint": "reports_bp.dynamic_report",
        "css_class": "dynamic",
        "category": "analytics",
    },
    {
        "key": "customers",
        "title": "تقارير العملاء",
        "description": "إجمالي الفواتير / المدفوع / الرصيد",
        "icon": "fas fa-user-friends",
        "endpoint": "reports_bp.customers_report",
        "css_class": "customers",
        "category": "financial",
    },
    {
        "key": "suppliers",
        "title": "الموردون",
        "description": "الرصيد / المدفوع / الصافي",
        "icon": "fas fa-truck-loading",
        "endpoint": "reports_bp.suppliers_report",
        "css_class": "suppliers",
        "category": "financial",
    },
    {
        "key": "partners",
        "title": "الشركاء",
        "description": "الحصة / الرصيد / المدفوع",
        "icon": "fas fa-handshake",
        "endpoint": "reports_bp.partners_report",
        "css_class": "partners",
        "category": "financial",
    },
    {
        "key": "sales",
        "title": "المبيعات",
        "description": "ملخص وفواصل زمنية",
        "icon": "fas fa-cash-register",
        "endpoint": "reports_bp.sales",
        "css_class": "sales",
        "category": "financial",
    },
    {
        "key": "payments",
        "title": "ملخص المدفوعات",
        "description": "حسب طريقة الدفع",
        "icon": "fas fa-wallet",
        "endpoint": "reports_bp.payments_summary",
        "css_class": "payments",
        "category": "financial",
    },
    {
        "key": "top_products",
        "title": "أفضل المنتجات",
        "description": "كمية وإيراد",
        "icon": "fas fa-crown",
        "endpoint": "reports_bp.top_products",
        "css_class": "products",
        "category": "analytics",
    },
    {
        "key": "expenses",
        "title": "المصاريف",
        "description": "حسب النوع / الموظف",
        "icon": "fas fa-wallet",
        "endpoint": "reports_bp.expenses_report",
        "css_class": "expenses",
        "category": "financial",
    },
    {
        "key": "inventory",
        "title": "المخزون",
        "description": "منتج × مستودع",
        "icon": "fas fa-boxes",
        "endpoint": "reports_bp.inventory",
        "css_class": "inventory",
        "category": "inventory",
    },
    {
        "key": "below_min",
        "title": "تحت الحد الأدنى",
        "description": "الأصناف منخفضة المخزون",
        "icon": "fas fa-exclamation-triangle",
        "endpoint": "reports_bp.below_min_stock_report",
        "css_class": "below-min",
        "category": "inventory",
    },
    {
        "key": "shipments",
        "title": "الشحنات",
        "description": "قيمة وإجماليات",
        "icon": "fas fa-shipping-fast",
        "endpoint": "reports_bp.shipments",
        "css_class": "shipments",
        "category": "inventory",
    },
    {
        "key": "online",
        "title": "الأونلاين",
        "description": "طلبات / مدفوعات / سلال",
        "icon": "fas fa-globe",
        "endpoint": "reports_bp.online",
        "css_class": "online",
        "category": "analytics",
    },
    {
        "key": "ar_aging",
        "title": "أعمار الذمم (عملاء)",
        "description": "تفصيل حسب الفترات",
        "icon": "fas fa-user-clock",
        "endpoint": "reports_bp.ar_aging",
        "css_class": "ar",
        "category": "analytics",
    },
    {
        "key": "ap_aging",
        "title": "أعمار الذمم (موردون)",
        "description": "تفصيل حسب الفترات",
        "icon": "fas fa-truck-loading",
        "endpoint": "reports_bp.ap_aging",
        "css_class": "ap",
        "category": "analytics",
    },
    {
        "key": "service",
        "title": "تقارير الصيانة",
        "description": "عدد / إيراد / قطع / أجور",
        "icon": "fas fa-tools",
        "endpoint": "reports_bp.service_reports",
        "css_class": "service",
        "category": "analytics",
    },
    {
        "key": "invoices",
        "title": "الفواتير",
        "description": "شاملة / مدفوع / متأخرة",
        "icon": "fas fa-file-invoice-dollar",
        "endpoint": "reports_bp.invoices_report",
        "css_class": "invoices",
        "category": "financial",
    },
    {
        "key": "preorders",
        "title": "الطلبيات المسبقة",
        "description": "طلبيات / مدفوع / متبقي",
        "icon": "fas fa-clipboard-list",
        "endpoint": "reports_bp.preorders_report",
        "css_class": "preorders",
        "category": "financial",
    },
    {
        "key": "profit_loss",
        "title": "الأرباح والخسائر",
        "description": "P&L / هامش الربح",
        "icon": "fas fa-chart-line",
        "endpoint": "reports_bp.profit_loss_report",
        "css_class": "profit",
        "category": "financial",
    },
    {
        "key": "cash_flow",
        "title": "التدفقات النقدية",
        "description": "Cash Flow / وارد / صادر",
        "icon": "fas fa-money-bill-wave",
        "endpoint": "reports_bp.cash_flow_report",
        "css_class": "cashflow",
        "category": "financial",
    },
]

FIELD_LABELS: Dict[str, str] = {
    "id": "المعرف",
    "sale_number": "رقم الفاتورة",
    "sale_date": "اليوم",
    "customer_id": "العميل",
    "seller_id": "المندوب",
    "seller_employee_id": "الموظف البائع",
    "preorder_id": "طلب مسبق",
    "status": "الحالة",
    "payment_status": "حالة الدفع",
    "currency": "العملة",
    "discount_total": "إجمالي الخصم",
    "tax_rate": "نسبة الضريبة",
    "total_amount": "الإجمالي",
    "shipping_cost": "تكلفة الشحن",
    "billing_address": "عنوان الفاتورة",
    "shipping_address": "عنوان الشحن",
    "notes": "ملاحظات",
    "created_at": "تاريخ الإنشاء",
    "updated_at": "آخر تحديث",
    "date": "التاريخ",
    "type_id": "نوع المصروف",
    "amount": "المبلغ",
    "employee_id": "الوظف",
    "warehouse_id": "المستودع",
    "partner_id": "الشريك",
    "desc": "الوصف",
    "is_paid": "مدفوع؟",
    "invoice_date": "تاريخ الفاتورة",
    "total_invoiced": "إجمالي الفواتير",
    "net_balance": "الصافي",
    "total_paid": "المدفوع",
    "balance": "الرصيد",
    "payment_date": "تاريخ الدفع",
    "method": "طريقة الدفع",
    "received_at": "تاريخ الاستلام",
    "priority": "الأولوية",
    "mechanic_id": "الميكانيكي",
    "service_cost": "تكلفة الخدمة",
    "shipment_date": "تاريخ الشحنة",
    "number": "رقم الشحنة",
    "origin": "المنشأ",
    "destination": "الوجهة",
    "carrier": "الناقل",
    "tracking": "رقم التتبع",
    "value_before": "قيمة قبل التكاليف",
    "total_value": "القيمة الإجمالية",
    "product": "المنتج",
    "warehouse": "المستودع",
    "quantity": "الكمية",
    "reserved": "محجوز",
    "available": "المتوفر",
    "min_stock": "الحد الأدنى",
    "max_stock": "الحد الأقصى",
    "sales": "المبيعات",
    "sales_by_day": "مبيعات حسب اليوم",
    "date_range": "نطاق التاريخ",
    "start_date": "من",
    "end_date": "إلى",
    "refresh": "تحديث",
    "sales_table": "جدول المبيعات",
    "grand_total": "الإجمالي",
    "ap_aging": "أعمار الذمم (الموردون)",
    "ar_aging": "أعمار الذمم (العملاء)",
    "supplier": "المورد",
    "customer": "العميل",
    "customers": "العملاء",
    "service_reports": "تقارير الصيانة",
    "total_requests": "عدد الطلبات",
    "completed": "مكتملة",
    "revenue": "الإيراد",
    "parts": "قطع",
    "labor": "أجور",
    "total": "الإجمالي",
    "payments_summary": "ملخص المدفوعات حسب طريقة الدفع",
    "payment_method": "طريقة الدفع",
}

METHOD_LABELS_DEFAULT = {
    "cash": "نقدي",
    "card": "بطاقة",
    "bank": "حوالة بنكية",
    "BANK": "حوالة بنكية",
    "CHEQUE": "شيك",
    "cheque": "شيك",
    "online": "أونلاين",
    "other": "أخرى",
}

def _ensure_model(name: str):
    model = _MODEL_LOOKUP.get(name)
    if not model:
        raise BadRequest("نموذج غير معروف")
    return model

def _model_columns(model) -> List[str]:
    return [c.key for c in class_mapper(model).columns]

def _model_all_fields(model):
    cols = set(c.key for c in class_mapper(model).columns)
    hybrids = []
    for name in dir(model):
        if name.startswith("_") or name in cols:
            continue
        attr = pyinspect.getattr_static(model, name, None)
        if isinstance(attr, hybrid_property):
            hybrids.append(name)
    return sorted(list(cols.union(hybrids)))

def _is_selectable_field(model, name):
    mapper_cols = {c.key for c in class_mapper(model).columns}
    if name in mapper_cols:
        return True
    attr = pyinspect.getattr_static(model, name, None)
    if isinstance(attr, hybrid_property):
        try:
            _ = getattr(model, name).expression
            return True
        except Exception:
            return False
    return False

def _sanitize_fields(fields: List[str], allowed: List[str]) -> List[str]:
    allowed_set = set(allowed or [])
    return [f for f in (fields or []) if f in allowed_set]

def _sanitize_likes(like_filters: Dict[str, str], allowed: List[str]) -> Dict[str, str]:
    allowed_set = set(allowed or [])
    return {k: v for k, v in (like_filters or {}).items() if k in allowed_set and v not in (None, "")}

def _clamp_limit(v: Optional[int], default: int = 1000, max_v: int = 10000) -> int:
    try:
        n = int(v if v is not None else default)
    except Exception:
        n = default
    return max(1, min(n, max_v))

def _to_ils(amount, currency, ref_date):
    value = Decimal(str(amount or 0))
    if currency and currency != "ILS":
        try:
            return convert_amount(value, currency, "ILS", ref_date)
        except Exception:
            return value
    return value

def _norm_currency(code):
    return (code or "ILS").upper()

def _to_ils_with_fx(amount, currency, fx_used, ref_date):
    value = Decimal(str(amount or 0))
    code = _norm_currency(currency)
    if code == "ILS":
        return value
    if fx_used:
        try:
            return value * Decimal(str(fx_used))
        except Exception:
            pass
    try:
        return convert_amount(value, code, "ILS", ref_date)
    except Exception:
        return value

def _currency_acc_add(acc: dict, currency, **kv):
    code = _norm_currency(currency)
    row = acc.get(code)
    if not row:
        row = {"currency": code}
        acc[code] = row
    for k, v in (kv or {}).items():
        row[k] = row.get(k, Decimal("0.00")) + Decimal(str(v or 0))

def _currency_acc_to_list(acc: dict) -> list:
    out = []
    for code in sorted((acc or {}).keys()):
        row = acc[code]
        out_row = {}
        for k, v in (row or {}).items():
            if k == "currency":
                out_row[k] = v
            else:
                out_row[k] = float(v or 0)
        out.append(out_row)
    return out

@reports_bp.route("/", methods=["GET"], endpoint="universal")
@reports_bp.route("", methods=["GET"], endpoint="index")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def reports_index():
    summary_counts = {
        "total": len(REPORT_CARDS),
        "financial": sum(1 for card in REPORT_CARDS if card["category"] == "financial"),
        "inventory": sum(1 for card in REPORT_CARDS if card["category"] == "inventory"),
        "analytics": sum(1 for card in REPORT_CARDS if card["category"] == "analytics"),
    }
    return render_template(
        "reports/index.html",
        model_names=list(_MODEL_LOOKUP.keys()),
        defaults=_DEFAULT_DATE_FIELD,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
        report_cards=REPORT_CARDS,
        reports_summary=summary_counts,
    )

@reports_bp.route("/dynamic", methods=["GET", "POST"])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_REPORTS)
def dynamic_report():
    model_names = list(_MODEL_LOOKUP.keys())
    if request.method == "POST":
        table = (request.form.get("table") or "").strip()
        selected_fields = request.form.getlist("selected_fields") or []
        date_field = (request.form.get("date_field") or "").strip()
        start_date = _parse_date(request.form.get("start_date"))
        end_date = _parse_date(request.form.get("end_date"))
        limit = _clamp_limit(request.form.get("limit"))
        if limit > 2000:
            flash("تم تقليص الحد الأقصى للصفوف إلى 2000 للحفاظ على الأداء.", "warning")
            limit = 2000
        try:
            model = _ensure_model(table)
        except BadRequest as e:
            flash(str(e), 'danger')
            return render_template("reports/dynamic.html", data=None, summary=None, columns=selected_fields, model_names=model_names, selected_table=None, defaults=_DEFAULT_DATE_FIELD, date_field=date_field, start_date=request.form.get("start_date", ""), end_date=request.form.get("end_date", ""), like_filters={}, limit=limit, FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS), 400
        cols = [c for c in _model_all_fields(model) if _is_selectable_field(model, c)]
        all_fields = _model_all_fields(model)
        selected_fields = _sanitize_fields(selected_fields, all_fields) or None
        like_filters = {k: v for k, v in request.form.items() if k not in {"csrf_token", "table", "date_field", "start_date", "end_date", "selected_fields", "limit"} and v not in (None, "")}
        like_filters = _sanitize_likes(like_filters, cols)
        if date_field and date_field not in cols:
            date_field = ""
        if not date_field:
            df = _DEFAULT_DATE_FIELD.get(table)
            date_field = df if df in cols else None
        try:
            rpt = advanced_report(model=model, date_field=date_field or None, start_date=start_date, end_date=end_date, filters=None, like_filters=like_filters or None, columns=selected_fields, aggregates={"count": ["id"]})
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template("reports/dynamic.html", data=None, summary=None, columns=(selected_fields or []), model_names=model_names, selected_table=table, defaults=_DEFAULT_DATE_FIELD, date_field=(date_field or ""), start_date=request.form.get("start_date", ""), end_date=request.form.get("end_date", ""), like_filters=like_filters, limit=limit, FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS), 400
        data = rpt.get("data") or []
        if limit:
            data = data[:limit]
        return render_template("reports/dynamic.html", data=data, summary=rpt.get("summary") or {}, columns=(selected_fields or []), model_names=model_names, selected_table=table, defaults=_DEFAULT_DATE_FIELD, date_field=(date_field or ""), start_date=request.form.get("start_date", ""), end_date=request.form.get("end_date", ""), like_filters=like_filters, limit=limit, FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS)
    selected_table = model_names[0] if model_names else None
    return render_template("reports/dynamic.html", data=None, summary=None, columns=[], model_names=model_names, selected_table=selected_table, defaults=_DEFAULT_DATE_FIELD, date_field=_DEFAULT_DATE_FIELD.get(selected_table, "") if selected_table else "", start_date="", end_date="", like_filters={}, limit=1000, FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS)

@reports_bp.route("/below_min_stock", endpoint="below_min_stock_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def below_min_stock_report():
    try:
        from models import Warehouse
        
        q = (
            db.session.query(StockLevel)
            .join(Product, StockLevel.product_id == Product.id)
            .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
            .filter(Product.is_active.is_(True))
            .filter(StockLevel.min_stock.isnot(None))
            .filter(StockLevel.quantity < StockLevel.min_stock)
            .options(joinedload(StockLevel.product), joinedload(StockLevel.warehouse))
            .order_by(Product.name.asc(), Warehouse.name.asc())
        )
        rows = q.all()
        
        grouped: Dict[int, Dict[str, Any]] = {}
        for sl in rows:
            pid = int(sl.product_id or 0)
            if pid not in grouped:
                grouped[pid] = {
                    "product": sl.product,
                    "stocks": [],
                }
            grouped[pid]["stocks"].append(
                {
                    "warehouse_id": sl.warehouse_id,
                    "warehouse_name": sl.warehouse.name if sl.warehouse else "غير محدد",
                    "quantity": int(sl.quantity or 0),
                    "min_stock": int(sl.min_stock or 0),
                    "available": int(sl.quantity or 0) - int(getattr(sl, "reserved_quantity", 0) or 0),
                }
            )

        data = []
        for pid, g in grouped.items():
            p = g.get("product")
            stocks = g.get("stocks") or []
            data.append(
                {
                    "id": getattr(p, "id", pid),
                    "name": getattr(p, "name", None),
                    "sku": getattr(p, "sku", "") or "",
                    "total_on_hand": sum(int(s.get("quantity") or 0) for s in stocks),
                    "stocks": stocks,
                }
            )
        data.sort(key=lambda x: (x.get("name") or "").lower())
        
        return render_template(
            "reports/below_min_stock.html",
            data=data,
            FIELD_LABELS=FIELD_LABELS,
            MODEL_LABELS=MODEL_LABELS,
        )
    except SQLAlchemyError as err:
        current_app.logger.error("DB error: %s", err)
        flash("خطأ في قاعدة البيانات", "danger")
        return redirect(url_for("reports_bp.index"))

@reports_bp.route("/shipments", methods=["GET"], endpoint="shipments")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def shipments_report():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    start = None
    end = None
    try:
        if start_str:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
        if end_str:
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
    except Exception:
        flash("❌ صيغة التاريخ غير صحيحة", "danger")
    q = db.session.query(Shipment)
    if start:
        q = q.filter(Shipment.shipment_date >= start)
    if end:
        q = q.filter(Shipment.shipment_date <= end)
    rows = q.order_by(Shipment.shipment_date.desc()).all()
    by_currency = {}
    value_before_ils_total = Decimal("0.00")
    total_value_ils_total = Decimal("0.00")
    for s in rows:
        ref_dt = getattr(s, "shipment_date", None) or getattr(s, "date", None)
        vb = Decimal(str(getattr(s, "value_before", 0) or 0))
        tv = Decimal(str(getattr(s, "total_value", 0) or 0))
        vb_ils = _to_ils_with_fx(vb, getattr(s, "currency", None), getattr(s, "fx_rate_used", None), ref_dt)
        tv_ils = _to_ils_with_fx(tv, getattr(s, "currency", None), getattr(s, "fx_rate_used", None), ref_dt)
        s.value_before_ils = float(vb_ils)
        s.total_value_ils = float(tv_ils)
        _currency_acc_add(
            by_currency,
            getattr(s, "currency", None),
            value_before=vb,
            total_value=tv,
            value_before_ils=vb_ils,
            total_value_ils=tv_ils,
        )
        value_before_ils_total += vb_ils
        total_value_ils_total += tv_ils

    totals = {
        "shipments": len(rows),
        "by_currency": _currency_acc_to_list(by_currency),
        "value_before_ils": float(value_before_ils_total),
        "total_value_ils": float(total_value_ils_total),
    }
    return render_template(
        "reports/shipments.html",
        data=rows,
        totals=totals,
        start=start_str,
        end=end_str,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/online", endpoint="online")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def online_report():
    orders_count = db.session.query(func.count(OnlinePreOrder.id)).scalar() or 0
    carts_active = db.session.query(func.count(OnlineCart.id)).filter(OnlineCart.status == "ACTIVE").scalar() or 0

    ord_currency_expr = func.upper(func.coalesce(OnlinePreOrder.currency, "ILS"))
    ord_fx_mult = case(
        (ord_currency_expr == "ILS", 1),
        else_=func.coalesce(OnlinePreOrder.fx_rate_used, 1),
    )
    orders_rows = (
        db.session.query(
            ord_currency_expr.label("currency"),
            func.count(OnlinePreOrder.id).label("count"),
            func.coalesce(func.sum(OnlinePreOrder.total_amount), 0).label("total"),
            func.coalesce(func.sum(OnlinePreOrder.total_amount * ord_fx_mult), 0).label("total_ils"),
        )
        .group_by(ord_currency_expr)
        .order_by(ord_currency_expr.asc())
        .all()
    )

    pay_currency_expr = func.upper(func.coalesce(OnlinePayment.currency, "ILS"))
    pay_fx_mult = case(
        (pay_currency_expr == "ILS", 1),
        else_=func.coalesce(OnlinePayment.fx_rate_used, 1),
    )
    payments_rows = (
        db.session.query(
            pay_currency_expr.label("currency"),
            func.count(OnlinePayment.id).label("count"),
            func.coalesce(func.sum(OnlinePayment.amount), 0).label("total"),
            func.coalesce(func.sum(OnlinePayment.amount * pay_fx_mult), 0).label("total_ils"),
        )
        .filter(OnlinePayment.status == "SUCCESS")
        .group_by(pay_currency_expr)
        .order_by(pay_currency_expr.asc())
        .all()
    )

    orders_total_ils = float(sum((r.total_ils or 0) for r in orders_rows) or 0)
    payments_total_ils = float(sum((r.total_ils or 0) for r in payments_rows) or 0)
    return render_template(
        "reports/online.html",
        orders_count=orders_count,
        orders_by_currency=[{"currency": r.currency, "count": int(r.count or 0), "total": float(r.total or 0), "total_ils": float(r.total_ils or 0)} for r in orders_rows],
        payments_by_currency=[{"currency": r.currency, "count": int(r.count or 0), "total": float(r.total or 0), "total_ils": float(r.total_ils or 0)} for r in payments_rows],
        orders_total_ils=orders_total_ils,
        payments_total_ils=payments_total_ils,
        carts_active=carts_active,
        FIELD_LABELS=FIELD_LABELS
    )

@reports_bp.route("/sales", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def sales():
    return sales_advanced_report()

@reports_bp.route("/payments-summary", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def payments_summary():
    return payments_advanced_report()


@reports_bp.route("/invoices", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def invoices_report():
    from datetime import datetime
    from decimal import Decimal
    
    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    customer_id = request.args.get("customer_id")
    kind = request.args.get("kind")
    status_filter = request.args.get("status")
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    
    query = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.supplier),
        joinedload(Invoice.partner),
        joinedload(Invoice.lines),
        joinedload(Invoice.sale).joinedload(Sale.seller_employee),
        joinedload(Invoice.sale).joinedload(Sale.seller),
    )
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        query = query.filter(Invoice.invoice_date >= start_dt)
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        query = query.filter(Invoice.invoice_date <= end_dt)
    if customer_id:
        query = query.filter(Invoice.customer_id == int(customer_id))
    if kind:
        query = query.filter(Invoice.kind == kind)
    if status_filter:
        query = query.filter(Invoice.status == (status_filter or '').strip().upper())
    
    invoices = query.order_by(Invoice.invoice_date.desc()).all()
    
    by_currency = {}
    total_amount = Decimal('0')
    total_paid = Decimal('0')
    balance_due = Decimal('0')
    overdue_count = 0
    credit_notes = 0
    
    today = datetime.now().date()
    for inv in invoices:
        amount = Decimal(str(getattr(inv, "total_amount", None) or 0))
        if amount == 0:
            amount = Decimal(str(inv.computed_total or 0))
        if str(getattr(inv, "kind", "") or "").upper() == "CREDIT_NOTE":
            amount = -abs(amount)
        paid = Decimal(str(inv.total_paid or 0))
        ref_dt = getattr(inv, "invoice_date", None)
        amount_ils = _to_ils_with_fx(amount, getattr(inv, "currency", None), getattr(inv, "fx_rate_used", None), ref_dt)
        paid_ils = _to_ils_with_fx(paid, getattr(inv, "currency", None), getattr(inv, "fx_rate_used", None), ref_dt)
        due = amount - paid
        due_ils = amount_ils - paid_ils
        inv.total_amount_display = float(amount)
        inv.amount_ils = float(amount_ils)
        inv.paid_ils = float(paid_ils)
        inv.balance_due_ils = float(due_ils)
        total_amount += amount_ils
        total_paid += paid_ils
        balance_due += due_ils

        _currency_acc_add(
            by_currency,
            getattr(inv, "currency", None),
            total_amount=amount,
            total_amount_ils=amount_ils,
            total_paid=paid,
            total_paid_ils=paid_ils,
            balance_due=due,
            balance_due_ils=due_ils,
        )
        
        if inv.due_date and inv.due_date.date() < today and inv.status != 'PAID':
            overdue_count += 1
        if inv.kind == 'CREDIT_NOTE':
            credit_notes += 1
    
    summary = {
        'total_invoices': len(invoices),
        'total_amount': float(total_amount),
        'total_paid': float(total_paid),
        'balance_due': float(balance_due),
        'overdue_count': overdue_count,
        'credit_notes': credit_notes,
        "by_currency": _currency_acc_to_list(by_currency),
    }
    
    all_customers = Customer.query.filter_by(is_archived=False).order_by(Customer.name).all()
    
    return render_template(
        "reports/invoices.html",
        invoices=invoices,
        summary=summary,
        all_customers=all_customers
    )


@reports_bp.route("/preorders", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def preorders_report():
    from datetime import datetime
    from decimal import Decimal
    
    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    customer_id = request.args.get("customer_id")
    status_filter = request.args.get("status")
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    
    query = PreOrder.query.options(
        joinedload(PreOrder.customer),
        joinedload(PreOrder.product)
    )
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        query = query.filter(PreOrder.preorder_date >= start_dt)
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        query = query.filter(PreOrder.preorder_date <= end_dt)
    if customer_id:
        query = query.filter(PreOrder.customer_id == int(customer_id))
    if status_filter:
        query = query.filter(PreOrder.status == status_filter)
    
    preorders = query.order_by(PreOrder.preorder_date.desc()).all()

    preorder_ids = [int(p.id) for p in (preorders or []) if getattr(p, "id", None)]
    paid_ils_by_preorder = {}
    if preorder_ids:
        pay_currency_expr = func.upper(func.coalesce(Payment.currency, "ILS"))
        pay_fx_mult = case(
            (pay_currency_expr == "ILS", 1),
            else_=func.coalesce(Payment.fx_rate_used, 1),
        )
        paid_rows = (
            db.session.query(
                Payment.preorder_id,
                func.coalesce(func.sum(Payment.total_amount * pay_fx_mult), 0).label("paid_ils"),
            )
            .filter(
                Payment.preorder_id.in_(preorder_ids),
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.direction == PaymentDirection.IN.value,
            )
            .group_by(Payment.preorder_id)
            .all()
        )
        paid_ils_by_preorder = {int(pid): Decimal(str(paid_ils or 0)) for pid, paid_ils in paid_rows}

    by_currency = {}
    total_amount_ils = Decimal("0.00")
    total_paid_ils = Decimal("0.00")
    balance_due_ils = Decimal("0.00")

    for pre in preorders:
        ref_dt = getattr(pre, "preorder_date", None) or getattr(pre, "created_at", None)
        total_raw = Decimal(str(getattr(pre, "total_amount", 0) or 0))
        total_ils = _to_ils_with_fx(total_raw, getattr(pre, "currency", None), getattr(pre, "fx_rate_used", None), ref_dt)
        paid_ils = paid_ils_by_preorder.get(int(pre.id), Decimal("0.00"))
        due_ils = total_ils - paid_ils

        pre.total_amount_ils = float(total_ils)
        pre.total_paid_ils = float(paid_ils)
        pre.balance_due_ils = float(due_ils)

        _currency_acc_add(
            by_currency,
            getattr(pre, "currency", None),
            total_amount=total_raw,
            total_amount_ils=total_ils,
        )
        total_amount_ils += total_ils
        total_paid_ils += paid_ils
        balance_due_ils += due_ils

    summary = {
        "total_preorders": len(preorders),
        "by_currency": _currency_acc_to_list(by_currency),
        "total_amount_ils": float(total_amount_ils),
        "total_paid_ils": float(total_paid_ils),
        "balance_due_ils": float(balance_due_ils),
    }
    
    all_customers = Customer.query.filter_by(is_archived=False).order_by(Customer.name).all()
    
    return render_template(
        "reports/preorders.html",
        preorders=preorders,
        summary=summary,
        all_customers=all_customers
    )


@reports_bp.route("/profit-loss", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def profit_loss_report():
    from datetime import datetime, timedelta
    from decimal import Decimal
    
    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    
    query_sales = Sale.query.filter(Sale.status == 'CONFIRMED')
    query_services = ServiceRequest.query.filter(ServiceRequest.status == 'COMPLETED')
    query_returns = SaleReturn.query.filter(SaleReturn.status == 'CONFIRMED')
    query_expenses = Expense.query
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        query_sales = query_sales.filter(Sale.sale_date >= start_dt)
        query_services = query_services.filter(ServiceRequest.created_at >= start_dt)
        query_returns = query_returns.filter(SaleReturn.created_at >= start_dt)
        query_expenses = query_expenses.filter(Expense.created_at >= start_dt)
    
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        query_sales = query_sales.filter(Sale.sale_date <= end_dt)
        query_services = query_services.filter(ServiceRequest.created_at <= end_dt)
        query_returns = query_returns.filter(SaleReturn.created_at <= end_dt)
        query_expenses = query_expenses.filter(Expense.created_at <= end_dt)
    
    sales_currency_expr = func.upper(func.coalesce(Sale.currency, "ILS"))
    sales_fx_mult = case(
        (sales_currency_expr == "ILS", 1),
        else_=func.coalesce(Sale.fx_rate_used, 1),
    )
    # إيراد المبيعات بدون ضريبة (أساس قابل للضريبة + الشحن) لاحتساب الربح محاسبياً
    sales_revenue_excl_vat = (
        (func.coalesce(Sale.total_amount, 0) - func.coalesce(Sale.shipping_cost, 0))
        / (1 + func.coalesce(Sale.tax_rate, 0) / 100.0)
        + func.coalesce(Sale.shipping_cost, 0)
    )
    sales_amount_ils_expr = sales_revenue_excl_vat * sales_fx_mult

    srv_currency_expr = func.upper(func.coalesce(ServiceRequest.currency, "ILS"))
    srv_fx_mult = case(
        (srv_currency_expr == "ILS", 1),
        else_=func.coalesce(ServiceRequest.fx_rate_used, 1),
    )
    srv_amount_ils_expr = func.coalesce(ServiceRequest.total_amount, 0) * srv_fx_mult

    ret_currency_expr = func.upper(func.coalesce(SaleReturn.currency, "ILS"))
    ret_fx_mult = case(
        (ret_currency_expr == "ILS", 1),
        else_=func.coalesce(SaleReturn.fx_rate_used, 1),
    )
    ret_amount_ils_expr = func.coalesce(SaleReturn.total_amount, 0) * ret_fx_mult

    exp_currency_expr = func.upper(func.coalesce(Expense.currency, "ILS"))
    exp_fx_mult = case(
        (exp_currency_expr == "ILS", 1),
        else_=func.coalesce(Expense.fx_rate_used, 1),
    )
    exp_amount_ils_expr = func.coalesce(Expense.amount, 0) * exp_fx_mult

    sales_revenue_ils = Decimal(str(query_sales.with_entities(func.coalesce(func.sum(sales_amount_ils_expr), 0)).scalar() or 0))
    service_revenue_ils = Decimal(str(query_services.with_entities(func.coalesce(func.sum(srv_amount_ils_expr), 0)).scalar() or 0))
    returns_total_ils = Decimal(str(query_returns.with_entities(func.coalesce(func.sum(ret_amount_ils_expr), 0)).scalar() or 0))

    from models import ExpenseType

    type_name_expr = func.coalesce(ExpenseType.name, "")
    salary_cond = or_(type_name_expr.like("%رواتب%"), type_name_expr.like("%راتب%"))
    exp_q = query_expenses.join(ExpenseType, Expense.type_id == ExpenseType.id, isouter=True)
    exp_agg = exp_q.with_entities(
        func.coalesce(func.sum(exp_amount_ils_expr), 0).label("total"),
        func.coalesce(func.sum(case((salary_cond, exp_amount_ils_expr), else_=0)), 0).label("salary"),
        func.coalesce(func.sum(case((and_(~salary_cond, Expense.type_id.isnot(None)), exp_amount_ils_expr), else_=0)), 0).label("operational"),
        func.coalesce(func.sum(case((Expense.type_id.is_(None), exp_amount_ils_expr), else_=0)), 0).label("other"),
    ).first()

    total_expenses_ils = Decimal(str(getattr(exp_agg, "total", 0) or 0))
    salary_expenses_ils = Decimal(str(getattr(exp_agg, "salary", 0) or 0))
    operational_expenses_ils = Decimal(str(getattr(exp_agg, "operational", 0) or 0))
    other_expenses_ils = Decimal(str(getattr(exp_agg, "other", 0) or 0))

    other_revenue_ils = Decimal("0.00")
    total_revenue_ils = sales_revenue_ils + service_revenue_ils + other_revenue_ils - returns_total_ils
    net_profit_ils = total_revenue_ils - total_expenses_ils
    profit_margin = (float(net_profit_ils) / float(total_revenue_ils) * 100) if float(total_revenue_ils) > 0 else 0

    sales_by_currency = (
        query_sales.with_entities(
            sales_currency_expr.label("currency"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("amount"),
            func.coalesce(func.sum(sales_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(sales_currency_expr)
        .order_by(sales_currency_expr.asc())
        .all()
    )
    services_by_currency = (
        query_services.with_entities(
            srv_currency_expr.label("currency"),
            func.coalesce(func.sum(ServiceRequest.total_amount), 0).label("amount"),
            func.coalesce(func.sum(srv_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(srv_currency_expr)
        .order_by(srv_currency_expr.asc())
        .all()
    )
    returns_by_currency = (
        query_returns.with_entities(
            ret_currency_expr.label("currency"),
            func.coalesce(func.sum(SaleReturn.total_amount), 0).label("amount"),
            func.coalesce(func.sum(ret_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(ret_currency_expr)
        .order_by(ret_currency_expr.asc())
        .all()
    )
    expenses_by_currency = (
        query_expenses.with_entities(
            exp_currency_expr.label("currency"),
            func.coalesce(func.sum(Expense.amount), 0).label("amount"),
            func.coalesce(func.sum(exp_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(exp_currency_expr)
        .order_by(exp_currency_expr.asc())
        .all()
    )

    data = {
        "total_revenue_ils": float(total_revenue_ils),
        "sales_revenue_ils": float(sales_revenue_ils),
        "service_revenue_ils": float(service_revenue_ils),
        "other_revenue_ils": float(other_revenue_ils),
        "returns_total_ils": float(returns_total_ils),
        "total_expenses_ils": float(total_expenses_ils),
        "operational_expenses_ils": float(operational_expenses_ils),
        "salary_expenses_ils": float(salary_expenses_ils),
        "other_expenses_ils": float(other_expenses_ils),
        "net_profit_ils": float(net_profit_ils),
        "profit_margin": profit_margin,
        "sales_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in sales_by_currency],
        "services_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in services_by_currency],
        "returns_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in returns_by_currency],
        "expenses_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in expenses_by_currency],
    }
    
    return render_template(
        "reports/profit_loss.html",
        data=data,
        start_date=sd.isoformat() if sd else '',
        end_date=ed.isoformat() if ed else ''
    )


@reports_bp.route("/cash-flow", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def cash_flow_report():
    from datetime import datetime
    from decimal import Decimal
    
    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    
    query_pay_in = Payment.query.filter(
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    query_pay_out = Payment.query.filter(
        Payment.direction == PaymentDirection.OUT.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    query_expenses = Expense.query
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        query_pay_in = query_pay_in.filter(Payment.payment_date >= start_dt)
        query_pay_out = query_pay_out.filter(Payment.payment_date >= start_dt)
    
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        query_pay_in = query_pay_in.filter(Payment.payment_date <= end_dt)
        query_pay_out = query_pay_out.filter(Payment.payment_date <= end_dt)
    
    pay_in_currency_expr = func.upper(func.coalesce(Payment.currency, "ILS"))
    pay_in_fx_mult = case(
        (pay_in_currency_expr == "ILS", 1),
        else_=func.coalesce(Payment.fx_rate_used, 1),
    )
    pay_amount_ils_expr = func.coalesce(Payment.total_amount, 0) * pay_in_fx_mult

    payments_in = query_pay_in.all()
    payments_out = query_pay_out.all()

    for p in payments_in:
        try:
            p.amount_ils = float(_to_ils_with_fx(p.total_amount, getattr(p, "currency", None), getattr(p, "fx_rate_used", None), getattr(p, "payment_date", None)))
        except Exception:
            p.amount_ils = float(p.total_amount or 0)
    for p in payments_out:
        try:
            p.amount_ils = float(_to_ils_with_fx(p.total_amount, getattr(p, "currency", None), getattr(p, "fx_rate_used", None), getattr(p, "payment_date", None)))
        except Exception:
            p.amount_ils = float(p.total_amount or 0)

    customer_payments = Decimal(str(sum((getattr(p, "amount_ils", 0) or 0) for p in payments_in) or 0))
    cash_sales = Decimal('0')
    other_inflow = Decimal('0')
    
    total_inflow = customer_payments + cash_sales + other_inflow
    
    supplier_payments = Decimal('0')
    salaries_paid = Decimal('0')
    expenses_paid = Decimal('0')
    other_outflow = Decimal('0')

    for p in payments_out:
        amt = Decimal(str(getattr(p, "amount_ils", 0) or 0))
        et = getattr(p, 'entity_type', None)
        if str(getattr(et, 'value', et)).upper() == 'SUPPLIER':
            supplier_payments += amt
            continue
        exp = getattr(p, 'expense', None)
        if exp is not None:
            type_name = getattr(getattr(exp, 'expense_type', None), 'name', '') or getattr(getattr(exp, 'type', None), 'name', '')
            if type_name and ('رواتب' in type_name or 'راتب' in type_name):
                salaries_paid += amt
            else:
                expenses_paid += amt
        else:
            other_outflow += amt
    
    total_outflow = supplier_payments + salaries_paid + expenses_paid + other_outflow
    net_cash_flow = total_inflow - total_outflow

    in_by_currency_rows = (
        query_pay_in.with_entities(
            pay_in_currency_expr.label("currency"),
            func.coalesce(func.sum(Payment.total_amount), 0).label("amount"),
            func.coalesce(func.sum(pay_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(pay_in_currency_expr)
        .order_by(pay_in_currency_expr.asc())
        .all()
    )
    out_by_currency_rows = (
        query_pay_out.with_entities(
            pay_in_currency_expr.label("currency"),
            func.coalesce(func.sum(Payment.total_amount), 0).label("amount"),
            func.coalesce(func.sum(pay_amount_ils_expr), 0).label("amount_ils"),
        )
        .group_by(pay_in_currency_expr)
        .order_by(pay_in_currency_expr.asc())
        .all()
    )
    
    data = {
        'total_inflow': float(total_inflow),
        'customer_payments': float(customer_payments),
        'cash_sales': float(cash_sales),
        'other_inflow': float(other_inflow),
        'total_outflow': float(total_outflow),
        'supplier_payments': float(supplier_payments),
        'salaries_paid': float(salaries_paid),
        'expenses_paid': float(expenses_paid),
        'other_outflow': float(other_outflow),
        'net_cash_flow': float(net_cash_flow),
        "in_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in in_by_currency_rows],
        "out_by_currency": [{"currency": r.currency, "amount": float(r.amount or 0), "amount_ils": float(r.amount_ils or 0)} for r in out_by_currency_rows],
    }
    
    return render_template(
        "reports/cash_flow.html",
        data=data,
        start_date=sd.isoformat() if sd else '',
        end_date=ed.isoformat() if ed else ''
    )


@reports_bp.route("/payments/advanced", methods=["GET"], endpoint="payments_advanced_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def payments_advanced_report():
    """تقرير المدفوعات الشامل الاحترافي"""
    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    direction_filter = (request.args.get("direction") or "").strip()
    method_filter = (request.args.get("method") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd

    base_q = Payment.query.options(
        db.joinedload(Payment.customer),
        db.joinedload(Payment.supplier),
        db.joinedload(Payment.partner),
    )
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        base_q = base_q.filter(Payment.payment_date >= start_dt)
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        base_q = base_q.filter(Payment.payment_date <= end_dt)
    
    if direction_filter:
        direction_val = direction_filter.upper()
        try:
            base_q = base_q.filter(Payment.direction == PaymentDirection(direction_val).value)
        except Exception:
            base_q = base_q.filter(Payment.direction == direction_val)
    
    if method_filter:
        try:
            base_q = base_q.filter(Payment.method == PaymentMethod(method_filter.lower()).value)
        except Exception:
            base_q = base_q.filter(Payment.method == method_filter.lower())
    
    if status_filter:
        status_val = status_filter.upper()
        try:
            base_q = base_q.filter(Payment.status == PaymentStatus(status_val).value)
        except Exception:
            base_q = base_q.filter(Payment.status == status_val)
    else:
        base_q = base_q.filter(Payment.status == PaymentStatus.COMPLETED.value)

    pagination = base_q.order_by(Payment.payment_date.desc(), Payment.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    payments = list(pagination.items or [])

    def _fast_to_ils(amount, currency, fx_used, ref_date):
        value = Decimal(str(amount or 0))
        code = (currency or "ILS").upper()
        if code == "ILS":
            return value
        if fx_used:
            try:
                return value * Decimal(str(fx_used))
            except Exception:
                pass
        return _to_ils(value, code, ref_date)

    for p in payments:
        try:
            p.amount_ils = float(_fast_to_ils(p.total_amount, getattr(p, "currency", "ILS"), getattr(p, "fx_rate_used", None), p.payment_date))
        except Exception:
            p.amount_ils = float(p.total_amount or 0)

    fx_mult = case(
        (func.upper(func.coalesce(Payment.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Payment.fx_rate_used, 1),
    )
    amount_ils_expr = func.coalesce(Payment.total_amount, 0) * fx_mult

    status_up = func.upper(func.coalesce(Payment.status, ""))
    direction_up = func.upper(func.coalesce(Payment.direction, ""))

    agg = base_q.with_entities(
        func.count(Payment.id).label("total_payments"),
        func.coalesce(func.sum(case((direction_up == PaymentDirection.IN.value, amount_ils_expr), else_=0)), 0).label("total_in"),
        func.coalesce(func.sum(case((direction_up == PaymentDirection.OUT.value, amount_ils_expr), else_=0)), 0).label("total_out"),
        func.coalesce(func.sum(amount_ils_expr), 0).label("total_amount"),
        func.coalesce(func.sum(case((status_up == PaymentStatus.COMPLETED.value, 1), else_=0)), 0).label("completed_count"),
    ).first()

    total_payments = int(getattr(agg, "total_payments", 0) or 0)
    total_in = float(getattr(agg, "total_in", 0) or 0)
    total_out = float(getattr(agg, "total_out", 0) or 0)
    total_amount = float(getattr(agg, "total_amount", 0) or 0)
    completed_count = int(getattr(agg, "completed_count", 0) or 0)

    method_expr = func.lower(func.coalesce(Payment.method, "other"))
    method_stats_rows = (
        base_q.with_entities(
            method_expr.label("method"),
            func.coalesce(func.sum(amount_ils_expr), 0).label("total"),
        )
        .group_by(method_expr)
        .order_by(func.coalesce(func.sum(amount_ils_expr), 0).desc())
        .all()
    )

    method_labels = {
        'cash': 'نقدي',
        'bank': 'تحويل بنكي',
        'cheque': 'شيك',
        'card': 'بطاقة',
        'online': 'أونلاين',
        'other': 'أخرى'
    }
    
    method_stats = [
        {'method': m, 'label': method_labels.get(str(m).lower(), str(m)), 'total': float(t or 0)}
        for m, t in method_stats_rows
    ]
    
    summary = {
        'total_payments': total_payments,
        'total_in': total_in,
        'total_out': total_out,
        'net_flow': float(total_in - total_out),
        'total_amount': total_amount,
        'avg_payment': (float(total_amount) / float(total_payments)) if total_payments > 0 else 0,
        'completed_count': completed_count,
    }

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)
    
    return render_template(
        "reports/payments_summary.html",
        payments=payments,
        pagination=pagination,
        per_page=per_page,
        summary=summary,
        method_stats=method_stats,
        show_charts=True,
                         FIELD_LABELS=FIELD_LABELS, 
        MODEL_LABELS=MODEL_LABELS,
        query_args=query_args,
    )


@reports_bp.route("/payments-summary-old", methods=["GET"], strict_slashes=False)
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def payments_summary_old():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    rpt = payment_summary_report_ils(start, end)
    
    methods = rpt.get("methods", [])
    totals = [float(t) for t in rpt.get("totals_by_method", [])]
    grand_total = sum(totals)
    
    method_labels = {m: METHOD_LABELS_DEFAULT.get(m.upper(), METHOD_LABELS_DEFAULT.get(m, m)) for m in methods}
    return render_template(
        "reports/payments.html",
        methods=methods,
        totals=totals,
        grand_total=grand_total,
        METHOD_LABELS=method_labels,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/ar-aging", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def ar_aging():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    rpt = ar_aging_report(start_date=start, end_date=end)
    return render_template("reports/ar_aging.html", data=rpt.get("data", []), totals=rpt.get("totals", {}), as_of=rpt.get("as_of"), start=request.args.get("start", ""), end=request.args.get("end", ""), FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS)

@reports_bp.route("/inventory", methods=["GET"], endpoint="inventory")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def inventory_report():
    from models import Warehouse, StockLevel, Product
    from sqlalchemy.orm import joinedload
    from sqlalchemy import func
    from extensions import cache
    import csv
    import io

    search = (request.args.get("q") or "").strip()
    selected_warehouse_id = request.args.get("warehouse_id", type=int)
    low_only = request.args.get("low_only") == "1"
    export_format = (request.args.get("format") or "").lower()
    try:
        limit_rows = int(request.args.get("limit") or 1000)
    except Exception:
        limit_rows = 1000
    limit_rows = max(100, min(limit_rows, 5000))

    whs = Warehouse.query.order_by(Warehouse.name).all()
    if not whs:
        empty_context = {
            "warehouses": [],
            "all_warehouses": [],
            "rows": [],
            "search": search,
            "selected_warehouse_id": None,
            "low_only": low_only,
            "stats": {"products": 0, "on_hand": 0, "reserved": 0, "available": 0, "low_count": 0},
            "FIELD_LABELS": FIELD_LABELS,
        }
        if export_format == "csv":
            return Response("", mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})
        return render_template("reports/inventory.html", **empty_context)

    wh_ids = [w.id for w in whs]
    display_warehouses = whs
    q = (
        db.session.query(StockLevel)
        .join(Product, StockLevel.product_id == Product.id)
        .filter(StockLevel.warehouse_id.in_(wh_ids))
        .options(joinedload(StockLevel.product))
        .order_by(Product.name.asc())
    )

    if selected_warehouse_id and selected_warehouse_id in wh_ids:
        q = q.filter(StockLevel.warehouse_id == selected_warehouse_id)
        display_warehouses = [w for w in whs if w.id == selected_warehouse_id]
    else:
        selected_warehouse_id = None

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.part_number.ilike(like),
                Product.barcode.ilike(like),
            )
        )

    if export_format == "csv":
        header = ["Product", "SKU", "Barcode", "Total On Hand", "Reserved", "Available"]
        for wh in display_warehouses:
            header.extend([f"{wh.name} On Hand", f"{wh.name} Reserved"])

        display_wh_ids = [w.id for w in display_warehouses]
        q_stream = q.order_by(Product.name.asc(), StockLevel.product_id.asc(), StockLevel.warehouse_id.asc())

        def _rows():
            current_pid = None
            current_product = None
            by = None
            total_on = 0
            reserved_total = 0
            low_flag = False

            def _emit():
                if current_pid is None or current_product is None or by is None:
                    return None
                if low_only and not low_flag:
                    return None
                available_total = int(total_on) - int(reserved_total)
                base = [
                    current_product.name or current_pid,
                    current_product.sku or "",
                    current_product.barcode or "",
                    int(total_on),
                    int(reserved_total),
                    int(available_total),
                ]
                for wid in display_wh_ids:
                    stock = by.get(wid) or {"on": 0, "res": 0}
                    base.extend([int(stock.get("on", 0) or 0), int(stock.get("res", 0) or 0)])
                return base

            for sl in q_stream.yield_per(2000):
                pid = sl.product_id
                if current_pid is None:
                    current_pid = pid
                    current_product = sl.product
                    by = {wid: {"on": 0, "res": 0} for wid in display_wh_ids}
                    total_on = 0
                    reserved_total = 0
                    low_flag = False
                elif pid != current_pid:
                    row = _emit()
                    if row is not None:
                        yield row
                    current_pid = pid
                    current_product = sl.product
                    by = {wid: {"on": 0, "res": 0} for wid in display_wh_ids}
                    total_on = 0
                    reserved_total = 0
                    low_flag = False

                on = int(sl.quantity or 0)
                res = int(getattr(sl, "reserved_quantity", 0) or 0)
                if sl.warehouse_id in by:
                    by[sl.warehouse_id] = {"on": on, "res": res}
                total_on += on
                reserved_total += res
                if getattr(sl, "min_stock", None) is not None and (sl.quantity or 0) < sl.min_stock:
                    low_flag = True

            row = _emit()
            if row is not None:
                yield row

        return _stream_csv_rows(header, _rows(), "inventory_report.csv")

    rows = q.limit(limit_rows).all()
    pivot = {}
    stock_levels_by_product = {}
    for sl in rows:
        pid = sl.product_id
        p = sl.product
        if pid not in pivot:
            pivot[pid] = {
                "product": p,
                "by": {wid: {"on": 0, "res": 0} for wid in wh_ids},
                "total": 0,
                "reserved_total": 0,
            }
            stock_levels_by_product[pid] = []
        on = int(sl.quantity or 0)
        res = int(getattr(sl, "reserved_quantity", 0) or 0)
        pivot[pid]["by"][sl.warehouse_id] = {"on": on, "res": res}
        pivot[pid]["total"] += on
        pivot[pid]["reserved_total"] += res
        stock_levels_by_product[pid].append(sl)

    rows_data = sorted(pivot.values(), key=lambda d: (d["product"].name or "").lower())
    if low_only:
        rows_data = [
            row
            for row in rows_data
            if any(
                sl.min_stock is not None and sl.quantity < sl.min_stock
                for sl in stock_levels_by_product.get(row["product"].id, [])
            )
        ]

    filters = [StockLevel.warehouse_id.in_(wh_ids)]
    if selected_warehouse_id:
        filters.append(StockLevel.warehouse_id == selected_warehouse_id)
    if search:
        like = f"%{search}%"
        product_like = or_(
            Product.name.ilike(like),
            Product.sku.ilike(like),
            Product.part_number.ilike(like),
            Product.barcode.ilike(like),
        )
        filters.append(product_like)
    cache_key = f"inv_stats:{selected_warehouse_id or 'all'}:{(search or '').strip()[:50]}"
    cached_stats = cache.get(cache_key)
    if cached_stats is None:
        products_count = (
            db.session.query(func.count(func.distinct(StockLevel.product_id)))
            .join(Product, StockLevel.product_id == Product.id)
            .filter(*filters)
            .scalar()
            or 0
        )
        on_hand_total = (
            db.session.query(func.sum(StockLevel.quantity))
            .join(Product, StockLevel.product_id == Product.id)
            .filter(*filters)
            .scalar()
            or 0
        )
        reserved_total = (
            db.session.query(func.sum(getattr(StockLevel, "reserved_quantity")))
            .join(Product, StockLevel.product_id == Product.id)
            .filter(*filters)
            .scalar()
            or 0
        )
        low_filters = [StockLevel.warehouse_id.in_(wh_ids), StockLevel.min_stock.isnot(None), StockLevel.quantity < StockLevel.min_stock]
        if selected_warehouse_id:
            low_filters.append(StockLevel.warehouse_id == selected_warehouse_id)
        if search:
            like = f"%{search}%"
            low_filters.append(
                or_(
                    Product.name.ilike(like),
                    Product.sku.ilike(like),
                    Product.part_number.ilike(like),
                    Product.barcode.ilike(like),
                )
            )
        low_count_cached = (
            db.session.query(func.count(func.distinct(StockLevel.product_id)))
            .join(Product, StockLevel.product_id == Product.id)
            .filter(*low_filters)
            .scalar()
            or 0
        )
        cache.set(cache_key, {"products_count": int(products_count), "on_hand_total": int(on_hand_total), "reserved_total": int(reserved_total), "low_count": int(low_count_cached)}, timeout=300)
        products_count = int(products_count)
        on_hand_total = int(on_hand_total)
        reserved_total = int(reserved_total)
    else:
        products_count = int(cached_stats.get("products_count", 0))
        on_hand_total = int(cached_stats.get("on_hand_total", 0))
        reserved_total = int(cached_stats.get("reserved_total", 0))
        low_count_cached = int(cached_stats.get("low_count", 0))
    low_filters = [StockLevel.warehouse_id.in_(wh_ids), StockLevel.min_stock.isnot(None), StockLevel.quantity < StockLevel.min_stock]
    if selected_warehouse_id:
        low_filters.append(StockLevel.warehouse_id == selected_warehouse_id)
    if search:
        like = f"%{search}%"
        low_filters.append(
            or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.part_number.ilike(like),
                Product.barcode.ilike(like),
            )
        )
    low_count_val = low_count_cached if cached_stats is not None else (
        db.session.query(func.count(func.distinct(StockLevel.product_id)))
        .join(Product, StockLevel.product_id == Product.id)
        .filter(*low_filters)
        .scalar()
        or 0
    )
    stats = {
        "products": int(products_count),
        "on_hand": int(on_hand_total),
        "reserved": int(reserved_total),
        "available": int((on_hand_total or 0) - (reserved_total or 0)),
        "low_count": int(low_count_val),
    }

    return render_template(
        "reports/inventory.html",
        warehouses=display_warehouses,
        all_warehouses=whs,
        rows=rows_data,
        limit=limit_rows,
        search=search,
        selected_warehouse_id=selected_warehouse_id,
        low_only=low_only,
        stats=stats,
        FIELD_LABELS=FIELD_LABELS,
    )

@reports_bp.route("/top-products", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def top_products():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    try:
        limit = int(request.args.get("limit") or 20)
    except Exception:
        limit = 20
    limit = _clamp_limit(limit, default=20, max_v=1000)
    selected_warehouse_id = request.args.get("warehouse_id", type=int)
    requested_group = (request.args.get("group_by") == "warehouse")
    group_by_warehouse = requested_group or bool(selected_warehouse_id)

    def _build_report(gbw, wh_id):
        return top_products_report(
            start,
            end,
            limit=limit,
            warehouse_id=wh_id,
            group_by_warehouse=gbw,
        )

    rpt = _build_report(group_by_warehouse, selected_warehouse_id)
    forced = bool(selected_warehouse_id) and not requested_group
    if selected_warehouse_id and not rpt.get("can_group_by_warehouse", False):
        flash("لا يمكن التجميع حسب المستودع في هذا التقرير، تم عرض جميع المستودعات.", "warning")
        selected_warehouse_id = None
        group_by_warehouse = False
        rpt = _build_report(group_by_warehouse, selected_warehouse_id)

    warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()
    return render_template(
        "reports/top_products.html",
        data=rpt.get("data", []),
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        limit=limit,
        warehouses=warehouses,
        selected_warehouse_id=selected_warehouse_id,
        group_by_warehouse=group_by_warehouse,
        forced_grouping=forced,
        can_group_by_warehouse=rpt.get("can_group_by_warehouse", False),
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/suppliers", methods=["GET"], endpoint="suppliers_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def suppliers_report():
    search = (request.args.get("q") or "").strip()
    balance_filter = (request.args.get("balance") or "").strip()
    export_format = (request.args.get("format") or "").lower()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))

    q = Supplier.query.order_by(Supplier.name.asc())
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Supplier.name.ilike(like),
                Supplier.phone.ilike(like),
                Supplier.email.ilike(like),
            )
        )

    balance_col = Supplier.current_balance
    if balance_filter == "positive":
        q = q.filter(balance_col > 0)
    elif balance_filter == "negative":
        q = q.filter(balance_col < 0)
    elif balance_filter == "zero":
        q = q.filter(balance_col == 0)

    total_balance = float((q.order_by(None).with_entities(func.coalesce(func.sum(balance_col), 0)).scalar()) or 0)
    totals = {"balance": total_balance}

    pagination = None
    if export_format == "csv":
        def _rows():
            for s in q.yield_per(1000):
                bal = float(getattr(s, "current_balance", None) or getattr(s, "balance", 0) or 0)
                yield [s.id, s.name or '', bal]

        return _stream_csv_rows(["ID", "Name", "Balance"], _rows(), "suppliers_report.csv")

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    suppliers = list(pagination.items or [])
    data = [{"id": s.id, "name": s.name or '', "balance": float(getattr(s, "current_balance", None) or getattr(s, "balance", 0) or 0)} for s in suppliers]

    return render_template(
        "reports/suppliers.html",
        data=data,
        totals=totals,
        search=search,
        balance_filter=balance_filter,
        pagination=pagination,
        per_page=per_page,
        query_args={k: v for k, v in request.args.to_dict().items() if k not in ("page", "per_page")},
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/partners", methods=["GET"], endpoint="partners_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def partners_report():
    from datetime import datetime
    from utils import get_entity_balance_in_ils

    search = (request.args.get("q") or "").strip()
    balance_filter = (request.args.get("balance") or "").strip()
    export_format = (request.args.get("format") or "").lower()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))

    q = Partner.query.order_by(Partner.name.asc())
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Partner.name.ilike(like),
                Partner.phone_number.ilike(like),
                Partner.identity_number.ilike(like),
            )
        )

    if balance_filter == "positive":
        q = q.filter(Partner.current_balance > 0)
    elif balance_filter == "negative":
        q = q.filter(Partner.current_balance < 0)
    elif balance_filter == "zero":
        q = q.filter(Partner.current_balance == 0)

    if export_format == "csv":
        def _rows():
            for partner in q.yield_per(500):
                smart_balance = None
                try:
                    smart_balance = float(get_entity_balance_in_ils("PARTNER", int(partner.id)))
                except Exception:
                    smart_balance = None
                balance = smart_balance if smart_balance is not None else float(partner.current_balance or 0)
                share_pct = float(partner.share_percentage or 0)
                source = "smart" if smart_balance is not None else "stored"
                yield [partner.id, partner.name or '', balance, share_pct, source]

        return _stream_csv_rows(["ID", "Name", "Balance", "Share %", "Source"], _rows(), "partners_report.csv")

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    partners = list(pagination.items or [])
    data = []
    total_balance = 0.0
    for partner in partners:
        smart_balance = None
        try:
            smart_balance = float(get_entity_balance_in_ils("PARTNER", int(partner.id)))
        except Exception:
            smart_balance = None
        balance = smart_balance if smart_balance is not None else float(partner.current_balance or 0)
        data.append(
            {
                "id": partner.id,
                "name": partner.name or '',
                "balance": balance,
                "share_percentage": float(partner.share_percentage or 0),
                "source": "smart" if smart_balance is not None else "stored",
            }
        )
        total_balance += balance
    totals = {"balance": total_balance}

    return render_template(
        "reports/partners.html",
        data=data,
        totals=totals,
        search=search,
        balance_filter=balance_filter,
        pagination=pagination,
        per_page=per_page,
        query_args={k: v for k, v in request.args.to_dict().items() if k not in ("page", "per_page")},
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/customers", methods=["GET"], endpoint="customers_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def customers_report():
    return customers_advanced_report()


@reports_bp.route("/customers/advanced", methods=["GET"], endpoint="customers_advanced_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def customers_advanced_report():
    """تقرير العملاء الشامل الاحترافي"""
    from datetime import datetime
    from sqlalchemy import or_

    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    search = (request.args.get("search") or request.args.get("q") or "").strip()
    balance_status = (request.args.get("balance_status") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))

    cust_filters = []
    if search:
        cust_filters.append(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
                Customer.email.ilike(f"%{search}%"),
            )
        )
    if balance_status == "debit":
        cust_filters.append(Customer.current_balance > 0)
    elif balance_status == "credit":
        cust_filters.append(Customer.current_balance < 0)
    elif balance_status == "zero":
        cust_filters.append(Customer.current_balance == 0)

    customer_q = Customer.query
    if cust_filters:
        customer_q = customer_q.filter(*cust_filters)
    customer_q = customer_q.order_by(func.abs(func.coalesce(Customer.current_balance, 0)).desc(), Customer.id.desc())

    pagination = customer_q.paginate(page=page, per_page=per_page, error_out=False)
    customers = list(pagination.items or [])
    customer_ids = [c.id for c in customers if getattr(c, "id", None)]

    inv_start_dt = datetime.combine(start, datetime.min.time()) if start else None
    inv_end_dt = datetime.combine(end, datetime.max.time()) if end else None

    inv_fx = case(
        (func.upper(func.coalesce(Invoice.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Invoice.fx_rate_used, 1),
    )
    inv_amount_ils = func.coalesce(Invoice.total_amount, 0) * inv_fx

    inv_q = db.session.query(
        Invoice.customer_id.label("cid"),
        func.coalesce(func.sum(inv_amount_ils), 0).label("total_invoiced"),
        func.count(Invoice.id).label("invoice_count"),
        func.max(Invoice.invoice_date).label("last_invoice"),
    ).filter(Invoice.cancelled_at.is_(None))
    if customer_ids:
        inv_q = inv_q.filter(Invoice.customer_id.in_(customer_ids))
    if inv_start_dt:
        inv_q = inv_q.filter(Invoice.invoice_date >= inv_start_dt)
    if inv_end_dt:
        inv_q = inv_q.filter(Invoice.invoice_date <= inv_end_dt)
    inv_rows = inv_q.group_by(Invoice.customer_id).all() if customer_ids else []
    inv_map = {int(r.cid): r for r in inv_rows}

    pay_fx = case(
        (func.upper(func.coalesce(Payment.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Payment.fx_rate_used, 1),
    )
    pay_amount_ils = func.coalesce(Payment.total_amount, 0) * pay_fx
    pay_q = db.session.query(
        Payment.customer_id.label("cid"),
        func.coalesce(func.sum(pay_amount_ils), 0).label("total_paid"),
        func.max(Payment.payment_date).label("last_payment"),
    ).filter(
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value,
    )
    if customer_ids:
        pay_q = pay_q.filter(Payment.customer_id.in_(customer_ids))
    if inv_start_dt:
        pay_q = pay_q.filter(Payment.payment_date >= inv_start_dt)
    if inv_end_dt:
        pay_q = pay_q.filter(Payment.payment_date <= inv_end_dt)
    pay_rows = pay_q.group_by(Payment.customer_id).all() if customer_ids else []
    pay_map = {int(r.cid): r for r in pay_rows}

    data = []
    for c in customers:
        cid = int(c.id)
        inv_r = inv_map.get(cid)
        pay_r = pay_map.get(cid)
        total_invoiced = float(getattr(inv_r, "total_invoiced", 0) or 0)
        total_paid = float(getattr(pay_r, "total_paid", 0) or 0)
        balance = float(getattr(c, "current_balance", 0) or 0)
        data.append(
            {
                "id": cid,
                "name": c.name or "",
                "phone": c.phone or "",
                "email": c.email or "",
                "total_invoiced": total_invoiced,
                "total_paid": total_paid,
                "balance": balance,
            }
        )

    total_customers = int((Customer.query.filter(*cust_filters).with_entities(func.count(Customer.id)).scalar()) or 0) if cust_filters else int(db.session.query(func.count(Customer.id)).scalar() or 0)
    total_balance = float((Customer.query.filter(*cust_filters).with_entities(func.coalesce(func.sum(Customer.current_balance), 0)).scalar()) or 0) if cust_filters else float(db.session.query(func.coalesce(func.sum(Customer.current_balance), 0)).scalar() or 0)

    inv_total_q = db.session.query(func.coalesce(func.sum(inv_amount_ils), 0)).select_from(Invoice).join(Customer, Customer.id == Invoice.customer_id).filter(Invoice.cancelled_at.is_(None))
    if cust_filters:
        inv_total_q = inv_total_q.filter(*cust_filters)
    if inv_start_dt:
        inv_total_q = inv_total_q.filter(Invoice.invoice_date >= inv_start_dt)
    if inv_end_dt:
        inv_total_q = inv_total_q.filter(Invoice.invoice_date <= inv_end_dt)
    total_invoiced = float(inv_total_q.scalar() or 0)

    pay_total_q = db.session.query(func.coalesce(func.sum(pay_amount_ils), 0)).select_from(Payment).join(Customer, Customer.id == Payment.customer_id).filter(
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value,
    )
    if cust_filters:
        pay_total_q = pay_total_q.filter(*cust_filters)
    if inv_start_dt:
        pay_total_q = pay_total_q.filter(Payment.payment_date >= inv_start_dt)
    if inv_end_dt:
        pay_total_q = pay_total_q.filter(Payment.payment_date <= inv_end_dt)
    total_paid = float(pay_total_q.scalar() or 0)

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)

    return render_template(
        "reports/customers.html",
        data=data,
        totals={"invoiced": total_invoiced, "paid": total_paid, "balance": total_balance},
        total_customers=total_customers,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        search=search,
        balance_status=balance_status,
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )


@reports_bp.route("/sales/advanced", methods=["GET"], endpoint="sales_advanced_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def sales_advanced_report():
    """تقرير المبيعات الشامل الاحترافي"""
    from datetime import datetime, timedelta
    from sqlalchemy.orm import load_only

    sd = _parse_date(request.args.get("start_date"))
    ed = _parse_date(request.args.get("end_date"))
    customer_id = request.args.get("customer_id")
    status_filter = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    
    if sd and ed and ed < sd:
        sd, ed = ed, sd
    if not sd and not ed:
        sd = (datetime.now().date() - timedelta(days=90))
    
    base_q = Sale.query.options(
        db.joinedload(Sale.customer),
        db.joinedload(Sale.seller_employee),
        db.joinedload(Sale.seller),
    )
    
    if sd:
        start_dt = datetime.combine(sd, datetime.min.time())
        base_q = base_q.filter(Sale.sale_date >= start_dt)
    if ed:
        end_dt = datetime.combine(ed, datetime.max.time())
        base_q = base_q.filter(Sale.sale_date <= end_dt)
    
    if customer_id:
        try:
            base_q = base_q.filter(Sale.customer_id == int(customer_id))
        except Exception:
            pass
    
    employee_id = request.args.get("employee_id")

    if status_filter:
        base_q = base_q.filter(Sale.status == status_filter)
    else:
        base_q = base_q.filter(Sale.status == SaleStatus.CONFIRMED.value)

    if employee_id:
        try:
            base_q = base_q.filter(Sale.seller_employee_id == int(employee_id))
        except Exception:
            pass
    
    fx_mult = case(
        (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Sale.fx_rate_used, 1),
    )
    total_amount_ils = func.coalesce(Sale.total_amount, 0) * fx_mult

    agg_sales = base_q.with_entities(
        func.count(Sale.id).label("total_sales"),
        func.coalesce(func.sum(total_amount_ils), 0).label("total_revenue"),
    ).first()

    total_sales = int(getattr(agg_sales, "total_sales", 0) or 0)
    total_revenue = float(getattr(agg_sales, "total_revenue", 0) or 0)

    items_q = (
        db.session.query(
            func.count(SaleLine.id).label("total_items"),
            func.coalesce(func.sum(SaleLine.quantity), 0).label("total_quantity"),
        )
        .join(Sale, SaleLine.sale_id == Sale.id)
    )
    if sd:
        items_q = items_q.filter(Sale.sale_date >= datetime.combine(sd, datetime.min.time()))
    if ed:
        items_q = items_q.filter(Sale.sale_date <= datetime.combine(ed, datetime.max.time()))
    if customer_id:
        try:
            items_q = items_q.filter(Sale.customer_id == int(customer_id))
        except Exception:
            pass
    if status_filter:
        items_q = items_q.filter(Sale.status == status_filter)
    else:
        items_q = items_q.filter(Sale.status == SaleStatus.CONFIRMED.value)
    if employee_id:
        try:
            items_q = items_q.filter(Sale.seller_employee_id == int(employee_id))
        except Exception:
            pass

    items_row = items_q.first()
    total_items = int(getattr(items_row, "total_items", 0) or 0)
    total_quantity = int(getattr(items_row, "total_quantity", 0) or 0)

    pagination = base_q.order_by(Sale.sale_date.desc(), Sale.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    sales = list(pagination.items or [])

    sale_ids = [s.id for s in sales if getattr(s, "id", None)]
    line_counts = {}
    if sale_ids:
        lc_rows = (
            db.session.query(SaleLine.sale_id, func.count(SaleLine.id))
            .filter(SaleLine.sale_id.in_(sale_ids))
            .group_by(SaleLine.sale_id)
            .all()
        )
        line_counts = {sid: int(cnt or 0) for sid, cnt in lc_rows}

    for s in sales:
        try:
            setattr(s, "line_count", int(line_counts.get(s.id, 0)))
        except Exception:
            pass
        try:
            if (getattr(s, "currency", "ILS") or "ILS").upper() == "ILS":
                s.total_amount_ils = float(s.total_amount or 0)
            elif getattr(s, "fx_rate_used", None):
                s.total_amount_ils = float(Decimal(str(s.total_amount or 0)) * Decimal(str(s.fx_rate_used)))
            else:
                s.total_amount_ils = float(_to_ils(s.total_amount or 0, getattr(s, "currency", "ILS"), s.sale_date))
        except Exception:
            s.total_amount_ils = float(s.total_amount or 0)

    currency_expr = func.upper(func.coalesce(Sale.currency, "ILS"))
    by_currency_rows = (
        base_q.with_entities(
            currency_expr.label("currency"),
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_amount"),
            func.coalesce(func.sum(total_amount_ils), 0).label("total_amount_ils"),
        )
        .group_by(currency_expr)
        .order_by(currency_expr.asc())
        .all()
    )

    summary = {
        'total_sales': total_sales,
        'total_revenue': float(total_revenue),
        "total_revenue_ils": float(total_revenue),
        'avg_sale': float(total_revenue / total_sales) if total_sales > 0 else 0,
        'total_items': total_items,
        'total_quantity': total_quantity,
        'avg_item_value': float(total_revenue / total_items) if total_items > 0 else 0,
        "by_currency": [
            {
                "currency": r.currency,
                "count": int(r.count or 0),
                "total_amount": float(r.total_amount or 0),
                "total_amount_ils": float(r.total_amount_ils or 0),
            }
            for r in by_currency_rows
        ],
    }

    day_expr = func.date(Sale.sale_date)
    daily_rows = (
        base_q.with_entities(
            day_expr.label("day"),
            func.coalesce(func.sum(total_amount_ils), 0).label("total"),
        )
        .group_by(day_expr)
        .order_by(day_expr)
        .all()
    )
    daily_sales = [{"date": str(d), "total": float(t or 0)} for d, t in daily_rows]

    line_total_expr = (
        (SaleLine.quantity * SaleLine.unit_price)
        * (1 - (func.coalesce(SaleLine.discount_rate, 0) / 100.0))
        * (1 + (func.coalesce(SaleLine.tax_rate, 0) / 100.0))
    )
    top_rows = (
        db.session.query(
            Product.id.label("id"),
            Product.name.label("name"),
            func.coalesce(func.sum(SaleLine.quantity), 0).label("qty"),
            func.coalesce(func.sum(line_total_expr * fx_mult), 0).label("rev"),
        )
        .join(SaleLine, SaleLine.product_id == Product.id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .filter(Sale.id.isnot(None))
    )
    if sd:
        top_rows = top_rows.filter(Sale.sale_date >= datetime.combine(sd, datetime.min.time()))
    if ed:
        top_rows = top_rows.filter(Sale.sale_date <= datetime.combine(ed, datetime.max.time()))
    if customer_id:
        try:
            top_rows = top_rows.filter(Sale.customer_id == int(customer_id))
        except Exception:
            pass
    if status_filter:
        top_rows = top_rows.filter(Sale.status == status_filter)
    else:
        top_rows = top_rows.filter(Sale.status == SaleStatus.CONFIRMED.value)
    if employee_id:
        try:
            top_rows = top_rows.filter(Sale.seller_employee_id == int(employee_id))
        except Exception:
            pass
    top_rows = (
        top_rows.group_by(Product.id, Product.name)
        .order_by(func.coalesce(func.sum(line_total_expr * fx_mult), 0).desc())
        .limit(5)
        .all()
    )
    top_products = [{"id": pid, "name": pname or "منتج", "quantity": int(qty or 0), "revenue": float(rev or 0)} for pid, pname, qty, rev in top_rows]

    all_customers = Customer.query.options(load_only(Customer.id, Customer.name)).order_by(Customer.name).all()
    employees = Employee.query.options(load_only(Employee.id, Employee.name)).order_by(Employee.name).all()

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)
    
    return render_template(
        "reports/sales.html",
        sales=sales,
        pagination=pagination,
        per_page=per_page,
        summary=summary,
        daily_sales=daily_sales,
        top_products=top_products,
        all_customers=all_customers,
        employees=employees,
        selected_employee_id=int(employee_id) if employee_id else None,
        show_charts=True,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
        query_args=query_args,
    )


@reports_bp.route("/expenses", methods=["GET"], endpoint="expenses_report")
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def expenses_report():
    from decimal import Decimal
    from models import Warehouse, Partner, ExpenseType, convert_amount

    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    tab = (request.args.get("tab") or "expenses").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))

    expense_type = (request.args.get("type") or "").strip()
    warehouse_id = request.args.get("warehouse_id")
    partner_id = request.args.get("partner_id")
    is_paid = request.args.get("is_paid")

    q = Expense.query
    if start:
        q = q.filter(Expense.date >= start)
    if end:
        q = q.filter(Expense.date <= end)

    if expense_type:
        from models import ExpenseType as _ET

        try:
            et_id = int(expense_type)
            q = q.filter(Expense.type_id == et_id)
        except Exception:
            q = q.join(_ET, Expense.type_id == _ET.id).filter(_ET.name.ilike(f"%{expense_type}%"))
    if warehouse_id:
        try:
            q = q.filter(Expense.warehouse_id == int(warehouse_id))
        except Exception:
            pass
    if partner_id:
        try:
            q = q.filter(Expense.partner_id == int(partner_id))
        except Exception:
            pass
    if is_paid in ["true", "1"]:
        q = q.filter(Expense.is_paid.is_(True))
    elif is_paid in ["false", "0"]:
        q = q.filter(Expense.is_paid.is_(False))

    q = q.order_by(Expense.date.desc(), Expense.id.desc())

    fx_mult = case(
        (func.upper(func.coalesce(Expense.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Expense.fx_rate_used, 1),
    )
    amount_ils_expr = func.coalesce(Expense.amount, 0) * fx_mult

    agg = q.with_entities(
        func.count(Expense.id).label("cnt"),
        func.coalesce(func.sum(amount_ils_expr), 0).label("total_amount"),
    ).first()
    total_count = int(getattr(agg, "cnt", 0) or 0)
    total_amount = float(getattr(agg, "total_amount", 0) or 0)

    pagination = None
    rows = []
    if tab == "expenses":
        pagination = q.options(
            db.joinedload(Expense.type),
            db.joinedload(Expense.employee),
            db.joinedload(Expense.warehouse),
            db.joinedload(Expense.partner),
        ).paginate(page=page, per_page=per_page, error_out=False)
        rows = list(pagination.items or [])
    else:
        rows = []

    def _to_ils(amount, currency, fx_used, ref_date):
        value = Decimal(str(amount or 0))
        code = (currency or "ILS").upper()
        if code == "ILS":
            return value
        if fx_used:
            try:
                return value * Decimal(str(fx_used))
            except Exception:
                pass
        try:
            return convert_amount(value, code, "ILS", ref_date)
        except Exception:
            return value

    for e in rows:
        try:
            e.amount_ils = float(_to_ils(e.amount, e.currency, getattr(e, "fx_rate_used", None), getattr(e, "date", None)))
        except Exception:
            e.amount_ils = float(e.amount or 0)

    type_labels = []
    type_values = []
    emp_labels = []
    emp_values = []
    if tab == "expenses":
        type_label_expr = func.coalesce(ExpenseType.name, "غير محدد")
        by_type_rows = (
            q.join(ExpenseType, Expense.type_id == ExpenseType.id, isouter=True)
            .with_entities(
                type_label_expr.label("label"),
                func.coalesce(func.sum(amount_ils_expr), 0).label("total"),
            )
            .group_by(type_label_expr)
            .order_by(func.coalesce(func.sum(amount_ils_expr), 0).desc())
            .limit(20)
            .all()
        )
        type_labels = [str(lbl) for lbl, _ in by_type_rows]
        type_values = [float(t or 0) for _, t in by_type_rows]

        emp_label_expr = func.coalesce(Employee.name, "غير محدد")
        by_emp_rows = (
            q.join(Employee, Expense.employee_id == Employee.id, isouter=True)
            .with_entities(
                emp_label_expr.label("label"),
                func.coalesce(func.sum(amount_ils_expr), 0).label("total"),
            )
            .group_by(emp_label_expr)
            .order_by(func.coalesce(func.sum(amount_ils_expr), 0).desc())
            .limit(20)
            .all()
        )
        emp_labels = [str(lbl) for lbl, _ in by_emp_rows]
        emp_values = [float(t or 0) for _, t in by_emp_rows]

    warehouses = Warehouse.query.order_by(Warehouse.name).all()
    partners = Partner.query.order_by(Partner.name).all()
    expense_types = ExpenseType.query.filter_by(is_active=True).order_by(ExpenseType.name).all()
    
    receipts_rows = []
    receipts_total = 0.0
    if tab == "receipts":
        from models import User
        pq = db.session.query(
            Payment.created_by.label("uid"),
            func.coalesce(func.count(Payment.id), 0).label("count"),
            func.coalesce(func.sum(Payment.total_amount), 0).label("total")
        ).filter(
            Payment.direction == PaymentDirection.IN.value,
            Payment.status == PaymentStatus.COMPLETED.value
        )
        if start:
            pq = pq.filter(Payment.payment_date >= start)
        if end:
            pq = pq.filter(Payment.payment_date <= end)
        pq = pq.group_by(Payment.created_by)
        agg = pq.all()
        uid_to_name = {}
        if agg:
            uids = [r.uid for r in agg if r.uid]
            if uids:
                users = db.session.query(User.id, User.username, User.is_system_account).filter(User.id.in_(uids)).all()
                uid_to_name = {u.id: (u.username if not u.is_system_account else "System") for u in users}
        receipts_rows = [
            {
                "user_id": r.uid or 0,
                "user_name": uid_to_name.get(r.uid or 0, "—"),
                "payments_count": int(r.count or 0),
                "total_amount": float(r.total or 0),
            }
            for r in agg
        ]
        receipts_total = sum(x["total_amount"] for x in receipts_rows)

    if (request.args.get("export") or "").lower() == "csv":
        if tab == "receipts":
            csv_text = _csv_from_rows([
                {
                    "user_id": row.get("user_id"),
                    "user_name": row.get("user_name"),
                    "payments_count": row.get("payments_count"),
                    "total_amount": row.get("total_amount"),
                }
                for row in receipts_rows
            ])
            return Response(csv_text, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=receipts_by_user.csv"})
        export_q = q.options(
            db.joinedload(Expense.type),
            db.joinedload(Expense.employee),
            db.joinedload(Expense.warehouse),
            db.joinedload(Expense.partner),
        ).limit(20000)

        header = [
            "id",
            "date",
            "type",
            "amount_ils",
            "currency",
            "employee",
            "warehouse",
            "partner",
            "description",
            "is_paid",
        ]

        def _rows():
            for e in export_q.yield_per(1000):
                amount_ils = float(_to_ils(e.amount, e.currency, getattr(e, "fx_rate_used", None), getattr(e, "date", None)))
                yield [
                    e.id,
                    (e.date.strftime("%Y-%m-%d") if getattr(e, "date", None) else ""),
                    (getattr(e.type, "name", None) or e.type_id if getattr(e, "type", None) else e.type_id),
                    amount_ils,
                    e.currency or "",
                    (getattr(e.employee, "name", None) or "" if getattr(e, "employee", None) else ""),
                    (getattr(e.warehouse, "name", None) or "" if getattr(e, "warehouse", None) else ""),
                    (getattr(e.partner, "name", None) or "" if getattr(e, "partner", None) else ""),
                    getattr(e, "desc", None) or getattr(e, "description", "") or "",
                    ("YES" if getattr(e, "is_paid", False) else "NO"),
                ]

        return _stream_csv_rows(header, _rows(), "expenses.csv")

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)

    return render_template(
        "reports/expenses.html",
        data=rows,
        total_amount=total_amount,
        total_count=total_count,
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        tab=tab,
        selected_type=expense_type or "",
        selected_warehouse_id=int(warehouse_id) if warehouse_id else None,
        selected_partner_id=int(partner_id) if partner_id else None,
        selected_is_paid=is_paid or "",
        warehouses=warehouses,
        partners=partners,
        expense_types=expense_types,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
        type_labels=type_labels,
        type_values=type_values,
        emp_labels=emp_labels,
        emp_values=emp_values,
        receipts_rows=receipts_rows,
        receipts_total=receipts_total,
    )

@reports_bp.route("/ap-aging", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def ap_aging():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    rpt = ap_aging_report(start_date=start, end_date=end)
    return render_template("reports/ap_aging.html", data=rpt.get("data", []), totals=rpt.get("totals", {}), as_of=rpt.get("as_of"), start=request.args.get("start", ""), end=request.args.get("end", ""), FIELD_LABELS=FIELD_LABELS, MODEL_LABELS=MODEL_LABELS)

@reports_bp.route("/api/model_fields", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_REPORTS)
def model_fields():
    model_name = (request.args.get("model") or "").strip()
    if not model_name:
        return jsonify({"models": list(_MODEL_LOOKUP.keys())}), 200
    model = _MODEL_LOOKUP.get(model_name)
    if not model:
        return jsonify({"error": "Unknown model", "models": list(_MODEL_LOOKUP.keys())}), 404
    mapper = sa_inspect(model)
    columns = [col.key for col in mapper.columns]
    lower = {c: c.lower() for c in columns}
    date_fields = [c for c in columns if ("date" in lower[c]) or (lower[c].endswith("_at")) or ("created_at" in lower[c]) or ("updated_at" in lower[c])]
    all_fields = _model_all_fields(model)
    return jsonify({"columns": columns, "date_fields": date_fields, "all_fields": all_fields}), 200

@reports_bp.route("/service-reports", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def service_reports():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    status_filter = (request.args.get("status") or "").strip().upper()
    mechanic_id = request.args.get("mechanic_id", type=int)
    customer_id = request.args.get("customer_id", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    valid_statuses = {s.value for s in ServiceStatus}
    if status_filter and status_filter not in valid_statuses:
        status_filter = None

    if (request.args.get("format") or "").lower() == "csv":
        rpt = service_reports_report(
            start,
            end,
            status=status_filter,
            mechanic_id=mechanic_id,
            customer_id=customer_id,
            export=True,
        )
        csv_rows = [
            {
                "number": row.get("number"),
                "status": row.get("status"),
                "priority": row.get("priority"),
                "received_at": row.get("received_at"),
                "customer": row.get("customer_name"),
                "mechanic": row.get("mechanic_name"),
                "total_ils": row.get("total_ils"),
            }
            for row in rpt.get("data", [])
        ]
        csv_text = _csv_from_rows(csv_rows)
        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=service_reports.csv"},
        )

    rpt = service_reports_report(
        start,
        end,
        status=status_filter,
        mechanic_id=mechanic_id,
        customer_id=customer_id,
        page=page,
        per_page=per_page,
    )

    mechanics = User.query.options(load_only(User.id, User.username)).order_by(User.username.asc()).all()
    customers = Customer.query.options(load_only(Customer.id, Customer.name)).order_by(Customer.name.asc()).all()
    status_choices = [(s.value, s.label) for s in ServiceStatus]

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)

    return render_template(
        "reports/service_reports.html",
        total=rpt.get("total", 0),
        completed=rpt.get("completed", 0),
        revenue=rpt.get("revenue", 0.0),
        parts=rpt.get("parts", 0.0),
        labor=rpt.get("labor", 0.0),
        data=rpt.get("data", []),
        pagination=rpt.get("pagination"),
        per_page=per_page,
        query_args=query_args,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        mechanics=mechanics,
        customers=customers,
        status_choices=status_choices,
        selected_status=status_filter or "",
        selected_mechanic_id=mechanic_id,
        selected_customer_id=customer_id,
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/api/dynamic", methods=["POST"])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_REPORTS)
def api_dynamic():
    payload = request.get_json(silent=True) or {}
    table = (payload.get("table") or "").strip()
    model = _ensure_model(table)
    cols = [c for c in _model_all_fields(model) if _is_selectable_field(model, c)]
    all_fields = _model_all_fields(model)
    columns = _sanitize_fields(payload.get("columns") or [], all_fields) or None
    like_filters = _sanitize_likes(payload.get("like_filters") or {}, cols) or None
    date_field = (payload.get("date_field") or "").strip()
    if date_field and date_field not in cols:
        date_field = ""
    if not date_field:
        df = _DEFAULT_DATE_FIELD.get(table)
        date_field = df if df in cols else None
    limit = _clamp_limit(payload.get("limit"), default=1000, max_v=10000)
    rpt = advanced_report(
        model=model,
        date_field=date_field or None,
        start_date=_parse_date(payload.get("start_date")),
        end_date=_parse_date(payload.get("end_date")),
        filters=payload.get("filters"),
        like_filters=like_filters,
        columns=columns,
        aggregates=payload.get("aggregates"),
    )
    data = (rpt.get("data") or [])[:limit]
    return jsonify({"data": data, "summary": rpt.get("summary") or {}}), 200

def _csv_from_rows(rows: List[Dict[str, Any]]):
    if not rows:
        return ""
    import io, csv
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return output.getvalue()


def _stream_csv_rows(header: List[str], rows_iter, filename: str):
    import io
    import csv

    def _gen():
        buf = io.StringIO()
        buf.write("\ufeff")
        writer = csv.writer(buf)
        writer.writerow(header)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in rows_iter:
            writer.writerow(r)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return Response(
        stream_with_context(_gen()),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@reports_bp.route("/export/dynamic.csv", methods=["POST"])
@login_required
@utils.permission_required(SystemPermissions.MANAGE_REPORTS)
def export_dynamic_csv():
    table = (request.form.get("table") or "").strip()
    model = _ensure_model(table)
    cols = [c for c in _model_all_fields(model) if _is_selectable_field(model, c)]
    all_fields = _model_all_fields(model)
    selected_fields = request.form.getlist("selected_fields") or []
    selected_fields = _sanitize_fields(selected_fields, all_fields) or None
    date_field = (request.form.get("date_field") or "").strip()
    if date_field and date_field not in cols:
        date_field = ""
    if not date_field:
        df = _DEFAULT_DATE_FIELD.get(table)
        date_field = df if df in cols else None
    like_filters = {k: v for k, v in request.form.items() if k not in {"table", "date_field", "start_date", "end_date", "csrf_token", "selected_fields"} and v not in (None, "")}
    like_filters = _sanitize_likes(like_filters, cols)
    rpt = advanced_report(model=model, date_field=date_field or None, start_date=_parse_date(request.form.get("start_date")), end_date=_parse_date(request.form.get("end_date")), like_filters=like_filters or None, columns=selected_fields, aggregates={"count": ["id"]})
    csv_text = _csv_from_rows(rpt.get("data") or [])
    return Response(csv_text, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=dynamic_report.csv"})

@reports_bp.route("/export/ar_aging.csv", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def export_ar_aging_csv():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    rpt = ar_aging_report(start_date=start, end_date=end)
    rows = []
    for item in rpt.get("data", []):
        row = {
            "customer": item.get("customer"),
            "0-30": item.get("buckets", {}).get("0-30", 0),
            "31-60": item.get("buckets", {}).get("31-60", 0),
            "61-90": item.get("buckets", {}).get("61-90", 0),
            "90+": item.get("buckets", {}).get("90+", 0),
            "total": item.get("balance", 0),
        }
        rows.append(row)
    csv_text = _csv_from_rows(rows)
    return Response(csv_text, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=ar_aging.csv"})

@reports_bp.route("/export/ap_aging.csv", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def export_ap_aging_csv():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    rpt = ap_aging_report(start_date=start, end_date=end)
    rows = []
    for item in rpt.get("data", []):
        row = {
            "supplier": item.get("supplier"),
            "0-30": item.get("buckets", {}).get("0-30", 0),
            "31-60": item.get("buckets", {}).get("31-60", 0),
            "61-90": item.get("buckets", {}).get("61-90", 0),
            "90+": item.get("buckets", {}).get("90+", 0),
            "total": item.get("balance", 0),
        }
        rows.append(row)
    csv_text = _csv_from_rows(rows)
    return Response(csv_text, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=ap_aging.csv"})

@reports_bp.route("/customer-detail/<int:customer_id>", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def customer_detail_report(customer_id):
    from sqlalchemy.orm import load_only

    customer = db.get_or_404(Customer, customer_id)
    balance_data = None
    try:
        balance_data = build_customer_balance_view(customer_id, db.session)
    except Exception as exc:
        current_app.logger.warning("customer_balance_breakdown_failed: %s", exc)

    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    limit_rows = request.args.get("limit", 200, type=int)
    limit_rows = min(5000, max(50, limit_rows))

    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

    base_sales_q = Sale.query.filter(Sale.customer_id == customer_id)
    if start_dt:
        base_sales_q = base_sales_q.filter(Sale.sale_date >= start_dt)
    if end_dt:
        base_sales_q = base_sales_q.filter(Sale.sale_date <= end_dt)
    sales_count = int(base_sales_q.order_by(None).with_entities(func.count(Sale.id)).scalar() or 0)
    sale_fx = case(
        (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Sale.fx_rate_used, 1),
    )
    total_sales = float((base_sales_q.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Sale.total_amount, 0) * sale_fx), 0)).scalar()) or 0)
    sales = (
        base_sales_q.options(
            load_only(Sale.id, Sale.sale_number, Sale.sale_date, Sale.status, Sale.payment_status, Sale.total_amount, Sale.currency, Sale.fx_rate_used),
        )
        .order_by(Sale.sale_date.desc(), Sale.id.desc())
        .limit(limit_rows)
        .all()
    )

    base_inv_q = Invoice.query.filter(Invoice.customer_id == customer_id)
    if start_dt:
        base_inv_q = base_inv_q.filter(Invoice.invoice_date >= start_dt)
    if end_dt:
        base_inv_q = base_inv_q.filter(Invoice.invoice_date <= end_dt)
    invoices_count = int(base_inv_q.order_by(None).with_entities(func.count(Invoice.id)).scalar() or 0)
    inv_fx = case(
        (func.upper(func.coalesce(Invoice.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Invoice.fx_rate_used, 1),
    )
    total_invoices = float((base_inv_q.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Invoice.total_amount, 0) * inv_fx), 0)).scalar()) or 0)
    invoices = (
        base_inv_q.options(
            load_only(Invoice.id, Invoice.invoice_number, Invoice.invoice_date, Invoice.currency, Invoice.fx_rate_used, Invoice.total_amount, Invoice.cancelled_at),
        )
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .limit(limit_rows)
        .all()
    )

    base_srv_q = ServiceRequest.query.filter(ServiceRequest.customer_id == customer_id)
    if start_dt:
        base_srv_q = base_srv_q.filter(ServiceRequest.received_at >= start_dt)
    if end_dt:
        base_srv_q = base_srv_q.filter(ServiceRequest.received_at <= end_dt)
    services_count = int(base_srv_q.order_by(None).with_entities(func.count(ServiceRequest.id)).scalar() or 0)
    srv_fx = case(
        (func.upper(func.coalesce(ServiceRequest.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(ServiceRequest.fx_rate_used, 1),
    )
    total_services = float((base_srv_q.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(ServiceRequest.total_amount, 0) * srv_fx), 0)).scalar()) or 0)
    services = (
        base_srv_q.options(
            load_only(ServiceRequest.id, ServiceRequest.received_at, ServiceRequest.priority, ServiceRequest.mechanic_id, ServiceRequest.total_amount, ServiceRequest.status),
        )
        .order_by(ServiceRequest.received_at.desc(), ServiceRequest.id.desc())
        .limit(limit_rows)
        .all()
    )

    base_pay_q = Payment.query.filter(
        Payment.customer_id == customer_id,
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value,
    )
    if start_dt:
        base_pay_q = base_pay_q.filter(Payment.payment_date >= start_dt)
    if end_dt:
        base_pay_q = base_pay_q.filter(Payment.payment_date <= end_dt)
    payments_count = int(base_pay_q.order_by(None).with_entities(func.count(Payment.id)).scalar() or 0)
    pay_fx = case(
        (func.upper(func.coalesce(Payment.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Payment.fx_rate_used, 1),
    )
    total_payments = float((base_pay_q.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Payment.total_amount, 0) * pay_fx), 0)).scalar()) or 0)
    payments = (
        base_pay_q.options(
            load_only(Payment.id, Payment.payment_date, Payment.method, Payment.total_amount, Payment.currency, Payment.fx_rate_used, Payment.status, Payment.notes),
        )
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit_rows)
        .all()
    )

    base_po_q = OnlinePreOrder.query.filter(OnlinePreOrder.customer_id == customer_id)
    if start_dt:
        base_po_q = base_po_q.filter(OnlinePreOrder.created_at >= start_dt)
    if end_dt:
        base_po_q = base_po_q.filter(OnlinePreOrder.created_at <= end_dt)
    preorders_count = int(base_po_q.order_by(None).with_entities(func.count(OnlinePreOrder.id)).scalar() or 0)
    po_fx = case(
        (func.upper(func.coalesce(OnlinePreOrder.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(OnlinePreOrder.fx_rate_used, 1),
    )
    total_preorders = float((base_po_q.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(OnlinePreOrder.total_amount, 0) * po_fx), 0)).scalar()) or 0)
    preorders = (
        base_po_q.options(
            load_only(OnlinePreOrder.id, OnlinePreOrder.created_at, OnlinePreOrder.total_amount, OnlinePreOrder.currency, OnlinePreOrder.fx_rate_used, OnlinePreOrder.status, OnlinePreOrder.notes),
        )
        .order_by(OnlinePreOrder.created_at.desc(), OnlinePreOrder.id.desc())
        .limit(limit_rows)
        .all()
    )

    current_balance = float(customer.balance or 0)
    if balance_data and balance_data.get("success"):
        current_balance = float(balance_data.get("balance", {}).get("amount", current_balance))

    return render_template(
        "reports/customer_detail.html",
        customer=customer,
        sales=sales,
        invoices=invoices,
        services=services,
        payments=payments,
        preorders=preorders,
        total_sales=total_sales,
        total_invoices=total_invoices,
        total_services=total_services,
        total_payments=total_payments,
        total_preorders=total_preorders,
        limit_rows=limit_rows,
        sales_count=sales_count,
        invoices_count=invoices_count,
        services_count=services_count,
        payments_count=payments_count,
        preorders_count=preorders_count,
        current_balance=current_balance,
        balance_data=balance_data,
        start_date=request.args.get("start", ""),
        end_date=request.args.get("end", ""),
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/supplier-detail/<int:supplier_id>", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def supplier_detail_report(supplier_id):
    from sqlalchemy.orm import load_only
    from datetime import datetime

    supplier = db.get_or_404(Supplier, supplier_id)
    db.session.refresh(supplier)

    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    limit_rows = request.args.get("limit", 200, type=int)
    limit_rows = min(5000, max(50, limit_rows))

    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

    payments_out_query = Payment.query.filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.OUT.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    if start_dt:
        payments_out_query = payments_out_query.filter(Payment.payment_date >= start_dt)
    if end_dt:
        payments_out_query = payments_out_query.filter(Payment.payment_date <= end_dt)
    payments_out_count = int(payments_out_query.order_by(None).with_entities(func.count(Payment.id)).scalar() or 0)
    payments_out = (
        payments_out_query.options(
            load_only(Payment.id, Payment.payment_date, Payment.method, Payment.total_amount, Payment.currency, Payment.fx_rate_used, Payment.status, Payment.notes),
        )
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit_rows)
        .all()
    )
    
    payments_in_query = Payment.query.filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    if start_dt:
        payments_in_query = payments_in_query.filter(Payment.payment_date >= start_dt)
    if end_dt:
        payments_in_query = payments_in_query.filter(Payment.payment_date <= end_dt)
    payments_in_count = int(payments_in_query.order_by(None).with_entities(func.count(Payment.id)).scalar() or 0)
    payments_in = (
        payments_in_query.options(
            load_only(Payment.id, Payment.payment_date, Payment.method, Payment.total_amount, Payment.currency, Payment.fx_rate_used, Payment.status, Payment.notes),
        )
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit_rows)
        .all()
    )

    from models import ExchangeTransaction
    exchange_query = ExchangeTransaction.query.options(
        joinedload(ExchangeTransaction.product),
        joinedload(ExchangeTransaction.warehouse)
    ).filter(
        ExchangeTransaction.supplier_id == supplier_id
    )
    if start_dt:
        exchange_query = exchange_query.filter(ExchangeTransaction.created_at >= start_dt)
    if end_dt:
        exchange_query = exchange_query.filter(ExchangeTransaction.created_at <= end_dt)
    exchange_total_count = int(exchange_query.order_by(None).with_entities(func.count(ExchangeTransaction.id)).scalar() or 0)
    exchange_transactions = exchange_query.order_by(ExchangeTransaction.created_at.desc(), ExchangeTransaction.id.desc()).limit(limit_rows).all()
    exchange_in_count = int(
        exchange_query.order_by(None)
        .filter(ExchangeTransaction.direction.in_(["IN", "PURCHASE", "CONSIGN_IN"]))
        .with_entities(func.count(ExchangeTransaction.id))
        .scalar()
        or 0
    )
    exchange_out_count = int(
        exchange_query.order_by(None)
        .filter(ExchangeTransaction.direction.in_(["OUT", "RETURN", "CONSIGN_OUT"]))
        .with_entities(func.count(ExchangeTransaction.id))
        .scalar()
        or 0
    )

    sales = []
    if supplier.customer_id:
        from models import Sale, SaleStatus, SaleLine
        sales_query = Sale.query.options(
            joinedload(Sale.lines).joinedload(SaleLine.product)
        ).filter(
            Sale.customer_id == supplier.customer_id,
            Sale.status == SaleStatus.CONFIRMED.value
        )
        if start_dt:
            sales_query = sales_query.filter(Sale.sale_date >= start_dt)
        if end_dt:
            sales_query = sales_query.filter(Sale.sale_date <= end_dt)
        sales_count = int(sales_query.order_by(None).with_entities(func.count(Sale.id)).scalar() or 0)
        sales = sales_query.order_by(Sale.sale_date.desc(), Sale.id.desc()).limit(limit_rows).all()
    else:
        sales_count = 0

    services = []
    if supplier.customer_id:
        from models import ServiceRequest, ServiceTask
        services_query = ServiceRequest.query.options(
            joinedload(ServiceRequest.parts).joinedload(ServicePart.part),
            joinedload(ServiceRequest.tasks),
        ).filter(
            ServiceRequest.customer_id == supplier.customer_id,
            ServiceRequest.status == ServiceStatus.COMPLETED.value
        )
        if start_dt:
            services_query = services_query.filter(ServiceRequest.received_at >= start_dt)
        if end_dt:
            services_query = services_query.filter(ServiceRequest.received_at <= end_dt)
        services_count = int(services_query.order_by(None).with_entities(func.count(ServiceRequest.id)).scalar() or 0)
        services = services_query.order_by(ServiceRequest.received_at.desc(), ServiceRequest.id.desc()).limit(limit_rows).all()
    else:
        services_count = 0

    preorders = []
    if supplier.customer_id:
        preorders_query = PreOrder.query.options(
            joinedload(PreOrder.product)
        ).filter(
            PreOrder.customer_id == supplier.customer_id,
            PreOrder.status.in_(['CONFIRMED', 'COMPLETED'])
        )
        if start_dt:
            preorders_query = preorders_query.filter(PreOrder.preorder_date >= start_dt)
        if end_dt:
            preorders_query = preorders_query.filter(PreOrder.preorder_date <= end_dt)
        preorders_count = int(preorders_query.order_by(None).with_entities(func.count(PreOrder.id)).scalar() or 0)
        preorders = preorders_query.order_by(PreOrder.preorder_date.desc(), PreOrder.id.desc()).limit(limit_rows).all()
    else:
        preorders_query = None
        preorders_count = 0

    expenses_query = Expense.query.filter(
        or_(
            Expense.supplier_id == supplier_id,
            and_(Expense.payee_type == 'SUPPLIER', Expense.payee_entity_id == supplier_id)
        )
    )
    if start_dt:
        expenses_query = expenses_query.filter(Expense.date >= start_dt)
    if end_dt:
        expenses_query = expenses_query.filter(Expense.date <= end_dt)
    expenses_count = int(expenses_query.order_by(None).with_entities(func.count(Expense.id)).scalar() or 0)
    expenses = expenses_query.order_by(Expense.date.desc(), Expense.id.desc()).limit(limit_rows).all()

    from routes.supplier_settlements import _calculate_smart_supplier_balance
    from decimal import Decimal
    
    date_from = start_date if start_date else datetime(2024, 1, 1)
    date_to = end_date if end_date else datetime.now()
    
    try:
        balance_data = _calculate_smart_supplier_balance(supplier_id, date_from, date_to)
    except Exception as e:
        current_app.logger.exception('supplier balance calculation error')
        balance_data = {"success": False, "error": "حدث خطأ داخلي"}
    
    if balance_data and balance_data.get("success"):
        total_exchange_in = Decimal(str(balance_data.get("rights", {}).get("exchange_items", {}).get("total_value_ils", 0)))
        total_payments_out = Decimal(str(balance_data.get("payments", {}).get("total_paid", 0)))
        total_payments_in = Decimal(str(balance_data.get("payments", {}).get("total_received", 0)))
        total_obligations = Decimal(str(balance_data.get("obligations", {}).get("total", 0)))
        total_sales = Decimal(str(balance_data.get("obligations", {}).get("sales_to_supplier", {}).get("total_ils", 0)))
        total_services = Decimal(str(balance_data.get("obligations", {}).get("services_to_supplier", {}).get("total_ils", 0)))
        total_preorders = Decimal(str(balance_data.get("obligations", {}).get("preorders_to_supplier", {}).get("total_ils", 0) if isinstance(balance_data.get("obligations", {}).get("preorders_to_supplier"), dict) else 0))
        total_expenses = Decimal(str(balance_data.get("expenses", {}).get("total_ils", 0)))
        total_exchange_out = Decimal(str(balance_data.get("payments", {}).get("total_returns", 0)))
    else:
        pay_fx = case(
            (func.upper(func.coalesce(Payment.currency, "ILS")) == "ILS", 1),
            else_=func.coalesce(Payment.fx_rate_used, 1),
        )
        total_payments_out = Decimal(
            str(
                (payments_out_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Payment.total_amount, 0) * pay_fx), 0)).scalar())
                or 0
            )
        )
        total_payments_in = Decimal(
            str(
                (payments_in_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Payment.total_amount, 0) * pay_fx), 0)).scalar())
                or 0
            )
        )

        tx_amount = func.coalesce(ExchangeTransaction.quantity, 0) * func.coalesce(ExchangeTransaction.unit_cost, 0)
        total_exchange_in = Decimal(
            str(
                (
                    exchange_query.order_by(None)
                    .filter(ExchangeTransaction.direction.in_(["IN", "PURCHASE", "CONSIGN_IN"]))
                    .with_entities(func.coalesce(func.sum(tx_amount), 0))
                    .scalar()
                )
                or 0
            )
        )
        total_exchange_out = Decimal(
            str(
                (
                    exchange_query.order_by(None)
                    .filter(ExchangeTransaction.direction.in_(["OUT", "RETURN", "CONSIGN_OUT"]))
                    .with_entities(func.coalesce(func.sum(tx_amount), 0))
                    .scalar()
                )
                or 0
            )
        )

        if supplier.customer_id:
            sale_fx = case(
                (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
                else_=func.coalesce(Sale.fx_rate_used, 1),
            )
            total_sales = Decimal(
                str(
                    (sales_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Sale.total_amount, 0) * sale_fx), 0)).scalar())
                    or 0
                )
            )
            srv_fx = case(
                (func.upper(func.coalesce(ServiceRequest.currency, "ILS")) == "ILS", 1),
                else_=func.coalesce(ServiceRequest.fx_rate_used, 1),
            )
            total_services = Decimal(
                str(
                    (services_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(ServiceRequest.total_amount, 0) * srv_fx), 0)).scalar())
                    or 0
                )
            )
            po_fx = case(
                (func.upper(func.coalesce(PreOrder.currency, "ILS")) == "ILS", 1),
                else_=func.coalesce(PreOrder.fx_rate_used, 1),
            )
            total_preorders = Decimal(
                str(
                    (preorders_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(PreOrder.total_amount, 0) * po_fx), 0)).scalar())
                    or 0
                )
            ) if preorders_query is not None else Decimal("0.00")
        else:
            total_sales = Decimal("0.00")
            total_services = Decimal("0.00")
            total_preorders = Decimal("0.00")

        total_obligations = total_sales + total_services + total_preorders

        exp_fx = case(
            (func.upper(func.coalesce(Expense.currency, "ILS")) == "ILS", 1),
            else_=func.coalesce(Expense.fx_rate_used, 1),
        )
        total_expenses = Decimal(
            str(
                (expenses_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Expense.amount, 0) * exp_fx), 0)).scalar())
                or 0
            )
        )

    current_balance = balance_data.get('balance', {}).get('amount', 0) if balance_data.get('success') else float(supplier.balance or 0)

    supplier_breakdown = None
    try:
        supplier_breakdown = build_supplier_balance_view(supplier_id, db.session)
    except Exception as exc:
        current_app.logger.warning("supplier_balance_breakdown_report_failed: %s", exc)
    if supplier_breakdown and supplier_breakdown.get("success"):
        current_balance = float(supplier_breakdown.get("balance", {}).get("amount", current_balance))

    return render_template(
        "reports/supplier_detail.html",
        supplier=supplier,
        payments_out=payments_out,
        payments_in=payments_in,
        exchange_transactions=exchange_transactions,
        sales=sales,
        services=services,
        preorders=preorders,
        expenses=expenses,
        balance_data=balance_data,
        total_payments_out=float(total_payments_out),
        total_payments_in=float(total_payments_in),
        total_exchange_in=float(total_exchange_in),
        total_exchange_out=float(total_exchange_out),
        total_sales=float(total_sales),
        total_services=float(total_services),
        total_preorders=float(total_preorders),
        total_expenses=float(total_expenses),
        total_obligations=float(total_obligations),
        current_balance=current_balance,
        supplier_breakdown=supplier_breakdown,
        limit_rows=limit_rows,
        payments_in_count=payments_in_count,
        payments_out_count=payments_out_count,
        exchange_total_count=exchange_total_count,
        exchange_in_count=exchange_in_count,
        exchange_out_count=exchange_out_count,
        sales_count=sales_count,
        services_count=services_count,
        preorders_count=preorders_count,
        expenses_count=expenses_count,
        start_date=request.args.get("start", ""),
        end_date=request.args.get("end", ""),
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )

@reports_bp.route("/partner-detail/<int:partner_id>", methods=["GET"])
@login_required
@utils.permission_required(SystemPermissions.VIEW_REPORTS)
def partner_detail_report(partner_id):
    from sqlalchemy.orm import load_only

    partner = db.get_or_404(Partner, partner_id)

    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    limit_rows = request.args.get("limit", 200, type=int)
    limit_rows = min(5000, max(50, limit_rows))

    from routes.partner_settlements import _calculate_smart_partner_balance
    from datetime import datetime

    date_from = start_date if start_date else datetime(2024, 1, 1)
    date_to = end_date if end_date else datetime.now()

    try:
        balance_data = _calculate_smart_partner_balance(partner_id, date_from, date_to)
    except Exception as exc:
        balance_data = {"success": False, "error": str(exc)}

    inventory = []
    if isinstance(balance_data, dict) and balance_data.get("success"):
        rights = balance_data.get("rights") if isinstance(balance_data.get("rights"), dict) else {}
        sales_share = rights.get("sales_share")
        if isinstance(sales_share, dict) and "sales" not in rights:
            rights["sales"] = {
                "items": sales_share.get("items") or [],
                "count": int(sales_share.get("count") or 0),
                "total_ils": float(
                    sales_share.get("total_share_ils")
                    or sales_share.get("total_ils")
                    or sales_share.get("total")
                    or 0
                ),
            }
        balance_data["rights"] = rights

        inv = rights.get("inventory")
        if isinstance(inv, dict):
            inv_items = inv.get("items") or []
            try:
                from types import SimpleNamespace

                for item in inv_items:
                    if not isinstance(item, dict):
                        continue
                    notes_parts = []
                    if item.get("warehouse"):
                        notes_parts.append(f"المستودع: {item.get('warehouse')}")
                    if item.get("quantity") is not None:
                        notes_parts.append(f"الكمية: {item.get('quantity')}")
                    inventory.append(
                        SimpleNamespace(
                            product=SimpleNamespace(
                                id=item.get("product_id"),
                                name=item.get("product_name"),
                            ),
                            share_percent=item.get("share_percentage"),
                            share_amount=item.get("partner_share"),
                            notes=" - ".join(notes_parts) if notes_parts else None,
                        )
                    )
            except Exception:
                inventory = []

    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

    payments_out_query = Payment.query.filter(
        Payment.partner_id == partner_id,
        Payment.direction == PaymentDirection.OUT.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    if start_dt:
        payments_out_query = payments_out_query.filter(Payment.payment_date >= start_dt)
    if end_dt:
        payments_out_query = payments_out_query.filter(Payment.payment_date <= end_dt)
    payments_out_count = int(payments_out_query.order_by(None).with_entities(func.count(Payment.id)).scalar() or 0)
    payments_out = (
        payments_out_query.options(load_only(Payment.id, Payment.payment_date, Payment.method, Payment.total_amount, Payment.currency, Payment.fx_rate_used, Payment.notes))
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit_rows)
        .all()
    )
    
    payments_in_query = Payment.query.filter(
        Payment.partner_id == partner_id,
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value
    )
    if start_dt:
        payments_in_query = payments_in_query.filter(Payment.payment_date >= start_dt)
    if end_dt:
        payments_in_query = payments_in_query.filter(Payment.payment_date <= end_dt)
    payments_in_count = int(payments_in_query.order_by(None).with_entities(func.count(Payment.id)).scalar() or 0)
    payments_in = (
        payments_in_query.options(load_only(Payment.id, Payment.payment_date, Payment.method, Payment.total_amount, Payment.currency, Payment.fx_rate_used, Payment.notes))
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit_rows)
        .all()
    )

    sales = []
    sales_count = 0
    if partner.customer_id:
        sales_query = Sale.query.options(
            joinedload(Sale.lines).joinedload(SaleLine.product),
        ).filter(
            Sale.customer_id == partner.customer_id,
            Sale.status == SaleStatus.CONFIRMED.value
        )
        if start_dt:
            sales_query = sales_query.filter(Sale.sale_date >= start_dt)
        if end_dt:
            sales_query = sales_query.filter(Sale.sale_date <= end_dt)
        sales_count = int(sales_query.order_by(None).with_entities(func.count(Sale.id)).scalar() or 0)
        sales = sales_query.order_by(Sale.sale_date.desc(), Sale.id.desc()).limit(limit_rows).all()

    services = []
    services_count = 0
    if partner.customer_id:
        services_query = ServiceRequest.query.options(
            joinedload(ServiceRequest.parts).joinedload(ServicePart.part),
            joinedload(ServiceRequest.tasks),
        ).filter(
            ServiceRequest.customer_id == partner.customer_id,
            ServiceRequest.status == ServiceStatus.COMPLETED.value
        )
        if start_dt:
            services_query = services_query.filter(ServiceRequest.received_at >= start_dt)
        if end_dt:
            services_query = services_query.filter(ServiceRequest.received_at <= end_dt)
        services_count = int(services_query.order_by(None).with_entities(func.count(ServiceRequest.id)).scalar() or 0)
        services = services_query.order_by(ServiceRequest.received_at.desc(), ServiceRequest.id.desc()).limit(limit_rows).all()

    preorders_query = PreOrder.query.options(
        joinedload(PreOrder.product)
    ).filter(PreOrder.partner_id == partner_id)
    if start_dt:
        preorders_query = preorders_query.filter(PreOrder.created_at >= start_dt)
    if end_dt:
        preorders_query = preorders_query.filter(PreOrder.created_at <= end_dt)
    preorders_count = int(preorders_query.order_by(None).with_entities(func.count(PreOrder.id)).scalar() or 0)
    preorders = preorders_query.order_by(PreOrder.created_at.desc(), PreOrder.id.desc()).limit(limit_rows).all()

    service_parts_query = ServicePart.query.options(
        joinedload(ServicePart.part),
        joinedload(ServicePart.request)
    ).filter(ServicePart.partner_id == partner_id)
    if start_dt:
        service_parts_query = service_parts_query.filter(ServicePart.created_at >= start_dt)
    if end_dt:
        service_parts_query = service_parts_query.filter(ServicePart.created_at <= end_dt)
    service_parts_count = int(service_parts_query.order_by(None).with_entities(func.count(ServicePart.id)).scalar() or 0)
    service_parts = service_parts_query.order_by(ServicePart.created_at.desc(), ServicePart.id.desc()).limit(limit_rows).all()

    expenses_query = Expense.query.filter(
        or_(
            Expense.partner_id == partner_id,
            and_(Expense.payee_type == 'PARTNER', Expense.payee_entity_id == partner_id)
        )
    )
    if start_dt:
        expenses_query = expenses_query.filter(Expense.date >= start_dt)
    if end_dt:
        expenses_query = expenses_query.filter(Expense.date <= end_dt)
    expenses_count = int(expenses_query.order_by(None).with_entities(func.count(Expense.id)).scalar() or 0)
    expenses = expenses_query.order_by(Expense.date.desc(), Expense.id.desc()).limit(limit_rows).all()

    pay_fx = case(
        (func.upper(func.coalesce(Payment.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Payment.fx_rate_used, 1),
    )
    total_payments_out = float((payments_out_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Payment.total_amount, 0) * pay_fx), 0)).scalar()) or 0)
    total_payments_in = float((payments_in_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Payment.total_amount, 0) * pay_fx), 0)).scalar()) or 0)
    total_inventory = Decimal(str(partner.inventory_balance or 0))
    total_sales_share = Decimal(str(partner.sales_share_balance or 0))
    total_obligations = (
        Decimal(str(partner.sales_to_partner_balance or 0)) +
        Decimal(str(partner.service_fees_balance or 0)) +
        Decimal(str(partner.preorders_to_partner_balance or 0)) +
        Decimal(str(partner.damaged_items_balance or 0))
    )

    sale_total = 0.0
    if partner.customer_id:
        sale_fx = case(
            (func.upper(func.coalesce(Sale.currency, "ILS")) == "ILS", 1),
            else_=func.coalesce(Sale.fx_rate_used, 1),
        )
        total_sales = float((sales_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Sale.total_amount, 0) * sale_fx), 0)).scalar()) or 0)
    else:
        total_sales = float(sale_total)

    srv_total = 0.0
    if partner.customer_id:
        srv_fx = case(
            (func.upper(func.coalesce(ServiceRequest.currency, "ILS")) == "ILS", 1),
            else_=func.coalesce(ServiceRequest.fx_rate_used, 1),
        )
        total_services = float((services_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(ServiceRequest.total_amount, 0) * srv_fx), 0)).scalar()) or 0)
    else:
        total_services = float(srv_total)

    po_fx = case(
        (func.upper(func.coalesce(PreOrder.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(PreOrder.fx_rate_used, 1),
    )
    total_preorders = float((preorders_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(PreOrder.total_amount, 0) * po_fx), 0)).scalar()) or 0)

    total_service_parts = float(
        (
            service_parts_query.order_by(None)
            .with_entities(func.coalesce(func.sum(func.coalesce(ServicePart.quantity, 0) * func.coalesce(ServicePart.unit_price, 0)), 0))
            .scalar()
        )
        or 0
    )

    exp_fx = case(
        (func.upper(func.coalesce(Expense.currency, "ILS")) == "ILS", 1),
        else_=func.coalesce(Expense.fx_rate_used, 1),
    )
    total_expenses = float((expenses_query.order_by(None).with_entities(func.coalesce(func.sum(func.coalesce(Expense.amount, 0) * exp_fx), 0)).scalar()) or 0)

    if isinstance(balance_data, dict) and balance_data.get("success"):
        inv_total = balance_data.get("rights", {}).get("inventory", {}).get("total_ils", 0)
        try:
            total_inventory = Decimal(str(inv_total or 0))
        except Exception:
            pass

    partner_breakdown = None
    try:
        partner_breakdown = build_partner_balance_view(partner_id, db.session)
    except Exception as exc:
        current_app.logger.warning("partner_balance_breakdown_report_failed: %s", exc)
    current_balance = float(partner.balance or 0)
    if partner_breakdown and partner_breakdown.get("success"):
        current_balance = float(partner_breakdown.get("balance", {}).get("amount", current_balance))
    if isinstance(balance_data, dict) and balance_data.get("success"):
        current_balance = float(balance_data.get("balance", {}).get("amount", current_balance))

    partner_share = (float(partner.share_percentage or 0) / 100) * (float(total_preorders) + float(total_service_parts)) if partner.share_percentage else 0

    return render_template(
        "reports/partner_detail.html",
        partner=partner,
        payments_out=payments_out,
        payments_in=payments_in,
        sales=sales,
        services=services,
        preorders=preorders,
        service_parts=service_parts,
        expenses=expenses,
        inventory=inventory,
        balance_data=balance_data,
        partner_breakdown=partner_breakdown,
        total_payments_out=float(total_payments_out),
        total_payments_in=float(total_payments_in),
        total_sales=float(total_sales),
        total_services=float(total_services),
        total_preorders=float(total_preorders),
        total_service_parts=float(total_service_parts),
        total_expenses=float(total_expenses),
        total_inventory=float(total_inventory),
        total_sales_share=float(total_sales_share),
        total_obligations=float(total_obligations),
        partner_share=partner_share,
        current_balance=current_balance,
        limit_rows=limit_rows,
        payments_out_count=payments_out_count,
        payments_in_count=payments_in_count,
        sales_count=sales_count,
        services_count=services_count,
        preorders_count=preorders_count,
        service_parts_count=service_parts_count,
        expenses_count=expenses_count,
        start_date=request.args.get("start", ""),
        end_date=request.args.get("end", ""),
        FIELD_LABELS=FIELD_LABELS,
        MODEL_LABELS=MODEL_LABELS,
    )
