"""نقطة بيع — مبيعات نقدية سريعة."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, flash, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from sqlalchemy import or_
from models import (
    Customer,
    Product,
    Sale,
    SaleLine,
    SaleStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PaymentDirection,
    Warehouse,
    StockLevel,
    run_sale_gl_sync_after_commit,
)
from permissions_config.enums import SystemPermissions
from utils import permission_required, D

pos_bp = Blueprint("pos_bp", __name__, url_prefix="/pos")


def _walkin_customer():
    c = Customer.query.filter(Customer.name == "زبون نقدي POS").first()
    if c:
        return c
    c = Customer(name="زبون نقدي POS", phone="POS", currency="ILS")
    db.session.add(c)
    db.session.flush()
    return c


@pos_bp.route("/")
@login_required
@permission_required(SystemPermissions.USE_POS)
def terminal():
    import json
    from utils.company_scope import filter_warehouses_query

    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(300).all()
    warehouses = filter_warehouses_query(Warehouse.query.filter_by(is_active=True)).order_by(Warehouse.name).all()
    products_json = json.dumps(
        {
            str(p.id): {
                "id": p.id,
                "name": p.name,
                "price": float(p.selling_price or p.price or 0),
            }
            for p in products
        },
        ensure_ascii=False,
    )
    return render_template(
        "pos/terminal.html",
        products=products,
        warehouses=warehouses,
        products_json=products_json,
    )


@pos_bp.route("/barcode")
@login_required
@permission_required(SystemPermissions.USE_POS)
def barcode_lookup():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"success": False, "error": "الباركود مطلوب"}), 400
    p = Product.query.filter(
        or_(
            Product.barcode == code,
            Product.sku == code,
            Product.id == int(code) if code.isdigit() else -1,
        )
    ).filter_by(is_active=True).first()
    if not p:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    return jsonify({
        "success": True,
        "product": {
            "id": p.id,
            "name": p.name,
            "price": float(p.selling_price or p.price or 0),
            "barcode": p.barcode,
            "sku": p.sku,
        },
    })


@pos_bp.route("/checkout", methods=["POST"])
@login_required
@permission_required(SystemPermissions.USE_POS)
def checkout():
    try:
        from utils.company_scope import assert_warehouse_access

        data = request.get_json(force=True) if request.is_json else request.form
        warehouse_id = int(data.get("warehouse_id") or 0)
        assert_warehouse_access(warehouse_id)
        lines = data.get("lines") or []
        if not warehouse_id or not lines:
            return jsonify({"success": False, "error": "المستودع والبنود مطلوبان"}), 400
        customer = _walkin_customer()
        sale = Sale(
            customer_id=customer.id,
            seller_id=current_user.id,
            sale_date=datetime.now(timezone.utc).replace(tzinfo=None),
            status=SaleStatus.CONFIRMED.value,
            currency="ILS",
            tax_rate=Decimal(str(data.get("tax_rate") or 16)),
            sale_channel="POS",
            notes="[POS]",
        )
        db.session.add(sale)
        db.session.flush()
        total = Decimal("0")
        for row in lines:
            pid = int(row.get("product_id"))
            qty = Decimal(str(row.get("quantity") or 1))
            price = Decimal(str(row.get("price") or 0))
            if qty <= 0:
                continue
            stock = StockLevel.query.filter_by(product_id=pid, warehouse_id=warehouse_id).first()
            if stock and float(stock.quantity or 0) < float(qty):
                return jsonify({"success": False, "error": f"مخزون غير كافٍ للمنتج {pid}"}), 400
            line_total = qty * price
            total += line_total
            db.session.add(
                SaleLine(
                    sale_id=sale.id,
                    product_id=pid,
                    warehouse_id=warehouse_id,
                    quantity=int(qty),
                    unit_price=price,
                    discount_rate=Decimal("0"),
                    tax_rate=sale.tax_rate,
                )
            )
        sale.total_amount = total
        sale.balance_due = Decimal("0")
        pay = Payment(
            customer_id=customer.id,
            sale_id=sale.id,
            total_amount=total,
            currency="ILS",
            method=PaymentMethod.CASH.value,
            direction=PaymentDirection.IN.value,
            status=PaymentStatus.COMPLETED.value,
            payment_date=datetime.now(timezone.utc).replace(tzinfo=None),
            notes="POS cash",
        )
        db.session.add(pay)
        db.session.flush()
        sale.total_paid = total
        db.session.commit()
        run_sale_gl_sync_after_commit(sale.id)
        return jsonify({
            "success": True,
            "sale_id": sale.id,
            "payment_id": pay.id,
            "total": float(total),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
