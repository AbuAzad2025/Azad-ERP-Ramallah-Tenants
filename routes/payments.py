from __future__ import annotations

import re
import uuid
from io import BytesIO
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

from flask import (
    Response,
    abort,
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    session,
    send_file,
    make_response,
)
from extensions import csrf
from flask_login import current_user, login_required
from sqlalchemy import (
    func,
    and_,
    case,
    or_,
    select,
    text as sa_text,
    nullslast,
)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload, load_only

from extensions import db
from forms import PaymentForm
from models import (
    Check,
    CheckStatus,
    Customer,
    Expense,
    ExpenseType,
    Invoice,
    Partner,
    Payment,
    PaymentDirection,
    PaymentMethod,
    PaymentSplit,
    PaymentStatus,
    PaymentProgress,
    PreOrder,
    PreOrderStatus,
    Sale,
    SaleStatus,
    ServiceRequest,
    Shipment,
    Supplier,
    SupplierLoanSettlement,
    get_fx_rate_with_fallback,
    run_payment_gl_sync_after_commit,
)
import utils
from routes.partner_settlements import _calculate_smart_partner_balance
from routes.checks import create_check_record, CheckActionService
from utils import D, q0, archive_record, restore_record, permission_required
from permissions_config.enums import SystemPermissions
from constants import DEFAULT_CURRENCY
try:
    from acl import super_only
except Exception:
    from functools import wraps
    def super_only(f):
        @wraps(f)
        @login_required
        def _w(*a, **kw):
            if utils.is_super():
                return f(*a, **kw)
            abort(403)
        return _w
# Blueprint definition
payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

SMART_PARTNER_BALANCE_START = datetime(2024, 1, 1)

_FULL_LOAD_OPTIONS = (
    joinedload(Payment.customer),
    joinedload(Payment.supplier),
    joinedload(Payment.partner),
    joinedload(Payment.sale),
    joinedload(Payment.invoice),
    joinedload(Payment.service),
    joinedload(Payment.preorder),
    joinedload(Payment.shipment),
    joinedload(Payment.loan_settlement),
    joinedload(Payment.splits),
)

def _wants_json() -> bool:
    fmt = (request.args.get("format") or "").lower()
    if fmt in ("json", "1", "true", "yes"):
        return True
    try:
        best = request.accept_mimetypes.best or ""
    except Exception:
        best = ""
    return best == "application/json" or request.path.startswith("/api/")

def _safe_filename_component(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"[^0-9A-Za-z\u0600-\u06FF\-\._]", "", s)
    return s[:120] or ""

def _ok_not_found(msg: str = "السند غير موجود"):
    if _wants_json():
        return jsonify(error="not_found", message=msg), 200
    html = "<!doctype html><meta charset='utf-8'><title>غير موجود</title><div style='padding:24px;font-family:system-ui,Arial,sans-serif'>" + msg + "</div>"
    return make_response(html, 200)

def _safe_get_payment(payment_id: int, *, all_rels: bool = False) -> Payment | None:
    try:
        opts = _FULL_LOAD_OPTIONS if all_rels else (joinedload(Payment.customer), joinedload(Payment.supplier))
        stmt = select(Payment).options(*opts).where(Payment.id == int(payment_id))
        return db.session.execute(stmt).unique().scalar_one_or_none()
    except Exception:
        return None


