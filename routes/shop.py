
from datetime import datetime, timezone
import uuid, json
from functools import wraps
from types import SimpleNamespace
from typing import Any, Optional, Dict
from decimal import Decimal, InvalidOperation
from flask_wtf.csrf import generate_csrf
from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, abort, jsonify, current_app, redirect, url_for, flash, g
from flask_login import login_required, current_user
from sqlalchemy import func, case, and_
from sqlalchemy.exc import SQLAlchemyError
from flask_wtf import FlaskForm

from extensions import db, csrf
from forms import AddToOnlineCartForm, ProductForm
from models import (
    Customer,
    OnlineCart,
    OnlineCartItem,
    OnlinePreOrder,
    OnlinePreOrderItem,
    OnlinePayment,
    Product,
    ProductCategory,
    StockLevel,
    Warehouse,
    WarehouseType,
    Payment,
    PaymentStatus,
    PaymentDirection,
    PaymentEntityType,
    GLBatch,
    GLEntry,
    TaxEntry,
    OnlineCartStatus,
    PreOrderStatus,
    OnlinePaymentStatus,
    PaymentProgress,
)
import utils
from utils import _get_or_404

shop_bp = Blueprint("shop", __name__, url_prefix="/shop", template_folder="templates/shop")

@shop_bp.before_request
def restrict_shop_access():
    # الحماية: فقط للمالك والمطور (Level 0) لصفحات الإدارة
    if request.endpoint and 'admin' in request.endpoint:
        if not current_user.is_authenticated:
             return redirect(url_for('auth.login'))
        if not (current_user.is_system or current_user.role_name_l in ['owner', 'developer']):
            flash('⛔ غير مصرح لك بإدارة المتجر (تتطلب صلاحيات المالك)', 'danger')
            return redirect(url_for('main.dashboard'))

@shop_bp.app_context_processor
def _inject_shop_helpers():
    def _display_name_for_shop(p: Product) -> str:
        v = getattr(p, "online_name", None) or getattr(p, "commercial_name", None) or getattr(p, "name", "")
        return (v or "").strip()
    return dict(
        price_for_shop=_price_for_shop,
        csrf_token=generate_csrf,
        display_name_for_shop=_display_name_for_shop
    )

def _reserve_statuses():
    return set(current_app.config.get("SHOP_RESERVE_STATUSES") or [PreOrderStatus.PENDING.value, PreOrderStatus.CONFIRMED.value])

def _resp(msg, cat="info", code=None, data=None, to="shop.catalog"):
    if request.is_json or request.args.get("format") == "json":
        if code is None:
            code = 200 if cat in ("success", "info") else 400
        payload: Dict[str, Any] = {"message": msg, "status": cat}
        if data:
            payload.update(data)
        return jsonify(payload), code
    flash(msg, cat)
    return redirect(url_for(to))

def _find_default_warehouse():
    default_id = current_app.config.get("SHOP_DEFAULT_WAREHOUSE_ID")
    if default_id:
        wh = Warehouse.query.filter_by(id=default_id, is_active=True).first()
        if wh:
            return wh
    online_val = getattr(WarehouseType, "ONLINE").value if hasattr(WarehouseType, "ONLINE") else "ONLINE"
    return (
        Warehouse.query.filter_by(is_active=True, online_is_default=True).first()
        or (Warehouse.query.filter_by(is_active=True, warehouse_type=online_val).first() if hasattr(Warehouse, "warehouse_type") else None)
        or Warehouse.query.filter_by(is_active=True).first()
    )

def _json_loads(value: str) -> Dict[str, Any]:
    value = (value or "").strip()
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}

def _warehouse_types():
    raw = current_app.config.get("SHOP_WAREHOUSE_TYPES", ["MAIN", "INVENTORY"])
    vals = []
    for t in raw:
        try:
            vals.append(getattr(WarehouseType, t).value)
        except Exception:
            vals.append(t)
    return vals

def _online_scope_ids():
    if hasattr(g, "_online_ids"):
        return g._online_ids
    try:
        q = Warehouse.query.filter(Warehouse.is_active.is_(True))
        if hasattr(Warehouse, "online_is_default"):
            q = q.filter(Warehouse.online_is_default.is_(True))
        ids = [w.id for w in q.all()]
        if ids:
            g._online_ids = ids
            return g._online_ids
    except Exception:
        current_app.logger.debug('database query failed in shop.py', exc_info=True)
    try:
        online_val = getattr(WarehouseType, "ONLINE").value if hasattr(WarehouseType, "ONLINE") else "ONLINE"
        q = Warehouse.query.filter(Warehouse.is_active.is_(True))
        if hasattr(Warehouse, "warehouse_type"):
            q = q.filter(Warehouse.warehouse_type == online_val)
        ids = [w.id for w in q.all()]
        if ids:
            g._online_ids = ids
            return g._online_ids
    except Exception:
        current_app.logger.debug('attribute access failed in shop.py', exc_info=True)
    ids = current_app.config.get("SHOP_WAREHOUSE_IDS")
    g._online_ids = ids or None
    return g._online_ids

def _ensure_online_stocklevels_for_products(product_ids):
    try:
        product_ids = [int(pid) for pid in (product_ids or []) if pid]
    except Exception:
        product_ids = []
    if not product_ids:
        return 0
    targets = []
    default_wh = _find_default_warehouse()
    if default_wh:
        targets = [default_wh.id]
    else:
        ids = _online_scope_ids()
        if ids:
            targets = [ids[0]]
    if not targets:
        return 0
    wid = targets[0]
    existing_pids = {
        pid for (pid,) in db.session.query(StockLevel.product_id)
        .filter(StockLevel.warehouse_id == wid, StockLevel.product_id.in_(product_ids))
        .distinct()
        .all()
    }
    missing = [pid for pid in product_ids if pid not in existing_pids]
    if not missing:
        return 0
    base = {"warehouse_id": wid, "quantity": 0}
    if hasattr(StockLevel, "reserved_quantity"):
        base["reserved_quantity"] = 0
    objs = [StockLevel(product_id=pid, **base) for pid in missing]
    db.session.bulk_save_objects(objs)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return 0
    return len(objs)

def _as_decimal(val: Any) -> Optional[Decimal]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float, Decimal)):
        try:
            return Decimal(str(val))
        except InvalidOperation:
            return None
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")
    s = str(val).translate(trans)
    s = "".join(ch for ch in s if ch.isdigit() or ch in {".", "-", "+"})
    try:
        return Decimal(s)
    except InvalidOperation:
        return None

def _exists_product_field(col, val, exclude_id=None):
    if not val:
        return False
    s = str(val).strip()
    q = db.session.query(Product.id)
    q = q.filter(func.lower(col) == s.lower())
    if exclude_id:
        q = q.filter(Product.id != exclude_id)
    return db.session.query(q.exists()).scalar()

def _price_for_shop(p: Product) -> float:
    v = getattr(p, "online_price", None)
    if v in (None, 0, Decimal("0")):
        v = getattr(p, "selling_price", None)
        if v in (None, 0, Decimal("0")):
            v = getattr(p, "price", 0)
    try:
        return float(v or 0)
    except Exception:
        return 0.0

