"""إشعارات استلام بضاعة (GRN) من أوامر الشراء."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from extensions import db
from models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, Warehouse


def _next_grn_number() -> str:
    n = GoodsReceipt.query.count() + 1
    return f"GRN-{datetime.now().year}-{n:05d}"


def create_grn_from_po(
    po: PurchaseOrder,
    *,
    warehouse_id: int | None = None,
    line_qtys: dict[int, Decimal] | None = None,
    notes: str | None = None,
) -> GoodsReceipt:
    """إنشاء GRN من كميات الاستلام على أمر الشراء."""
    wh = None
    if warehouse_id:
        wh = db.session.get(Warehouse, warehouse_id)
    if not wh:
        wh = (
            Warehouse.query.filter_by(branch_id=po.branch_id, is_active=True)
            .order_by(Warehouse.id.asc())
            .first()
        )
    grn = GoodsReceipt(
        number=_next_grn_number(),
        purchase_order_id=po.id,
        branch_id=po.branch_id,
        warehouse_id=wh.id if wh else None,
        receipt_date=date.today(),
        status="POSTED",
        notes=notes or f"استلام من {po.number}",
    )
    db.session.add(grn)
    db.session.flush()
    any_line = False
    for ln in po.lines:
        if line_qtys and ln.id in line_qtys:
            qty = Decimal(str(line_qtys[ln.id] or 0))
        else:
            qty = Decimal(str(ln.received_qty or 0))
        if qty <= 0:
            continue
        max_q = Decimal(str(ln.quantity or 0))
        qty = min(qty, max_q)
        db.session.add(
            GoodsReceiptLine(
                goods_receipt_id=grn.id,
                product_id=ln.product_id,
                quantity=qty,
                unit_price=Decimal(str(ln.unit_price or 0)),
            )
        )
        any_line = True
    if not any_line:
        raise ValueError("لا بنود للاستلام في GRN")
    return grn