def _f2(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0

def _line_total(qty, unit_price, disc_pct, tax_pct):
    qy = int(qty or 0)
    u = _f2(unit_price)
    d = _f2(disc_pct)
    t = _f2(tax_pct)
    gross = qy * u
    disc = gross * (d / 100.0)
    taxable = gross - disc
    tax = taxable * (t / 100.0)
    taxable_d = q0(taxable)
    tax_d = q0(tax)
    total_d = q0(taxable_d + tax_d)
    return taxable_d, tax_d, total_d

def _service_totals(svc: ServiceRequest):
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    grand = Decimal("0")
    for p in (getattr(svc, "parts", None) or []):
        s, t, g = _line_total(p.quantity, p.unit_price, p.discount, p.tax_rate)
        subtotal += s
        tax_total += t
        grand += g
    for tsk in (getattr(svc, "tasks", None) or []):
        s, t, g = _line_total(tsk.quantity or 1, tsk.unit_price, tsk.discount, tsk.tax_rate)
        subtotal += s
        tax_total += t
        grand += g
    return int(q0(subtotal)), int(q0(tax_total)), int(q0(grand))

def _sale_info_dict(sale) -> dict | None:
    if not sale:
        return None
    try:
        return {
            "number": getattr(sale, "sale_number", None),
            "date": sale.sale_date.strftime("%Y-%m-%d") if getattr(sale, "sale_date", None) else "-",
            "total": int(q0(getattr(sale, "total_amount", 0) or 0)),
            "paid": int(q0(getattr(sale, "total_paid", 0) or 0)),
            "balance": int(q0(getattr(sale, "balance_due", 0) or 0)),
            "currency": (getattr(sale, "currency", "") or "").upper(),
        }
    except Exception:
        return None

def _clean_details(d: dict | None):
    if not d:
        return None
    cleaned = {}
    for k, v in d.items():
        if v in (None, "", []):
            continue
        if isinstance(v, (date, datetime)):
            cleaned[k] = v.isoformat()
        else:
            cleaned[k] = str(v)
    return cleaned or None

def _val(x):
    return getattr(x, "value", x)

def _coerce_method(v):
    s = str(_val(v) or "").strip()
    if not s:
        return PaymentMethod.CASH
    name_up = s.replace("-", "_").upper()
    for m in PaymentMethod:
        if m.name == name_up:
            return m
    for m in PaymentMethod:
        val = str(m.value).strip()
        if val.upper() == name_up or val.lower() == s.lower():
            return m
    return PaymentMethod.CASH

def _norm_dir(val):
    if val is None:
        return None
    v = val.value if hasattr(val, "value") else val
    v = str(v).strip().upper()
    if v in (PaymentDirection.IN.value, "INCOMING", "INCOME", "RECEIVE"):
        return PaymentDirection.IN.value
    if v in (PaymentDirection.OUT.value, "OUTGOING", "PAY", "PAYMENT", "EXPENSE"):
        return PaymentDirection.OUT.value
    return v

def _dir_to_db(v: str | None):
    vv = _norm_dir(v)
    return vv

def _sync_payment_method_with_splits(pmt: Payment):
    try:
        splits = list(pmt.splits or [])
    except Exception:
        splits = []
    if not splits:
        if not getattr(pmt, "method", None):
            pmt.method = PaymentMethod.CASH.value
        return
    first = splits[0]
    new_m = getattr(first, "method", None)
    new_m_val = getattr(new_m, "value", new_m)
    if new_m_val and new_m_val != getattr(pmt, "method", None):
        pmt.method = new_m_val

def _serialize_split(s):
    return {
        "id": s.id,
        "amount": int(q0(getattr(s, "amount", 0) or 0)),
        "method": (getattr(getattr(s, "method", None), "value", getattr(s, "method", "")) or ""),
        "details": (getattr(s, "details", None) or None),
        "currency": getattr(s, "currency", None),
        "converted_amount": float(q0(getattr(s, "converted_amount", 0) or 0)),
        "converted_currency": getattr(s, "converted_currency", None),
        "fx_rate_used": float(getattr(s, "fx_rate_used", 0) or 0) if getattr(s, "fx_rate_used", None) is not None else None,
        "fx_rate_source": getattr(s, "fx_rate_source", None),
    }

def _serialize_payment_min(p, *, full=False):
    is_manual_check = getattr(p, "is_manual_check", False)
    payment_date = getattr(p, "payment_date", None)
    if is_manual_check and hasattr(p, "_check_obj"):
        payment_date = p._check_obj.check_date
    
    # ✅ حساب المبلغ بالشيكل في الباكند
    amount_in_ils = float(p.total_amount or 0)
    if p.currency and p.currency != 'ILS':
        try:
            from models import convert_amount
            amount_in_ils = float(convert_amount(p.total_amount, p.currency, 'ILS', payment_date))
        except Exception:
            # fallback: استخدام fx_rate_used المحفوظ
            if p.fx_rate_used and p.fx_rate_used > 0:
                amount_in_ils = float(p.total_amount or 0) * float(p.fx_rate_used)
    
    d = {
        "id": p.id,
        "is_archived": getattr(p, "is_archived", False),
        "payment_date": (payment_date.isoformat() if payment_date else None),
        "total_amount": int(q0(getattr(p, "total_amount", 0) or 0)),
        "currency": getattr(p, "currency", "ILS") or "ILS",
        "amount_in_ils": amount_in_ils,  # ✅ إضافة المبلغ بالشيكل من الباكند
        "fx_rate_used": float(p.fx_rate_used) if p.fx_rate_used else None,
        "fx_rate_source": p.fx_rate_source if hasattr(p, 'fx_rate_source') else None,
        "method": (getattr(getattr(p, "method", None), "value", getattr(p, "method", "")) or ""),
        "direction": (getattr(getattr(p, "direction", None), "value", getattr(p, "direction", "")) or ""),
        "status": (getattr(getattr(p, "status", None), "value", getattr(p, "status", "")) or ""),
        "entity_type": getattr(p, "entity_type", "") or "",
        "entity_display": p.entity_label() if hasattr(p, "entity_label") else (getattr(p, "entity_type", "") or ""),
        "splits": [_serialize_split(s) for s in (list(getattr(p, "splits", []) or []))],
        "is_manual_check": is_manual_check,
    }
    try:
        if not d["entity_display"] or d["entity_display"].strip() in ("", "غير مرتبط"):
            name_fallback = _resolve_counterparty_name(
                person_name=getattr(p, "deliverer_name", None),
                customer_id=getattr(p, "customer_id", None),
                supplier_id=getattr(p, "supplier_id", None),
                partner_id=getattr(p, "partner_id", None),
                fallback=getattr(p, "reference", None),
            )
            if name_fallback:
                d["entity_display"] = name_fallback
    except Exception:
        current_app.logger.debug('attribute access failed in payments.py', exc_info=True)
    if hasattr(p, 'payment_id') and hasattr(p, 'split_id'):
        try:
            d["payment_id"] = int(getattr(p, 'payment_id'))
            d["split_id"] = int(getattr(p, 'split_id'))
        except Exception:
            current_app.logger.warning('payment processing failed silently in payments.py', exc_info=True)
    if hasattr(p, 'is_refunded_split'):
        d["is_refunded_split"] = bool(getattr(p, 'is_refunded_split'))
    if is_manual_check:
        d["check_id"] = getattr(p, "check_id", None)
        d["check_number"] = getattr(p, "check_number", None)
    d["deliverer_name"] = getattr(p, "deliverer_name", None)
    d["receiver_name"] = getattr(p, "receiver_name", None)
    d["service_id"] = getattr(p, "service_id", None)
    if getattr(p, "service_id", None):
        svc = getattr(p, "service", None)
        if svc is None and getattr(p, "service_id", None):
            try:
                svc = db.session.get(ServiceRequest, int(p.service_id))
            except Exception:
                svc = None
        if svc is not None:
            d["service_number"] = svc.service_number or svc.id
            d["service_vehicle"] = svc.vehicle_model or svc.vehicle_vrn or getattr(getattr(svc, "vehicle_type", None), "name", None)
            d["service_customer_name"] = getattr(getattr(svc, "customer", None), "name", None)
    if full:
        d.update({
            "payment_number": getattr(p, "payment_number", None),
            "receipt_number": getattr(p, "receipt_number", None),
            "reference": getattr(p, "reference", None),
            "notes": getattr(p, "notes", None),
            "deliverer_name": getattr(p, "deliverer_name", None),
            "receiver_name": getattr(p, "receiver_name", None),
            "customer_id": getattr(p, "customer_id", None),
            "supplier_id": getattr(p, "supplier_id", None),
            "partner_id": getattr(p, "partner_id", None),
            "sale_id": getattr(p, "sale_id", None),
            "invoice_id": getattr(p, "invoice_id", None),
            "service_id": getattr(p, "service_id", None),
            "expense_id": getattr(p, "expense_id", None),
            "preorder_id": getattr(p, "preorder_id", None),
            "shipment_id": getattr(p, "shipment_id", None),
            "loan_settlement_id": getattr(p, "loan_settlement_id", None),
        })
    return d

def _serialize_payment(p, *, full=False):
    return _serialize_payment_min(p, full=full)

def _resolve_user_display():
    for attr in ("display_name", "full_name", "name", "username", "email"):
        val = getattr(current_user, attr, None)
        if val:
            s = str(val).strip()
            if s:
                return s
    return ""

def _clean_name(value):
    if isinstance(value, dict):
        value = value.get("name")
    if value is None:
        return ""
    s = str(value).strip()
    return s or ""

def _resolve_counterparty_name(person_name=None, customer_id=None, supplier_id=None, partner_id=None, fallback=None):
    for src in (person_name, fallback):
        name = _clean_name(src)
        if name:
            return name
    if customer_id:
        obj = db.session.get(Customer, customer_id)
        name = _clean_name(getattr(obj, "name", None) if obj else None)
        if name:
            return name
    if supplier_id:
        obj = db.session.get(Supplier, supplier_id)
        name = _clean_name(getattr(obj, "name", None) if obj else None)
        if name:
            return name
    if partner_id:
        obj = db.session.get(Partner, partner_id)
        name = _clean_name(getattr(obj, "name", None) if obj else None)
        if name:
            return name
    return ""

def ensure_currency(cur):
    try:
        from models import ensure_currency as _ensure_ccy
    except Exception:
        _ensure_ccy = None
    if _ensure_ccy:
        return _ensure_ccy(cur)
    return (cur or "ILS").strip().upper()

def _render_payment_receipt_pdf(payment: Payment) -> bytes | None:
    """Render payment receipt as PDF. Returns None if WeasyPrint is unavailable (e.g. GTK missing on Windows)."""
    try:
        from weasyprint import HTML, CSS
    except (ImportError, OSError) as e:
        current_app.logger.warning(
            "weasyprint_unavailable: %s (PDF download disabled; use HTML receipt + print)",
            str(e),
            extra={"payment_id": getattr(payment, "id", None)},
        )
        return None
    html = render_template("payments/receipt.html", payment=payment, now=_utc_now_naive())
    css_inline = "@page { size: A4; margin: 14mm; } html, body { direction: rtl; font-family: 'Cairo','Noto Naskh Arabic',Arial,sans-serif; font-size: 12px; } h1,h2,h3 { margin: 0 0 8px 0; } table { width: 100%; border-collapse: collapse; } th, td { padding: 6px 8px; border-bottom: 1px solid #ddd; } .muted { color: #666; }"
    try:
        return HTML(string=html, base_url=request.url_root).write_pdf(stylesheets=[CSS(string=css_inline)])
    except Exception:
        current_app.logger.exception("payment.receipt_pdf_failed", extra={"payment_id": getattr(payment, "id", None)})
        try:
            return HTML(string=html, base_url=request.url_root).write_pdf()
        except Exception:
            return None

MAX_SEARCH_LIMIT = 25

@payments_bp.route("/entity-search", methods=["GET"])
@login_required
def entity_search():
    t = (request.args.get("type") or "").strip().upper()
    qtxt = (request.args.get("q") or "").strip()
    limit = min(request.args.get("limit", 8, type=int) or 8, MAX_SEARCH_LIMIT)
    if len(qtxt) < 2:
        return jsonify(results=[])
    like = f"%{qtxt}%"
    def rows_for(model, extra_cols=("phone", "mobile", "email")):
        conds = [getattr(model, "name").ilike(like)]
        for c in extra_cols:
            col = getattr(model, c, None)
            if col is not None:
                conds.append(col.ilike(like))
        return db.session.query(model).options(
            load_only(model.id, model.name, getattr(model, "phone", None), getattr(model, "mobile", None), getattr(model, "email", None))
        ).filter(or_(*conds)).order_by(getattr(model, "name").asc()).limit(limit).all()
    results = []
    if t == "CUSTOMER":
        rows = rows_for(Customer); results = [{"id": r.id, "label": r.name, "extra": (getattr(r, "phone", "") or getattr(r, "mobile", "") or "")} for r in rows]
    elif t == "SUPPLIER":
        rows = rows_for(Supplier); results = [{"id": r.id, "label": r.name, "extra": (getattr(r, "phone", "") or getattr(r, "mobile", "") or "")} for r in rows]
    elif t == "PARTNER":
        rows = rows_for(Partner); results = [{"id": r.id, "label": r.name, "extra": ""} for r in rows]
    elif t == "LOAN":
        qdigits = "".join(ch for ch in qtxt if ch.isdigit())
        qry = db.session.query(SupplierLoanSettlement, Supplier.name.label("supplier_name")).join(Supplier, Supplier.id == SupplierLoanSettlement.supplier_id)
        conds = []
        if qdigits:
            try:
                conds.append(SupplierLoanSettlement.id == int(qdigits))
            except Exception:
                current_app.logger.debug('numeric conversion failed in payments.py', exc_info=True)
        conds.append(Supplier.name.ilike(like))
        rows = qry.filter(or_(*conds)).order_by(SupplierLoanSettlement.id.desc()).limit(limit).all()
        results = [{"id": r[0].id, "label": f"Loan Settlement #{r[0].id}", "extra": r[1]} for r in rows]
    return jsonify(results=results)

@payments_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    if not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login", next=request.full_path))
    page = request.args.get("page", 1, type=int)
    per_page = 10
    print_mode = request.args.get("print") == "1"
    scope_param = request.args.get("scope")
    print_scope = scope_param or ("page" if print_mode else "all")
    range_start = request.args.get("range_start", type=int)
    range_end = request.args.get("range_end", type=int)
    target_page = request.args.get("page_number", type=int)
    entity_type = (request.args.get("entity_type") or request.args.get("entity") or "").strip().upper()
    search_term = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    direction = (request.args.get("direction") or "").strip()
    method = (request.args.get("method") or "").strip()
    start_date = (request.args.get("start_date") or request.args.get("start") or "").strip()
    end_date = (request.args.get("end_date") or request.args.get("end") or "").strip()
    currency_param = (request.args.get("currency") or "").strip().upper()
    entity_id = request.args.get("entity_id", type=int)
    reference_like = (request.args.get("reference") or "").strip()
    filters = []
    if entity_type:
        filters.append(Payment.entity_type == entity_type)
    if status:
        st_val = status.strip().upper(); mapped = None
        try:
            for s in PaymentStatus:
                if s.name == st_val or str(s.value).strip().upper() == st_val:
                    mapped = s.value
                    break
        except Exception:
            mapped = None
        filters.append(Payment.status == (mapped or st_val))
    if direction:
        filters.append(Payment.direction == _dir_to_db(direction))
    if method:
        try:
            m = _coerce_method(method); mv = getattr(m, "value", m); filters.append(Payment.method == mv)
        except Exception:
            filters.append(Payment.method == method)
    if currency_param:
        filters.append(Payment.currency == ensure_currency(currency_param))
    def _parse_ymd(s: str | None):
        if not s:
            return None
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except Exception:
            return None
    sd = _parse_ymd(start_date); ed = _parse_ymd(end_date)
    if sd:
        filters.append(Payment.payment_date >= datetime.combine(sd, time.min))
    if ed:
        filters.append(Payment.payment_date <= datetime.combine(ed, time.max))
    partner_obj = None
    selected_partner = None
    partner_ledger = None
    if entity_type == "PARTNER" and entity_id:
        partner_obj = db.session.get(Partner, entity_id)
        selected_partner = _get_partner_balance_details(partner_obj)
        ledger_from = datetime.combine(sd, time.min) if sd else None
        ledger_to = datetime.combine(ed, time.max) if ed else None
        if partner_obj:
            partner_ledger = _build_partner_ledger(partner_obj, selected_partner, ledger_from, ledger_to)
    if entity_id and entity_type:
        et = entity_type.lower()
        if et == "customer":
            filters.append(Payment.customer_id == entity_id)
        elif et == "supplier":
            filters.append(Payment.supplier_id == entity_id)
        elif et == "partner":
            filters.append(Payment.partner_id == entity_id)
        elif et == "sale":
            filters.append(Payment.sale_id == entity_id)
        elif et == "invoice":
            filters.append(Payment.invoice_id == entity_id)
        elif et == "preorder":
            filters.append(Payment.preorder_id == entity_id)
        elif et == "service":
            filters.append(Payment.service_id == entity_id)
        elif et == "expense":
            filters.append(Payment.expense_id == entity_id)
        elif et == "loan":
            filters.append(Payment.loan_settlement_id == entity_id)
        elif et == "shipment":
            filters.append(Payment.shipment_id == entity_id)
    if reference_like:
        filters.append(Payment.reference.ilike(f"%{reference_like}%"))
    if search_term:
        like_pattern = f"%{search_term}%"
        search_filters = [
            Payment.payment_number.ilike(like_pattern),
            Payment.reference.ilike(like_pattern),
            Payment.receipt_number.ilike(like_pattern),
            Payment.notes.ilike(like_pattern),
            Payment.deliverer_name.ilike(like_pattern),
            Payment.receiver_name.ilike(like_pattern),
            Payment.bank_transfer_ref.ilike(like_pattern),
            Payment.check_number.ilike(like_pattern),
            Payment.card_holder.ilike(like_pattern),
        ]
        if search_term.isdigit():
            search_filters.append(Payment.id == int(search_term))
        search_filters.extend([
            Payment.customer.has(Customer.name.ilike(like_pattern)),
            Payment.supplier.has(Supplier.name.ilike(like_pattern)),
            Payment.partner.has(Partner.name.ilike(like_pattern)),
            Payment.invoice.has(Invoice.invoice_number.ilike(like_pattern)),
            Payment.sale.has(Sale.sale_number.ilike(like_pattern)),
            Payment.service.has(ServiceRequest.service_number.ilike(like_pattern)),
        ])
        filters.append(or_(*search_filters))
    active_filter = or_(
        Payment.is_archived.is_(False),
        Payment.is_archived.is_(None),
        and_(Payment.is_archived.is_(True), Payment.archived_at.is_(None)),
    )
    base_q = (
        Payment.query.filter(active_filter)
        .filter(*filters)
        .options(
            load_only(
                Payment.id,
                Payment.payment_date,
                Payment.total_amount,
                Payment.currency,
                Payment.fx_rate_used,
                Payment.method,
                Payment.direction,
                Payment.status,
                Payment.entity_type,
                Payment.deliverer_name,
                Payment.receiver_name,
                Payment.reference,
                Payment.notes,
                Payment.payment_number,
                Payment.receipt_number,
                Payment.customer_id,
                Payment.supplier_id,
                Payment.partner_id,
                Payment.sale_id,
                Payment.invoice_id,
                Payment.service_id,
                Payment.preorder_id,
                Payment.shipment_id,
                Payment.loan_settlement_id,
            ),
            joinedload(Payment.customer),
            joinedload(Payment.supplier),
            joinedload(Payment.partner),
            joinedload(Payment.splits),
        )
    )
    
    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    
    if sort == "date":
        if order == "asc":
            ordered_query = base_q.order_by(Payment.payment_date.asc(), Payment.id.asc())
        else:
            ordered_query = base_q.order_by(Payment.payment_date.desc(), Payment.id.desc())
    elif sort == "amount":
        if order == "asc":
            ordered_query = base_q.order_by(Payment.total_amount.asc().nullslast(), Payment.id.asc())
        else:
            ordered_query = base_q.order_by(Payment.total_amount.desc().nullslast(), Payment.id.desc())
    elif sort == "entity":
        if order == "asc":
            ordered_query = base_q.order_by(Payment.entity_type.asc().nullslast(), Payment.id.asc())
        else:
            ordered_query = base_q.order_by(Payment.entity_type.desc().nullslast(), Payment.id.desc())
    elif sort == "direction":
        if order == "asc":
            ordered_query = base_q.order_by(Payment.direction.asc().nullslast(), Payment.id.asc())
        else:
            ordered_query = base_q.order_by(Payment.direction.desc().nullslast(), Payment.id.desc())
    elif sort == "method":
        if order == "asc":
            ordered_query = base_q.order_by(Payment.method.asc().nullslast(), Payment.id.asc())
        else:
            ordered_query = base_q.order_by(Payment.method.desc().nullslast(), Payment.id.desc())
    else:
        ordered_query = base_q.order_by(Payment.payment_date.desc(), Payment.id.desc())
    
    per_page = min(max(1, per_page), 500)
    
    range_start_value = None
    range_end_value = None
    target_page_value = None
    
    if print_mode:
        if print_scope == "all":
            pag = ordered_query.paginate(page=1, per_page=10000, error_out=False)
            payments_list = list(pag.items)
            row_offset = 0
        elif print_scope == "range":
            range_start_value = max(1, range_start or 1)
            range_end_value = range_end or 10000
            if range_end_value < range_start_value:
                range_end_value = range_start_value
            range_size = range_end_value - range_start_value + 1
            range_page = math.ceil(range_start_value / per_page)
            pag = ordered_query.paginate(page=range_page, per_page=range_size, error_out=False)
            payments_list = list(pag.items)
            row_offset = range_start_value - 1
        else:
            target_page_value = max(1, target_page or 1)
            pag = ordered_query.paginate(page=target_page_value, per_page=per_page, error_out=False)
            payments_list = list(pag.items)
            row_offset = (pag.page - 1) * pag.per_page if pag else 0
    else:
        pag = ordered_query.paginate(page=page, per_page=per_page, error_out=False)
        payments_list = list(pag.items)
        row_offset = (pag.page - 1) * pag.per_page if pag else 0
    
    total_filtered = pag.total if pag else 0
    total_pages = pag.pages if pag else 1
    
    for s in payments_list:
        try:
            _ = s.entity_label()
        except Exception:
            current_app.logger.debug('operation failed in payments.py', exc_info=True)
    
    # ✅ إضافة الشيكات اليدوية إلى قائمة الدفعات المعروضة
    manual_checks_for_display = []
    # إضافة الشيكات اليدوية حتى لو لم يكن هناك entity_type و entity_id (للعرض العام)
    check_filters = [Check.payment_id.is_(None)]
    
    if entity_type in ["PARTNER", "SUPPLIER", "CUSTOMER"] and entity_id:
        if entity_type == "PARTNER":
            check_filters.append(Check.partner_id == entity_id)
        elif entity_type == "SUPPLIER":
            check_filters.append(Check.supplier_id == entity_id)
        elif entity_type == "CUSTOMER":
            check_filters.append(Check.customer_id == entity_id)
    
    if sd:
        check_filters.append(Check.check_date >= datetime.combine(sd, time.min))
    if ed:
        check_filters.append(Check.check_date <= datetime.combine(ed, time.max))
    
    if status:
        st_val = status.strip().upper()
        if st_val in [s.value for s in CheckStatus]:
            check_filters.append(Check.status == st_val)
    
    if direction:
        dir_val = _dir_to_db(direction)
        if dir_val:
            check_filters.append(Check.direction == dir_val)
    
    manual_checks_q = db.session.query(Check).filter(*check_filters).order_by(Check.check_date.desc(), Check.id.desc())
    if print_mode:
        manual_checks_list = manual_checks_q.limit(10000).all()
    else:
        manual_checks_list = manual_checks_q.limit(200).all()
    
    for check in manual_checks_list:
        class MockPayment:
            def __init__(self, check_obj):
                self.id = f"check_{check_obj.id}"
                self.payment_date = check_obj.check_date
                self.total_amount = check_obj.amount
                self.currency = check_obj.currency or "ILS"
                self.method = PaymentMethod.CHEQUE.value
                self.direction = check_obj.direction
                self.status = check_obj.status
                self.entity_type = entity_type
                self.payment_number = None
                self.receipt_number = None
                self.reference = f"شيك يدوي - {check_obj.check_number or ''}"
                self.notes = check_obj.notes or "شيك يدوي"
                self.check_id = check_obj.id
                self.check_number = check_obj.check_number
                self.fx_rate_used = None
                self.fx_rate_source = None
                self.splits = []
                self.is_manual_check = True
                self._check_obj = check_obj
            
            def entity_label(self):
                check_entity_type = None
                check_entity_id = None
                if self._check_obj.customer_id:
                    check_entity_type = "CUSTOMER"
                    check_entity_id = self._check_obj.customer_id
                elif self._check_obj.supplier_id:
                    check_entity_type = "SUPPLIER"
                    check_entity_id = self._check_obj.supplier_id
                elif self._check_obj.partner_id:
                    check_entity_type = "PARTNER"
                    check_entity_id = self._check_obj.partner_id
                
                if check_entity_type == "PARTNER":
                    partner_obj = db.session.get(Partner, check_entity_id)
                    return f"شريك: {partner_obj.name if partner_obj else ''}"
                elif check_entity_type == "SUPPLIER":
                    supplier_obj = db.session.get(Supplier, check_entity_id)
                    return f"مورد: {supplier_obj.name if supplier_obj else ''}"
                elif check_entity_type == "CUSTOMER":
                    customer_obj = db.session.get(Customer, check_entity_id)
                    return f"عميل: {customer_obj.name if customer_obj else ''}"
                return "شيك يدوي"
        
        mock_payment = MockPayment(check)
        manual_checks_for_display.append(mock_payment)
    
    # ✅ إذا كانت الدفعة لديها splits، نستبدل الدفعة الرئيسية بكل splits كدفعات منفصلة
    expanded_payments = []
    for payment in payments_list:
        splits = list(getattr(payment, 'splits', []) or [])
        if splits and len(splits) > 0:
            for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                class SplitPaymentWrapper:
                    def __init__(self, parent_payment, split_obj):
                        self.parent_payment = parent_payment
                        self.split_obj = split_obj
                        self.id = f"{parent_payment.id}_split_{split_obj.id}"
                        self.payment_id = parent_payment.id
                        self.split_id = split_obj.id
                        self.payment_date = parent_payment.payment_date
                        self.total_amount = split_obj.amount or split_obj.converted_amount or Decimal(0)
                        self.currency = split_obj.currency or parent_payment.currency or "ILS"
                        self.fx_rate_used = split_obj.fx_rate_used or parent_payment.fx_rate_used
                        self.fx_rate_source = split_obj.fx_rate_source or parent_payment.fx_rate_source
                        self.method = getattr(getattr(split_obj, "method", None), "value", getattr(split_obj, "method", "")) or ""
                        self.direction = getattr(getattr(parent_payment, "direction", None), "value", getattr(parent_payment, "direction", "")) or ""
                        self.status = getattr(getattr(parent_payment, "status", None), "value", getattr(parent_payment, "status", "")) or ""
                        self.entity_type = parent_payment.entity_type
                        self.deliverer_name = parent_payment.deliverer_name
                        self.receiver_name = parent_payment.receiver_name
                        self.payment_number = parent_payment.payment_number
                        self.receipt_number = parent_payment.receipt_number
                        self.reference = parent_payment.reference
                        self.notes = parent_payment.notes
                        self.customer_id = parent_payment.customer_id
                        self.supplier_id = parent_payment.supplier_id
                        self.partner_id = parent_payment.partner_id
                        self.sale_id = parent_payment.sale_id
                        self.invoice_id = parent_payment.invoice_id
                        self.service_id = parent_payment.service_id
                        self.expense_id = parent_payment.expense_id
                        self.preorder_id = parent_payment.preorder_id
                        self.shipment_id = parent_payment.shipment_id
                        self.loan_settlement_id = parent_payment.loan_settlement_id
                        self.splits = []
                        self.is_manual_check = False
                        self.check_id = None
                        self.check_number = None

                        try:
                            details = getattr(split_obj, 'details', None) or {}
                            if isinstance(details, str):
                                import json as _json
                                try:
                                    details = _json.loads(details)
                                except Exception:
                                    details = {}
                            self.is_refunded_split = bool(details.get('refunded'))
                        except Exception:
                            self.is_refunded_split = False
                        
                        if self.method in ['cheque', 'check']:
                            check_obj = db.session.query(Check).filter(Check.payment_id == parent_payment.id).filter(
                                or_(
                                    Check.check_number == getattr(split_obj, 'check_number', None),
                                    Check.id == getattr(split_obj, 'check_id', None)
                                )
                            ).first()
                            if check_obj:
                                self.check_id = check_obj.id
                                self.check_number = check_obj.check_number
                                self.status = getattr(getattr(check_obj, "status", None), "value", getattr(check_obj, "status", "")) or self.status
                    
                    def entity_label(self):
                        return self.parent_payment.entity_label() if hasattr(self.parent_payment, 'entity_label') else (self.entity_type or "")
                    
                    @property
                    def service(self):
                        return getattr(self.parent_payment, 'service', None)
                
                split_wrapper = SplitPaymentWrapper(payment, split)
                expanded_payments.append(split_wrapper)
        else:
            expanded_payments.append(payment)
    
    payments_render = expanded_payments + manual_checks_for_display
    
    def sort_key(x):
        payment_date = datetime.min
        if hasattr(x, 'payment_date') and x.payment_date:
            if isinstance(x.payment_date, datetime):
                payment_date = x.payment_date
            elif isinstance(x.payment_date, str):
                try:
                    payment_date = datetime.strptime(x.payment_date, '%Y-%m-%d')
                except Exception:
                    payment_date = datetime.min
            elif isinstance(x.payment_date, date):
                payment_date = datetime.combine(x.payment_date, datetime.min.time())
        
        item_id = getattr(x, 'id', 0)
        if isinstance(item_id, str):
            if item_id.startswith('check_'):
                try:
                    item_id = int(item_id.replace('check_', ''))
                except Exception:
                    item_id = 0
            elif '_split_' in item_id:
                try:
                    parent_id = int(item_id.split('_split_')[0])
                    split_id = int(item_id.split('_split_')[1])
                    item_id = parent_id * 1000000 + split_id
                except Exception:
                    try:
                        item_id = int(item_id.replace('_split_', ''))
                    except Exception:
                        item_id = 0
            else:
                try:
                    item_id = int(item_id)
                except Exception:
                    item_id = 0
        
        return (payment_date, item_id)
    
    payments_render.sort(key=sort_key, reverse=True)
    query_args = request.args.to_dict()
    for key in ["page", "print", "scope", "range_start", "range_end", "page_number"]:
        query_args.pop(key, None)
    
    # حساب الملخصات بالشيكل - فلترة الدفعات غير المؤرشفة
    agg_row = db.session.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(Payment.status == PaymentStatus.COMPLETED.value, Payment.direction == PaymentDirection.IN.value),
                        case(
                            (Payment.currency == DEFAULT_CURRENCY, Payment.total_amount),
                            else_=Payment.total_amount * func.coalesce(Payment.fx_rate_used, 1)
                        ),
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("incoming_ils"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(Payment.status == PaymentStatus.COMPLETED.value, Payment.direction == PaymentDirection.OUT.value),
                        case(
                            (Payment.currency == DEFAULT_CURRENCY, Payment.total_amount),
                            else_=Payment.total_amount * func.coalesce(Payment.fx_rate_used, 1)
                        ),
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("outgoing_ils"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.currency == DEFAULT_CURRENCY, Payment.total_amount),
                    else_=Payment.total_amount * func.coalesce(Payment.fx_rate_used, 1)
                )
            ),
            0,
        ).label("grand_ils"),
    ).filter(Payment.is_archived == False).filter(*filters).first()
    
    total_incoming_ils = float(agg_row.incoming_ils or 0)
    total_outgoing_ils = float(agg_row.outgoing_ils or 0)
    grand_total_ils = float(agg_row.grand_ils or 0)
    
    # ✅ إضافة الشيكات اليدوية (بدون payment_id) للإحصائيات
    manual_checks_filters = []
    if entity_type == "PARTNER" and entity_id:
        manual_checks_filters.append(Check.partner_id == entity_id)
    elif entity_type == "SUPPLIER" and entity_id:
        manual_checks_filters.append(Check.supplier_id == entity_id)
    elif entity_type == "CUSTOMER" and entity_id:
        manual_checks_filters.append(Check.customer_id == entity_id)
    
    if manual_checks_filters:
        manual_checks_filters.append(Check.payment_id.is_(None))
        if sd:
            manual_checks_filters.append(Check.check_date >= datetime.combine(sd, time.min))
        if ed:
            manual_checks_filters.append(Check.check_date <= datetime.combine(ed, time.max))
        manual_checks_filters.append(~Check.status.in_([
            CheckStatus.RETURNED.value,
            CheckStatus.BOUNCED.value,
            CheckStatus.CANCELLED.value,
            CheckStatus.ARCHIVED.value,
        ]))
        
        checks_agg = db.session.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            Check.direction == PaymentDirection.IN.value,
                            case(
                                (Check.currency == DEFAULT_CURRENCY, Check.amount),
                                else_=Check.amount * func.coalesce(Check.fx_rate_cash, Check.fx_rate_issue, 0)
                            ),
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("incoming_ils"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Check.direction == PaymentDirection.OUT.value,
                            case(
                                (Check.currency == DEFAULT_CURRENCY, Check.amount),
                                else_=Check.amount * func.coalesce(Check.fx_rate_cash, Check.fx_rate_issue, 0)
                            ),
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("outgoing_ils"),
            func.coalesce(
                func.sum(
                    case(
                        (Check.currency == DEFAULT_CURRENCY, Check.amount),
                        else_=Check.amount * func.coalesce(Check.fx_rate_cash, Check.fx_rate_issue, 0)
                    )
                ),
                0,
            ).label("grand_ils"),
        ).filter(*manual_checks_filters).first()
        
        total_incoming_ils += float(getattr(checks_agg, "incoming_ils", 0) or 0)
        total_outgoing_ils += float(getattr(checks_agg, "outgoing_ils", 0) or 0)
        grand_total_ils += float(getattr(checks_agg, "grand_ils", 0) or 0)
    
    net_total_ils = total_incoming_ils - total_outgoing_ils
    
    rows = db.session.query(
        Payment.currency.label("ccy"),
        func.coalesce(func.sum(case((and_(Payment.direction == PaymentDirection.IN.value, Payment.status == PaymentStatus.COMPLETED.value), Payment.total_amount), else_=0)), 0).label("total_incoming"),
        func.coalesce(func.sum(case((and_(Payment.direction == PaymentDirection.OUT.value, Payment.status == PaymentStatus.COMPLETED.value), Payment.total_amount), else_=0)), 0).label("total_outgoing"),
        func.coalesce(func.sum(Payment.total_amount), 0).label("grand_total")
    ).filter(Payment.is_archived == False).filter(*filters).group_by(Payment.currency).all()
    totals_by_currency = {}
    for r in rows:
        ti = q0(D(r.total_incoming or 0))
        to = q0(D(r.total_outgoing or 0))
        gt = q0(D(r.grand_total or 0))
        totals_by_currency[r.ccy] = {
            "total_incoming": int(ti),
            "total_outgoing": int(to),
            "net_total": int(q0(ti - to)),
            "grand_total": int(gt),
            "total_paid": int(ti)
        }
    page_payments = payments_list if not print_mode else payments_for_summary
    if _wants_json():
        expanded_page_payments = []
        for payment in page_payments:
            splits = list(getattr(payment, 'splits', []) or [])
            if splits and len(splits) > 0:
                for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                    class SplitPaymentWrapper:
                        def __init__(self, parent_payment, split_obj):
                            self.parent_payment = parent_payment
                            self.split_obj = split_obj
                            self.id = f"{parent_payment.id}_split_{split_obj.id}"
                            self.payment_id = parent_payment.id
                            self.split_id = split_obj.id
                            self.payment_date = parent_payment.payment_date
                            self.total_amount = split_obj.amount or split_obj.converted_amount or Decimal(0)
                            self.currency = split_obj.currency or parent_payment.currency or "ILS"
                            self.fx_rate_used = split_obj.fx_rate_used or parent_payment.fx_rate_used
                            self.fx_rate_source = split_obj.fx_rate_source or parent_payment.fx_rate_source
                            self.method = getattr(getattr(split_obj, "method", None), "value", getattr(split_obj, "method", "")) or ""
                            self.direction = getattr(getattr(parent_payment, "direction", None), "value", getattr(parent_payment, "direction", "")) or ""
                            self.status = getattr(getattr(parent_payment, "status", None), "value", getattr(parent_payment, "status", "")) or ""
                            self.entity_type = parent_payment.entity_type
                            self.deliverer_name = parent_payment.deliverer_name
                            self.receiver_name = parent_payment.receiver_name
                            self.payment_number = parent_payment.payment_number
                            self.receipt_number = parent_payment.receipt_number
                            self.reference = parent_payment.reference
                            self.notes = parent_payment.notes
                            self.customer_id = parent_payment.customer_id
                            self.supplier_id = parent_payment.supplier_id
                            self.partner_id = parent_payment.partner_id
                            self.sale_id = parent_payment.sale_id
                            self.invoice_id = parent_payment.invoice_id
                            self.service_id = parent_payment.service_id
                            self.expense_id = parent_payment.expense_id
                            self.preorder_id = parent_payment.preorder_id
                            self.shipment_id = parent_payment.shipment_id
                            self.loan_settlement_id = parent_payment.loan_settlement_id
                            self.splits = []
                            self.is_manual_check = False

                            try:
                                details = getattr(split_obj, 'details', None) or {}
                                if isinstance(details, str):
                                    import json as _json
                                    try:
                                        details = _json.loads(details)
                                    except Exception:
                                        details = {}
                                self.is_refunded_split = bool(details.get('refunded'))
                            except Exception:
                                self.is_refunded_split = False
                            
                        def entity_label(self):
                            return self.parent_payment.entity_label() if hasattr(self.parent_payment, 'entity_label') else (self.entity_type or "")
                    
                    split_wrapper = SplitPaymentWrapper(payment, split)
                    expanded_page_payments.append(split_wrapper)
            else:
                expanded_page_payments.append(payment)
        
        page_sum = 0.0
        page_sum_ils = 0.0
        for p in expanded_page_payments:
            page_sum += float(p.total_amount or 0)
            if p.currency == 'ILS':
                page_sum_ils += float(p.total_amount or 0)
            else:
                try:
                    from models import convert_amount
                    converted = float(convert_amount(p.total_amount, p.currency, 'ILS', p.payment_date))
                    page_sum_ils += converted
                except Exception:
                    current_app.logger.debug('Currency conversion skipped')
        
        return jsonify({
            "payments": [_serialize_payment(p, full=False) for p in expanded_page_payments],
            "total_pages": total_pages if total_pages else 1,
            "current_page": page,
            "total_items": total_filtered,
            "currency": None,
            "totals_by_currency": totals_by_currency,
            "totals": {
                "total_incoming": total_incoming_ils,
                "total_outgoing": total_outgoing_ils,
                "net_total": net_total_ils,
                "grand_total": grand_total_ils,
                "page_sum": page_sum,
                "page_sum_ils": page_sum_ils,
            },
            "selected_partner": selected_partner,
            "partner_ledger": partner_ledger,
        })
    if 'query_args' not in locals():
        query_args = request.args.to_dict()
        for key in ["page", "print", "scope", "range_start", "range_end", "page_number", "ajax"]:
            query_args.pop(key, None)
    
    return render_template(
        "payments/list.html",
        payments=payments_render,
        total_paid=total_incoming_ils,
        total_incoming=total_incoming_ils,
        total_outgoing=total_outgoing_ils,
        net_total=net_total_ils,
        grand_total=grand_total_ils,
        totals_by_currency=totals_by_currency,
        selected_partner=selected_partner,
        partner_ledger=partner_ledger,
        print_mode=print_mode,
        print_scope=print_scope,
        range_start=range_start_value,
        range_end=range_end_value,
        target_page=target_page_value,
        total_filtered=total_filtered,
        total_pages=total_pages if total_pages else 1,
        per_page=per_page,
        row_offset=row_offset,
        generated_at=_utc_now_naive(),
        pdf_export=False,
        show_actions=not print_mode,
        pagination=pag,
        query_args=query_args,
        current_sort=sort,
        current_order=order,
    )

