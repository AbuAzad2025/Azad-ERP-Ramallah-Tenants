"""فلترة قيود GL حسب فروع الشركة."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, or_, select

from utils.company_scope import _sale_ids_in_branches, branch_ids_for_company


def resolve_branch_filter(company_id: Optional[int] = None) -> Optional[List[int]]:
    """None = كل الفروع (لمن يملك view_all فقط)، [] = لا شيء، list = فروع."""
    from utils.company_scope import get_report_branch_ids

    return get_report_branch_ids(company_id)


def gl_entries_as_of(branch_filter_ids: Optional[List[int]], as_of_dt: datetime):
    """GLEntry + GLBatch + Account حتى تاريخ معيّن."""
    from models import GLBatch, GLEntry, Account

    q = (
        GLEntry.query.join(GLBatch, GLBatch.id == GLEntry.batch_id)
        .join(Account, Account.code == GLEntry.account)
        .filter(GLBatch.status == "POSTED", GLBatch.posted_at <= as_of_dt)
    )
    if branch_filter_ids is not None:
        if not branch_filter_ids:
            return q.filter(GLEntry.id == -1)
        q = q.filter(gl_batch_branch_clause(branch_filter_ids))
    return q


def gl_batch_branch_clause(branch_ids: List[int]):
    """شرط SQLAlchemy على GLBatch حسب الفرع."""
    from models import GLBatch, Expense, PurchaseOrder, Shipment, Warehouse, Invoice, Sale
    from utils.company_scope import payment_ids_in_branches

    sale_ids = _sale_ids_in_branches(branch_ids)
    pay_ids = payment_ids_in_branches(branch_ids)
    cust_ids = select(Sale.customer_id).filter(
        Sale.id.in_(sale_ids), Sale.customer_id.isnot(None)
    ).distinct()
    invoice_via_sale = select(Invoice.id).filter(
        or_(Invoice.sale_id.in_(sale_ids), Invoice.customer_id.in_(cust_ids))
    )
    expense_ids = select(Expense.id).where(Expense.branch_id.in_(branch_ids))
    po_ids = select(PurchaseOrder.id).where(PurchaseOrder.branch_id.in_(branch_ids))
    ship_ids = (
        select(Shipment.id)
        .join(Warehouse, Warehouse.id == Shipment.destination_id)
        .where(Warehouse.branch_id.in_(branch_ids))
    )
    direct_branch = GLBatch.branch_id.in_(branch_ids)
    inferred = or_(
        and_(GLBatch.source_type == "SALE", GLBatch.source_id.in_(sale_ids)),
        and_(GLBatch.source_type == "INVOICE", GLBatch.source_id.in_(invoice_via_sale)),
        and_(
            GLBatch.source_type.in_(("EXPENSE", "EXPENSE_PAYMENT", "PAYROLL")),
            GLBatch.source_id.in_(expense_ids),
        ),
        and_(GLBatch.source_type == "PURCHASE_ORDER", GLBatch.source_id.in_(po_ids)),
        and_(GLBatch.source_type == "SHIPMENT", GLBatch.source_id.in_(ship_ids)),
        and_(
            GLBatch.source_type.in_(("PAYMENT", "PAYMENT_SPLIT")),
            GLBatch.source_id.in_(pay_ids),
        ),
    )
    return or_(direct_branch, and_(GLBatch.branch_id.is_(None), inferred))


def gl_entries_base(branch_filter_ids: Optional[List[int]], start_dt: datetime, end_dt: datetime):
    """استعلام أساسي: GLEntry + GLBatch + Account مع فترة واختيار فروع."""
    from models import GLBatch, GLEntry, Account

    q = (
        GLEntry.query.join(GLBatch, GLBatch.id == GLEntry.batch_id)
        .join(Account, Account.code == GLEntry.account)
        .filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
        )
    )
    if branch_filter_ids is not None:
        if not branch_filter_ids:
            return q.filter(GLEntry.id == -1)
        q = q.filter(gl_batch_branch_clause(branch_filter_ids))
    return q


def filter_gl_query_on_batch(query, company_id: Optional[int] = None):
    """تطبيق نطاق الفروع على استعلام يحتوي GLBatch."""
    from models import GLBatch

    branch_ids = resolve_branch_filter(company_id)
    if branch_ids is None:
        return query
    if not branch_ids:
        return query.filter(GLBatch.id == -1)
    return query.filter(gl_batch_branch_clause(branch_ids))
