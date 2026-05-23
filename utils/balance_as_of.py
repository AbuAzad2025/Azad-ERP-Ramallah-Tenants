"""
رصيد الزبون قبل تاريخ — نفس صيغة الرصيد المخزّن (حقوق − التزامات + افتتاحي).
"""
from __future__ import annotations

from decimal import Decimal

from extensions import db
from utils.accounting_formulas import customer_balance_from_components


def _opening_ils(customer) -> Decimal:
    from utils.balance_calculator import convert_amount

    opening = Decimal(str(customer.opening_balance or 0))
    if customer.currency and str(customer.currency).upper() != "ILS":
        try:
            opening = convert_amount(opening, customer.currency, "ILS", customer.created_at)
        except Exception:
            pass
    return opening


def calculate_balance_before_date(customer_id, before_date, session=None) -> Decimal:
    """رصيد تراكمي قبل تاريخ — مطابق لصيغة الرصيد المخزّن."""
    from models import Customer
    from utils.balance_calculator import calculate_customer_balance_components

    if not session:
        session = db.session
    customer = session.get(Customer, customer_id)
    if not customer:
        return Decimal("0.00")

    opening = _opening_ils(customer)
    comp = calculate_customer_balance_components(
        customer_id, session, before_exclusive=before_date
    )
    if not comp:
        return opening
    return customer_balance_from_components(opening, comp)