@payments_bp.route("/create", methods=["GET", "POST"], endpoint="create_payment")
@login_required
def create_payment():
    form = PaymentForm()
    # السماح بجميع الاتجاهات لجميع الجهات عدا المصاريف
    form._incoming_entities = set()
    form._outgoing_entities = {"EXPENSE"}  # المصاريف فقط صادرة
    entity_info = None
    def _fd(f):
        return getattr(f, "data", None) if f is not None else None
    if request.method == "GET":
        form.payment_date.data = _utc_now_naive()
        # ✅ تم إلغاء Request Token لتحسين UX - الاعتماد على CSRF + Idempotency فقط
        raw_et = (request.args.get("entity_type") or "").strip().upper()
        if raw_et == "SHIPMENT_CUSTOMS":
            raw_et = "SHIPMENT"
        et = raw_et if hasattr(form, "_entity_field_map") and raw_et in form._entity_field_map else ""
        raw_entity_id = (request.args.get("entity_id") or "").strip()
        eid = None
        if raw_entity_id:
            try:
                eid = int(raw_entity_id)
            except (TypeError, ValueError):
                current_app.logger.warning("payments.create_payment invalid entity_id '%s' for type %s", raw_entity_id, et or raw_et)
        pre_amount = D(request.args.get("amount"))
        if pre_amount <= 0:
            pre_amount = D(request.args.get("total_amount"))
        if pre_amount <= 0:
            pre_amount = None
        preset_direction = _norm_dir(request.args.get("direction"))
        preset_method = request.args.get("method")
        preset_currency = "ILS"
        preset_ref = (request.args.get("reference") or "").strip() or None
        preset_notes = (request.args.get("notes") or "").strip()
        if et:
            form.entity_type.data = et
            field_name = form._entity_field_map[et]
            if eid is not None and hasattr(form, field_name):
                getattr(form, field_name).data = eid
                form.entity_id.data = str(eid)
            elif raw_entity_id:
                form.entity_id.data = raw_entity_id
            if et == "CUSTOMER" and eid is not None:
                c = db.session.get(Customer, eid)
                if c:
                    balance = int(q0(getattr(c, "balance", 0) or 0))
                    entity_info = {"type": "customer", "name": c.name, "balance": balance, "currency": getattr(c, "currency", "ILS")}
                    # ملء المبلغ تلقائياً إذا كان هناك رصيد
                    if pre_amount is None and balance > 0:
                        pre_amount = balance
                    if not preset_currency:
                        form.currency.data = getattr(c, "currency", "ILS")
                    # ملء اسم العميل في search field
                    if hasattr(form, 'customer_search'):
                        form.customer_search.data = c.name
            elif et == "SUPPLIER" and eid is not None:
                s = db.session.get(Supplier, eid)
                if s:
                    balance = int(q0(s.balance_in_ils or 0))
                    entity_info = {"type": "supplier", "name": s.name, "balance": balance, "currency": getattr(s, "currency", "ILS")}
                    if pre_amount is None and balance > 0:
                        pre_amount = balance
                    if not preset_currency:
                        form.currency.data = getattr(s, "currency", "ILS")
                    if hasattr(form, 'supplier_search'):
                        form.supplier_search.data = s.name
            elif et == "PARTNER" and eid is not None:
                p = db.session.get(Partner, eid)
                if p:
                    details = _get_partner_balance_details(p)
                    balance_val = details["balance"] if details else float(p.balance_in_ils or 0)
                    balance = int(q0(balance_val))
                    currency_val = (details or {}).get("currency", getattr(p, "currency", "ILS"))
                    entity_info = {
                        "type": "partner",
                        "name": p.name,
                        "balance": balance,
                        "currency": currency_val,
                        "balance_source": (details or {}).get("balance_source")
                    }
                    if pre_amount is None and balance > 0:
                        pre_amount = balance
                    if not preset_currency:
                        form.currency.data = currency_val
                    if hasattr(form, 'partner_search'):
                        form.partner_search.data = p.name
            elif et == "SALE" and eid is not None:
                rec = db.session.get(Sale, eid)
                if rec:
                    total_i = int(q0(getattr(rec, "total_amount", getattr(rec, "total", 0)) or 0))
                    paid_i = int(q0(getattr(rec, "total_paid", 0) or 0))
                    due_i = int(q0(D(total_i) - D(paid_i)))
                    if pre_amount is None:
                        pre_amount = due_i
                    if not preset_currency:
                        form.currency.data = getattr(rec, "currency", form.currency.data)
                    person = None
                    if getattr(rec, "customer_id", None):
                        cust = db.session.get(Customer, rec.customer_id)
                        if cust:
                            person = {"type": "customer", "id": cust.id, "name": cust.name}
                    entity_info = {"type": "sale","number": rec.sale_number,"date": rec.sale_date.strftime("%Y-%m-%d") if rec.sale_date else "","total": total_i,"paid": paid_i,"balance": due_i,"currency": getattr(rec, "currency", "ILS"),"person": person}
            elif et == "INVOICE" and eid is not None:
                rec = db.session.get(Invoice, eid)
                if rec:
                    total_i = int(q0(getattr(rec, "total_amount", 0) or 0))
                    paid_i = int(q0(getattr(rec, "total_paid", 0) or 0))
                    due_i = int(q0(D(total_i) - D(paid_i)))
                    if pre_amount is None:
                        pre_amount = due_i
                    if not preset_currency:
                        form.currency.data = getattr(rec, "currency", form.currency.data)
                    person = None
                    if getattr(rec, "customer_id", None):
                        cust = db.session.get(Customer, rec.customer_id)
                        if cust:
                            person = {"type": "customer", "id": cust.id, "name": cust.name}
                    entity_info = {"type": "invoice","number": rec.invoice_number,"date": rec.invoice_date.strftime("%Y-%m-%d") if rec.invoice_date else "","total": total_i,"paid": paid_i,"balance": due_i,"currency": getattr(rec, "currency", "ILS"),"person": person}
            elif et == "SERVICE" and eid is not None:
                svc = db.session.get(ServiceRequest, eid)
                if svc:
                    try:
                        subtotal_i, tax_i, grand_i = _service_totals(svc)
                    except Exception:
                        subtotal_i = int(q0(getattr(svc, "total_cost", 0) or 0))
                        tax_i = 0
                        grand_i = subtotal_i
                    total_paid_i = int(q0(getattr(svc, "total_paid", 0) or 0))
                    due_i = int(q0(D(grand_i) - D(total_paid_i)))
                    if pre_amount is None:
                        pre_amount = due_i
                    person = None
                    if getattr(svc, "customer_id", None):
                        cust = db.session.get(Customer, svc.customer_id)
                        if cust:
                            person = {"type": "customer", "id": cust.id, "name": cust.name}
                            if hasattr(form, "customer_search"):
                                form.customer_search.data = cust.name
                            if hasattr(form, "customer_id"):
                                form.customer_id.data = str(cust.id)
                    identifier = svc.service_number or f"#{svc.id}"
                    if hasattr(form, "service_search"):
                        form.service_search.data = identifier
                    entity_info = {"type": "service","number": identifier,"date": svc.request_date.strftime("%Y-%m-%d") if getattr(svc, "request_date", None) else "","total": int(q0(grand_i)),"paid": total_paid_i,"balance": due_i,"currency": getattr(svc, "currency", "ILS") if hasattr(svc, "currency") else "ILS","person": person}
                    if not form.direction.data:
                        form.direction.data = "IN"
            elif et == "EXPENSE" and eid is not None:
                exp = db.session.get(Expense, eid)
                if exp:
                    bal = D(getattr(exp, "balance", getattr(exp, "amount", 0)) or 0)
                    if pre_amount is None:
                        pre_amount = bal
                    if not preset_currency:
                        form.currency.data = getattr(exp, "currency", form.currency.data)
                    person = None
                    if getattr(exp, "employee", None) and getattr(exp.employee, "name", None):
                        person = {"type": "employee", "id": getattr(exp.employee, "id", None), "name": exp.employee.name}
                    elif getattr(exp, "shipment", None):
                        person = {"type": "shipment", "id": getattr(exp.shipment, "id", None), "name": getattr(exp.shipment, "number", f"شحنة رقم {exp.shipment_id or ''}")}
                    elif getattr(exp, "utility_account", None):
                        ua = exp.utility_account
                        ua_name = ua.alias or ua.provider or f"Utility #{getattr(ua, 'id', '')}"
                        person = {"type": "utility", "id": getattr(ua, "id", None), "name": ua_name}
                    elif getattr(exp, "stock_adjustment", None):
                        sa = exp.stock_adjustment
                        person = {"type": "stock_adjustment", "id": getattr(sa, "id", None), "name": f"Stock Adj #{getattr(sa, 'id', '')}"}
                    else:
                        payee_name = getattr(exp, "payee_name", None) or getattr(exp, "paid_to", None) or ""
                        if payee_name:
                            person = {"type": "payee", "id": None, "name": payee_name}
                    ref_txt = (person and person.get("name")) or getattr(exp, "payee_name", None) or getattr(exp, "paid_to", None) or getattr(exp, "description", None) or f"مصروف #{exp.id}"
                    if not form.reference.data:
                        form.reference.data = f"دفع مصروف {ref_txt}"
                    entity_info = {"type": "expense","number": f"EXP-{exp.id}","date": exp.date.strftime("%Y-%m-%d") if getattr(exp, "date", None) else "","description": exp.description or "","amount": int(q0(getattr(exp, "amount", 0) or 0)),"balance": int(q0(getattr(exp, "balance", 0) or 0)),"currency": getattr(exp, "currency", "ILS"),"type_name": getattr(getattr(exp, "type", None), "name", None),"employee_name": getattr(getattr(exp, "employee", None), "name", None),"person": person}
            elif et == "SHIPMENT" and eid is not None:
                shp = db.session.get(Shipment, eid)
                if shp:
                    if hasattr(shp, "currency") and shp.currency and not preset_currency:
                        form.currency.data = shp.currency
                    if pre_amount is None:
                        amt = D(getattr(shp, "customs_due", None) or 0) or D(getattr(shp, "total_due", None) or 0) or D(getattr(shp, "balance", None) or 0) or D(getattr(shp, "total_cost", None) or 0)
                        if amt > 0:
                            pre_amount = amt
                    if not form.reference.data:
                        ref_no = getattr(shp, "shipment_number", None) or shp.id
                        form.reference.data = f"دفع شحنة {ref_no}"
                    person = None
                    supplier_id = getattr(shp, "supplier_id", None)
                    if supplier_id:
                        sup = db.session.get(Supplier, supplier_id)
                        if sup:
                            person = {"type": "supplier", "id": sup.id, "name": sup.name}
                    entity_info = {"type": "shipment","number": getattr(shp, "shipment_number", None),"date": shp.shipment_date.strftime("%Y-%m-%d") if getattr(shp, "shipment_date", None) else "","destination": getattr(shp, "destination", "") or "","currency": getattr(shp, "currency", "USD"),"person": person}
            elif et == "PREORDER" and eid is not None:
                po = db.session.get(PreOrder, eid)
                if po:
                    if not preset_currency:
                        form.currency.data = getattr(po, "currency", "ILS")
                    if pre_amount is None:
                        amt = D(getattr(po, "balance_due", None) or 0) or D(getattr(po, "prepaid_amount", None) or 0) or D(getattr(po, "deposit_amount", None) or 0)
                        if amt > 0:
                            pre_amount = amt
                    if not form.reference.data:
                        ref_no = getattr(po, "reference", None) or po.id
                        form.reference.data = f"دفعة حجز {ref_no}"
                    person = None
                    if getattr(po, "customer_id", None):
                        cust = db.session.get(Customer, po.customer_id)
                        if cust:
                            person = {"type": "customer", "id": cust.id, "name": cust.name}
                    entity_info = {"type": "preorder","number": getattr(po, "reference", None),"date": po.created_at.strftime("%Y-%m-%d") if getattr(po, "created_at", None) else "","currency": getattr(po, "currency", "ILS"),"person": person}
        if preset_currency:
            form.currency.data = ensure_currency((preset_currency or "").upper())
        if preset_method and hasattr(form, "method"):
            try:
                form.method.data = _coerce_method(preset_method).value
            except Exception:
                form.method.data = (preset_method or "").lower()
        if preset_direction:
            form.direction.data = _norm_dir(preset_direction)
        if preset_ref:
            form.reference.data = preset_ref
        if preset_notes and hasattr(form, "notes"):
            form.notes.data = preset_notes
        if pre_amount is not None and not form.total_amount.data:
            form.total_amount.data = int(q0(pre_amount))
        if not form.status.data:
            form.status.data = PaymentStatus.COMPLETED.value
    if request.method == "POST":
        # ✅ تم إلغاء Request Token validation - الاعتماد على CSRF + Idempotency فقط
        form.currency.data = "ILS"
        raw_dir = request.form.get("direction")
        if raw_dir:
            form.direction.data = _norm_dir(raw_dir)
        etype = (request.form.get("entity_type") or form.entity_type.data or "").upper()
        # المصاريف دائماً صادرة - يتم التحقق من ذلك في النموذج
        if etype == "EXPENSE":
            form.direction.data = "OUT"
        form._incoming_entities = set()
        form._outgoing_entities = {"EXPENSE"}
        if not form.validate():
            if _wants_json():
                return jsonify(status="error", errors=form.errors), 400
            return render_template("payments/form.html", form=form, entity_info=None)
        try:
            etype = (form.entity_type.data or "").upper()
            field_name = getattr(form, "_entity_field_map", {}).get(etype)
            def _parse_optional_id(raw):
                if raw is None:
                    return None
                if isinstance(raw, str):
                    raw = raw.strip()
                    if not raw:
                        return None
                    return int(raw) if raw.isdigit() else None
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None

            target_id = _parse_optional_id(getattr(form, field_name).data if field_name and hasattr(form, field_name) else None)
            if etype and field_name and not target_id and etype not in ("MISCELLANEOUS", "OTHER", "EXPENSE"):
                msg = "نوع الجهة محدد بدون رقم مرجع."
                if _wants_json():
                    return jsonify(status="error", message=msg), 400
                flash(msg, "danger")
                return render_template("payments/form.html", form=form, entity_info=None)
            target_currency = "ILS"
            split_entries = getattr(form, "splits", []).entries
            parsed_splits, sum_converted, has_split_error = _parse_split_forms(split_entries, target_currency)
            if has_split_error:
                if _wants_json():
                    return jsonify(status="error", errors=form.errors), 400
                flash("أدخل سعر الصرف للدفعات متعددة العملات.", "danger")
                return render_template("payments/form.html", form=form, entity_info=None)
            tgt_total_dec = q0(D(request.form.get("total_amount") or form.total_amount.data or 0))
            if tgt_total_dec <= 0:
                msg = "❌ المبلغ الكلي يجب أن يكون أكبر من صفر."
                if _wants_json():
                    return jsonify(status="error", message=msg), 400
                flash(msg, "danger")
                return render_template("payments/form.html", form=form, entity_info=None)
            actual_amount = sum_converted if sum_converted > 0 else tgt_total_dec
            if parsed_splits and sum_converted != tgt_total_dec:
                diff = sum_converted - tgt_total_dec
                if diff > 0:
                    flash(f"⚠️ تحذير: مجموع الدفعات بعد التحويل ({float(sum_converted):.2f}) أكبر من المطلوب ({float(tgt_total_dec):.2f}) بمقدار {float(diff):.2f}. سيُحدّث الرصيد بالمبلغ الفعلي.", "warning")
                else:
                    flash(f"⚠️ تحذير: مجموع الدفعات بعد التحويل ({float(sum_converted):.2f}) أقل من المطلوب ({float(tgt_total_dec):.2f}) بمقدار {abs(float(diff)):.2f}. سيُحدّث الرصيد بالمبلغ الفعلي.", "warning")
            direction_val = _norm_dir(form.direction.data or request.form.get("direction"))
            if etype == "EXPENSE":
                direction_val = "OUT"
            direction_db = _dir_to_db(direction_val)
            # ✅ استخراج method من الدفعات الجزئية (الأولوية) أو default
            if parsed_splits:
                method_val = parsed_splits[0].method
            else:
                # إذا ما كان في splits، نستخدم form.method أو default
                form_method = getattr(form, "method", None)
                method_val = _coerce_method(form_method.data if form_method and form_method.data else "cash").value
            notes_raw = (_fd(getattr(form, "note", None)) or _fd(getattr(form, "notes", None)) or "")
            related_customer_id = None
            related_supplier_id = None
            related_partner_id = None
            person_name = None
            if etype == "CUSTOMER":
                related_customer_id = target_id
                c = db.session.get(Customer, target_id) if target_id else None
                person_name = getattr(c, "name", None)
            elif etype == "SALE" and target_id:
                s = db.session.get(Sale, target_id)
                related_customer_id = getattr(s, "customer_id", None) if s else None
                if related_customer_id:
                    c = db.session.get(Customer, related_customer_id)
                    person_name = getattr(c, "name", None)
            elif etype == "INVOICE" and target_id:
                inv = db.session.get(Invoice, target_id)
                related_customer_id = getattr(inv, "customer_id", None) if inv else None
                if related_customer_id:
                    c = db.session.get(Customer, related_customer_id)
                    person_name = getattr(c, "name", None)
            elif etype == "SERVICE" and target_id:
                svc = db.session.get(ServiceRequest, target_id)
                related_customer_id = getattr(svc, "customer_id", None) if svc else None
                if related_customer_id:
                    c = db.session.get(Customer, related_customer_id)
                    person_name = getattr(c, "name", None)
            elif etype == "PREORDER" and target_id:
                po = db.session.get(PreOrder, target_id)
                related_customer_id = getattr(po, "customer_id", None) if po else None
                if related_customer_id:
                    c = db.session.get(Customer, related_customer_id)
                    person_name = getattr(c, "name", None)
            elif etype == "SUPPLIER":
                related_supplier_id = target_id
                s = db.session.get(Supplier, target_id) if target_id else None
                person_name = getattr(s, "name", None)
            elif etype == "PARTNER":
                related_partner_id = target_id
                p = db.session.get(Partner, target_id) if target_id else None
                person_name = getattr(p, "name", None)
            elif etype == "LOAN" and target_id:
                loan_settlement = db.session.get(SupplierLoanSettlement, target_id)
                related_supplier_id = getattr(loan_settlement, "supplier_id", None) if loan_settlement else None
                if related_supplier_id:
                    s = db.session.get(Supplier, related_supplier_id)
                    person_name = getattr(s, "name", None)
            elif etype == "EXPENSE" and target_id:
                expense = db.session.get(Expense, target_id)
                if expense:
                    related_supplier_id = getattr(expense, "supplier_id", None)
                    related_partner_id = getattr(expense, "partner_id", None)
                    related_customer_id = getattr(expense, "customer_id", None)
                    if related_supplier_id:
                        s = db.session.get(Supplier, related_supplier_id)
                        person_name = getattr(s, "name", None)
                    elif related_partner_id:
                        p = db.session.get(Partner, related_partner_id)
                        person_name = getattr(p, "name", None)
                    elif related_customer_id:
                        c = db.session.get(Customer, related_customer_id)
                        person_name = getattr(c, "name", None)
                    elif expense.payee_name:
                        person_name = expense.payee_name
            elif etype == "SHIPMENT" and target_id:
                shp = db.session.get(Shipment, target_id)
                related_supplier_id = getattr(shp, "supplier_id", None) if shp else None
                related_partner_id = getattr(shp, "partner_id", None) if shp else None
                if related_supplier_id:
                    s = db.session.get(Supplier, related_supplier_id)
                    person_name = getattr(s, "name", None)
                elif related_partner_id:
                    p = db.session.get(Partner, related_partner_id)
                    person_name = getattr(p, "name", None)
            ref_text = (form.reference.data or "").strip()
            if not ref_text and person_name:
                if direction_val == "IN":
                    ref_text = f"دفعة واردة من {person_name}"
                else:
                    ref_text = f"دفعة صادرة إلى {person_name}"
            final_customer_id = None
            final_supplier_id = None
            final_partner_id = None
            
            if etype == "CUSTOMER":
                final_customer_id = target_id
            elif etype == "SUPPLIER":
                final_supplier_id = target_id
            elif etype == "PARTNER":
                final_partner_id = target_id
            else:
                final_customer_id = related_customer_id
                final_supplier_id = related_supplier_id
                final_partner_id = related_partner_id

            if etype == "EXPENSE" and not target_id and not final_customer_id:
                fallback_customer = _parse_optional_id(getattr(form, 'customer_id').data if hasattr(form, 'customer_id') else None)
                if fallback_customer:
                    final_customer_id = fallback_customer
                    try:
                        cust_obj = db.session.get(Customer, fallback_customer)
                        if cust_obj:
                            person_name = getattr(cust_obj, 'name', person_name)
                    except Exception:
                        current_app.logger.debug('attribute access failed in payments.py', exc_info=True)
            
            deliverer_val = (form.deliverer_name.data or "").strip() if hasattr(form, "deliverer_name") else ""
            receiver_val = (form.receiver_name.data or "").strip() if hasattr(form, "receiver_name") else ""
            user_display = _resolve_user_display()
            counterparty_name = _resolve_counterparty_name(person_name=person_name, customer_id=final_customer_id, supplier_id=final_supplier_id, partner_id=final_partner_id, fallback=ref_text)
            if direction_val == "IN":
                if not deliverer_val:
                    deliverer_val = counterparty_name
                if not receiver_val:
                    receiver_val = user_display
            elif direction_val == "OUT":
                if not deliverer_val:
                    deliverer_val = user_display
                if not receiver_val:
                    receiver_val = counterparty_name
            else:
                if not deliverer_val:
                    deliverer_val = user_display
                if not receiver_val:
                    receiver_val = counterparty_name
            deliverer_val = (deliverer_val or "").strip() or None
            receiver_val = (receiver_val or "").strip() or None
            target_kwargs = {}
            if etype == "CUSTOMER":
                target_kwargs["customer_id"] = target_id
            elif etype == "SUPPLIER":
                target_kwargs["supplier_id"] = target_id
            elif etype == "PARTNER":
                target_kwargs["partner_id"] = target_id
            elif etype == "SHIPMENT":
                target_kwargs["shipment_id"] = target_id
            elif etype == "EXPENSE":
                target_kwargs["expense_id"] = target_id
            elif etype == "LOAN":
                target_kwargs["loan_settlement_id"] = target_id
            elif etype == "SALE":
                target_kwargs["sale_id"] = target_id
            elif etype == "INVOICE":
                target_kwargs["invoice_id"] = target_id
            elif etype == "PREORDER":
                target_kwargs["preorder_id"] = target_id
            elif etype == "SERVICE":
                target_kwargs["service_id"] = target_id
            else:
                if final_customer_id:
                    target_kwargs["customer_id"] = final_customer_id
                elif final_supplier_id:
                    target_kwargs["supplier_id"] = final_supplier_id
                elif final_partner_id:
                    target_kwargs["partner_id"] = final_partner_id
            payment = Payment(
                entity_type=etype,
                **target_kwargs,
                direction=direction_db,
                status=form.status.data or PaymentStatus.COMPLETED.value,
                payment_date=form.payment_date.data,
                total_amount=q0(actual_amount),  # ✅ المبلغ الفعلي المدفوع (مجموع الدفعات الجزئية)
                currency="ILS",
                method=getattr(method_val, "value", method_val),
                reference=ref_text or None,
                receipt_number=(_fd(getattr(form, "receipt_number", None)) or None),
                notes=notes_raw,
                deliverer_name=deliverer_val,
                receiver_name=receiver_val,
                created_by=getattr(current_user, "id", None),
            )
            _ensure_payment_number(payment)
            db.session.add(payment)
            db.session.flush()
            
            # ✅ ضمان وجود Split واحد على الأقل لإنشاء القيود المحاسبية
            if not parsed_splits:
                default_split = PaymentSplit(
                    payment_id=payment.id,
                    amount=payment.total_amount,
                    currency=payment.currency,
                    method=payment.method,
                    details={"auto_created": True}
                )
                db.session.add(default_split)
                parsed_splits.append(default_split)
            else:
                for sp in parsed_splits:
                    sp.payment_id = payment.id
                    db.session.add(sp)
            
            _sync_payment_method_with_splits(payment)
            db.session.add(payment)
            try:
                db.session.commit()
            except IntegrityError as ie:
                db.session.rollback()
                msg = str(ie).lower()
                fixed = False
                if "payments.payment_number" in msg or "unique constraint failed: payments.payment_number" in msg:
                    # إعادة توليد رقم الدفع باستخدام _ensure_payment_number
                    payment.payment_number = None  # إعادة تعيين
                    _ensure_payment_number(payment)
                    fixed = True
                if "payments.method" in msg or "may not be null" in msg:
                    if parsed_splits:
                        payment.method = getattr(parsed_splits[0].method, "value", str(parsed_splits[0].method))
                    else:
                        payment.method = PaymentMethod.CASH.value
                    fixed = True
                if fixed:
                    db.session.add(payment)
                    for sp in parsed_splits:
                        sp.payment_id = payment.id
                        db.session.add(sp)
                    db.session.commit()
                else:
                    raise
            try:
                if payment.sale_id:
                    sale = db.session.get(Sale, payment.sale_id)
                    if sale and hasattr(sale, "update_payment_status"):
                        old_paid = float(sale.total_paid or 0)
                        sale.update_payment_status()
                        db.session.add(sale)
                        
                        # خصم المخزون عند اكتمال الدفع (إذا كانت مؤكدة ومدفوعة)
                        preorder_already_fulfilled = False
                        try:
                            if getattr(sale, "preorder_id", None):
                                po = db.session.get(PreOrder, int(sale.preorder_id))
                                st = getattr(po, "status", None) if po else None
                                st = getattr(st, "value", st) if st is not None else None
                                preorder_already_fulfilled = str(st or "").upper() == "FULFILLED"
                        except Exception:
                            preorder_already_fulfilled = False

                        if sale.status == SaleStatus.CONFIRMED and sale.payment_status == PaymentProgress.PAID.value and old_paid < float(sale.total or 0) and not preorder_already_fulfilled:
                            from routes.sales import _deduct_stock
                            try:
                                _deduct_stock(sale)
                            except Exception as stock_err:
                                # إذا فشل الخصم، نسجل الخطأ لكن لا نمنع الدفع
                                current_app.logger.warning(f"⚠️ تحذير: فشل خصم المخزون للبيع {sale.sale_number}: {stock_err}")
                        
                        # إذا كانت المبيعة من حجز مسبق ومدفوعة بالكامل، نحدث حالة الحجز
                        if sale.preorder_id and sale.balance_due <= 0:
                            po = db.session.get(PreOrder, sale.preorder_id)
                            if po and po.status != "FULFILLED":
                                po.status = PreOrderStatus.FULFILLED.value
                                db.session.add(po)
                if payment.invoice_id:
                    inv = db.session.get(Invoice, payment.invoice_id)
                    if inv and hasattr(inv, "update_status"):
                        inv.update_status()
                        db.session.add(inv)
                if payment.status == PaymentStatus.COMPLETED.value:
                    customer_id_for_balance = None
                    try:
                        from utils.customer_balance_updater import get_customer_from_payment
                        customer_id_for_balance = get_customer_from_payment(payment)
                    except Exception:
                        customer_id_for_balance = getattr(payment, "customer_id", None)
                    if customer_id_for_balance:
                        from utils.customer_balance_updater import update_customer_balance_components
                        update_customer_balance_components(customer_id_for_balance, db.session)
                    if payment.supplier_id:
                        utils.update_entity_balance("supplier", payment.supplier_id)
                    if payment.partner_id:
                        utils.update_entity_balance("partner", payment.partner_id)
                    if payment.loan_settlement_id:
                        ls = db.session.get(SupplierLoanSettlement, payment.loan_settlement_id)
                        if ls and ls.supplier_id:
                            utils.update_entity_balance("supplier", ls.supplier_id)
                if payment.preorder_id:
                    # لا نحدث حالة الحجز عند دفع العربون
                    # فقط عند دفع المبيعة المرتبطة بالحجز (انظر payment.sale_id)
                    pass
                db.session.commit()
                try:
                    run_payment_gl_sync_after_commit(payment.id)
                except Exception:
                    current_app.logger.warning(f'Failed to sync payment GL entries: {payment.id}')
                created_checks = False
                payment_method_str = str(payment.method).upper()
                if ('CHECK' in payment_method_str or 'CHEQUE' in payment_method_str) and payment.check_number and payment.check_bank:
                    _, created = create_check_record(
                        payment=payment,
                        amount=payment.total_amount,
                        check_number=payment.check_number,
                        check_bank=payment.check_bank,
                        check_date=payment.payment_date or _utc_now_naive(),
                        check_due_date=payment.check_due_date or payment.payment_date,
                        notes=f"شيك من دفعة رقم {payment.payment_number or payment.id}"
                    )
                    created_checks = created or created_checks
                for split in payment.splits:
                    method_str = str(split.method).upper()
                    if 'CHECK' not in method_str and 'CHEQUE' not in method_str:
                        continue
                    details = split.details or {}
                    check_number = (details.get('check_number') or "").strip()
                    check_bank = (details.get('check_bank') or "").strip()
                    if not check_number or not check_bank:
                        current_app.logger.warning(f"⚠️ شيك بدون رقم أو بنك في دفعة {payment.id}")
                        continue
                    check_due_date_raw = details.get('check_due_date') or payment.check_due_date or payment.payment_date
                    _, created = create_check_record(
                        payment=payment,
                        amount=split.amount,
                        check_number=check_number,
                        check_bank=check_bank,
                        check_date=payment.payment_date or _utc_now_naive(),
                        check_due_date=check_due_date_raw,
                        notes=f"شيك من دفعة رقم {payment.payment_number or payment.id}"
                    )
                    created_checks = created or created_checks
                if created_checks:
                    try:
                        db.session.commit()
                        current_app.logger.info(f"✅ تم حفظ الشيكات من دفعة {payment.id}")
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"❌ فشل إنشاء سجل شيك من دفعة {payment.id}: {str(e)}")
                
                utils.log_audit("Payment", payment.id, "CREATE")
                
                check_token = request.form.get("check_token") or request.args.get("check_token")
                if check_token:
                    try:
                        from routes.checks import CheckActionService
                        service = CheckActionService(current_user)
                        ctx = service._resolve(check_token)
                        current_status = service._current_status(ctx)
                        if current_status not in ['CANCELLED', 'CASHED']:
                            note_text = "تم تسوية الشيك مرتجع عن طريق دفع بديل"
                            payment._skip_gl_entry = True
                            if ctx.kind in ['payment', 'payment_split'] and ctx.payment:
                                if current_status == 'PENDING':
                                    service.run(check_token, 'CANCELLED', note_text)
                                else:
                                    note_suffix = "\n[SETTLED=true] " + note_text
                                    if '[SETTLED=true]' not in (ctx.payment.notes or ''):
                                        ctx.payment.notes = (ctx.payment.notes or '') + note_suffix
                            elif ctx.kind == 'expense' and ctx.expense:
                                note_suffix = "\n[SETTLED=true] " + note_text
                                if '[SETTLED=true]' not in (ctx.expense.notes or ''):
                                    ctx.expense.notes = (ctx.expense.notes or '') + note_suffix
                            elif ctx.kind == 'manual' and ctx.manual:
                                if current_status == 'PENDING':
                                    service.run(check_token, 'CANCELLED', note_text)
                                else:
                                    note_suffix = "\n[SETTLED=true] " + note_text
                                    if '[SETTLED=true]' not in (ctx.manual.notes or ''):
                                        ctx.manual.notes = (ctx.manual.notes or '') + note_suffix
                            db.session.commit()
                            current_app.logger.info(f"✅ تم تسوية الشيك {check_token} بعد حفظ الدفعة {payment.id}")
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"⚠️ فشل تسوية الشيك {check_token} بعد حفظ الدفعة {payment.id}: {str(e)}")
            except SQLAlchemyError:
                db.session.rollback()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('payment save error')
            if _wants_json():
                return jsonify(status="error", message="حدث خطأ داخلي"), 400
            flash("❌ حدث خطأ داخلي", "danger")
            return render_template("payments/form.html", form=form, entity_info=None)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('payment save error')
            if _wants_json():
                return jsonify(status="error", message="حدث خطأ داخلي"), 400
            flash("❌ حدث خطأ داخلي", "danger")
            return render_template("payments/form.html", form=form, entity_info=None)
        if _wants_json():
            return jsonify(status="success", payment=_serialize_payment(payment, full=True)), 201
        flash("✅ تم تسجيل الدفعة", "success")
        return redirect(url_for(".index"))
    return render_template("payments/form.html", form=form, entity_info=entity_info)

