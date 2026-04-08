from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import redis
from flask import Response, abort, current_app, make_response, request, jsonify
from flask_login import current_user, login_required
from flask_mail import Message
from sqlalchemy import case, func, select, or_, text
from sqlalchemy.orm.attributes import set_committed_value
from constants import DEFAULT_CURRENCY
from extensions import cache

try:
    import qrcode
except Exception:
    qrcode = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
except Exception:
    colors = letter = SimpleDocTemplate = Table = TableStyle = None

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None

from extensions import limiter, db, mail

def _get_models():
    from models import Customer, Supplier, Partner
    return Customer, Supplier, Partner

redis_client: Optional[redis.Redis] = None
_TWOPLACES = Decimal("0.01")
_ACL_CACHE_LISTENERS_INSTALLED = False
_ACCOUNTING_LISTENERS_INSTALLED = False


def _D(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def q(value: Any, places: int = 2) -> Decimal:
    try:
        p = int(places)
    except Exception:
        p = 2
    try:
        quant = Decimal(10) ** (-p)
    except Exception:
        quant = _TWOPLACES
    try:
        return _D(value).quantize(quant, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0").quantize(quant, rounding=ROUND_HALF_UP)


def Q2(value: Any) -> Decimal:
    return q(value, 2)


def D(value: Any) -> Decimal:
    return _D(value)


def _q2(x: Any) -> Decimal:
    return q(x, 2)


def _q(x: Any) -> Decimal:
    return q(x, 2)


def _get_or_404(model, ident, *, load_options=None, pk_name: str = "id"):
    try:
        if pk_name == "id" and not load_options:
            obj = db.session.get(model, ident)
        else:
            stmt = select(model)
            if load_options:
                stmt = stmt.options(*load_options)
            stmt = stmt.where(getattr(model, pk_name) == ident)
            result = db.session.execute(stmt)
            if load_options:
                result = result.unique()
            obj = result.scalar_one_or_none()
    except Exception:
        obj = None
    if obj is None:
        abort(404)
    return obj


def search_model(
    model,
    search_fields: List[str],
    *,
    label_attr: str = "name",
    value_attr: str = "id",
    extra_filters: Optional[List] = None,
    limit_default: int = 20,
    serializer: Optional[Callable[[Any], Dict[str, Any]]] = None,
    q_param: str = "q",
    **kwargs,
):
    qtxt = (request.args.get(q_param) or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit") or limit_default), 100))
    except Exception:
        limit = limit_default
    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1

    query = db.session.query(model)
    if extra_filters:
        query = query.filter(*extra_filters)

    if qtxt:
        ors = []
        q_low = qtxt.lower()
        for field_name in (search_fields or []):
            col = getattr(model, field_name, None)
            if col is not None:
                ors.append(func.lower(col).like(f"%{q_low}%"))
        if qtxt.isdigit() and hasattr(model, value_attr):
            try:
                ors.append(getattr(model, value_attr) == int(qtxt))
            except Exception:
                pass
        if ors:
            query = query.filter(or_(*ors))

    if hasattr(model, label_attr):
        query = query.order_by(getattr(model, label_attr).asc())
    elif hasattr(model, value_attr):
        query = query.order_by(getattr(model, value_attr).asc())

    offset = (page - 1) * limit
    items_query = query.offset(offset).limit(limit + 1)
    items = items_query.all()
    
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    
    total = None

    def _serialize(obj):
        if serializer:
            d = serializer(obj)
        else:
            d = {
                "id": getattr(obj, value_attr, None),
                "text": getattr(obj, label_attr, None) or str(getattr(obj, value_attr, "")),
            }
        if "name" not in d:
            d["name"] = d.get("text")
        return d

    results = [_serialize(o) for o in items]
    return jsonify({"results": results, "pagination": {"more": has_more}})


def _limit(spec: str):
    return limiter.limit(spec)


def _query_limit(default: int = 20, maximum: int = 50) -> int:
    try:
        limit = int(request.args.get("limit", default))
    except Exception:
        limit = default
    return min(max(limit, 1), maximum)


def init_app(app):
    global redis_client

    app.jinja_env.filters.update({
        "format_currency": format_currency,
        "format_percent": format_percent,
        "format_date": format_date,
        "format_datetime": format_datetime,
        "yes_no": yes_no,
        "status_label": status_label,
    })

    skip_redis = str(os.getenv("SKIP_REDIS", "")).strip().lower() in {"1", "true", "yes", "on"}
    if skip_redis:
        redis_client = None
    else:
        try:
            rc = redis.StrictRedis.from_url(
                app.config.get("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            if getattr(rc, "ping", None):
                rc.ping()
            redis_client = rc
        except Exception:
            redis_client = None

    def _acl_ctx():
        def can(code: str) -> bool:
            try:
                if not getattr(current_user, "is_authenticated", False):
                    return False
                if is_super():
                    return True
                needed = _expand_perms(code)
                if hasattr(current_user, "has_permission") and callable(current_user.has_permission):
                    for p in needed:
                        if current_user.has_permission(p):
                            return True
                user_perms = _get_user_permissions(current_user)
                return bool(user_perms & needed)
            except Exception:
                return False

        return dict(
            can=can,
            can_super=lambda: is_super(),
            can_admin=lambda: is_admin(),
        )

    app.context_processor(_acl_ctx)

    _install_acl_cache_listeners()
    _install_accounting_listeners()

def send_email_notification(subject: str, recipients: List[str], body: str, html: Optional[str] = None):
    mail.send(Message(subject=subject, recipients=recipients, body=body, html=html))


def _to_e164(msisdn: str) -> Optional[str]:
    raw = (msisdn or "").strip()
    if not raw:
        return None
    if raw.startswith("+"):
        s = "+" + re.sub(r"\D", "", raw[1:])
        digits = re.sub(r"\D", "", s)
        return s if len(digits) >= 7 else None
    s = re.sub(r"\D", "", raw)
    if not s:
        return None
    if s.startswith("00"):
        s = s[2:]
    cc = str(current_app.config.get("TWILIO_DEFAULT_COUNTRY_CODE") or "").lstrip("+")
    if cc:
        if s.startswith("0"):
            s = cc + s[1:]
        elif not s.startswith(cc):
            s = cc + s
    return "+" + s


def send_whatsapp_message(to_number: str, body: str) -> Tuple[bool, str]:
    try:
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client
    except ImportError:
        return (False, "مكتبة Twilio غير مثبتة. قم بتثبيتها: pip install twilio")

    sid = current_app.config.get("TWILIO_ACCOUNT_SID")
    token = current_app.config.get("TWILIO_AUTH_TOKEN")
    from_number = current_app.config.get("TWILIO_WHATSAPP_NUMBER")
    if not all([sid, token, from_number]):
        return (False, "Twilio credentials missing")
    to_e164 = _to_e164(to_number)
    if not to_e164:
        return (False, "Invalid recipient number")
    try:
        msg = Client(sid, token).messages.create(
            from_=f"whatsapp:{from_number}",
            to=f"whatsapp:{to_e164}",
            body=body,
        )
        return (True, msg.sid)
    except TwilioRestException as e:
        code = getattr(e, "code", "")
        msg = getattr(e, "msg", str(e))
        return (False, f"{code} {msg}")
    except Exception as e:
        return (False, str(e))


def format_currency(value: Any) -> str:
    try:
        return f"{float(_q2(value)):,.2f} ₪"
    except Exception:
        return "0.00 ₪"


def format_currency_in_ils(value: Any) -> str:
    """تنسيق العملة بالشيكل"""
    try:
        return f"{float(_q2(value)):,.2f} شيكل"
    except Exception:
        return "0.00 شيكل"


def get_partner_balance_unified(partner_id: int) -> float:
    """
    دالة موحدة لحساب رصيد الشريك - تستخدم current_balance من قاعدة البيانات
    """
    try:
        from models import Partner
        from extensions import db
        
        partner = db.session.get(Partner, partner_id)
        if not partner:
            return 0.0
        
        return float(partner.current_balance or 0)
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.warning(f"⚠️ خطأ عام في get_partner_balance_unified #{partner_id}: {e}")
        except:
            pass
        return 0.0

def get_entity_balance_in_ils(entity_type: str, entity_id: int) -> Decimal:
    try:
        from models import Customer, Supplier, Partner
        cache_key = f"entity_balance_{entity_type}_{entity_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Decimal(str(cached))
        
        et = (entity_type or "").upper()
        result = Decimal("0.00")
        if et == "CUSTOMER":
            obj = db.session.get(Customer, entity_id)
            if obj:
                result = Decimal(str(getattr(obj, "balance_in_ils", 0) or 0))
        elif et == "SUPPLIER":
            obj = db.session.get(Supplier, entity_id)
            if obj:
                result = Decimal(str(getattr(obj, "balance_in_ils", 0) or 0))
        elif et == "PARTNER":
            result = Decimal(str(get_partner_balance_unified(entity_id)))
        
        try:
            cache.set(cache_key, float(result), timeout=300)
        except Exception:
            pass
        return result
    except Exception:
        return Decimal("0.00")


def validate_currency_consistency(entity_type: str, entity_id: int) -> dict:
    """التحقق من اتساق العملات"""
    try:
        from models import Customer, Supplier, Partner
        balance = get_entity_balance_in_ils(entity_type, entity_id)
        
        et = (entity_type or "").upper()
        stored_balance = Decimal("0.00")
        if et == "CUSTOMER":
            customer = db.session.get(Customer, entity_id)
            if customer:
                stored_balance = Decimal(str(customer.balance or 0))
        elif et == "SUPPLIER":
            supplier = db.session.get(Supplier, entity_id)
            if supplier:
                stored_balance = Decimal(str(supplier.balance or 0))
        elif et == "PARTNER":
            partner = db.session.get(Partner, entity_id)
            if partner:
                stored_balance = Decimal(str(partner.balance or 0))
        
        difference = abs(balance - stored_balance)
        tolerance = Decimal("0.01")
        
        return {
            'is_consistent': difference <= tolerance,
            'calculated_balance': balance,
            'stored_balance': stored_balance,
            'difference': difference,
            'tolerance': tolerance,
            'validation_date': datetime.now(timezone.utc)
        }
    except Exception as e:
        return {
            'is_consistent': False,
            'error': str(e),
            'validation_date': datetime.now(timezone.utc)
        }


def format_percent(value: Any) -> str:
    try:
        return f"{float(_q2(value)):.2f}%"
    except Exception:
        return "0.00%"


def format_date(value: Optional[datetime], fmt: str = "%Y-%m-%d") -> str:
    try:
        return value.strftime(fmt) if value else "-"
    except Exception:
        return "-"


def format_datetime(value: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        return value.strftime(fmt) if value else ""
    except Exception:
        return ""


def active_archived(value: Any) -> str:
    return "نشط" if value else "مؤرشف"


def yes_no(value: Any) -> str:
    return active_archived(value)


def status_label(status: Any) -> str:
    m = {
        "active": "نشط",
        "inactive": "غير نشط",
        "credit_hold": "معلق ائتمانيًا",
        "pending": "قيد الانتظار",
        "completed": "مكتمل",
        "failed": "فشل",
    }
    return m.get(str(status).lower(), str(status))


def qr_to_base64(value: str) -> str:
    if not qrcode:
        return ""
    img = qrcode.make(value)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _get_id(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if "|" in s:
            s = s.split("|", 1)[0]
        try:
            return int(float(s))
        except Exception:
            return None
    if isinstance(v, dict):
        return _get_id(v.get("id"))
    if isinstance(v, (list, tuple)) and v:
        return _get_id(v[0])
    return None


def _apply_stock_delta(product_id: int, warehouse_id: int, delta: int) -> int:
    from models import StockLevel

    delta = int(delta or 0)
    rec = (
        StockLevel.query
        .filter_by(product_id=product_id, warehouse_id=warehouse_id)
        .with_for_update(read=False)
        .first()
    )
    if rec is None:
        if delta < 0:
            raise ValueError("insufficient stock")
        rec = StockLevel(product_id=product_id, warehouse_id=warehouse_id, quantity=0, reserved_quantity=0)
        db.session.add(rec)
        db.session.flush()

    new_qty = int(rec.quantity or 0) + delta
    reserved = int(getattr(rec, "reserved_quantity", 0) or 0)
    if new_qty < 0 or new_qty < reserved:
        raise ValueError("insufficient stock")

    rec.quantity = new_qty
    db.session.flush()
    return new_qty


def recent_notes(limit: int = 5):
    from models import Note
    return Note.query.order_by(Note.created_at.desc()).limit(limit).all()


def generate_excel_report(data: Iterable[Any], filename: str = "report.xlsx") -> Response:
    def _row_to_dict(item):
        if hasattr(item, "to_dict"):
            try:
                return item.to_dict()
            except Exception:
                pass
        if isinstance(item, dict):
            return item
        try:
            cols = {}
            for k in dir(item):
                if k.startswith("_"):
                    continue
                v = getattr(item, k, None)
                if callable(v):
                    continue
                if k in ("metadata", "query", "query_class"):
                    continue
                if hasattr(v, "property"):
                    continue
                cols[k] = v
            return cols
        except Exception:
            return {"value": str(item)}

    rows = [_row_to_dict(x) for x in data]

    try:
        import pandas as pd
    except Exception:
        buf = io.StringIO()
        if rows:
            fieldnames = sorted({k for r in rows for k in r.keys()})
            w = csv.DictWriter(buf, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fieldnames})
        else:
            buf.write("")
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename.rsplit(".",1)[0]}.csv"'},
        )

    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def generate_pdf_report(data: Iterable[Any]) -> Response:
    if not all([colors, letter, SimpleDocTemplate, Table, TableStyle]):
        abort(500, description="ReportLab غير متوفر على الخادم")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    table_data = [["ID", "Name", "Balance"]] + [
        [str(getattr(item, "id", "")), getattr(item, "name", ""), f"{getattr(item, 'balance', 0):,.2f}"]
        for item in data
    ]
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))
    doc.build([table])
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
    )


def generate_vcf(customers: Iterable[Any], fields: List[str], filename: str = "contacts.vcf") -> Response:
    cards = []
    for c in customers:
        def _get(attr, default=""):
            try:
                v = getattr(c, attr, default)
                return v if v is not None else default
            except Exception:
                return default

        name = ""
        if "name" in fields:
            for attr in ("name", "full_name", "username"):
                name = _get(attr, "")
                if name:
                    break

        phone = ""
        if "phone" in fields:
            for attr in ("phone", "whatsapp", "mobile"):
                phone = _get(attr, "")
                if phone:
                    break

        email = _get("email", "") if "email" in fields else ""

        card = ["BEGIN:VCARD", "VERSION:3.0"]
        if name:
            card.append(f"N:{name}")
            card.append(f"FN:{name}")
        if phone:
            card.append(f"TEL;TYPE=CELL:{phone}")
        if email:
            card.append(f"EMAIL;TYPE=INTERNET:{email}")
        card.append("END:VCARD")
        cards.append("\r\n".join(card))

    payload = ("\r\n".join(cards) + "\r\n").encode("utf-8")
    resp = make_response(payload)
    resp.mimetype = "text/vcard"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def generate_csv_contacts(customers: Iterable[Any], fields: List[str]) -> Response:
    buffer = io.StringIO()
    w = csv.writer(buffer)
    w.writerow(fields)
    for c in customers:
        w.writerow([getattr(c, f, "") or "" for f in fields])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
    )


