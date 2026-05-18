
from datetime import datetime, date as _date, time as _time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request, jsonify, render_template, url_for, abort, current_app
from flask_login import login_required
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
import utils
from models import Partner, PaymentDirection, PaymentMethod, PartnerSettlement, PartnerSettlementStatus, build_partner_settlement_draft, AuditLog, SaleStatus, ServiceStatus, Expense, ExpenseType
import json

partner_settlements_bp = Blueprint("partner_settlements_bp", __name__, url_prefix="/partners")

def get_unpriced_partner_products():
    """
    جلب القطع غير المسعّرة للشركاء
    Returns: list of dicts with product info
    """
    from models import (
        WarehousePartnerShare, ProductPartner, Product, 
        Partner, StockLevel, Warehouse
    )
    from sqlalchemy import or_
    
    unpriced_items = []
    
    wps_unpriced = db.session.query(
        WarehousePartnerShare.partner_id,
        Partner.name.label("partner_name"),
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.sku,
        Product.purchase_price,
        Product.selling_price,
        WarehousePartnerShare.share_percentage.label("share_pct")
    ).join(
        Partner, Partner.id == WarehousePartnerShare.partner_id
    ).join(
        Product, Product.id == WarehousePartnerShare.product_id
    ).filter(
        or_(
            Product.purchase_price == None,
            Product.purchase_price == 0,
            Product.selling_price == None,
            Product.selling_price == 0
        )
    ).all()
    
    for item in wps_unpriced:
        has_stock = db.session.query(StockLevel).filter(
            StockLevel.product_id == item.product_id,
            StockLevel.quantity > 0
        ).first() is not None
        
        unpriced_items.append({
            "partner_id": item.partner_id,
            "partner_name": item.partner_name,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "sku": item.sku,
            "purchase_price": float(item.purchase_price or 0),
            "selling_price": float(item.selling_price or 0),
            "share_percentage": float(item.share_pct),
            "has_stock": has_stock,
            "missing": []
        })
        
        if not item.purchase_price or item.purchase_price == 0:
            unpriced_items[-1]["missing"].append("purchase_price")
        if not item.selling_price or item.selling_price == 0:
            unpriced_items[-1]["missing"].append("selling_price")
    
    pp_unpriced = db.session.query(
        ProductPartner.partner_id,
        Partner.name.label("partner_name"),
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.sku,
        Product.purchase_price,
        Product.selling_price,
        ProductPartner.share_percent.label("share_pct")
    ).join(
        Partner, Partner.id == ProductPartner.partner_id
    ).join(
        Product, Product.id == ProductPartner.product_id
    ).filter(
        or_(
            Product.purchase_price == None,
            Product.purchase_price == 0,
            Product.selling_price == None,
            Product.selling_price == 0
        )
    ).all()
    
    existing_ids = {(item["partner_id"], item["product_id"]) for item in unpriced_items}
    
    for item in pp_unpriced:
        if (item.partner_id, item.product_id) in existing_ids:
            continue
        
        has_stock = db.session.query(StockLevel).filter(
            StockLevel.product_id == item.product_id,
            StockLevel.quantity > 0
        ).first() is not None
        
        unpriced_items.append({
            "partner_id": item.partner_id,
            "partner_name": item.partner_name,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "sku": item.sku,
            "purchase_price": float(item.purchase_price or 0),
            "selling_price": float(item.selling_price or 0),
            "share_percentage": float(item.share_pct),
            "has_stock": has_stock,
            "missing": []
        })
        
        if not item.purchase_price or item.purchase_price == 0:
            unpriced_items[-1]["missing"].append("purchase_price")
        if not item.selling_price or item.selling_price == 0:
            unpriced_items[-1]["missing"].append("selling_price")
    
    return unpriced_items

@partner_settlements_bp.route("/unpriced-items", methods=["GET"])
@login_required
def check_unpriced_items():
    """التحقق من القطع غير المسعّرة للشركاء"""
    unpriced = get_unpriced_partner_products()
    return jsonify({
        "success": True,
        "count": len(unpriced),
        "items": unpriced
    })

@partner_settlements_bp.route("/settlements", methods=["GET"], endpoint="list")
@login_required
def settlements_list():
    """قائمة تسويات الشركاء"""
    return render_template("partner_settlements/list.html")

def _get_partner_or_404(pid: int) -> Partner:
    obj = db.session.get(Partner, pid)
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

def _overlap_exists(partner_id: int, dfrom: datetime, dto: datetime) -> bool:
    return db.session.query(PartnerSettlement.id).filter(
        PartnerSettlement.partner_id == partner_id,
        PartnerSettlement.status.in_([PartnerSettlementStatus.DRAFT.value, PartnerSettlementStatus.CONFIRMED.value]),
        and_(PartnerSettlement.from_date <= dto, PartnerSettlement.to_date >= dfrom)
    ).first() is not None

@partner_settlements_bp.route("/<int:partner_id>/settlements/preview", methods=["GET"])
@login_required
def preview(partner_id):
    from flask import redirect
    return redirect(url_for('partner_settlements_bp.partner_settlement', partner_id=partner_id))