@payments_bp.route("/expense/<int:exp_id>/create", methods=["GET", "POST"], endpoint="create_expense_payment")
@login_required
def create_expense_payment(exp_id):
    exp = utils._get_or_404(Expense, exp_id)
    form = PaymentForm()
    form._incoming_entities = set()
    form._outgoing_entities = {"EXPENSE"}
    form.entity_type.data = "EXPENSE"
    if hasattr(form, "_entity_field_map") and "EXPENSE" in form._entity_field_map:
        getattr(form, form._entity_field_map["EXPENSE"]).data = exp.id
    entity_info = {"type": "expense","number": f"EXP-{exp.id}","date": exp.date.strftime("%Y-%m-%d") if getattr(exp, "date", None) else "","description": exp.description or "","amount": int(q0(D(getattr(exp, "amount", 0) or 0))),"currency": getattr(exp, "currency", "ILS")}
    if request.method == "GET":
        form.payment_date.data = _utc_now_naive()
        form.total_amount.data = int(q0(D(getattr(exp, "amount", 0) or 0)))
        form.reference.data = f"دفع مصروف {exp.description or ''}".strip()
        form.direction.data = "OUT"
        form.currency.data = "ILS"
        if not form.status.data:
            form.status.data = PaymentStatus.COMPLETED.value
        return render_template("payments/form.html", form=form, entity_info=entity_info)
    raw_dir = request.form.get("direction")
    if raw_dir:
        form.direction.data = _norm_dir(raw_dir)
    form.direction.data = "OUT"
    form.currency.data = "ILS"
    if not form.validate_on_submit():
        if _wants_json():
            return jsonify(status="error", errors=form.errors), 400
        return render_template("payments/form.html", form=form, entity_info=entity_info)
    try:
        target_currency = "ILS"
        split_entries = getattr(form, "splits", []).entries
        parsed_splits, sum_converted, has_split_error = _parse_split_forms(split_entries, target_currency)
        if has_split_error:
            if _wants_json():
                return jsonify(status="error", errors=form.errors), 400
            flash("أدخل سعر الصرف للدفعات متعددة العملات.", "danger")
            return render_template("payments/form.html", form=form, entity_info=entity_info)
        tgt_total_dec = q0(D(request.form.get("total_amount") or form.total_amount.data or 0))
        if tgt_total_dec <= 0:
            msg = "❌ المبلغ الكلي يجب أن يكون أكبر من صفر."
            if _wants_json():
                return jsonify(status="error", message=msg), 400
            flash(msg, "danger")
            return render_template("payments/form.html", form=form, entity_info=entity_info)
        actual_amount_expense = sum_converted if sum_converted > 0 else tgt_total_dec
        if parsed_splits and sum_converted != tgt_total_dec:
            diff = sum_converted - tgt_total_dec
            if diff > 0:
                flash(f"⚠️ تحذير: مجموع الدفعات بعد التحويل ({float(sum_converted):.2f}) أكبر من المطلوب ({float(tgt_total_dec):.2f}) بمقدار {float(diff):.2f}. سيُحدّث الرصيد بالمبلغ الفعلي.", "warning")
            else:
                flash(f"⚠️ تحذير: مجموع الدفعات بعد التحويل ({float(sum_converted):.2f}) أقل من المطلوب ({float(tgt_total_dec):.2f}) بمقدار {abs(float(diff)):.2f}. سيُحدّث الرصيد بالمبلغ الفعلي.", "warning")
        method_val = parsed_splits[0].method if parsed_splits else _coerce_method(getattr(form, "method", None).data or "cash").value
        notes_raw = (getattr(form, "note", None).data if hasattr(form, "note") else None) or (getattr(form, "notes", None).data if hasattr(form, "notes") else None) or ""
        deliverer_val = (form.deliverer_name.data or "").strip() if hasattr(form, "deliverer_name") else ""
        receiver_val = (form.receiver_name.data or "").strip() if hasattr(form, "receiver_name") else ""
        user_display = _resolve_user_display()
        payee = exp.payee_name or exp.paid_to or exp.beneficiary_name or (getattr(exp.employee, "name", None) if getattr(exp, "employee", None) else None) or "غير محدد"
        counterparty_name = _resolve_counterparty_name(person_name=payee, supplier_id=getattr(exp, "supplier_id", None), partner_id=getattr(exp, "partner_id", None), customer_id=getattr(exp, "customer_id", None), fallback=payee)
        if not deliverer_val:
            deliverer_val = user_display
        if not receiver_val:
            receiver_val = counterparty_name
        deliverer_val = (deliverer_val or "").strip() or None
        receiver_val = (receiver_val or "").strip() or None
        payment = Payment(
            entity_type="EXPENSE",
            expense_id=exp.id,
            supplier_id=getattr(exp, "supplier_id", None),
            partner_id=getattr(exp, "partner_id", None),
            customer_id=getattr(exp, "customer_id", None),
            total_amount=q0(actual_amount_expense),
            currency="ILS",
            method=getattr(method_val, "value", method_val),
            direction=_dir_to_db("OUT"),
            status=form.status.data or PaymentStatus.COMPLETED.value,
            payment_date=form.payment_date.data or _utc_now_naive(),
            reference=(form.reference.data or "").strip() or None,
            notes=(notes_raw or "").strip() or None,
            deliverer_name=deliverer_val,
            receiver_name=receiver_val,
            created_by=getattr(current_user, "id", None),
        )
        _ensure_payment_number(payment)
        
        # ✅ ضمان وجود Split واحد على الأقل لإنشاء القيود المحاسبية
        if not parsed_splits:
            default_split = PaymentSplit(
                payment=payment,
                amount=payment.total_amount,
                currency=payment.currency,
                method=payment.method,
                details={"auto_created": True}
            )
            db.session.add(default_split)
            # لا حاجة لإضافة default_split لـ parsed_splits هنا لأنه لن يُستخدم لاحقاً في هذه الدالة
        else:
            for sp in parsed_splits:
                payment.splits.append(sp)
                
        db.session.add(payment)
        db.session.commit()
        try:
            run_payment_gl_sync_after_commit(payment.id)
        except Exception:
            current_app.logger.warning(f'Failed to sync payment GL entries: {payment.id}')
        # تحديث الأرصدة بشكل فوري
        try:
            if payment.supplier_id:
                utils.update_entity_balance("SUPPLIER", payment.supplier_id)
            if payment.partner_id:
                utils.update_entity_balance("PARTNER", payment.partner_id)
            if payment.customer_id:
                utils.update_entity_balance("CUSTOMER", payment.customer_id)
        except Exception as e:
            current_app.logger.error(f"❌ فشل تحديث الأرصدة بعد دفع المصروف {payment.id}: {e}")

        utils.log_audit("Payment", payment.id, f"CREATE (expense #{exp.id})")
        if _wants_json():
            return jsonify(status="success", payment=_serialize_payment(payment, full=True)), 201
        flash("✅ تم تسجيل دفع المصروف بنجاح", "success")
        return redirect(url_for(".index"))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('expense payment error')
        if _wants_json():
            return jsonify(status="error", message="حدث خطأ داخلي"), 400
        flash("❌ حدث خطأ داخلي", "danger")
        return render_template("payments/form.html", form=form, entity_info=entity_info)

