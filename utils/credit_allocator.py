from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models import (
    Customer,
    Invoice,
    Partner,
    PartnerSettlement,
    PartnerSettlementStatus,
    Payment,
    PaymentDirection,
    PaymentEntityType,
    PaymentMethod,
    PaymentSplit,
    PaymentStatus,
    PreOrder,
    Sale,
    ServiceRequest,
    Supplier,
    SupplierLoanSettlement,
    SupplierSettlement,
    SupplierSettlementStatus,
    run_payment_gl_sync_after_commit,
)
from utils import q0


def _dec(v) -> Decimal:
    try:
        return q0(Decimal(str(v or 0)))
    except Exception:
        return Decimal("0")


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _has_check_like(payment: Payment) -> bool:
    try:
        if getattr(payment, "check_number", None) or getattr(payment, "check_bank", None):
            return True
    except Exception:
        pass
    try:
        rc = getattr(payment, "related_check", None)
        if rc is not None:
            try:
                if hasattr(rc, "__len__") and len(rc) > 0:
                    return True
            except Exception:
                try:
                    first = rc.first()
                    if first is not None:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    try:
        for sp in (getattr(payment, "splits", None) or []):
            m = getattr(sp, "method", None)
            m = getattr(m, "value", m)
            m = str(m or "").upper()
            if "CHECK" in m or "CHEQUE" in m:
                return True
    except Exception:
        pass
    return False


def _is_check_cashed(payment: Payment) -> bool:
    if not _has_check_like(payment):
        return True
    try:
        rc = getattr(payment, "related_check", None)
        checks = []
        if rc is None:
            checks = []
        elif isinstance(rc, (list, tuple)):
            checks = list(rc)
        else:
            try:
                checks = list(rc)
            except Exception:
                try:
                    checks = list(rc.all())
                except Exception:
                    try:
                        first = rc.first()
                        checks = [first] if first is not None else []
                    except Exception:
                        checks = []
        if not checks:
            return False
        for ch in checks:
            st = str(getattr(ch, "status", "") or "").upper()
            if st != "CASHED":
                return False
        return True
    except Exception:
        return False


def _convert_amount_or_none(amount, from_code: str | None, to_code: str | None, at: datetime | None) -> Decimal | None:
    f = (from_code or "").upper()
    t = (to_code or "").upper()
    if not f or not t:
        return None
    if f == t:
        return q0(_dec(amount))
    try:
        from models import convert_amount

        try:
            return q0(_dec(convert_amount(q0(_dec(amount)), f, t, at)))
        except Exception:
            if at is None:
                return None
            return q0(_dec(convert_amount(q0(_dec(amount)), f, t, datetime.now(timezone.utc))))
    except Exception:
        return None


def _to_ils(amount, currency: str | None, at: datetime | None) -> Decimal | None:
    c = (currency or "ILS").upper()
    if c == "ILS":
        return q0(_dec(amount))
    return _convert_amount_or_none(amount, c, "ILS", at)


def _from_ils(amount_ils, currency: str | None, at: datetime | None) -> Decimal | None:
    c = (currency or "ILS").upper()
    if c == "ILS":
        return q0(_dec(amount_ils))
    return _convert_amount_or_none(amount_ils, "ILS", c, at)


def _ensure_default_split(payment: Payment) -> None:
    if getattr(payment, "splits", None):
        return
    sp = PaymentSplit(
        payment_id=getattr(payment, "id", None),
        method=getattr(payment.method, "value", payment.method) or PaymentMethod.CASH.value,
        amount=q0(_dec(payment.total_amount)),
        details={"auto_created": True},
        currency=(getattr(payment, "currency", None) or "ILS").upper(),
        converted_amount=q0(_dec(payment.total_amount)),
        converted_currency=(getattr(payment, "currency", None) or "ILS").upper(),
    )
    db.session.add(sp)


