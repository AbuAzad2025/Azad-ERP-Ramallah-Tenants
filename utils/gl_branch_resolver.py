"""تحديد فرع قيد GL من مصدر الحركة."""
from __future__ import annotations

from typing import Optional


def resolve_branch_for_gl(
    source_type: str,
    source_id: int,
    *,
    connection=None,
) -> Optional[int]:
    st = (source_type or "").upper()
    sid = int(source_id or 0)
    if not sid and st not in ("MANUAL", "TAX_ACCRUAL"):
        return None

    from extensions import db

    sess = connection or db.session

    if st == "SALE":
        from models import Sale, SaleLine, Warehouse

        sale = sess.get(Sale, sid) if hasattr(sess, "get") else None
        if sale:
            line = (
                SaleLine.query.filter_by(sale_id=sale.id)
                .join(Warehouse, Warehouse.id == SaleLine.warehouse_id)
                .filter(Warehouse.branch_id.isnot(None))
                .first()
            )
            if line and line.warehouse and line.warehouse.branch_id:
                return int(line.warehouse.branch_id)
        return None

    if st in ("PAYMENT", "PAYMENT_SPLIT"):
        from models import Payment, Expense, Shipment, Warehouse, Sale

        pay = sess.get(Payment, sid) if hasattr(sess, "get") else None
        if not pay:
            return None
        if pay.expense_id:
            exp = sess.get(Expense, pay.expense_id)
            if exp and exp.branch_id:
                return int(exp.branch_id)
        if pay.shipment_id:
            sh = sess.get(Shipment, pay.shipment_id)
            if sh and sh.destination_id:
                wh = sess.get(Warehouse, sh.destination_id)
                if wh and wh.branch_id:
                    return int(wh.branch_id)
        if pay.sale_id:
            return resolve_branch_for_gl("SALE", pay.sale_id, connection=connection)
        return None

    if st in ("EXPENSE", "EXPENSE_PAYMENT", "PAYROLL"):
        from models import Expense, PayrollRun

        if st == "PAYROLL":
            pr = sess.get(PayrollRun, sid)
            return int(pr.branch_id) if pr and pr.branch_id else None
        exp = sess.get(Expense, sid)
        return int(exp.branch_id) if exp and exp.branch_id else None

    if st == "PURCHASE_ORDER":
        from models import PurchaseOrder

        po = sess.get(PurchaseOrder, sid)
        return int(po.branch_id) if po and po.branch_id else None

    if st == "SHIPMENT":
        from models import Shipment, Warehouse

        sh = sess.get(Shipment, sid)
        if sh and sh.destination_id:
            wh = sess.get(Warehouse, sh.destination_id)
            if wh and wh.branch_id:
                return int(wh.branch_id)
        return None

    if st == "SUPPLIER_INVOICE":
        from models import SupplierInvoice

        inv = sess.get(SupplierInvoice, sid)
        return int(inv.branch_id) if inv and inv.branch_id else None

    return None