@payments_bp.route("/split/<int:split_id>/delete", methods=["DELETE"], endpoint="delete_split")
@login_required
def delete_split(split_id):
    split = utils._get_or_404(PaymentSplit, split_id)
    try:
        payment_id = split.payment_id
        pmt = db.session.get(Payment, payment_id)
        if pmt and (pmt.status == PaymentStatus.COMPLETED.value or str(getattr(pmt.status, "value", pmt.status)) == "COMPLETED"):
            return jsonify(status="error", message="لا يمكن تعديل دفعات سند مكتمل."), 409
        db.session.delete(split)
        db.session.flush()
        if payment_id:
            if pmt is None:
                pmt = db.session.get(Payment, payment_id)
            if pmt is not None:
                _sync_payment_method_with_splits(pmt)
                rem = list(pmt.splits or [])
                pmt.total_amount = _sum_splits_decimal(rem) if rem else q0(0)
                db.session.add(pmt)
        db.session.commit()
        try:
            customer_id = getattr(pmt, "customer_id", None) if pmt else None
            supplier_id = getattr(pmt, "supplier_id", None) if pmt else None
            partner_id = getattr(pmt, "partner_id", None) if pmt else None
            if pmt and getattr(pmt, "expense_id", None) and not (customer_id or supplier_id or partner_id):
                exp = db.session.get(Expense, int(pmt.expense_id))
                if exp:
                    customer_id = getattr(exp, "customer_id", None)
                    supplier_id = getattr(exp, "supplier_id", None)
                    partner_id = getattr(exp, "partner_id", None)
            if customer_id:
                utils.update_entity_balance("CUSTOMER", customer_id)
            if supplier_id:
                utils.update_entity_balance("SUPPLIER", supplier_id)
            if partner_id:
                utils.update_entity_balance("PARTNER", partner_id)
        except Exception as e:
            current_app.logger.error(f"❌ فشل تحديث الأرصدة بعد حذف جزء دفعة {split_id}: {e}")
        current_app.logger.info("payment.split_deleted", extra={"event": "payments.split.delete", "payment_id": payment_id, "split_id": split_id})
        return jsonify(status="success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("payment.split_delete_failed", extra={"event": "payments.split.error", "split_id": split_id})
        return jsonify(status="error", message="حدث خطأ داخلي"), 400

@payments_bp.route("/<string:payment_id>", methods=["GET"], endpoint="view_payment")
@login_required
def view_payment(payment_id: str):
    """عرض تفاصيل الدفعة"""
    # معالجة المعرفات المركبة (مثل 309_split_233)
    real_id = payment_id
    split_id = None
    
    if isinstance(payment_id, str) and '_split_' in payment_id:
        try:
            parts = payment_id.split('_split_')
            real_id = int(parts[0])
            split_id = int(parts[1])
        except (ValueError, IndexError):
            current_app.logger.warning('payment processing failed silently in payments.py', exc_info=True)
    
    try:
        real_id = int(real_id)
    except (ValueError, TypeError):
        if _wants_json():
            return jsonify(error="invalid_id", message="معرف السند غير صالح"), 400
        flash("معرف السند غير صالح", "error")
        return redirect(url_for("payments.index"))

    payment = _safe_get_payment(real_id, all_rels=True)
    if not payment:
        if _wants_json():
            return jsonify(error="not_found", message="السند غير موجود"), 404
        flash("السند غير موجود", "error")
        return redirect(url_for("payments.index"))
    
    # إذا كان المطلوب جزء معين من الدفعة، نقوم بتجهيزه للعرض
    display_payment = payment
    if split_id:
        # البحث عن الجزء المطلوب
        target_split = None
        for split in payment.splits:
            if split.id == split_id:
                target_split = split
                break
        
        if target_split:
            # إنشاء كائن مؤقت للعرض يمثل الجزء
            # نحتاج لاستيراد SplitPaymentWrapper إذا لم يكن متاحاً في النطاق
            # لكن للتبسيط سنقوم بتمرير الدفعة الأصلية مع تحديد الجزء المطلوب في القالب
            pass

    if _wants_json():
        return jsonify(payment=_serialize_payment(payment, full=True))
    
    return render_template("payments/view.html", payment=payment, highlight_split_id=split_id)

@payments_bp.route("/<int:payment_id>/status", methods=["POST"], endpoint="update_payment_status")
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def update_payment_status(payment_id: int):
    """تحديث حالة الدفعة"""
    payment = _safe_get_payment(payment_id, all_rels=True)
    if not payment:
        return jsonify(error="not_found", message="السند غير موجود"), 404
    
    # الحصول على الحالة الجديدة من JSON أو form data
    if request.is_json:
        new_status = request.json.get("status")
    else:
        new_status = request.form.get("status")
    
    if not new_status:
        return jsonify(error="missing_status", message="يجب تحديد الحالة الجديدة"), 400

    new_status = str(new_status).strip().upper()
    
    # التحقق من صحة الحالة الجديدة
    valid_statuses = ["COMPLETED", "PENDING", "FAILED", "REFUNDED", "CANCELLED"]
    if new_status not in valid_statuses:
        return jsonify(error="invalid_status", message="حالة غير صحيحة"), 400
    
    # التحقق من الانتقال المنطقي بين الحالات
    current_status = str(getattr(payment.status, 'value', payment.status) or '').upper()
    allowed_transitions = {
        "PENDING":   {"COMPLETED", "FAILED", "CANCELLED"},
        "COMPLETED": {"REFUNDED", "CANCELLED"},
        "FAILED":    {"PENDING"},
        "REFUNDED":  set(),
        "CANCELLED": set(),
    }
    allowed = allowed_transitions.get(current_status, set())
    if new_status not in allowed:
        return jsonify(
            error="invalid_transition",
            message=f"لا يمكن الانتقال من {current_status} إلى {new_status}"
        ), 400
    
    try:
        if new_status == "REFUNDED":
            return refund_payment(payment_id)
        
        old_status = current_status
        payment.status = new_status
        db.session.flush()
        
        # تحديث الأرصدة عند تغيير الحالة من/إلى COMPLETED
        if old_status == "COMPLETED" and new_status == "CANCELLED":
            if payment.sale_id:
                sale = db.session.get(Sale, payment.sale_id)
                if sale and hasattr(sale, "update_payment_status"):
                    sale.update_payment_status()
                    db.session.add(sale)
            if payment.customer_id:
                try:
                    from utils.customer_balance_updater import update_customer_balance_components
                    update_customer_balance_components(payment.customer_id, db.session)
                except Exception as bal_err:
                    import logging
                    logging.getLogger(__name__).warning(f"فشل تحديث رصيد العميل {payment.customer_id}: {bal_err}")
            if payment.supplier_id:
                utils.update_entity_balance("supplier", payment.supplier_id)
            if payment.partner_id:
                utils.update_entity_balance("partner", payment.partner_id)
        elif old_status == "PENDING" and new_status == "COMPLETED":
            if payment.sale_id:
                sale = db.session.get(Sale, payment.sale_id)
                if sale and hasattr(sale, "update_payment_status"):
                    sale.update_payment_status()
                    db.session.add(sale)
            if payment.customer_id:
                try:
                    from utils.customer_balance_updater import update_customer_balance_components
                    update_customer_balance_components(payment.customer_id, db.session)
                except Exception as bal_err:
                    import logging
                    logging.getLogger(__name__).warning(f"فشل تحديث رصيد العميل {payment.customer_id}: {bal_err}")
            if payment.supplier_id:
                utils.update_entity_balance("supplier", payment.supplier_id)
            if payment.partner_id:
                utils.update_entity_balance("partner", payment.partner_id)
        
        db.session.commit()
        try:
            run_payment_gl_sync_after_commit(payment.id)
        except Exception:
            current_app.logger.warning(f'Failed to sync payment GL entries: {payment.id}')
        return jsonify(success=True, message="تم تحديث حالة الدفعة بنجاح", status=new_status)
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('payment status update error')
        return jsonify(error="update_failed", message="حدث خطأ داخلي"), 500


@payments_bp.route("/<string:payment_id>/receipt", methods=["GET"], endpoint="payment_receipt")
@login_required
def view_receipt(payment_id: str):
    # معالجة المعرفات المركبة (مثل 309_split_233)
    real_id = payment_id
    split_id = None
    
    if isinstance(payment_id, str) and '_split_' in payment_id:
        try:
            parts = payment_id.split('_split_')
            real_id = int(parts[0])
            split_id = int(parts[1])
        except (ValueError, IndexError):
            current_app.logger.warning('payment processing failed silently in payments.py', exc_info=True)
    
    try:
        real_id = int(real_id)
    except (ValueError, TypeError):
        return _ok_not_found("رقم السند غير صالح")

    payment = _safe_get_payment(real_id, all_rels=True)
    if not payment:
        return _ok_not_found()
    
    # إذا كان هناك جزء محدد، نحاول تجهيز بيانات الإيصال له
    display_payment = payment
    if split_id:
        target_split = next((s for s in payment.splits if s.id == split_id), None)
        if target_split:
            # هنا يمكننا إنشاء كائن مؤقت يحمل بيانات الجزء فقط للطباعة
            # لكن حالياً سنطبع الدفعة الأصلية مع تمرير split_id للقالب لتمييزه
            pass

    sale_info = _sale_info_dict(payment.sale) if getattr(payment, "sale_id", None) else None
    if _wants_json():
        payload = _serialize_payment_min(payment)
        payload["sale_info"] = sale_info
        return jsonify(payment=payload)
    
    # التحقق من نوع القالب (بسيط أو ملون)
    use_simple = request.args.get('simple', '').strip().lower() in ('1', 'true', 'yes')
    template_name = "payments/receipt_simple.html" if use_simple else "payments/receipt.html"
    
    return render_template(template_name, payment=payment, now=_utc_now_naive(), sale_info=sale_info, split_id=split_id)

@payments_bp.route("/<string:payment_id>/receipt/download", methods=["GET"], endpoint="download_receipt")
@login_required
def download_receipt(payment_id: str):
    # معالجة المعرفات المركبة (مثل 309_split_233)
    real_id = payment_id
    if isinstance(payment_id, str) and '_split_' in payment_id:
        try:
            real_id = int(payment_id.split('_split_')[0])
        except (ValueError, IndexError):
            current_app.logger.warning('payment processing failed silently in payments.py', exc_info=True)
    
    try:
        real_id = int(real_id)
    except (ValueError, TypeError):
        return _ok_not_found("رقم السند غير صالح")

    payment = _safe_get_payment(real_id, all_rels=False)
    if not payment:
        return _ok_not_found("السند غير موجود للتنزيل")
    try:
        pdf_bytes = _render_payment_receipt_pdf(payment)
        if not pdf_bytes:
            if _wants_json():
                return jsonify(error="render_error", message="تنزيل PDF غير متاح على هذا الخادم. استخدم صفحة الإيصال وطباعة المتصفح."), 503
            flash("تنزيل PDF غير متاح على هذا الخادم (يتطلب تثبيت مكتبات الطباعة). يمكنك طباعة الإيصال من صفحة العرض باستخدام طباعة المتصفح (Ctrl+P).", "info")
            return redirect(url_for("payments.payment_receipt", payment_id=payment.id))
    except Exception as e:
        current_app.logger.exception("receipt.pdf_error", extra={"payment_id": payment_id})
        if _wants_json():
            return jsonify(error="exception", message="حدث خطأ داخلي"), 500
        return make_response("<!doctype html><meta charset='utf-8'><div style='padding:24px;font-family:system-ui,Arial,sans-serif'>حصل خطأ أثناء توليد PDF</div>", 500)
    safe_suffix = (getattr(payment, "receipt_number", "") or "").strip() or (getattr(payment, "payment_number", "") or "").strip() or f"{payment_id}_{_utc_now_naive():%Y%m%d}"
    safe_suffix = _safe_filename_component(safe_suffix)
    filename = f"payment_receipt_{safe_suffix or payment_id}.pdf"
    inline = (request.args.get("inline") or "").strip().lower() in ("1", "true", "yes")
    buf = BytesIO(pdf_bytes)
    buf.seek(0)
    resp = send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=not inline,
        download_name=filename,
        max_age=0,
        conditional=False,
        etag=False,
        last_modified=None,
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Content-Disposition"] = ("inline" if inline else "attachment") + f'; filename="{filename}"'
    return resp

@payments_bp.route("/entity-fields", methods=["GET"], endpoint="entity_fields")
@login_required
def entity_fields():
    """جلب حقول الجهة المرتبطة بالدفعة"""
    entity_type = (request.args.get("type") or "customer").strip().lower()
    entity_id = request.args.get("entity_id")
    form = PaymentForm()
    # السماح بجميع الاتجاهات لجميع الجهات عدا المصاريف
    form._incoming_entities = set()
    form._outgoing_entities = {"EXPENSE"}  # المصاريف فقط صادرة
    form.entity_type.data = entity_type.upper()
    model_map = {
        "customer": (Customer, "customer_id"),
        "supplier": (Supplier, "supplier_id"),
        "partner": (Partner, "partner_id"),
        "sale": (Sale, "sale_id"),
        "invoice": (Invoice, "invoice_id"),
        "service": (ServiceRequest, "service_id"),
        "shipment": (Shipment, "shipment_id"),
        "expense": (Expense, "expense_id"),
        "preorder": (PreOrder, "preorder_id"),
        "loan": (SupplierLoanSettlement, "loan_settlement_id")
    }
    if entity_id:
        try:
            eid = int(entity_id)
            model, field_name = model_map.get(entity_type, (None, None))
            if model is not None and db.session.get(model, eid):
                getattr(form, field_name).data = eid
        except (ValueError, TypeError):
            if _wants_json():
                return jsonify(status="error", message="رقم الجهة غير صالح"), 400
    if hasattr(form, "_sync_entity_id_for_render"):
        form._sync_entity_id_for_render()
    return render_template("payments/_entity_fields.html", form=form)

def _ensure_payment_number(pmt: Payment) -> None:
    if getattr(pmt, "payment_number", None):
        return
    base_dt = getattr(pmt, "payment_date", None) or _utc_now_naive()
    prefix = base_dt.strftime("PMT%Y%m%d")
    
    # استخدام MAX بدلاً من COUNT لتجنب التكرار
    result = db.session.execute(
        sa_text("SELECT payment_number FROM payments WHERE payment_number LIKE :pfx ORDER BY payment_number DESC LIMIT 1"), 
        {"pfx": f"{prefix}-%"}
    ).scalar()
    
    if result:
        try:
            last_num = int(result.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    # محاولة إيجاد رقم فريد
    for attempt in range(100):
        candidate = f"{prefix}-{next_num:04d}"
        exists = db.session.execute(
            sa_text("SELECT 1 FROM payments WHERE payment_number = :num LIMIT 1"),
            {"num": candidate}
        ).scalar()
        if not exists:
            pmt.payment_number = candidate
            return
        next_num += 1
    
    # fallback: استخدام timestamp
    import time
    pmt.payment_number = f"{prefix}-{int(time.time() * 1000) % 10000:04d}"

def _sum_splits_decimal(splits=None, parsed_splits=None) -> Decimal:
    seq = parsed_splits if parsed_splits is not None else splits
    total = Decimal("0")
    for s in (seq or []):
        total += q0(getattr(s, "amount", 0))
    return q0(total)

def _parse_split_forms(split_entries, target_currency: str):
    parsed = []
    total_converted = Decimal("0")
    has_error = False
    target_currency = ensure_currency(target_currency or "ILS")
    fx_precision = Decimal("0.000001")
    for entry in (split_entries or []):
        split_form = entry.form
        amt_dec = q0(getattr(split_form, "amount").data or 0)
        if amt_dec <= 0:
            continue
        method_raw = getattr(split_form, "method").data or ""
        method_value = str(method_raw).strip().lower()
        details = {}
        for fld in ("check_number", "check_bank", "check_due_date", "card_number", "card_holder", "card_expiry", "bank_transfer_ref", "online_gateway", "online_ref"):
            if hasattr(split_form, fld):
                val = getattr(split_form, fld).data
                if val in (None, "", []):
                    continue
                if fld == "check_due_date" and isinstance(val, (datetime, date)):
                    details[fld] = val.isoformat()
                elif fld == "card_number":
                    num = "".join(ch for ch in str(val) if ch.isdigit())
                    if num:
                        details["card_last4"] = num[-4:]
                else:
                    details[fld] = val
        details = _clean_details(details)
        split_currency = ensure_currency(getattr(split_form, "currency").data or target_currency)
        fx_rate_value = getattr(split_form, "fx_rate").data
        rate_used = Decimal("1")
        rate_source = "same"
        converted_amount = q0(amt_dec)
        if split_currency != target_currency:
            if fx_rate_value:
                rate_used = Decimal(str(fx_rate_value)).quantize(fx_precision, rounding=ROUND_HALF_UP)
                if rate_used <= 0:
                    split_form.fx_rate.errors.append("أدخل سعر صرف أكبر من صفر.")
                    has_error = True
                    continue
                rate_source = "manual"
            else:
                try:
                    rate_info = get_fx_rate_with_fallback(split_currency, target_currency)
                except Exception:
                    rate_info = {"success": False, "rate": 0}
                rate_val = Decimal(str(rate_info.get("rate", 0) or 0))
                if rate_val <= 0 or not rate_info.get("success"):
                    split_form.fx_rate.errors.append(f"لا يوجد سعر صرف بين {split_currency} و {target_currency}. أدخل السعر يدوياً.")
                    has_error = True
                    continue
                rate_used = rate_val.quantize(fx_precision, rounding=ROUND_HALF_UP)
                rate_source = rate_info.get("source") or "auto"
            converted_amount = q0(amt_dec * rate_used)
        parsed.append(
            PaymentSplit(
                method=_coerce_method(method_value).value,
                amount=amt_dec,
                details=details,
                currency=split_currency,
                converted_amount=converted_amount,
                converted_currency=target_currency,
                fx_rate_used=rate_used,
                fx_rate_source=rate_source,
                fx_rate_timestamp=_utc_now_naive(),
                fx_base_currency=split_currency,
                fx_quote_currency=target_currency,
            )
        )
        total_converted += converted_amount
    return parsed, q0(total_converted), has_error


def _get_partner_balance_details(partner: Partner | None) -> dict | None:
    """احسب رصيد الشريك الحالي من current_balance"""
    if not partner:
        return None
    balance = float(partner.current_balance or 0)
    return {
        "id": partner.id,
        "name": partner.name,
        "balance": balance,
        "currency": partner.currency or "ILS",
    }




@payments_bp.route("/api/fx-rate", methods=["GET"], endpoint="fx_rate_lookup")
@login_required
def fx_rate_lookup():
    base = ensure_currency(request.args.get("base") or "ILS")
    quote = ensure_currency(request.args.get("quote") or "ILS")
    if base == quote:
        return jsonify(success=True, rate=1.0, source="same", base=base, quote=quote)
    try:
        rate_info = get_fx_rate_with_fallback(base, quote)
    except Exception as e:
        current_app.logger.exception('fx rate lookup error')
        return jsonify(success=False, rate=0, base=base, quote=quote, message="حدث خطأ داخلي"), 500
    rate = float(rate_info.get("rate", 0) or 0)
    success_flag = bool(rate_info.get("success"))
    source = rate_info.get("source")
    if rate <= 0 or not success_flag:
        try:
            inverse_info = get_fx_rate_with_fallback(quote, base)
        except Exception:
            inverse_info = None
        inv_rate = float(inverse_info.get("rate", 0) or 0) if inverse_info else 0
        inv_success = bool(inverse_info.get("success")) if inverse_info else False
        if inv_rate > 0 and inv_success:
            rate = 1.0 / inv_rate
            success_flag = True
            source = (inverse_info.get("source") or "") + "_inverse"
        else:
            return jsonify(success=False, rate=0, base=base, quote=quote, message="سعر الصرف غير متوفر"), 404
    return jsonify(
        success=success_flag,
        rate=rate,
        source=source,
        base=base,
        quote=quote,
    )


@payments_bp.route("/api/entities/<entity_type>", methods=["GET"], endpoint="get_entities")
@login_required
def get_entities(entity_type):
    """API للحصول على الجهات حسب النوع مع فلترة ذكية"""
    search = request.args.get("search", "").strip()
    limit = utils._query_limit(20, 100)
    
    try:
        if entity_type == "CUSTOMER":
            query = Customer.query.filter_by(is_active=True).options(
                load_only(Customer.id, Customer.name, Customer.phone, Customer.email)
            )
            if search:
                query = query.filter(
                    or_(
                        Customer.name.ilike(f"%{search}%"),
                        func.coalesce(Customer.phone, '').ilike(f"%{search}%"),
                        func.coalesce(Customer.email, '').ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Customer.name).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": c.id,
                    "name": utils.entity_name(c),
                    "phone": utils.entity_phone(c),
                    "email": utils.entity_email(c),
                    "display": utils.entity_display(c),
                    "balance": float(getattr(c, "current_balance", None) or getattr(c, "balance", 0) or 0)
                } for c in entities]
            })
            
        elif entity_type == "SUPPLIER":
            query = Supplier.query.filter_by(is_archived=False).options(
                load_only(Supplier.id, Supplier.name, Supplier.phone, Supplier.email)
            )
            if search:
                query = query.filter(
                    or_(
                        Supplier.name.ilike(f"%{search}%"),
                        func.coalesce(Supplier.phone, '').ilike(f"%{search}%"),
                        func.coalesce(Supplier.email, '').ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Supplier.name).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": s.id,
                    "name": utils.entity_name(s),
                    "phone": utils.entity_phone(s),
                    "email": utils.entity_email(s),
                    "display": utils.entity_display(s),
                    "balance": float(s.balance or 0)
                } for s in entities]
            })
            
        elif entity_type == "PARTNER":
            query = Partner.query.filter_by(is_archived=False).options(
                load_only(Partner.id, Partner.name, Partner.phone_number, Partner.email)
            )
            if search:
                query = query.filter(
                    or_(
                        Partner.name.ilike(f"%{search}%"),
                        func.coalesce(Partner.phone_number, '').ilike(f"%{search}%"),
                        func.coalesce(Partner.email, '').ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Partner.name).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": p.id,
                    "name": utils.entity_name(p),
                    "phone": utils.entity_phone(p),
                    "email": utils.entity_email(p),
                    "display": utils.entity_display(p),
                    "balance": float(p.balance or 0)
                } for p in entities]
            })
            
        elif entity_type == "SALE":
            query = Sale.query.filter_by(status="CONFIRMED").options(
                joinedload(Sale.customer).load_only(Customer.id, Customer.name),
                load_only(Sale.id, Sale.sale_number, Sale.sale_date, Sale.total_amount, Sale.currency)
            )
            if search:
                query = query.join(Customer).filter(
                    or_(
                        Sale.sale_number.ilike(f"%{search}%"),
                        Customer.name.ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Sale.sale_date.desc()).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": s.id,
                    "sale_number": s.sale_number,
                    "customer_name": s.customer.name if s.customer else "غير محدد",
                    "total_amount": float(s.total_amount or 0),
                    "display": f"{s.sale_number} - {s.customer.name if s.customer else 'غير محدد'}"
                } for s in entities]
            })
            
        elif entity_type == "INVOICE":
            from sqlalchemy import and_
            query = Invoice.query.filter(
                and_(
                    Invoice.total_paid == 0,
                    Invoice.cancelled_at.is_(None)
                )
            ).options(
                joinedload(Invoice.customer).load_only(Customer.id, Customer.name),
                load_only(Invoice.id, Invoice.invoice_number, Invoice.invoice_date, Invoice.total_amount, Invoice.currency, Invoice.total_paid, Invoice.cancelled_at)
            )
            if search:
                query = query.join(Customer).filter(
                    or_(
                        Invoice.invoice_number.ilike(f"%{search}%"),
                        Customer.name.ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Invoice.invoice_date.desc()).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": i.id,
                    "invoice_number": i.invoice_number,
                    "customer_name": i.customer.name if i.customer else "غير محدد",
                    "total_amount": float(i.total_amount or 0),
                    "display": f"{i.invoice_number} - {i.customer.name if i.customer else 'غير محدد'}"
                } for i in entities]
            })
        
        elif entity_type == "EXPENSE":
            query = Expense.query
            if search:
                query = query.filter(
                    or_(
                        Expense.description.ilike(f"%{search}%"),
                        func.coalesce(Expense.tax_invoice_number, '').ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(Expense.date.desc()).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": e.id,
                    "name": e.description or f"مصروف #{e.id}",
                    "reference": e.tax_invoice_number,
                    "amount": float(e.amount or 0),
                    "display": f"{e.description or 'مصروف'} - {e.tax_invoice_number}" if e.tax_invoice_number else (e.description or f"مصروف #{e.id}")
                } for e in entities]
            })
        
        elif entity_type == "EXPENSE_TYPE":
            query = ExpenseType.query.filter_by(is_active=True)
            if search:
                query = query.filter(
                    or_(
                        ExpenseType.name.ilike(f"%{search}%"),
                        func.coalesce(ExpenseType.code, '').ilike(f"%{search}%")
                    )
                )
            entities = query.order_by(ExpenseType.name).limit(limit).all()
            return jsonify({
                "success": True,
                "results": [{
                    "id": et.id,
                    "name": et.name,
                    "code": et.code,
                    "display": f"{et.name} ({et.code})" if et.code else et.name
                } for et in entities]
            })
            
        else:
            return jsonify({"success": False, "results": [], "message": "نوع جهة غير مدعوم"})
            
    except Exception as e:
        try:
            current_app.logger.exception("get_entities error")
        except Exception:
            pass
        current_app.logger.exception('API error')
        return jsonify({"results": [], "error": "حدث خطأ داخلي"}), 500