def _split_payment_amount(payment: Payment, keep_amount: Decimal) -> Payment | None:
    total = q0(_dec(payment.total_amount))
    keep = q0(_dec(keep_amount))
    if keep <= 0 or keep >= total:
        return None
    if _has_check_like(payment):
        return None

    et_raw = getattr(payment, "entity_type", None)
    et_val = getattr(et_raw, "value", et_raw)
    et = str(et_val or "").upper()

    rem_entity_type = et_val or "CUSTOMER"
    rem_customer_id = getattr(payment, "customer_id", None)
    rem_supplier_id = getattr(payment, "supplier_id", None)
    rem_partner_id = getattr(payment, "partner_id", None)

    if et in ("SALE", "INVOICE", "SERVICE", "PREORDER"):
        cid = None
        try:
            if getattr(payment, "sale_id", None):
                cid = getattr(getattr(payment, "sale", None), "customer_id", None)
            elif getattr(payment, "invoice_id", None):
                cid = getattr(getattr(payment, "invoice", None), "customer_id", None)
            elif getattr(payment, "service_id", None):
                cid = getattr(getattr(payment, "service", None), "customer_id", None)
            elif getattr(payment, "preorder_id", None):
                cid = getattr(getattr(payment, "preorder", None), "customer_id", None)
        except Exception:
            cid = None
        rem_entity_type = PaymentEntityType.CUSTOMER.value
        rem_customer_id = cid
        rem_supplier_id = None
        rem_partner_id = None

    elif et == "LOAN":
        sid = None
        try:
            if getattr(payment, "loan_settlement_id", None):
                sid = getattr(getattr(payment, "loan_settlement", None), "supplier_id", None)
        except Exception:
            sid = None
        rem_entity_type = PaymentEntityType.SUPPLIER.value
        rem_supplier_id = sid
        rem_customer_id = None
        rem_partner_id = None

    elif et == "EXPENSE":
        cid = None
        sid = None
        pid = None
        try:
            exp = getattr(payment, "expense", None)
            if exp is not None:
                cid = getattr(exp, "customer_id", None)
                sid = getattr(exp, "supplier_id", None)
                pid = getattr(exp, "partner_id", None)
        except Exception:
            pass
        if cid:
            rem_entity_type = PaymentEntityType.CUSTOMER.value
            rem_customer_id = cid
            rem_supplier_id = None
            rem_partner_id = None
        elif sid:
            rem_entity_type = PaymentEntityType.SUPPLIER.value
            rem_supplier_id = sid
            rem_customer_id = None
            rem_partner_id = None
        elif pid:
            rem_entity_type = PaymentEntityType.PARTNER.value
            rem_partner_id = pid
            rem_customer_id = None
            rem_supplier_id = None
        else:
            rem_entity_type = PaymentEntityType.OTHER.value
            rem_customer_id = None
            rem_supplier_id = None
            rem_partner_id = None

    remainder_amount = q0(total - keep)
    remainder = Payment(
        entity_type=rem_entity_type,
        customer_id=rem_customer_id,
        supplier_id=rem_supplier_id,
        partner_id=rem_partner_id,
        direction=payment.direction,
        status=payment.status,
        payment_date=payment.payment_date,
        total_amount=remainder_amount,
        currency=payment.currency,
        method=payment.method,
        reference=payment.reference,
        receipt_number=None,
        notes=payment.notes,
        deliverer_name=getattr(payment, "deliverer_name", None),
        receiver_name=getattr(payment, "receiver_name", None),
        created_by=getattr(payment, "created_by", None),
    )
    db.session.add(remainder)
    db.session.flush()

    splits = list(getattr(payment, "splits", None) or [])
    if not splits:
        _ensure_default_split(payment)
        db.session.flush()
        splits = list(getattr(payment, "splits", None) or [])

    ratio = keep / total if total > 0 else Decimal("0")
    for sp in splits:
        sp_amt = q0(_dec(getattr(sp, "amount", 0)))
        sp_conv = q0(_dec(getattr(sp, "converted_amount", sp_amt)))
        keep_sp_amt = q0(sp_amt * ratio)
        keep_sp_conv = q0(sp_conv * ratio)
        rem_sp_amt = q0(sp_amt - keep_sp_amt)
        rem_sp_conv = q0(sp_conv - keep_sp_conv)

        sp.amount = keep_sp_amt
        sp.converted_amount = keep_sp_conv
        db.session.add(sp)

        if rem_sp_amt > 0:
            rsp = PaymentSplit(
                payment_id=remainder.id,
                method=getattr(sp.method, "value", sp.method),
                amount=rem_sp_amt,
                details=(sp.details or {}),
                currency=sp.currency,
                converted_amount=rem_sp_conv,
                converted_currency=getattr(sp, "converted_currency", None) or sp.currency,
                fx_rate_used=getattr(sp, "fx_rate_used", None),
                fx_rate_source=getattr(sp, "fx_rate_source", None),
                fx_rate_timestamp=getattr(sp, "fx_rate_timestamp", None),
                fx_base_currency=getattr(sp, "fx_base_currency", None),
                fx_quote_currency=getattr(sp, "fx_quote_currency", None),
            )
            db.session.add(rsp)

    payment.total_amount = keep
    db.session.add(payment)
    return remainder