def available_qty(product_id: int) -> int:
    if not hasattr(g, "_avail_cache"):
        g._avail_cache = {}
    if product_id in g._avail_cache:
        return g._avail_cache[product_id]
    if hasattr(StockLevel, "available"):
        on_hand_q = (
            db.session.query(func.coalesce(func.sum(StockLevel.available), 0))
            .select_from(StockLevel)
            .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
            .filter(StockLevel.product_id == product_id, Warehouse.is_active.is_(True))
        )
    else:
        on_hand_q = (
            db.session.query(func.coalesce(func.sum(StockLevel.quantity), 0))
            .select_from(StockLevel)
            .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
            .filter(StockLevel.product_id == product_id, Warehouse.is_active.is_(True))
        )
    ids = _online_scope_ids()
    if ids:
        on_hand_q = on_hand_q.filter(Warehouse.id.in_(ids))
    else:
        tvals = _warehouse_types()
        if tvals and hasattr(Warehouse, "warehouse_type"):
            on_hand_q = on_hand_q.filter(Warehouse.warehouse_type.in_(tvals))
    on_hand = on_hand_q.scalar() or 0
    reserved = 0
    if not hasattr(StockLevel, "available"):
        reserved = (
            db.session.query(func.coalesce(func.sum(OnlinePreOrderItem.quantity), 0))
            .join(OnlinePreOrder, OnlinePreOrderItem.order_id == OnlinePreOrder.id)
            .filter(
                OnlinePreOrderItem.product_id == product_id,
                OnlinePreOrder.status.in_(_reserve_statuses()),
            )
            .scalar()
            or 0
        )
    v = max(0, int(on_hand) - int(reserved))
    g._avail_cache[product_id] = v
    return v


def _bulk_available_map(product_ids) -> Dict[int, int]:
    ids = []
    for x in (product_ids or []):
        try:
            xi = int(x)
        except Exception:
            continue
        if xi > 0:
            ids.append(xi)
    if not ids:
        return {}
    uniq = list(dict.fromkeys(ids))

    if not hasattr(g, "_avail_cache"):
        g._avail_cache = {}

    unknown = [pid for pid in uniq if pid not in g._avail_cache]
    if not unknown:
        return {pid: int(g._avail_cache.get(pid, 0) or 0) for pid in uniq}

    if hasattr(StockLevel, "available"):
        on_hand_expr = func.coalesce(func.sum(StockLevel.available), 0)
    else:
        on_hand_expr = func.coalesce(func.sum(StockLevel.quantity), 0)

    on_hand_q = (
        db.session.query(StockLevel.product_id, on_hand_expr.label("on_hand"))
        .select_from(StockLevel)
        .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
        .filter(StockLevel.product_id.in_(unknown), Warehouse.is_active.is_(True))
    )
    scope_ids = _online_scope_ids()
    if scope_ids:
        on_hand_q = on_hand_q.filter(Warehouse.id.in_(scope_ids))
    else:
        tvals = _warehouse_types()
        if tvals and hasattr(Warehouse, "warehouse_type"):
            on_hand_q = on_hand_q.filter(Warehouse.warehouse_type.in_(tvals))

    on_hand_rows = on_hand_q.group_by(StockLevel.product_id).all()
    on_hand_map = {int(pid): int(total or 0) for pid, total in on_hand_rows}

    reserved_map = {}
    if not hasattr(StockLevel, "available"):
        reserved_rows = (
            db.session.query(
                OnlinePreOrderItem.product_id,
                func.coalesce(func.sum(OnlinePreOrderItem.quantity), 0).label("reserved"),
            )
            .join(OnlinePreOrder, OnlinePreOrderItem.order_id == OnlinePreOrder.id)
            .filter(
                OnlinePreOrderItem.product_id.in_(unknown),
                OnlinePreOrder.status.in_(_reserve_statuses()),
            )
            .group_by(OnlinePreOrderItem.product_id)
            .all()
        )
        reserved_map = {int(pid): int(total or 0) for pid, total in reserved_rows}

    for pid in unknown:
        on_hand = int(on_hand_map.get(pid, 0) or 0)
        reserved = int(reserved_map.get(pid, 0) or 0)
        g._avail_cache[pid] = max(0, on_hand - reserved)

    return {pid: int(g._avail_cache.get(pid, 0) or 0) for pid in uniq}

def _super_roles():
    try:
        from utils import _SUPER_ROLES as _SR
        return {str(x).strip().lower() for x in (_SR or [])}
    except Exception:
        return {"developer", "owner"}

def is_super_admin(user) -> bool:
    try:
        if not getattr(user, "is_authenticated", False):
            return False
        # PBAC: التحقق من الصلاحية بدلاً من الدور
        if hasattr(user, 'has_permission'):
            return user.has_permission(SystemPermissions.MANAGE_SHOP)
        return False
    except Exception:
        return False

def super_admin_required(f):
    @wraps(f)
    @login_required
    def inner(*a, **kw):
        if not is_super_admin(current_user):
            abort(403)
        return f(*a, **kw)
    return inner

def online_customer_required(f):
    @wraps(f)
    @login_required
    def inner(*a, **kw):
        if is_super_admin(current_user):
            g.viewer_only = False
            g.online_customer = SimpleNamespace(
                id=current_user.id,
                phone=getattr(current_user, "phone", None),
                address=getattr(current_user, "address", None),
                currency="ILS",
                is_online=True,
                name=getattr(current_user, "username", "مستخدم"),
            )
            return f(*a, **kw)
        return _resp("هذه الميزة غير متاحة للحسابات المسجلة.", "warning")
    return inner

class GatewayAdapter:
    name = "base"
    def authorize_capture(self, *, preorder: OnlinePreOrder, amount: float, currency: str):
        raise NotImplementedError
    def refund(self, op: OnlinePayment) -> dict:
        raise NotImplementedError
    def handle_webhook(self, request) -> dict:
        raise NotImplementedError