@payments_bp.route("/api/related-party", methods=["GET"], endpoint="get_related_party")
@login_required
def get_related_party():
    """API لجلب الجهة المرتبطة (العميل أو المورد) بناءً على الكيان"""
    entity_type = request.args.get("entity_type", "").strip().upper()
    entity_id = request.args.get("entity_id", "").strip()
    
    if not entity_type or not entity_id:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
    
    try:
        entity_id = int(entity_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid entity_id"}), 400
    
    try:
        result = {"success": True}
        
        if entity_type == "SALE":
            sale = db.session.get(Sale, entity_id)
            if sale and sale.customer_id:
                customer = db.session.get(Customer, sale.customer_id)
                if customer:
                    result["customer_id"] = customer.id
                    result["customer_name"] = customer.name
                    
                    # البحث عن المورد المرتبط بالعميل
                    supplier = db.session.query(Supplier).filter_by(customer_id=customer.id).first()
                    if supplier:
                        result["supplier_id"] = supplier.id
                        result["supplier_name"] = supplier.name
        
        elif entity_type == "INVOICE":
            invoice = db.session.get(Invoice, entity_id)
            if invoice and invoice.customer_id:
                customer = db.session.get(Customer, invoice.customer_id)
                if customer:
                    result["customer_id"] = customer.id
                    result["customer_name"] = customer.name
                    
                    # البحث عن المورد المرتبط
                    supplier = db.session.query(Supplier).filter_by(customer_id=customer.id).first()
                    if supplier:
                        result["supplier_id"] = supplier.id
                        result["supplier_name"] = supplier.name
        
        elif entity_type == "SERVICE":
            service = db.session.get(ServiceRequest, entity_id)
            if service and service.customer_id:
                customer = db.session.get(Customer, service.customer_id)
                if customer:
                    result["customer_id"] = customer.id
                    result["customer_name"] = customer.name
        
        elif entity_type == "PREORDER":
            preorder = db.session.get(PreOrder, entity_id)
            if preorder and preorder.customer_id:
                customer = db.session.get(Customer, preorder.customer_id)
                if customer:
                    result["customer_id"] = customer.id
                    result["customer_name"] = customer.name
        
        elif entity_type == "SHIPMENT":
            shipment = db.session.get(Shipment, entity_id)
            if shipment and shipment.supplier_id:
                supplier = db.session.get(Supplier, shipment.supplier_id)
                if supplier:
                    result["supplier_id"] = supplier.id
                    result["supplier_name"] = supplier.name
        
        return jsonify(result)
    
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500


@payments_bp.route("/search-entities", methods=["GET"], endpoint="search_entities")
@login_required
def search_entities():
    """البحث الذكي عن الجهات المرتبطة للدفعات"""
    try:
        entity_type = request.args.get("type", "").strip().lower()
        query = request.args.get("q", "").strip()
        
        if not entity_type or not query:
            return jsonify([])
        
        # البحث في العملاء
        if entity_type == "customer":
            customers = Customer.query.filter(
                or_(
                    Customer.name.ilike(f"%{query}%"),
                    Customer.phone.ilike(f"%{query}%"),
                    Customer.email.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "display": f"{c.name} - {c.phone}" if c.phone else c.name
            } for c in customers])
        
        # البحث في الموردين
        elif entity_type == "supplier":
            suppliers = Supplier.query.filter(
                or_(
                    Supplier.name.ilike(f"%{query}%"),
                    Supplier.contact.ilike(f"%{query}%"),
                    Supplier.phone.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": s.id,
                "name": s.name,
                "contact": s.contact,
                "phone": s.phone,
                "display": f"{s.name} - {s.phone}" if s.phone else s.name
            } for s in suppliers])
        
        # البحث في الشركاء
        elif entity_type == "partner":
            partners = Partner.query.filter(
                or_(
                    Partner.name.ilike(f"%{query}%"),
                    Partner.contact.ilike(f"%{query}%"),
                    Partner.phone.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": p.id,
                "name": p.name,
                "contact": p.contact,
                "phone": p.phone,
                "display": f"{p.name} - {p.phone}" if p.phone else p.name
            } for p in partners])
        
        # البحث في المبيعات
        elif entity_type == "sale":
            sales = Sale.query.join(Customer).filter(
                or_(
                    Sale.sale_number.ilike(f"%{query}%"),
                    Customer.name.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": s.id,
                "sale_number": s.sale_number,
                "customer_name": s.customer.name if s.customer else "غير محدد",
                "total_amount": float(s.total_amount or 0),
                "display": f"{s.sale_number} - {s.customer.name if s.customer else 'غير محدد'}"
            } for s in sales])
        
        # البحث في طلبات الصيانة
        elif entity_type == "service":
            services = ServiceRequest.query.join(Customer).filter(
                or_(
                    ServiceRequest.service_number.ilike(f"%{query}%"),
                    Customer.name.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": s.id,
                "service_number": s.service_number,
                "customer_name": s.customer.name if s.customer else "غير محدد",
                "display": f"{s.service_number} - {s.customer.name if s.customer else 'غير محدد'}"
            } for s in services])
        
        # البحث في الشحنات
        elif entity_type == "shipment":
            shipments = Shipment.query.join(Supplier).filter(
                or_(
                    Shipment.shipment_number.ilike(f"%{query}%"),
                    Supplier.name.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": s.id,
                "shipment_number": s.shipment_number,
                "supplier_name": s.supplier.name if s.supplier else "غير محدد",
                "display": f"{s.shipment_number} - {s.supplier.name if s.supplier else 'غير محدد'}"
            } for s in shipments])
        
        # البحث في النفقات
        elif entity_type == "expense":
            expenses = Expense.query.filter(
                or_(
                    Expense.description.ilike(f"%{query}%"),
                    Expense.tax_invoice_number.ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": e.id,
                "description": e.description,
                "reference": e.tax_invoice_number,
                "amount": float(e.amount or 0),
                "display": f"{e.description} - {e.tax_invoice_number}" if e.tax_invoice_number else (e.description or f"مصروف #{e.id}")
            } for e in expenses])
        
        elif entity_type == "expense_type":
            types = ExpenseType.query.filter(
                or_(
                    ExpenseType.name.ilike(f"%{query}%"),
                    func.coalesce(ExpenseType.code, '').ilike(f"%{query}%")
                )
            ).limit(10).all()
            
            return jsonify([{
                "id": et.id,
                "name": et.name,
                "code": et.code,
                "display": f"{et.name} ({et.code})" if et.code else et.name
            } for et in types])
        
        else:
            return jsonify([])
            
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500


