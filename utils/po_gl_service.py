"""ترحيل GL لأوامر الشراء عند الاستلام الكامل."""
from __future__ import annotations

from datetime import datetime, timezone


def run_po_gl_sync_after_commit(purchase_order_id: int) -> None:
    if not purchase_order_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session
        from models import PurchaseOrder, GL_ACCOUNTS, _gl_upsert_batch_and_entries, _ensure_account_exists

        session = Session(db.engine)
        try:
            po = session.get(PurchaseOrder, purchase_order_id)
            if not po or (po.status or "").upper() != "RECEIVED":
                return
            amount = float(po.total_amount or 0)
            if amount <= 0:
                return
            conn = session.connection()
            purchase_account = GL_ACCOUNTS.get("PURCHASES", "5100_PURCHASES")
            ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
            _ensure_account_exists(conn, purchase_account)
            _ensure_account_exists(conn, ap_account)
            _gl_upsert_batch_and_entries(
                conn,
                source_type="PURCHASE_ORDER",
                source_id=po.id,
                purpose="PO_RECEIVED",
                currency=po.currency or "ILS",
                memo=f"استلام أمر شراء {po.number}",
                entries=[(purchase_account, amount, 0.0), (ap_account, 0.0, amount)],
                ref=po.number or f"PO-{po.id}",
                entity_type="SUPPLIER",
                entity_id=po.supplier_id,
            )
            session.commit()
        finally:
            session.close()
    except Exception as e:
        try:
            from flask import current_app
            if current_app:
                current_app.logger.warning(
                    "PO GL sync failed for po_id=%s: %s", purchase_order_id, e, exc_info=True
                )
        except Exception:
            pass