class BlooprintAdapter(GatewayAdapter):
    name = "blooprint"
    def authorize_capture(self, *, preorder: OnlinePreOrder, amount: float, currency: str):
        form = request.form
        raw = _json_loads(form.get("transaction_data", "")) or {}
        card = raw.get("card") if isinstance(raw, dict) else {}
        def pick(*keys):
            for k in keys:
                v = form.get(k)
                if v:
                    return v
            if isinstance(raw, dict):
                for k in keys:
                    v = raw.get(k)
                    if v:
                        return v
            if isinstance(card, dict):
                for k in keys:
                    v = card.get(k)
                    if v:
                        return v
            return None
        status = OnlinePaymentStatus.SUCCESS.value if amount > 0 else OnlinePaymentStatus.PENDING.value
        return {
            "success": amount > 0,
            "status": status,
            "txn_id": (raw.get("transaction_id") or f"TXN-{uuid.uuid4().hex[:10]}"),
            "card_last4": pick("card_last4", "last4"),
            "card_expiry": pick("card_expiry", "expiry"),
            "cardholder_name": pick("cardholder_name", "card_holder", "holder"),
            "card_brand": pick("card_brand", "brand"),
            "card_fingerprint": pick("card_fingerprint", "fingerprint"),
            "raw": raw,
        }
    def refund(self, op: OnlinePayment) -> dict:
        return {"success": True, "status": OnlinePaymentStatus.REFUNDED.value}
    def handle_webhook(self, request) -> dict:
        secret = current_app.config.get("BLOOPRINT_WEBHOOK_SECRET") or ""
        sig = (request.headers.get("X-Blooprint-Signature") or "").strip()
        if secret and sig != secret:
            return {"ok": False, "error": "invalid_signature"}
        payload = request.get_json(silent=True) or {}
        ref = (payload.get("payment_ref") or "").strip()
        new_status = (payload.get("status") or "").strip().upper()
        if not ref or new_status not in {OnlinePaymentStatus.SUCCESS.value, OnlinePaymentStatus.FAILED.value, OnlinePaymentStatus.REFUNDED.value}:
            return {"ok": False, "error": "bad_payload"}
        op = OnlinePayment.query.filter_by(payment_ref=ref).first()
        if not op:
            return {"ok": False, "error": "payment_not_found"}
        op.status = new_status
        op.card_last4 = payload.get("card_last4") or op.card_last4
        op.card_brand = payload.get("card_brand") or op.card_brand
        op.cardholder_name = payload.get("cardholder_name") or op.cardholder_name
        op.transaction_data = payload
        db.session.add(op)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('commit error')
            return jsonify({'success': False, 'error': 'حدث خطأ داخلي'}), 500
        return {"ok": True, "payment_id": op.id, "status": op.status}

_GATEWAYS = {"blooprint": BlooprintAdapter()}

def _get_adapter(name: Optional[str] = None) -> GatewayAdapter:
    gname = (name or current_app.config.get("ONLINE_GATEWAY_DEFAULT") or "blooprint").lower()
    return _GATEWAYS.get(gname, _GATEWAYS["blooprint"])

@shop_bp.route("/webhook/<gateway>", methods=["POST"], endpoint="gateway_webhook")
@csrf.exempt
def gateway_webhook(gateway: str):
    adp = _get_adapter(gateway)
    result = adp.handle_webhook(request)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code

def _apply_online_scope(q):
    ids = _online_scope_ids()
    q = (
        q.join(StockLevel, StockLevel.product_id == Product.id)
         .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
         .filter(Warehouse.is_active.is_(True))
    )
    if hasattr(Warehouse, "is_online"):
        q = q.filter(Warehouse.is_online.is_(True))
    if hasattr(Warehouse, "deleted_at"):
        q = q.filter(Warehouse.deleted_at.is_(None))
    if ids:
        q = q.filter(Warehouse.id.in_(ids))
    else:
        tvals = _warehouse_types()
        if tvals and hasattr(Warehouse, "warehouse_type"):
            q = q.filter(Warehouse.warehouse_type.in_(tvals))
    q = q.filter(Product.is_active.is_(True))
    if hasattr(Product, "is_published"):
        try:
            q = q.filter(Product.is_published.is_(True))
        except Exception:
            current_app.logger.debug('database query failed in shop.py', exc_info=True)
    if hasattr(Product, "deleted_at"):
        q = q.filter(Product.deleted_at.is_(None))
    company_ids = current_app.config.get("SHOP_WAREHOUSE_COMPANY_IDS")
    if company_ids and hasattr(Warehouse, "company_id"):
        q = q.filter(Warehouse.company_id.in_(company_ids))
    return q

@shop_bp.route("/", endpoint="catalog")
def catalog():
    qparam = (request.args.get("query") or "").strip()
    
    # Allow visitors to see products without login
    if current_user.is_authenticated:
        if not is_super_admin(current_user):
            pre = db.session.query(Product).filter(Product.is_active.is_(True))
            if hasattr(Product, "is_published"):
                try:
                    pre = pre.filter(Product.is_published.is_(True))
                except Exception:
                    current_app.logger.debug('database query failed in shop.py', exc_info=True)
            if qparam:
                like = f"%{qparam}%"
                pre = pre.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.part_number.ilike(like)))
            pre_ids = [pid for (pid,) in pre.with_entities(Product.id).all()]
            _ensure_online_stocklevels_for_products(pre_ids)
        
        if is_super_admin(current_user):
            q = db.session.query(Product)
        else:
            q = _apply_online_scope(db.session.query(Product))
    else:
        # For non-authenticated users, show all active products
        q = db.session.query(Product).filter(Product.is_active.is_(True))
        # Don't filter by is_published for visitors - show all active products
    
    if qparam:
        like = f"%{qparam}%"
        q = q.filter((Product.name.ilike(like)) | (Product.sku.ilike(like)) | (Product.part_number.ilike(like)))
    
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    
    products = q.distinct().order_by(Product.name.asc(), Product.id.asc()).limit(per_page * 10).all()
    if request.is_json or request.args.get("format") == "json":
        avail = _bulk_available_map([p.id for p in products]) if current_user.is_authenticated else {}
        return jsonify([
            {
                "id": p.id,
                "name": (getattr(p, "online_name", None) or getattr(p, "commercial_name", None) or p.name),
                "price": _price_for_shop(p),
                "online_price": (float(p.online_price) if getattr(p, "online_price", None) is not None else None),
                "stock": int(avail.get(p.id, 0) if current_user.is_authenticated else getattr(p, 'stock_quantity', 0) or 0),
                "image": getattr(p, "image", None),
                "online_image": getattr(p, "online_image", None),
            }
            for p in products
        ])
    # Create availability map - for non-authenticated users, show stock_quantity
    if current_user.is_authenticated:
        avail_map = _bulk_available_map([p.id for p in products])
    else:
        avail_map = {p.id: getattr(p, 'stock_quantity', 0) for p in products}
    
    return render_template(
        "shop/catalog.html",
        products=products,
        form=FlaskForm(),
        avail_map=avail_map,
        is_super_admin=is_super_admin(current_user) if current_user.is_authenticated else False,
    )

@shop_bp.route("/product/<int:product_id>", endpoint="product_detail")
def product_detail(product_id):
    """Display detailed product information with AI features."""
    product = _get_or_404(Product, product_id)
    
    if not product.is_active:
        abort(404)
    
    # Get related products (AI recommendations)
    related_products = db.session.query(Product).filter(
        Product.id != product_id,
        Product.is_active == True,
        Product.category_id == product.category_id
    ).limit(4).all()
    
    # Get category information
    category = None
    if product.category_id:
        category = db.session.get(ProductCategory, product.category_id)
    
    return render_template("shop/product_detail.html", 
                         product=product,
                         related_products=related_products,
                         category=category)

