
from datetime import datetime, date as _date, time as _time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request, jsonify, render_template, url_for, abort, current_app
from flask_login import login_required
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
import utils
from models import Supplier, PaymentDirection, PaymentMethod, PaymentStatus, SupplierSettlement, SupplierSettlementStatus, build_supplier_settlement_draft, AuditLog, SaleStatus, ServiceStatus
import json

supplier_settlements_bp = Blueprint("supplier_settlements_bp", __name__, url_prefix="/suppliers")

def get_unpriced_supplier_products():
    """
    جلب القطع غير المسعّرة للموردين/التجار
    Returns: list of dicts with product info
    """
    from models import (
        ExchangeTransaction, Product, Supplier, 
        Warehouse, WarehouseType, StockLevel
    )
    from sqlalchemy import or_
    
    unpriced_items = []
    
    # جلب جميع معاملات التبادل مع الموردين
    transactions = db.session.query(
        ExchangeTransaction.supplier_id,
        Supplier.name.label("supplier_name"),
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.sku,
        Product.purchase_price,
        Product.selling_price,
        ExchangeTransaction.unit_cost
    ).join(
        Supplier, Supplier.id == ExchangeTransaction.supplier_id
    ).join(
        Product, Product.id == ExchangeTransaction.product_id
    ).filter(
        ExchangeTransaction.supplier_id.isnot(None),
        or_(
            Product.purchase_price == None,
            Product.purchase_price == 0,
            Product.selling_price == None,
            Product.selling_price == 0,
            ExchangeTransaction.unit_cost == None,
            ExchangeTransaction.unit_cost == 0
        )
    ).distinct().all()
    
    seen_products = set()
    
    for tx in transactions:
        key = (tx.supplier_id, tx.product_id)
        if key in seen_products:
            continue
        seen_products.add(key)
        
        has_stock = db.session.query(StockLevel).filter(
            StockLevel.product_id == tx.product_id,
            StockLevel.quantity > 0
        ).first() is not None
        
        missing = []
        if not tx.purchase_price or tx.purchase_price == 0:
            missing.append("purchase_price")
        if not tx.selling_price or tx.selling_price == 0:
            missing.append("selling_price")
        if not tx.unit_cost or tx.unit_cost == 0:
            missing.append("unit_cost")
        
        unpriced_items.append({
            "supplier_id": tx.supplier_id,
            "supplier_name": tx.supplier_name,
            "product_id": tx.product_id,
            "product_name": tx.product_name,
            "sku": tx.sku,
            "purchase_price": float(tx.purchase_price or 0),
            "selling_price": float(tx.selling_price or 0),
            "unit_cost": float(tx.unit_cost or 0),
            "has_stock": has_stock,
            "missing": missing
        })
    
    return unpriced_items

@supplier_settlements_bp.route("/unpriced-items", methods=["GET"])
@login_required
def check_unpriced_items():
    """التحقق من القطع غير المسعّرة للموردين/التجار"""
    unpriced = get_unpriced_supplier_products()
    return jsonify({
        "success": True,
        "count": len(unpriced),
        "items": unpriced
    })

@supplier_settlements_bp.route("/settlements", methods=["GET"], endpoint="list")
@login_required
def settlements_list():
    """قائمة تسويات الموردين"""
    from sqlalchemy import desc
    
    settlements = db.session.query(SupplierSettlement).options(
        joinedload(SupplierSettlement.supplier)
    ).order_by(desc(SupplierSettlement.created_at)).limit(1000).all()
    
    for settlement in settlements:
        db.session.refresh(settlement)
        if settlement.supplier:
            db.session.refresh(settlement.supplier)
    
    return render_template(
        "supplier_settlements/list.html",
        settlements=settlements
    )

def _get_supplier_or_404(sid: int) -> Supplier:
    obj = db.session.get(Supplier, sid)
    if not obj:
        abort(404)
    return obj

def _parse_iso_to_datetime(val: str, end: bool = False):
    s = (val or "").strip()
    if not s:
        return None
    try:
        if len(s) == 10:
            d = _date.fromisoformat(s)
            return datetime.combine(d, _time.max if end else _time.min)
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _extract_range_from_request():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start_default = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_default = now
    if request.method == "GET":
        frm = request.args.get("from")
        to = request.args.get("to")
    else:
        payload = request.get_json(silent=True) or {}
        frm = payload.get("from") or request.form.get("from")
        to = payload.get("to") or request.form.get("to")
    dfrom = _parse_iso_to_datetime(frm, end=False) if frm else start_default
    dto = _parse_iso_to_datetime(to, end=True) if to else end_default
    if not dfrom or not dto:
        return None, None, "Bad date ISO format"
    if dfrom > dto:
        return None, None, "from must be before to"
    return dfrom, dto, ""

from utils import _q2

def _d2(v) -> Decimal:
    """تحويل إلى Decimal بدقة منزلتين"""
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _due_direction(v: Decimal):
    if v > 0:
        return PaymentDirection.OUT.value
    return PaymentDirection.IN.value

def _currency_mismatch(lines, currency: str) -> bool:
    for l in lines or []:
        c = getattr(l, "currency", None) or currency
        if c != currency:
            return True
    return False

def _overlap_exists(supplier_id: int, dfrom: datetime, dto: datetime) -> bool:
    return db.session.query(SupplierSettlement.id).filter(
        SupplierSettlement.supplier_id == supplier_id,
        SupplierSettlement.status.in_([SupplierSettlementStatus.DRAFT.value, SupplierSettlementStatus.CONFIRMED.value]),
        and_(SupplierSettlement.from_date <= dto, SupplierSettlement.to_date >= dfrom)
    ).first() is not None

@supplier_settlements_bp.route("/<int:supplier_id>/settlements/preview", methods=["GET"])
@login_required
def preview(supplier_id):
    from flask import redirect
    return redirect(url_for('supplier_settlements_bp.supplier_settlement', supplier_id=supplier_id))

