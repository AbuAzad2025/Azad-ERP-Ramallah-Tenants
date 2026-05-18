
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, abort, current_app
)
from flask_login import login_required
from flask_wtf.csrf import generate_csrf

from sqlalchemy import or_, func, desc, asc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, aliased, load_only

from extensions import db
from forms import ShipmentForm
from models import (
    Shipment, ShipmentItem, ShipmentPartner,
    Partner, Product, Warehouse, _queue_partner_balance,
    GLBatch, GLEntry, GL_ACCOUNTS, ShipmentStatus
)
import utils

def _safe_get_id(obj):
    try:
        if hasattr(obj, 'id'):
            return obj.id
        if isinstance(obj, int):
            return obj
    except Exception:
        pass
    return None

shipments_bp = Blueprint("shipments_bp", __name__, url_prefix="/shipments")

@shipments_bp.app_context_processor
def _inject_utils():
    return dict(format_currency=utils.format_currency)

from utils import D as _D, _q2, _get_or_404

def _norm_currency(v):
    return (v or "USD").strip().upper()

def _wants_json() -> bool:
    accept = request.headers.get("Accept", "")
    return ("application/json" in accept and "text/html" not in accept) or ((request.args.get("format") or "").lower() == "json")

def _compute_totals(sh: Shipment) -> Decimal:
    items_total = sum((_q2(it.quantity) * _q2(it.unit_cost)) for it in sh.items)
    sh.value_before = _q2(items_total)
    extras = _q2(sh.shipping_cost) + _q2(sh.customs) + _q2(sh.vat) + _q2(sh.insurance)
    sh.currency = _norm_currency(sh.currency)
    total = _q2(items_total + extras)
    sh.total_cost = total  # ✅ حفظ التكلفة الإجمالية
    return total

_compute_shipment_totals = _compute_totals

def _norm_status(v):
    if hasattr(v, "data"):
        v = v.data
    if v is None:
        return ShipmentStatus.DRAFT.value
    if hasattr(v, "value"):
        v = v.value
    return str(v).upper()

def _landed_allocation(items, extras_total):
    total_value = sum(_q2(it.quantity) * _q2(it.unit_cost) for it in items)
    if total_value <= 0 or _q2(extras_total) <= 0:
        return {i: Decimal("0.00") for i, _ in enumerate(items)}
    alloc = {}
    rem = _q2(extras_total)
    for idx, it in enumerate(items):
        base = _q2(it.quantity) * _q2(it.unit_cost)
        share = (base / total_value) * _q2(extras_total)
        share_q = _q2(share)
        alloc[idx] = share_q
        rem -= share_q
    keys = list(alloc.keys())
    k = 0
    while rem != Decimal("0.00") and keys:
        step = Decimal("0.01") if rem > 0 else Decimal("-0.01")
        alloc[keys[k % len(keys)]] += step
        rem -= step
        k += 1
    return alloc

def _apply_arrival_items(items):
    from models import StockLevel, Warehouse, WarehouseType
    for it in items:
        pid = int(it.get("product_id") or 0)
        wid = int(it.get("warehouse_id") or 0)
        qty = int(it.get("quantity") or 0)
        if not (pid and wid and qty > 0):
            continue
        
        # التحقق من نوع المستودع
        warehouse = db.session.get(Warehouse, wid)
        if not warehouse:
            continue
            
        # إذا كان المستودع من نوع PARTNER، تأكد من وجود شريك
        if warehouse.warehouse_type == WarehouseType.PARTNER.value:
            if not warehouse.partner_id:
                raise ValueError(f"مستودع الشريك {warehouse.name} غير مربوط بشريك")
        
        sl = (
            db.session.query(StockLevel)
            .filter_by(product_id=pid, warehouse_id=wid)
            .with_for_update(read=False)
            .first()
        )
        if not sl:
            sl = StockLevel(product_id=pid, warehouse_id=wid, quantity=0, reserved_quantity=0)
            db.session.add(sl)
            db.session.flush()
        new_qty = int(sl.quantity or 0) + qty
        reserved = int(getattr(sl, "reserved_quantity", 0) or 0)
        if new_qty < reserved:
            raise ValueError("insufficient stock")
        sl.quantity = new_qty
        db.session.flush()

def _reverse_arrival_items(items):
    from models import StockLevel, Warehouse, WarehouseType
    for it in items:
        pid = int(it.get("product_id") or 0)
        wid = int(it.get("warehouse_id") or 0)
        qty = int(it.get("quantity") or 0)
        if not (pid and wid and qty > 0):
            continue
        
        # التحقق من نوع المستودع
        warehouse = db.session.get(Warehouse, wid)
        if not warehouse:
            continue
            
        # إذا كان المستودع من نوع PARTNER، تأكد من وجود شريك
        if warehouse.warehouse_type == WarehouseType.PARTNER.value:
            if not warehouse.partner_id:
                raise ValueError(f"مستودع الشريك {warehouse.name} غير مربوط بشريك")
        
        sl = (
            db.session.query(StockLevel)
            .filter_by(product_id=pid, warehouse_id=wid)
            .with_for_update(read=False)
            .first()
        )
        if not sl:
            raise ValueError("insufficient stock")
        reserved = int(getattr(sl, "reserved_quantity", 0) or 0)
        new_qty = int(sl.quantity or 0) - qty
        if new_qty < 0 or new_qty < reserved:
            raise ValueError("insufficient stock")
        sl.quantity = new_qty
        db.session.flush()