@shop_bp.route("/products", endpoint="products")
def products():
    qparam = (request.args.get("query") or "").strip()
    if not is_super_admin(current_user):
        pre = db.session.query(Product).filter(Product.is_active.is_(True))
        if hasattr(Product, "is_published"):
            try:
                pre = pre.filter(Product.is_published.is_(True))
            except Exception:
                current_app.logger.debug('database query failed in shop.py', exc_info=True)
        if qparam:
            like = f"%{qparam}%"
            pre = pre.filter(
                (Product.name.ilike(like)) |
                (Product.sku.ilike(like)) |
                (Product.part_number.ilike(like))
            )
        pre_ids = [pid for (pid,) in pre.with_entities(Product.id).all()]
        _ensure_online_stocklevels_for_products(pre_ids)
    if is_super_admin(current_user):
        q = db.session.query(Product)
    else:
        q = _apply_online_scope(db.session.query(Product))
    if qparam:
        like = f"%{qparam}%"
        q = q.filter(
            (Product.name.ilike(like)) |
            (Product.sku.ilike(like)) |
            (Product.part_number.ilike(like))
        )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    pagination = q.distinct().order_by(Product.name.asc(), Product.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    products = list(pagination.items or [])
    avail_map = _bulk_available_map([p.id for p in products])
    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)
    return render_template(
        "shop/products.html",
        products=products,
        avail_map=avail_map,
        is_super_admin=is_super_admin(current_user),
        price_for_shop=_price_for_shop,
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
    )

@shop_bp.get("/api/products")
def api_products():
    try:
        qparam = (request.args.get("query") or "").strip()
        if not is_super_admin(current_user):
            pre = db.session.query(Product).filter(Product.is_active.is_(True))
            if hasattr(Product, "is_published"):
                try:
                    pre = pre.filter(Product.is_published.is_(True))
                except Exception:
                    current_app.logger.debug('database query failed in shop.py', exc_info=True)
            if qparam:
                like = f"%{qparam}%"
                pre = pre.filter(
                    (Product.name.ilike(like)) |
                    (Product.sku.ilike(like)) |
                    (Product.part_number.ilike(like))
                )
            pre_ids = [pid for (pid,) in pre.with_entities(Product.id).all()]
            _ensure_online_stocklevels_for_products(pre_ids)
        if is_super_admin(current_user):
            q = db.session.query(Product)
        else:
            q = _apply_online_scope(db.session.query(Product))
        if qparam:
            like = f"%{qparam}%"
            q = q.filter(
                (Product.name.ilike(like)) |
                (Product.sku.ilike(like)) |
                (Product.part_number.ilike(like))
            )
        products = q.distinct().order_by(Product.name.asc(), Product.id.asc()).limit(500).all()
        avail = _bulk_available_map([p.id for p in products])
        data = []
        for p in products:
            data.append({
                "id": p.id,
                "name": (getattr(p, "online_name", None) or getattr(p, "commercial_name", None) or p.name),
                "sku": getattr(p, "sku", None),
                "part_number": getattr(p, "part_number", None),
                "price": _price_for_shop(p),
                "online_price": (float(p.online_price) if getattr(p, "online_price", None) is not None else None),
                "selling_price": (float(p.selling_price) if getattr(p, "selling_price", None) is not None else None),
                "stock": int(avail.get(p.id, 0) or 0),
                "image": getattr(p, "image", None),
                "online_image": getattr(p, "online_image", None),
                "brand": getattr(p, "brand", None),
            })
        return jsonify({"data": data})
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@shop_bp.get("/api/product/<int:pid>")
def api_product_detail(pid: int):
    try:
        p = _get_or_404(Product, pid)
        return jsonify({
            "id": p.id,
            "name": (getattr(p, "online_name", None) or getattr(p, "commercial_name", None) or p.name),
            "sku": getattr(p, "sku", None),
            "part_number": getattr(p, "part_number", None),
            "price": _price_for_shop(p),
            "online_price": (float(p.online_price) if getattr(p, "online_price", None) is not None else None),
            "selling_price": (float(p.selling_price) if getattr(p, "selling_price", None) is not None else None),
            "stock": available_qty(p.id),
            "image": getattr(p, "image", None),
            "online_image": getattr(p, "online_image", None),
            "brand": getattr(p, "brand", None),
            "unit": getattr(p, "unit", None),
            "category_name": getattr(p, "category_name", None),
        })
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@shop_bp.route("/order", methods=["POST"], endpoint="place_order")
@online_customer_required
def place_order():
    cart = get_active_cart(g.online_customer.id)
    if not cart or not cart.items:
        return _resp("سلتك فارغة.", "warning")
    return redirect(url_for("shop.checkout"))

def get_active_cart(customer_id: int) -> OnlineCart | None:
    return OnlineCart.query.filter_by(
        customer_id=customer_id,
        status=OnlineCartStatus.ACTIVE.value
    ).first()

def _json_requested():
    if request.is_json:
        return True
    if request.args.get("format") == "json":
        return True
    acc = (request.headers.get("Accept") or "").lower()
    return "application/json" in acc

def _prepaid_rate():
    return float(current_app.config.get("SHOP_PREPAID_RATE", 0.2))

def _cart_numbers(cart: "OnlineCart"):
    subtotal = sum((i.quantity or 0) * float(i.price or 0) for i in cart.items)
    total = round(subtotal, 2)
    prepaid = round(total * _prepaid_rate(), 2)
    count = sum(i.quantity or 0 for i in cart.items)
    return {"subtotal": total, "total": total, "prepaid_amount": prepaid, "cart_count": count}

@shop_bp.route("/cart/add/<int:product_id>", methods=["POST"], endpoint="add_to_cart")
@online_customer_required
def add_to_cart(product_id):
    product = _get_or_404(Product, product_id)
    form = AddToOnlineCartForm()
    if not form.validate_on_submit():
        if _json_requested():
            return jsonify({"ok": False, "message": "بيانات غير صحيحة."}), 400
        return _resp("بيانات غير صحيحة.", "danger")
    qty = int(form.quantity.data or 0)
    if qty <= 0:
        if _json_requested():
            return jsonify({"ok": False, "message": "كمية غير صالحة."}), 400
        return _resp("كمية غير صالحة.", "danger")
    if qty > available_qty(product.id):
        if _json_requested():
            return jsonify({"ok": False, "message": "الكمية المطلوبة غير متوفرة."}), 400
        return _resp("الكمية المطلوبة غير متوفرة.", "danger")
    cart = get_active_cart(g.online_customer.id) or OnlineCart(
        customer_id=g.online_customer.id, session_id=uuid.uuid4().hex, status=OnlineCartStatus.ACTIVE.value
    )
    db.session.add(cart)
    db.session.flush()
    item = OnlineCartItem.query.filter_by(cart_id=cart.id, product_id=product.id).first()
    unit_price = _price_for_shop(product)
    if item:
        new_total = int(item.quantity or 0) + qty
        if new_total > available_qty(product.id):
            if _json_requested():
                return jsonify({"ok": False, "message": "الكمية المطلوبة تتجاوز المتوفر."}), 400
            return _resp("الكمية المطلوبة تتجاوز المتوفر.", "danger")
        item.quantity = new_total
        item.price = unit_price
    else:
        db.session.add(
            OnlineCartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=qty,
                price=unit_price,
            )
        )
    try:
        db.session.commit()
        cart = get_active_cart(g.online_customer.id)
        nums = _cart_numbers(cart)
        if _json_requested():
            return jsonify({
                "ok": True,
                "message": "تمت إضافة المنتج إلى السلة.",
                **nums
            })
        return _resp("تمت إضافة المنتج إلى السلة.", "success", code=200)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        if _json_requested():
            return jsonify({"ok": False, "message": "خطأ أثناء الإضافة"}), 500
        return _resp("خطأ أثناء الإضافة", "danger")

