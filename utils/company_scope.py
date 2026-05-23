"""نطاق الشركة/الفرع داخل تينانت SaaS — عزل تطبيقي على مستوى schema الحالي."""
from __future__ import annotations

from typing import List, Optional

from flask import abort
from flask_login import current_user
from sqlalchemy import and_, or_, select


def can_view_all_branches() -> bool:
    try:
        import utils

        if utils.is_super():
            return True
    except Exception:
        pass
    try:
        u = current_user
        if not u or not getattr(u, "is_authenticated", False):
            return False
        if getattr(u, "is_system_account", False):
            return True
        fn = getattr(u, "has_permission", None)
        if callable(fn) and fn("view_all_branches"):
            return True
    except Exception:
        pass
    return False


def get_accessible_branch_ids() -> Optional[List[int]]:
    if can_view_all_branches():
        return None
    try:
        u = current_user
        if not u or not getattr(u, "is_authenticated", False):
            return []
        links = getattr(u, "user_branches", None) or []
        ids = [int(ub.branch_id) for ub in links if getattr(ub, "branch_id", None)]
        return ids or []
    except Exception:
        return []


def get_report_branch_ids(company_id: Optional[int] = None) -> Optional[List[int]]:
    if company_id:
        return branch_ids_for_company(company_id)
    return get_accessible_branch_ids()


def get_accessible_company_ids() -> Optional[List[int]]:
    from extensions import db
    from models import Branch

    branch_ids = get_accessible_branch_ids()
    if branch_ids is None:
        return None
    if not branch_ids:
        return []
    rows = (
        db.session.query(Branch.company_id)
        .filter(Branch.id.in_(branch_ids), Branch.company_id.isnot(None))
        .distinct()
        .all()
    )
    return list({int(r[0]) for r in rows if r[0]})


def branch_ids_for_company(company_id: Optional[int]) -> Optional[List[int]]:
    from models import Branch

    if not company_id:
        return get_accessible_branch_ids()
    q = Branch.query.filter_by(company_id=int(company_id), is_active=True)
    allowed = get_accessible_branch_ids()
    if allowed is not None:
        q = q.filter(Branch.id.in_(allowed))
    return [b.id for b in q.all()]


def filter_by_branches(query, branch_column):
    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        return query.filter(branch_column == -1)
    return query.filter(branch_column.in_(ids))


def filter_branches_query(query):
    from models import Branch

    co_ids = get_accessible_company_ids()
    if co_ids is None:
        return query
    if not co_ids:
        return query.filter(Branch.id == -1)
    return query.filter(Branch.company_id.in_(co_ids))


def filter_companies_query(query):
    from models import Company

    co_ids = get_accessible_company_ids()
    if co_ids is None:
        return query
    if not co_ids:
        return query.filter(Company.id == -1)
    return query.filter(Company.id.in_(co_ids))


def filter_warehouses_query(query):
    from models import Warehouse

    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        return query.filter(Warehouse.id == -1)
    return query.filter(Warehouse.branch_id.in_(ids))


def _sale_ids_in_branches(branch_ids: List[int]):
    from extensions import db
    from models import SaleLine, Warehouse

    return (
        db.session.query(SaleLine.sale_id)
        .join(Warehouse, Warehouse.id == SaleLine.warehouse_id)
        .filter(Warehouse.branch_id.in_(branch_ids), SaleLine.sale_id.isnot(None))
        .distinct()
    )


def filter_sales_query(query):
    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Sale

        return query.filter(Sale.id == -1)
    from models import Sale

    sub = _sale_ids_in_branches(ids).subquery()
    return query.filter(Sale.id.in_(select(sub.c.sale_id)))


def payment_ids_in_branches(branch_ids: List[int]):
    from models import Payment, Sale, Shipment, Warehouse, Expense

    sale_sub = _sale_ids_in_branches(branch_ids).subquery()
    shipment_branch = (
        select(Shipment.id)
        .join(Warehouse, Warehouse.id == Shipment.destination_id)
        .where(Warehouse.branch_id.in_(branch_ids))
    )
    customer_in_branch = (
        select(Sale.customer_id)
        .filter(Sale.id.in_(select(sale_sub.c.sale_id)), Sale.customer_id.isnot(None))
        .distinct()
    )
    clauses = [
        Payment.sale_id.in_(select(sale_sub.c.sale_id)),
        Payment.expense.has(Expense.branch_id.in_(branch_ids)),
        Payment.shipment_id.in_(shipment_branch),
        and_(
            Payment.customer_id.isnot(None),
            Payment.customer_id.in_(customer_in_branch),
            Payment.sale_id.is_(None),
            Payment.invoice_id.is_(None),
        ),
    ]
    return select(Payment.id).where(or_(*clauses))


def filter_payments_query(query):
    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Payment

        return query.filter(Payment.id == -1)
    from models import Payment

    return query.filter(Payment.id.in_(payment_ids_in_branches(ids)))


def filter_expenses_query(query):
    from models import Expense

    return filter_by_branches(query, Expense.branch_id)