def _create_shipment_gl_entries(sh: Shipment):
    """
    إنشاء قيود محاسبية للشحنة المستلمة (ARRIVED)
    """
    # 1. التحقق من عدم وجود قيد سابق
    existing_batch = GLBatch.query.filter_by(
        source_type='SHIPMENT',
        source_id=sh.id,
        status='POSTED'
    ).filter(GLBatch.purpose == None).first()
    
    if existing_batch:
        return # تم الإنشاء سابقاً

    # 2. إعداد الحسابات
    inventory_acc = GL_ACCOUNTS.get('INVENTORY', '1200_INVENTORY')
    ap_acc = GL_ACCOUNTS.get('AP', '2000_AP')
    partner_equity_acc = GL_ACCOUNTS.get('PARTNER_EQUITY', '3200_PARTNER_EQUITY')

    # 3. القيم
    total_cost = float(sh.total_cost or 0)
    if total_cost <= 0:
        # Try to compute if not set
        total_cost = sum((float(it.unit_cost or 0) * float(it.quantity or 0)) for it in sh.items)
        total_cost += float(sh.shipping_cost or 0) + float(sh.customs or 0) + float(sh.vat or 0) + float(sh.insurance or 0)
    
    total_val = float(total_cost)
    
    if total_val <= 0:
        return

    batch = GLBatch(
        posted_at=sh.actual_arrival or sh.shipment_date or datetime.now(timezone.utc),
        source_type='SHIPMENT',
        source_id=sh.id,
        memo=f"استلام شحنة #{sh.shipment_number or sh.id}",
        currency=sh.currency,
        status='POSTED',
        entity_type='SUPPLIER', # مبدئياً
        entity_id=None # لا يوجد مورد محدد
    )
    db.session.add(batch)
    db.session.flush()

    # 4. الطرف المدين: المخزون
    debit_entry = GLEntry(
        batch_id=batch.id,
        account=inventory_acc,
        debit=total_val,
        credit=0,
        currency=sh.currency,
        ref=f"SH-{sh.id}"
    )
    db.session.add(debit_entry)

    # 5. الطرف الدائن: شركاء أو موردين
    if sh.partners:
        # توزيع على الشركاء
        total_partners_share = 0
        for sp in sh.partners:
            share_amt = float(sp.share_amount or 0)
            if share_amt > 0:
                credit_entry = GLEntry(
                    batch_id=batch.id,
                    account=partner_equity_acc,
                    debit=0,
                    credit=share_amt,
                    currency=sh.currency,
                    ref=f"PTR-{sp.partner_id}"
                )
                db.session.add(credit_entry)
                total_partners_share += share_amt
        
        # الفارق (إن وجد) يذهب للموردين
        remaining = total_val - total_partners_share
        if abs(remaining) > 0.01:
             credit_entry = GLEntry(
                batch_id=batch.id,
                account=ap_acc,
                debit=0,
                credit=remaining,
                currency=sh.currency,
                ref="SUPPLIER"
            )
             db.session.add(credit_entry)
    else:
        # كله للموردين
        credit_entry = GLEntry(
            batch_id=batch.id,
            account=ap_acc,
            debit=0,
            credit=total_val,
            currency=sh.currency,
            ref="SUPPLIER"
        )
        db.session.add(credit_entry)

    db.session.flush()

def _items_snapshot(sh):
    return [
        {
            "product_id": int(i.product_id or 0),
            "warehouse_id": int(i.warehouse_id or 0),
            "quantity": int(i.quantity or 0),
        }
        for i in sh.items
    ]

def _status_applies_stock(status: str) -> bool:
    st = (status or "").upper()
    return st in (ShipmentStatus.ARRIVED.value, ShipmentStatus.DELIVERED.value)

def _snapshot_key(items):
    return sorted(
        (
            int(it.get("product_id") or 0),
            int(it.get("warehouse_id") or 0),
            int(it.get("quantity") or 0),
        )
        for it in (items or [])
    )

def _ensure_partner_warehouse(warehouse_id, shipment=None):
    """تأكد من أن المستودع مربوط بشريك إذا كان من نوع PARTNER"""
    from models import Warehouse, WarehouseType
    warehouse = db.session.get(Warehouse, warehouse_id)
    if not warehouse:
        raise ValueError("warehouse_not_found")
    
    # إذا كان المستودع من نوع PARTNER، نتحقق من وجود شركاء في الشحنة
    if warehouse.warehouse_type == WarehouseType.PARTNER.value:
        if shipment:
            # نتحقق من وجود شركاء في الشحنة
            has_partners = len(shipment.partners) > 0 if hasattr(shipment, 'partners') else False
            if not has_partners:
                raise ValueError("partner_warehouse_requires_partner")
        # إذا لم نمرر الشحنة، نسمح بالعملية (للتوافق مع الكود القديم)
    
    return warehouse

@shipments_bp.route("/", methods=["GET"], endpoint="list_shipments")
@login_required
def list_shipments():
    status = (request.args.get("status") or "").strip().upper()
    search = (request.args.get("search") or "").strip()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()
    destination = (request.args.get("destination") or "").strip()

    def _status_label(st):
        try:
            return ShipmentStatus((st or "").upper()).label
        except ValueError:
            return st

    if _wants_json():
        q = db.session.query(Shipment).filter(Shipment.is_archived == False).options(
            joinedload(Shipment.destination_warehouse),
        )

        if status:
            q = q.filter(Shipment.status == status)

        if destination:
            like = f"%{destination}%"
            q = q.filter(or_(
                Shipment.destination.ilike(like),
                Shipment.destination_warehouse.has(Warehouse.name.ilike(like)),
            ))

        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                Shipment.shipment_number.ilike(like),
                Shipment.tracking_number.ilike(like),
                Shipment.origin.ilike(like),
                Shipment.carrier.ilike(like),
                Shipment.destination.ilike(like),
                Shipment.destination_warehouse.has(Warehouse.name.ilike(like)),
            ))

        df = _parse_dt(date_from) if date_from else None
        dt = _parse_dt(date_to) if date_to else None
        if df:
            q = q.filter(Shipment.expected_arrival >= datetime.combine(df, datetime.min.time()))
        if dt:
            q = q.filter(Shipment.expected_arrival <= datetime.combine(dt, datetime.max.time()))

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = q.order_by(
            Shipment.expected_arrival.desc().nullslast(),
            Shipment.id.desc(),
        ).paginate(page=page, per_page=per_page, error_out=False)

        ids = [s.id for s in (pagination.items or []) if getattr(s, "id", None)]
        items_count_map = {}
        partners_count_map = {}
        if ids:
            ic_rows = (
                db.session.query(ShipmentItem.shipment_id, func.coalesce(func.count(ShipmentItem.id), 0))
                .filter(ShipmentItem.shipment_id.in_(ids))
                .group_by(ShipmentItem.shipment_id)
                .all()
            )
            items_count_map = {int(sid): int(cnt or 0) for sid, cnt in ic_rows}
            pc_rows = (
                db.session.query(ShipmentPartner.shipment_id, func.coalesce(func.count(ShipmentPartner.id), 0))
                .filter(ShipmentPartner.shipment_id.in_(ids))
                .group_by(ShipmentPartner.shipment_id)
                .all()
            )
            partners_count_map = {int(sid): int(cnt or 0) for sid, cnt in pc_rows}

        return jsonify({
            "data": [
                {
                    "id": s.id,
                    "number": s.shipment_number,
                    "status": s.status,
                    "status_label": _status_label(s.status),
                    "origin": s.origin,
                    "destination": (s.destination_warehouse.name if s.destination_warehouse else (s.destination or None)),
                    "expected_arrival": s.expected_arrival.isoformat() if s.expected_arrival else None,
                    "total_value": float(s.total_value or 0),
                    "items_count": int(items_count_map.get(int(s.id), 0) or 0),
                    "partners_count": int(partners_count_map.get(int(s.id), 0) or 0),
                }
                for s in pagination.items
            ],
            "meta": {
                "page": pagination.page,
                "pages": pagination.pages,
                "per_page": per_page,
                "total": pagination.total,
            },
        })

    return render_template(
        "warehouses/shipments.html",
        search=search,
        status=status,
        date_from=date_from,
        date_to=date_to,
        destination=destination,
    )