@partner_settlements_bp.route("/<int:partner_id>/settlements/create", methods=["POST"])
@login_required
def create(partner_id):
    partner = _get_partner_or_404(partner_id)
    dfrom, dto, err = _extract_range_from_request()
    if err:
        return jsonify({"success": False, "error": err}), 400
    draft = build_partner_settlement_draft(partner.id, dfrom, dto, currency=partner.currency)
    lines = getattr(draft, "lines", []) or []
    if not lines:
        return jsonify({"success": False, "error": "لا توجد سطور لتسويتها"}), 400
    if _currency_mismatch(lines, partner.currency):
        return jsonify({"success": False, "error": "عملة غير متطابقة داخل التسوية"}), 400
    if _overlap_exists(partner.id, dfrom, dto):
        return jsonify({"success": False, "error": "نطاق متداخل مع تسوية سابقة"}), 409
    due = Decimal(str(draft.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if due == Decimal("0.00"):
        return jsonify({"success": False, "error": "لا توجد مبالغ مستحقة"}), 400
    draft.ensure_code()
    draft.from_date = dfrom
    draft.to_date = dto
    draft.currency = partner.currency
    try:
        with db.session.begin_nested():
            db.session.add(draft)
            db.session.flush()
            db.session.add(AuditLog(model_name="PartnerSettlement", record_id=draft.id, action="CREATE", old_data=None, new_data=json.dumps({
                "partner_id": partner.id, "from": dfrom.isoformat(), "to": dto.isoformat(), "total_due": str(due), "code": draft.code
            })))
    except SQLAlchemyError as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
    direction = _due_direction(due)
    amount_str = f"{abs(due):.2f}"
    pay_url = url_for(
        "payments.create_payment",
        entity_type="PARTNER",   # <-- كانت "partner"
        entity_id=str(partner.id),
        direction=direction,
        total_amount=amount_str,
        currency=partner.currency,
        method=PaymentMethod.BANK.value,
        reference=f"PartnerSettle:{draft.code}",
        notes=f"تسوية شريك {partner.name} {dfrom.date()} - {dto.date()} ({draft.code})",
    )
    return jsonify({"success": True, "id": draft.id, "code": draft.code, "pay_url": pay_url})

@partner_settlements_bp.route("/settlements/<int:settlement_id>/confirm", methods=["POST"])
@login_required
def confirm(settlement_id):
    ps = db.session.get(PartnerSettlement, settlement_id)
    if not ps:
        abort(404)
    if ps.status != PartnerSettlementStatus.DRAFT.value:
        return jsonify({"success": False, "error": "Only DRAFT can be confirmed"}), 400
    recalc = build_partner_settlement_draft(ps.partner_id, ps.from_date, ps.to_date, currency=ps.currency)
    orig = Decimal(str(ps.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    now_ = Decimal(str(recalc.total_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if orig != now_ or len(getattr(ps, "lines", []) or []) != len(getattr(recalc, "lines", []) or []):
        return jsonify({"success": False, "error": "اختلفت البيانات منذ المعاينة، أعد الإنشاء"}), 409
    try:
        with db.session.begin_nested():
            ps.mark_confirmed()
            db.session.flush()
            db.session.add(AuditLog(model_name="PartnerSettlement", record_id=ps.id, action="CONFIRM", old_data=None, new_data=json.dumps({
                "code": ps.code, "from": ps.from_date.isoformat(), "to": ps.to_date.isoformat(), "total_due": str(orig)
            })))
    except SQLAlchemyError as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
    return jsonify({"success": True, "id": ps.id, "code": ps.code})

@partner_settlements_bp.route("/settlements/<int:settlement_id>", methods=["GET"])
@login_required
def show(settlement_id):
    from flask import jsonify
    ps = db.session.get(PartnerSettlement, settlement_id)
    if not ps:
        abort(404)
    
    try:
        settlement_data = {
            "code": ps.code or "N/A",
            "from_date": ps.from_date,
            "to_date": ps.to_date,
            "opening_balance": float(ps.opening_balance or 0),
            "rights": {
                "inventory": float(ps.rights_inventory or 0),
                "sales_share": float(ps.rights_sales_share or 0),
                "preorders": float(ps.rights_preorders or 0),
                "total": float(ps.rights_total or 0)
            },
            "obligations": {
                "sales": float(ps.obligations_sales_to_partner or 0),
                "services": float(ps.obligations_services or 0),
                "damaged": float(ps.obligations_damaged or 0),
                "returns": float(ps.obligations_returns or 0),
                "total": float(ps.obligations_total or 0)
            },
            "expenses": {
                "total_ils": float(ps.obligations_expenses or 0)
            },
            "payments": {
                "out": float(ps.payments_out or 0),
                "in": float(ps.payments_in or 0),
                "net": float(ps.payments_net or 0)
            },
            "closing_balance": float(ps.closing_balance or 0),
            "approved_by": ps.approved_by_user.username if ps.approved_by_user else "N/A",
            "approved_at": ps.approved_at
        }
        
        return render_template(
            "vendors/partners/settlement_detail.html",
            settlement=ps,
            settlement_data=settlement_data,
            partner=ps.partner
        )
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500



@partner_settlements_bp.route("/<int:partner_id>/settlement", methods=["GET"], endpoint="partner_settlement")
@login_required
def partner_settlement(partner_id):
    """التسوية الذكية للشريك"""
    partner = _get_partner_or_404(partner_id)
    
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    if date_from:
        date_from = _parse_iso_to_datetime(date_from, end=False)
    else:
        # Auto-detect start date from last settlement to avoid overlap
        last_settlement = db.session.query(PartnerSettlement).filter(
            PartnerSettlement.partner_id == partner_id,
            PartnerSettlement.status == PartnerSettlementStatus.CONFIRMED.value
        ).order_by(PartnerSettlement.to_date.desc()).first()
        
        if last_settlement:
            # Start from the next second/day
            date_from = last_settlement.to_date + timedelta(seconds=1)
        else:
            date_from = datetime(2024, 1, 1)
    
    if date_to:
        date_to = _parse_iso_to_datetime(date_to, end=True)
    else:
        date_to = datetime.now()
    
    balance_data = _calculate_smart_partner_balance(partner_id, date_from, date_to)
    
    from types import SimpleNamespace
    ps = SimpleNamespace(
        id=None,
        partner=partner,
        from_date=date_from,
        to_date=date_to,
        currency=partner.currency,
        total_gross=balance_data.get("incoming", {}).get("total", 0),
        total_due=balance_data.get("balance", {}).get("amount", 0),
        status="DRAFT",
        code=f"PS-SMART-{partner_id}-{date_from.strftime('%Y%m%d')}",
        lines=[],
        created_at=date_from,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    return render_template(
        "vendors/partners/settlement_preview.html",
        partner=partner,
        balance_data=balance_data,
        date_from=date_from,
        date_to=date_to,
        ps=ps  # object بدلاً من dict
    )


def _get_returned_checks_to_partner(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    الشيكات الصادرة المرتدة (دفعنا للشريك) - تُحسب بشكل منفصل
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentMethod, Check, CheckStatus, Sale, Invoice, ServiceRequest, PreOrder
    from sqlalchemy import or_, and_

    session = session or db.session
    
    returned_checks_out = Decimal('0.00')
    items = []
    
    returned_out_direct = session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.partner_id == partner_id,
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
    
    if partner.customer_id:
        returned_out_from_customer = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == partner.customer_id,
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
        
        returned_out_from_sales = session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == partner.customer_id,
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
        
        returned_out_from_invoices = session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == partner.customer_id,
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
        
        returned_out_from_services = session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == partner.customer_id,
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
        
        returned_out_from_preorders = session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == partner.customer_id,
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
    
    manual_returned_checks = session.query(Check).filter(
        Check.partner_id == partner_id,
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


def _get_returned_checks_from_partner(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    الشيكات الواردة المرتدة (دفع الشريك لنا) - تُحسب بشكل منفصل
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentMethod, Check, CheckStatus, Sale, Invoice, ServiceRequest, PreOrder
    from sqlalchemy import or_, and_

    session = session or db.session
    
    returned_checks_in = Decimal('0.00')
    items = []
    
    returned_in_direct = session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.partner_id == partner_id,
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
    
    if partner.customer_id:
        returned_in_from_customer = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == partner.customer_id,
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
        
        returned_in_from_sales = session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == partner.customer_id,
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
        
        returned_in_from_invoices = session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == partner.customer_id,
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
        
        returned_in_from_services = session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == partner.customer_id,
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
        
        returned_in_from_preorders = session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == partner.customer_id,
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
    
    manual_returned_checks = session.query(Check).filter(
        Check.partner_id == partner_id,
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


def _calculate_smart_partner_balance(partner_id: int, date_from: datetime, date_to: datetime):
    """
    حساب التسوية الذكية الشاملة للشريك
    
    المعادلة المحاسبية الصحيحة:
    ═════════════════════════════════════════════════════════════
    حقوق الشريك = المخزون + المبيعات
    التزامات الشريك = مبيعات له + صيانة له + تالف + مصروفات
    الدفعات المسددة = دفعنا له (OUT) + دفع لنا (IN)
    
    الرصيد النهائي = حقوقه - التزاماته - الدفعات المسددة
    ═════════════════════════════════════════════════════════════
    
    ملاحظات مهمة:
    - جميع العملات تُحول إلى ILS قبل الجمع
    - الدفعات الواردة (IN) تُخصم من الرصيد (يُحسب له)
    - الدفعات الصادرة (OUT) تُخصم من الرصيد (يُحسب له)
    """
    try:
        partner = db.session.get(Partner, partner_id)
        if not partner:
            return {"success": False, "error": "الشريك غير موجود"}
        
        opening_balance = Decimal(str(getattr(partner, 'opening_balance', 0) or 0))
        partner_currency = getattr(partner, 'currency', 'ILS') or 'ILS'
        
        if partner_currency != 'ILS' and opening_balance != 0:
            try:
                opening_balance = convert_amount(opening_balance, partner_currency, 'ILS', date_from)
            except Exception:
                current_app.logger.debug('Currency conversion skipped')
        
        inventory = _get_partner_inventory(partner_id, date_from, date_to)
        sales_share = _get_partner_sales_share(partner_id, date_from, date_to)
        sales_returns = _get_partner_sales_returns(partner_id, date_from, date_to)
        payments_from_partner = _get_partner_payments_received(partner_id, partner, date_from, date_to)
        preorders_prepaid = _get_partner_preorders_prepaid(partner_id, partner, date_from, date_to)
        shipments_share = _get_partner_shipments_share(partner_id, date_from, date_to)
        returned_checks_in = _get_returned_checks_from_partner(partner_id, partner, date_from, date_to)
        returned_checks_out = _get_returned_checks_to_partner(partner_id, partner, date_from, date_to)
        payments_to_partner = _get_payments_to_partner(partner_id, partner, date_from, date_to)
        sales_to_partner = _get_partner_sales_as_customer(partner_id, partner, date_from, date_to)
        service_fees = _get_partner_service_fees(partner_id, partner, date_from, date_to)
        preorders_to_partner = _get_partner_preorders_as_customer(partner_id, partner, date_from, date_to)
        damaged_items = _get_partner_damaged_items(partner_id, date_from, date_to)
        expenses_deducted = _get_partner_expenses(partner_id, date_from, date_to)
        expenses_to_partner = Expense.query.join(ExpenseType).filter(
            or_(
                Expense.partner_id == partner_id,
                and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
            ),
            Expense.date >= date_from,
            Expense.date <= date_to,
            func.upper(ExpenseType.code) == "PARTNER_EXPENSE"
        ).all()
        
        partner_service_total = Decimal('0.00')
        expenses_items = []
        for exp in expenses_to_partner:
            amt = Decimal(str(exp.amount or 0))
            amt_ils = amt
            if exp.currency == "ILS":
                partner_service_total += amt
            else:
                try:
                    from models import convert_amount
                    amt_ils = convert_amount(amt, exp.currency, "ILS", exp.date)
                    partner_service_total += amt_ils
                except Exception:
                    current_app.logger.debug('Currency conversion skipped')
            
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
        
        partner_rights = Decimal(str(inventory.get("total_ils", 0) if isinstance(inventory, dict) else 0)) + \
                        Decimal(str(sales_share.get("total_share_ils", 0))) - \
                        Decimal(str(sales_returns.get("total_return_share_ils", 0) if isinstance(sales_returns, dict) else 0)) + \
                        Decimal(str(shipments_share.get("total_ils", 0) if isinstance(shipments_share, dict) else 0))
        partner_obligations = Decimal(str(sales_to_partner.get("total_ils", 0))) + \
                             Decimal(str(service_fees.get("total_ils", 0))) + \
                             Decimal(str(preorders_to_partner.get("total_ils", 0) if isinstance(preorders_to_partner, dict) else 0)) + \
                             Decimal(str(damaged_items.get("total_ils", 0)))
        net_before_payments = partner_rights - partner_obligations
        paid_to_partner = Decimal(str(payments_to_partner.get("total_ils", 0)))
        received_from_partner = Decimal(str(payments_from_partner.get("total_ils", 0))) + \
                               Decimal(str(preorders_prepaid.get("total_ils", 0)))
        returned_checks_in_total = Decimal(str(returned_checks_in.get("total_ils", 0)))
        returned_checks_out_total = Decimal(str(returned_checks_out.get("total_ils", 0)))
        balance = opening_balance + net_before_payments - paid_to_partner + received_from_partner - Decimal(str(expenses_deducted or 0)) + partner_service_total - returned_checks_in_total + returned_checks_out_total
        
        opening_view = utils.classify_entity_balance(opening_balance)
        balance_view = utils.classify_entity_balance(balance)

        return {
            "success": True,
            "partner": {
                "id": partner.id,
                "name": partner.name,
                "currency": partner.currency,
                "share_percentage": float(partner.share_percentage or 0)
            },
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat()
            },
            "opening_balance": {
                "amount": float(opening_balance),
                "currency": "ILS",
                "direction": "له علينا" if opening_view["balance"] > 0 else "عليه لنا" if opening_view["balance"] < 0 else "متوازن"
            },
            "rights": {
                "inventory": inventory,
                "sales_share": sales_share,
                "sales_returns": sales_returns,
                "preorders_share": preorders_prepaid,
                "shipments_share": shipments_share,
                "total": float(partner_rights)
            },
            "obligations": {
                "sales_to_partner": sales_to_partner,
                "service_fees": service_fees,
                "preorders_to_partner": preorders_to_partner,
                "damaged_items": damaged_items,
                "total": float(partner_obligations)
            },
            "payments": {
                "paid_to_partner": payments_to_partner,
                "received_from_partner": payments_from_partner,
                "preorders_prepaid": preorders_prepaid,
                "shipments_share": shipments_share,
                "returned_checks_in": returned_checks_in,
                "returned_checks_out": returned_checks_out,
                "total_paid": float(paid_to_partner),
                "total_received": float(received_from_partner),
                "total_returned_checks_in": float(returned_checks_in_total),
                "total_returned_checks_out": float(returned_checks_out_total),
                "total_settled": float(paid_to_partner + received_from_partner)
            },
            "expenses": {
                "items": expenses_items,
                "total_ils": float(partner_service_total),
                "deducted_ils": float(expenses_deducted or 0),
                "count": len(expenses_to_partner)
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
                "formula": f"({float(opening_balance):.2f} + {float(partner_rights):.2f} - {float(partner_obligations):.2f} - {float(paid_to_partner):.2f} + {float(received_from_partner):.2f} - {float(expenses_deducted or 0):.2f} + {float(partner_service_total):.2f} - {float(returned_checks_in_total):.2f} + {float(returned_checks_out_total):.2f}) = {float(balance):.2f}"
            },
            "previous_settlements": _get_previous_partner_settlements(partner_id, date_from),
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
        return {"success": False, "error": "خطأ في حساب رصيد الشريك"}


def _calculate_partner_incoming(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الوارد من الشريك"""
    from models import ServicePart, ServiceRequest, ExchangeTransaction
    from sqlalchemy import func
    
    sales_share = db.session.query(func.sum(ServicePart.quantity * ServicePart.unit_price)).join(
        ServiceRequest, ServiceRequest.id == ServicePart.service_id
    ).filter(
        ServicePart.partner_id == partner_id,
        ServiceRequest.received_at >= date_from,
        ServiceRequest.received_at <= date_to
    ).scalar() or 0
    
    products_given = db.session.query(func.sum(ExchangeTransaction.quantity * ExchangeTransaction.unit_cost)).filter(
        ExchangeTransaction.partner_id == partner_id,
        ExchangeTransaction.direction == "OUT",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).scalar() or 0
    
    shipments_share_data = _get_partner_shipments_share(partner_id, date_from, date_to)
    shipments_share = shipments_share_data.get("total_ils", 0)
    
    return {
        "sales_share": float(sales_share),
        "products_given": float(products_given),
        "shipments_share": float(shipments_share),
        "total": float(sales_share + products_given + shipments_share)
    }


def _calculate_partner_outgoing(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الصادر للشريك"""
    from models import Expense, ExchangeTransaction
    from sqlalchemy import func, or_, and_
    
    purchases_share = db.session.query(func.sum(Expense.amount)).filter(
        or_(
        Expense.partner_id == partner_id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).scalar() or 0
    
    products_taken = db.session.query(func.sum(ExchangeTransaction.quantity * ExchangeTransaction.unit_cost)).filter(
        ExchangeTransaction.partner_id == partner_id,
        ExchangeTransaction.direction == "IN",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).scalar() or 0
    
    return {
        "purchases_share": float(purchases_share),
        "products_taken": float(products_taken),
        "total": float(purchases_share + products_taken)
    }


def _calculate_payments_to_partner(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الدفعات المدفوعة للشريك"""
    from models import Payment
    from sqlalchemy import func
    
    amount = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.partner_id == partner_id,
        Payment.direction == "OUTGOING",
        Payment.status == "COMPLETED",
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).scalar() or 0
    return float(amount)


def _calculate_payments_from_partner(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الدفعات المستلمة من الشريك"""
    from models import Payment
    from sqlalchemy import func
    
    amount = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.partner_id == partner_id,
        Payment.direction == "INCOMING",
        Payment.status == "COMPLETED",
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).scalar() or 0
    return float(amount)


def _check_unpriced_items_for_partner(partner_id: int, date_from: datetime, date_to: datetime):
    """التحقق من القطع غير المسعرة للشريك"""
    from models import ExchangeTransaction, Product
    from sqlalchemy import func, or_
    
    unpriced_transactions = db.session.query(ExchangeTransaction).join(Product).filter(
        ExchangeTransaction.partner_id == partner_id,
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


def _get_last_partner_settlement(partner_id: int):
    """الحصول على آخر تسوية للشريك"""
    from models import PartnerSettlement
    from sqlalchemy import desc
    
    last_settlement = db.session.query(PartnerSettlement).filter(
        PartnerSettlement.partner_id == partner_id
    ).order_by(desc(PartnerSettlement.created_at)).first()
    
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


def _get_partner_operations_details(partner_id: int, date_from: datetime, date_to: datetime):
    """الحصول على تفاصيل العمليات للشريك"""
    from models import ExchangeTransaction, ServicePart, ServiceRequest, Payment, Expense
    from sqlalchemy import func, desc
    
    recent_transactions = db.session.query(ExchangeTransaction).filter(
        ExchangeTransaction.partner_id == partner_id,
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).order_by(desc(ExchangeTransaction.created_at)).limit(10).all()
    
    recent_payments = db.session.query(Payment).filter(
        Payment.partner_id == partner_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).order_by(desc(Payment.payment_date)).limit(10).all()
    
    recent_expenses = db.session.query(Expense).filter(
        or_(
        Expense.partner_id == partner_id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).order_by(desc(Expense.date)).limit(10).all()
    
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
            "message": f"يجب دفع {balance_view['owed_by_us']:.2f} {currency} للشريك",
            "amount": balance_view["owed_by_us"],
            "direction": "OUT",
            "warnings": []
        }
    else:  # الباقي عليه
        return {
            "action": "قبض",
            "message": f"يجب قبض {balance_view['owed_to_us']:.2f} {currency} من الشريك",
            "amount": balance_view["owed_to_us"],
            "direction": "IN",
            "warnings": []
        }



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


def _get_payment_total_ils(payment) -> Decimal:
    """
    حساب إجمالي الدفعة بالشيكل مع مراعاة Splits و converted_amount
    """
    from models import PaymentSplit
    splits = db.session.query(PaymentSplit).filter(PaymentSplit.payment_id == payment.id).all()
    
    if splits:
        payment_total_ils = Decimal('0.00')
        for split in splits:
            split_amt = Decimal(str(split.amount or 0))
            split_converted_amt = Decimal(str(getattr(split, 'converted_amount', 0) or 0))
            split_converted_currency = (getattr(split, 'converted_currency', None) or split.currency or 'ILS').upper()
            split_currency = split.currency or payment.currency or 'ILS'
            
            if split_converted_amt > 0 and split_converted_currency == 'ILS':
                payment_total_ils += split_converted_amt
            elif split_currency == 'ILS':
                payment_total_ils += split_amt
            else:
                try:
                    payment_total_ils += _convert_to_ils(split_amt, split_currency, payment.payment_date)
                except Exception:
                    current_app.logger.warning('currency conversion failed silently in partner_settlements.py', exc_info=True)
        return payment_total_ils
    else:
        return _convert_to_ils(Decimal(str(payment.total_amount or 0)), payment.currency, payment.payment_date)


def _convert_to_ils(amount: Decimal | float, from_currency: str, at: datetime = None) -> Decimal:
    """
    تحويل أي مبلغ إلى الشيكل (ILS)
    الأولوية: 1- السعر اليدوي المحلي 2- سعر السيرفر 3- خطأ (إدخال يدوي مطلوب)
    """
    if not amount or amount == 0:
        return Decimal('0.00')
    
    from_currency = (from_currency or "ILS").strip().upper()
    
    if from_currency == "ILS":
        return _d2(amount)
    
    from models import convert_amount
    t = at or datetime.now(timezone.utc).replace(tzinfo=None)
    return _d2(convert_amount(amount, from_currency, "ILS", t))


def _get_partner_inventory(partner_id: int, date_from: datetime, date_to: datetime, session=None):
    """
    المخزون الحالي للشريك (نصيبه من التكلفة)
    يحسب من المستودعات التي لها صفة شراكة وله نسبة فيها
    """
    from models import (
        Warehouse, WarehousePartnerShare, StockLevel, Product, ProductPartner
    )
    from sqlalchemy import func
    from types import SimpleNamespace
    from extensions import db as _db

    session = session or _db.session
    db = SimpleNamespace(session=session)
    
    partner_warehouse_shares = db.session.query(
        WarehousePartnerShare.warehouse_id,
        WarehousePartnerShare.product_id,
        WarehousePartnerShare.share_percentage,
        Warehouse.name.label('warehouse_name')
    ).outerjoin(
        Warehouse, Warehouse.id == WarehousePartnerShare.warehouse_id
    ).filter(
        WarehousePartnerShare.partner_id == partner_id,
        WarehousePartnerShare.share_percentage > 0
    ).all()
    
    if not partner_warehouse_shares:
        product_shares = db.session.query(
            ProductPartner.product_id,
            ProductPartner.share_percent
        ).filter(
            ProductPartner.partner_id == partner_id,
            ProductPartner.share_percent > 0
        ).all()
        
        if not product_shares:
            return {"items": [], "total": 0.0}
        
        product_ids = [ps[0] for ps in product_shares]
        share_map = {ps[0]: float(ps[1]) for ps in product_shares}
        
        inventory_items = db.session.query(
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.sku,
            Warehouse.name.label("warehouse_name"),
            StockLevel.quantity,
            Product.purchase_price,
            Product.currency
    ).join(
            StockLevel, StockLevel.product_id == Product.id
        ).join(
            Warehouse, Warehouse.id == StockLevel.warehouse_id
    ).filter(
            Product.id.in_(product_ids),
        StockLevel.quantity > 0
    ).all()
    else:
        inventory_items = []
        for wh_share in partner_warehouse_shares:
            wh_id, prod_id, share_pct, wh_name = wh_share
            
            if wh_id is None:
                partner_warehouses = db.session.query(Warehouse.id, Warehouse.name).filter(
                    Warehouse.warehouse_type == 'PARTNER'
                ).all()
                
                if prod_id:
                    for wh in partner_warehouses:
                        stock = db.session.query(
                            Product.id.label("product_id"),
                            Product.name.label("product_name"),
                            Product.sku,
                            StockLevel.quantity,
                            Product.purchase_price,
                            Product.currency
                        ).join(
                            Product, Product.id == StockLevel.product_id
                        ).filter(
                            StockLevel.warehouse_id == wh.id,
                            StockLevel.product_id == prod_id,
                            StockLevel.quantity > 0
                        ).first()
                        
                        if stock:
                            inventory_items.append({
                                'product_id': stock.product_id,
                                'product_name': stock.product_name,
                                'sku': stock.sku,
                                'warehouse_name': wh.name,
                                'quantity': stock.quantity,
                                'purchase_price': stock.purchase_price,
                                'currency': stock.currency,
                                'share_pct': share_pct
                            })
                else:
                    for wh in partner_warehouses:
                        stocks = db.session.query(
                            Product.id.label("product_id"),
                            Product.name.label("product_name"),
                            Product.sku,
                            StockLevel.quantity,
                            Product.purchase_price,
                            Product.currency
                        ).join(
                            Product, Product.id == StockLevel.product_id
                        ).filter(
                            StockLevel.warehouse_id == wh.id,
                            StockLevel.quantity > 0
                        ).all()
                        
                        for stock in stocks:
                            inventory_items.append({
                                'product_id': stock.product_id,
                                'product_name': stock.product_name,
                                'sku': stock.sku,
                                'warehouse_name': wh.name,
                                'quantity': stock.quantity,
                                'purchase_price': stock.purchase_price,
                                'currency': stock.currency,
                                'share_pct': share_pct
                            })
            elif prod_id:
                stock = db.session.query(
                    Product.id.label("product_id"),
                    Product.name.label("product_name"),
                    Product.sku,
                    StockLevel.quantity,
                    Product.purchase_price
                ).join(
                    Product, Product.id == StockLevel.product_id
                ).filter(
                    StockLevel.warehouse_id == wh_id,
                    StockLevel.product_id == prod_id,
                    StockLevel.quantity > 0
                ).first()
                
                if stock:
                    inventory_items.append({
                        'product_id': stock.product_id,
                        'product_name': stock.product_name,
                        'sku': stock.sku,
                        'warehouse_name': wh_name or 'غير محدد',
                        'quantity': stock.quantity,
                        'purchase_price': stock.purchase_price,
                        'share_pct': share_pct
                    })
            else:
                stocks = db.session.query(
                    Product.id.label("product_id"),
                    Product.name.label("product_name"),
                    Product.sku,
                    StockLevel.quantity,
                    Product.purchase_price
                ).join(
                    Product, Product.id == StockLevel.product_id
                ).filter(
                    StockLevel.warehouse_id == wh_id,
                    StockLevel.quantity > 0
                ).all()
    
                for stock in stocks:
                    inventory_items.append({
                        'product_id': stock.product_id,
                        'product_name': stock.product_name,
                        'sku': stock.sku,
                        'warehouse_name': wh_name or 'غير محدد',
                        'quantity': stock.quantity,
                        'purchase_price': stock.purchase_price,
                        'share_pct': share_pct
                    })
    
    items = []
    total = Decimal("0")
    
    for inv_item in inventory_items:
        if isinstance(inv_item, dict):
            prod_id = inv_item['product_id']
            prod_name = inv_item['product_name']
            sku = inv_item['sku']
            wh_name = inv_item['warehouse_name']
            qty = inv_item['quantity']
            cost = inv_item['purchase_price']
            share_pct = inv_item['share_pct']
            product_currency = inv_item.get('currency', 'ILS')
        else:
            prod_id = inv_item.product_id
            prod_name = inv_item.product_name
            sku = inv_item.sku
            wh_name = getattr(inv_item, 'warehouse_name', '-')
            qty = inv_item.quantity
            cost = inv_item.purchase_price
            share_pct = share_map.get(prod_id, 0) if 'share_map' in locals() else 0
            product_currency = getattr(inv_item, 'currency', 'ILS')
        
        partner_share = Decimal(str(qty)) * Decimal(str(cost or 0)) * Decimal(str(share_pct)) / Decimal("100")
        
        if product_currency and product_currency != 'ILS':
            try:
                partner_share = _convert_to_ils(partner_share, product_currency, datetime.now(timezone.utc).replace(tzinfo=None))
            except Exception:
                pass  # إذا فشل التحويل، نستخدم القيمة الأصلية
        
        total += partner_share
        
        items.append({
            "product_id": prod_id,
            "product_name": prod_name,
            "sku": sku,
            "warehouse": wh_name,
            "quantity": int(qty),
            "cost_per_unit": float(cost or 0),
            "share_percentage": float(share_pct),
            "partner_share": float(partner_share)
        })
    
    return {
        "items": items,
        "total": float(total),
        "total_ils": float(total),  # ✅ المخزون مُفترض بالشيكل
        "count": len(items)
    }


def _get_partner_sales_share(partner_id: int, date_from: datetime, date_to: datetime, session=None):
    """
    حساب نصيب الشريك من المبيعات (من سعر البيع)
    يشمل: مبيعات الصيانة + مبيعات عادية
    ملاحظة: يجب خصم نصيب الشريك من مرتجعات المبيعات من sales_share_balance
    """
    from models import (
        ServicePart, ServiceRequest, SaleLine, Sale, Product,
        ProductPartner, WarehousePartnerShare, Customer
    )
    from sqlalchemy import func
    from types import SimpleNamespace
    from extensions import db as _db

    session = session or _db.session
    db = SimpleNamespace(session=session)
    
    all_sales = []
    total_ils = Decimal('0.00')
    total_discount_ils = Decimal('0.00')
    
    service_sales = db.session.query(
        ServiceRequest.id.label("service_id"),
        ServiceRequest.service_number,
        ServiceRequest.received_at.label("date"),
        ServiceRequest.currency,
        ServiceRequest.discount_total.label("service_discount_total"),
        ServiceRequest.parts_total.label("service_parts_total"),
        ServiceRequest.labor_total.label("service_labor_total"),
        Customer.name.label("customer_name"),
        Product.name.label("product_name"),
        Product.sku,
        ServicePart.quantity,
        ServicePart.unit_price,
        ServicePart.discount,
        ServicePart.share_percentage
    ).join(
        ServicePart, ServicePart.service_id == ServiceRequest.id
    ).join(
        Product, Product.id == ServicePart.part_id
    ).join(
        Customer, Customer.id == ServiceRequest.customer_id
    ).filter(
        ServicePart.partner_id == partner_id,
        ServiceRequest.received_at >= date_from,
        ServiceRequest.received_at <= date_to,
        ServiceRequest.status == ServiceStatus.COMPLETED.value
    ).all()
    
    service_discount_info = {}
    for item in service_sales:
        sr_id = item.service_id
        if sr_id not in service_discount_info:
            parts_total = Decimal(str(item.service_parts_total or 0))
            labor_total = Decimal(str(item.service_labor_total or 0))
            discount_total = Decimal(str(item.service_discount_total or 0))
            total_before_discount = parts_total + labor_total
            parts_discount_share = Decimal("0")
            if total_before_discount > 0 and discount_total > 0:
                parts_discount_share = (parts_total / total_before_discount) * discount_total
            service_discount_info[sr_id] = {
                "parts_total": parts_total,
                "parts_discount": parts_discount_share
            }
        parts_total = service_discount_info[sr_id]["parts_total"]
        parts_discount_share = service_discount_info[sr_id]["parts_discount"]
        gross_amount = Decimal(str(item.quantity)) * Decimal(str(item.unit_price))
        line_discount = Decimal(str(item.discount or 0))
        net_amount = gross_amount - line_discount
        if net_amount < 0:
            net_amount = Decimal("0")
        allocated_service_discount = Decimal("0")
        if parts_total > 0 and parts_discount_share > 0:
            allocated_service_discount = (net_amount / parts_total) * parts_discount_share
        net_after_discount = net_amount - allocated_service_discount
        if net_after_discount < 0:
            net_after_discount = Decimal("0")
        share_pct = Decimal(str(item.share_percentage or 0))
        partner_share = net_after_discount * share_pct / Decimal("100")
        try:
            partner_share_ils = _convert_to_ils(partner_share, item.currency, item.date)
        except Exception:
            partner_share_ils = partner_share
        total_discount = line_discount + allocated_service_discount
        if total_discount < 0:
            total_discount = Decimal("0")
        try:
            discount_amount_ils = _convert_to_ils(total_discount, item.currency, item.date)
        except Exception:
            discount_amount_ils = total_discount
        total_ils += partner_share_ils
        total_discount_ils += discount_amount_ils
        all_sales.append({
            "type": "صيانة",
            "reference_number": item.service_number,
            "date": item.date.strftime("%Y-%m-%d") if item.date else "",
            "customer_name": item.customer_name,
            "product_name": item.product_name,
            "sku": item.sku,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "total_amount": float(net_after_discount),
            "share_percentage": float(share_pct),
            "partner_share": float(partner_share),
            "discount_amount": float(total_discount),
            "discount_amount_ils": float(discount_amount_ils),
            "currency": item.currency,
            "partner_share_ils": float(partner_share_ils)
        })
    
    regular_sales_pp = db.session.query(
        Sale.id.label("sale_id"),
        Sale.sale_number,
        Sale.sale_date,
        Sale.discount_total.label("sale_discount_total"),
        Customer.name.label("customer_name"),
        Product.name.label("product_name"),
        Product.sku,
        SaleLine.quantity,
        SaleLine.unit_price,
        SaleLine.discount_rate,
        ProductPartner.share_percent.label("share_pct"),
        Sale.currency
    ).join(
        SaleLine, SaleLine.sale_id == Sale.id
    ).join(
        Product, Product.id == SaleLine.product_id
    ).join(
        ProductPartner, ProductPartner.product_id == Product.id
    ).join(
        Customer, Customer.id == Sale.customer_id
    ).filter(
        ProductPartner.partner_id == partner_id,
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to,
        Sale.status == SaleStatus.CONFIRMED,
        ProductPartner.share_percent > 0
    ).all()
    
    regular_sales_wps = db.session.query(
        Sale.id.label("sale_id"),
        Sale.sale_number,
        Sale.sale_date,
        Sale.discount_total.label("sale_discount_total"),
        Customer.name.label("customer_name"),
        Product.name.label("product_name"),
        Product.sku,
        SaleLine.quantity,
        SaleLine.unit_price,
        SaleLine.discount_rate,
        WarehousePartnerShare.share_percentage.label("share_pct"),
        Sale.currency
    ).join(
        SaleLine, SaleLine.sale_id == Sale.id
    ).join(
        Product, Product.id == SaleLine.product_id
    ).join(
        WarehousePartnerShare, WarehousePartnerShare.product_id == Product.id
    ).join(
        Customer, Customer.id == Sale.customer_id
    ).filter(
        WarehousePartnerShare.partner_id == partner_id,
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to,
        Sale.status == SaleStatus.CONFIRMED,
        WarehousePartnerShare.share_percentage > 0
    ).all()
    
    all_regular_sales = list(regular_sales_pp) + list(regular_sales_wps)
    sale_ids = {item.sale_id for item in all_regular_sales}
    sale_net_totals = {}
    if sale_ids:
        net_rows = db.session.query(
            SaleLine.sale_id,
            func.coalesce(
                func.sum(
                    (SaleLine.quantity * SaleLine.unit_price)
                    * (1 - (func.coalesce(SaleLine.discount_rate, 0) / 100.0))
                ),
                0.0,
            ),
        ).filter(
            SaleLine.sale_id.in_(sale_ids)
        ).group_by(
            SaleLine.sale_id
        ).all()
        for sale_id, net_value in net_rows:
            sale_net_totals[sale_id] = Decimal(str(net_value or 0))
    
    added_sales = set()
    
    for item in all_regular_sales:
        sale_line_key = (item.sale_id, item.product_name, item.quantity)
        if sale_line_key in added_sales:
            continue
        added_sales.add(sale_line_key)
        
        line_gross = Decimal(str(item.quantity)) * Decimal(str(item.unit_price))
        line_discount_rate = Decimal(str(item.discount_rate or 0))
        net_amount = line_gross * (Decimal("1") - (line_discount_rate / Decimal("100")))
        if net_amount < 0:
            net_amount = Decimal("0")
        sale_discount_total = Decimal(str(item.sale_discount_total or 0))
        total_sale_net = sale_net_totals.get(item.sale_id, Decimal("0"))
        allocated_sale_discount = Decimal("0")
        if total_sale_net > 0 and sale_discount_total > 0:
            allocated_sale_discount = (net_amount / total_sale_net) * sale_discount_total
        net_after_discount = net_amount - allocated_sale_discount
        if net_after_discount < 0:
            net_after_discount = Decimal("0")
        share_pct = Decimal(str(item.share_pct or 0))
        partner_share = net_after_discount * share_pct / Decimal("100")
        try:
            partner_share_ils = _convert_to_ils(partner_share, item.currency, item.sale_date)
        except Exception:
            partner_share_ils = partner_share
        line_discount_value = line_gross - net_amount
        if line_discount_value < 0:
            line_discount_value = Decimal("0")
        total_discount = line_discount_value + allocated_sale_discount
        if total_discount < 0:
            total_discount = Decimal("0")
        try:
            discount_amount_ils = _convert_to_ils(total_discount, item.currency, item.sale_date)
        except Exception:
            discount_amount_ils = total_discount
        total_ils += partner_share_ils
        total_discount_ils += discount_amount_ils
        all_sales.append({
            "type": "بيع عادي",
            "reference_number": item.sale_number,
            "date": item.sale_date.strftime("%Y-%m-%d") if item.sale_date else "",
            "customer_name": item.customer_name,
            "product_name": item.product_name,
            "sku": item.sku,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "total_amount": float(net_after_discount),
            "share_percentage": float(share_pct),
            "partner_share": float(partner_share),
            "discount_amount": float(total_discount),
            "discount_amount_ils": float(discount_amount_ils),
            "currency": item.currency,
            "partner_share_ils": float(partner_share_ils)
        })
    
    return {
        "items": all_sales,
        "count": len(all_sales),
        "total_share": float(total_ils),
        "total_share_ils": float(total_ils),
        "total_discount_ils": float(total_discount_ils)
    }


def _get_partner_sales_returns(partner_id: int, date_from: datetime, date_to: datetime, session=None):
    """
    حساب نصيب الشريك من مرتجعات المبيعات (يُخصم من sales_share_balance)
    للقطع السليمة فقط - القطع التالفة تُحسب في damaged_items_balance
    """
    from models import (
        SaleReturn, SaleReturnLine, SaleLine, Sale, Product,
        ProductPartner, WarehousePartnerShare, SaleStatus
    )
    from sqlalchemy import func
    from types import SimpleNamespace
    from extensions import db as _db

    session = session or _db.session
    db = SimpleNamespace(session=session)
    
    all_returns = []
    total_return_share_ils = Decimal('0.00')
    
    sale_returns = db.session.query(SaleReturn).filter(
        SaleReturn.status == 'CONFIRMED',
        SaleReturn.return_date >= date_from,
        SaleReturn.return_date <= date_to
    ).all()
    
    for sale_return in sale_returns:
        if not sale_return.sale_id:
            continue
        
        sale = db.session.get(Sale, sale_return.sale_id)
        if not sale or sale.status != SaleStatus.CONFIRMED:
            continue
        
        for return_line in (sale_return.lines or []):
            if return_line.condition != 'GOOD':
                continue
            
            product_id = return_line.product_id
            warehouse_id = return_line.warehouse_id
            
            share_pct = Decimal('0.00')
            
            product_partner = db.session.query(ProductPartner).filter(
                ProductPartner.partner_id == partner_id,
                ProductPartner.product_id == product_id
            ).first()
            
            if product_partner and product_partner.share_percent:
                share_pct = Decimal(str(product_partner.share_percent))
            else:
                warehouse_partner_share = db.session.query(WarehousePartnerShare).filter(
                    WarehousePartnerShare.partner_id == partner_id,
                    WarehousePartnerShare.product_id == product_id
                ).first()
                
                if warehouse_partner_share and warehouse_partner_share.share_percentage:
                    share_pct = Decimal(str(warehouse_partner_share.share_percentage))
                elif warehouse_id:
                    warehouse_partner_share_general = db.session.query(WarehousePartnerShare).filter(
                        WarehousePartnerShare.partner_id == partner_id,
                        WarehousePartnerShare.warehouse_id == warehouse_id,
                        WarehousePartnerShare.product_id.is_(None)
                    ).first()
                    
                    if warehouse_partner_share_general and warehouse_partner_share_general.share_percentage:
                        share_pct = Decimal(str(warehouse_partner_share_general.share_percentage))
            
            if share_pct <= 0:
                continue
            
            return_amount = Decimal(str(return_line.quantity or 0)) * Decimal(str(return_line.unit_price or 0))
            partner_return_share = return_amount * share_pct / Decimal("100")
            
            try:
                partner_return_share_ils = _convert_to_ils(
                    partner_return_share,
                    sale_return.currency or 'ILS',
                    sale_return.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
                )
            except Exception:
                partner_return_share_ils = partner_return_share
            
            total_return_share_ils += partner_return_share_ils
            
            product = db.session.get(Product, product_id) if product_id else None
            
            all_returns.append({
                "type": "مرتجع مبيعات",
                "reference_number": sale_return.id,
                "sale_id": sale_return.sale_id,
                "date": sale_return.created_at.strftime("%Y-%m-%d") if sale_return.created_at else "",
                "product_name": product.name if product else f"منتج #{product_id}",
                "sku": product.sku if product else None,
                "quantity": return_line.quantity,
                "unit_price": float(return_line.unit_price or 0),
                "return_amount": float(return_amount),
                "share_percentage": float(share_pct),
                "partner_return_share": float(partner_return_share),
                "partner_return_share_ils": float(partner_return_share_ils),
                "currency": sale_return.currency or 'ILS',
                "condition": return_line.condition
            })
    
    return {
        "items": all_returns,
        "count": len(all_returns),
        "total_return_share": float(total_return_share_ils),
        "total_return_share_ils": float(total_return_share_ils)
    }


def _get_payments_to_partner(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    دفعات دفعناها للشريك (OUT) - تُخصم من حقوقه علينا
    ✅ لا تستثني الشيكات المرتدة (تبقى في payments_out_balance، والشيكات المرتجة تُحسب كقيد منفصل)
    
    تشمل:
    1. الدفعات المرتبطة مباشرة بـ partner_id
    2. الدفعات المرتبطة بـ customer_id (العميل المرتبط بالشريك)
    3. الدفعات المرتبطة بمبيعات للعميل (entity_type = SALE)
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentEntityType, Sale, Check
    from sqlalchemy import or_

    session = session or db.session
    
    items = []
    total_ils = Decimal('0.00')
    
    direct_payments = session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).filter(
        Payment.partner_id == partner_id,
        Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    for payment in direct_payments:
        amount_ils = _get_payment_total_ils(payment)
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
            "source": "partner"
        })
    
    seen_payment_ids = {it.get("payment_id") for it in items if it.get("payment_id")}
    if partner.customer_id:
        customer_payments = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in customer_payments:
            amount_ils = _get_payment_total_ils(payment)
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
        
        sale_payments = session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Sale.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in sale_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
    
    from models import Expense
    expense_payments = session.query(Payment).join(
        Expense, Expense.id == Payment.expense_id
    ).filter(
        or_(
            Expense.partner_id == partner_id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
        ),
        Payment.direction == PaymentDirection.OUT,
        Payment.status == PaymentStatus.COMPLETED,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    ).all()
    
    for payment in expense_payments:
        if payment.id not in seen_payment_ids:
            amount_ils = _get_payment_total_ils(payment)
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
            seen_payment_ids.add(payment.id)
    
    if partner.customer_id:
        from models import Invoice
        invoice_payments = session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in invoice_payments:
            if payment.id not in seen_payment_ids:
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
                seen_payment_ids.add(payment.id)
        
        from models import ServiceRequest
        service_payments = session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in service_payments:
            if payment.id not in seen_payment_ids:
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
                seen_payment_ids.add(payment.id)
        
        from models import PreOrder
        preorder_payments = session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.OUT,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in preorder_payments:
            if payment.id not in seen_payment_ids:
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
                seen_payment_ids.add(payment.id)
    
    from models import Check, CheckStatus
    manual_checks = session.query(Check).filter(
        Check.partner_id == partner_id,
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
    
    items.sort(key=lambda x: x['date'])
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_partner_shipments_share(partner_id: int, date_from: datetime, date_to: datetime):
    """
    حساب نصيب الشريك من الشحنات
    """
    from models import Shipment, ShipmentPartner, ShipmentItem, Product
    
    items = []
    total_ils = Decimal('0.00')
    
    shipments = db.session.query(
        Shipment.id,
        Shipment.shipment_number,
        Shipment.created_at,
        Shipment.delivered_date,
        Shipment.total_cost,
        Shipment.currency,
        ShipmentPartner.share_percentage,
        ShipmentPartner.share_amount
    ).join(
        ShipmentPartner, ShipmentPartner.shipment_id == Shipment.id
    ).filter(
        ShipmentPartner.partner_id == partner_id,
        Shipment.status.in_(['IN_TRANSIT', 'IN_CUSTOMS', 'ARRIVED', 'DELIVERED']),
        Shipment.created_at >= date_from,
        Shipment.created_at <= date_to
    ).all()
    
    for shipment in shipments:
        sh_id, sh_number, created_at, delivered_date, total_cost, currency, share_pct, share_amount = shipment
        
        amount_ils = _convert_to_ils(
            Decimal(str(share_amount or 0)), 
            currency or 'ILS', 
            created_at or datetime.now(timezone.utc).replace(tzinfo=None)
        )
        total_ils += amount_ils
        
        shipment_items = db.session.query(
            ShipmentItem.product_id,
            Product.name.label('product_name'),
            Product.sku,
            ShipmentItem.quantity,
            ShipmentItem.landed_unit_cost
        ).join(
            Product, Product.id == ShipmentItem.product_id
        ).filter(
            ShipmentItem.shipment_id == sh_id
        ).all()
        
        items_details = []
        for item in shipment_items:
            items_details.append({
                "product_name": item.product_name,
                "sku": item.sku or "",
                "quantity": float(item.quantity or 0),
                "unit_cost": float(item.landed_unit_cost or 0),
                "total": float(Decimal(str(item.quantity or 0)) * Decimal(str(item.landed_unit_cost or 0)))
            })
        
        items.append({
            "shipment_id": sh_id,
            "shipment_number": sh_number or f"SHIP-{sh_id}",
            "date": created_at.strftime("%Y-%m-%d") if created_at else "",
            "delivered_date": delivered_date.strftime("%Y-%m-%d") if delivered_date else "",
            "total_cost": float(total_cost or 0),
            "share_percentage": float(share_pct or 0),
            "share_amount": float(share_amount or 0),
            "share_amount_ils": float(amount_ils),
            "currency": currency or 'ILS',
            "items": items_details
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_partner_preorders_share(partner_id: int, date_from: datetime, date_to: datetime):
    """
    حساب نصيب الشريك من الحجوزات المسبقة
    """
    from models import PreOrder
    
    items = []
    total_ils = Decimal('0.00')
    
    preorders = db.session.query(PreOrder).filter(
        PreOrder.partner_id == partner_id,
        PreOrder.status.in_(['CONFIRMED', 'COMPLETED', 'DELIVERED']),
        PreOrder.created_at >= date_from,
        PreOrder.created_at <= date_to
    ).all()
    
    for po in preorders:
        partner_share_pct = float(po.partner_share_percentage or 0)
        preorder_total = Decimal(str(po.total_amount or 0))
        share_amount = preorder_total * Decimal(str(partner_share_pct / 100.0))
        
        amount_ils = _convert_to_ils(
            share_amount,
            po.currency or 'ILS',
            po.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
        )
        total_ils += amount_ils
        
        items.append({
            "preorder_id": po.id,
            "preorder_number": po.preorder_number or f"PO-{po.id}",
            "date": po.created_at.strftime("%Y-%m-%d") if po.created_at else "",
            "total_amount": float(preorder_total),
            "share_percentage": partner_share_pct,
            "share_amount": float(share_amount),
            "share_amount_ils": float(amount_ils),
            "currency": po.currency or 'ILS',
            "status": po.status
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_partner_preorders_prepaid(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    أرصدة الحجوزات المسبقة (العربون المدفوع) للشريك
    إذا كان الشريك له عميل مرتبط، نحسب العربون من الحجوزات لذلك العميل
    """
    from models import PreOrder, PreOrderStatus
    from types import SimpleNamespace
    from extensions import db as _db

    session = session or _db.session
    db = SimpleNamespace(session=session)
    
    if not partner.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    preorders = db.session.query(PreOrder).filter(
        PreOrder.customer_id == partner.customer_id,
        PreOrder.prepaid_amount > 0,
        PreOrder.status != 'FULFILLED',
        PreOrder.preorder_date >= date_from,
        PreOrder.preorder_date <= date_to
    ).order_by(PreOrder.preorder_date).limit(10000).all()
    
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


def _get_partner_expenses(partner_id: int, date_from: datetime, date_to: datetime, session=None):
    """جلب المصروفات المخصومة من حصة الشريك (غير توريد الخدمة)"""
    from models import Expense, ExpenseType
    from sqlalchemy import or_, and_, func
    from types import SimpleNamespace
    from extensions import db as _db

    session = session or _db.session
    db = SimpleNamespace(session=session)
    
    expenses = db.session.query(Expense).join(ExpenseType, Expense.type_id == ExpenseType.id).filter(
        or_(
            Expense.partner_id == partner_id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to,
        func.upper(ExpenseType.code) != "PARTNER_EXPENSE"
    ).all()
    
    total_ils = Decimal('0.00')
    for expense in expenses:
        amount = Decimal(str(expense.amount or 0))
        currency = expense.currency or "ILS"
        expense_date = expense.date or datetime.now(timezone.utc).replace(tzinfo=None)
        
        amount_ils = _convert_to_ils(amount, currency, expense_date)
        total_ils = total_ils + amount_ils
    
    return float(total_ils)


def _get_previous_partner_settlements(partner_id: int, before_date: datetime):
    """جلب التسويات السابقة للشريك"""
    from models import PartnerSettlement
    from sqlalchemy import desc
    
    settlements = db.session.query(PartnerSettlement).filter(
        PartnerSettlement.partner_id == partner_id,
        PartnerSettlement.created_at < before_date
    ).order_by(desc(PartnerSettlement.created_at)).limit(5).all()
    
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


def _get_partner_payments_received(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    دفعات استلمناها من الشريك (IN) - تُضاف إلى حقوقه علينا
    
    تشمل:
    1. الدفعات المرتبطة مباشرة بـ partner_id
    2. الدفعات المرتبطة بـ customer_id (العميل المرتبط بالشريك)
    3. الدفعات المرتبطة بمبيعات للعميل (entity_type = SALE)
    """
    from models import Payment, PaymentDirection, PaymentStatus, PaymentEntityType, Sale, Check
    from sqlalchemy import or_
    
    items = []
    total_ils = Decimal('0.00')

    session = session or db.session
    
    from models import PreOrder
    direct_payments = session.query(Payment).outerjoin(
        Check, Check.payment_id == Payment.id
    ).outerjoin(
        PreOrder, Payment.preorder_id == PreOrder.id
    ).filter(
        Payment.partner_id == partner_id,
        Payment.direction == PaymentDirection.IN,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to,
        or_(
            Payment.preorder_id.is_(None),
            Payment.sale_id.isnot(None),
            PreOrder.status == 'FULFILLED'
        )
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
            "source": "partner"
        })
    
    seen_payment_ids = {it.get("payment_id") for it in items if it.get("payment_id")}
    if partner.customer_id:
        from models import PreOrder
        customer_payments = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).outerjoin(
            PreOrder, Payment.preorder_id == PreOrder.id
        ).filter(
            Payment.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to,
            or_(
                Payment.preorder_id.is_(None),
                Payment.sale_id.isnot(None),
                PreOrder.status == 'FULFILLED'
            )
        ).all()
        
        for payment in customer_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
        
        sale_payments = session.query(Payment).join(
            Sale, Sale.id == Payment.sale_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).outerjoin(
            PreOrder, Payment.preorder_id == PreOrder.id
        ).filter(
            Sale.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to,
            or_(
                Payment.preorder_id.is_(None),
                Payment.sale_id.isnot(None),
                PreOrder.status == 'FULFILLED'
            )
        ).all()
        
        for payment in sale_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
        
        from models import Invoice
        invoice_payments = session.query(Payment).join(
            Invoice, Invoice.id == Payment.invoice_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Invoice.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.IN,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in invoice_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
        
        from models import ServiceRequest
        service_payments = session.query(Payment).join(
            ServiceRequest, ServiceRequest.id == Payment.service_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            ServiceRequest.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.IN,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in service_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
        
        from models import PreOrder
        preorder_payments = session.query(Payment).join(
            PreOrder, PreOrder.id == Payment.preorder_id
        ).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            PreOrder.customer_id == partner.customer_id,
            Payment.direction == PaymentDirection.IN,
        Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        Payment.payment_date >= date_from,
            Payment.payment_date <= date_to
        ).all()
        
        for payment in preorder_payments:
            if payment.id not in seen_payment_ids:
                amount_ils = _get_payment_total_ils(payment)
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
                seen_payment_ids.add(payment.id)
        
        preorders_with_prepaid = session.query(PreOrder).filter(
            PreOrder.customer_id == partner.customer_id,
            PreOrder.prepaid_amount > 0,
            PreOrder.status != 'FULFILLED',
            PreOrder.preorder_date >= date_from,
            PreOrder.preorder_date <= date_to
        ).all()
        
        for po in preorders_with_prepaid:
            existing_payment = session.query(Payment).filter(
                Payment.preorder_id == po.id,
                Payment.direction == PaymentDirection.IN,
                Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING])
            ).first()
            
            if not existing_payment:
                amount_ils = _convert_to_ils(
                    Decimal(str(po.prepaid_amount or 0)),
                    po.currency or 'ILS',
                    po.preorder_date or datetime.now(timezone.utc).replace(tzinfo=None)
                )
                total_ils += amount_ils
                
                items.append({
                    "payment_id": None,
                    "payment_number": None,
                    "date": po.preorder_date.strftime("%Y-%m-%d") if po.preorder_date else "",
                    "method": "PREPAID",
                    "check_number": None,
                    "amount": float(po.prepaid_amount or 0),
                    "currency": po.currency or 'ILS',
                    "amount_ils": float(amount_ils),
                    "notes": f"عربون حجز #{po.id}",
                    "source": "preorder_prepaid"
                })
    
    from models import Check, CheckStatus
    manual_checks = session.query(Check).filter(
        Check.partner_id == partner_id,
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
    
    items.sort(key=lambda x: x['date'])
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_partner_sales_as_customer(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    مبيعات للشريك (كعميل) - تُخصم من حقوقه
    """
    from models import Sale, SaleLine, Product
    session = session or db.session
    
    if not partner.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    sales = session.query(
        Sale.id.label("sale_id"),
        Sale.sale_number,
        Sale.sale_date,
        Sale.currency,
        Sale.total_amount,
        Sale.status
    ).filter(
        Sale.customer_id == partner.customer_id,
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to,
        Sale.status == SaleStatus.CONFIRMED
    ).order_by(Sale.sale_date).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for sale in sales:
        sale_lines = session.query(
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


def _get_partner_service_fees(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    رسوم صيانة على الشريك (كعميل) - تُخصم من حقوقه
    """
    from models import ServiceRequest
    session = session or db.session
    
    if not partner.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    services = session.query(ServiceRequest).filter(
        ServiceRequest.customer_id == partner.customer_id,
        ServiceRequest.received_at >= date_from,
        ServiceRequest.received_at <= date_to,
        ServiceRequest.status == ServiceStatus.COMPLETED.value
    ).order_by(ServiceRequest.received_at).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for service in services:
        parts_total = float(service.parts_total or 0)
        labor_total = float(service.labor_total or 0)
        discount = float(service.discount_total or 0)
        tax_rate = float(service.tax_rate or 0)
        
        subtotal = parts_total + labor_total - discount
        if subtotal < 0:
            subtotal = 0
        
        tax_amount = subtotal * (tax_rate / 100.0)
        service_total = subtotal + tax_amount
        
        amount_ils = _convert_to_ils(Decimal(str(service_total)), service.currency, service.received_at)
        total_ils += amount_ils
        
        items.append({
            "service_id": service.id,
            "service_number": service.service_number,
            "date": service.received_at.strftime("%Y-%m-%d") if service.received_at else "",
            "description": service.description or service.problem_description,
            "amount": service_total,
            "currency": service.currency,
            "amount_ils": float(amount_ils),
            "status": service.status,
            "parts_total": parts_total,
            "labor_total": labor_total,
            "discount": discount,
            "tax_rate": tax_rate,
            "service_total": service_total
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


def _get_partner_preorders_as_customer(partner_id: int, partner: Partner, date_from: datetime, date_to: datetime, session=None):
    """
    حجوزات مسبقة للشريك (إذا كان عميلاً) - تُخصم من حقوقه
    """
    from models import PreOrder
    session = session or db.session
    
    if not partner.customer_id:
        return {"items": [], "total_ils": 0.0, "count": 0}
    
    items = []
    total_ils = Decimal('0.00')
    
    preorders = session.query(PreOrder).filter(
        PreOrder.customer_id == partner.customer_id,
        PreOrder.status.in_(['CONFIRMED', 'COMPLETED', 'DELIVERED']),
        PreOrder.status != 'FULFILLED',
        PreOrder.created_at >= date_from,
        PreOrder.created_at <= date_to
    ).all()
    
    for po in preorders:
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


def _get_partner_damaged_items(partner_id: int, date_from: datetime, date_to: datetime, session=None):
    """
    القطع التالفة - نصيب الشريك من الخسارة (من سعر التكلفة)
    """
    from models import (
        StockAdjustment, StockAdjustmentItem, Product, 
        ProductPartner, Warehouse
    )
    session = session or db.session
    
    damaged_items = session.query(
        StockAdjustment.date,
        Product.name.label("product_name"),
        Product.sku,
        StockAdjustmentItem.quantity,
        StockAdjustmentItem.unit_cost,
        ProductPartner.share_percent,
        StockAdjustmentItem.notes,
        Warehouse.name.label("warehouse_name")
    ).join(
        StockAdjustmentItem, StockAdjustmentItem.adjustment_id == StockAdjustment.id
    ).join(
        Product, Product.id == StockAdjustmentItem.product_id
    ).join(
        ProductPartner, ProductPartner.product_id == Product.id
    ).outerjoin(
        Warehouse, Warehouse.id == StockAdjustmentItem.warehouse_id
    ).filter(
        ProductPartner.partner_id == partner_id,
        StockAdjustment.reason == 'DAMAGED',
        StockAdjustment.date >= date_from,
        StockAdjustment.date <= date_to,
        ProductPartner.share_percent > 0
    ).order_by(StockAdjustment.date).all()
    
    items = []
    total_ils = Decimal('0.00')
    
    for damaged in damaged_items:
        partner_loss = Decimal(str(damaged.quantity)) * Decimal(str(damaged.unit_cost or 0)) * Decimal(str(damaged.share_percent)) / Decimal("100")
        
        
        total_ils += partner_loss
        
        items.append({
            "date": damaged.date.strftime("%Y-%m-%d") if damaged.date else "",
            "product_name": damaged.product_name,
            "sku": damaged.sku,
            "warehouse": damaged.warehouse_name or "-",
            "quantity": damaged.quantity,
            "unit_cost": float(damaged.unit_cost or 0),
            "share_percentage": float(damaged.share_percent),
            "partner_loss": float(partner_loss),
            "reason": damaged.notes or "تالف"
        })
    
    return {
        "items": items,
        "total_ils": float(total_ils),
        "count": len(items)
    }


@partner_settlements_bp.route("/<int:partner_id>/settlement/approve", methods=["POST"], endpoint="approve_settlement")
@login_required
def approve_settlement(partner_id):
    from flask import flash, redirect
    from flask_login import current_user
    from models import PartnerSettlement
    
    partner = db.session.get(Partner, partner_id)
    if not partner:
        abort(404)
    
    date_from = request.form.get("date_from")
    date_to = request.form.get("date_to")
    
    if not date_from or not date_to:
        flash("يجب تحديد الفترة الزمنية", "error")
        return redirect(url_for("partner_settlements_bp.partner_settlement", partner_id=partner_id))
    
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00")) if isinstance(date_from, str) else date_from
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")) if isinstance(date_to, str) else date_to
    except Exception:
        flash("تنسيق التاريخ غير صحيح", "error")
        return redirect(url_for("partner_settlements_bp.partner_settlement", partner_id=partner_id))
    
    balance_data = _calculate_smart_partner_balance(partner_id, date_from_dt, date_to_dt)
    
    if not balance_data.get("success"):
        flash(balance_data.get("error", "خطأ في حساب التسوية"), "error")
        return redirect(url_for("partner_settlements_bp.partner_settlement", partner_id=partner_id))
    
    prev_settlement = db.session.query(PartnerSettlement).filter(
        PartnerSettlement.partner_id == partner_id,
        PartnerSettlement.is_approved == True
    ).order_by(PartnerSettlement.to_date.desc()).first()
    
    settlement = PartnerSettlement(
        partner_id=partner_id,
        from_date=date_from_dt,
        to_date=date_to_dt,
        currency="ILS",
        status=PartnerSettlementStatus.CONFIRMED.value,
        previous_settlement_id=prev_settlement.id if prev_settlement else None,
        opening_balance=Decimal(str(balance_data.get("opening_balance", {}).get("amount", 0))),
        rights_inventory=Decimal(str(balance_data.get("rights", {}).get("inventory", {}).get("total_ils", 0) if isinstance(balance_data.get("rights", {}).get("inventory"), dict) else balance_data.get("rights", {}).get("inventory", {}).get("total", 0))),
        rights_sales_share=Decimal(str(balance_data.get("rights", {}).get("sales_share", {}).get("total_share_ils", 0) if isinstance(balance_data.get("rights", {}).get("sales_share"), dict) else balance_data.get("rights", {}).get("sales_share", {}).get("total", 0))),
        rights_preorders=Decimal(str(balance_data.get("payments", {}).get("preorders_prepaid", {}).get("total_ils", 0))),
        rights_total=Decimal(str(balance_data.get("rights", {}).get("total", 0))),
        obligations_sales_to_partner=Decimal(str(balance_data.get("obligations", {}).get("sales_to_partner", {}).get("total_ils", 0))),
        obligations_services=Decimal(str(balance_data.get("obligations", {}).get("service_fees", {}).get("total_ils", 0))),
        obligations_damaged=Decimal(str(balance_data.get("obligations", {}).get("damaged_items", {}).get("total_ils", 0))),
        obligations_expenses=Decimal(str(balance_data.get("expenses", {}).get("total_ils", 0))),
        obligations_returns=0,
        obligations_total=Decimal(str(balance_data.get("obligations", {}).get("total", 0))),
        payments_out=Decimal(str(balance_data.get("payments", {}).get("total_paid", 0))),
        payments_in=Decimal(str(balance_data.get("payments", {}).get("total_received", 0))),
        payments_net=Decimal(str(balance_data.get("payments", {}).get("total_settled", 0))),
        closing_balance=Decimal(str(balance_data.get("balance", {}).get("net", 0))),
        is_approved=True,
        approved_by=current_user.id,
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    db.session.add(settlement)
    db.session.flush()
    
    try:
        from models import _gl_upsert_batch_and_entries, GL_ACCOUNTS
        
        partner_account = GL_ACCOUNTS.get("PARTNER_EQUITY", "3200_PARTNER_EQUITY")
        cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")
        ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
        
        # ✅ إضافة قيد محاسبي لنسبة المخزون (إن وجدت)
        inventory_share_amount = float(settlement.rights_inventory or 0)
        if inventory_share_amount > 0.01:
            # نسبة المخزون = حق للشريك (له علينا)
            # القيد: مدين Inventory Reserve / دائن AP
            inventory_reserve_account = GL_ACCOUNTS.get("INVENTORY_RESERVE", "1300_INV_RSV")
            if not inventory_reserve_account:
                inventory_reserve_account = "1300_INV_RSV"
            
            _gl_upsert_batch_and_entries(
                db.session.connection(),
                source_type="PARTNER_SETTLEMENT",
                source_id=settlement.id,
                purpose="INVENTORY_SHARE",
                currency="ILS",
                memo=f"نسبة الشريك في المخزون - تسوية #{settlement.code}",
                entries=[
                    (inventory_reserve_account, inventory_share_amount, 0.0),  # مدين: Inventory Reserve (أصل زاد)
                    (ap_account, 0.0, inventory_share_amount),  # دائن: AP (خصم زاد - له علينا)
                ],
                ref=f"PSETTLEMENT-INV-{settlement.code}",
                entity_type="PARTNER",
                entity_id=partner_id
            )
        
        # ✅ قيد التسوية (الرصيد النهائي)
        closing_balance_amount = float(settlement.closing_balance or 0)
        
        if abs(closing_balance_amount) > 0.01:
            if closing_balance_amount > 0:
                entries = [
                    (partner_account, closing_balance_amount, 0),
                    (cash_account, 0, closing_balance_amount),
                ]
                memo = f"تسوية شريك #{settlement.code} - له علينا {closing_balance_amount:.2f} ₪"
            else:
                entries = [
                    (cash_account, abs(closing_balance_amount), 0),
                    (partner_account, 0, abs(closing_balance_amount)),
                ]
                memo = f"تسوية شريك #{settlement.code} - عليه لنا {abs(closing_balance_amount):.2f} ₪"
            
            _gl_upsert_batch_and_entries(
                db.session.connection(),
                source_type="PARTNER_SETTLEMENT",
                source_id=settlement.id,
                purpose="SETTLEMENT",
                currency="ILS",
                memo=memo,
                entries=entries,
                ref=f"PSETTLEMENT-{settlement.code}",
                entity_type="PARTNER",
                entity_id=partner_id
            )
    except Exception as e:
        current_app.logger.warning(f"⚠️ تحذير: فشل إنشاء قيد GL للتسوية: {str(e)}")
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')

    try:
        import utils
        utils.update_entity_balance("PARTNER", partner_id)
    except Exception as e:
        current_app.logger.error(f"❌ فشل تحديث رصيد الشريك بعد اعتماد التسوية {getattr(settlement, 'code', '')}: {e}")
    
    flash("تم اعتماد التسوية بنجاح ✅ وإنشاء القيد المحاسبي", "success")
    return redirect(url_for("partner_settlements_bp.partner_settlement", partner_id=partner_id))


@partner_settlements_bp.route("/<int:partner_id>/settlements", methods=["GET"], endpoint="partner_settlements_list")
@login_required
def partner_settlements_list(partner_id):
    from models import PartnerSettlement
    
    partner = db.session.get(Partner, partner_id)
    if not partner:
        abort(404)
    
    settlements = db.session.query(PartnerSettlement).filter(
        PartnerSettlement.partner_id == partner_id,
        PartnerSettlement.is_approved == True
    ).order_by(PartnerSettlement.to_date.desc()).all()
    
    return render_template(
        "vendors/partners/settlements_list.html",
        partner=partner,
        settlements=settlements
    )

@partner_settlements_bp.route("/<int:partner_id>/inventory")
@login_required
def partner_inventory(partner_id):
    """
    تقرير مخزون الشريك: يعرض المنتجات التي يملك الشريك حصة فيها
    مع الكميات المتوفرة حالياً وقيمتها.
    """
    partner = Partner.query.get_or_404(partner_id)
    
    # 1. المنتجات المرتبطة بالشريك عبر ProductPartner (نسبة ثابتة في المنتج)
    pp_items = db.session.query(
        Product,
        ProductPartner.share_percent,
        StockLevel.quantity,
        Warehouse.name.label('warehouse_name')
    ).join(
        ProductPartner, ProductPartner.product_id == Product.id
    ).outerjoin(
        StockLevel, StockLevel.product_id == Product.id
    ).outerjoin(
        Warehouse, Warehouse.id == StockLevel.warehouse_id
    ).filter(
        ProductPartner.partner_id == partner_id,
        StockLevel.quantity > 0
    ).all()

    inventory = []
    total_value = 0

    for prod, share, qty, wh_name in pp_items:
        qty = float(qty or 0)
        share_pct = float(share or 0)
        owned_qty = qty * (share_pct / 100.0)
        
        # Value based on purchase price (Asset Value)
        unit_cost = float(prod.purchase_price or 0)
        owned_value = owned_qty * unit_cost
        
        inventory.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "sku": prod.sku,
            "warehouse": wh_name or "Unknown",
            "total_qty": qty,
            "share_pct": share_pct,
            "owned_qty": round(owned_qty, 2),
            "unit_cost": unit_cost,
            "owned_value": round(owned_value, 2),
            "source": "Product Share"
        })
        total_value += owned_value

    # 2. المنتجات المرتبطة بالشريك عبر WarehousePartnerShare (نسبة في مستودع)
    # هذا يتطلب منطقاً أعقد قليلاً إذا كان الشريك يملك نسبة في كل منتجات المستودع
    # ولكن عادة WarehousePartnerShare يكون محدداً بمنتج معين أيضاً (حسب الموديل)
    
    # التحقق من الموديل WarehousePartnerShare
    # إذا كان مرتبطاً بمنتج، نضيفه.
    
    from models import WarehousePartnerShare
    wps_items = db.session.query(
        Product,
        WarehousePartnerShare.share_percentage,
        StockLevel.quantity,
        Warehouse.name.label('warehouse_name')
    ).join(
        WarehousePartnerShare, 
        and_(
            WarehousePartnerShare.product_id == Product.id,
            WarehousePartnerShare.warehouse_id == StockLevel.warehouse_id
        )
    ).join(
        StockLevel, StockLevel.product_id == Product.id
    ).join(
        Warehouse, Warehouse.id == StockLevel.warehouse_id
    ).filter(
        WarehousePartnerShare.partner_id == partner_id,
        StockLevel.quantity > 0
    ).all()

    for prod, share, qty, wh_name in wps_items:
        # Avoid duplicates if covered by ProductPartner (assuming ProductPartner overrides or adds?)
        # Let's assume they are additive or mutually exclusive in usage.
        # For reporting, we list them.
        
        qty = float(qty or 0)
        share_pct = float(share or 0)
        owned_qty = qty * (share_pct / 100.0)
        unit_cost = float(prod.purchase_price or 0)
        owned_value = owned_qty * unit_cost

        inventory.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "sku": prod.sku,
            "warehouse": wh_name,
            "total_qty": qty,
            "share_pct": share_pct,
            "owned_qty": round(owned_qty, 2),
            "unit_cost": unit_cost,
            "owned_value": round(owned_value, 2),
            "source": "Warehouse Share"
        })
        total_value += owned_value

    return render_template(
        "vendors/partners/inventory.html",
        partner=partner,
        inventory=inventory,
        total_value=round(total_value, 2)
    )
