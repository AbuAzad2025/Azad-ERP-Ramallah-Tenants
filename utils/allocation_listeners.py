#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مستمعات التوزيع التلقائي - نسخة محسّنة وسريعة

هيكل بسيط:
- مستمع واحد لكل كيان (بعد الإنشاء/التحديث)
- كل مستمع يستدعي دالة توزيع واحدة
- لا تعقيد، لا تداخل
"""

import logging

logger = logging.getLogger(__name__)
_ALLOCATION_LISTENERS_REGISTERED = False
_ALLOC_RUNNING = False

# =============================================================================
# الدالة المركزية للتوزيع
# =============================================================================

def _allocate(customer_id: int, source: str = "") -> None:
    """
    دالة بسيطة لتفعيل التوزيع لعميل محدد
    """
    if not customer_id:
        return
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return

    try:
        from utils.credit_allocator import apply_customer_credit_to_obligations

        result = apply_customer_credit_to_obligations(customer_id)

        if result:
            logger.info(f"✅ توزيع تلقائي للعميل #{customer_id} ({len(result)} دفعة) - مصدر: {source}")

    except Exception as e:
        logger.error(f"❌ خطأ في التوزيع للعميل #{customer_id}: {e}")

def _allocate_supplier(supplier_id: int, source: str = "") -> None:
    if not supplier_id:
        return
    try:
        from utils.credit_allocator import apply_supplier_out_payments_to_obligations

        result = apply_supplier_out_payments_to_obligations(int(supplier_id))
        if result:
            logger.info(f"✅ توزيع تلقائي للمورد #{supplier_id} ({len(result)} دفعة) - مصدر: {source}")
    except Exception as e:
        logger.error(f"❌ خطأ في التوزيع للمورد #{supplier_id}: {e}")


def _allocate_partner(partner_id: int, source: str = "") -> None:
    if not partner_id:
        return
    try:
        from utils.credit_allocator import apply_partner_out_payments_to_obligations

        result = apply_partner_out_payments_to_obligations(int(partner_id))
        if result:
            logger.info(f"✅ توزيع تلقائي للشريك #{partner_id} ({len(result)} دفعة) - مصدر: {source}")
    except Exception as e:
        logger.error(f"❌ خطأ في التوزيع للشريك #{partner_id}: {e}")

def _spawn_allocation(kind: str, entity_id: int, source: str = "") -> None:
    if not entity_id:
        return
    try:
        from flask import current_app, has_request_context
        from extensions import db

        app = current_app._get_current_object()
        join_thread = not has_request_context()

        def _worker():
            global _ALLOC_RUNNING
            _ALLOC_RUNNING = True
            try:
                with app.app_context():
                    try:
                        db.session.remove()
                    except Exception:
                        pass
                    if kind == "customer":
                        _allocate(int(entity_id), source)
                    elif kind == "supplier":
                        _allocate_supplier(int(entity_id), source)
                    elif kind == "partner":
                        _allocate_partner(int(entity_id), source)
            finally:
                try:
                    db.session.remove()
                except Exception:
                    pass
                _ALLOC_RUNNING = False

        t = Thread(target=_worker, daemon=not join_thread)
        t.start()
        if join_thread:
            t.join()
    except Exception:
        return

def _queue_customer_allocation(target, customer_id: int, source: str = "") -> None:
    if not customer_id:
        return
    if _ALLOC_RUNNING:
        return
    try:
        from sqlalchemy.orm import object_session
        from extensions import db

        sess = object_session(target) or db.session
        queue = sess.info.setdefault("customer_alloc_queue", [])
        queue.append({"customer_id": int(customer_id), "source": str(source or "")})
    except Exception:
        pass


def _queue_customer_allocation_by_id(customer_id: int, source: str = "") -> None:
    if not customer_id:
        return
    if _ALLOC_RUNNING:
        return
    try:
        from extensions import db

        queue = db.session.info.setdefault("customer_alloc_queue", [])
        queue.append({"customer_id": int(customer_id), "source": str(source or "")})
    except Exception:
        pass


def _queue_supplier_allocation(target, supplier_id: int, source: str = "") -> None:
    if not supplier_id:
        return
    if _ALLOC_RUNNING:
        return
    try:
        from sqlalchemy.orm import object_session
        from extensions import db

        sess = object_session(target) or db.session
        queue = sess.info.setdefault("supplier_alloc_queue", [])
        queue.append({"supplier_id": int(supplier_id), "source": str(source or "")})
    except Exception:
        pass


def _queue_partner_allocation(target, partner_id: int, source: str = "") -> None:
    if not partner_id:
        return
    if _ALLOC_RUNNING:
        return
    try:
        from sqlalchemy.orm import object_session
        from extensions import db

        sess = object_session(target) or db.session
        queue = sess.info.setdefault("partner_alloc_queue", [])
        queue.append({"partner_id": int(partner_id), "source": str(source or "")})
    except Exception:
        pass

# =============================================================================
# مستمعات الالتزامات (Obligations) - للعملاء
# =============================================================================

def on_sale_created(mapper, connection, target):
    """مستمع إنشاء مبيعة جديدة"""
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    if target.customer_id and (getattr(target, 'balance_due', 0) or 0) > 0:
        _queue_customer_allocation(target, target.customer_id, f"Sale #{getattr(target, 'sale_number', target.id)}")

def on_service_created(mapper, connection, target):
    """مستمع إنشاء طلب صيانة جديد"""
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    if target.customer_id and (getattr(target, 'balance_due', 0) or 0) > 0:
        _queue_customer_allocation(target, target.customer_id, f"Service #{getattr(target, 'request_number', target.id)}")

def on_preorder_created(mapper, connection, target):
    """مستمع إنشاء حجز جديد"""
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    if target.customer_id and (getattr(target, 'balance_due', 0) or 0) > 0:
        _queue_customer_allocation(target, target.customer_id, f"Preorder #{getattr(target, 'preorder_number', target.id)}")

def on_invoice_created(mapper, connection, target):
    """مستمع إنشاء فاتورة جديدة (مستقلة)"""
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    if target.customer_id and not target.sale_id and not target.service_id and not target.preorder_id:
        balance = (getattr(target, 'total_amount', 0) or 0) - (getattr(target, 'total_paid', 0) or 0)
        if balance > 0:
            _queue_customer_allocation(target, target.customer_id, f"Invoice #{getattr(target, 'invoice_number', target.id)}")


# =============================================================================
# مستمعات الحقوق (Rights) - للعملاء
# =============================================================================

def on_payment_received(mapper, connection, target):
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    direction = getattr(target, "direction", None)
    status = getattr(target, "status", None)

    if (
        direction == "IN"
        and status == "COMPLETED"
        and not target.sale_id
        and not target.invoice_id
        and not target.service_id
        and not target.preorder_id
    ):
        customer_id = getattr(target, "customer_id", None)
        if not customer_id:
            try:
                from sqlalchemy import text as sa_text

                supplier_id = getattr(target, "supplier_id", None)
                partner_id = getattr(target, "partner_id", None)
                if supplier_id:
                    customer_id = connection.execute(
                        sa_text("SELECT customer_id FROM suppliers WHERE id = :id"),
                        {"id": int(supplier_id)},
                    ).scalar()
                elif partner_id:
                    customer_id = connection.execute(
                        sa_text("SELECT customer_id FROM partners WHERE id = :id"),
                        {"id": int(partner_id)},
                    ).scalar()
            except Exception:
                customer_id = None
        if customer_id:
            _queue_customer_allocation(target, int(customer_id), f"Payment #{target.id}")

    if (
        direction == "OUT"
        and status == "COMPLETED"
        and not target.shipment_id
        and not target.sale_id
        and not target.invoice_id
        and not target.service_id
        and not target.preorder_id
        and not target.expense_id
        and not target.loan_settlement_id
    ):
        ref = str(getattr(target, "reference", "") or "")
        if getattr(target, "supplier_id", None):
            if not ref.startswith("SupplierSettle:"):
                _queue_supplier_allocation(target, int(target.supplier_id), f"Payment #{target.id}")
        elif getattr(target, "partner_id", None):
            if not ref.startswith("PartnerSettle:"):
                _queue_partner_allocation(target, int(target.partner_id), f"Payment #{target.id}")


def on_check_updated(mapper, connection, target):
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return
    except Exception:
        return
    try:
        status = str(getattr(target, "status", "") or "").upper()
        if status != "CASHED":
            return
        payment_id = getattr(target, "payment_id", None)
        if not payment_id:
            return
        from sqlalchemy import text as sa_text

        row = connection.execute(
            sa_text("SELECT direction, customer_id, supplier_id, partner_id FROM payments WHERE id = :pid"),
            {"pid": int(payment_id)},
        ).first()
        if not row:
            return
        direction, customer_id, supplier_id, partner_id = row[0], row[1], row[2], row[3]

        if str(direction or "").upper() == "IN":
            if not customer_id:
                try:
                    if supplier_id:
                        customer_id = connection.execute(
                            sa_text("SELECT customer_id FROM suppliers WHERE id = :id"),
                            {"id": int(supplier_id)},
                        ).scalar()
                    elif partner_id:
                        customer_id = connection.execute(
                            sa_text("SELECT customer_id FROM partners WHERE id = :id"),
                            {"id": int(partner_id)},
                        ).scalar()
                except Exception:
                    customer_id = None
            if customer_id:
                _queue_customer_allocation_by_id(int(customer_id), f"Check #{getattr(target, 'id', payment_id)} CASHED")
            return

        if str(direction or "").upper() == "OUT":
            if supplier_id:
                _queue_supplier_allocation(target, int(supplier_id), f"Check #{getattr(target, 'id', payment_id)} CASHED")
            elif partner_id:
                _queue_partner_allocation(target, int(partner_id), f"Check #{getattr(target, 'id', payment_id)} CASHED")
    except Exception:
        pass


def _process_alloc_queue(session):
    if session.info.get("_alloc_in_commit"):
        return
    if _ALLOC_RUNNING:
        return
    cqueue = (session.info.pop("customer_alloc_queue", None) or []).copy()
    squeue = (session.info.pop("supplier_alloc_queue", None) or []).copy()
    pqueue = (session.info.pop("partner_alloc_queue", None) or []).copy()
    if not cqueue and not squeue and not pqueue:
        return
    session.info["_alloc_in_commit"] = True
    try:
        seen_c = set()
        for item in cqueue:
            try:
                cid = int(item.get("customer_id") or 0)
            except Exception:
                cid = 0
            if not cid or cid in seen_c:
                continue
            seen_c.add(cid)
            _spawn_allocation("customer", cid, item.get("source", "") or "")

        seen_s = set()
        for item in squeue:
            try:
                sid = int(item.get("supplier_id") or 0)
            except Exception:
                sid = 0
            if not sid or sid in seen_s:
                continue
            seen_s.add(sid)
            _spawn_allocation("supplier", sid, item.get("source", "") or "")

        seen_p = set()
        for item in pqueue:
            try:
                pid = int(item.get("partner_id") or 0)
            except Exception:
                pid = 0
            if not pid or pid in seen_p:
                continue
            seen_p.add(pid)
            _spawn_allocation("partner", pid, item.get("source", "") or "")
    finally:
        session.info.pop("_alloc_in_commit", None)


def on_supplier_settlement_updated(mapper, connection, target):
    try:
        from sqlalchemy import inspect

        hist = inspect(target)
        if not hist.attrs.get("status"):
            return
        status_hist = hist.attrs["status"].history
        old_status = status_hist.deleted[0] if status_hist.deleted else None
        new_status = status_hist.added[0] if status_hist.added else getattr(target, "status", None)
        if old_status != new_status and str(new_status or "").upper() == "CONFIRMED":
            if getattr(target, "supplier_id", None):
                _queue_supplier_allocation(target, int(target.supplier_id), f"SupplierSettlement #{getattr(target, 'code', target.id)} CONFIRMED")
    except Exception:
        pass


def on_partner_settlement_updated(mapper, connection, target):
    try:
        from sqlalchemy import inspect

        hist = inspect(target)
        if not hist.attrs.get("status"):
            return
        status_hist = hist.attrs["status"].history
        old_status = status_hist.deleted[0] if status_hist.deleted else None
        new_status = status_hist.added[0] if status_hist.added else getattr(target, "status", None)
        if old_status != new_status and str(new_status or "").upper() == "CONFIRMED":
            if getattr(target, "partner_id", None):
                _queue_partner_allocation(target, int(target.partner_id), f"PartnerSettlement #{getattr(target, 'code', target.id)} CONFIRMED")
    except Exception:
        pass


def on_expense_created(mapper, connection, target):
    try:
        if getattr(target, "supplier_id", None):
            _queue_supplier_allocation(target, int(target.supplier_id), f"Expense #{getattr(target, 'id', '')}")
        elif getattr(target, "partner_id", None):
            _queue_partner_allocation(target, int(target.partner_id), f"Expense #{getattr(target, 'id', '')}")
    except Exception:
        pass


def on_supplier_loan_settlement_created(mapper, connection, target):
    try:
        if getattr(target, "supplier_id", None):
            _queue_supplier_allocation(target, int(target.supplier_id), f"SupplierLoanSettlement #{getattr(target, 'id', '')}")
    except Exception:
        pass


def register_allocation_listeners():
    """
    تسجيل جميع مستمعات التوزيع التلقائي
    """
    global _ALLOCATION_LISTENERS_REGISTERED
    if _ALLOCATION_LISTENERS_REGISTERED:
        return
    from sqlalchemy import event
    from extensions import db
    from models import (
        Check,
        Expense,
        Invoice,
        PartnerSettlement,
        Payment,
        PreOrder,
        Sale,
        ServiceRequest,
        SupplierLoanSettlement,
        SupplierSettlement,
    )

    if not event.contains(db.session, "after_commit", _process_alloc_queue):
        event.listen(db.session, "after_commit", _process_alloc_queue)

    if not event.contains(Sale, "after_insert", on_sale_created):
        event.listen(Sale, "after_insert", on_sale_created)
    if not event.contains(ServiceRequest, "after_insert", on_service_created):
        event.listen(ServiceRequest, "after_insert", on_service_created)
    if not event.contains(PreOrder, "after_insert", on_preorder_created):
        event.listen(PreOrder, "after_insert", on_preorder_created)
    if not event.contains(Invoice, "after_insert", on_invoice_created):
        event.listen(Invoice, "after_insert", on_invoice_created)

    if not event.contains(Payment, "after_insert", on_payment_received):
        event.listen(Payment, "after_insert", on_payment_received)
    if not event.contains(Payment, "after_update", on_payment_received):
        event.listen(Payment, "after_update", on_payment_received)

    if not event.contains(Check, "after_update", on_check_updated):
        event.listen(Check, "after_update", on_check_updated)

    if not event.contains(SupplierSettlement, "after_update", on_supplier_settlement_updated):
        event.listen(SupplierSettlement, "after_update", on_supplier_settlement_updated)
    if not event.contains(PartnerSettlement, "after_update", on_partner_settlement_updated):
        event.listen(PartnerSettlement, "after_update", on_partner_settlement_updated)
    if not event.contains(Expense, "after_insert", on_expense_created):
        event.listen(Expense, "after_insert", on_expense_created)
    if not event.contains(SupplierLoanSettlement, "after_insert", on_supplier_loan_settlement_created):
        event.listen(SupplierLoanSettlement, "after_insert", on_supplier_loan_settlement_created)

    _ALLOCATION_LISTENERS_REGISTERED = True
    logger.info("✅ تم تسجيل مستمعات التوزيع التلقائي")