def generate_excel_contacts(customers: Iterable[Any], fields: List[str]) -> Response:
    try:
        from openpyxl import Workbook
    except Exception:
        abort(500, description="openpyxl غير متوفر على الخادم")
    stream = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.append(fields)
    for c in customers:
        ws.append([getattr(c, f, "") or "" for f in fields])
    wb.save(stream)
    stream.seek(0)
    return Response(
        stream.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="contacts.xlsx"'},
    )
def entity_phone(obj) -> str:
    for attr in ("phone", "phone_number", "mobile", "whatsapp"):
        try:
            v = getattr(obj, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    return ""

def entity_email(obj) -> str:
    try:
        v = getattr(obj, "email", None)
        return v or ""
    except Exception:
        return ""

def entity_name(obj) -> str:
    for attr in ("name", "full_name", "username"):
        try:
            v = getattr(obj, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    try:
        return str(getattr(obj, "id", ""))
    except Exception:
        return ""

def entity_display(obj) -> str:
    n = entity_name(obj)
    ph = entity_phone(obj)
    em = entity_email(obj)
    tail = ph if ph else (em if em else "")
    return f"{n} - {tail}" if tail else n
def _get_super_roles():
    try:
        from permissions_config.permissions import PermissionsRegistry
        return PermissionsRegistry.get_super_roles()
    except Exception:
        return {"developer", "owner", "super_admin", "super"}

_SUPER_ROLES = _get_super_roles()

# مفاتيح وأسماء أساسية من SystemPermissions؛ القيم الإضافية في كل set لأسماء قديمة/مرادفة في DB (توافق رجعي).
_PERMISSION_ALIASES = {
    "view_warehouses": {"view_warehouses", "view_inventory", "manage_inventory", "manage_warehouses"},
    "view_inventory": {"view_inventory", "manage_inventory", "manage_warehouses"},
    "manage_inventory": {"manage_inventory", "manage_warehouses", "manage_stock", "warehouse_transfer"},
    "warehouse_transfer": {"warehouse_transfer", "manage_inventory", "manage_warehouses"},
    "view_parts": {"view_parts", "view_inventory", "manage_inventory"},
    "view_preorders": {"view_preorders", "view_inventory", "manage_inventory"},
    "add_preorder": {"add_preorder", "manage_inventory"},
    "edit_preorder": {"edit_preorder", "manage_inventory"},
    "delete_preorder": {"delete_preorder", "manage_inventory"},
    "add_customer": {"add_customer", "manage_customers"},
    "add_supplier": {"add_supplier", "manage_vendors"},
    "add_partner": {"add_partner", "manage_vendors"},
    "manage_shipments": {"manage_shipments", "manage_inventory", "manage_warehouses"},
    "manage_payments": {"manage_payments", "manage_sales"},
    "backup_database": {"backup_database", "backup", "backup_db", "download_backup", "db_backup"},
    "restore_database": {"restore_database", "restore", "restore_db", "upload_backup", "db_restore"},
    "view_shop": {"view_shop", "browse_products"},
    "browse_products": {"browse_products", "view_shop"},
    "manage_shop": {"manage_shop", "view_shop", "browse_products"},
}


def _expand_perms(*names) -> set:
    expanded = set()
    for n in names:
        if isinstance(n, (list, tuple, set)):
            expanded |= _expand_perms(*n)
        else:
            key = str(n).lower()
            expanded |= _PERMISSION_ALIASES.get(key, {key})
    return expanded

# وظائف التخزين المؤقت المحسّنة
def cache_key(prefix, *args):
    """إنشاء مفتاح تخزين مؤقت"""
    return f"{prefix}:{':'.join(str(arg) for arg in args)}"

@cache.memoize(timeout=300)  # 5 دقائق
def get_cached_currencies():
    """الحصول على العملات من التخزين المؤقت"""
    from models import Currency
    return Currency.query.filter_by(is_active=True).all()

@cache.memoize(timeout=600)  # 10 دقائق
def get_cached_exchange_rates():
    """الحصول على أسعار الصرف من التخزين المؤقت"""
    from models import ExchangeRate
    return ExchangeRate.query.filter_by(is_active=True).all()

@cache.memoize(timeout=180)  # 3 دقائق
def get_cached_customer_balance(customer_id):
    """الحصول على رصيد العميل من التخزين المؤقت"""
    from models import Customer
    customer = db.session.get(Customer, customer_id)
    if customer:
        return float(customer.balance_in_ils)
    return 0.0

@cache.memoize(timeout=300)  # 5 دقائق
def get_cached_dashboard_stats():
    """الحصول على إحصائيات لوحة التحكم من التخزين المؤقت"""
    from models import Customer, Sale, Payment, ServiceRequest
    
    stats = {
        'total_customers': Customer.query.count(),
        'total_sales': Sale.query.count(),
        'total_payments': Payment.query.count(),
        'total_services': ServiceRequest.query.count(),
    }
    
    return stats

@cache.memoize(timeout=600)  # 10 دقائق
def get_cached_sales_summary():
    """إحصائيات المبيعات المحسنة"""
    from models import Sale, SaleLine, db
    from sqlalchemy import func
    
    # إجمالي المبيعات
    total_sales = db.session.query(func.sum(Sale.total_amount)).scalar() or 0
    
    # عدد المبيعات
    sales_count = Sale.query.count()
    
    # متوسط قيمة البيع
    avg_sale = total_sales / sales_count if sales_count > 0 else 0
    
    # أفضل المنتجات مبيعاً
    top_products = db.session.query(
        SaleLine.product_id,
        func.sum(SaleLine.quantity).label('total_quantity'),
        func.sum(SaleLine.total_price).label('total_revenue')
    ).group_by(SaleLine.product_id).order_by(
        func.sum(SaleLine.quantity).desc()
    ).limit(5).all()
    
    return {
        'total_sales': float(total_sales),
        'sales_count': sales_count,
        'avg_sale': float(avg_sale),
        'top_products': [
            {
                'product_id': p.product_id,
                'quantity': p.total_quantity,
                'revenue': float(p.total_revenue)
            } for p in top_products
        ]
    }

@cache.memoize(timeout=1800)  # 30 دقيقة
def get_cached_inventory_status():
    """حالة المخزون المحسنة"""
    from models import Product, StockLevel, Warehouse
    
    # المنتجات منخفضة المخزون
    low_stock_products = db.session.query(Product).join(StockLevel).filter(
        StockLevel.quantity <= Product.min_stock_level
    ).limit(10).all()
    
    # إجمالي قيمة المخزون (بسعر التكلفة)
    total_inventory_value = db.session.query(
        func.sum(StockLevel.quantity * Product.purchase_price)
    ).join(Product).filter(
        StockLevel.quantity > 0
    ).scalar() or 0
    
    return {
        'low_stock_count': len(low_stock_products),
        'low_stock_products': [
            {
                'id': p.id,
                'name': p.name,
                'current_stock': p.current_stock,
                'min_stock': p.min_stock_level
            } for p in low_stock_products
        ],
        'total_inventory_value': float(total_inventory_value)
    }

def clear_cache_pattern(pattern):
    """مسح التخزين المؤقت بنمط معين"""
    try:
        cache.delete_memoized(pattern)
    except Exception as e:
        pass

def optimize_database_queries():
    """تحسين استعلامات قاعدة البيانات"""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import time
    
    @event.listens_for(Engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.time()
    
    @event.listens_for(Engine, "after_cursor_execute")
    def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        total = time.time() - context._query_start_time
        if total > 0.1:
            pass

def get_performance_metrics():
    """الحصول على مقاييس الأداء"""
    from sqlalchemy import text
    
    try:
        uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if "postgresql" not in uri:
            return {'error': 'unsupported database'}
        
        db_size = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
        table_count = db.session.execute(text("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        """)).scalar()
        index_count = db.session.execute(text("""
            SELECT COUNT(*)
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        """)).scalar()
        
        return {
            'database_size_mb': round(float(db_size or 0) / (1024 * 1024), 2),
            'table_count': int(table_count or 0),
            'index_count': int(index_count or 0),
            'cache_hit_ratio': getattr(cache, 'hit_ratio', 0)
        }
    except Exception as e:
        return {'error': str(e)}

def optimize_system():
    """تحسين النظام العام"""
    try:
        uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if "postgresql" in uri:
            conn = db.engine.raw_connection()
            try:
                conn.set_isolation_level(0)
                cursor = conn.cursor()
                cursor.execute("VACUUM ANALYZE")
                cursor.close()
            finally:
                conn.close()
        
        # مسح التخزين المؤقت القديم
        cache.clear()
        
        return True
    except Exception as e:
        return False

def clear_all_cache():
    """مسح جميع التخزين المؤقت"""
    try:
        cache.clear()
    except Exception:
        pass


def _iter_rel(rel):
    try:
        return rel.all()
    except Exception:
        return rel or []


def _fetch_permissions_from_db(user) -> set:
    perms = set()
    if getattr(user, "role", None):
        try:
            perms |= get_role_permissions(user.role)
        except Exception:
            for p in _iter_rel(user.role.permissions):
                name = getattr(p, "code", None) or getattr(p, "name", None)
                if name:
                    perms.add(str(name).lower())
    extra_rel = getattr(user, "extra_permissions", None)
    if extra_rel is not None:
        for p in _iter_rel(extra_rel):
            name = getattr(p, "code", None) or getattr(p, "name", None)
            if name:
                perms.add(str(name).lower())
    return perms


def _get_user_permissions(user) -> set:
    if not user:
        return set()
    try:
        from flask import has_request_context, g
        if has_request_context():
            cache_map = getattr(g, "_user_permissions_cache", None)
            if not isinstance(cache_map, dict):
                cache_map = {}
                g._user_permissions_cache = cache_map
            uid = getattr(user, "id", None)
            if uid is not None and uid in cache_map and isinstance(cache_map.get(uid), set):
                return cache_map.get(uid) or set()
    except Exception:
        cache_map = None
        uid = None
    key = f"user_permissions:{user.id}"
    rc = redis_client
    if rc:
        try:
            cached = rc.smembers(key)
        except Exception:
            cached = None
        if cached:
            def _to_text(v):
                if isinstance(v, str):
                    return v
                if isinstance(v, (bytes, bytearray)):
                    try:
                        return v.decode("utf-8")
                    except Exception:
                        return v.decode(errors="ignore")
                return str(v)
            perms = {_to_text(x).lower() for x in cached}
            try:
                if cache_map is not None and uid is not None:
                    cache_map[uid] = perms
            except Exception:
                pass
            return perms

    perms = _fetch_permissions_from_db(user)
    try:
        if rc:
            rc.delete(key)
            if perms:
                rc.sadd(key, *list(perms))
            rc.expire(key, 300)
    except Exception:
        pass
    try:
        if cache_map is not None and uid is not None:
            cache_map[uid] = set(perms or set())
    except Exception:
        pass
    return perms


def _csv_set(val: Optional[str]) -> set:
    if not val:
        return set()
    return {x.strip().lower() for x in str(val).split(",") if x.strip()}


def _match_user(user, ids_csv, emails_csv) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    ids = _csv_set(ids_csv)
    emails = _csv_set(emails_csv)
    if str(getattr(user, "id", "")).lower() in ids:
        return True
    email = (getattr(user, "email", "") or "").lower()
    return email in emails


def is_super() -> bool:
    try:
        if _match_user(
            current_user,
            current_app.config.get("SUPER_USER_IDS"),
            current_app.config.get("SUPER_USER_EMAILS"),
        ):
            return True
    except Exception:
        pass
    try:
        if not getattr(current_user, "is_authenticated", False):
            return False
        if getattr(current_user, "is_super_role", False):
            return True
        return bool(getattr(current_user, "is_system_account", False) or getattr(current_user, "username", "") == "__OWNER__")
    except Exception:
        return False


def is_admin() -> bool:
    try:
        if _match_user(
            current_user,
            current_app.config.get("ADMIN_USER_IDS"),
            current_app.config.get("ADMIN_USER_EMAILS"),
        ):
            return True
    except Exception:
        pass
    try:
        if not getattr(current_user, "is_authenticated", False):
            return False
        if getattr(current_user, "is_system_account", False) or getattr(current_user, "username", "") == "__OWNER__":
            return True
        fn = getattr(current_user, "has_permission", None)
        if callable(fn):
            return bool(fn("manage_users") or fn("manage_permissions"))
        return False
    except Exception:
        return False


def super_only(f):
    @wraps(f)
    def _w(*args, **kwargs):
        if not is_super():
            abort(403)
        return f(*args, **kwargs)
    return _w


def admin_or_super(f):
    @wraps(f)
    def _w(*args, **kwargs):
        if not (is_admin() or is_super()):
            abort(403)
        return f(*args, **kwargs)
    return _w


def permission_required(*permission_names):
    base_needed = {str(p).strip().lower() for p in permission_names if p}

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                cfg = getattr(current_app, "config", {})
            except Exception:
                cfg = {}
            if cfg.get("PERMISSION_DISABLED") or cfg.get("LOGIN_DISABLED"):
                return f(*args, **kwargs)
            if is_super():
                return f(*args, **kwargs)
            if not getattr(current_user, "is_authenticated", False):
                return current_app.login_manager.unauthorized()
            if hasattr(current_user, "__tablename__") and current_user.__tablename__ == "customers":
                return f(*args, **kwargs)
            needed = set(base_needed)
            if needed:
                try:
                    needed = {str(x).lower() for x in _expand_perms(*needed)}
                except Exception:
                    needed = {str(x).lower() for x in needed}
            if not needed:
                return f(*args, **kwargs)
            try:
                user_perms = _get_user_permissions(current_user) or set()
            except Exception:
                user_perms = set()
            require_all = bool(cfg.get("PERMISSIONS_REQUIRE_ALL"))
            allowed = needed.issubset(user_perms) if require_all else bool(user_perms & needed or needed.issubset(user_perms))
            if allowed:
                return f(*args, **kwargs)
            if hasattr(current_user, "has_permission") and callable(getattr(current_user, "has_permission")):
                if require_all:
                    if all(current_user.has_permission(p) for p in needed):
                        return f(*args, **kwargs)
                else:
                    for p in needed:
                        if current_user.has_permission(p):
                            return f(*args, **kwargs)
            abort(403)
        return wrapped
    return decorator


def clear_user_permission_cache(user_id: int) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(f"user_permissions:{user_id}")
    except Exception:
        pass


def clear_role_permission_cache(role_id: int) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(f"role_permissions:{role_id}")
    except Exception:
        pass


def clear_users_cache_by_role(role_id: int):
    if not redis_client:
        return
    try:
        from models import User
        ids = [uid for (uid,) in db.session.query(User.id).filter(User.role_id == role_id).all()]
        for uid in ids:
            try:
                redis_client.delete(f"user_permissions:{uid}")
            except Exception:
                pass
    except Exception:
        pass


def get_role_permissions(role) -> set:
    if not role:
        return set()
    key = f"role_permissions:{role.id}"
    rc = redis_client
    if rc:
        try:
            cached = rc.smembers(key)
            if cached:
                return {str(x).lower() for x in cached}
        except Exception:
            pass
    perms = set()
    for p in _iter_rel(getattr(role, "permissions", [])):
        name = getattr(p, "code", None) or getattr(p, "name", None)
        if name:
            perms.add(str(name).lower())
    try:
        if rc:
            rc.delete(key)
            if perms:
                rc.sadd(key, *list(perms))
            rc.expire(key, 300)
    except Exception:
        pass
    return perms


def _install_acl_cache_listeners():
    global _ACL_CACHE_LISTENERS_INSTALLED
    if _ACL_CACHE_LISTENERS_INSTALLED:
        return
    try:
        from sqlalchemy import event
        from models import Role, User
    except Exception:
        return
    _ACL_CACHE_LISTENERS_INSTALLED = True

    def _role_perm_change(target, value, initiator):
        try:
            if getattr(target, "id", None) is not None:
                clear_role_permission_cache(target.id)
                clear_users_cache_by_role(target.id)
        except Exception:
            pass
        return value

    def _user_extra_perm_change(target, value, initiator):
        try:
            if getattr(target, "id", None) is not None:
                clear_user_permission_cache(target.id)
        except Exception:
            pass
        return value

    def _user_role_set(target, value, oldvalue, initiator):
        try:
            if getattr(target, "id", None) is not None:
                clear_user_permission_cache(target.id)
        except Exception:
            pass
        try:
            if getattr(oldvalue, "id", None):
                clear_users_cache_by_role(oldvalue.id)
            if getattr(value, "id", None):
                clear_users_cache_by_role(value.id)
        except Exception:
            pass
        return value

    try:
        event.listen(Role.permissions, "append", _role_perm_change)
        event.listen(Role.permissions, "remove", _role_perm_change)
    except Exception:
        pass

    try:
        event.listen(User.extra_permissions, "append", _user_extra_perm_change)
        event.listen(User.extra_permissions, "remove", _user_extra_perm_change)
        event.listen(User.role, "set", _user_role_set, retval=True)
    except Exception:
        pass


def log_customer_action(cust, action: str, old_data: Optional[dict] = None, new_data: Optional[dict] = None) -> None:
    from models import AuditLog

    old_json = json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None
    new_json = json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None
    entry = AuditLog(
        created_at=datetime.now(timezone.utc),
        model_name="Customer",
        customer_id=cust.id,
        record_id=cust.id,
        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
        action=action,
        old_data=old_json,
        new_data=new_json,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(entry)
    db.session.flush()


def _audit(event: str, *, ok: bool = True, user_id=None, customer_id=None, note: Optional[str] = None, extra: Optional[dict] = None) -> None:
    """
    SECURITY: تسجيل آمن - تنظيف البيانات الحساسة من Logs
    """
    from models import AuditLog
    import re
    
    # SECURITY: تنظيف note من البيانات الحساسة
    if note:
        note = str(note)
        # إزالة كلمات المرور
        note = re.sub(r'(password|pwd|pass)[=:\s]+\S+', r'\1=***', note, flags=re.IGNORECASE)
        # إزالة tokens
        note = re.sub(r'(token|auth|bearer)[=:\s]+\S+', r'\1=***', note, flags=re.IGNORECASE)
        # إزالة API keys
        note = re.sub(r'(api[_-]?key|secret)[=:\s]+\S+', r'\1=***', note, flags=re.IGNORECASE)
        # إزالة أرقام البطاقات (16 رقم)
        note = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '****-****-****-****', note)
        # تحديد الطول
        if len(note) > 500:
            note = note[:497] + '...'
    
    # SECURITY: تنظيف extra من البيانات الحساسة
    if extra:
        extra_clean = {}
        for key, val in extra.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in ['password', 'token', 'secret', 'api_key', 'card', 'cvv', 'pin']):
                extra_clean[key] = '***'
            else:
                extra_clean[key] = val
        extra = extra_clean

    details_old = {"ok": bool(ok)}
    if note:
        details_old["note"] = note
    record_id = int(customer_id) if customer_id is not None else (int(user_id) if user_id is not None else None)
    old_json = json.dumps(details_old, ensure_ascii=False, default=str) if details_old else None
    new_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None
    try:
        entry = AuditLog(
            created_at=datetime.now(timezone.utc),
            model_name="Auth",
            record_id=record_id,
            user_id=(user_id if user_id is not None else (getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None)),
            action=str(event),
            old_data=old_json,
            new_data=new_json,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
        db.session.add(entry)
        db.session.flush()
    except Exception as e:
        # تجاهل أخطاء audit لعدم تعطيل النظام
        db.session.rollback()
        import logging
        logging.warning(f"Audit log failed: {e}")


def log_audit(model_name: str, record_id: int, action: str, old_data: Optional[dict] = None, new_data: Optional[dict] = None):
    from models import AuditLog

    old_json = json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None
    new_json = json.dumps(new_data, ensure_ascii=False, default=str) if new_data else None
    entry = AuditLog(
        created_at=datetime.now(timezone.utc),
        model_name=model_name,
        record_id=record_id,
        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
        action=action,
        old_data=old_json,
        new_data=new_json,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(entry)
    db.session.flush()


_ENUM_AR = {
    "PaymentMethod": {"cash": "نقداً", "bank": "تحويل", "card": "بطاقة", "cheque": "شيك", "online": "إلكتروني"},
    "PaymentStatus": {"PENDING": "قيد الانتظار", "COMPLETED": "مكتملة", "FAILED": "فاشلة", "REFUNDED": "مُرجعة"},
    "PaymentDirection": {"IN": "وارد", "OUT": "صادر"},
    "PaymentEntityType": {
        "CUSTOMER": "عميل", "SUPPLIER": "مورد", "PARTNER": "شريك", "SHIPMENT": "شحنة",
        "EXPENSE": "مصروف", "LOAN": "قرض", "SALE": "بيع", "INVOICE": "فاتورة",
        "PREORDER": "حجز", "SERVICE": "صيانة"
    },
}


def _enum_choices(enum_cls, arabic_labels: bool = True):
    if not arabic_labels:
        return [(e.value, e.value) for e in enum_cls]
    lab = _ENUM_AR.get(enum_cls.__name__, {})
    return [(e.value, lab.get(e.value, e.value)) for e in enum_cls]


def prepare_payment_form_choices(form, *, compat_post: bool = False, arabic_labels: bool = True):
    from models import PaymentMethod, PaymentStatus, PaymentDirection, PaymentEntityType

    if hasattr(form, "currency"):
        form.currency.choices = (
            [("ILS", "شيكل إسرائيلي"), ("USD", "دولار أمريكي"), ("EUR", "يورو"), ("JOD", "دينار أردني"), ("AED", "درهم إماراتي"), ("SAR", "ريال سعودي"), ("EGP", "جنيه مصري"), ("GBP", "جنيه إسترليني")]
            if arabic_labels else [("ILS", "ILS"), ("USD", "USD"), ("EUR", "EUR"), ("JOD", "JOD"), ("AED", "AED"), ("SAR", "SAR"), ("EGP", "EGP"), ("GBP", "GBP")]
        )
    if hasattr(form, "method"):
        form.method.choices = _enum_choices(PaymentMethod, arabic_labels)
    if hasattr(form, "status"):
        form.status.choices = _enum_choices(PaymentStatus, arabic_labels)
    if hasattr(form, "direction"):
        # 👈 فقط قيم enum: "IN"/"OUT"
        form.direction.choices = _enum_choices(PaymentDirection, arabic_labels)
    if hasattr(form, "entity_type"):
        form.entity_type.choices = _enum_choices(PaymentEntityType, arabic_labels)

def update_entity_balance(entity: str, eid: int) -> float:
    entity = entity.upper()
    try:
        if entity == "SUPPLIER":
            from sqlalchemy.orm import sessionmaker
            from helpers.balance_events import emit_balance_update
            from models import Supplier
            from utils.supplier_balance_updater import update_supplier_balance_components
            SessionFactory = sessionmaker(bind=db.engine)
            session = SessionFactory()
            try:
                update_supplier_balance_components(eid, session, emit=False)
                session.commit()
                supplier = session.get(Supplier, eid)
                balance = float(supplier.current_balance or 0) if supplier else 0.0
            except Exception:
                try:
                    session.rollback()
                except Exception:
                    pass
                return 0.0
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            try:
                emit_balance_update("supplier", eid, balance)
            except Exception:
                pass
            return balance
        elif entity == "CUSTOMER":
            from utils.customer_balance_updater import update_customer_balance_components
            from models import Customer
            update_customer_balance_components(eid)
            customer = db.session.get(Customer, eid)
            return float(customer.current_balance or 0) if customer else 0.0
        elif entity == "PARTNER":
            from sqlalchemy.orm import sessionmaker
            from helpers.balance_events import emit_balance_update
            from models import Partner
            from utils.partner_balance_updater import update_partner_balance_components
            SessionFactory = sessionmaker(bind=db.engine)
            session = SessionFactory()
            try:
                update_partner_balance_components(eid, session, emit=False)
                session.commit()
                partner = session.get(Partner, eid)
                balance = float(partner.current_balance or 0) if partner else 0.0
            except Exception:
                try:
                    session.rollback()
                except Exception:
                    pass
                return 0.0
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            try:
                emit_balance_update("partner", eid, balance)
            except Exception:
                pass
            return balance
        return 0.0
    except Exception:
        return 0.0


def customer_required(f):
    @login_required
    @wraps(f)
    def wrapper(*args, **kwargs):
        from models import Customer
        if not isinstance(current_user, Customer):
            abort(403)
        if "place_online_order" not in _get_user_permissions(current_user):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def luhn_check(card_number: str) -> bool:
    if not card_number:
        return False
    digits = "".join(ch for ch in card_number if ch.isdigit())
    if not digits:
        return False
    s, alt = 0, False
    for d in digits[::-1]:
        n = ord(d) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return (s % 10) == 0


def is_valid_ean13(code: str) -> bool:
    if not code or len(code) != 13 or not code.isdigit():
        return False
    digits = [int(d) for d in code]
    checksum = (10 - ((sum(digits[::2]) + sum(d * 3 for d in digits[1:-1:2])) % 10)) % 10
    return checksum == digits[-1]


def is_valid_expiry_mm_yy(s: str) -> bool:
    if not s or not re.match(r"^\d{2}/\d{2}$", s):
        return False
    mm_str, yy_str = s.split("/")
    try:
        mm = int(mm_str)
        yy = int("20" + yy_str)
        if not (1 <= mm <= 12):
            return False
        now = datetime.now(timezone.utc)
        y, m = now.year, now.month
        return (yy > y) or (yy == y and mm >= m)
    except Exception:
        return False


def get_fernet():
    key = current_app.config.get("CARD_ENC_KEY")
    if not key or Fernet is None:
        return None
    if isinstance(key, str):
        key = key.encode("utf-8")
    try:
        return Fernet(key)
    except Exception:
        return None


def encrypt_card_number(pan: str) -> Optional[bytes]:
    f = get_fernet()
    if not f:
        return None
    digits = "".join(ch for ch in (pan or "") if ch.isdigit())
    if not digits:
        return None
    return f.encrypt(digits.encode("utf-8"))


def decrypt_card_number(token: bytes) -> Optional[str]:
    f = get_fernet()
    if not f or not token:
        return None
    try:
        return f.decrypt(token).decode("utf-8")
    except Exception:
        return None


def card_fingerprint(pan: str) -> Optional[str]:
    digits = "".join(ch for ch in (pan or "") if ch.isdigit())
    if not digits:
        return None
    return hashlib.sha256(digits.encode("utf-8")).hexdigest()


def detect_card_brand(pan: str) -> str:
    digits = "".join(ch for ch in (pan or "") if ch.isdigit())
    if not digits:
        return "UNKNOWN"
    if digits.startswith("4"):
        return "VISA"
    i2 = int(digits[:2]) if len(digits) >= 2 else -1
    i4 = int(digits[:4]) if len(digits) >= 4 else -1
    if 51 <= i2 <= 55 or (2221 <= i4 <= 2720):
        return "MASTERCARD"
    if i2 in (34, 37):
        return "AMEX"
    return "UNKNOWN"


def _install_accounting_listeners():
    global _ACCOUNTING_LISTENERS_INSTALLED
    if _ACCOUNTING_LISTENERS_INSTALLED:
        return
    try:
        from sqlalchemy import event
        from sqlalchemy.orm import object_session
        from models import Payment, PaymentStatus, Sale, SaleLine
        Q = Decimal("0.01")
    except Exception:
        return
    _ACCOUNTING_LISTENERS_INSTALLED = True

    def _q2_local(x):
        try:
            return Decimal(str(x or 0)).quantize(Q, rounding=ROUND_HALF_UP)
        except Exception:
            return Decimal("0.00")

    def _recompute_sale_totals(sess, sale_id: int):
        sale = sess.get(Sale, sale_id)
        if not sale:
            return
        subtotal = Decimal("0.00")
        for ln in sale.lines or []:
            qv = _q2_local(ln.quantity)
            pv = _q2_local(ln.unit_price)
            dr = _q2_local(ln.discount_rate)
            base = (qv * pv * (Decimal("1") - dr / Decimal("100"))).quantize(Q, rounding=ROUND_HALF_UP)
            subtotal += base
        discount = _q2_local(getattr(sale, "discount_total", 0) or 0)
        shipping = _q2_local(getattr(sale, "shipping_cost", 0) or 0)
        tax_rate = _q2_local(getattr(sale, "tax_rate", 0) or 0)
        base_for_tax = (subtotal - discount + shipping)
        if base_for_tax < Decimal("0"):
            base_for_tax = Decimal("0")
        tax_amount = (base_for_tax * tax_rate / Decimal("100")).quantize(Q, rounding=ROUND_HALF_UP)
        total = (base_for_tax + tax_amount).quantize(Q, rounding=ROUND_HALF_UP)
        set_committed_value(sale, "total_amount", float(total))
        # تحديث المتبقي فوراً لضمان الاتساق في الواجهة
        current_paid = _q2_local(getattr(sale, "total_paid", 0) or 0)
        balance_due = float((total - current_paid).quantize(Q, rounding=ROUND_HALF_UP))
        set_committed_value(sale, "balance_due", balance_due)

    def _recompute_sale_payments(sess, sale_id: int):
        sale = sess.get(Sale, sale_id)
        if not sale:
            return
        paid = Decimal("0.00")
        sale_curr = (getattr(sale, "currency", None) or DEFAULT_CURRENCY).upper()
        from models import convert_amount as _convert_amount
        for p in sale.payments or []:
            if getattr(p, "status", None) == PaymentStatus.COMPLETED.value:
                splits = getattr(p, "splits", None) or []
                if splits:
                    split_sum = Decimal("0.00")
                    for s in splits:
                        amt = _q2_local(getattr(s, "converted_amount", None) or 0)
                        cur = (getattr(s, "converted_currency", None) or getattr(s, "currency", None) or getattr(p, "currency", None) or sale_curr).upper()
                        if amt <= 0:
                            amt = _q2_local(getattr(s, "amount", 0) or 0)
                            cur = (getattr(s, "currency", None) or getattr(p, "currency", None) or sale_curr).upper()
                        if cur != sale_curr:
                            try:
                                amt = _q2_local(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None)))
                            except Exception:
                                pass
                        split_sum += amt
                    paid += split_sum
                else:
                    amt = _q2_local(getattr(p, "total_amount", 0) or 0)
                    cur = (getattr(p, "currency", None) or sale_curr).upper()
                    if cur != sale_curr:
                        try:
                            amt = _q2_local(_convert_amount(amt, cur, sale_curr, getattr(p, "payment_date", None)))
                        except Exception:
                            pass
                    paid += amt
        total_paid = float(paid.quantize(Q, rounding=ROUND_HALF_UP))
        balance_due = float((_q2_local(sale.total_amount) - paid).quantize(Q, rounding=ROUND_HALF_UP))
        set_committed_value(sale, "total_paid", total_paid)
        set_committed_value(sale, "balance_due", balance_due)
        if hasattr(sale, "update_payment_status"):
            try:
                sale.update_payment_status()
            except Exception:
                pass

    @event.listens_for(Payment, "after_insert")
    @event.listens_for(Payment, "after_update")
    def _pmt_upd(mapper, conn, target):
        sess = object_session(target)
        if not sess or not getattr(target, "sale_id", None):
            return
        _recompute_sale_payments(sess, int(target.sale_id))

    @event.listens_for(Payment, "after_delete")
    def _pmt_del(mapper, conn, target):
        sess = object_session(target)
        if not sess or not getattr(target, "sale_id", None):
            return
        _recompute_sale_payments(sess, int(target.sale_id))

    @event.listens_for(SaleLine, "after_insert")
    @event.listens_for(SaleLine, "after_update")
    @event.listens_for(SaleLine, "after_delete")
    def _line_changed(mapper, conn, target):
        sess = object_session(target)
        if not sess or not getattr(target, "sale_id", None):
            return
        _recompute_sale_totals(sess, int(target.sale_id))


def archive_record(record, reason=None, user_id=None):
    """أرشفة سجل"""
    from datetime import datetime
    from flask import flash
    from flask_login import current_user
    from sqlalchemy.exc import SQLAlchemyError
    from extensions import db
    from models import Archive
    
    try:
        if user_id is None and current_user and current_user.is_authenticated:
            user_id = current_user.id
        
        archive = Archive.archive_record(
            record=record,
            reason=reason or 'أرشفة تلقائية',
            user_id=user_id
        )
        
        record.is_archived = True
        record.archived_at = datetime.now(timezone.utc)
        record.archived_by = user_id
        record.archive_reason = reason or 'أرشفة تلقائية'
        
        db.session.commit()
        return archive
        
    except SQLAlchemyError as e:
        db.session.rollback()
        raise e

def restore_record(archive_id):
    """استعادة سجل من الأرشيف"""
    from sqlalchemy.exc import SQLAlchemyError
    from extensions import db
    from models import Archive
    import json
    
    try:
        archive = db.get_or_404(Archive, archive_id)
        
        model_map = {
            'service_requests': 'ServiceRequest',
            'payments': 'Payment', 
            'sales': 'Sale',
            'expenses': 'Expense',
            'checks': 'Check',
            'customers': 'Customer',
            'suppliers': 'Supplier',
            'partners': 'Partner',
            'shipments': 'Shipment'
        }
        
        model_name = model_map.get(archive.record_type)
        if not model_name:
            raise ValueError(f'نوع السجل غير مدعوم للاستعادة: {archive.record_type}')
        
        from models import ServiceRequest as ServiceRequest, Payment, Sale, Expense, Check, Customer, Supplier, Partner, Shipment
        model_map_actual = {
            'ServiceRequest': ServiceRequest,
            'Payment': Payment,
            'Sale': Sale, 
            'Expense': Expense,
            'Check': Check,
            'Customer': Customer,
            'Supplier': Supplier,
            'Partner': Partner,
            'Shipment': Shipment
        }
        
        model_class = model_map_actual.get(model_name)
        if not model_class:
            raise ValueError(f'نموذج غير موجود: {model_name}')
        
        original_record = db.session.get(model_class, archive.record_id)
        
        if original_record:
            original_record.is_archived = False
            original_record.archived_at = None
            original_record.archived_by = None
            original_record.archive_reason = None
            
            db.session.delete(archive)
            db.session.commit()
            
            return original_record
        else:
            archived_data = json.loads(archive.archived_data)
            
            new_record = model_class()
            for key, value in archived_data.items():
                if hasattr(new_record, key) and key not in ['id', 'is_archived', 'archived_at', 'archived_by', 'archive_reason']:
                    # تحويل التواريخ من string إلى datetime
                    if value and isinstance(value, str) and ('_at' in key or 'date' in key.lower() or '_time' in key):
                        try:
                            # محاولة تحويل التاريخ
                            if 'T' in value:  # ISO format
                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            else:
                                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                        except (ValueError, AttributeError):
                            # إذا فشل التحويل، حاول تنسيق آخر
                            try:
                                value = datetime.strptime(value, '%Y-%m-%d')
                            except (ValueError, AttributeError):
                                pass  # اترك القيمة كما هي
                    
                    setattr(new_record, key, value)
            
            db.session.add(new_record)
            db.session.flush()
            
            db.session.delete(archive)
            db.session.commit()
            
            return new_record
            
    except SQLAlchemyError as e:
        db.session.rollback()
        raise e



# Calculation utilities
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWOPLACES = Decimal("0.01")
ZERO_PLACES = Decimal("1")

def D(x):
    """Convert to Decimal safely"""
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

def q0(x):
    """Quantize to zero decimal places"""
    return D(x).quantize(ZERO_PLACES, rounding=ROUND_HALF_UP)

def q2(x):
    """Quantize to two decimal places"""
    return D(x).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

def _q2(x):
    """Quantize to two decimal places and return as float"""
    return float(q2(x))

def money_fmt(value):
    """Format money with thousand separators"""
    v = value if isinstance(value, Decimal) else D(value or 0)
    return f"{v:,.2f}"

def line_total_decimal(qty, unit_price, discount_rate):
    """Calculate line total with discount"""
    q = D(qty)
    p = D(unit_price)
    dr = D(discount_rate or 0)
    one = Decimal("1")
    hundred = Decimal("100")
    total = q * p * (one - dr / hundred)
    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

def safe_divide(numerator, denominator, default=Decimal("0")):
    """Safe division returning default if denominator is zero"""
    num = D(numerator)
    den = D(denominator)
    if den == 0:
        return D(default)
    return (num / den).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

def calculate_percentage(part, total):
    """Calculate percentage"""
    if D(total) == 0:
        return Decimal("0")
    return (D(part) / D(total) * 100).quantize(TWOPLACES, rounding=ROUND_HALF_UP)



def get_archive_stats():
    """Get archive statistics"""
    from sqlalchemy import func
    from datetime import datetime
    from extensions import db
    from models import Archive
    
    total_archives = Archive.query.count()
    
    type_stats = db.session.query(
        Archive.record_type,
        func.count(Archive.id).label('count')
    ).group_by(Archive.record_type).all()
    
    current_month = datetime.now().replace(day=1)
    monthly_archives = Archive.query.filter(
        Archive.archived_at >= current_month
    ).count()
    
    return {
        'total_archives': total_archives,
        'type_stats': type_stats,
        'monthly_archives': monthly_archives
    }


# ==================== تحسينات بسيطة ====================

class SimpleCache:
    """تخزين مؤقت بسيط في الذاكرة"""
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
    
    def get(self, key):
        if key in self._cache:
            if datetime.now() < self._timestamps.get(key, datetime.now()):
                return self._cache[key]
            self.delete(key)
        return None
    
    def set(self, key, value, timeout=300):
        self._cache[key] = value
        self._timestamps[key] = datetime.now() + timedelta(seconds=timeout)
    
    def delete(self, key):
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

simple_cache = SimpleCache()


def cache_result(timeout=300):
    """Decorator للتخزين المؤقت"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cache_key = f"{f.__name__}:{hash(str(args) + str(kwargs))}"
            result = simple_cache.get(cache_key)
            if result is None:
                result = f(*args, **kwargs)
                simple_cache.set(cache_key, result, timeout)
            return result
        return wrapper
    return decorator


# ========================================================================
# System Constants Helpers
# ========================================================================

def get_system_constant(key: str, default: Any = None) -> Any:
    """
    الحصول على ثابت من إعدادات النظام
    
    Args:
        key: مفتاح الثابت (مثال: 'default_vat_rate')
        default: القيمة الافتراضية إذا لم يتم إيجاد الثابت
    
    Returns:
        قيمة الثابت
    
    Examples:
        >>> get_system_constant('default_vat_rate', 16.0)
        16.0
        >>> get_system_constant('vat_enabled', True)
        True
    """
    try:
        from models import SystemSettings
        return SystemSettings.get_setting(key, default)
    except Exception as e:
        current_app.logger.warning(f"⚠️ فشل جلب الثابت {key}: {e}")
        return default


BUSINESS_GROUP_DEFAULTS = {
    'tax': True,
    'payroll': True,
    'assets': True,
    'accounting': True,
    'notifications': True,
    'business_rules': True,
    'multi_tenancy': True,
}


def is_business_group_enabled(group: str, default: bool = None) -> bool:
    """التحقق من تفعيل مجموعة ثوابت معينة"""
    if default is None:
        default = BUSINESS_GROUP_DEFAULTS.get(group, True)
    return bool(get_system_constant(f'enable_{group}_constants', default))


def get_vat_rate() -> float:
    """الحصول على نسبة VAT الافتراضية من إعدادات النظام"""
    default = 0.0
    if not is_business_group_enabled('tax'):
        return default
    return float(get_system_constant('default_vat_rate', default))


def is_vat_enabled() -> bool:
    """التحقق من تفعيل VAT في النظام"""
    if not is_business_group_enabled('tax'):
        return False
    return bool(get_system_constant('vat_enabled', False))


def get_income_tax_rate() -> float:
    """نسبة ضريبة الدخل على الشركات"""
    default = 15.0
    if not is_business_group_enabled('tax'):
        return default
    return float(get_system_constant('income_tax_rate', default))


def get_withholding_tax_rate() -> float:
    """نسبة الخصم من المنبع"""
    default = 5.0
    if not is_business_group_enabled('tax'):
        return default
    return float(get_system_constant('withholding_tax_rate', default))


def get_social_insurance_rates() -> dict:
    """نسب التأمينات الاجتماعية"""
    group_enabled = is_business_group_enabled('payroll')
    if not group_enabled:
        return {
            'enabled': False,
            'company_rate': 7.5,
            'employee_rate': 7.0
        }
    return {
        'enabled': group_enabled and bool(get_system_constant('social_insurance_enabled', False)),
        'company_rate': float(get_system_constant('social_insurance_company', 7.5)),
        'employee_rate': float(get_system_constant('social_insurance_employee', 7.0))
    }


def get_overtime_rate() -> float:
    """معدل العمل الإضافي"""
    default = 1.5
    if not is_business_group_enabled('payroll'):
        return default
    return float(get_system_constant('overtime_rate_normal', default))


def get_working_hours_per_day() -> int:
    """ساعات العمل اليومية"""
    default = 8
    if not is_business_group_enabled('payroll'):
        return default
    return int(get_system_constant('working_hours_per_day', default))


def calculate_vat_amount(base_amount: float, vat_rate: Optional[float] = None) -> dict:
    """
    حساب ضريبة VAT
    
    Args:
        base_amount: المبلغ الأساسي (قبل الضريبة)
        vat_rate: نسبة VAT (اختياري، يستخدم من الإعدادات إذا لم يُحدد)
    
    Returns:
        dict: {
            'base_amount': المبلغ الأساسي,
            'vat_rate': نسبة VAT,
            'vat_amount': مبلغ الضريبة,
            'total_with_vat': المجموع شامل الضريبة
        }
    """
    if not is_vat_enabled():
        return {
            'base_amount': base_amount,
            'vat_rate': 0.0,
            'vat_amount': 0.0,
            'total_with_vat': base_amount
        }
    
    if vat_rate is None:
        vat_rate = get_vat_rate()
    
    vat_amount = base_amount * (vat_rate / 100.0)
    total_with_vat = base_amount + vat_amount
    
    return {
        'base_amount': round(base_amount, 2),
        'vat_rate': vat_rate,
        'vat_amount': round(vat_amount, 2),
        'total_with_vat': round(total_with_vat, 2)
    }


def get_all_business_constants() -> dict:
    """الحصول على جميع ثوابت الأعمال"""
    tax_enabled = is_business_group_enabled('tax')
    payroll_enabled = is_business_group_enabled('payroll')
    assets_enabled = is_business_group_enabled('assets')
    accounting_enabled = is_business_group_enabled('accounting')
    notifications_enabled = is_business_group_enabled('notifications')
    rules_enabled = is_business_group_enabled('business_rules')
    tenancy_enabled = is_business_group_enabled('multi_tenancy', False)
    
    payroll_constants = get_social_insurance_rates()
    
    return {
        # Tax
        'tax': {
            'group_enabled': tax_enabled,
            'default_vat_rate': get_vat_rate(),
            'vat_enabled': is_vat_enabled(),
            'income_tax_rate': get_income_tax_rate(),
            'withholding_tax_rate': get_withholding_tax_rate()
        },
        # Payroll
        'payroll': payroll_constants | {
            'group_enabled': payroll_enabled,
            'overtime_rate': get_overtime_rate(),
            'working_hours_per_day': get_working_hours_per_day()
        },
        # Assets
        'assets': {
            'group_enabled': assets_enabled,
            'auto_depreciation': bool(get_system_constant('asset_auto_depreciation', True)) if assets_enabled else False,
            'threshold_amount': float(get_system_constant('asset_threshold_amount', 500))
        },
        # Accounting
        'accounting': {
            'group_enabled': accounting_enabled,
            'cost_centers_enabled': bool(get_system_constant('cost_centers_enabled', False)) if accounting_enabled else False,
            'budgeting_enabled': bool(get_system_constant('budgeting_enabled', False)) if accounting_enabled else False,
            'fiscal_year_start_month': int(get_system_constant('fiscal_year_start_month', 1))
        },
        # Notifications
        'notifications': {
            'group_enabled': notifications_enabled,
            'service_complete': bool(get_system_constant('notify_on_service_complete', True)) if notifications_enabled else False,
            'payment_due': bool(get_system_constant('notify_on_payment_due', True)) if notifications_enabled else False,
            'low_stock': bool(get_system_constant('notify_on_low_stock', True)) if notifications_enabled else False,
            'payment_reminder_days': int(get_system_constant('payment_reminder_days', 3))
        },
        # Business Rules
        'business_rules': {
            'group_enabled': rules_enabled,
            'allow_negative_stock': bool(get_system_constant('allow_negative_stock', False)) if rules_enabled else False,
            'require_approval_above': float(get_system_constant('require_approval_for_sales_above', 10000)),
            'discount_max_percent': float(get_system_constant('discount_max_percent', 50)),
            'credit_limit_check': bool(get_system_constant('credit_limit_check', True)) if rules_enabled else False
        },
        # Multi-Tenancy
        'multi_tenancy': {
            'group_enabled': tenancy_enabled,
            'enabled': bool(get_system_constant('multi_tenancy_enabled', False)) if tenancy_enabled else False,
            'trial_period_days': int(get_system_constant('trial_period_days', 30))
        }
    }


# ========================================================================
# Notifications System - نظام الإشعارات
# ========================================================================

def send_notification_sms(to: str, message: str, metadata: dict = None) -> dict:
    """
    إرسال SMS عبر Twilio
    
    Args:
        to: رقم الهاتف مع كود الدولة (+970...)
        message: نص الرسالة
        metadata: بيانات إضافية (customer_id, invoice_id, etc)
    
    Returns:
        dict: {'success': bool, 'message_sid': str, 'error': str}
    
    Example:
        >>> send_notification_sms('+970562150193', 'تم إتمام الخدمة')
        {'success': True, 'message_sid': 'SM...'}
    """
    from models import NotificationLog, db
    from datetime import datetime, timezone
    
    # التحقق من إعدادات Twilio
    account_sid = get_system_constant('twilio_account_sid', '')
    auth_token = get_system_constant('twilio_auth_token', '')
    from_number = get_system_constant('twilio_phone_number', '')
    
    if not all([account_sid, auth_token, from_number]):
        current_app.logger.warning('⚠️ Twilio not configured')
        return {'success': False, 'error': 'Twilio not configured'}
    
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        
        # إرسال الرسالة
        twilio_msg = client.messages.create(
            body=message,
            from_=from_number,
            to=to
        )
        
        # تسجيل في قاعدة البيانات
        log = NotificationLog(
            type='sms',
            recipient=to,
            content=message[:500],
            status='sent',
            provider_id=twilio_msg.sid,
            sent_at=datetime.now(timezone.utc)
        )
        if metadata:
            log.data = metadata
        
        db.session.add(log)
        db.session.commit()
        
        current_app.logger.info(f'✅ SMS sent to {to}')
        return {
            'success': True,
            'message_sid': twilio_msg.sid,
            'status': twilio_msg.status
        }
        
    except ImportError:
        error = 'Twilio library not installed. Run: pip install twilio'
        current_app.logger.error(f'❌ {error}')
        return {'success': False, 'error': error}
    except Exception as e:
        current_app.logger.error(f'❌ SMS failed to {to}: {e}')
        
        # تسجيل الفشل
        log = NotificationLog(
            type='sms',
            recipient=to,
            content=message[:500],
            status='failed',
            error_message=str(e)
        )
        if metadata:
            log.data = metadata
        
        db.session.add(log)
        db.session.commit()
        
        return {'success': False, 'error': str(e)}


def send_notification_email(
    to: str,
    subject: str,
    body_html: str = None,
    body_text: str = None,
    metadata: dict = None
) -> dict:
    """
    إرسال Email عبر Flask-Mail
    
    Args:
        to: البريد الإلكتروني
        subject: الموضوع
        body_html: محتوى HTML
        body_text: محتوى نصي (fallback)
        metadata: بيانات إضافية
    
    Returns:
        dict: {'success': bool, 'error': str}
    
    Example:
        >>> send_notification_email(
        ...     'customer@example.com',
        ...     'تم إتمام الخدمة',
        ...     body_html='<h1>شكراً</h1>'
        ... )
        {'success': True}
    """
    from models import NotificationLog, db
    from flask_mail import Message
    from extensions import mail
    from datetime import datetime, timezone
    
    try:
        msg = Message(
            subject=subject,
            recipients=[to],
            html=body_html,
            body=body_text
        )
        
        mail.send(msg)
        
        # تسجيل النجاح
        log = NotificationLog(
            type='email',
            recipient=to,
            subject=subject,
            content=(body_html or body_text or '')[:500],
            status='sent',
            sent_at=datetime.now(timezone.utc)
        )
        if metadata:
            log.data = metadata
        
        db.session.add(log)
        db.session.commit()
        
        current_app.logger.info(f'✅ Email sent to {to}')
        return {'success': True}
        
    except Exception as e:
        current_app.logger.error(f'❌ Email failed to {to}: {e}')
        
        # تسجيل الفشل
        log = NotificationLog(
            type='email',
            recipient=to,
            subject=subject,
            content=(body_html or body_text or '')[:500],
            status='failed',
            error_message=str(e)
        )
        if metadata:
            log.data = metadata
        
        db.session.add(log)
        db.session.commit()
        
        return {'success': False, 'error': str(e)}


def notify_service_completed(service_id: int) -> dict:
    """
    إشعار تلقائي عند إتمام خدمة
    
    يستخدم الثابت: notify_on_service_complete
    
    Args:
        service_id: رقم الخدمة
    
    Returns:
        dict: نتيجة الإرسال
    """
    from models import ServiceRequest as Service
    
    # التحقق من التفعيل
    if not is_business_group_enabled('notifications') or not get_system_constant('notify_on_service_complete', True):
        return {'success': False, 'reason': 'Notifications disabled'}
    
    try:
        service = db.session.get(Service, service_id)
        if not service or not service.customer:
            return {'success': False, 'error': 'Service or customer not found'}
        
        customer = service.customer
        message = (
            f"✅ تم إتمام خدمة {service.reference}\n"
            f"المجموع: {service.total:.2f} ₪\n"
            f"شكراً لتعاملكم - AZAD Garage"
        )
        
        results = {}
        
        # SMS
        if customer.phone:
            results['sms'] = send_notification_sms(
                to=customer.phone,
                message=message,
                metadata={
                    'service_id': service_id,
                    'customer_id': customer.id,
                    'type': 'service_complete'
                }
            )
        
        # Email (إذا كان موجوداً)
        if customer.email:
            html = f"""
            <h2>✅ تم إتمام الخدمة</h2>
            <p>عزيزنا {customer.name}</p>
            <p>تم إتمام خدمة <strong>{service.reference}</strong></p>
            <p>المجموع: <strong>{service.total:.2f} ₪</strong></p>
            <br>
            <p>شكراً لتعاملكم معنا</p>
            <p>AZAD Garage</p>
            """
            
            results['email'] = send_notification_email(
                to=customer.email,
                subject=f'✅ تم إتمام خدمة {service.reference}',
                body_html=html,
                body_text=message,
                metadata={
                    'service_id': service_id,
                    'customer_id': customer.id,
                    'type': 'service_complete'
                }
            )
        
        return {'success': True, 'results': results}
        
    except Exception as e:
        current_app.logger.error(f'❌ notify_service_completed failed: {e}')
        return {'success': False, 'error': str(e)}


def notify_payment_reminder(days_before: int = None) -> dict:
    """
    إشعارات تذكير بالدفع
    
    يستخدم الثوابت:
    - notify_on_payment_due
    - payment_reminder_days
    
    Args:
        days_before: عدد الأيام قبل الاستحقاق (None = من الثوابت)
    
    Returns:
        dict: عدد الإشعارات المُرسلة
    """
    from models import Invoice
    from datetime import datetime, timedelta
    
    # التحقق من التفعيل
    if not is_business_group_enabled('notifications') or not get_system_constant('notify_on_payment_due', True):
        return {'success': False, 'reason': 'Notifications disabled'}
    
    try:
        # عدد الأيام
        if days_before is None:
            days_before = int(get_system_constant('payment_reminder_days', 3))
        
        # تاريخ الاستحقاق
        target_date = datetime.now().date() + timedelta(days=days_before)
        
        # الفواتير المستحقة
        invoices = Invoice.query.filter(
            Invoice.due_date == target_date,
            Invoice.balance_due > 0
        ).all()
        
        results = {
            'total': len(invoices),
            'sent': 0,
            'failed': 0
        }
        
        for invoice in invoices:
            if not invoice.customer:
                continue
            
            customer = invoice.customer
            message = (
                f"🔔 تذكير: الفاتورة {invoice.reference}\n"
                f"المبلغ المستحق: {invoice.balance_due:.2f} ₪\n"
                f"تاريخ الاستحقاق: {invoice.due_date}\n"
                f"AZAD Garage"
            )
            
            if customer.phone:
                result = send_notification_sms(
                    to=customer.phone,
                    message=message,
                    metadata={
                        'invoice_id': invoice.id,
                        'customer_id': customer.id,
                        'type': 'payment_reminder'
                    }
                )
                
                if result['success']:
                    results['sent'] += 1
                else:
                    results['failed'] += 1
        
        return {'success': True, **results}
        
    except Exception as e:
        current_app.logger.error(f'❌ notify_payment_reminder failed: {e}')
        return {'success': False, 'error': str(e)}


# ========================================================================
# Tax System - نظام الضرائب
# ========================================================================

def create_tax_entry(
    entry_type: str,
    transaction_type: str,
    transaction_id: int,
    base_amount: float,
    tax_rate: float = None,
    **kwargs
) -> dict:
    """
    إنشاء سجل ضريبة
    
    Args:
        entry_type: INPUT_VAT, OUTPUT_VAT, INCOME_TAX, WITHHOLDING
        transaction_type: SALE, PURCHASE, SERVICE, PAYMENT
        transaction_id: رقم المعاملة
        base_amount: المبلغ الأساسي
        tax_rate: نسبة الضريبة (None = من الثوابت)
        **kwargs: حقول إضافية
    
    Returns:
        dict: {'success': bool, 'tax_entry_id': int}
    
    Example:
        >>> create_tax_entry('OUTPUT_VAT', 'SALE', 123, 1000.0)
        {'success': True, 'tax_entry_id': 45}
    """
    from models import TaxEntry, db
    from datetime import datetime
    
    try:
        # نسبة الضريبة من الثوابت إذا لم تُحدد
        if tax_rate is None:
            tax_rate = get_vat_rate()
        
        # حساب الضريبة
        tax_amount = base_amount * (tax_rate / 100)
        total_amount = base_amount + tax_amount
        
        # التاريخ المالي
        now = datetime.now()
        
        # إنشاء السجل
        tax_entry = TaxEntry(
            entry_type=entry_type,
            transaction_type=transaction_type,
            transaction_id=transaction_id,
            transaction_reference=kwargs.get('reference'),
            tax_rate=tax_rate,
            base_amount=base_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            currency=kwargs.get('currency', DEFAULT_CURRENCY),
            fiscal_year=now.year,
            fiscal_month=now.month,
            tax_period=now.strftime('%Y-%m'),
            customer_id=kwargs.get('customer_id'),
            supplier_id=kwargs.get('supplier_id'),
            notes=kwargs.get('notes')
        )
        
        db.session.add(tax_entry)
        db.session.commit()
        
        current_app.logger.info(f'✅ Tax entry created: {entry_type} - {tax_amount} {tax_entry.currency}')
        
        return {
            'success': True,
            'tax_entry_id': tax_entry.id,
            'tax_amount': tax_amount,
            'total_amount': total_amount
        }
        
    except Exception as e:
        current_app.logger.error(f'❌ create_tax_entry failed: {e}')
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def get_tax_summary(period: str = None) -> dict:
    """
    ملخص الضرائب لفترة معينة
    
    Args:
        period: YYYY-MM (None = الشهر الحالي)
    
    Returns:
        dict: ملخص الضرائب
    
    Example:
        >>> get_tax_summary('2025-10')
        {
            'period': '2025-10',
            'input_vat': 1600.0,
            'output_vat': 3200.0,
            'net_vat': 1600.0,
            'income_tax': 750.0
        }
    """
    from models import TaxEntry
    from sqlalchemy import func
    from datetime import datetime
    
    try:
        # الفترة الافتراضية
        if period is None:
            period = datetime.now().strftime('%Y-%m')
        
        # استعلام ملخص
        summary = db.session.query(
            TaxEntry.entry_type,
            func.sum(TaxEntry.tax_amount).label('total')
        ).filter(
            TaxEntry.tax_period == period
        ).group_by(
            TaxEntry.entry_type
        ).all()
        
        result = {
            'period': period,
            'input_vat': 0.0,
            'output_vat': 0.0,
            'income_tax': 0.0,
            'withholding': 0.0
        }
        
        for entry_type, total in summary:
            if entry_type == 'INPUT_VAT':
                result['input_vat'] = float(total or 0)
            elif entry_type == 'OUTPUT_VAT':
                result['output_vat'] = float(total or 0)
            elif entry_type == 'INCOME_TAX':
                result['income_tax'] = float(total or 0)
            elif entry_type == 'WITHHOLDING':
                result['withholding'] = float(total or 0)
        
        # صافي VAT (المستحق للحكومة)
        result['net_vat'] = result['output_vat'] - result['input_vat']
        
        return {'success': True, **result}
        
    except Exception as e:
        current_app.logger.error(f'❌ get_tax_summary failed: {e}')
        return {'success': False, 'error': str(e)}


def check_ip_allowed(ip: str) -> Dict[str, Any]:
    from models import SystemSettings
    
    enable_whitelist = SystemSettings.get_setting('enable_ip_whitelist', False)
    enable_blacklist = SystemSettings.get_setting('enable_ip_blacklist', False)
    enable_country_block = SystemSettings.get_setting('enable_country_blocking', False)
    
    if not any([enable_whitelist, enable_blacklist, enable_country_block]):
        return {'allowed': True, 'reason': 'Security checks disabled'}
    
    if enable_blacklist:
        blacklist_raw = SystemSettings.get_setting('ip_blacklist', '[]')
        try:
            blacklist = json.loads(blacklist_raw) if isinstance(blacklist_raw, str) else blacklist_raw
        except Exception:
            blacklist = []
        
        if ip in blacklist:
            return {'allowed': False, 'reason': 'IP في القائمة السوداء'}
    
    if enable_whitelist:
        whitelist_raw = SystemSettings.get_setting('ip_whitelist', '[]')
        try:
            whitelist = json.loads(whitelist_raw) if isinstance(whitelist_raw, str) else whitelist_raw
        except Exception:
            whitelist = []
        
        if ip not in whitelist:
            return {'allowed': False, 'reason': 'IP غير موجود في القائمة البيضاء'}
    
    if enable_country_block:
        try:
            import requests
            response = requests.get(f'http://ip-api.com/json/{ip}?fields=countryCode', timeout=2)
            if response.status_code == 200:
                data = response.json()
                country_code = data.get('countryCode', '')
                
                blocked_countries_raw = SystemSettings.get_setting('blocked_countries', '[]')
                try:
                    blocked_countries = json.loads(blocked_countries_raw) if isinstance(blocked_countries_raw, str) else blocked_countries_raw
                except Exception:
                    blocked_countries = []
                
                if country_code in blocked_countries:
                    return {'allowed': False, 'reason': f'الدولة {country_code} محظورة'}
        except Exception:
            pass
    
    return {'allowed': True, 'reason': 'مسموح'}


def serialize_enum(enum_cls):
    """Return a dict of {name: value} for an Enum class."""
    try:
        return {name: member.value for name, member in enum_cls.__members__.items()}
    except Exception:
        return {}