def _open_customer_obligations(customer_id: int):
    obligations = []

    try:
        rows = (
            ServiceRequest.query.filter(
                ServiceRequest.customer_id == customer_id,
                ServiceRequest.is_archived == False,
                ServiceRequest.cancelled_at.is_(None),
                ServiceRequest.balance_due > 0.01,
            )
            .order_by(ServiceRequest.received_at.asc(), ServiceRequest.id.asc())
            .all()
        )
        for r in rows:
            dtv = getattr(r, "received_at", None) or getattr(r, "created_at", None)
            obligations.append(("SERVICE", dtv, r.id, q0(_dec(getattr(r, "balance_due", 0))), (getattr(r, "currency", None) or "ILS").upper()))
    except Exception:
        pass

    try:
        rows = (
            PreOrder.query.filter(
                PreOrder.customer_id == customer_id,
                PreOrder.cancelled_at.is_(None),
                PreOrder.balance_due > 0.01,
            )
            .order_by(PreOrder.preorder_date.asc(), PreOrder.id.asc())
            .all()
        )
        for r in rows:
            dtv = getattr(r, "preorder_date", None) or getattr(r, "created_at", None)
            obligations.append(("PREORDER", dtv, r.id, q0(_dec(getattr(r, "balance_due", 0))), (getattr(r, "currency", None) or "ILS").upper()))
    except Exception:
        pass

    try:
        rows = (
            Sale.query.filter(
                Sale.customer_id == customer_id,
                Sale.balance_due > 0.01,
                Sale.is_archived == False,
                Sale.cancelled_at.is_(None),
            )
            .order_by(Sale.sale_date.asc(), Sale.id.asc())
            .all()
        )
        for r in rows:
            dtv = getattr(r, "sale_date", None)
            obligations.append(("SALE", dtv, r.id, q0(_dec(getattr(r, "balance_due", 0))), (getattr(r, "currency", None) or "ILS").upper()))
    except Exception:
        pass

    try:
        rows = (
            Invoice.query.filter(
                Invoice.customer_id == customer_id,
                Invoice.cancelled_at.is_(None),
                (Invoice.total_amount - Invoice.total_paid) > 0.01,
                Invoice.sale_id.is_(None),
                Invoice.service_id.is_(None),
                Invoice.preorder_id.is_(None),
            )
            .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
            .all()
        )
        for r in rows:
            dtv = getattr(r, "invoice_date", None)
            due = q0(_dec(getattr(r, "total_amount", 0)) - _dec(getattr(r, "total_paid", 0)))
            obligations.append(("INVOICE", dtv, r.id, due, (getattr(r, "currency", None) or "ILS").upper()))
    except Exception:
        pass

    obligations = [o for o in obligations if o[3] > 0]
    obligations.sort(key=lambda x: (x[1] or datetime.min.replace(tzinfo=None), x[0], x[2]))
    return obligations