@supplier_settlements_bp.route("/<int:supplier_id>/settlements/create", methods=["POST"])
@login_required
def create(supplier_id):
    supplier = _get_supplier_or_404(supplier_id)
    dfrom, dto, err = _extract_range_from_request()
    if err:
        return jsonify({"success": False, "error": err}), 400
    draft = build_supplier_settlement_draft(supplier.id, dfrom, dto, currency=supplier.currency)
    lines = getattr(draft, "lines", []) or []
    if not lines:
        return jsonify({"success": False, "error": "لا توجد سطور لتسويتها"}), 400
    if _currency_mismatch(lines, supplier.currency):
        return jsonify({"success": False, "error": "عملة غير متطابقة داخل التسوية"}), 400
    if _overlap_exists(supplier.id, dfrom, dto):
        return jsonify({"success": False, "error": "نطاق متداخل مع تسوية سابقة"}), 409
    due = Decimal(str(draft.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if due == Decimal("0.00"):
        return jsonify({"success": False, "error": "لا توجد مبالغ مستحقة"}), 400
    draft.ensure_code()
    draft.from_date = dfrom
    draft.to_date = dto
    draft.currency = supplier.currency
    try:
        with db.session.begin_nested():
            db.session.add(draft)
            db.session.flush()
            db.session.add(AuditLog(model_name="SupplierSettlement", record_id=draft.id, action="CREATE", old_data=None, new_data=json.dumps({
                "supplier_id": supplier.id, "from": dfrom.isoformat(), "to": dto.isoformat(), "total_due": str(due), "code": draft.code
            })))
    except SQLAlchemyError as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
    direction = _due_direction(due)
    amount_str = f"{abs(due):.2f}"
    pay_url = url_for(
        "payments.create_payment",
        entity_type="SUPPLIER",
        entity_id=str(supplier.id),
        direction=direction,
        total_amount=amount_str,
        currency=supplier.currency,
        method=PaymentMethod.BANK.value,
        reference=f"SupplierSettle:{draft.code}",
        notes=f"تسوية مورد {supplier.name} {dfrom.date()} - {dto.date()} ({draft.code})",
    )
    return jsonify({"success": True, "id": draft.id, "code": draft.code, "pay_url": pay_url})

@supplier_settlements_bp.route("/settlements/<int:settlement_id>/confirm", methods=["POST"])
@login_required
def confirm(settlement_id):
    ss = db.session.get(SupplierSettlement, settlement_id)
    if not ss:
        abort(404)
    db.session.refresh(ss)
    if ss.supplier:
        db.session.refresh(ss.supplier)
    if ss.status != SupplierSettlementStatus.DRAFT.value:
        return jsonify({"success": False, "error": "Only DRAFT can be confirmed"}), 400
    recalc = build_supplier_settlement_draft(ss.supplier_id, ss.from_date, ss.to_date, currency=ss.currency)
    orig = Decimal(str(ss.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    now_ = Decimal(str(recalc.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if orig != now_ or len(getattr(ss, "lines", []) or []) != len(getattr(recalc, "lines", []) or []):
        return jsonify({"success": False, "error": "اختلفت البيانات منذ المعاينة، أعد الإنشاء"}), 409
    try:
        with db.session.begin_nested():
            ss.mark_confirmed()
            db.session.flush()
            db.session.add(AuditLog(model_name="SupplierSettlement", record_id=ss.id, action="CONFIRM", old_data=None, new_data=json.dumps({
                "code": ss.code, "from": ss.from_date.isoformat(), "to": ss.to_date.isoformat(), "total_due": str(orig)
            })))
        from utils.supplier_balance_updater import update_supplier_balance_components
        update_supplier_balance_components(ss.supplier_id)
    except SQLAlchemyError as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
    return jsonify({"success": True, "id": ss.id, "code": ss.code})

@supplier_settlements_bp.route("/settlements/<int:settlement_id>/void", methods=["POST"])
@login_required
def void(settlement_id):
    ss = db.session.get(SupplierSettlement, settlement_id)
    if not ss:
        abort(404)
    if ss.status != SupplierSettlementStatus.DRAFT.value:
        return jsonify({"success": False, "error": "Only DRAFT can be voided"}), 400
    try:
        with db.session.begin_nested():
            db.session.delete(ss)
            db.session.flush()
            db.session.add(AuditLog(model_name="SupplierSettlement", record_id=settlement_id, action="VOID", old_data=None, new_data=None))
    except SQLAlchemyError as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
    return jsonify({"success": True})

@supplier_settlements_bp.route("/settlements/<int:settlement_id>", methods=["GET"])
@login_required
def show(settlement_id):
    settlement = db.session.get(SupplierSettlement, settlement_id)
    if not settlement:
        abort(404)
    
    db.session.refresh(settlement)
    supplier = settlement.supplier
    if supplier:
        db.session.refresh(supplier)
    
    balance_data = _calculate_smart_supplier_balance(
        supplier.id if supplier else 0,
        settlement.from_date,
        settlement.to_date
    ) if supplier else None
    
    return render_template("vendors/suppliers/settlement_preview.html", ss=settlement, supplier=supplier, balance_data=balance_data, date_from=settlement.from_date, date_to=settlement.to_date)


@supplier_settlements_bp.route("/exchange-transaction/<int:tx_id>/update-price", methods=["POST"])
@login_required
def update_exchange_transaction_price(tx_id):
    """تحديث سعر قطعة في مستودع التبادل - API"""
    from models import ExchangeTransaction
    
    tx = db.session.get(ExchangeTransaction, tx_id)
    if not tx:
        return jsonify({"success": False, "error": "المعاملة غير موجودة"}), 404
    
    data = request.get_json() or {}
    new_price = data.get("unit_cost")
    
    if new_price is None:
        return jsonify({"success": False, "error": "السعر مطلوب"}), 400
    
    try:
        new_price = Decimal(str(new_price))
        if new_price < 0:
            return jsonify({"success": False, "error": "السعر يجب أن يكون >= 0"}), 400
    except (ValueError, InvalidOperation):
        return jsonify({"success": False, "error": "سعر غير صالح"}), 400
    
    try:
        tx.unit_cost = new_price
        tx.is_priced = True
        db.session.commit()
        
        # حساب القيمة الجديدة
        total_value = float(_q2(tx.quantity * new_price))
        
        return jsonify({
            "success": True,
            "message": "تم تحديث السعر بنجاح",
            "transaction_id": tx.id,
            "new_price": float(new_price),
            "quantity": tx.quantity,
            "total_value": total_value
        })
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500


@supplier_settlements_bp.route("/<int:supplier_id>/settlement", methods=["GET"], endpoint="supplier_settlement")
@login_required
def supplier_settlement(supplier_id):
    """التسوية الذكية للمورد"""
    supplier = _get_supplier_or_404(supplier_id)
    db.session.refresh(supplier)
    
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    if date_from:
        date_from = _parse_iso_to_datetime(date_from, end=False)
    else:
        # Auto-detect start date from last settlement to prevent overlap
        last_settlement = db.session.query(SupplierSettlement).filter(
            SupplierSettlement.supplier_id == supplier_id,
            SupplierSettlement.status == SupplierSettlementStatus.CONFIRMED.value
        ).order_by(SupplierSettlement.to_date.desc()).first()
        
        if last_settlement:
            date_from = last_settlement.to_date + timedelta(seconds=1)
        else:
            date_from = datetime(2024, 1, 1)
    
    if date_to:
        date_to = _parse_iso_to_datetime(date_to, end=True)
    else:
        date_to = datetime.now(timezone.utc).replace(tzinfo=None)
    
    balance_data = _calculate_smart_supplier_balance(supplier_id, date_from, date_to)
    
    # إنشاء object بسيط للتوافق مع القالب
    from types import SimpleNamespace
    ss = SimpleNamespace(
        id=None,
        supplier=supplier,
        from_date=date_from,
        to_date=date_to,
        currency=supplier.currency,
        total_gross=balance_data.get("incoming", {}).get("total", 0) if isinstance(balance_data, dict) else 0,
        total_due=balance_data.get("balance", {}).get("amount", 0) if isinstance(balance_data, dict) else 0,
        remaining=balance_data.get("balance", {}).get("amount", 0) if isinstance(balance_data, dict) else 0,
        status="DRAFT",
        code=f"SS-SMART-{supplier_id}-{date_from.strftime('%Y%m%d')}",
        lines=[],
        created_at=date_from,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    return render_template(
        "vendors/suppliers/settlement_preview.html",
        supplier=supplier,
        ss=ss,
        balance_data=balance_data,
        date_from=date_from,
        date_to=date_to
    )


def _get_returned_checks_to_supplier(supplier_id: int, supplier, date_from: datetime, date_to: datetime):
    """
    الشيكات الصادرة المرتدة (دفعنا للمورد) - تُحسب بشكل منفصل
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentMethod, Check, CheckStatus, Sale, Invoice, ServiceRequest, PreOrder
    from sqlalchemy import or_, and_
    
    returned_checks_out = Decimal('0.00')
    items = []
    
    returned_out_direct = db.session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.OUT,
        or_(
            Check.status.in_(['RETURNED', 'BOUNCED']),
            and_(
                Payment.status == PaymentStatus.FAILED,
                Payment.method == PaymentMethod.CHEQUE.value
            )
        ),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    returned_out_from_customer = []
    returned_out_from_sales = []
    returned_out_from_invoices = []
    returned_out_from_services = []
    returned_out_from_preorders = []
    
    if supplier.customer_id:
        returned_out_from_customer = db.session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_out_from_sales = db.session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_out_from_invoices = db.session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_out_from_services = db.session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_out_from_preorders = db.session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
    
    seen_returned_out_ids = set()
    returned_out_all = []
    for p in (returned_out_direct + returned_out_from_customer + returned_out_from_sales + 
             returned_out_from_invoices + returned_out_from_services + returned_out_from_preorders):
        if p.id not in seen_returned_out_ids:
            seen_returned_out_ids.add(p.id)
            returned_out_all.append(p)
    
    for p in returned_out_all:
        amt = _convert_to_ils(Decimal(str(p.total_amount or 0)), p.currency, p.payment_date)
        returned_checks_out += amt
        items.append({
            "payment_id": p.id,
            "payment_number": p.payment_number,
            "date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else "",
            "amount_ils": float(amt)
        })
    
    # ✅ الشيكات اليدوية المرتدة (بدون payment_id) - OUT
    manual_returned_checks = db.session.query(Check).filter(
        Check.supplier_id == supplier_id,
        Check.payment_id.is_(None),
        Check.direction == PaymentDirection.OUT.value,
        Check.status.in_([CheckStatus.RETURNED.value, CheckStatus.BOUNCED.value]),
        Check.check_date >= date_from,
        Check.check_date <= date_to
    ).all()
    
    for check in manual_returned_checks:
        amt = _convert_to_ils(Decimal(str(check.amount or 0)), check.currency or 'ILS', check.check_date or date_from)
        returned_checks_out += amt
        items.append({
            "check_id": check.id,
            "payment_id": None,
            "date": check.check_date.strftime("%Y-%m-%d") if check.check_date else "",
            "amount_ils": float(amt)
        })
    
    return {
        "items": items,
        "total_ils": float(returned_checks_out),
        "count": len(items)
    }


def _get_returned_checks_from_supplier(supplier_id: int, supplier, date_from: datetime, date_to: datetime):
    """
    الشيكات الواردة المرتدة (دفع المورد لنا) - تُحسب بشكل منفصل
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentMethod, Check, CheckStatus, Sale, Invoice, ServiceRequest, PreOrder
    from sqlalchemy import or_, and_
    
    returned_checks_in = Decimal('0.00')
    items = []
    
    returned_in_direct = db.session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.IN,
        or_(
            Check.status.in_(['RETURNED', 'BOUNCED']),
            and_(
                Payment.status == PaymentStatus.FAILED,
                Payment.method == PaymentMethod.CHEQUE.value
            )
        ),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    returned_in_from_customer = []
    returned_in_from_sales = []
    returned_in_from_invoices = []
    returned_in_from_services = []
    returned_in_from_preorders = []
    
    if supplier.customer_id:
        returned_in_from_customer = db.session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_in_from_sales = db.session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_in_from_invoices = db.session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_in_from_services = db.session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        returned_in_from_preorders = db.session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_(['RETURNED', 'BOUNCED']),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE.value
                )
            ),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
    
    seen_returned_in_ids = set()
    returned_in_all = []
    for p in (returned_in_direct + returned_in_from_customer + returned_in_from_sales + 
             returned_in_from_invoices + returned_in_from_services + returned_in_from_preorders):
        if p.id not in seen_returned_in_ids:
            seen_returned_in_ids.add(p.id)
            returned_in_all.append(p)
    
    for p in returned_in_all:
        amt = _convert_to_ils(Decimal(str(p.total_amount or 0)), p.currency, p.payment_date)
        returned_checks_in += amt
        items.append({
            "payment_id": p.id,
            "payment_number": p.payment_number,
            "date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else "",
            "amount_ils": float(amt)
        })
    
    # ✅ الشيكات اليدوية المرتدة (بدون payment_id) - IN
    manual_returned_checks = db.session.query(Check).filter(
        Check.supplier_id == supplier_id,
        Check.payment_id.is_(None),
        Check.direction == PaymentDirection.IN.value,
        Check.status.in_([CheckStatus.RETURNED.value, CheckStatus.BOUNCED.value]),
        Check.check_date >= date_from,
        Check.check_date <= date_to
    ).all()
    
    for check in manual_returned_checks:
        amt = _convert_to_ils(Decimal(str(check.amount or 0)), check.currency or 'ILS', check.check_date or date_from)
        returned_checks_in += amt
        items.append({
            "check_id": check.id,
            "payment_id": None,
            "date": check.check_date.strftime("%Y-%m-%d") if check.check_date else "",
            "amount_ils": float(amt)
        })
    
    return {
        "items": items,
        "total_ils": float(returned_checks_in),
        "count": len(items)
    }


def _calculate_smart_supplier_balance(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    حساب التسوية الذكية الشاملة للمورد
    
    المعادلة المحاسبية الصحيحة:
    ═════════════════════════════════════════════════════════════
    حقوق المورد = القطع المأخوذة منه (من مستودع التبادل)
    التزامات المورد = مبيعات له + صيانة له
    الدفعات المسددة = دفعنا له (OUT) + دفع لنا (IN) + المرتجعات (OUT)
    
    الرصيد النهائي = حقوقه - التزاماته - الدفعات المسددة
    ═════════════════════════════════════════════════════════════
    
    ملاحظات مهمة:
    - جميع العملات تُحول إلى ILS قبل الجمع
    - القطع غير المسعرة: يجب تسعيرها قبل التوثيق
    - المرتجعات (OUT) تُخصم من حقوقه
    """
    try:
        from models import (
            Expense, Sale, SaleLine, ExchangeTransaction, Payment, Product,
            ServiceRequest, ServicePart, Warehouse, WarehouseType, StockLevel
        )
        from sqlalchemy import func, desc, or_
        
        if supplier_id is None or (hasattr(supplier_id, '__clause_element__')):
            return {"success": False, "error": "معرّف المورد غير صحيح"}
        
        supplier_id_int = int(supplier_id) if supplier_id else None
        if supplier_id_int is None:
            return {"success": False, "error": "معرّف المورد غير صحيح"}
        
        supplier = db.session.get(Supplier, supplier_id_int)
        if not supplier:
            return {"success": False, "error": "المورد غير موجود"}
        
        opening_balance = Decimal(str(getattr(supplier, 'opening_balance', 0) or 0))
        supplier_currency = getattr(supplier, 'currency', 'ILS') or 'ILS'
        
        if supplier_currency != 'ILS' and opening_balance != 0:
            try:
                opening_balance = _convert_to_ils(opening_balance, supplier_currency, date_from)
            except Exception:
                current_app.logger.warning('currency conversion failed silently in supplier_settlements.py', exc_info=True)
        
        exchange_items = _get_supplier_exchange_items(supplier_id, date_from, date_to)
        
        sales_to_supplier = _get_sales_to_supplier(supplier_id, date_from, date_to)
        services_to_supplier = _get_services_to_supplier(supplier_id, date_from, date_to)
        preorders_to_supplier = _get_supplier_preorders(supplier_id, date_from, date_to)
        returns_to_supplier = _get_returns_to_supplier(supplier_id, date_from, date_to)
        
        from models import ExpenseType, SaleReturn, SaleReturnLine
        expenses_service = Expense.query.outerjoin(ExpenseType).filter(
            or_(
                Expense.supplier_id == supplier_id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
            ),
            Expense.date >= date_from,
            Expense.date <= date_to,
            or_(
                func.upper(ExpenseType.code) == "PARTNER_EXPENSE",
                func.upper(ExpenseType.code) == "SUPPLIER_EXPENSE"
            )
        ).all()
        
        expenses_normal = Expense.query.outerjoin(ExpenseType).filter(
            or_(
                Expense.supplier_id == supplier_id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
            ),
            Expense.date >= date_from,
            Expense.date <= date_to,
            or_(
                ExpenseType.id.is_(None),
                ExpenseType.code.is_(None),
                ~func.upper(ExpenseType.code).in_(["PARTNER_EXPENSE", "SUPPLIER_EXPENSE"])
            )
        ).all()
        
        expenses_service_total = Decimal('0.00')
        expenses_normal_total = Decimal('0.00')
        expenses_items = []
        
        for exp in expenses_service:
            amt = Decimal(str(exp.amount or 0))
            amt_ils = amt
            if exp.currency == "ILS":
                expenses_service_total += amt
            else:
                try:
                    amt_ils = _convert_to_ils(amt, exp.currency, exp.date)
                    expenses_service_total += amt_ils
                except Exception:
                    current_app.logger.warning('currency conversion failed silently in supplier_settlements.py', exc_info=True)
            
            exp_type_name = getattr(getattr(exp, 'type', None), 'name', 'توريد خدمة') if hasattr(exp, 'type') and exp.type else 'توريد خدمة'
            expenses_items.append({
                "id": exp.id,
                "date": exp.date.isoformat() if exp.date else None,
                "description": exp.description or exp_type_name,
                "amount": float(amt),
                "currency": exp.currency or "ILS",
                "amount_ils": float(amt_ils),
                "expense_type": exp_type_name,
                "reference": f"مصروف #{exp.id}"
            })
        
        for exp in expenses_normal:
            amt = Decimal(str(exp.amount or 0))
            amt_ils = amt
            if exp.currency == "ILS":
                expenses_normal_total += amt
            else:
                try:
                    amt_ils = _convert_to_ils(amt, exp.currency, exp.date)
                    expenses_normal_total += amt_ils
                except Exception:
                    current_app.logger.warning('currency conversion failed silently in supplier_settlements.py', exc_info=True)
        
        sale_returns_from_supplier = Decimal('0.00')
        sale_returns_from_customer = Decimal('0.00')
        
        if supplier.customer_id:
            sale_returns = SaleReturn.query.filter(
                SaleReturn.customer_id == supplier.customer_id,
                SaleReturn.status == 'CONFIRMED',
                SaleReturn.created_at >= date_from,
                SaleReturn.created_at <= date_to
            ).all()
            
            for sr in sale_returns:
                amt = Decimal(str(sr.total_amount or 0))
                if sr.currency != "ILS":
                    try:
                        amt = _convert_to_ils(amt, sr.currency, sr.created_at)
                    except Exception:
                        current_app.logger.warning('currency conversion failed silently in supplier_settlements.py', exc_info=True)
                
                has_supplier_liability = SaleReturnLine.query.filter(
                    SaleReturnLine.sale_return_id == sr.id,
                    SaleReturnLine.liability_party == 'SUPPLIER'
                ).first()
                
                if has_supplier_liability:
                    sale_returns_from_customer += amt
                else:
                    sale_returns_from_supplier += amt
        
        supplier_rights = Decimal(str(exchange_items.get("total_value_ils", 0))) + expenses_service_total + sale_returns_from_supplier
        
        supplier_obligations = Decimal(str(sales_to_supplier.get("total_ils", 0))) + \
                               Decimal(str(services_to_supplier.get("total_ils", 0))) + \
                               Decimal(str(preorders_to_supplier.get("total_ils", 0) if isinstance(preorders_to_supplier, dict) else 0)) + \
                               expenses_normal_total
        
        payments_to_supplier = _get_payments_to_supplier(supplier_id, supplier, date_from, date_to)
        payments_from_supplier = _get_payments_from_supplier(supplier_id, supplier, date_from, date_to)
        preorders_prepaid = _get_supplier_preorders_prepaid(supplier_id, supplier, date_from, date_to)
        returned_checks_in = _get_returned_checks_from_supplier(supplier_id, supplier, date_from, date_to)
        returned_checks_out = _get_returned_checks_to_supplier(supplier_id, supplier, date_from, date_to)
        
        net_before_payments = supplier_rights - supplier_obligations
        
        paid_to_supplier = Decimal(str(payments_to_supplier.get("total_ils", 0)))
        received_from_supplier = Decimal(str(payments_from_supplier.get("total_ils", 0)))
        preorders_prepaid_total = Decimal(str(preorders_prepaid.get("total_ils", 0)))
        returns_value = Decimal(str(returns_to_supplier.get("total_value_ils", 0)))
        
        returned_checks_in_total = Decimal(str(returned_checks_in.get("total_ils", 0)))
        returned_checks_out_total = Decimal(str(returned_checks_out.get("total_ils", 0)))
        
        balance = opening_balance + net_before_payments - paid_to_supplier + received_from_supplier - preorders_prepaid_total - returns_value - returned_checks_in_total + returned_checks_out_total
        
        # القطع غير المسعرة
        unpriced_items = exchange_items.get("unpriced_items", [])
        
        # التسويات السابقة
        previous_settlements = _get_previous_supplier_settlements(supplier_id, date_from)
        
        opening_view = utils.classify_entity_balance(opening_balance)
        balance_view = utils.classify_entity_balance(balance)

        return {
            "success": True,
            "supplier": {
                "id": supplier.id,
                "name": supplier.name,
                "currency": supplier.currency
            },
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat()
            },
            # 🔵 الرصيد الافتتاحي
            "opening_balance": {
                "amount": float(opening_balance),
                "currency": "ILS",
                "direction": "له علينا" if opening_view["balance"] > 0 else "عليه لنا" if opening_view["balance"] < 0 else "متوازن"
            },
            "rights": {
                "exchange_items": exchange_items,
                "services": {
                    "items": expenses_items,
                    "total_ils": float(expenses_service_total),
                    "count": len(expenses_service)
                },
                "sale_returns_from_supplier": float(sale_returns_from_supplier),
                "total": float(supplier_rights)
            },
            "obligations": {
                "sales_to_supplier": sales_to_supplier,
                "services_to_supplier": services_to_supplier,
                "preorders_to_supplier": preorders_to_supplier,
                "expenses_normal": float(expenses_normal_total),
                "sale_returns_from_customer": float(sale_returns_from_customer),
                "total": float(supplier_obligations)
            },
            "payments": {
                "paid_to_supplier": payments_to_supplier,
                "received_from_supplier": payments_from_supplier,
                "preorders_prepaid": preorders_prepaid,
                "returns_to_supplier": returns_to_supplier,
                "returned_checks_in": returned_checks_in,
                "returned_checks_out": returned_checks_out,
                "total_paid": float(paid_to_supplier),
                "total_received": float(received_from_supplier),
                "total_returns": float(returns_value),
                "total_returned_checks_in": float(returned_checks_in_total),
                "total_returned_checks_out": float(returned_checks_out_total),
                "total_settled": float(paid_to_supplier + received_from_supplier + returns_value)
            },
            "expenses": {
                "items": expenses_items,
                "service_total_ils": float(expenses_service_total),
                "normal_total_ils": float(expenses_normal_total),
                "total_ils": float(expenses_service_total + expenses_normal_total),
                "count": len(expenses_service) + len(expenses_normal)
            },
            "balance": {
                "gross": float(net_before_payments),
                "net": float(balance),
                "amount": balance_view["abs_balance"],
                "raw_amount": float(balance),
                "owed_to_us": balance_view["owed_to_us"],
                "owed_by_us": balance_view["owed_by_us"],
                "direction": "له علينا" if balance_view["balance"] > 0 else "عليه لنا" if balance_view["balance"] < 0 else "متوازن",
                "payment_direction": "OUT" if balance_view["balance"] > 0 else "IN" if balance_view["balance"] < 0 else None,
                "action": "ندفع له" if balance_view["balance"] > 0 else "يدفع لنا" if balance_view["balance"] < 0 else "لا شيء",
                "currency": "ILS",
                "formula": f"({float(opening_balance):.2f} + {float(supplier_rights):.2f} - {float(supplier_obligations):.2f} - {float(paid_to_supplier):.2f} + {float(received_from_supplier):.2f} - {float(preorders_prepaid_total):.2f} - {float(returns_value):.2f} - {float(returned_checks_in_total):.2f} + {float(returned_checks_out_total):.2f}) = {float(balance):.2f}"
            },
            "unpriced_items": unpriced_items,
            "has_unpriced": len(unpriced_items) > 0,
            "previous_settlements": previous_settlements,
            "currency_note": "⚠️ جميع المبالغ بالشيكل (ILS) بعد التحويل"
        }
        
    except ValueError as e:
        if "fx.rate_unavailable" in str(e) or "rate_unavailable" in str(e):
            return {
                "success": False,
                "error": "سعر الصرف غير متوفر",
                "error_type": "missing_fx_rate",
                "message": "⚠️ تنبيه: لا يمكن إتمام التسوية لعدم توفر سعر صرف لإحدى العملات.\n\nيرجى:\n1. إدخال سعر الصرف يدوياً من [إعدادات العملات]\n2. أو تفعيل الاتصال بالسيرفرات العالمية\n3. ثم إعادة المحاولة",
                "help_url": "/settings/currencies"
            }
        current_app.logger.exception('settlement calculation error')
        return {"success": False, "error": "خطأ في الحساب"}
    except Exception as e:
        current_app.logger.exception('settlement calculation error')
        return {"success": False, "error": "خطأ في حساب رصيد المورد"}


def _calculate_supplier_incoming(supplier_id: int, date_from: datetime, date_to: datetime):
    """حساب الوارد من المورد"""
    from models import Expense, ExchangeTransaction
    from sqlalchemy import func, or_, and_
    
    # المشتريات (النفقات من نوع مشتريات)
    purchases = db.session.query(func.sum(Expense.amount)).filter(
        or_(
            Expense.supplier_id == supplier_id,
            and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).scalar() or 0
    
    # القطع المعطاة للمورد (ExchangeTransaction مع اتجاه OUT)
    products_given = db.session.query(func.sum(ExchangeTransaction.quantity * ExchangeTransaction.unit_cost)).filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.direction == "OUT",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).scalar() or 0
    
    return {
        "purchases": float(purchases),
        "products_given": float(products_given),
        "total": float(purchases + products_given)
    }


def _calculate_supplier_outgoing(supplier_id: int, date_from: datetime, date_to: datetime):
    """حساب الصادر للمورد"""
    from models import Sale, ExchangeTransaction
    from sqlalchemy import func
    
    # المبيعات للمورد (إذا كان عميل أيضاً)
    sales = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.customer_id == supplier_id,  # إذا كان المورد عميل أيضاً
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to
    ).scalar() or 0
    
    # القطع المأخوذة من المورد (ExchangeTransaction مع اتجاه IN)
    products_taken = db.session.query(func.sum(ExchangeTransaction.quantity * ExchangeTransaction.unit_cost)).filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.direction == "IN",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).scalar() or 0
    
    return {
        "sales": float(sales),
        "products_taken": float(products_taken),
        "total": float(sales + products_taken)
    }


def _calculate_payments_to_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """حساب الدفعات المدفوعة للمورد"""
    from models import Payment
    from sqlalchemy import func
    
    amount = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == "OUTGOING",
        Payment.status == "COMPLETED",
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).scalar() or 0
    return float(amount)


def _calculate_payments_from_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """حساب الدفعات المستلمة من المورد"""
    from models import Payment
    from sqlalchemy import func
    
    amount = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == "INCOMING",
        Payment.status == "COMPLETED",
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).scalar() or 0
    return float(amount)


def _check_unpriced_items_for_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """التحقق من القطع غير المسعرة للمورد"""
    from models import ExchangeTransaction, Product
    from sqlalchemy import func, or_
    
    # البحث عن القطع التي لا تحتوي على سعر
    unpriced_transactions = db.session.query(ExchangeTransaction).join(Product).filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to,
        or_(
            ExchangeTransaction.unit_cost.is_(None),
            ExchangeTransaction.unit_cost == 0,
            Product.purchase_price.is_(None),
            Product.purchase_price == 0
        )
    ).all()
    
    unpriced_items = []
    for transaction in unpriced_transactions:
        unpriced_items.append({
            "transaction_id": transaction.id,
            "product_name": transaction.product.name if transaction.product else "غير محدد",
            "product_id": transaction.product_id,
            "quantity": transaction.quantity,
            "direction": transaction.direction,
            "date": transaction.created_at.isoformat() if transaction.created_at else None,
            "suggested_price": float(transaction.product.purchase_price) if transaction.product and transaction.product.purchase_price else 0
        })
    
    return {
        "count": len(unpriced_items),
        "items": unpriced_items,
        "total_estimated_value": sum(item["quantity"] * item["suggested_price"] for item in unpriced_items)
    }


def _get_last_supplier_settlement(supplier_id: int):
    """الحصول على آخر تسوية للمورد"""
    from models import SupplierSettlement
    from sqlalchemy import desc
    
    last_settlement = db.session.query(SupplierSettlement).filter(
        SupplierSettlement.supplier_id == supplier_id
    ).order_by(desc(SupplierSettlement.created_at)).first()
    
    if not last_settlement:
        return None
    
    return {
        "id": last_settlement.id,
        "code": last_settlement.code,
        "date": last_settlement.created_at.isoformat() if last_settlement.created_at else None,
        "status": last_settlement.status,
        "total_due": float(last_settlement.total_due) if last_settlement.total_due else 0,
        "currency": last_settlement.currency
    }


def _get_supplier_operations_details(supplier_id: int, date_from: datetime, date_to: datetime):
    """الحصول على تفاصيل العمليات للمورد"""
    from models import ExchangeTransaction, Payment, Expense, Sale
    from sqlalchemy import func, desc
    
    # العمليات الأخيرة
    recent_transactions = db.session.query(ExchangeTransaction).filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).order_by(desc(ExchangeTransaction.created_at)).limit(10).all()
    
    recent_payments = db.session.query(Payment).filter(
        Payment.supplier_id == supplier_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).order_by(desc(Payment.payment_date)).limit(10).all()
    
    recent_expenses = db.session.query(Expense).filter(
        or_(
            Expense.supplier_id == supplier_id,
            and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).order_by(desc(Expense.date)).limit(10).all()
    
    recent_sales = db.session.query(Sale).filter(
        Sale.customer_id == supplier_id,
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to
    ).order_by(desc(Sale.sale_date)).limit(10).all()
    
    return {
        "recent_transactions": [
            {
                "id": t.id,
                "product_name": t.product.name if t.product else "غير محدد",
                "quantity": t.quantity,
                "unit_cost": float(t.unit_cost) if t.unit_cost else 0,
                "direction": t.direction,
                "date": t.created_at.isoformat() if t.created_at else None,
                "total_value": float(t.quantity * t.unit_cost) if t.unit_cost else 0
            } for t in recent_transactions
        ],
        "recent_payments": [
            {
                "id": p.id,
                "amount": float(p.total_amount),
                "direction": p.direction,
                "method": p.method,
                "date": p.payment_date.isoformat() if p.payment_date else None,
                "status": p.status
            } for p in recent_payments
        ],
        "recent_expenses": [
            {
                "id": e.id,
                "amount": float(e.amount),
                "description": e.description,
                "date": e.date.isoformat() if e.date else None,
                "payee_name": e.payee_name
            } for e in recent_expenses
        ],
        "recent_sales": [
            {
                "id": s.id,
                "amount": float(s.total_amount),
                "sale_number": s.sale_number,
                "date": s.sale_date.isoformat() if s.sale_date else None,
                "status": s.status
            } for s in recent_sales
        ]
    }


def _get_settlement_recommendation(balance: float, currency: str):
    """اقتراح التسوية مع التحقق من القطع غير المسعرة"""
    balance_view = utils.classify_entity_balance(balance)
    if balance_view["is_settled"]:
        return {
            "action": "متوازن",
            "message": "لا توجد تسوية مطلوبة",
            "amount": 0,
            "warnings": []
        }
    elif balance_view["balance"] > 0:  # الباقي له
        return {
            "action": "دفع",
            "message": f"يجب دفع {balance_view['owed_by_us']:.2f} {currency} للمورد",
            "amount": balance_view["owed_by_us"],
            "direction": "OUT",
            "warnings": []
        }
    else:  # الباقي عليه
        return {
            "action": "قبض",
            "message": f"يجب قبض {balance_view['owed_to_us']:.2f} {currency} من المورد",
            "amount": balance_view["owed_to_us"],
            "direction": "IN",
            "warnings": []
        }


# ═══════════════════════════════════════════════════════════════════════
# دوال مساعدة للتسوية الذكية الشاملة
# Helper Functions for Comprehensive Smart Settlement
# ═══════════════════════════════════════════════════════════════════════

def _check_required_fx_rates(currencies: list) -> dict:
    """
    التحقق من توفر أسعار الصرف المطلوبة
    يرجع قائمة بالعملات المفقودة إن وجدت
    """
    from models import fx_rate
    
    missing_rates = []
    available_rates = {}
    
    for currency in set(currencies):
        if currency == "ILS":
            continue
        
        try:
            rate = fx_rate(currency, "ILS", None, raise_on_missing=False)
            if rate <= 0:
                missing_rates.append(currency)
            else:
                available_rates[currency] = float(rate)
        except Exception:
            missing_rates.append(currency)
    
    return {
        "has_missing": len(missing_rates) > 0,
        "missing_currencies": missing_rates,
        "available_rates": available_rates
    }


def _convert_to_ils(amount: Decimal | float, from_currency: str, at: datetime = None) -> Decimal:
    """
    تحويل أي مبلغ إلى الشيكل (ILS)
    الأولوية: 1- السعر اليدوي المحلي 2- سعر السيرفر 3- خطأ (إدخال يدوي مطلوب)
    """
    from models import convert_amount, money
    
    if not amount or amount == 0:
        return Decimal('0.00')
    
    # تنظيف اسم العملة
    from_currency = (from_currency or "ILS").strip().upper()
    
    # إذا كانت بالفعل ILS، لا حاجة للتحويل
    if from_currency == "ILS":
        return _d2(amount)
    
    # التحويل - يستخدم fx_rate داخلياً:
    # 1. يبحث في قاعدة البيانات المحلية (السعر اليدوي)
    # 2. إن لم يجد، يحاول السيرفرات العالمية
    # 3. إن فشل كلاهما، يرفع ValueError
    converted = convert_amount(
        amount=amount,
        from_code=from_currency,
        to_code="ILS",
        at=at or datetime.now(timezone.utc).replace(tzinfo=None)
    )
    return _d2(converted)


def _get_supplier_exchange_items(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    جلب القطع من مستودع التبادل (ما أخذناه من المورد)
    مع تحويل العملات إلى ILS
    
    ✅ يجلب من ExchangeTransaction (المعاملات التاريخية في الفترة)
    ✅ يجلب أيضاً المخزون الحالي (StockLevel) غير المباع من مستودعات التبادل
    """
    from models import ExchangeTransaction, Warehouse, WarehouseType, StockLevel, Product
    from sqlalchemy import func
    
    transactions = db.session.query(ExchangeTransaction).options(
        joinedload(ExchangeTransaction.product)
    ).filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.direction.in_(['IN', 'PURCHASE', 'CONSIGN_IN']),
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).all()
    
    items = []
    unpriced_items = []
    total_ils = Decimal('0.00')
    
    for tx in transactions:
        prod = tx.product
        qty = Decimal(str(tx.quantity or 0))
        unit_cost = Decimal(str(tx.unit_cost or 0))
        
        if unit_cost == 0:
            if prod and prod.purchase_price:
                unit_cost = Decimal(str(prod.purchase_price))
            else:
                unpriced_items.append({
                    "id": tx.id,
                    "product_id": tx.product_id,
                    "product_name": prod.name if prod else "غير محدد",
                    "product_sku": prod.sku if prod else None,
                    "quantity": int(qty),
                    "date": tx.created_at.strftime("%Y-%m-%d") if tx.created_at else "",
                    "suggested_price": 0
                })
                continue
        
        value = qty * unit_cost
        
        product_currency = getattr(prod, 'currency', 'ILS') if prod else 'ILS'
        
        if product_currency != 'ILS':
            try:
                value_ils = _convert_to_ils(value, product_currency, tx.created_at)
            except Exception:
                value_ils = value
        else:
            value_ils = value
        
        total_ils += value_ils
        
        items.append({
            "id": tx.id,
            "product_id": tx.product_id,
            "product_name": prod.name if prod else "غير محدد",
            "product_sku": prod.sku if prod else None,
            "quantity": int(qty),
            "unit_cost": float(unit_cost),
            "total_value": float(value_ils),
            "date": tx.created_at.strftime("%Y-%m-%d") if tx.created_at else "",
            "currency": "ILS",
            "type": "transaction"
        })
    
    exchange_warehouses = db.session.query(Warehouse.id).filter(
        Warehouse.supplier_id == supplier_id,
        Warehouse.warehouse_type == WarehouseType.EXCHANGE.value
    ).all()
    
    warehouse_ids = [w[0] for w in exchange_warehouses]
    current_stock_items = []
    total_stock_ils = Decimal('0.00')
    
    if warehouse_ids:
        current_stock = db.session.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Product.sku,
            Product.purchase_price,
            Product.currency,
            func.sum(StockLevel.quantity).label("total_qty")
        ).join(
            StockLevel, StockLevel.product_id == Product.id
        ).filter(
            StockLevel.warehouse_id.in_(warehouse_ids),
            StockLevel.quantity > 0
        ).group_by(
            Product.id, Product.name, Product.sku, Product.purchase_price, Product.currency
        ).all()
        
        for stock in current_stock:
            qty = Decimal(str(stock.total_qty or 0))
            unit_cost = Decimal(str(stock.purchase_price or 0))
            
            if unit_cost == 0:
                unpriced_items.append({
                    "id": None,
                    "product_id": stock.product_id,
                    "product_name": stock.product_name or "غير محدد",
                    "product_sku": stock.sku,
                    "quantity": int(qty),
                    "date": "",
                    "suggested_price": 0,
                    "is_current_stock": True
                })
                continue
            
            value = qty * unit_cost
            product_currency = stock.currency or 'ILS'
            
            if product_currency != 'ILS':
                try:
                    value_ils = _convert_to_ils(value, product_currency, datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception:
                    value_ils = value
            else:
                value_ils = value
            
            total_stock_ils += value_ils
            
            current_stock_items.append({
                "id": None,
                "product_id": stock.product_id,
                "product_name": stock.product_name or "غير محدد",
                "product_sku": stock.sku,
                "quantity": int(qty),
                "unit_cost": float(unit_cost),
                "total_value": float(value_ils),
                "date": "",
                "currency": "ILS",
                "type": "current_stock"
            })
    
    return {
        "items": items,
        "current_stock_items": current_stock_items,
        "unpriced_items": unpriced_items,
        "total_value_ils": float(total_ils),
        "total_stock_ils": float(total_stock_ils),
        "count": len(items)
    }


def _get_sales_to_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    مبيعات للمورد (كعميل) - تُخصم من حقوقه
    """
    from models import Sale, SaleLine, Product, Supplier
    
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or not supplier.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    sales = db.session.query(
        Sale.id.label("sale_id"),
        Sale.sale_number,
        Sale.sale_date,
        Sale.currency,
        Sale.total_amount,
        Sale.status
    ).filter(
        Sale.customer_id == supplier.customer_id,
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to,
        Sale.status == SaleStatus.CONFIRMED
    ).order_by(Sale.sale_date).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for sale in sales:
        # جلب تفاصيل الأسطر
        sale_lines = db.session.query(
            Product.name.label("product_name"),
            SaleLine.quantity,
            SaleLine.unit_price
        ).join(
            Product, Product.id == SaleLine.product_id
        ).filter(
            SaleLine.sale_id == sale.sale_id
        ).all()
        
        amount_ils = _convert_to_ils(Decimal(str(sale.total_amount or 0)), sale.currency, sale.sale_date)
        total_ils += amount_ils
        
        items.append({
            "sale_id": sale.sale_id,
            "sale_number": sale.sale_number,
            "date": sale.sale_date.strftime("%Y-%m-%d") if sale.sale_date else "",
            "products": [{"name": sl.product_name, "qty": sl.quantity, "price": float(sl.unit_price)} for sl in sale_lines],
            "amount": float(sale.total_amount or 0),
            "currency": sale.currency,
            "amount_ils": float(amount_ils),
            "status": sale.status
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_services_to_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    رسوم صيانة على المورد (كعميل) - تُخصم من حقوقه
    """
    from models import ServiceRequest, Supplier
    
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or not supplier.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    services = db.session.query(ServiceRequest).filter(
        ServiceRequest.customer_id == supplier.customer_id,
        ServiceRequest.received_at >= date_from,
        ServiceRequest.received_at <= date_to,
        ServiceRequest.status == ServiceStatus.COMPLETED.value
    ).order_by(ServiceRequest.received_at).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for service in services:
        amount_ils = _convert_to_ils(Decimal(str(service.total_amount or 0)), service.currency, service.received_at)
        total_ils += amount_ils
        
        items.append({
            "service_id": service.id,
            "service_number": service.service_number,
            "date": service.received_at.strftime("%Y-%m-%d") if service.received_at else "",
            "description": service.description or service.problem_description,
            "amount": float(service.total_amount or 0),
            "currency": service.currency,
            "amount_ils": float(amount_ils),
            "status": service.status
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_payments_to_supplier(supplier_id: int, supplier, date_from: datetime, date_to: datetime):
    """
    دفعات دفعناها للمورد (OUT) - تُخصم من حقوقه
    ✅ تستثني الشيكات المرتدة (لأنها كانت محسوبة سابقاً)
    
    تشمل:
    1. الدفعات المرتبطة مباشرة بـ supplier_id
    2. الدفعات المرتبطة بـ customer_id (العميل المرتبط بالمورد)
    3. الدفعات المرتبطة بمبيعات للعميل (entity_type = SALE)
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentEntityType, Sale, Check
    from sqlalchemy import or_
    
    items = []
    total_ils = Decimal('0.00')
    
    # 1. الدفعات المرتبطة مباشرة بالمورد
    direct_payments = db.session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    for payment in direct_payments:
        amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
        total_ils += amount_ils
        
        items.append({
            "payment_id": payment.id,
            "payment_number": payment.payment_number,
            "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
            "method": payment.method,
            "check_number": payment.check_number,
            "amount": float(payment.total_amount or 0),
            "currency": payment.currency,
            "amount_ils": float(amount_ils),
            "notes": payment.notes,
            "source": "supplier"
        })
    
    # 2. الدفعات المرتبطة بالعميل المرتبط بالمورد
    if supplier.customer_id:
        customer_payments = db.session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in customer_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "customer"
                })
        
        # 3. الدفعات المرتبطة بمبيعات للعميل (استثناء الشيكات المرتدة)
        sale_payments = db.session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in sale_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "sale"
                })
    
    # ✅ 4. الدفعات المرتبطة بمصروفات المورد (توريد خدمة) - خارج if supplier.customer_id
    from models import Expense
    expense_payments = db.session.query(Payment).join(
        Expense, Expense.id == Payment.expense_id
    ).filter(
        or_(
            Expense.supplier_id == supplier_id,
            and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
        ),
        Payment.direction == PaymentDirection.OUT,
        Payment.status == PaymentStatus.COMPLETED,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    for payment in expense_payments:
        if not any(item['payment_id'] == payment.id for item in items):
            amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
            total_ils += amount_ils
            
            items.append({
                "payment_id": payment.id,
                "payment_number": payment.payment_number,
                "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                "method": payment.method,
                "check_number": payment.check_number,
                "amount": float(payment.total_amount or 0),
                "currency": payment.currency,
                "amount_ils": float(amount_ils),
                "notes": payment.notes or f"دفع مصروف #{payment.expense_id}",
                "source": "expense"
            })
    
    if supplier.customer_id:
        # 5. الدفعات المرتبطة بفواتير للعميل (استثناء الشيكات المرتدة)
        from models import Invoice
        invoice_payments = db.session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in invoice_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "invoice"
                })
        
        # 5. الدفعات المرتبطة بخدمات للعميل (استثناء الشيكات المرتدة)
        from models import ServiceRequest
        service_payments = db.session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in service_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "service"
                })
        
        # 6. الدفعات المرتبطة بحجوزات مسبقة للعميل (استثناء الشيكات المرتدة)
        from models import PreOrder
        preorder_payments = db.session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in preorder_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "preorder"
                })
    
    # ✅ 7. الشيكات اليدوية (بدون payment_id) المرتبطة بالمورد مباشرة
    from models import Check, CheckStatus
    manual_checks = db.session.query(Check).filter(
        Check.supplier_id == supplier_id,
        Check.payment_id.is_(None),
        Check.direction == PaymentDirection.OUT.value,
        ~Check.status.in_([CheckStatus.RETURNED.value, CheckStatus.BOUNCED.value, CheckStatus.CANCELLED.value, CheckStatus.ARCHIVED.value]),
        Check.check_date >= date_from,
        Check.check_date <= date_to
    ).all()
    
    for check in manual_checks:
        amount_ils = _convert_to_ils(Decimal(str(check.amount or 0)), check.currency or 'ILS', check.check_date or date_from)
        total_ils += amount_ils
        
        items.append({
            "check_id": check.id,
            "payment_id": None,
            "payment_number": None,
            "date": check.check_date.strftime("%Y-%m-%d") if check.check_date else "",
            "method": "CHEQUE",
            "check_number": check.check_number,
            "amount": float(check.amount or 0),
            "currency": check.currency or 'ILS',
            "amount_ils": float(amount_ils),
            "notes": check.notes or "شيك يدوي",
            "source": "manual_check"
        })
    
    # ترتيب حسب التاريخ
    items.sort(key=lambda x: x['date'])
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_payments_from_supplier(supplier_id: int, supplier, date_from: datetime, date_to: datetime):
    """
    دفعات استلمناها من المورد (IN) - تُحسب له (تُخصم)
    
    تشمل:
    1. الدفعات المرتبطة مباشرة بـ supplier_id
    2. الدفعات المرتبطة بـ customer_id (العميل المرتبط بالمورد)
    3. الدفعات المرتبطة بمبيعات للعميل (entity_type = SALE)
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentEntityType, Sale, Check
    from sqlalchemy import or_
    
    items = []
    total_ils = Decimal('0.00')
    
    # 1. الدفعات المرتبطة مباشرة بالمورد
    direct_payments = db.session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.supplier_id == supplier_id,
        Payment.direction == PaymentDirection.IN,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    for payment in direct_payments:
        amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
        total_ils += amount_ils
        
        items.append({
            "payment_id": payment.id,
            "payment_number": payment.payment_number,
            "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
            "method": payment.method,
            "check_number": payment.check_number,
            "amount": float(payment.total_amount or 0),
            "currency": payment.currency,
            "amount_ils": float(amount_ils),
            "notes": payment.notes,
            "source": "supplier"
        })
    
    # 2. الدفعات المرتبطة بالعميل المرتبط بالمورد (استثناء الشيكات المرتدة)
    if supplier.customer_id:
        customer_payments = db.session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in customer_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "customer"
                })
        
        # 3. الدفعات المرتبطة بمبيعات للعميل (استثناء الشيكات المرتدة)
        sale_payments = db.session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in sale_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "sale"
                })
        
        # 4. الدفعات المرتبطة بفواتير للعميل (استثناء الشيكات المرتدة)
        from models import Invoice
        invoice_payments = db.session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in invoice_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "invoice"
                })
        
        # 5. الدفعات المرتبطة بخدمات للعميل (استثناء الشيكات المرتدة)
        from models import ServiceRequest
        service_payments = db.session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in service_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "service"
                })
        
        # 5. الدفعات المرتبطة بحجوزات مسبقة للعميل (استثناء الشيكات المرتدة)
        from models import PreOrder
        preorder_payments = db.session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == supplier.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in preorder_payments:
            if not any(item['payment_id'] == payment.id for item in items):
                amount_ils = _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)
                total_ils += amount_ils
                
                items.append({
                    "payment_id": payment.id,
                    "payment_number": payment.payment_number,
                    "date": payment.payment_date.strftime("%Y-%m-%d") if payment.payment_date else "",
                    "method": payment.method,
                    "check_number": payment.check_number,
                    "amount": float(payment.total_amount or 0),
                    "currency": payment.currency,
                    "amount_ils": float(amount_ils),
                    "notes": payment.notes,
                    "source": "preorder"
                })
    
    # ✅ 7. الشيكات اليدوية (بدون payment_id) المرتبطة بالمورد مباشرة
    from models import Check, CheckStatus
    manual_checks = db.session.query(Check).filter(
        Check.supplier_id == supplier_id,
        Check.payment_id.is_(None),
        Check.direction == PaymentDirection.IN.value,
        ~Check.status.in_([CheckStatus.RETURNED.value, CheckStatus.BOUNCED.value, CheckStatus.CANCELLED.value, CheckStatus.ARCHIVED.value]),
        Check.check_date >= date_from,
        Check.check_date <= date_to
    ).all()
    
    for check in manual_checks:
        amount_ils = _convert_to_ils(Decimal(str(check.amount or 0)), check.currency or 'ILS', check.check_date or date_from)
        total_ils += amount_ils
        
        items.append({
            "check_id": check.id,
            "payment_id": None,
            "payment_number": None,
            "date": check.check_date.strftime("%Y-%m-%d") if check.check_date else "",
            "method": "CHEQUE",
            "check_number": check.check_number,
            "amount": float(check.amount or 0),
            "currency": check.currency or 'ILS',
            "amount_ils": float(amount_ils),
            "notes": check.notes or "شيك يدوي",
            "source": "manual_check"
        })
    
    # ترتيب حسب التاريخ
    items.sort(key=lambda x: x['date'])
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_supplier_preorders(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    حجوزات مسبقة للمورد (إذا كان عميلاً)
    تُحسب فقط الإجمالي (عليه)، بدون العربون
    """
    from models import PreOrder, Supplier
    
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or not supplier.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    items = []
    total_ils = Decimal('0.00')
    
    preorders = db.session.query(PreOrder).filter(
        PreOrder.customer_id == supplier.customer_id,
        PreOrder.status.in_(['CONFIRMED', 'COMPLETED', 'DELIVERED']),
        PreOrder.status != 'FULFILLED',
        PreOrder.created_at >= date_from,
        PreOrder.created_at <= date_to
    ).all()
    
    for po in preorders:
        # تحويل إلى ILS
        amount_ils = _convert_to_ils(
            Decimal(str(po.total_amount or 0)),
            po.currency or 'ILS',
            po.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
        )
        total_ils += amount_ils
        
        items.append({
            "preorder_id": po.id,
            "preorder_number": po.preorder_number or f"PO-{po.id}",
            "date": po.created_at.strftime("%Y-%m-%d") if po.created_at else "",
            "total_amount": float(po.total_amount or 0),
            "amount_ils": float(amount_ils),
            "currency": po.currency or 'ILS',
            "status": po.status
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_supplier_preorders_prepaid(supplier_id: int, supplier: Supplier, date_from: datetime, date_to: datetime):
    """
    أرصدة الحجوزات المسبقة (العربون) للمورد - تُحسب كدفعة واردة
    """
    from models import PreOrder
    
    if not supplier.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    preorders = db.session.query(PreOrder).filter(
        PreOrder.customer_id == supplier.customer_id,
        PreOrder.prepaid_amount > 0,
        PreOrder.status != 'FULFILLED',
        PreOrder.preorder_date >= date_from,
        PreOrder.preorder_date <= date_to
    ).order_by(PreOrder.preorder_date).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for po in preorders:
        amount_ils = _convert_to_ils(
            Decimal(str(po.prepaid_amount or 0)),
            po.currency or 'ILS',
            po.preorder_date or datetime.now(timezone.utc).replace(tzinfo=None)
        )
        total_ils += amount_ils
        
        items.append({
            "preorder_id": po.id,
            "reference": po.reference,
            "date": po.preorder_date.strftime("%Y-%m-%d") if po.preorder_date else "",
            "amount": float(po.prepaid_amount or 0),
            "currency": po.currency or 'ILS',
            "amount_ils": float(amount_ils),
            "status": po.status,
            "product": po.product.name if po.product else ""
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_returns_to_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    """
    مرتجعات للمورد (OUT من Exchange) - قطع رجعناها له
    """
    from models import ExchangeTransaction, Warehouse, WarehouseType, Product
    
    # جلب مستودعات التبادل
    exchange_warehouses = db.session.query(Warehouse.id).filter(
        Warehouse.supplier_id == supplier_id,
        Warehouse.warehouse_type == WarehouseType.EXCHANGE.value
    ).all()
    
    warehouse_ids = [w[0] for w in exchange_warehouses]
    
    if not warehouse_ids:
        return {"items": [], "total_value_ils": 0.0, "count": 0}
    
    # المعاملات OUT (قطع رجعناها للمورد)
    transactions = db.session.query(ExchangeTransaction).options(
        joinedload(ExchangeTransaction.product)
    ).filter(
        ExchangeTransaction.warehouse_id.in_(warehouse_ids),
        ExchangeTransaction.direction.in_(['OUT', 'RETURN', 'CONSIGN_OUT']),
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for tx in transactions:
        prod = tx.product
        qty = Decimal(str(tx.quantity or 0))
        unit_cost = Decimal(str(tx.unit_cost or 0))
        
        if unit_cost == 0 and prod and prod.purchase_price:
            unit_cost = Decimal(str(prod.purchase_price))
        
        value_ils = qty * unit_cost
        total_ils += value_ils
        
        items.append({
            "id": tx.id,
            "product_name": prod.name if prod else "غير محدد",
            "product_sku": prod.sku if prod else None,
            "quantity": int(qty),
            "unit_cost": float(unit_cost),
            "total_value": float(value_ils),
            "date": tx.created_at.strftime("%Y-%m-%d") if tx.created_at else "",
            "currency": "ILS"
        })
    
    return {
        "items": items,
        "total_value_ils": float(total_ils),
        "count": len(items)
    }


def _get_previous_supplier_settlements(supplier_id: int, before_date: datetime):
    """جلب التسويات السابقة للمورد"""
    from models import SupplierSettlement
    from sqlalchemy import desc
    
    settlements = db.session.query(SupplierSettlement).filter(
        SupplierSettlement.supplier_id == supplier_id,
        SupplierSettlement.created_at < before_date
    ).order_by(desc(SupplierSettlement.created_at)).limit(5).all()
    
    return [{
        "id": s.id,
        "code": s.code,
        "date": s.created_at,
        "status": s.status,
        "total_due": float(s.total_due or 0),
        "currency": s.currency,
        "from_date": s.from_date,
        "to_date": s.to_date
    } for s in settlements]


def _get_supplier_old_debts(supplier_id: int, before_date: datetime):
    """جلب الديون القديمة للمورد (قبل الفترة)"""
    # يمكن إضافة منطق للديون القديمة إذا كانت مسجلة في مكان ما
    # حالياً نرجع 0
    return 0


def _get_previous_supplier_settlements(supplier_id: int, before_date: datetime):
    """جلب التسويات السابقة للمورد"""
    from models import SupplierSettlement
    from sqlalchemy import desc
    
    settlements = db.session.query(SupplierSettlement).filter(
        SupplierSettlement.supplier_id == supplier_id,
        SupplierSettlement.created_at < before_date
    ).order_by(desc(SupplierSettlement.created_at)).limit(5).all()
    
    return [{
        "id": s.id,
        "code": s.code,
        "date": s.created_at,
        "status": s.status,
        "total_due": float(s.total_due or 0),
        "currency": s.currency,
        "from_date": s.from_date,
        "to_date": s.to_date
    } for s in settlements]


def _get_supplier_consignment_value(supplier_id: int):
    """حساب قيمة العهدة المتبقية في المخزون"""
    from models import Warehouse, WarehouseType, StockLevel, Product
    from sqlalchemy import func
    
    # جلب مستودعات التبادل للمورد
    exchange_warehouses = db.session.query(Warehouse.id).filter(
        Warehouse.supplier_id == supplier_id,
        Warehouse.warehouse_type == WarehouseType.EXCHANGE.value
    ).all()
    
    warehouse_ids = [w[0] for w in exchange_warehouses]
    
    if not warehouse_ids:
        return 0
    
    # حساب القيمة الإجمالية للعهدة
    rows = db.session.query(
        func.sum(StockLevel.quantity * Product.purchase_price)
    ).join(
        Product, Product.id == StockLevel.product_id
    ).filter(
        StockLevel.warehouse_id.in_(warehouse_ids),
        StockLevel.quantity > 0
    ).scalar() or 0
    
    return float(rows)


@supplier_settlements_bp.route("/<int:supplier_id>/settlement/approve", methods=["POST"], endpoint="approve_settlement")
@login_required
def approve_settlement(supplier_id):
    from flask import flash, redirect
    from flask_login import current_user
    from models import SupplierSettlement
    
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        abort(404)
    db.session.refresh(supplier)
    
    date_from = request.form.get("date_from")
    date_to = request.form.get("date_to")
    
    if not date_from or not date_to:
        flash("يجب تحديد الفترة الزمنية", "error")
        return redirect(url_for("supplier_settlements_bp.supplier_settlement", supplier_id=supplier_id))
    
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00")) if isinstance(date_from, str) else date_from
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")) if isinstance(date_to, str) else date_to
    except Exception:
        flash("تنسيق التاريخ غير صحيح", "error")
        return redirect(url_for("supplier_settlements_bp.supplier_settlement", supplier_id=supplier_id))
    
    balance_data = _calculate_smart_supplier_balance(supplier_id, date_from_dt, date_to_dt)
    
    if not balance_data.get("success"):
        flash(balance_data.get("error", "خطأ في حساب التسوية"), "error")
        return redirect(url_for("supplier_settlements_bp.supplier_settlement", supplier_id=supplier_id))
    
    prev_settlement = db.session.query(SupplierSettlement).filter(
        SupplierSettlement.supplier_id == supplier_id,
        SupplierSettlement.is_approved == True
    ).order_by(SupplierSettlement.to_date.desc()).first()
    
    settlement = SupplierSettlement(
        supplier_id=supplier_id,
        from_date=date_from_dt,
        to_date=date_to_dt,
        currency="ILS",
        status=SupplierSettlementStatus.CONFIRMED.value,
        previous_settlement_id=prev_settlement.id if prev_settlement else None,
        opening_balance=Decimal(str(balance_data.get("opening_balance", {}).get("amount", 0))),
        rights_exchange=Decimal(str(balance_data.get("rights", {}).get("exchange_items", {}).get("total_value_ils", 0))),
        rights_total=Decimal(str(balance_data.get("rights", {}).get("total", 0))),
        obligations_sales=Decimal(str(balance_data.get("obligations", {}).get("sales_to_supplier", {}).get("total_ils", 0))),
        obligations_services=Decimal(str(balance_data.get("obligations", {}).get("services_to_supplier", {}).get("total_ils", 0))),
        obligations_preorders=Decimal(str(balance_data.get("obligations", {}).get("preorders_to_supplier", {}).get("total_ils", 0) if isinstance(balance_data.get("obligations", {}).get("preorders_to_supplier"), dict) else 0)),
        obligations_expenses=Decimal(str(balance_data.get("expenses", {}).get("total_ils", 0))),
        obligations_total=Decimal(str(balance_data.get("obligations", {}).get("total", 0))),
        payments_out=Decimal(str(balance_data.get("payments", {}).get("total_paid", 0))),
        payments_in=Decimal(str(balance_data.get("payments", {}).get("total_received", 0))),
        payments_returns=Decimal(str(balance_data.get("payments", {}).get("total_returns", 0))),
        payments_net=Decimal(str(balance_data.get("payments", {}).get("total_settled", 0))),
        closing_balance=Decimal(str(balance_data.get("balance", {}).get("net", 0))),
        is_approved=True,
        approved_by=current_user.id,
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    settlement.ensure_code()
    
    db.session.add(settlement)
    db.session.flush()
    
    try:
        from models import _gl_upsert_batch_and_entries, GL_ACCOUNTS
        
        ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
        cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")
        
        closing_balance_amount = float(settlement.closing_balance or 0)
        
        if abs(closing_balance_amount) > 0.01:
            if closing_balance_amount > 0:
                entries = [
                    (ap_account, closing_balance_amount, 0),
                    (cash_account, 0, closing_balance_amount),
                ]
                memo = f"تسوية مورد #{settlement.code} - له علينا {closing_balance_amount:.2f} ₪"
            else:
                entries = [
                    (cash_account, abs(closing_balance_amount), 0),
                    (ap_account, 0, abs(closing_balance_amount)),
                ]
                memo = f"تسوية مورد #{settlement.code} - عليه لنا {abs(closing_balance_amount):.2f} ₪"
            
            _gl_upsert_batch_and_entries(
                db.session.connection(),
                source_type="SUPPLIER_SETTLEMENT",
                source_id=settlement.id,
                purpose="SETTLEMENT",
                currency="ILS",
                memo=memo,
                entries=entries,
                ref=settlement.code,
                entity_type="SUPPLIER",
                entity_id=supplier_id
            )
    except Exception as e:
        current_app.logger.error(f"⚠️ خطأ في إنشاء قيد GL للتسوية #{settlement.code}: {e}")
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
        return redirect(url_for("supplier_settlements_bp.supplier_settlement", supplier_id=supplier_id))
    
    from utils.supplier_balance_updater import update_supplier_balance_components
    update_supplier_balance_components(supplier_id)
    
    flash(f"تم اعتماد التسوية {settlement.code} بنجاح", "success")
    return redirect(url_for("supplier_settlements_bp.show_settlement", settlement_id=settlement.id))


@supplier_settlements_bp.route("/settlements/approved", methods=["GET"], endpoint="approved_settlements_list")
@login_required
def approved_settlements_list():
    from sqlalchemy import desc
    
    settlements = db.session.query(SupplierSettlement).filter(
        SupplierSettlement.is_approved == True
    ).order_by(desc(SupplierSettlement.approved_at)).all()
    
    for settlement in settlements:
        db.session.refresh(settlement)
        if settlement.supplier:
            db.session.refresh(settlement.supplier)
    
    return render_template(
        "vendors/suppliers/settlements_list.html",
        settlements=settlements
    )


@supplier_settlements_bp.route("/settlements/<int:settlement_id>/show", methods=["GET"], endpoint="show_settlement")
@login_required
def show_settlement(settlement_id):
    settlement = db.session.get(SupplierSettlement, settlement_id)
    if not settlement:
        abort(404)
    
    db.session.refresh(settlement)
    if settlement.supplier:
        db.session.refresh(settlement.supplier)
    
    if not settlement.is_approved:
        from flask import flash, redirect
        flash("هذه التسوية غير معتمدة", "warning")
        return redirect(url_for("supplier_settlements_bp.supplier_settlement", supplier_id=settlement.supplier_id))
    
    balance_data = _calculate_smart_supplier_balance(
        settlement.supplier_id,
        settlement.from_date,
        settlement.to_date
    )
    
    from models import GLBatch
    gl_batch = db.session.query(GLBatch).filter(
        GLBatch.source_type == "SUPPLIER_SETTLEMENT",
        GLBatch.source_id == settlement_id
    ).first()
    
    return render_template(
        "vendors/suppliers/settlement_show.html",
        settlement=settlement,
        supplier=settlement.supplier,
        balance_data=balance_data,
        gl_batch=gl_batch
    )

@supplier_settlements_bp.route("/<int:supplier_id>/inventory", endpoint="supplier_inventory")
@login_required
def supplier_inventory(supplier_id):
    """
    تقرير مخزون المورد: يعرض المنتجات التي تم شراؤها من المورد وما زالت في المخزون.
    """
    from models import Supplier, Product, StockLevel, Warehouse
    
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        abort(404)
    
    # Products where this supplier is the primary supplier
    items = db.session.query(
        Product,
        StockLevel.quantity,
        Warehouse.name.label('warehouse_name')
    ).join(
        StockLevel, StockLevel.product_id == Product.id
    ).join(
        Warehouse, Warehouse.id == StockLevel.warehouse_id
    ).filter(
        Product.supplier_id == supplier_id,
        StockLevel.quantity > 0
    ).all()
    
    inventory = []
    total_value = 0
    
    for prod, qty, wh_name in items:
        qty = float(qty or 0)
        cost = float(prod.purchase_price or 0)
        val = qty * cost
        
        inventory.append({
            "product_name": prod.name,
            "sku": prod.sku,
            "warehouse": wh_name,
            "quantity": qty,
            "unit_cost": cost,
            "total_value": round(val, 2)
        })
        total_value += val
        
    return render_template(
        "vendors/suppliers/inventory.html",
        supplier=supplier,
        inventory=inventory,
        total_value=round(total_value, 2)
    )