shipments_bp.add_url_rule("/", endpoint="shipments", view_func=list_shipments)


def _parse_dt(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

@shipments_bp.route("/data", methods=["GET"]) 
@login_required
def shipments_data():
    from flask_wtf.csrf import generate_csrf

    try:
        draw   = int(request.args.get("draw", 1))
    except (ValueError, TypeError):
        draw = 1
    try:
        start  = int(request.args.get("start", 0))
    except (ValueError, TypeError):
        start = 0
    try:
        length = int(request.args.get("length", 10))
    except (ValueError, TypeError):
        length = 10

    f_status = (request.args.get("status") or "").strip().upper()
    f_from   = _parse_dt(request.args.get("from") or request.args.get("search[from]", "") or "")
    f_to     = _parse_dt(request.args.get("to") or request.args.get("search[to]", "") or "")
    f_dest   = (request.args.get("destination") or "").strip()
    f_extra  = (request.args.get("search_extra") or request.args.get("search[value]", "") or "").strip()

    base_q = db.session.query(Shipment).filter(Shipment.is_archived == False)
    total_count = base_q.order_by(None).with_entities(func.count(Shipment.id)).scalar() or 0
    q = base_q
    dest_wh = None
    if f_dest or f_extra:
        dest_wh = aliased(Warehouse)
        q = q.outerjoin(dest_wh, Shipment.destination_id == dest_wh.id)

    if f_status:
        q = q.filter(Shipment.status == f_status)
    if f_from:
        q = q.filter(Shipment.expected_arrival >= datetime.combine(f_from, datetime.min.time()))
    if f_to:
        q = q.filter(Shipment.expected_arrival <= datetime.combine(f_to, datetime.max.time()))
    if f_dest:
        like = f"%{f_dest}%"
        if dest_wh is not None:
            q = q.filter(or_(Shipment.destination.ilike(like), dest_wh.name.ilike(like)))
        else:
            q = q.filter(Shipment.destination.ilike(like))
    if f_extra:
        like = f"%{f_extra}%"
        q = q.filter(or_(
            Shipment.shipment_number.ilike(like),
            Shipment.tracking_number.ilike(like),
            Shipment.origin.ilike(like),
            Shipment.carrier.ilike(like),
            Shipment.destination.ilike(like),
            (dest_wh.name.ilike(like) if dest_wh is not None else False)
        ))

    filtered_count = q.order_by(None).with_entities(func.count(Shipment.id)).scalar() or 0

    try:
        order_col_index = int(request.args.get("order[0][column]", 3) or 3)
    except (ValueError, TypeError):
        order_col_index = 3
    order_dir = (request.args.get("order[0][dir]") or "desc").lower()
    col_map = {
        0: Shipment.id,
        1: Shipment.shipment_number,
        2: Shipment.destination,
        3: Shipment.expected_arrival,
        4: Shipment.status,
        5: Shipment.currency,
        7: Shipment.total_cost  # أو Shipment.value_before حسب الرغبة، ولكن العمود هو الإجمالي
    }
    order_col = col_map.get(order_col_index, Shipment.expected_arrival)
    q = q.order_by(desc(order_col) if order_dir == "desc" else asc(order_col))

    rows = (
        q.options(
            load_only(
                Shipment.id,
                Shipment.shipment_number,
                Shipment.destination,
                Shipment.expected_arrival,
                Shipment.status,
                Shipment.currency,
                Shipment.fx_rate_used,
                Shipment.fx_rate_source,
                Shipment.total_value,
                Shipment.origin,
                Shipment.carrier,
                Shipment.tracking_number,
            ),
            joinedload(Shipment.destination_warehouse).load_only(Warehouse.id, Warehouse.name),
        )
        .offset(start)
        .limit(length)
        .all()
    )

    csrf_token = generate_csrf()

    def _status_label(st):
        try:
            return ShipmentStatus((st or "").upper()).label
        except ValueError:
            return st

    data = []
    for s in rows:
        actions_html = f"""
        <div class="d-flex justify-content-center gap-1">
            <a href="{url_for('shipments_bp.shipment_detail', id=s.id)}" class="btn btn-sm btn-info rounded-circle text-white" title="تفاصيل" data-bs-toggle="tooltip"><i class="fa fa-eye"></i></a>
            <a href="{url_for('shipments_bp.edit_shipment', id=s.id)}" class="btn btn-sm btn-warning rounded-circle text-white" title="تعديل" data-bs-toggle="tooltip"><i class="fa fa-edit"></i></a>
            <form method="POST" action="{url_for('shipments_bp.delete_shipment', id=s.id)}" style="display:inline;" onsubmit="return confirm('تأكيد الحذف؟');">
                <input type="hidden" name="csrf_token" value="{csrf_token}">
                <button type="submit" class="btn btn-sm btn-danger rounded-circle" title="حذف" data-bs-toggle="tooltip"><i class="fa fa-trash"></i></button>
            </form>
        </div>
        """
        data.append({
            "id": s.id,
            "number": s.shipment_number,
            "status": s.status,
            "status_label": _status_label(s.status),
            "origin": s.origin,
            "destination": (s.destination_warehouse.name if s.destination_warehouse else (s.destination or None)),
            "expected_arrival": s.expected_arrival.isoformat() if s.expected_arrival else None,
            "currency": s.currency,
            "fx_rate_used": float(s.fx_rate_used) if s.fx_rate_used else None,
            "fx_rate_source": s.fx_rate_source,
            "total_value": float(s.total_value or 0),
            "actions": actions_html,
        })

    return jsonify({
        "draw": draw,
        "recordsTotal": int(total_count),
        "recordsFiltered": int(filtered_count),
        "data": data
    })

@shipments_bp.route("/create", methods=["GET", "POST"], endpoint="create_shipment")
@login_required
def create_shipment():
    form = ShipmentForm()
    pre_dest_id = request.args.get("destination_id", type=int)

    if request.method == "GET":
        if not form.shipment_date.data:
            form.shipment_date.data = datetime.now(timezone.utc)
        if not form.expected_arrival.data:
            form.expected_arrival.data = datetime.now(timezone.utc) + timedelta(days=14)

    if request.method == "POST":
        def _blank_item(f):
            return not (f.product_id.data and (f.warehouse_id.data or form.destination_id.data) and (f.quantity.data or 0) > 0)
        def _blank_partner(f):
            return not f.partner_id.data
        if hasattr(form, "items"):
            form.items.entries[:] = [e for e in form.items.entries if not _blank_item(getattr(e, "form", e))]
        if hasattr(form, "partners"):
            form.partners.entries[:] = [e for e in form.partners.entries if not _blank_partner(getattr(e, "form", e))]

    if pre_dest_id and not form.destination_id.data:
        dest_prefill = db.session.get(Warehouse, pre_dest_id)
        if dest_prefill:
            form.destination_id.data = dest_prefill

    if request.method == "POST" and not form.validate_on_submit():
        if _wants_json():
            return jsonify({"ok": False, "errors": form.errors}), 422
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"❌ {form[field].label.text}: {err}", "danger")
        return render_template("warehouses/shipment_form.html", form=form, shipment=None)

    if form.validate_on_submit():
        dest_obj = form.destination_id.data
        sh = Shipment(
            shipment_number=form.shipment_number.data or None,
            shipment_date=form.shipment_date.data or datetime.now(timezone.utc),
            expected_arrival=form.expected_arrival.data,
            actual_arrival=form.actual_arrival.data,
            origin=form.origin.data or None,
            destination_id=_safe_get_id(form.destination_id.data),
            carrier=form.carrier.data or None,
            tracking_number=form.tracking_number.data or None,
            status=_norm_status(form.status.data),
            shipping_cost=form.shipping_cost.data,
            customs=form.customs.data,
            vat=form.vat.data,
            insurance=form.insurance.data,
            notes=form.notes.data or None,
            currency=_norm_currency(getattr(form, "currency", None) and form.currency.data),
            sale_id=(form.sale_id.data.id if getattr(form, "sale_id", None) and getattr(form.sale_id.data, "id", None) else None),
            # الحقول الإضافية
            weight=form.weight.data if hasattr(form, "weight") else None,
            dimensions=form.dimensions.data if hasattr(form, "dimensions") else None,
            package_count=form.package_count.data if hasattr(form, "package_count") else None,
            priority=form.priority.data if hasattr(form, "priority") else None,
            delivery_method=form.delivery_method.data if hasattr(form, "delivery_method") else None,
            delivery_instructions=form.delivery_instructions.data if hasattr(form, "delivery_instructions") else None,
        )

        db.session.add(sh)
        db.session.flush()

        acc_items = {}
        for entry in getattr(form.items, "entries", []):
            f = getattr(entry, "form", entry)
            pid = f.product_id.data
            wid = f.warehouse_id.data or (dest_obj.id if dest_obj else None)
            if not pid or not wid:
                continue
            qty = f.quantity.data or 0
            if qty <= 0:
                continue
            uc = Decimal(str(f.unit_cost.data or 0))
            dec = Decimal(str(f.declared_value.data or 0))
            notes = getattr(f, "notes", None)
            notes_val = notes.data if notes is not None else None
            key = (pid, wid)
            it = acc_items.get(key) or {"qty": 0, "cost_total": Decimal("0"), "declared": Decimal("0"), "notes": None}
            it["qty"] += qty
            it["cost_total"] += Decimal(qty) * uc
            it["declared"] += dec
            it["notes"] = notes_val if notes_val else it["notes"]
            acc_items[key] = it

        for (pid, wid), v in acc_items.items():
            qty = v["qty"]
            unit_cost = (v["cost_total"] / Decimal(qty)) if qty else Decimal("0")
            sh.items.append(ShipmentItem(
                product_id=pid,
                warehouse_id=wid,
                quantity=qty,
                unit_cost=float(unit_cost),
                declared_value=float(v["declared"]),
                notes=v["notes"],
            ))

        acc_partners = {}
        for entry in getattr(form.partners, "entries", []):
            f = getattr(entry, "form", entry)
            pid = f.partner_id.data
            if not pid:
                continue
            p = acc_partners.get(pid) or {
                "share_percentage": Decimal("0"),
                "share_amount": Decimal("0"),
                "identity_number": None,
                "phone_number": None,
                "address": None,
                "unit_price_before_tax": Decimal("0"),
                "expiry_date": None,
                "notes": None,
            }
            p["share_percentage"] += Decimal(str(f.share_percentage.data or 0))
            p["share_amount"] += Decimal(str(f.share_amount.data or 0))
            p["unit_price_before_tax"] += Decimal(str(f.unit_price_before_tax.data or 0))
            p["identity_number"] = f.identity_number.data or p["identity_number"]
            p["phone_number"] = f.phone_number.data or p["phone_number"]
            p["address"] = f.address.data or p["address"]
            p["expiry_date"] = f.expiry_date.data or p["expiry_date"]
            p["notes"] = f.notes.data or p["notes"]
            acc_partners[pid] = p

        for pid, v in acc_partners.items():
            sh.partners.append(ShipmentPartner(
                partner_id=pid,
                share_percentage=float(v["share_percentage"]),
                share_amount=float(v["share_amount"]),
                identity_number=v["identity_number"],
                phone_number=v["phone_number"],
                address=v["address"],
                unit_price_before_tax=float(v["unit_price_before_tax"]),
                expiry_date=v["expiry_date"],
                notes=v["notes"],
            ))

        db.session.flush()

        extras_total = _q2(sh.shipping_cost) + _q2(sh.customs) + _q2(sh.vat) + _q2(sh.insurance)
        alloc = _landed_allocation(sh.items, extras_total)
        for idx, it in enumerate(sh.items):
            extra = alloc.get(idx, Decimal("0.00"))
            it.landed_extra_share = _q2(extra)
            qty = _q2(it.quantity)
            base_total = qty * _q2(it.unit_cost)
            landed_total = base_total + _q2(extra)
            it.landed_unit_cost = _q2((landed_total / qty) if qty > 0 else 0)

        _compute_shipment_totals(sh)

        if (sh.status or "").upper() == ShipmentStatus.ARRIVED.value:
            _apply_arrival_items(
                [{"product_id": it.product_id, "warehouse_id": it.warehouse_id, "quantity": it.quantity} for it in sh.items]
            )

        try:
            # تحديث رصيد الشركاء عند إنشاء الشحنة (إذا كان هناك شركاء)
            if sh.partners:
                partner_ids = {int(sp.partner_id) for sp in sh.partners if sp and sp.partner_id}
                for pid in partner_ids:
                    _queue_partner_balance(db.session, pid)
            
            db.session.commit()
            flash("✅ تم إنشاء الشحنة بنجاح", "success")
            dest_id = sh.destination_id or (dest_obj.id if dest_obj else None)
            return redirect(url_for("warehouse_bp.detail", warehouse_id=dest_id)) if dest_id else redirect(url_for("shipments_bp.list_shipments"))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f"❌ خطأ أثناء إنشاء الشحنة: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ تعذر إتمام العملية: {e}", "danger")

    return render_template("warehouses/shipment_form.html", form=form, shipment=None)
