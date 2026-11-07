"""أوامر الشراء — دورة AP خفيفة مكمّلة للشحنات."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from decimal import Decimal

from extensions import db
from models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    Branch,
    Product,
    Warehouse,
    Shipment,
    ShipmentItem,
    GoodsReceipt,
    SupplierInvoice,
)
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.company_scope import filter_by_branches, default_company

purchases_bp = Blueprint("purchases_bp", __name__, url_prefix="/purchases")


def _next_po_number():
    n = PurchaseOrder.query.count() + 1
    return f"PO-{datetime.now().year}-{n:05d}"


@purchases_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def index():
    q = PurchaseOrder.query.order_by(PurchaseOrder.order_date.desc())
    q = filter_by_branches(q, PurchaseOrder.branch_id)
    status = request.args.get("status", "")
    if status:
        q = q.filter(PurchaseOrder.status == status.upper())
    orders = q.limit(200).all()
    return render_template("purchases/index.html", orders=orders, status=status)


@purchases_bp.route("/add", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def add():
    suppliers = Supplier.query.filter(Supplier.is_archived == False).order_by(Supplier.name).all()  # noqa: E712
    from utils.tenant_ui import accessible_branches_query, resolve_branch_id

    branches = accessible_branches_query().all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).limit(500).all()

    if request.method == "POST":
        try:
            supplier_id = request.form.get("supplier_id", type=int)
            branch_id = resolve_branch_id(request.form.get("branch_id"), required=True)
            raw_date = request.form.get("order_date")
            if raw_date:
                try:
                    order_date = date.fromisoformat(str(raw_date)[:10])
                except ValueError:
                    order_date = date.today()
            else:
                order_date = date.today()
            po = PurchaseOrder(
                number=_next_po_number(),
                supplier_id=supplier_id,
                branch_id=branch_id,
                order_date=order_date,
                expected_date=request.form.get("expected_date") or None,
                status="ORDERED",
                currency=request.form.get("currency") or "ILS",
                notes=request.form.get("notes"),
            )
            db.session.add(po)
            db.session.flush()
            total = Decimal("0")
            pids = request.form.getlist("product_id")
            qtys = request.form.getlist("quantity")
            prices = request.form.getlist("unit_price")
            for i, pid in enumerate(pids):
                if not pid:
                    continue
                qty = Decimal(str(qtys[i] if i < len(qtys) else 1))
                price = Decimal(str(prices[i] if i < len(prices) else 0))
                if qty <= 0:
                    continue
                db.session.add(
                    PurchaseOrderLine(
                        purchase_order_id=po.id,
                        product_id=int(pid),
                        quantity=qty,
                        unit_price=price,
                    )
                )
                total += qty * price
            po.total_amount = total
            db.session.commit()
            flash(f"تم إنشاء أمر الشراء {po.number}", "success")
            return redirect(url_for("purchases_bp.detail", id=po.id))
        except Exception as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template(
        "purchases/form.html",
        suppliers=suppliers,
        branches=branches,
        products=products,
        order=None,
    )


@purchases_bp.route("/<int:id>")
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def detail(id):
    order = db.session.get(PurchaseOrder, id) or abort(404)
    return render_template("purchases/detail.html", order=order)


@purchases_bp.route("/<int:id>/status", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def set_status(id):
    from flask import abort
    order = db.session.get(PurchaseOrder, id) or abort(404)
    st = (request.form.get("status") or "").upper()
    if st in ("DRAFT", "ORDERED", "PARTIAL", "RECEIVED", "CANCELLED"):
        order.status = st
        if st == "RECEIVED":
            for ln in order.lines:
                ln.received_qty = ln.quantity
        db.session.commit()
        if st == "RECEIVED":
            from utils.po_gl_service import run_po_gl_sync_after_commit
            run_po_gl_sync_after_commit(order.id)
        flash("تم تحديث الحالة", "success")
    return redirect(url_for("purchases_bp.detail", id=id))


@purchases_bp.route("/<int:id>/create-shipment", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def create_shipment_from_po(id):
    order = db.session.get(PurchaseOrder, id) or abort(404)
    if not order.lines:
        flash("أمر الشراء بلا بنود", "warning")
        return redirect(url_for("purchases_bp.detail", id=id))
    wh = (
        Warehouse.query.filter_by(branch_id=order.branch_id, is_active=True)
        .order_by(Warehouse.id.asc())
        .first()
    )
    if not wh:
        flash("لا مستودع نشط مرتبط بفرع أمر الشراء", "danger")
        return redirect(url_for("purchases_bp.detail", id=id))
    sh = Shipment(
        shipment_number=None,
        shipment_date=datetime.now(),
        expected_arrival=datetime.now(),
        status="DRAFT",
        destination_id=wh.id,
        currency=order.currency or "ILS",
        purchase_order_id=order.id,
        notes=f"من أمر شراء {order.number}",
    )
    db.session.add(sh)
    db.session.flush()
    for ln in order.lines:
        qty = int(ln.quantity or 0) or 1
        sh.items.append(
            ShipmentItem(
                product_id=ln.product_id,
                warehouse_id=wh.id,
                quantity=qty,
                unit_cost=float(ln.unit_price or 0),
                declared_value=float((ln.quantity or 0) * (ln.unit_price or 0)),
            )
        )
    db.session.commit()
    flash(f"تم إنشاء الشحنة #{sh.id} من {order.number}", "success")
    return redirect(url_for("shipments_bp.edit_shipment", id=sh.id))


@purchases_bp.route("/<int:id>/receive", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def partial_receive(id):
    order = db.session.get(PurchaseOrder, id) or abort(404)
    any_rcv = False
    for ln in order.lines:
        key = f"recv_qty_{ln.id}"
        raw = request.form.get(key)
        if raw is None:
            continue
        qty = Decimal(str(raw or 0))
        if qty < 0:
            continue
        max_q = Decimal(str(ln.quantity or 0))
        ln.received_qty = min(qty, max_q)
        if ln.received_qty > 0:
            any_rcv = True
    if not any_rcv:
        flash("لم تُدخل كميات استلام", "warning")
        return redirect(url_for("purchases_bp.detail", id=id))
    all_full = all(
        Decimal(str(l.received_qty or 0)) >= Decimal(str(l.quantity or 0)) for l in order.lines
    )
    any_partial = any(
        Decimal("0") < Decimal(str(l.received_qty or 0)) < Decimal(str(l.quantity or 0))
        for l in order.lines
    )
    order.status = "RECEIVED" if all_full else "PARTIAL"
    db.session.commit()
    if order.status == "RECEIVED":
        from utils.po_gl_service import run_po_gl_sync_after_commit
        run_po_gl_sync_after_commit(order.id)
    flash("تم تسجيل الاستلام", "success")
    return redirect(url_for("purchases_bp.detail", id=id))


@purchases_bp.route("/<int:id>/supplier-invoice", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def create_supplier_invoice(id):
    order = db.session.get(PurchaseOrder, id) or abort(404)
    try:
        from utils.supplier_invoice_service import create_from_purchase_order, post_supplier_invoice_gl

        inv = create_from_purchase_order(order)
        db.session.commit()
        post_supplier_invoice_gl(inv.id)
        flash(f"تم إنشاء وترحيل فاتورة المورد {inv.number}", "success")
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("purchases_bp.detail", id=id))


@purchases_bp.route("/<int:id>/request-approval", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def request_po_approval(id):
    from flask_login import current_user
    from utils.document_approval_service import request_approval

    request_approval("PURCHASE_ORDER", id, current_user.id)
    db.session.commit()
    flash("تم طلب اعتماد أمر الشراء", "info")
    return redirect(url_for("purchases_bp.detail", id=id))


@purchases_bp.route("/<int:id>/grn", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def create_grn(id):
    order = db.session.get(PurchaseOrder, id) or abort(404)
    try:
        from utils.goods_receipt_service import create_grn_from_po

        wh_id = request.form.get("warehouse_id", type=int)
        grn = create_grn_from_po(order, warehouse_id=wh_id)
        db.session.commit()
        flash(f"تم إنشاء إشعار الاستلام {grn.number}", "success")
        return redirect(url_for("purchases_bp.grn_detail", id=grn.id))
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("purchases_bp.detail", id=id))


@purchases_bp.route("/grn/<int:id>")
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def grn_detail(id):
    grn = db.session.get(GoodsReceipt, id) or abort(404)
    return render_template("purchases/grn_detail.html", grn=grn)


@purchases_bp.route("/supplier-invoices")
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def supplier_invoices():
    q = SupplierInvoice.query.order_by(SupplierInvoice.invoice_date.desc())
    q = filter_by_branches(q, SupplierInvoice.branch_id)
    status = request.args.get("status", "")
    if status:
        q = q.filter(SupplierInvoice.status == status.upper())
    invoices = q.limit(200).all()
    for inv in invoices:
        inv.balance_due = float(inv.total_amount or 0) - float(inv.amount_paid or 0)
    return render_template("purchases/supplier_invoices.html", invoices=invoices, status=status)


@purchases_bp.route("/supplier-invoices/<int:id>/pay", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def pay_supplier_invoice(id):
    from flask_login import current_user
    from utils.supplier_invoice_service import pay_supplier_invoice as do_pay

    inv = db.session.get(SupplierInvoice, id) or abort(404)
    amount = request.form.get("amount", type=float) or float(inv.total_amount or 0) - float(inv.amount_paid or 0)
    try:
        do_pay(inv, amount, method=request.form.get("method") or "BANK", created_by_id=current_user.id)
        flash("تم تسجيل الدفع وترحيل القيد", "success")
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("purchases_bp.supplier_invoices"))