@shop_bp.route("/cart", endpoint="cart")
@online_customer_required
def cart():
    cart = get_active_cart(g.online_customer.id)
    items = cart.items if cart else []
    subtotal = sum(i.quantity * float(i.price or 0) for i in items)
    rate = _prepaid_rate()
    prepaid = round(subtotal * rate, 2)
    return render_template(
        "shop/cart.html",
        cart=cart,
        items=items,
        subtotal=subtotal,
        prepaid_amount=prepaid,
        form=FlaskForm(),
        is_super_admin=is_super_admin(current_user),
    )

@shop_bp.route("/cart/update/<int:item_id>", methods=["POST"], endpoint="update_cart_item")
@online_customer_required
def update_cart_item(item_id):
    item = _get_or_404(OnlineCartItem, item_id)
    if item.cart.customer_id != g.online_customer.id:
        return jsonify({"ok": False, "message": "غير مصرح"}), 403
    new_qty = request.form.get("quantity", type=int)
    if not new_qty or new_qty <= 0:
        return jsonify({"ok": False, "message": "كمية غير صالحة"}), 400
    if new_qty > available_qty(item.product_id):
        return jsonify({"ok": False, "message": "الكمية غير متوفرة"}), 400
    item.quantity = new_qty
    try:
        db.session.commit()
        cart = item.cart
        nums = _cart_numbers(cart)
        item_total = round(item.quantity * float(item.price or 0), 2)
        payload = {
            "ok": True,
            "message": "تم تحديث الكمية",
            "item": {
                "id": item.id,
                "quantity": item.quantity,
                "price": float(item.price or 0),
                "total": item_total
            },
            **nums
        }
        if _json_requested():
            return jsonify(payload)
        flash("تم تحديث الكمية", "success")
        return redirect(url_for("shop.cart"))
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "فشل التحديث"}), 500

@shop_bp.route("/cart/remove/<int:item_id>", methods=["POST"], endpoint="remove_from_cart")
@online_customer_required
def remove_from_cart(item_id):
    item = _get_or_404(OnlineCartItem, item_id)
    if item.cart.customer_id != g.online_customer.id:
        return jsonify({"ok": False, "message": "غير مصرح"}), 403
    cart = item.cart
    db.session.delete(item)
    try:
        db.session.commit()
        nums = _cart_numbers(cart)
        payload = {"ok": True, "message": "تم الحذف", "removed_id": item_id, **nums}
        if _json_requested():
            return jsonify(payload)
        flash("تم الحذف", "success")
        return redirect(url_for("shop.cart"))
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "فشل الحذف"}), 500

@shop_bp.route("/checkout", methods=["GET", "POST"], endpoint="checkout")
@online_customer_required
def checkout():
    cart = get_active_cart(g.online_customer.id)
    if not cart or not cart.items:
        return _resp("سلتك فارغة.", "warning", to="shop.catalog")

    subtotal_before_tax = sum(i.quantity * float(i.price or 0) for i in cart.items)
    vat_enabled = False
    vat_rate = 0.0
    tax_amount = 0.0
    subtotal = subtotal_before_tax
    
    rate = _prepaid_rate()
    prepaid = round(subtotal * rate, 2)
    if request.method == "POST":
        try:
            with db.session.begin_nested():
                product_ids = [itm.product_id for itm in cart.items]
                if product_ids:
                    q = (
                        db.session.query(StockLevel.id)
                        .join(Warehouse, StockLevel.warehouse_id == Warehouse.id)
                        .filter(StockLevel.product_id.in_(product_ids), Warehouse.is_active.is_(True))
                    )
                    ids = _online_scope_ids()
                    if ids:
                        q = q.filter(Warehouse.id.in_(ids))
                    else:
                        tvals = _warehouse_types()
                        if tvals:
                            q = q.filter(Warehouse.warehouse_type.in_(tvals))
                    _ = q.with_for_update(skip_locked=True).all()
                for itm in cart.items:
                    if itm.quantity > available_qty(itm.product_id):
                        abort(409, description="الكمية المطلوبة غير متوفرة.")
                payment_status = PaymentProgress.PAID.value if prepaid >= subtotal else (PaymentProgress.PARTIAL.value if prepaid > 0 else PaymentProgress.PENDING.value)
                
                preorder = OnlinePreOrder(
                    customer_id=g.online_customer.id,
                    cart_id=cart.id,
                    order_number=f"PO-{uuid.uuid4().hex[:8].upper()}",
                    prepaid_amount=prepaid,
                    total_amount=subtotal,
                    base_amount=subtotal_before_tax,
                    tax_rate=vat_rate,
                    tax_amount=tax_amount,
                    status=PreOrderStatus.CONFIRMED.value,
                    payment_status=payment_status,
                    payment_method="card",
                    shipping_address=request.form.get("shipping_address") or getattr(g.online_customer, "address", None),
                    billing_address=request.form.get("billing_address") or getattr(g.online_customer, "address", None),
                    notes=None,
                )
                db.session.add(preorder)
                db.session.flush()
                for itm in cart.items:
                    db.session.add(
                        OnlinePreOrderItem(
                            order_id=preorder.id,
                            product_id=itm.product_id,
                            quantity=itm.quantity,
                            price=itm.price,
                        )
                    )
                payment_ref = f"PAY-{uuid.uuid4().hex[:8].upper()}"
                op = OnlinePayment(
                    payment_ref=payment_ref,
                    order_id=preorder.id,
                    amount=prepaid,
                    currency=getattr(g.online_customer, "currency", "ILS"),
                    method="card",
                    gateway=(current_app.config.get("ONLINE_GATEWAY_DEFAULT") or "blooprint").lower(),
                    status=OnlinePaymentStatus.PENDING.value,
                    transaction_data=_json_loads(request.form.get("transaction_data", "")),
                )
                db.session.add(op)
                db.session.flush()
                adp = _get_adapter(op.gateway)
                res = adp.authorize_capture(preorder=preorder, amount=float(prepaid or 0), currency=op.currency)
                if res.get("success"):
                    op.status = res.get("status") or OnlinePaymentStatus.SUCCESS.value
                    op.transaction_data = res.get("raw") or op.transaction_data
                    op.card_last4 = res.get("card_last4") or op.card_last4
                    op.card_expiry = res.get("card_expiry") or op.card_expiry
                    op.cardholder_name = res.get("cardholder_name") or op.cardholder_name
                    op.card_brand = res.get("card_brand") or op.card_brand
                    op.card_fingerprint = res.get("card_fingerprint") or op.card_fingerprint
                else:
                    op.status = OnlinePaymentStatus.FAILED.value if prepaid > 0 else OnlinePaymentStatus.PENDING.value
                db.session.add(op)
                if prepaid > 0 and op.status == OnlinePaymentStatus.SUCCESS.value:
                    payment = Payment(
                        entity_type=PaymentEntityType.CUSTOMER.value,
                        customer_id=g.online_customer.id,
                        direction=PaymentDirection.IN.value,
                        status=PaymentStatus.COMPLETED.value,
                        method="card",
                        total_amount=prepaid,
                        currency=getattr(g.online_customer, "currency", "ILS"),
                        payment_date=datetime.now(timezone.utc),
                        reference=f"Online Preorder {preorder.order_number}",
                        notes="Online prepaid via checkout",
                    )
                    db.session.add(payment)
                    db.session.flush()
                    op.payment_id = payment.id
                    db.session.add(op)
                
                gl_batch = GLBatch(
                    source_type='ONLINE_PREORDER',
                    source_id=preorder.id,
                    purpose='ONLINE_SALE',
                    posted_at=datetime.now(timezone.utc),
                    currency=preorder.currency,
                    memo=f"Online Preorder {preorder.order_number}",
                    status='POSTED',
                    entity_type='CUSTOMER',
                    entity_id=g.online_customer.id
                )
                db.session.add(gl_batch)
                db.session.flush()
                
                db.session.add(GLEntry(
                    batch_id=gl_batch.id,
                    account='1100_AR',
                    debit=subtotal,
                    credit=0,
                    ref=f"Online Order {preorder.order_number}"
                ))
                
                db.session.add(GLEntry(
                    batch_id=gl_batch.id,
                    account='4000_SALES',
                    debit=0,
                    credit=subtotal_before_tax,
                    ref=f"Online Sales {preorder.order_number}"
                ))
                
                if vat_enabled and tax_amount > 0:
                    db.session.add(GLEntry(
                        batch_id=gl_batch.id,
                        account='2100_VAT_PAYABLE',
                        debit=0,
                        credit=tax_amount,
                        ref=f"VAT {vat_rate}%"
                    ))
                    
                    order_date = datetime.now(timezone.utc)
                    tax_entry = TaxEntry(
                        entry_type='OUTPUT_VAT',
                        transaction_type='ONLINE_PREORDER',
                        transaction_id=preorder.id,
                        transaction_reference=preorder.order_number,
                        tax_rate=float(vat_rate),
                        base_amount=float(subtotal_before_tax),
                        tax_amount=float(tax_amount),
                        total_amount=float(subtotal),
                        currency=preorder.currency,
                        fiscal_year=order_date.year,
                        fiscal_month=order_date.month,
                        tax_period=f"{order_date.year}-{order_date.month:02d}",
                        customer_id=g.online_customer.id,
                        gl_entry_id=gl_batch.id,
                        notes=f'طلب أونلاين: {preorder.order_number}'
                    )
                    db.session.add(tax_entry)
                
                cart.status = "CONVERTED"
            try:
                if getattr(g.online_customer, "phone", None):
                    if prepaid > 0 and op.status == "SUCCESS":
                        utils.send_whatsapp_message(
                            g.online_customer.phone,
                            f"✅ تم تأكيد طلبك {preorder.order_number} وإتمام الدفع بنجاح. تم دفع عربون {prepaid} {getattr(g.online_customer,'currency','ILS')}"
                        )
            except Exception:
                current_app.logger.warning('currency conversion failed silently in shop.py', exc_info=True)
            if request.is_json or request.args.get("format") == "json":
                return _resp(
                    "تم إتمام الطلب والدفع بنجاح!",
                    "success",
                    code=200,
                    to="shop.preorder_receipt",
                    data={"preorder_id": preorder.id},
                )
            return redirect(url_for("shop.preorder_receipt", preorder_id=preorder.id))
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('internal error')
            return _resp("خطأ أثناء الدفع", "danger")
    return render_template("shop/pay_online.html", 
                          cart=cart, 
                          subtotal=subtotal, 
                          subtotal_before_tax=subtotal_before_tax,
                          tax_amount=0,
                          vat_rate=0,
                          prepaid_amount=prepaid)