def apply_customer_credit_to_obligations(customer_id: int, *, created_by: int | None = None) -> list[int]:
    try:
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if not payment_auto_allocate_enabled():
            return []
    except Exception:
        return []
    if not customer_id:
        return []

    touched_payment_ids: list[int] = []

    customer = db.session.get(Customer, int(customer_id))
    if not customer:
        return []

    obligations = _open_customer_obligations(int(customer_id))
    if not obligations:
        return []

    credit_payments: list[Payment] = []

    credit_payments.extend(
        Payment.query.filter(
            Payment.customer_id == int(customer_id),
            Payment.direction == PaymentDirection.IN.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
            Payment.service_id.is_(None),
            Payment.preorder_id.is_(None),
            Payment.expense_id.is_(None),
            Payment.shipment_id.is_(None),
            Payment.supplier_id.is_(None),
            Payment.partner_id.is_(None),
            Payment.loan_settlement_id.is_(None),
            Payment.is_archived == False,
        )
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )

    credit_payments.extend(
        Payment.query.join(Supplier, Supplier.id == Payment.supplier_id)
        .filter(
            Supplier.customer_id == int(customer_id),
            Payment.customer_id.is_(None),
            Payment.direction == PaymentDirection.IN.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
            Payment.service_id.is_(None),
            Payment.preorder_id.is_(None),
            Payment.expense_id.is_(None),
            Payment.shipment_id.is_(None),
            Payment.partner_id.is_(None),
            Payment.loan_settlement_id.is_(None),
            Payment.is_archived == False,
        )
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )

    credit_payments.extend(
        Payment.query.join(Partner, Partner.id == Payment.partner_id)
        .filter(
            Partner.customer_id == int(customer_id),
            Payment.customer_id.is_(None),
            Payment.direction == PaymentDirection.IN.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
            Payment.service_id.is_(None),
            Payment.preorder_id.is_(None),
            Payment.expense_id.is_(None),
            Payment.shipment_id.is_(None),
            Payment.supplier_id.is_(None),
            Payment.loan_settlement_id.is_(None),
            Payment.is_archived == False,
        )
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )

    credit_payments.sort(key=lambda p: (getattr(p, "payment_date", None) or datetime.min.replace(tzinfo=None), int(getattr(p, "id", 0) or 0)))
    credit_payments = [p for p in credit_payments if _is_check_cashed(p)]

    def _assign_payment(p: Payment, kind: str, oid: int):
        p.customer_id = None
        p.supplier_id = None
        p.partner_id = None
        if kind == "SALE":
            p.sale_id = oid
            p.entity_type = "SALE"
        elif kind == "SERVICE":
            p.service_id = oid
            p.entity_type = "SERVICE"
        elif kind == "PREORDER":
            p.preorder_id = oid
            p.entity_type = "PREORDER"
        else:
            p.invoice_id = oid
            p.entity_type = "INVOICE"
        db.session.add(p)

    for kind, odt, oid, due, ocur in obligations:
        remaining_due_ils = _to_ils(due, ocur, odt) or Decimal("0")
        while remaining_due_ils > Decimal("0.01") and credit_payments:
            p = credit_payments[0]
            amt = q0(_dec(p.total_amount))
            if amt <= 0:
                credit_payments.pop(0)
                continue
            pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if pay_ils is None or pay_ils <= 0:
                credit_payments.pop(0)
                continue
            if pay_ils <= remaining_due_ils + Decimal("0.0001"):
                _assign_payment(p, kind, int(oid))
                touched_payment_ids.append(int(p.id))
                credit_payments.pop(0)
                remaining_due_ils = q0(remaining_due_ils - pay_ils)
                continue

            if _has_check_like(p):
                break

            keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if keep_amt is None:
                break
            remainder = _split_payment_amount(p, keep_amt)
            _assign_payment(p, kind, int(oid))
            touched_payment_ids.append(int(p.id))
            if remainder is not None:
                credit_payments[0] = remainder
            else:
                credit_payments.pop(0)
            remaining_due_ils = Decimal("0")

    opening_credit = q0(_dec(getattr(customer, "opening_balance", 0)))
    if opening_credit > 0 and (getattr(customer, "currency", "ILS") or "ILS").upper() == "ILS":
        for kind, _dtv, oid, due, _cur in obligations:
            if opening_credit <= 0:
                break
            need = q0(_dec(due))
            if need <= 0:
                continue
            apply_amt = need if need <= opening_credit else q0(opening_credit)
            if apply_amt <= 0:
                continue

            p = Payment(
                direction=PaymentDirection.IN.value,
                status=PaymentStatus.COMPLETED.value,
                payment_date=_now_naive(),
                total_amount=apply_amt,
                currency="ILS",
                method=PaymentMethod.BANK.value,
                reference="تسديد من رصيد سابق",
                notes="[CREDIT_APPLIED=true]",
                created_by=created_by,
            )
            p._skip_gl_entry = True
            if kind == "SALE":
                p.entity_type = "SALE"
                p.sale_id = int(oid)
            elif kind == "SERVICE":
                p.entity_type = "SERVICE"
                p.service_id = int(oid)
            elif kind == "PREORDER":
                p.entity_type = "PREORDER"
                p.preorder_id = int(oid)
            else:
                p.entity_type = "INVOICE"
                p.invoice_id = int(oid)
            db.session.add(p)
            db.session.flush()
            sp = PaymentSplit(
                payment_id=p.id,
                method=p.method,
                amount=apply_amt,
                details={"credit_applied": True},
                currency="ILS",
                converted_amount=apply_amt,
                converted_currency="ILS",
            )
            db.session.add(sp)
            touched_payment_ids.append(int(p.id))
            opening_credit = q0(opening_credit - apply_amt)

        customer.opening_balance = opening_credit
        db.session.add(customer)

    db.session.commit()
    for pid in touched_payment_ids:
        try:
            run_payment_gl_sync_after_commit(int(pid))
        except Exception:
            pass
    return touched_payment_ids