def assert_expense_access(expense_id: int):
    from models import Expense

    exp = Expense.query.get_or_404(expense_id)
    ids = get_accessible_branch_ids()
    if ids is None:
        return exp
    bid = getattr(exp, "branch_id", None)
    if not bid or int(bid) not in ids:
        abort(403)
    return exp


def filter_shipments_query(query):
    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Shipment

        return query.filter(Shipment.id == -1)
    from models import Shipment, Warehouse

    wh_ids = select(Warehouse.id).where(Warehouse.branch_id.in_(ids))
    return query.filter(Shipment.destination_id.in_(wh_ids))


def filter_service_requests_query(query):
    from extensions import db
    from models import ServiceRequest, ServicePart, Warehouse

    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        return query.filter(ServiceRequest.id == -1)
    sr_via_parts = (
        db.session.query(ServicePart.service_id)
        .join(Warehouse, Warehouse.id == ServicePart.warehouse_id)
        .filter(Warehouse.branch_id.in_(ids), ServicePart.service_id.isnot(None))
        .distinct()
    )
    return query.filter(ServiceRequest.id.in_(sr_via_parts))


def filter_sale_returns_query(query):
    from models import SaleReturn

    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        return query.filter(SaleReturn.id == -1)
    sale_ids = _sale_ids_in_branches(ids)
    return query.filter(SaleReturn.sale_id.in_(sale_ids))


def filter_customers_query(query, branch_ids: Optional[List[int]] = None):
    ids = branch_ids if branch_ids is not None else get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Customer

        return query.filter(Customer.id == -1)
    from extensions import db
    from models import Customer, Sale, Payment

    sale_customer_ids = (
        db.session.query(Sale.customer_id)
        .filter(Sale.id.in_(_sale_ids_in_branches(ids)), Sale.customer_id.isnot(None))
        .distinct()
    )
    payment_customer_ids = (
        db.session.query(Payment.customer_id)
        .filter(Payment.id.in_(payment_ids_in_branches(ids)), Payment.customer_id.isnot(None))
        .distinct()
    )
    return query.filter(
        or_(
            Customer.id.in_(sale_customer_ids),
            Customer.id.in_(payment_customer_ids),
        )
    )


def filter_suppliers_query(query, branch_ids: Optional[List[int]] = None):
    ids = branch_ids if branch_ids is not None else get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Supplier

        return query.filter(Supplier.id == -1)
    from models import Supplier, Expense

    exp_supplier_ids = (
        select(Expense.supplier_id)
        .where(Expense.branch_id.in_(ids), Expense.supplier_id.isnot(None))
        .distinct()
    )
    return query.filter(Supplier.id.in_(exp_supplier_ids))


def payment_id_in_accessible_branches(payment_id: int) -> bool:
    from extensions import db
    from models import Payment

    ids = get_accessible_branch_ids()
    if ids is None:
        return True
    if not ids:
        return False
    return bool(
        db.session.query(
            payment_ids_in_branches(ids).where(Payment.id == int(payment_id)).exists()
        ).scalar()
    )


def assert_supplier_access(supplier_id: int) -> None:
    from models import Supplier

    if filter_suppliers_query(Supplier.query.filter_by(id=int(supplier_id))).first() is None:
        abort(404)


def assert_partner_access(partner_id: int) -> None:
    from models import Partner

    if filter_partners_query(Partner.query.filter_by(id=int(partner_id))).first() is None:
        abort(404)


def filter_checks_query(query):
    """شيكات مرتبطة بدفعات/زبائن/موردين/شركاء ضمن نطاق الفروع."""
    from models import Check, Customer, Partner, Supplier

    ids = get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        return query.filter(Check.id == -1)
    pay_ids = payment_ids_in_branches(ids)
    cust_ids = filter_customers_query(Customer.query.with_entities(Customer.id))
    sup_ids = filter_suppliers_query(Supplier.query.with_entities(Supplier.id))
    part_ids = filter_partners_query(Partner.query.with_entities(Partner.id))
    return query.filter(
        or_(
            Check.payment_id.in_(pay_ids),
            Check.customer_id.in_(cust_ids),
            Check.supplier_id.in_(sup_ids),
            Check.partner_id.in_(part_ids),
        )
    )


def filter_partners_query(query, branch_ids: Optional[List[int]] = None):
    ids = branch_ids if branch_ids is not None else get_accessible_branch_ids()
    if ids is None:
        return query
    if not ids:
        from models import Partner

        return query.filter(Partner.id == -1)
    from models import Partner, Expense

    partner_ids = (
        select(Expense.partner_id)
        .where(Expense.branch_id.in_(ids), Expense.partner_id.isnot(None))
        .distinct()
    )
    return query.filter(Partner.id.in_(partner_ids))


def sale_id_in_accessible_branches(sale_id: int) -> bool:
    ids = get_accessible_branch_ids()
    if ids is None:
        return True
    if not ids:
        return False
    from extensions import db
    from models import SaleLine

    q = _sale_ids_in_branches(ids).filter(SaleLine.sale_id == int(sale_id))
    return bool(db.session.query(q.exists()).scalar())


