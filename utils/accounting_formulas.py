"""
صيغ محاسبية موحّدة: حقوق − التزامات (+ افتتاحي) = الرصيد.

الاتجاه:
- العميل: سالب = عليه لنا، موجب = له عندنا
- المورد/الشريك: موجب = له علينا، سالب = عليه لنا
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0.00")


def customer_rights_total(components: dict) -> Decimal:
    """حقوق العميل (ما يقلّل ما عليه)."""
    return (
        _d(components.get("payments_in_balance"))
        + _d(components.get("returns_balance"))
        + _d(components.get("returned_checks_out_balance"))
        + _d(components.get("service_expenses_balance"))
    )


def customer_obligations_total(components: dict) -> Decimal:
    """التزامات العميل (ذمم — ما عليه)."""
    return (
        _d(components.get("sales_balance"))
        + _d(components.get("invoices_balance"))
        + _d(components.get("services_balance"))
        + _d(components.get("preorders_balance"))
        + _d(components.get("online_orders_balance"))
        + _d(components.get("payments_out_balance"))
        + _d(components.get("returned_checks_in_balance"))
        + _d(components.get("expenses_balance"))
    )


def customer_balance_from_components(opening: Decimal, components: dict) -> Decimal:
    return _d(opening) + customer_rights_total(components) - customer_obligations_total(components)


CUSTOMER_RIGHTS_KEYS = (
    "payments_in_balance",
    "returns_balance",
    "returned_checks_out_balance",
    "service_expenses_balance",
)
CUSTOMER_OBLIGATIONS_KEYS = (
    "sales_balance",
    "invoices_balance",
    "services_balance",
    "preorders_balance",
    "online_orders_balance",
    "payments_out_balance",
    "returned_checks_in_balance",
    "expenses_balance",
)


def supplier_rights_total(components: dict) -> Decimal:
    """حقوق المورد (ما للمورد علينا — دائن المورد)."""
    sale_returns = _d(components.get("sale_returns_from_supplier")) + _d(
        components.get("sale_returns_from_customer")
    )
    return (
        _d(components.get("exchange_items_balance"))
        + _d(components.get("expenses_service_supply"))
        + _d(components.get("expenses_normal"))
        + sale_returns
        + _d(components.get("payments_in_balance"))
        + _d(components.get("returned_checks_out_balance"))
    )


def supplier_obligations_total(components: dict) -> Decimal:
    """التزامات المورد (ما على المورد لنا)."""
    return (
        _d(components.get("returns_balance"))
        + _d(components.get("sales_balance"))
        + _d(components.get("services_balance"))
        + _d(components.get("preorders_balance"))
        + _d(components.get("payments_out_balance"))
        + _d(components.get("returned_checks_in_balance"))
    )


def supplier_balance_from_components(opening: Decimal, components: dict) -> Decimal:
    return _d(opening) + supplier_rights_total(components) - supplier_obligations_total(components)


SUPPLIER_RIGHTS_KEYS = (
    "exchange_items_balance",
    "expenses_service_supply",
    "expenses_normal",
    "sale_returns_from_supplier",
    "sale_returns_from_customer",
    "payments_in_balance",
    "returned_checks_out_balance",
)
SUPPLIER_OBLIGATIONS_KEYS = (
    "returns_balance",
    "sales_balance",
    "services_balance",
    "preorders_balance",
    "payments_out_balance",
    "returned_checks_in_balance",
)


def partner_rights_total(components: dict) -> Decimal:
    """حقوق الشريك (ما للشريك علينا).
    ملاحظة: العربونات مدمجة في payments_in_balance — لا تُجمع preorders_prepaid_balance مرتين.
    """
    return (
        _d(components.get("inventory_balance"))
        + _d(components.get("sales_share_balance"))
        + _d(components.get("shipments_share_balance"))
        + _d(components.get("payments_in_balance"))
        + _d(components.get("service_expenses_balance"))
        + _d(components.get("returned_checks_out_balance"))
    )


def partner_obligations_total(components: dict) -> Decimal:
    """التزامات الشريك (ما على الشريك لنا)."""
    return (
        _d(components.get("sales_to_partner_balance"))
        + _d(components.get("service_fees_balance"))
        + _d(components.get("preorders_to_partner_balance"))
        + _d(components.get("damaged_items_balance"))
        + _d(components.get("payments_out_balance"))
        + _d(components.get("expenses_balance"))
        + _d(components.get("returned_checks_in_balance"))
    )


def partner_balance_from_components(opening: Decimal, components: dict) -> Decimal:
    return _d(opening) + partner_rights_total(components) - partner_obligations_total(components)


PARTNER_RIGHTS_KEYS = (
    "inventory_balance",
    "sales_share_balance",
    "shipments_share_balance",
    "payments_in_balance",
    "service_expenses_balance",
    "returned_checks_out_balance",
)
PARTNER_OBLIGATIONS_KEYS = (
    "sales_to_partner_balance",
    "service_fees_balance",
    "preorders_to_partner_balance",
    "damaged_items_balance",
    "payments_out_balance",
    "expenses_balance",
    "returned_checks_in_balance",
)