@shop_bp.route("/preorders", endpoint="preorder_list")
@online_customer_required
def preorder_list():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    per_page = min(200, max(10, per_page))

    q = OnlinePreOrder.query.options(
        db.joinedload(OnlinePreOrder.customer),
        db.selectinload(OnlinePreOrder.items),
    )

    if not is_super_admin(current_user):
        q = q.filter(OnlinePreOrder.customer_id == g.online_customer.id)

    q = q.order_by(OnlinePreOrder.created_at.desc(), OnlinePreOrder.id.desc())

    agg = q.order_by(None).with_entities(
        func.count(OnlinePreOrder.id).label("total"),
        func.coalesce(func.sum(func.coalesce(OnlinePreOrder.total_amount, 0)), 0).label("total_amount"),
        func.coalesce(func.sum(case((OnlinePreOrder.status == "FULFILLED", 1), else_=0)), 0).label("fulfilled"),
        func.coalesce(func.sum(case((OnlinePreOrder.status == "PENDING", 1), else_=0)), 0).label("pending"),
        func.coalesce(func.sum(case((OnlinePreOrder.status == "CONFIRMED", 1), else_=0)), 0).label("confirmed"),
        func.coalesce(func.sum(case((OnlinePreOrder.status == "CANCELLED", 1), else_=0)), 0).label("cancelled"),
    ).first()

    summary = {
        "total": int(getattr(agg, "total", 0) or 0),
        "total_amount": float(getattr(agg, "total_amount", 0) or 0),
        "fulfilled": int(getattr(agg, "fulfilled", 0) or 0),
        "pending": int(getattr(agg, "pending", 0) or 0),
        "confirmed": int(getattr(agg, "confirmed", 0) or 0),
        "cancelled": int(getattr(agg, "cancelled", 0) or 0),
    }

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    preorders = list(pagination.items or [])

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)

    return render_template(
        "shop/preorder_list.html",
        preorders=preorders,
        is_super_admin=is_super_admin(current_user),
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
        summary=summary,
    )

@shop_bp.route("/preorder/<int:preorder_id>/receipt", endpoint="preorder_receipt")
@online_customer_required
def preorder_receipt(preorder_id):
    preorder = _get_or_404(OnlinePreOrder, preorder_id)
    if not is_super_admin(current_user) and preorder.customer_id != g.online_customer.id:
        abort(403)
    return render_template("shop/preorder_receipt.html", preorder=preorder)

@shop_bp.route("/preorder/<int:preorder_id>/cancel", methods=["POST"], endpoint="cancel_preorder")
@online_customer_required
def cancel_preorder(preorder_id):
    po = _get_or_404(OnlinePreOrder, preorder_id)
    if not is_super_admin(current_user) and po.customer_id != g.online_customer.id:
        return _resp("غير مصرح.", "danger", to="shop.preorder_list")
    if po.status not in ("PENDING", "CONFIRMED"):
        return _resp("لا يمكن إلغاء هذا الطلب.", "warning", to="shop.preorder_list")
    try:
        with db.session.begin_nested():
            po.status = "CANCELLED"
        return _resp("تم إلغاء الطلب.", "success", code=200, to="shop.preorder_list")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return _resp("خطأ أثناء الإلغاء", "danger", to="shop.preorder_list")

@shop_bp.route("/admin/preorders", endpoint="admin_preorders")
@super_admin_required
def admin_preorders():
    return redirect(url_for("admin_reports.preorders", **request.args.to_dict()))

@shop_bp.route("/admin/products", endpoint="admin_products")
@super_admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).limit(500).all()
    avail_map = _bulk_available_map([p.id for p in products])
    return render_template("shop/admin_products.html", products=products, avail_map=avail_map)