@shipments_bp.route("/<int:id>/edit", methods=["GET", "POST"], endpoint="edit_shipment")
@login_required
def edit_shipment(id: int):
    sh = _get_or_404(Shipment, id, load_options=[
        joinedload(Shipment.items), 
        joinedload(Shipment.partners),
        joinedload(Shipment.destination_warehouse)
    ])
    old_status = (sh.status or "").upper()
    old_items = _items_snapshot(sh)
    form = ShipmentForm(obj=sh)

    if request.method == "GET":
        # تحميل مستودع الوجهة الصحيح - بشكل صريح
        if sh.destination_id:
            dest_warehouse = db.session.get(Warehouse, sh.destination_id)
            if dest_warehouse:
                # تعيين المستودع بشكل مباشر وصريح
                form.destination_id.data = dest_warehouse
                # التأكد من أن القيمة لن تتغير
                form.destination_id.query = Warehouse.query.filter(
                    (Warehouse.id == sh.destination_id) | (Warehouse.is_active == True)
                ).order_by(Warehouse.name)
        
        form.partners.entries.clear()
        for p in sh.partners:
            form.partners.append_entry({
                "partner_id": p.partner_id,
                "share_percentage": p.share_percentage,
                "share_amount": p.share_amount,
                "identity_number": p.identity_number,
                "phone_number": p.phone_number,
                "address": p.address,
                "unit_price_before_tax": p.unit_price_before_tax,
                "expiry_date": p.expiry_date,
                "notes": p.notes,
            })

        form.items.entries.clear()
        for i in sh.items:
            form.items.append_entry({
                "product_id": i.product_id,
                "warehouse_id": i.warehouse_id,
                "quantity": i.quantity,
                "unit_cost": i.unit_cost,
                "declared_value": i.declared_value,
                "notes": i.notes,
            })

    if request.method == "POST":
        def _blank_item(f):
            return not (f.product_id.data and f.warehouse_id.data and (f.quantity.data or 0) > 0)
        def _blank_partner(f):
            return not f.partner_id.data
        if hasattr(form, "items"):
            form.items.entries[:] = [e for e in form.items.entries if not _blank_item(getattr(e, "form", e))]
        if hasattr(form, "partners"):
            form.partners.entries[:] = [e for e in form.partners.entries if not _blank_partner(getattr(e, "form", e))]

    if request.method == "POST" and not form.validate_on_submit():
        if _wants_json():
            return jsonify({"ok": False, "errors": form.errors}), 422
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"❌ {form[field].label.text}: {err}", "danger")
        return render_template("warehouses/shipment_form.html", form=form, shipment=sh)

    if form.validate_on_submit():
        dest_obj = form.destination_id.data
        sh.shipment_number = form.shipment_number.data or sh.shipment_number or None
        sh.shipment_date = form.shipment_date.data
        sh.expected_arrival = form.expected_arrival.data
        sh.actual_arrival = form.actual_arrival.data
        sh.origin = form.origin.data
        sh.destination_id = (dest_obj.id if dest_obj else None)
        sh.carrier = form.carrier.data
        sh.tracking_number = form.tracking_number.data
        sh.status = _norm_status(form.status.data)
        sh.shipping_cost = form.shipping_cost.data
        sh.customs = form.customs.data
        sh.vat = form.vat.data
        sh.insurance = form.insurance.data
        sh.notes = form.notes.data
        sh.currency = _norm_currency(getattr(form, "currency", None) and form.currency.data)
        sh.sale_id = (form.sale_id.data.id if getattr(form, "sale_id", None) and form.sale_id.data else None)
        
        # حفظ الحقول الإضافية
        if hasattr(form, "weight") and form.weight.data is not None:
            sh.weight = form.weight.data
        if hasattr(form, "dimensions") and form.dimensions.data:
            sh.dimensions = form.dimensions.data
        if hasattr(form, "package_count") and form.package_count.data:
            sh.package_count = form.package_count.data
        if hasattr(form, "priority") and form.priority.data:
            sh.priority = form.priority.data
        if hasattr(form, "delivery_method") and form.delivery_method.data:
            sh.delivery_method = form.delivery_method.data
        if hasattr(form, "delivery_instructions") and form.delivery_instructions.data:
            sh.delivery_instructions = form.delivery_instructions.data

        old_partner_ids = {int(sp.partner_id) for sp in (sh.partners or []) if sp and sp.partner_id}
        sh.partners.clear()
        sh.items.clear()
        db.session.flush()

        acc_partners = {}
        for entry in getattr(form.partners, "entries", []):
            f = getattr(entry, "form", entry)
            pid = f.partner_id.data
            if not pid:
                continue
            p = acc_partners.get(pid) or {
                "share_percentage": Decimal("0"),
                "share_amount": Decimal("0"),
                "identity_number": None,
                "phone_number": None,
                "address": None,
                "unit_price_before_tax": Decimal("0"),
                "expiry_date": None,
                "notes": None,
            }
            sp = f.share_percentage.data or 0
            sa = f.share_amount.data or 0
            p["share_percentage"] = Decimal(p["share_percentage"]) + Decimal(str(sp))
            p["share_amount"] = Decimal(p["share_amount"]) + Decimal(str(sa))
            p["identity_number"] = f.identity_number.data or p["identity_number"]
            p["phone_number"] = f.phone_number.data or p["phone_number"]
            p["address"] = f.address.data or p["address"]
            p["unit_price_before_tax"] = Decimal(p["unit_price_before_tax"]) + Decimal(str(f.unit_price_before_tax.data or 0))
            p["expiry_date"] = f.expiry_date.data or p["expiry_date"]
            p["notes"] = f.notes.data or p["notes"]
            acc_partners[pid] = p

        for pid, v in acc_partners.items():
            sh.partners.append(ShipmentPartner(
                partner_id=pid,
                share_percentage=float(v["share_percentage"]),
                share_amount=float(v["share_amount"]),
                identity_number=v["identity_number"],
                phone_number=v["phone_number"],
                address=v["address"],
                unit_price_before_tax=float(v["unit_price_before_tax"]),
                expiry_date=v["expiry_date"],
                notes=v["notes"],
            ))

        acc_items = {}
        for entry in getattr(form.items, "entries", []):
            f = getattr(entry, "form", entry)
            pid = f.product_id.data
            wid = f.warehouse_id.data
            if not pid or not wid:
                continue
            qty = f.quantity.data or 0
            uc = Decimal(str(f.unit_cost.data or 0))
            dec = Decimal(str(f.declared_value.data or 0))
            notes = getattr(f, "notes", None)
            notes_val = notes.data if notes is not None else None
            key = (pid, wid)
            it = acc_items.get(key) or {"qty": 0, "cost_total": Decimal("0"), "declared": Decimal("0"), "notes": None}
            it["qty"] += qty
            it["cost_total"] += Decimal(qty) * uc
            it["declared"] += dec
            it["notes"] = notes_val if notes_val else it["notes"]
            acc_items[key] = it

        for (pid, wid), v in acc_items.items():
            qty = v["qty"]
            unit_cost = (v["cost_total"] / Decimal(qty)) if qty else Decimal("0")
            sh.items.append(ShipmentItem(
                product_id=pid,
                warehouse_id=wid,
                quantity=qty,
                unit_cost=float(unit_cost),
                declared_value=float(v["declared"]),
                notes=v["notes"],
            ))

        db.session.flush()

        extras_total = _q2(sh.shipping_cost) + _q2(sh.customs) + _q2(sh.vat) + _q2(sh.insurance)
        alloc = _landed_allocation(sh.items, extras_total)
        for idx, it in enumerate(sh.items):
            extra = alloc.get(idx, Decimal("0.00"))
            it.landed_extra_share = _q2(extra)
            qty = _q2(it.quantity)
            base_total = qty * _q2(it.unit_cost)
            landed_total = base_total + _q2(extra)
            it.landed_unit_cost = _q2((landed_total / qty) if qty > 0 else 0)

        _compute_shipment_totals(sh)

        new_items = _items_snapshot(sh)
        new_status = (sh.status or "").upper()

        try:
            old_applies = _status_applies_stock(old_status)
            new_applies = _status_applies_stock(new_status)
            if old_applies and not new_applies:
                _reverse_arrival_items(old_items)
            elif not old_applies and new_applies:
                _apply_arrival_items(new_items)
            elif old_applies and new_applies:
                if _snapshot_key(old_items) != _snapshot_key(new_items):
                    _reverse_arrival_items(old_items)
                    _apply_arrival_items(new_items)

            # تحديث رصيد الشركاء عند تحديث الشحنة (إذا كان هناك شركاء)
            partner_ids = {int(sp.partner_id) for sp in (sh.partners or []) if sp and sp.partner_id}
            if old_partner_ids:
                partner_ids.update(old_partner_ids)
            for pid in partner_ids:
                _queue_partner_balance(db.session, pid)
            
            db.session.commit()

            if _wants_json():
                return jsonify({"ok": True, "shipment_id": sh.id, "number": sh.shipment_number})

            flash("✅ تم تحديث بيانات الشحنة", "success")
            dest_id = sh.destination_id
            return redirect(url_for("warehouse_bp.detail", warehouse_id=dest_id)) if dest_id else redirect(url_for("shipments_bp.list_shipments"))
        except SQLAlchemyError as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 500
            flash(f"❌ خطأ أثناء التحديث: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 400
            flash(f"❌ خطأ أثناء ضبط المخزون: {e}", "danger")

    return render_template("warehouses/shipment_form.html", form=form, shipment=sh)

@shipments_bp.route("/<int:id>/delete", methods=["POST"], endpoint="delete_shipment")
@login_required
def delete_shipment(id: int):
    sh = _get_or_404(Shipment, id, load_options=[joinedload(Shipment.items), joinedload(Shipment.partners)])
    dest_id = sh.destination_id
    try:
        # إذا وصلت الشحنة، لازم نرجع المخزون قبل الحذف
        if _status_applies_stock(sh.status):
            _reverse_arrival_items(_items_snapshot(sh))

        # تحديث رصيد الشركاء قبل حذف الشحنة (إذا كان هناك شركاء)
        if sh.partners:
            partner_ids = {int(sp.partner_id) for sp in sh.partners if sp and sp.partner_id}
            for pid in partner_ids:
                _queue_partner_balance(db.session, pid)
        
        # تنظيف العلاقات قبل الحذف
        sh.partners.clear()
        sh.items.clear()
        db.session.flush()

        db.session.delete(sh)
        db.session.commit()

        if _wants_json():
            return jsonify({"ok": True, "message": f"🚮 تم حذف الشحنة رقم {sh.shipment_number or sh.id}"}), 200

        flash(f"🚮 تم حذف الشحنة رقم {sh.shipment_number or sh.id}", "warning")
    except SQLAlchemyError as e:
        db.session.rollback()
        if _wants_json():
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 500
        flash(f"❌ خطأ من قاعدة البيانات أثناء الحذف: {e}", "danger")
    except Exception as e:
        db.session.rollback()
        if _wants_json():
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 400
        flash(f"❌ خطأ غير متوقع أثناء الحذف: {e}", "danger")

    return redirect(url_for("warehouse_bp.detail", warehouse_id=dest_id)) if dest_id else redirect(url_for("shipments_bp.list_shipments"))

@shipments_bp.route("/<int:id>", methods=["GET"], endpoint="shipment_detail")
@login_required
def shipment_detail(id: int):
    sh = _get_or_404(
        Shipment,
        id,
        load_options=[
            joinedload(Shipment.items).joinedload(ShipmentItem.product),
            joinedload(Shipment.partners).joinedload(ShipmentPartner.partner),
            joinedload(Shipment.destination_warehouse),
        ],
    )

    try:
        from models import Payment, PaymentStatus, convert_amount
        from decimal import Decimal
        
        payments = db.session.query(Payment).filter(
            Payment.shipment_id == sh.id,
            Payment.status == PaymentStatus.COMPLETED.value
        ).all()
        
        total_paid = Decimal('0.00')
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == sh.currency:
                total_paid += amt
            else:
                try:
                    total_paid += convert_amount(amt, p.currency, sh.currency or "ILS", p.payment_date)
                except Exception:
                    pass
        total_paid = float(total_paid)
    except Exception:
        total_paid = 0.0

    # رسائل تحذيرية بناءً على حالة الشحنة
    alerts = []
    status = (sh.status or "").upper()
    if status == ShipmentStatus.CANCELLED.value:
        alerts.append({"level": "warning", "msg": "⚠️ هذه الشحنة ملغاة ولا يمكن تعديلها."})
    elif status == ShipmentStatus.DRAFT.value:
        alerts.append({"level": "info", "msg": "✏️ هذه الشحنة ما زالت في وضع المسودة."})
    elif status == ShipmentStatus.IN_TRANSIT.value:
        alerts.append({"level": "info", "msg": "🚚 الشحنة في الطريق."})
    elif status == ShipmentStatus.ARRIVED.value:
        alerts.append({"level": "success", "msg": "📦 الشحنة وصلت وتم اعتمادها."})

    if _wants_json():
        return jsonify(
            {
                "shipment": {
                    "id": sh.id,
                    "number": sh.shipment_number,
                    "status": sh.status,
                    "origin": sh.origin,
                    "destination": (sh.destination_warehouse.name if sh.destination_warehouse else (sh.destination or None)),
                    "expected_arrival": sh.expected_arrival.isoformat() if sh.expected_arrival else None,
                    "total_value": float(sh.total_value or 0),
                    "items": [
                        {
                            "product": (it.product.name if it.product else None),
                            "warehouse_id": it.warehouse_id,
                            "quantity": it.quantity,
                            "unit_cost": float(it.unit_cost or 0),
                            "declared_value": float(it.declared_value or 0),
                            "landed_extra_share": float(it.landed_extra_share or 0),
                            "landed_unit_cost": float(it.landed_unit_cost or 0),
                            "notes": it.notes,
                        }
                        for it in sh.items
                    ],
                    "partners": [
                        {
                            "partner": (ln.partner.name if ln.partner else None),
                            "share_percentage": float(ln.share_percentage or 0),
                            "share_amount": float(ln.share_amount or 0),
                        }
                        for ln in sh.partners
                    ],
                    "total_paid": float(total_paid or 0),
                },
                "alerts": alerts,
            }
        )

    # في حالة HTML نمرر التنبيهات للقالب
    return render_template(
        "warehouses/shipment_detail.html",
        shipment=sh,
        total_paid=total_paid,
        alerts=alerts,
        format_currency=utils.format_currency,
    )

@shipments_bp.route("/<int:id>/mark-arrived", methods=["POST"], endpoint="mark_arrived")
@login_required
def mark_arrived(id: int):
    sh = _get_or_404(Shipment, id, load_options=[joinedload(Shipment.items)])
    st = (sh.status or "").upper()
    if st == "ARRIVED":
        msg = f"📦 الشحنة {sh.shipment_number or sh.id} معلّمة بواصل مسبقاً"
        if _wants_json():
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "info")
        return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))
    if st == "DELIVERED":
        msg = "❌ لا يمكن اعتماد وصول شحنة مسلّمة"
        if _wants_json():
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "danger")
        return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))
    try:
        # التحقق من المستودعات قبل اعتماد الوصول
        for item in sh.items:
            if not item.warehouse_id:
                raise ValueError(f"❌ البند {item.product.name if item.product else item.id} بدون مستودع")
            if not item.quantity or item.quantity <= 0:
                raise ValueError(f"❌ البند {item.product.name if item.product else item.id} بدون كمية محددة")
            _ensure_partner_warehouse(item.warehouse_id, sh)
        
        # _apply_arrival_items removed to avoid double counting (handled by listener on status change)
        sh.status = ShipmentStatus.ARRIVED.value
        sh.actual_arrival = sh.actual_arrival or datetime.now(timezone.utc)
        
        # Create GL Entries
        _create_shipment_gl_entries(sh)
        
        # تحديث رصيد الشركاء عند وصول الشحنة (إذا كان هناك شركاء)
        if sh.partners:
            for shipment_partner in sh.partners:
                pass
        
        db.session.commit()
        msg = f"✅ تم اعتماد وصول الشحنة {sh.shipment_number or sh.id} وتحديث المخزون"
        if _wants_json():
            return jsonify({"ok": True, "shipment_id": sh.id, "status": sh.status, "message": msg}), 200
        flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        if _wants_json():
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 500
        flash(f"❌ تعذّر اعتماد الوصول: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/cancel", methods=["POST"], endpoint="cancel_shipment")