def apply_supplier_out_payments_to_obligations(supplier_id: int) -> list[int]:
    if not supplier_id:
        return []

    touched_payment_ids: list[int] = []

    payments = (
        Payment.query.filter(
            Payment.supplier_id == int(supplier_id),
            Payment.direction == PaymentDirection.OUT.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.customer_id.is_(None),
            Payment.partner_id.is_(None),
            Payment.shipment_id.is_(None),
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
            Payment.preorder_id.is_(None),
            Payment.service_id.is_(None),
            Payment.expense_id.is_(None),
            Payment.loan_settlement_id.is_(None),
            Payment.is_archived == False,
        )
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )
    payments = [p for p in payments if _is_check_cashed(p)]

    def _ref_is_settlement(p: Payment) -> bool:
        r = str(getattr(p, "reference", "") or "")
        return r.startswith("SupplierSettle:")

    payments = [p for p in payments if not _ref_is_settlement(p)]
    if not payments:
        return []

    settlements = (
        SupplierSettlement.query.filter(
            SupplierSettlement.supplier_id == int(supplier_id),
            SupplierSettlement.status == SupplierSettlementStatus.CONFIRMED.value,
        )
        .order_by(SupplierSettlement.from_date.asc(), SupplierSettlement.id.asc())
        .all()
    )

    def _settlement_remaining(s: SupplierSettlement) -> Decimal:
        try:
            due = q0(_dec(getattr(s, "total_due", 0)))
            paid = q0(_dec(getattr(s, "total_paid", 0)))
            return q0(due - paid)
        except Exception:
            return Decimal("0")

    def _assign_to_settlement(p: Payment, s: SupplierSettlement) -> None:
        p.entity_type = PaymentEntityType.SUPPLIER.value
        p.reference = f"SupplierSettle:{getattr(s, 'code', '')}"
        db.session.add(p)

    for s in settlements:
        remaining_due_cur = _settlement_remaining(s)
        if remaining_due_cur <= Decimal("0.01"):
            continue
        settlement_currency = (getattr(s, "currency", None) or "ILS").upper()
        remaining_due_ils = _to_ils(remaining_due_cur, settlement_currency, getattr(s, "created_at", None)) or Decimal("0")
        if remaining_due_ils <= Decimal("0.01"):
            continue

        while remaining_due_ils > Decimal("0.01") and payments:
            p = payments[0]
            amt = q0(_dec(p.total_amount))
            if amt <= 0:
                payments.pop(0)
                continue
            pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if pay_ils is None or pay_ils <= 0:
                payments.pop(0)
                continue
            if pay_ils <= remaining_due_ils + Decimal("0.0001"):
                _assign_to_settlement(p, s)
                touched_payment_ids.append(int(p.id))
                payments.pop(0)
                remaining_due_ils = q0(remaining_due_ils - pay_ils)
                continue

            if _has_check_like(p):
                break
            keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if keep_amt is None:
                break
            remainder = _split_payment_amount(p, keep_amt)
            _assign_to_settlement(p, s)
            touched_payment_ids.append(int(p.id))
            if remainder is not None:
                payments[0] = remainder
            else:
                payments.pop(0)
            remaining_due_ils = Decimal("0")

    loan_settlements = (
        SupplierLoanSettlement.query.filter(
            SupplierLoanSettlement.supplier_id == int(supplier_id),
        )
        .order_by(SupplierLoanSettlement.settlement_date.asc(), SupplierLoanSettlement.id.asc())
        .all()
    )
    if payments and loan_settlements:
        existing_linked_ids = {
            int(pid)
            for (pid,) in db.session.query(Payment.loan_settlement_id)
            .join(SupplierLoanSettlement, SupplierLoanSettlement.id == Payment.loan_settlement_id)
            .filter(
                SupplierLoanSettlement.supplier_id == int(supplier_id),
                Payment.loan_settlement_id.isnot(None),
                Payment.is_archived == False,
            )
            .distinct()
            .all()
            if pid is not None
        }

        for ls in loan_settlements:
            if not payments:
                break
            lsid = int(getattr(ls, "id", 0) or 0)
            if not lsid or lsid in existing_linked_ids:
                continue
            remaining_due_cur = q0(_dec(getattr(ls, "settled_price", 0)))
            if remaining_due_cur <= Decimal("0.01"):
                continue
            loan_currency = (getattr(ls, "supplier", None) and getattr(ls.supplier, "currency", None)) or "ILS"
            loan_currency = (loan_currency or "ILS").upper()
            remaining_due_ils = _to_ils(remaining_due_cur, loan_currency, getattr(ls, "settlement_date", None)) or Decimal("0")
            if remaining_due_ils <= Decimal("0.01"):
                continue

            p = payments[0]
            amt = q0(_dec(p.total_amount))
            pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if pay_ils is None or pay_ils <= 0:
                continue
            if pay_ils + Decimal("0.0001") < remaining_due_ils:
                continue
            if pay_ils > remaining_due_ils + Decimal("0.0001"):
                if _has_check_like(p):
                    continue
                keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
                if keep_amt is None:
                    continue
                remainder = _split_payment_amount(p, keep_amt)
                p.loan_settlement_id = lsid
                p.entity_type = PaymentEntityType.LOAN.value
                p.supplier_id = None
                db.session.add(p)
                touched_payment_ids.append(int(p.id))
                if remainder is not None:
                    payments[0] = remainder
                else:
                    payments.pop(0)
            else:
                p.loan_settlement_id = lsid
                p.entity_type = PaymentEntityType.LOAN.value
                p.supplier_id = None
                db.session.add(p)
                touched_payment_ids.append(int(p.id))
                payments.pop(0)

    if payments:
        from models import Expense

        expenses = (
            Expense.query.filter(
                Expense.supplier_id == int(supplier_id),
                Expense.is_paid == False,
            )
            .order_by(Expense.date.asc(), Expense.id.asc())
            .all()
        )
        for exp in expenses:
            if not payments:
                break
            exp_currency = (getattr(exp, "currency", None) or "ILS").upper()
            remaining_due_cur = q0(_dec(getattr(exp, "amount", 0)) - _dec(getattr(exp, "total_paid", 0)))
            if remaining_due_cur <= Decimal("0.01"):
                continue
            remaining_due_ils = _to_ils(remaining_due_cur, exp_currency, getattr(exp, "date", None)) or Decimal("0")
            if remaining_due_ils <= Decimal("0.01"):
                continue

            while remaining_due_ils > Decimal("0.01") and payments:
                p = payments[0]
                amt = q0(_dec(p.total_amount))
                if amt <= 0:
                    payments.pop(0)
                    continue
                pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
                if pay_ils is None or pay_ils <= 0:
                    payments.pop(0)
                    continue
                if pay_ils <= remaining_due_ils + Decimal("0.0001"):
                    p.expense_id = int(exp.id)
                    p.entity_type = PaymentEntityType.EXPENSE.value
                    p.supplier_id = None
                    db.session.add(p)
                    touched_payment_ids.append(int(p.id))
                    payments.pop(0)
                    remaining_due_ils = q0(remaining_due_ils - pay_ils)
                    continue

                if _has_check_like(p):
                    break
                keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
                if keep_amt is None:
                    break
                remainder = _split_payment_amount(p, keep_amt)
                p.expense_id = int(exp.id)
                p.entity_type = PaymentEntityType.EXPENSE.value
                p.supplier_id = None
                db.session.add(p)
                touched_payment_ids.append(int(p.id))
                if remainder is not None:
                    payments[0] = remainder
                else:
                    payments.pop(0)
                remaining_due_ils = Decimal("0")

    if touched_payment_ids:
        db.session.commit()
        for pid in touched_payment_ids:
            try:
                run_payment_gl_sync_after_commit(int(pid))
            except Exception:
                pass
    return touched_payment_ids