@shop_bp.route("/admin/categories/quick_create", methods=["POST"], endpoint="admin_categories_quick_create")
@super_admin_required
def admin_categories_quick_create():
    if request.is_json:
        name = (request.json.get("name") or "").strip()
        parent_id = request.json.get("parent_id")
    else:
        name = (request.form.get("name") or "").strip()
        parent_id = request.form.get("parent_id")
    if not name:
        return jsonify({"ok": False, "error": "الاسم مطلوب"}), 400
    if len(name) > 100:
        return jsonify({"ok": False, "error": "الاسم أطول من 100 حرف"}), 400
    exists = (
        db.session.query(ProductCategory)
        .filter(func.lower(ProductCategory.name) == name.lower())
        .first()
    )
    if exists:
        return jsonify({"ok": True, "id": exists.id, "name": exists.name}), 200
    cat = ProductCategory(name=name)
    try:
        if parent_id:
            try:
                pid = int(parent_id)
                parent = db.session.get(ProductCategory, pid)
                if parent:
                    cat.parent = parent
            except Exception:
                current_app.logger.debug('numeric conversion failed in shop.py', exc_info=True)
        db.session.add(cat)
        db.session.commit()
        return jsonify({"ok": True, "id": cat.id, "name": cat.name}), 201
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return jsonify({"ok": False, "error": "خطأ في قاعدة البيانات"}), 400

@shop_bp.route("/admin/products/new", methods=["GET", "POST"], endpoint="admin_product_new")
@super_admin_required
def admin_product_new():
    form = ProductForm()
    cats = ProductCategory.query.order_by(ProductCategory.name.asc()).all()
    form.category_id.choices = [(c.id, c.name) for c in cats]
    if form.validate_on_submit():
        def _is_blank(v):
            if v is None:
                return True
            if isinstance(v, str):
                return not v.strip()
            return False

        name = (form.name.data or "").strip()
        existing = (
            Product.query.filter(func.lower(Product.name) == name.lower()).order_by(Product.id.asc()).first()
            if name
            else None
        )
        if existing:
            try:
                form.id.process(None, existing.id)
            except Exception:
                form.id.data = existing.id

        p = existing or Product()
        preserve_if_blank = {}
        if existing:
            for k in (
                "sku",
                "serial_no",
                "barcode",
                "description",
                "part_number",
                "brand",
                "commercial_name",
                "chassis_number",
                "unit",
                "origin_country",
                "dimensions",
                "image",
                "online_name",
                "online_image",
                "notes",
                "supplier_id",
                "supplier_international_id",
                "supplier_local_id",
                "vehicle_type_id",
                "reorder_point",
                "warranty_period",
                "weight",
                "min_price",
                "max_price",
                "online_price",
            ):
                preserve_if_blank[k] = getattr(p, k, None)

        form.apply_to(p)
        if existing:
            for field_name, old_val in preserve_if_blank.items():
                if hasattr(form, field_name):
                    if _is_blank(getattr(form, field_name).data):
                        setattr(p, field_name, old_val)

        sku = (getattr(p, "sku", None) or "").strip() or None
        barcode = (getattr(p, "barcode", None) or "").strip() or None
        serial = (getattr(p, "serial_no", None) or "").strip() or None
        exclude_id = p.id if existing else None
        if sku and _exists_product_field(Product.sku, sku, exclude_id=exclude_id):
            flash("SKU مستخدم بالفعل.", "danger")
            return render_template("shop/admin_product_form.html", form=form, product=None)
        if barcode and _exists_product_field(Product.barcode, barcode, exclude_id=exclude_id):
            flash("الباركود مستخدم بالفعل.", "danger")
            return render_template("shop/admin_product_form.html", form=form, product=None)
        if serial and _exists_product_field(Product.serial_no, serial, exclude_id=exclude_id):
            flash("الرقم التسلسلي مستخدم بالفعل.", "danger")
            return render_template("shop/admin_product_form.html", form=form, product=None)
        db.session.add(p)
        db.session.flush()
        online_val = getattr(WarehouseType, "ONLINE").value if hasattr(WarehouseType, "ONLINE") else "ONLINE"
        default_wh = (
            Warehouse.query.filter_by(is_active=True, online_is_default=True).first()
            or Warehouse.query.filter_by(is_active=True, warehouse_type=online_val).first()
            or Warehouse.query.filter_by(is_active=True).first()
        )
        if default_wh:
            if not StockLevel.query.filter_by(product_id=p.id, warehouse_id=default_wh.id).first():
                kwargs = {"product_id": p.id, "warehouse_id": default_wh.id, "quantity": 0}
                if hasattr(StockLevel, "reserved_quantity"):
                    kwargs["reserved_quantity"] = 0
                stock = StockLevel(**kwargs)
                db.session.add(stock)
        try:
            db.session.commit()
            flash("✅ تم تحديث المنتج الموجود" if existing else "✅ تم إضافة المنتج", "success")
            return redirect(url_for("shop.admin_products"))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('خطأ', 'danger')
    return render_template("shop/admin_product_form.html", form=form, product=None)

@shop_bp.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"], endpoint="admin_product_edit")
@super_admin_required
def admin_product_edit(pid):
    product = _get_or_404(Product, pid)
    form = ProductForm(obj=product)
    cats = ProductCategory.query.order_by(ProductCategory.name.asc()).all()
    form.category_id.choices = [(c.id, c.name) for c in cats]
    if form.validate_on_submit():
        try:
            old_sku = (product.sku or "").strip() if product.sku else None
            old_barcode = (product.barcode or "").strip() if product.barcode else None
            old_serial = (product.serial_no or "").strip() if product.serial_no else None
            
            # حفظ الصور من الحقول المخفية قبل apply_to
            new_image = request.form.get("image", "").strip()
            new_online_image = request.form.get("online_image", "").strip()
            
            form.apply_to(product)
            
            # تحديث الصور بعد apply_to (لأن apply_to قد يعيد كتابتها)
            if new_image:
                # تنظيف المسار
                if new_image.startswith("/static/"):
                    new_image = new_image[len("/static/"):]
                product.image = new_image
            if new_online_image:
                # تنظيف المسار
                if new_online_image.startswith("/static/"):
                    new_online_image = new_online_image[len("/static/"):]
                product.online_image = new_online_image
            
            new_sku = (product.sku or "").strip() if product.sku else None
            new_barcode = (product.barcode or "").strip() if product.barcode else None
            new_serial = (product.serial_no or "").strip() if product.serial_no else None
            if new_sku and new_sku != old_sku and _exists_product_field(Product.sku, new_sku, exclude_id=product.id):
                db.session.rollback()
                flash("SKU مستخدم بالفعل.", "danger")
                return render_template("shop/admin_product_form.html", form=form, product=product)
            if new_barcode and new_barcode != old_barcode and _exists_product_field(Product.barcode, new_barcode, exclude_id=product.id):
                db.session.rollback()
                flash("الباركود مستخدم بالفعل.", "danger")
                return render_template("shop/admin_product_form.html", form=form, product=product)
            if new_serial and new_serial != old_serial and _exists_product_field(Product.serial_no, new_serial, exclude_id=product.id):
                db.session.rollback()
                flash("الرقم التسلسلي مستخدم بالفعل.", "danger")
                return render_template("shop/admin_product_form.html", form=form, product=product)
            raw_price = (request.form.get("price") or "").strip()
            if raw_price != "":
                parsed = _as_decimal(raw_price)
                if parsed is not None and parsed >= 0:
                    product.price = parsed
            raw_online_price = (request.form.get("online_price") or "").strip()
            if raw_online_price != "":
                parsed_op = _as_decimal(raw_online_price)
                if parsed_op is not None and parsed_op >= 0:
                    product.online_price = parsed_op
            if not product.selling_price or _as_decimal(request.form.get("selling_price")) is None:
                product.selling_price = product.price
            if not StockLevel.query.filter_by(product_id=product.id).first():
                online_val = getattr(WarehouseType, "ONLINE").value if hasattr(WarehouseType, "ONLINE") else "ONLINE"
                default_wh = (
                    Warehouse.query.filter_by(is_active=True, online_is_default=True).first()
                    or Warehouse.query.filter_by(is_active=True, warehouse_type=online_val).first()
                    or Warehouse.query.filter_by(is_active=True).first()
                )
                if default_wh:
                    kwargs = {"product_id": product.id, "warehouse_id": default_wh.id, "quantity": 0}
                    if hasattr(StockLevel, "reserved_quantity"):
                        kwargs["reserved_quantity"] = 0
                    db.session.add(StockLevel(**kwargs))
            db.session.commit()
            flash("✅ تم التحديث", "success")
            return redirect(url_for("shop.admin_products"))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('خطأ', 'danger')
    return render_template("shop/admin_product_form.html", form=form, product=product)

