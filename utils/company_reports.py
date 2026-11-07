"""تقارير مجمّعة على مستوى الشركة."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from extensions import db
from models import Branch, Customer, Supplier, Company, FiscalPeriod
from utils.balance_calculator import build_customer_balance_view


def company_dashboard(company_id: int) -> Dict[str, Any]:
    company = db.session.get(Company, company_id)
    if not company:
        raise ValueError("الشركة غير موجودة")

    branch_ids = [b.id for b in Branch.query.filter_by(company_id=company_id, is_active=True).all()]
    customers_ar = Decimal("0")
    customers_count = 0
    if branch_ids:
        from models import Sale, SaleLine, Warehouse

        customer_ids = {
            cid
            for (cid,) in (
                db.session.query(Sale.customer_id)
                .join(SaleLine, SaleLine.sale_id == Sale.id)
                .join(Warehouse, Warehouse.id == SaleLine.warehouse_id)
                .filter(
                    Warehouse.branch_id.in_(branch_ids),
                    Sale.customer_id.isnot(None),
                )
                .distinct()
                .limit(3000)
            )
            if cid
        }
        for cid in customer_ids:
            view = build_customer_balance_view(cid, db.session)
            if view.get("success"):
                net = Decimal(str((view.get("balance") or {}).get("amount", 0)))
                if net != 0:
                    customers_ar += net
                    customers_count += 1

    open_periods = FiscalPeriod.query.filter_by(status="OPEN").count()
    locked_periods = FiscalPeriod.query.filter(FiscalPeriod.status == "LOCKED").count()

    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "code": company.code,
            "tax_id": company.tax_id,
            "currency": company.currency,
        },
        "branches_count": len(branch_ids),
        "branch_ids": branch_ids,
        "customers_with_balance": customers_count,
        "customers_balance_net": float(customers_ar),
        "fiscal_open_periods": open_periods,
        "fiscal_locked_periods": locked_periods,
    }