# ===== نظام الدفع المتكامل للمتجر =====

@payments_bp.route("/shop/checkout", methods=["POST"], endpoint="shop_checkout")
@login_required
def shop_checkout():
    """إنشاء طلب دفع للمتجر الإلكتروني"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        
        # التحقق من البيانات المطلوبة
        required_fields = ["items", "total_amount", "currency"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"حقل {field} مطلوب"}), 400
        
        items = data.get("items", [])
        if not items:
            return jsonify({"error": "لا توجد منتجات في الطلب"}), 400
        
        total_amount = float(data.get("total_amount", 0))
        if total_amount <= 0:
            return jsonify({"error": "المبلغ الإجمالي يجب أن يكون أكبر من صفر"}), 400
        
        currency = data.get("currency", "ILS")
        payment_method = data.get("payment_method", "CASH")
        customer_id = data.get("customer_id")
        
        deliverer_name = data.get("deliverer_name")
        if isinstance(deliverer_name, str):
            deliverer_name = deliverer_name.strip()
        else:
            deliverer_name = ""
        receiver_name = data.get("receiver_name")
        if isinstance(receiver_name, str):
            receiver_name = receiver_name.strip()
        else:
            receiver_name = ""
        user_display = _resolve_user_display()
        counterparty_name = _resolve_counterparty_name(person_name=data.get("customer_name"), customer_id=customer_id, fallback=data.get("customer_name"))
        if not deliverer_name:
            deliverer_name = counterparty_name
        if not receiver_name:
            receiver_name = user_display
        deliverer_name = deliverer_name.strip() or None
        receiver_name = receiver_name.strip() or None

        payment = Payment(
            entity_type="SHOP_ORDER",
            customer_id=customer_id,
            direction=PaymentDirection.IN.value,
            status=PaymentStatus.PENDING.value,
            payment_date=_utc_now_naive(),
            total_amount=total_amount,
            currency=currency,
            method=payment_method,
            reference=f"طلب متجر #{_utc_now_naive().strftime('%Y%m%d%H%M%S')}",
            notes=f"دفعة متجر إلكتروني - {len(items)} منتج",
            created_by=current_user.id,
            deliverer_name=deliverer_name,
            receiver_name=receiver_name,
        )
        
        _ensure_payment_number(payment)
        db.session.add(payment)
        db.session.flush()
        
        # ✅ إنشاء Split تلقائي لطلب المتجر لضمان إنشاء القيود
        shop_split = PaymentSplit(
            payment_id=payment.id,
            amount=payment.total_amount,
            currency=payment.currency,
            method=payment.method,
            details={"shop_order": True}
        )
        db.session.add(shop_split)
        
        # إضافة تفاصيل المنتجات
        for item in items:
            product_id = item.get("product_id")
            quantity = item.get("quantity", 1)
            unit_price = item.get("unit_price", 0)
            
            if product_id and quantity > 0:
                # يمكن إضافة جدول منفصل لتفاصيل طلبات المتجر
                pass
        
        db.session.commit()
        
        # إرسال إشعار
        try:
            from notifications import notify_order_created
            notify_order_created(payment.id, {
                "type": "shop_order",
                "total_amount": total_amount,
                "currency": currency,
                "items_count": len(items)
            })
        except ImportError:
            current_app.logger.warning('notification dispatch failed silently in payments.py', exc_info=True)
        
        return jsonify({
            "success": True,
            "payment_id": payment.id,
            "payment_number": payment.payment_number,
            "total_amount": total_amount,
            "currency": currency,
            "status": payment.status
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500


@payments_bp.route("/shop/payment-methods", methods=["GET"], endpoint="shop_payment_methods")
@login_required
def shop_payment_methods():
    """الحصول على طرق الدفع المتاحة للمتجر"""
    methods = [
        {
            "id": "CASH",
            "name": "نقدي",
            "description": "دفع نقدي عند الاستلام",
            "icon": "fas fa-money-bill-wave",
            "enabled": True
        },
        {
            "id": "BANK_TRANSFER",
            "name": "تحويل بنكي",
            "description": "تحويل إلى الحساب البنكي",
            "icon": "fas fa-university",
            "enabled": True
        },
        {
            "id": "CREDIT_CARD",
            "name": "بطاقة ائتمان",
            "description": "دفع بالبطاقة الائتمانية",
            "icon": "fas fa-credit-card",
            "enabled": True
        },
        {
            "id": "CHECK",
            "name": "شيك",
            "description": "دفع بشيك",
            "icon": "fas fa-file-invoice",
            "enabled": True
        }
    ]
    
    return jsonify({"payment_methods": methods})


@payments_bp.route("/shop/process-payment", methods=["POST"], endpoint="shop_process_payment")
@login_required
def shop_process_payment():
    """معالجة الدفع للمتجر"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        
        payment_id = data.get("payment_id")
        if not payment_id:
            return jsonify({"error": "معرف الدفعة مطلوب"}), 400
        
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return jsonify({"error": "الدفعة غير موجودة"}), 404
        
        if payment.status != PaymentStatus.PENDING.value:
            return jsonify({"error": "الدفعة غير قابلة للمعالجة"}), 400
        
        # تحديث حالة الدفعة
        payment.status = PaymentStatus.COMPLETED.value
        payment.payment_date = _utc_now_naive()
        
        # تحديث رصيد العميل إذا كان موجود
        if payment.customer_id:
            try:
                from utils.customer_balance_updater import update_customer_balance_components
                update_customer_balance_components(payment.customer_id, db.session)
            except ImportError:
                current_app.logger.warning(f'Failed to update customer balance')
        
        db.session.commit()
        
        # إرسال إشعار نجاح الدفع
        try:
            from notifications import notify_payment_received
            notify_payment_received(payment.id, float(payment.total_amount), payment.currency)
        except ImportError:
            current_app.logger.warning('notification dispatch failed silently in payments.py', exc_info=True)
        
        return jsonify({
            "success": True,
            "message": "تم معالجة الدفعة بنجاح",
            "payment_id": payment.id,
            "status": payment.status
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500


@payments_bp.route("/shop/refund", methods=["POST"], endpoint="shop_refund")
@login_required
def shop_refund():
    """استرداد مبلغ للمتجر"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        
        payment_id = data.get("payment_id")
        refund_amount = float(data.get("refund_amount", 0))
        reason = data.get("reason", "استرداد")
        
        if not payment_id:
            return jsonify({"error": "معرف الدفعة مطلوب"}), 400
        
        if refund_amount <= 0:
            return jsonify({"error": "مبلغ الاسترداد يجب أن يكون أكبر من صفر"}), 400
        
        original_payment = db.session.get(Payment, payment_id)
        if not original_payment:
            return jsonify({"error": "الدفعة غير موجودة"}), 404
        
        if original_payment.status != PaymentStatus.COMPLETED.value:
            return jsonify({"error": "لا يمكن استرداد دفعة غير مكتملة"}), 400
        
        if getattr(original_payment, 'is_refunded', False):
            return jsonify({"error": "هذه الدفعة تم استردادها مسبقاً"}), 400
        
        previous_refunds = db.session.query(
            func.coalesce(func.sum(Payment.total_amount), 0)
        ).filter(
            Payment.refund_of_id == original_payment.id,
            Payment.status == PaymentStatus.COMPLETED.value
        ).scalar() or 0
        from decimal import Decimal as D
        max_refundable = float(D(str(original_payment.total_amount or 0)) - D(str(previous_refunds)))
        
        if refund_amount > max_refundable:
            return jsonify({"error": f"مبلغ الاسترداد ({refund_amount}) يتجاوز المبلغ القابل للاسترداد ({max_refundable:.2f})"}), 400
        
        user_display = _resolve_user_display()
        counterparty_name = _resolve_counterparty_name(person_name=original_payment.receiver_name or original_payment.deliverer_name, customer_id=original_payment.customer_id)
        deliverer_name = user_display.strip() if user_display else ""
        receiver_name = counterparty_name.strip() if counterparty_name else ""
        deliverer_name = deliverer_name or None
        receiver_name = receiver_name or None
        refund_payment = Payment(
            entity_type="SHOP_REFUND",
            customer_id=original_payment.customer_id,
            direction=PaymentDirection.OUT.value,
            status=PaymentStatus.COMPLETED.value,
            payment_date=_utc_now_naive(),
            total_amount=refund_amount,
            currency=original_payment.currency,
            method=original_payment.method,
            reference=f"استرداد - {original_payment.payment_number}",
            notes=f"استرداد مبلغ: {reason}",
            created_by=current_user.id,
            deliverer_name=deliverer_name,
            receiver_name=receiver_name,
            refund_of_id=original_payment.id,
        )
        
        _ensure_payment_number(refund_payment)
        db.session.add(refund_payment)
        
        # تمييز الدفعة الأصلية كمستردة إذا تم استرداد كامل المبلغ
        total_refunded_after = float(D(str(previous_refunds)) + D(str(refund_amount)))
        if total_refunded_after >= float(original_payment.total_amount or 0):
            original_payment.is_refunded = True
            db.session.add(original_payment)
        
        # تحديث رصيد العميل
        if original_payment.customer_id:
            try:
                from utils.customer_balance_updater import update_customer_balance_components
                update_customer_balance_components(original_payment.customer_id, db.session)
            except ImportError:
                current_app.logger.warning(f'Failed to update customer balance')
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "تم إنشاء استرداد بنجاح",
            "refund_id": refund_payment.id,
            "refund_amount": refund_amount,
            "currency": original_payment.currency
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500


@payments_bp.route("/shop/payment-status/<int:payment_id>", methods=["GET"], endpoint="shop_payment_status")
@login_required
def shop_payment_status(payment_id):
    """التحقق من حالة الدفع"""
    try:
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return jsonify({"error": "الدفعة غير موجودة"}), 404
        
        return jsonify({
            "payment_id": payment.id,
            "payment_number": payment.payment_number or f"PAY-{payment.id}",
            "status": getattr(payment, 'status', 'COMPLETED'),
            "total_amount": float(payment.total_amount or 0),
            "currency": payment.currency or 'ILS',
            "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
            "created_by": payment.created_by if hasattr(payment, 'created_by') else None
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500

@payments_bp.route("/archive/<payment_id>", methods=["POST"])
@login_required
def archive_payment(payment_id):
    # دعم معرّف من نوع 309_split_233 (عرض split) → نؤرشف الدفعة الأم 309
    try:
        raw = str(payment_id).strip()
        if "_split_" in raw:
            raw = raw.split("_split_")[0]
        real_id = int(raw)
    except (ValueError, TypeError):
        flash("رقم الدفعة غير صالح", "error")
        return redirect(url_for("payments.index"))
    payment_id = real_id
    try:
        from models import Archive
        
        payment = db.get_or_404(Payment, payment_id)
        
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        utils.archive_record(payment, reason, current_user.id)
        flash(f'تم أرشفة الدفعة رقم {payment.id} بنجاح', 'success')
        return redirect(url_for('payments.index'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('payments.index'))

@payments_bp.route("/restore/<payment_id>", methods=["POST"])
@login_required
def restore_payment(payment_id):
    """استعادة دفعة"""
    # دعم معرّف من نوع 309_split_233 → نستعيد الدفعة الأم 309
    try:
        raw = str(payment_id).strip()
        if "_split_" in raw:
            raw = raw.split("_split_")[0]
        real_id = int(raw)
    except (ValueError, TypeError):
        flash("رقم الدفعة غير صالح", "error")
        return redirect(url_for("payments.index"))
    payment_id = real_id
    try:
        payment = db.get_or_404(Payment, payment_id)
        
        if not payment.is_archived:
            flash('الدفعة غير مؤرشفة', 'warning')
            return redirect(url_for('payments.index'))
        
        # البحث عن الأرشيف
        from models import Archive
        archive = Archive.query.filter_by(
            record_type='payments',
            record_id=payment_id
        ).first()
        
        if archive:
            utils.restore_record(archive.id)
        
        flash(f'تم استعادة الدفعة رقم {payment_id} بنجاح', 'success')
        return redirect(url_for('payments.index'))
        
    except Exception as e:
        
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('payments.index'))


class LedgerEntry(dict):
    """بنية موحدة لحركة الشريك."""

    __slots__ = ()

    @classmethod
    def create(
        cls,
        *,
        date: datetime | None,
        label: str,
        amount: float,
        direction: str,
        category: str,
        reference: str | None = None,
        details: dict | None = None,
    ) -> "LedgerEntry":
        return cls(
            {
                "date": date,
                "label": label,
                "amount": float(amount or 0),
                "direction": direction,
                "category": category,
                "reference": reference,
                "details": details or {},
            }
        )


def _collect_partner_rights(partner: Partner, date_from: datetime, date_to: datetime) -> list:
    from routes.partner_settlements import (
        _get_partner_sales_share,
        _get_partner_preorders_share,
        _get_partner_inventory,
        _get_partner_preorders_prepaid,
        _get_partner_payments_received,
    )

    entries: list[dict] = []

    sales_share = _get_partner_sales_share(partner.id, date_from, date_to)
    for item in sales_share.get("items", []):
        amount = float(item.get("partner_share_ils") or item.get("partner_share") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label=f"نصيب من {item.get('type', 'معاملة')}\u200f",
                amount=amount,
                direction="credit",
                category="rights_sales",
                reference=item.get("reference_number"),
                details=item,
            )
        )

    preorders_share = _get_partner_preorders_share(partner.id, date_from, date_to)
    for item in preorders_share.get("items", []):
        amount = float(item.get("share_amount_ils") or item.get("share_amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="نصيب من حجز مسبق",
                amount=amount,
                direction="credit",
                category="rights_preorders",
                reference=item.get("preorder_number"),
                details=item,
            )
        )

    inventory_share = _get_partner_inventory(partner.id, date_from, date_to)
    for item in inventory_share.get("items", []):
        amount = float(item.get("partner_share") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=date_to,
                label=f"نصيب مخزون - {item.get('product_name')}",
                amount=amount,
                direction="credit",
                category="rights_inventory",
                reference=None,
                details=item,
            )
        )

    preorder_payments = _get_partner_preorders_prepaid(partner.id, partner, date_from, date_to)
    for item in preorder_payments.get("items", []):
        amount = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="دفعة حجز مسبق واردة",
                amount=amount,
                direction="credit",
                category="payments_in",
                reference=item.get("preorder_number"),
                details=item,
            )
        )

    partner_payments = _get_partner_payments_received(partner.id, partner, date_from, date_to)
    for item in partner_payments.get("items", []):
        amount = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="دفعة واردة من الشريك",
                amount=amount,
                direction="credit",
                category="payments_in",
                reference=item.get("payment_number"),
                details=item,
            )
        )

    from models import Expense, ExpenseType
    from sqlalchemy import or_, and_, func
    service_expenses = db.session.query(Expense).join(ExpenseType).filter(
        or_(
            Expense.partner_id == partner.id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner.id),
        ),
        Expense.date >= date_from,
        Expense.date <= date_to,
        func.upper(ExpenseType.code) == "PARTNER_EXPENSE"
    ).all()
    for expense in service_expenses:
        amount = float(expense.amount or 0)
        if not amount:
            continue
        amount_ils = amount
        currency = expense.currency or "ILS"
        try:
            amount_ils = float(_convert_to_ils(Decimal(str(amount)), currency, expense.date or _utc_now_naive()))
        except Exception:
            amount_ils = amount
        exp_type_name = getattr(getattr(expense, 'type', None), 'name', 'توريد خدمة')
        entries.append(
            LedgerEntry.create(
                date=expense.date or _utc_now_naive(),
                label=f"توريد خدمة: {exp_type_name}" + (f" - {expense.description}" if expense.description else ""),
                amount=amount_ils,
                direction="credit",
                category="rights_service_supply",
                reference=f"EXP-{expense.id}",
                details={
                    "expense_id": expense.id,
                    "description": expense.description,
                    "currency": currency,
                    "original_amount": amount,
                },
            )
        )

    return entries


def _collect_partner_obligations(partner: Partner, date_from: datetime, date_to: datetime) -> list:
    from routes.partner_settlements import (
        _get_partner_sales_as_customer,
        _get_partner_service_fees,
        _get_partner_damaged_items,
        _get_partner_expenses,
        _get_payments_to_partner,
    )
    from models import Expense
    from sqlalchemy import or_, and_

    entries: list[dict] = []

    sales_to_partner = _get_partner_sales_as_customer(partner.id, partner, date_from, date_to)
    for item in sales_to_partner.get("items", []):
        amount = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="مبيعات للشريك كعميل",
                amount=amount,
                direction="debit",
                category="obligations_sales",
                reference=item.get("reference"),
                details=item,
            )
        )

    service_fees = _get_partner_service_fees(partner.id, partner, date_from, date_to)
    for item in service_fees.get("items", []):
        amount_ils = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount_ils:
            continue
        
        service_number = item.get("service_number") or f"SRV-{item.get('service_id', '')}"
        
        label = f"صيانة #{service_number} - الإجمالي: {amount_ils:.2f} ₪"
        
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label=label,
                amount=amount_ils,
                direction="debit",
                category="obligations_service",
                reference=item.get("service_number") or item.get("reference"),
                details=item,
            )
        )

    damaged_items = _get_partner_damaged_items(partner.id, date_from, date_to)
    for item in damaged_items.get("items", []):
        amount = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="قطع تالفة محمولة على الشريك",
                amount=amount,
                direction="debit",
                category="obligations_damaged",
                reference=item.get("reference"),
                details=item,
            )
        )

    from models import ExpenseType
    from sqlalchemy import func
    expenses_q = db.session.query(Expense).join(ExpenseType).filter(
        or_(
            Expense.partner_id == partner.id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner.id),
        ),
        Expense.date >= date_from,
        Expense.date <= date_to,
        func.upper(ExpenseType.code) != "PARTNER_EXPENSE"
    ).all()
    for expense in expenses_q:
        amount = float(expense.amount or 0)
        if not amount:
            continue
        amount_ils = amount
        currency = expense.currency or "ILS"
        try:
            amount_ils = float(_convert_to_ils(Decimal(str(amount)), currency, expense.date or _utc_now_naive()))
        except Exception:
            amount_ils = amount
        entries.append(
            LedgerEntry.create(
                date=expense.date or _utc_now_naive(),
                label=expense.description or "مصروف على الشريك",
                amount=amount_ils,
                direction="debit",
                category="obligations_expenses",
                reference=f"EXP-{expense.id}",
                details={
                    "expense_id": expense.id,
                    "description": expense.description,
                    "currency": currency,
                    "original_amount": amount,
                },
            )
        )

    payments_out = _get_payments_to_partner(partner.id, partner, date_from, date_to)
    for item in payments_out.get("items", []):
        amount = float(item.get("amount_ils") or item.get("amount") or 0)
        if not amount:
            continue
        entries.append(
            LedgerEntry.create(
                date=datetime.strptime(item.get("date") or date_from.strftime("%Y-%m-%d"), "%Y-%m-%d"),
                label="دفعة صادرة للشريك",
                amount=amount,
                direction="debit",
                category="payments_out",
                reference=item.get("payment_number"),
                details=item,
            )
        )

    return entries


def _build_partner_ledger(
    partner: Partner,
    balance_details: dict | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict:
    df = date_from or SMART_PARTNER_BALANCE_START
    dt = date_to or _utc_now_naive()
    entries: list[dict] = []

    opening_amount = 0.0
    if balance_details and balance_details.get("balance_data"):
        opening_amount = float(balance_details["balance_data"].get("opening_balance", {}).get("amount", 0) or 0)
    else:
        opening_amount = float(partner.opening_balance or 0)

    entries.append(
        LedgerEntry.create(
            date=df,
            label="الرصيد الافتتاحي",
            amount=opening_amount,
            direction="opening",
            category="opening_balance",
            reference=None,
        )
    )
    entries[0]["running_balance"] = opening_amount
    entries[0]["balance_after"] = opening_amount
    entries[0]["debit"] = 0.0
    entries[0]["credit"] = 0.0

    entries.extend(_collect_partner_rights(partner, df, dt))
    entries.extend(_collect_partner_obligations(partner, df, dt))

    def _parse_date(d):
        if isinstance(d, datetime):
            return d
        if not d:
            return dt
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return dt

    entries[1:] = sorted(entries[1:], key=lambda e: _parse_date(e.get("date")))

    running = opening_amount
    for entry in entries[1:]:
        amt = entry.get("amount", 0)
        entry["debit"] = 0.0
        entry["credit"] = 0.0
        if entry.get("direction") == "credit":
            entry["credit"] = amt
            running += amt
        elif entry.get("direction") == "debit":
            entry["debit"] = amt
            running -= amt
        entry["running_balance"] = running
        entry["balance_after"] = running

    total_rights = sum(e.get("credit", 0.0) for e in entries)
    total_obligations = sum(e.get("debit", 0.0) for e in entries)
    net_flow = total_rights - total_obligations

    def _direction_meta(amount: float):
        if amount > 0:
            return "له رصيد عندنا", "text-success"
        if amount < 0:
            return "عليه يدفع لنا", "text-danger"
        return "متوازن", "text-secondary"

    closing_direction_text, closing_direction_class = _direction_meta(running)

    return {
        "entries": entries,
        "closing_balance": running,
        "date_from": df,
        "date_to": dt,
        "totals": {
            "rights": total_rights,
            "obligations": total_obligations,
            "net": net_flow,
            "opening": opening_amount,
        },
        "closing_direction_text": closing_direction_text,
        "closing_direction_class": closing_direction_class,
    }
@payments_bp.route("/<int:payment_id>/split/<int:split_id>", methods=["GET"], endpoint="view_payment_split")
@login_required
def view_payment_split(payment_id: int, split_id: int):
    payment = _safe_get_payment(payment_id, all_rels=True)
    if not payment:
        if _wants_json():
            return jsonify(error="not_found", message="السند غير موجود"), 404
        flash("السند غير موجود", "error")
        return redirect(url_for("payments.index"))
    try:
        split = next((s for s in list(getattr(payment, "splits", []) or []) if getattr(s, "id", None) == split_id), None)
    except Exception:
        split = None
    if not split:
        if _wants_json():
            return jsonify(error="not_found", message="جزء الدفعة غير موجود"), 404
        flash("جزء الدفعة غير موجود", "error")
        return redirect(url_for("payments.view_payment", payment_id=payment_id))
    return render_template("payments/view.html", payment=payment, active_split=split)

@payments_bp.route("/<int:payment_id>_split_<int:split_id>", methods=["GET"], endpoint="view_payment_split_legacy")
@login_required
def view_payment_split_legacy(payment_id: int, split_id: int):
    return view_payment_split(payment_id, split_id)

@payments_bp.route("/split/<int:split_id>/refund", methods=["POST"], endpoint="refund_split")
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def refund_split(split_id: int):
    split = db.session.get(PaymentSplit, split_id)
    if not split:
        return jsonify(error="not_found", message="جزء الدفعة غير موجود"), 404
    parent = db.session.get(Payment, split.payment_id)
    if not parent:
        return jsonify(error="not_found", message="السند غير موجود"), 404
    try:
        refund_direction = PaymentDirection.OUT.value if parent.direction == PaymentDirection.IN.value else PaymentDirection.IN.value
        amt = q0(getattr(split, "amount", 0) or 0)
        conv_amt = q0(getattr(split, "converted_amount", 0) or 0)
        parent_ccy = (parent.currency or "ILS").upper()
        split_conv_ccy = (getattr(split, "converted_currency", None) or getattr(split, "currency", None) or parent.currency or "ILS").upper()
        total_amount = conv_amt if (conv_amt > 0 and split_conv_ccy == parent_ccy) else amt
        refund = Payment(
            entity_type=parent.entity_type,
            customer_id=parent.customer_id,
            supplier_id=parent.supplier_id,
            partner_id=parent.partner_id,
            sale_id=parent.sale_id,
            invoice_id=parent.invoice_id,
            service_id=parent.service_id,
            expense_id=parent.expense_id,
            preorder_id=parent.preorder_id,
            shipment_id=parent.shipment_id,
            loan_settlement_id=parent.loan_settlement_id,
            direction=refund_direction,
            status=PaymentStatus.COMPLETED.value,
            payment_date=_utc_now_naive(),
            total_amount=total_amount,
            currency=(split.currency or parent.currency or "ILS"),
            method=getattr(split.method, "value", split.method),
            reference=f"إرجاع جزء #{split.id} من الدفعة #{parent.id}",
            notes=parent.notes,
            refund_of_id=parent.id,
        )
        _ensure_payment_number(refund)
        db.session.add(refund)
        new_split = PaymentSplit(
            payment=refund,
            method=split.method,
            amount=split.amount,
            currency=split.currency,
            converted_amount=split.converted_amount,
            converted_currency=split.converted_currency,
            fx_rate_used=split.fx_rate_used,
            fx_rate_source=split.fx_rate_source,
            fx_rate_timestamp=split.fx_rate_timestamp,
            fx_base_currency=split.fx_base_currency,
            fx_quote_currency=split.fx_quote_currency,
            details=split.details,
        )
        db.session.add(new_split)
        try:
            details = split.details or {}
            if isinstance(details, str):
                import json as _json
                try:
                    details = _json.loads(details)
                except Exception:
                    details = {}
            details["refunded"] = True
            split.details = details
            db.session.add(split)
        except Exception:
            current_app.logger.warning(f'Failed to mark split {split.id} details as refunded')
        try:
            split_method_val = getattr(split.method, 'value', split.method)
            if str(split_method_val).upper() == PaymentMethod.CHEQUE.value:
                service = CheckActionService(current_user)
                try:
                    ctx = service._resolve(split.id)
                    prev = service._current_status(ctx)
                    base_note = 'تم ارجاعه للزبون بسبب ارجاع الدفعة'
                    if prev == 'RETURNED':
                        service.run(split.id, 'PENDING', '')
                    else:
                        service.run(split.id, 'RETURNED', base_note + ' [RETURN_REASON=PAYMENT_REFUND]')
                except Exception:
                    current_app.logger.warning('refund processing failed silently in payments.py', exc_info=True)
        finally:
            db.session.commit()

        # تحديث الأرصدة بعد استرجاع الدفعة
        try:
            if refund.supplier_id:
                utils.update_entity_balance("SUPPLIER", refund.supplier_id)
            if refund.partner_id:
                utils.update_entity_balance("PARTNER", refund.partner_id)
            if refund.customer_id:
                utils.update_entity_balance("CUSTOMER", refund.customer_id)
        except Exception as e:
            current_app.logger.error(f"❌ فشل تحديث الأرصدة بعد استرجاع جزء دفعة {split_id}: {e}")

        # تمييز الدفعة الأصلية كمستردة فقط إذا تم استرداد جميع الأجزاء
        all_splits = list(getattr(parent, "splits", []) or [])
        all_refunded = all(
            (isinstance(s.details, dict) and s.details.get("refunded"))
            for s in all_splits if s.id != split.id
        )
        if all_refunded:
            parent.is_refunded = True
            db.session.add(parent)
            db.session.commit()

        return jsonify(success=True, refund_id=refund.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('split refund error')
        return jsonify(error="refund_failed", message="حدث خطأ داخلي"), 500





@payments_bp.route("/refund/<int:payment_id>", methods=["POST"], endpoint="refund_payment")
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def refund_payment(payment_id: int):
    original = db.session.get(Payment, payment_id)
    if not original:
        return jsonify(error="not_found", message="السند غير موجود"), 404
    try:
        existing = (
            db.session.query(Payment)
            .filter(Payment.refund_of_id == original.id)
            .order_by(Payment.id.desc())
            .first()
        )
        if existing:
            return jsonify(success=True, refund_id=existing.id, already_refunded=True)
        splits = list(getattr(original, "splits", []) or [])
        refund_direction = PaymentDirection.OUT.value if original.direction == PaymentDirection.IN.value else PaymentDirection.IN.value
        amount_total = _sum_splits_decimal(splits) if splits else q0(getattr(original, "total_amount", 0) or 0)
        refund = Payment(
            entity_type=original.entity_type,
            customer_id=original.customer_id,
            supplier_id=original.supplier_id,
            partner_id=original.partner_id,
            sale_id=original.sale_id,
            invoice_id=original.invoice_id,
            service_id=original.service_id,
            expense_id=original.expense_id,
            preorder_id=original.preorder_id,
            shipment_id=original.shipment_id,
            loan_settlement_id=original.loan_settlement_id,
            direction=refund_direction,
            status=PaymentStatus.COMPLETED.value,
            payment_date=_utc_now_naive(),
            total_amount=amount_total,
            currency=(original.currency or "ILS"),
            method=(original.method or PaymentMethod.CASH.value),
            reference=f"إرجاع كامل الدفعة #{original.id}",
            notes=original.notes,
            refund_of_id=original.id,
        )
        _ensure_payment_number(refund)
        db.session.add(refund)
        if splits:
            for sp in splits:
                db.session.add(PaymentSplit(
                    payment=refund,
                    method=sp.method,
                    amount=sp.amount,
                    currency=sp.currency,
                    converted_amount=sp.converted_amount,
                    converted_currency=sp.converted_currency,
                    fx_rate_used=sp.fx_rate_used,
                    fx_rate_source=sp.fx_rate_source,
                    fx_rate_timestamp=sp.fx_rate_timestamp,
                    fx_base_currency=sp.fx_base_currency,
                    fx_quote_currency=sp.fx_quote_currency,
                    details=sp.details,
                ))
                try:
                    details = sp.details or {}
                    if isinstance(details, str):
                        import json as _json
                        try:
                            details = _json.loads(details)
                        except Exception:
                            details = {}
                    details["refunded"] = True
                    sp.details = details
                    db.session.add(sp)
                except Exception:
                    current_app.logger.warning('DB add failed silently')
        else:
            db.session.add(PaymentSplit(
                payment=refund,
                method=(original.method or PaymentMethod.CASH.value),
                amount=original.total_amount,
                currency=original.currency,
                converted_amount=0,
                converted_currency=(original.currency or "ILS"),
                details={"refunded": True},
            ))
        # الحالة تبقى COMPLETED للحفاظ على صحة القيود المحاسبية وحسابات الأرصدة.
        # is_refunded يُستخدم للتمييز في التقارير بدون تغيير الحالة.
        original.is_refunded = True
        db.session.add(original)
        try:
            service = CheckActionService(current_user)
            cheque_splits = [sp for sp in splits if getattr(sp.method, 'value', sp.method) == PaymentMethod.CHEQUE.value]
            if cheque_splits:
                for sp in cheque_splits:
                    try:
                        ctx = service._resolve(sp.id)
                        prev = service._current_status(ctx)
                        base_note = 'تم ارجاعه للزبون بسبب ارجاع الدفعة'
                        if prev == 'RETURNED':
                            service.run(sp.id, 'PENDING', '')
                        else:
                            service.run(sp.id, 'RETURNED', base_note + ' [RETURN_REASON=PAYMENT_REFUND]')
                    except Exception:
                        current_app.logger.warning(f'Failed to update check status for split {sp.id} during refund')
                        continue
            else:
                method_val = getattr(original.method, 'value', original.method)
                if str(method_val).upper() == PaymentMethod.CHEQUE.value:
                    try:
                        ctx = service._resolve(original.id)
                        prev = service._current_status(ctx)
                        base_note = 'تم ارجاعه للزبون بسبب ارجاع الدفعة'
                        if prev == 'RETURNED':
                            service.run(original.id, 'PENDING', '')
                        else:
                            service.run(original.id, 'RETURNED', base_note + ' [RETURN_REASON=PAYMENT_REFUND]')
                    except Exception:
                        current_app.logger.warning(f'Failed to update check status for payment {original.id} during refund')
        finally:
            db.session.commit()
        
        try:
            customer_id = getattr(refund, "customer_id", None)
            supplier_id = getattr(refund, "supplier_id", None)
            partner_id = getattr(refund, "partner_id", None)
            if getattr(refund, "expense_id", None) and not (customer_id or supplier_id or partner_id):
                exp = db.session.get(Expense, int(refund.expense_id))
                if exp:
                    customer_id = getattr(exp, "customer_id", None)
                    supplier_id = getattr(exp, "supplier_id", None)
                    partner_id = getattr(exp, "partner_id", None)
            if customer_id:
                utils.update_entity_balance("CUSTOMER", customer_id)
            if supplier_id:
                utils.update_entity_balance("SUPPLIER", supplier_id)
            if partner_id:
                utils.update_entity_balance("PARTNER", partner_id)
        except Exception as e:
            current_app.logger.error(f"❌ فشل تحديث الأرصدة بعد استرجاع الدفعة {payment_id}: {e}")
        return jsonify(success=True, refund_id=refund.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('payment refund error')
        return jsonify(error="refund_failed", message="حدث خطأ داخلي"), 500