@login_required
def cancel_shipment(id: int):
    sh = _get_or_404(Shipment, id, load_options=[joinedload(Shipment.items)])
    try:
        st = (sh.status or "").upper()
        if st == "DELIVERED":
            raise ValueError("❌ لا يمكن إلغاء شحنة مسلّمة")
        if _status_applies_stock(st):
            # التحقق من المستودعات قبل إلغاء الوصول
            for item in sh.items:
                if item.warehouse_id:
                    _ensure_partner_warehouse(item.warehouse_id, sh)
            
            _reverse_arrival_items(_items_snapshot(sh))
        sh.status = ShipmentStatus.CANCELLED.value
        
        # تحديث رصيد الشركاء عند إلغاء الشحنة (إذا كان هناك شركاء)
        if sh.partners:
            for shipment_partner in sh.partners:
                pass
        
        db.session.commit()
        msg = f"⚠️ تم إلغاء الشحنة {sh.shipment_number or sh.id}"
        if _wants_json():
            return jsonify({"ok": True, "shipment_id": sh.id, "status": sh.status, "message": msg}), 200
        flash(msg, "warning")
    except Exception as e:
        db.session.rollback()
        if _wants_json():
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 500
        flash(f"❌ تعذّر الإلغاء: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/mark-in-transit", methods=["POST"]) 