def assert_sale_access(sale_id: int) -> None:
    if not sale_id_in_accessible_branches(int(sale_id)):
        abort(404)


def assert_sale_return_access(return_id: int) -> None:
    from models import SaleReturn

    sr = SaleReturn.query.filter_by(id=int(return_id)).first()
    if not sr:
        abort(404)
    if sr.sale_id:
        assert_sale_access(int(sr.sale_id))
        return
    if not filter_sale_returns_query(SaleReturn.query.filter_by(id=int(return_id))).first():
        abort(404)


def assert_payment_access(payment_id: int) -> None:
    from extensions import db
    from models import Payment

    ids = get_accessible_branch_ids()
    if ids is None:
        return
    if not ids:
        abort(404)
    ok = db.session.query(
        payment_ids_in_branches(ids).where(Payment.id == int(payment_id)).exists()
    ).scalar()
    if not ok:
        abort(404)


def assert_warehouse_access(warehouse_id: int) -> None:
    ids = get_accessible_branch_ids()
    if ids is None:
        return
    if not ids:
        abort(404)
    from models import Warehouse

    wh = Warehouse.query.filter_by(id=int(warehouse_id)).first()
    if not wh or not wh.branch_id or int(wh.branch_id) not in ids:
        abort(404)


def assert_company_access(company_id: int) -> None:
    allowed = get_accessible_company_ids()
    if allowed is None:
        return
    if int(company_id) not in allowed:
        abort(404)


def assert_customer_access(customer_id: int) -> None:
    from models import Customer

    if filter_customers_query(Customer.query.filter_by(id=int(customer_id))).first() is None:
        abort(404)


def assert_payment_entity_scope(entity_type: str, entity_id: Optional[int]) -> None:
    et = (entity_type or "").upper()
    eid = entity_id
    if not eid:
        return
    if et in ("SALE", "INVOICE"):
        assert_sale_access(int(eid))
    elif et == "EXPENSE":
        assert_expense_access(int(eid))
    elif et == "CUSTOMER":
        assert_customer_access(int(eid))
    elif et == "SHIPMENT":
        from models import Shipment, Warehouse

        ids = get_accessible_branch_ids()
        if ids is None:
            return
        shp = Shipment.query.filter_by(id=int(eid)).first()
        if not shp:
            abort(404)
        dest_id = getattr(shp, "destination_id", None)
        if dest_id:
            wh = Warehouse.query.filter_by(id=int(dest_id)).first()
            if wh and wh.branch_id and int(wh.branch_id) not in ids:
                abort(404)


def default_company():
    from models import Company

    co_ids = get_accessible_company_ids()
    q = Company.query.filter_by(is_active=True).order_by(Company.id.asc())
    if co_ids is not None:
        if not co_ids:
            return None
        q = q.filter(Company.id.in_(co_ids))
    return q.first()


def scoped_payment_query(session=None):
    """استعلام Payment مع نطاق الفرع (للتسويات والدوال الداخلية)."""
    from extensions import db
    from models import Payment

    s = session if session is not None else db.session
    return filter_payments_query(s.query(Payment))


def scoped_check_query(session=None):
    from extensions import db
    from models import Check

    s = session if session is not None else db.session
    return filter_checks_query(s.query(Check))


def scoped_expense_query(session=None):
    from extensions import db
    from models import Expense

    s = session if session is not None else db.session
    return filter_expenses_query(s.query(Expense))


def scoped_sale_query(session=None):
    from extensions import db
    from models import Sale

    s = session if session is not None else db.session
    return filter_sales_query(s.query(Sale))


def scoped_service_request_query(session=None):
    from extensions import db
    from models import ServiceRequest

    s = session if session is not None else db.session
    return filter_service_requests_query(s.query(ServiceRequest))


def scoped_shipment_query(session=None):
    from extensions import db
    from models import Shipment

    s = session if session is not None else db.session
    return filter_shipments_query(s.query(Shipment))


def assert_branch_access(branch_id: int) -> None:
    from models import Branch

    if filter_branches_query(Branch.query.filter_by(id=int(branch_id))).first() is None:
        abort(404)


def branch_expenses_query(branch_id: Optional[int] = None):
    """مصاريف ضمن فروع المستخدم؛ يُقيَّد بفرع واحد عند تمرير branch_id."""
    from models import Expense

    q = filter_expenses_query(Expense.query)
    if branch_id is not None:
        assert_branch_access(int(branch_id))
        q = q.filter(Expense.branch_id == int(branch_id))
    return q


def branch_warehouses_query(branch_id: Optional[int] = None):
    from models import Warehouse

    q = filter_warehouses_query(Warehouse.query)
    if branch_id is not None:
        assert_branch_access(int(branch_id))
        q = q.filter(Warehouse.branch_id == int(branch_id))
    return q


def branch_scoped_query(model, branch_id: int, branch_column):
    """استعلام عام لنموذج له branch_id بعد التحقق من صلاحية الفرع."""
    assert_branch_access(int(branch_id))
    return filter_by_branches(model.query.filter(branch_column == int(branch_id)), branch_column)