def apply_partner_out_payments_to_obligations(partner_id: int) -> list[int]:
    if not partner_id:
        return []

    touched_payment_ids: list[int] = []

    payments = (
        Payment.query.filter(
            Payment.partner_id == int(partner_id),
            Payment.direction == PaymentDirection.OUT.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.customer_id.is_(None),
            Payment.supplier_id.is_(None),
            Payment.shipment_id.is_(None),
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
            Payment.preorder_id.is_(None),
            Payment.service_id.is_(None),
            Payment.expense_id.is_(None),
            Payment.loan_settlement_id.is_(None),
            Payment.is_archived == False,
        )
        .order_by(Payment.payment_date.asc(), Payment.id.asc())
        .all()
    )
    payments = [p for p in payments if _is_check_cashed(p)]

    def _ref_is_settlement(p: Payment) -> bool:
        r = str(getattr(p, "reference", "") or "")
        return r.startswith("PartnerSettle:")

    payments = [p for p in payments if not _ref_is_settlement(p)]
    if not payments:
        return []

    settlements = (
        PartnerSettlement.query.filter(
            PartnerSettlement.partner_id == int(partner_id),
            PartnerSettlement.status == PartnerSettlementStatus.CONFIRMED.value,
        )
        .order_by(PartnerSettlement.from_date.asc(), PartnerSettlement.id.asc())
        .all()
    )

    def _settlement_remaining(s: PartnerSettlement) -> Decimal:
        try:
            due = q0(_dec(getattr(s, "total_due", 0)))
            paid = q0(_dec(getattr(s, "total_paid", 0)))
            return q0(due - paid)
        except Exception:
            return Decimal("0")

    def _assign_to_settlement(p: Payment, s: PartnerSettlement) -> None:
        p.entity_type = PaymentEntityType.PARTNER.value
        p.reference = f"PartnerSettle:{getattr(s, 'code', '')}"
        db.session.add(p)

    for s in settlements:
        remaining_due_cur = _settlement_remaining(s)
        if remaining_due_cur <= Decimal("0.01"):
            continue
        settlement_currency = (getattr(s, "currency", None) or "ILS").upper()
        remaining_due_ils = _to_ils(remaining_due_cur, settlement_currency, getattr(s, "created_at", None)) or Decimal("0")
        if remaining_due_ils <= Decimal("0.01"):
            continue
        while remaining_due_ils > Decimal("0.01") and payments:
            p = payments[0]
            amt = q0(_dec(p.total_amount))
            if amt <= 0:
                payments.pop(0)
                continue
            pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if pay_ils is None or pay_ils <= 0:
                payments.pop(0)
                continue
            if pay_ils <= remaining_due_ils + Decimal("0.0001"):
                _assign_to_settlement(p, s)
                touched_payment_ids.append(int(p.id))
                payments.pop(0)
                remaining_due_ils = q0(remaining_due_ils - pay_ils)
                continue

            if _has_check_like(p):
                break
            keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
            if keep_amt is None:
                break
            remainder = _split_payment_amount(p, keep_amt)
            _assign_to_settlement(p, s)
            touched_payment_ids.append(int(p.id))
            if remainder is not None:
                payments[0] = remainder
            else:
                payments.pop(0)
            remaining_due_ils = Decimal("0")

    if payments:
        from models import Expense

        expenses = (
            Expense.query.filter(
                Expense.partner_id == int(partner_id),
                Expense.is_paid == False,
            )
            .order_by(Expense.date.asc(), Expense.id.asc())
            .all()
        )
        for exp in expenses:
            if not payments:
                break
            exp_currency = (getattr(exp, "currency", None) or "ILS").upper()
            remaining_due_cur = q0(_dec(getattr(exp, "amount", 0)) - _dec(getattr(exp, "total_paid", 0)))
            if remaining_due_cur <= Decimal("0.01"):
                continue
            remaining_due_ils = _to_ils(remaining_due_cur, exp_currency, getattr(exp, "date", None)) or Decimal("0")
            if remaining_due_ils <= Decimal("0.01"):
                continue

            while remaining_due_ils > Decimal("0.01") and payments:
                p = payments[0]
                amt = q0(_dec(p.total_amount))
                if amt <= 0:
                    payments.pop(0)
                    continue
                pay_ils = _to_ils(amt, getattr(p, "currency", None), getattr(p, "payment_date", None))
                if pay_ils is None or pay_ils <= 0:
                    payments.pop(0)
                    continue
                if pay_ils <= remaining_due_ils + Decimal("0.0001"):
                    p.expense_id = int(exp.id)
                    p.entity_type = PaymentEntityType.EXPENSE.value
                    p.partner_id = None
                    db.session.add(p)
                    touched_payment_ids.append(int(p.id))
                    payments.pop(0)
                    remaining_due_ils = q0(remaining_due_ils - pay_ils)
                    continue

                if _has_check_like(p):
                    break
                keep_amt = _from_ils(remaining_due_ils, getattr(p, "currency", None), getattr(p, "payment_date", None))
                if keep_amt is None:
                    break
                remainder = _split_payment_amount(p, keep_amt)
                p.expense_id = int(exp.id)
                p.entity_type = PaymentEntityType.EXPENSE.value
                p.partner_id = None
                db.session.add(p)
                touched_payment_ids.append(int(p.id))
                if remainder is not None:
                    payments[0] = remainder
                else:
                    payments.pop(0)
                remaining_due_ils = Decimal("0")

    if touched_payment_ids:
        db.session.commit()
        for pid in touched_payment_ids:
            try:
                run_payment_gl_sync_after_commit(int(pid))
            except Exception:
                pass
    return touched_payment_ids