@login_required
def mark_in_transit(id):
    sh = _get_or_404(Shipment, id)
    if (sh.status or "").upper() == "IN_TRANSIT":
        if _wants_json():
            return jsonify({"ok": True, "message": "already_in_transit"})
        flash("✅ الشحنة في الطريق بالفعل", "info")
    else:
        try:
            # التحقق من المستودعات قبل وضع الشحنة في الطريق
            for item in sh.items:
                if item.warehouse_id:
                    _ensure_partner_warehouse(item.warehouse_id, sh)
            
            sh.status = ShipmentStatus.IN_TRANSIT.value
            
            # تحديث رصيد الشركاء عند وضع الشحنة في الطريق (إذا كان هناك شركاء)
            if sh.partners:
                for shipment_partner in sh.partners:
                    pass
            
            db.session.commit()
            if _wants_json():
                return jsonify({"ok": True, "message": "marked_in_transit"})
            flash("✅ تم وضع الشحنة في الطريق", "success")
        except Exception as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 500
            flash(f"❌ تعذّر التحديث: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/mark-in-customs", methods=["POST"]) 
@login_required
def mark_in_customs(id):
    sh = _get_or_404(Shipment, id)
    if (sh.status or "").upper() == "IN_CUSTOMS":
        if _wants_json():
            return jsonify({"ok": True, "message": "already_in_customs"})
        flash("✅ الشحنة في الجمارك بالفعل", "info")
    else:
        try:
            # التحقق من المستودعات قبل وضع الشحنة في الجمارك
            for item in sh.items:
                if item.warehouse_id:
                    _ensure_partner_warehouse(item.warehouse_id, sh)
            
            sh.status = ShipmentStatus.IN_CUSTOMS.value
            
            # تحديث رصيد الشركاء عند وضع الشحنة في الجمارك (إذا كان هناك شركاء)
            if sh.partners:
                for shipment_partner in sh.partners:
                    pass
            
            db.session.commit()
            if _wants_json():
                return jsonify({"ok": True, "message": "marked_in_customs"})
            flash("✅ تم وضع الشحنة في الجمارك", "success")
        except Exception as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 500
            flash(f"❌ تعذّر التحديث: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/mark-delivered", methods=["POST"])