@shop_bp.route("/admin/products/<int:pid>/update_fields", methods=["POST"], endpoint="admin_product_update_fields")
@super_admin_required
def admin_product_update_fields(pid):
    product = _get_or_404(Product, pid)
    payload = request.get_json(silent=True) or {}

    def _clean_img(v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if s.startswith("http://") or s.startswith("https://"):
            result = s
        elif s.startswith("/static/"):
            result = s[len("/static/"):]
        elif s.startswith("/"):
            result = s
        else:
            s = s.lstrip("./")
            if s.startswith("static/"):
                s = s[len("static/"):]
            # لا نضيف "products/" إذا كان المسار يحتوي على "uploads/products/"
            if not s.startswith("products/") and not s.startswith("uploads/"):
                s = "products/" + s
            result = s
        return result

    new_name = (payload.get("name") or "").strip() if "name" in payload else None
    new_price = _as_decimal(payload.get("price")) if "price" in payload else None
    new_online_price = _as_decimal(payload.get("online_price")) if "online_price" in payload else None
    new_online_image = _clean_img(payload.get("online_image")) if "online_image" in payload else None
    new_image = _clean_img(payload.get("image")) if "image" in payload else None

    changed = False
    if new_name:
        product.name = new_name[:255]
        changed = True
    if new_price is not None and new_price >= 0:
        product.price = new_price.quantize(Decimal("0.01"))
        if not product.selling_price:
            product.selling_price = product.price
        changed = True
    if new_online_price is not None and new_online_price >= 0:
        product.online_price = new_online_price.quantize(Decimal("0.01"))
        changed = True
    if new_online_image is not None:
        product.online_image = new_online_image or None
        changed = True
    if new_image is not None:
        product.image = new_image or None
        changed = True
    if not changed:
        return _resp("لا توجد حقول محدثة.", "warning", code=400, to="shop.admin_products")
    try:
        db.session.commit()
        return _resp(
            "تم تحديث بيانات المنتج.",
            "success",
            code=200,
            data={
                "id": product.id,
                "name": product.name,
                "price": float(product.price or 0),
                "online_price": (float(product.online_price) if getattr(product, "online_price", None) is not None else None),
                "online_image": getattr(product, "online_image", None),
                "image": getattr(product, "image", None),
            },
            to="shop.admin_products",
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return _resp("خطأ أثناء التحديث", "danger", code=400, to="shop.admin_products")

@shop_bp.route("/admin/products/<int:pid>/toggle_active", methods=["POST"], endpoint="admin_product_toggle_active")
@super_admin_required
def admin_product_toggle_active(pid):
    product = _get_or_404(Product, pid)
    product.is_active = not bool(product.is_active)
    try:
        db.session.commit()
        return _resp("تم تحديث حالة المنتج.", "success", code=200, to="shop.admin_products")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return _resp("خطأ أثناء التحديث", "danger", code=400, to="shop.admin_products")

@shop_bp.route("/admin/products/<int:pid>/delete", methods=["POST"], endpoint="admin_product_delete")
@super_admin_required
def admin_product_delete(pid):
    product = _get_or_404(Product, pid)
    has_links = (
        (product.preorders and len(product.preorders) > 0) or
        (product.online_preorder_items and len(product.online_preorder_items) > 0) or
        (product.online_cart_items and len(product.online_cart_items) > 0) or
        (product.sale_lines and len(product.sale_lines) > 0) or
        (product.transfers and len(product.transfers) > 0) or
        (product.shipment_items and len(product.shipment_items) > 0) or
        (product.exchange_transactions and len(product.exchange_transactions) > 0) or
        (product.service_parts and len(product.service_parts) > 0)
    )
    if has_links:
        flash("❌ لا يمكن حذف المنتج لأنه مرتبط بسجلات أخرى.", "danger")
        return redirect(url_for("shop.admin_products"))
    for sl in list(product.stock_levels or []):
        db.session.delete(sl)
    db.session.delete(product)
    try:
        db.session.commit()
        flash("تم حذف المنتج", "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('خطأ', 'danger')
    return redirect(url_for("shop.admin_products"))

@shop_bp.route("/payments/<int:op_id>/refund", methods=["POST"], endpoint="refund_payment")
@super_admin_required
def refund_payment(op_id: int):
    op = _get_or_404(OnlinePayment, op_id)
    if op.status != "SUCCESS":
        return _resp("لا يمكن استرجاع عملية غير ناجحة.", "warning", to="shop.admin_preorders")
    adp = _get_adapter(op.gateway)
    res = adp.refund(op)
    if not res.get("success"):
        return _resp("تعذر تنفيذ الاسترجاع.", "danger", to="shop.admin_preorders")
    try:
        with db.session.begin_nested():
            op.status = "REFUNDED"
            db.session.add(op)
        return _resp("✅ تم استرجاع الدفعة.", "success", to="shop.admin_preorders")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return _resp("خطأ أثناء الاسترجاع", "danger", to="shop.admin_preorders")

@shop_bp.route("/archive-preorder/<int:preorder_id>", methods=["POST"])
@login_required
def archive_preorder(preorder_id):
    """أرشفة حجز مسبق"""
    try:
        from models import Archive
        
        preorder = db.get_or_404(OnlinePreOrder, preorder_id)
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        # أرشفة الحجز المسبق
        archive = Archive.archive_record(
            record=preorder,
            reason=reason,
            user_id=current_user.id
        )
        
        # حذف الحجز المسبق الأصلي
        db.session.delete(preorder)
        db.session.commit()
        
        flash(f'تم أرشفة الحجز المسبق رقم {preorder.id} بنجاح', 'success')
        return redirect(url_for('shop.admin_preorders'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('shop.admin_preorders'))
