"""فحص وإصلاح جودة البيانات — شيكات، دفعات، أرصدة."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import (
    Check,
    Customer,
    Expense,
    Invoice,
    Partner,
    Payment,
    PaymentMethod,
    PaymentSplit,
    Sale,
    ServiceRequest,
    Shipment,
    Supplier,
)


def _cheque_method_filter(column):
    return db.or_(
        column == PaymentMethod.CHEQUE.value,
        column == PaymentMethod.CHEQUE_UPPER.value,
        func.lower(column) == 'cheque',
        func.lower(column) == 'check',
    )


def _resolve_payment_for_check(check):
    payment = None
    ref = (check.reference_number or '').strip()
    if ref.startswith('PMT-SPLIT-'):
        try:
            split_id = int(ref.replace('PMT-SPLIT-', ''))
            split = db.session.get(PaymentSplit, split_id)
            if split:
                payment = split.payment
        except (TypeError, ValueError):
            pass
    elif ref.startswith('SPLIT-'):
        try:
            split_id = int(ref.replace('SPLIT-', ''))
            split = db.session.get(PaymentSplit, split_id)
            if split:
                payment = split.payment
        except (TypeError, ValueError):
            pass
    elif ref.startswith('PMT-'):
        try:
            payment_id = int(ref.replace('PMT-', ''))
            payment = db.session.get(Payment, payment_id)
        except (TypeError, ValueError):
            pass
    if not payment and check.check_number:
        payment = Payment.query.filter(Payment.check_number == check.check_number).first()
    if not payment and check.amount and check.check_date:
        payment = Payment.query.filter(
            Payment.total_amount == check.amount,
            func.date(Payment.payment_date) == check.check_date.date(),
        ).first()
    return payment


def _link_check_entity(check, payment=None):
    payment = payment or _resolve_payment_for_check(check)
    if not payment:
        return False

    if payment.customer_id:
        check.customer_id = payment.customer_id
        return True
    if payment.supplier_id:
        check.supplier_id = payment.supplier_id
        return True
    if payment.partner_id:
        check.partner_id = payment.partner_id
        return True

    if payment.sale_id:
        sale = db.session.get(Sale, payment.sale_id)
        if sale and sale.customer_id:
            check.customer_id = sale.customer_id
            return True
    if payment.invoice_id:
        invoice = db.session.get(Invoice, payment.invoice_id)
        if invoice and invoice.customer_id:
            check.customer_id = invoice.customer_id
            return True
    if payment.service_id:
        service = db.session.get(ServiceRequest, payment.service_id)
        if service and service.customer_id:
            check.customer_id = service.customer_id
            return True
    if payment.shipment_id:
        shipment = db.session.get(Shipment, payment.shipment_id)
        if shipment and shipment.supplier_id:
            check.supplier_id = shipment.supplier_id
            return True
    if payment.expense_id:
        expense = db.session.get(Expense, payment.expense_id)
        if expense and expense.supplier_id:
            check.supplier_id = expense.supplier_id
            return True
    return False


def _count_balance_drift(model, breakdown_fn, limit=300):
    tolerance = Decimal('0.01')
    drift = 0
    scanned = 0
    truncated = False
    query = model.query.order_by(model.id.asc())
    if hasattr(model, 'is_archived'):
        query = query.filter(model.is_archived.is_(False))
    for obj in query:
        if scanned >= limit:
            truncated = True
            break
        scanned += 1
        try:
            breakdown = breakdown_fn(obj.id, db.session)
            if not breakdown or not breakdown.get('success'):
                continue
            expected = Decimal(str(breakdown.get('balance', {}).get('amount', 0)))
            stored = Decimal(str(getattr(obj, 'current_balance', 0) or 0))
            if (expected - stored).copy_abs() > tolerance:
                drift += 1
        except Exception:
            continue
    return drift, truncated


def collect_data_quality_stats(scan_balances=False):
    checks_no_entity = Check.query.filter(
        Check.customer_id.is_(None),
        Check.supplier_id.is_(None),
        Check.partner_id.is_(None),
    ).count()
    checks_no_bank = Check.query.filter(
        db.or_(Check.check_bank.is_(None), Check.check_bank == ''),
    ).count()

    payments_no_bank = Payment.query.filter(
        _cheque_method_filter(Payment.method),
        db.or_(Payment.check_bank.is_(None), Payment.check_bank == ''),
    ).count()
    payments_no_due_date = Payment.query.filter(
        _cheque_method_filter(Payment.method),
        Payment.check_due_date.is_(None),
    ).count()

    customers_null = Customer.query.filter(Customer.current_balance.is_(None)).count()
    suppliers_null = Supplier.query.filter(Supplier.current_balance.is_(None)).count()
    partners_null = Partner.query.filter(Partner.current_balance.is_(None)).count()

    balance_drift = {
        'customers': 0,
        'suppliers': 0,
        'partners': 0,
        'scan_truncated': False,
    }
    if scan_balances:
        from utils.balance_calculator import build_customer_balance_view
        from utils.supplier_balance_updater import build_supplier_balance_view
        from utils.partner_balance_updater import build_partner_balance_view

        for key, model, fn in (
            ('customers', Customer, build_customer_balance_view),
            ('suppliers', Supplier, build_supplier_balance_view),
            ('partners', Partner, build_partner_balance_view),
        ):
            drift, truncated = _count_balance_drift(model, fn)
            balance_drift[key] = drift
            balance_drift['scan_truncated'] = balance_drift['scan_truncated'] or truncated

    stats = {
        'checks': {
            'total': Check.query.count(),
            'no_entity': checks_no_entity,
            'no_bank': checks_no_bank,
        },
        'payments': {
            'total': Payment.query.count(),
            'no_bank': payments_no_bank,
            'no_due_date': payments_no_due_date,
        },
        'balances': {
            'customers_null': customers_null,
            'suppliers_null': suppliers_null,
            'partners_null': partners_null,
            'customers_drift': balance_drift['customers'],
            'suppliers_drift': balance_drift['suppliers'],
            'partners_drift': balance_drift['partners'],
            'scan_truncated': balance_drift['scan_truncated'],
        },
        'entities': {
            'customers': Customer.query.count(),
            'suppliers': Supplier.query.count(),
            'partners': Partner.query.count(),
        },
        'scan_balances': scan_balances,
    }

    total_issues = (
        checks_no_entity + checks_no_bank + payments_no_bank + payments_no_due_date
        + customers_null + suppliers_null + partners_null
    )
    if scan_balances:
        total_issues += (
            balance_drift['customers'] + balance_drift['suppliers'] + balance_drift['partners']
        )
    return stats, total_issues


def fix_data_quality_checks():
    from datetime import timedelta, timezone
    from datetime import datetime

    fixed = 0
    orphan_checks = Check.query.filter(
        Check.customer_id.is_(None),
        Check.supplier_id.is_(None),
        Check.partner_id.is_(None),
    ).all()
    for check in orphan_checks:
        if _link_check_entity(check):
            fixed += 1

    for check in Check.query.filter(db.or_(Check.check_bank.is_(None), Check.check_bank == '')).all():
        payment = _resolve_payment_for_check(check)
        if payment and payment.check_bank:
            check.check_bank = payment.check_bank
            fixed += 1
        elif not (check.check_bank or '').strip():
            check.check_bank = 'غير محدد'
            fixed += 1

    return fixed


def fix_data_quality_payments():
    from datetime import datetime, timedelta, timezone

    fixed = 0
    for payment in Payment.query.filter(_cheque_method_filter(Payment.method)).all():
        changed = False
        if not (payment.check_bank or '').strip():
            check_record = Check.query.filter(
                Check.reference_number == f'PMT-{payment.id}',
            ).first()
            payment.check_bank = (
                check_record.check_bank if check_record and check_record.check_bank
                else 'غير محدد'
            )
            changed = True
        if not payment.check_due_date:
            check_record = Check.query.filter(
                Check.reference_number == f'PMT-{payment.id}',
            ).first()
            payment.check_due_date = (
                check_record.check_due_date if check_record and check_record.check_due_date
                else (payment.payment_date or datetime.now(timezone.utc)) + timedelta(days=30)
            )
            changed = True
        if changed:
            fixed += 1
    return fixed


def fix_data_quality_balances():
    from utils.balance_calculator import build_customer_balance_view
    from utils.customer_balance_updater import update_customer_balance_components
    from utils.supplier_balance_updater import (
        build_supplier_balance_view,
        update_supplier_balance_components,
    )
    from utils.partner_balance_updater import (
        build_partner_balance_view,
        update_partner_balance_components,
    )

    tolerance = Decimal('0.01')
    fixed = 0

    for model in (Customer, Supplier, Partner):
        for row in model.query.filter(model.current_balance.is_(None)).all():
            row.current_balance = 0
            fixed += 1

    groups = (
        (Customer, build_customer_balance_view, update_customer_balance_components),
        (Supplier, build_supplier_balance_view, update_supplier_balance_components),
        (Partner, build_partner_balance_view, update_partner_balance_components),
    )
    for model, breakdown_fn, updater_fn in groups:
        query = model.query.order_by(model.id.asc())
        if hasattr(model, 'is_archived'):
            query = query.filter(model.is_archived.is_(False))
        for obj in query:
            try:
                breakdown = breakdown_fn(obj.id, db.session)
                if not breakdown or not breakdown.get('success'):
                    continue
                expected = Decimal(str(breakdown.get('balance', {}).get('amount', 0)))
                stored = Decimal(str(getattr(obj, 'current_balance', 0) or 0))
                if (expected - stored).copy_abs() > tolerance:
                    updater_fn(obj.id, db.session)
                    fixed += 1
            except Exception:
                continue
    return fixed


def run_data_quality_fix(action):
    fixed = 0
    if action in ('all', 'checks'):
        fixed += fix_data_quality_checks()
    if action in ('all', 'payments'):
        fixed += fix_data_quality_payments()
    if action in ('all', 'balances'):
        fixed += fix_data_quality_balances()
    return fixed