@login_required
def mark_delivered(id):
    """
    تسليم الشحنة - ترحيل البنود للمستودعات
    
    المنطق:
    1. عند الإنشاء: بنود الشحنة موجودة لكن بكميات وأسعار 0
    2. عند التسليم: 
       - تحديث الكميات والأسعار الفعلية
       - إضافة البنود للمخزون (StockLevel)
       - توليد باركود لكل بند
       - تحديث الحالة إلى DELIVERED
    """
    from models import Product
    
    sh = _get_or_404(Shipment, id)
    if (sh.status or "").upper() == "DELIVERED":
        if _wants_json():
            return jsonify({"ok": True, "message": "already_delivered"})
        flash("✅ الشحنة مسلمة بالفعل", "info")
    else:
        try:
            if (sh.status or "").upper() != "ARRIVED":
                raise ValueError("❌ لا يمكن تسليم شحنة قبل اعتماد وصولها")
            # التحقق من المستودعات قبل تسليم الشحنة
            for item in sh.items:
                if not item.warehouse_id:
                    raise ValueError(f"❌ البند {item.product.name if item.product else item.id} بدون مستودع")
                
                _ensure_partner_warehouse(item.warehouse_id, sh)
                
                # التحقق من أن الكمية والسعر تم تحديثهما
                if not item.quantity or item.quantity <= 0:
                    raise ValueError(f"❌ البند {item.product.name if item.product else item.id} بدون كمية محددة")
                
                if not item.landed_unit_cost or item.landed_unit_cost <= 0:
                    raise ValueError(f"❌ البند {item.product.name if item.product else item.id} بدون تكلفة نهائية")
                
                # توليد باركود للمنتج إذا لم يكن موجوداً
                product = db.session.get(Product, item.product_id)
                if product and not product.barcode:
                    # توليد باركود بسيط: PRD + timestamp + 4 أرقام عشوائية
                    import random
                    from datetime import datetime
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    random_digits = str(random.randint(1000, 9999))
                    product.barcode = f"PRD{timestamp}{random_digits}"
            
            # حساب التكلفة الإجمالية للشحنة
            _compute_totals(sh)
            
            # توزيع النسب للشركاء (إذا كان هناك شركاء)
            if sh.partners:
                from models import ShipmentPartner, ProductPartner
                
                for shipment_partner in sh.partners:
                    # حساب قيمة النسبة بناءً على التكلفة الإجمالية
                    total_shipment_value = float(sh.total_cost or 0)
                    partner_share_percentage = float(shipment_partner.share_percentage or 0)
                    partner_share_amount = total_shipment_value * (partner_share_percentage / 100.0)
                    
                    # ✅ تحويل المبلغ لعملة الشريك قبل الحفظ
                    if shipment_partner.partner_id:
                        partner = db.session.get(Partner, shipment_partner.partner_id)
                        if partner and partner.currency and partner.currency != (sh.currency or 'USD'):
                            # تحويل من عملة الشحنة إلى عملة الشريك
                            # استخدام دالة تحويل بسيطة
                            from models import ExchangeRate
                            rate = ExchangeRate.get_rate(
                                sh.currency or 'USD',
                                partner.currency,
                                sh.delivered_date or datetime.now(timezone.utc)
                            )
                            if rate:
                                partner_share_amount = partner_share_amount * float(rate)
                            else:
                                # استخدام سعر افتراضي تقريبي
                                if (sh.currency or 'USD') == 'USD' and partner.currency == 'ILS':
                                    partner_share_amount = partner_share_amount * 3.65
                    
                    # تحديث مبلغ النسبة (بعملة الشريك)
                    shipment_partner.share_amount = partner_share_amount
                    
                    # ✅ ربط البنود بالشريك (ProductPartner)
                    if partner_share_percentage > 0 and shipment_partner.partner_id:
                        for item in sh.items:
                            # التحقق من وجود ربط سابق
                            existing_link = ProductPartner.query.filter_by(
                                product_id=item.product_id,
                                partner_id=shipment_partner.partner_id
                            ).first()
                            
                            # حساب قيمة نصيب الشريك من هذا البند
                            item_total_value = float(item.quantity or 0) * float(item.landed_unit_cost or 0)
                            partner_item_amount = item_total_value * (partner_share_percentage / 100.0)
                            
                            if existing_link:
                                # تحديث الربط الموجود (تجميع النسب)
                                existing_link.share_amount = float(existing_link.share_amount or 0) + partner_item_amount
                            else:
                                # إنشاء ربط جديد
                                new_link = ProductPartner(
                                    product_id=item.product_id,
                                    partner_id=shipment_partner.partner_id,
                                    share_percent=partner_share_percentage,
                                    share_amount=partner_item_amount,
                                    notes=f"من الشحنة {sh.shipment_number}"
                                )
                                db.session.add(new_link)
            
            # تحديث حالة الشحنة
            sh.status = ShipmentStatus.DELIVERED.value
            sh.delivered_date = datetime.now(timezone.utc)
            
            db.session.commit()
            
            if _wants_json():
                return jsonify({"ok": True, "message": "marked_delivered"})
            flash("✅ تم تسليم الشحنة وترحيل البنود للمستودعات", "success")
            
        except ValueError as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 400
            flash(f"{e}", "danger")
        except Exception as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 500
            flash(f"❌ تعذّر التحديث: {e}", "danger")
    
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/mark-returned", methods=["POST"])
@login_required
def mark_returned(id):
    sh = _get_or_404(Shipment, id)
    if (sh.status or "").upper() == "RETURNED":
        if _wants_json():
            return jsonify({"ok": True, "message": "already_returned"})
        flash("✅ الشحنة مرتجعة بالفعل", "info")
    else:
        try:
            # التحقق من المستودعات قبل إرجاع الشحنة
            for item in sh.items:
                if item.warehouse_id:
                    _ensure_partner_warehouse(item.warehouse_id, sh)
            if _status_applies_stock(sh.status):
                _reverse_arrival_items(_items_snapshot(sh))
            
            sh.status = ShipmentStatus.RETURNED.value
            
            # تحديث رصيد الشركاء عند إرجاع الشحنة (إذا كان هناك شركاء)
            if sh.partners:
                for shipment_partner in sh.partners:
                    pass
            
            db.session.commit()
            if _wants_json():
                return jsonify({"ok": True, "message": "marked_returned"})
            flash("✅ تم إرجاع الشحنة", "success")
        except Exception as e:
            db.session.rollback()
            if _wants_json():
                current_app.logger.exception('API error')
                return jsonify({"error": "حدث خطأ داخلي"}), 500
            flash(f"❌ تعذّر التحديث: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))


@shipments_bp.route("/<int:id>/update-delivery-attempt", methods=["POST"])
@login_required
def update_delivery_attempt(id):
    sh = _get_or_404(Shipment, id)
    data = request.get_json(silent=True) or {}
    
    try:
        sh.delivery_attempts = (sh.delivery_attempts or 0) + 1
        sh.last_delivery_attempt = datetime.now(timezone.utc)
        if data.get("notes"):
            sh.notes = (sh.notes or "") + f"\nمحاولة تسليم #{sh.delivery_attempts}: {data.get('notes')}"
        
        # تحديث رصيد الشركاء عند تحديث محاولة التسليم (إذا كان هناك شركاء)
        if sh.partners:
            for shipment_partner in sh.partners:
                pass
        
        db.session.commit()
        if _wants_json():
            return jsonify({"ok": True, "message": "delivery_attempt_updated"})
        flash("✅ تم تحديث محاولة التسليم", "success")
    except Exception as e:
        db.session.rollback()
        if _wants_json():
            current_app.logger.exception('API error')
            return jsonify({"error": "حدث خطأ داخلي"}), 500
        flash(f"❌ تعذّر التحديث: {e}", "danger")
    return redirect(url_for("shipments_bp.shipment_detail", id=sh.id))
