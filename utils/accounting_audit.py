"""
تدقيق محاسبي صارم: حقوق / التزامات / رصيد — زبون، مورد، شريك.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from extensions import db
from utils.accounting_formulas import (
    customer_balance_from_components,
    customer_obligations_total,
    customer_rights_total,
    partner_balance_from_components,
    partner_obligations_total,
    partner_rights_total,
    supplier_balance_from_components,
    supplier_obligations_total,
    supplier_rights_total,
)


TOLERANCE = Decimal("0.02")


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0.00")


def _opening_ils(opening_raw, currency: str | None) -> Decimal:
    opening = _d(opening_raw)
    if currency and str(currency).upper() != "ILS":
        try:
            from utils.customer_balance_updater import convert_amount
            opening = convert_amount(opening, currency, "ILS")
        except Exception:
            pass
    return opening


def audit_entity_balances(*, limit: int = 0, include_archived: bool = False, fix: bool = False, fix_policy: bool = False) -> dict:
    from models import Customer, Partner, Supplier
    from utils.balance_calculator import build_customer_balance_view, calculate_customer_balance_components
    from utils.partner_balance_updater import build_partner_balance_view, update_partner_balance_components
    from utils.supplier_balance_updater import (
        build_supplier_balance_view,
        calculate_supplier_balance_components,
        update_supplier_balance_components,
    )
    from utils.customer_balance_updater import update_customer_balance_components

    report: dict = {
        "tolerance": float(TOLERANCE),
        "fix": bool(fix),
        "customers": {"checked": 0, "formula_ok": 0, "stored_mismatch": 0, "fixed": 0, "issues": []},
        "suppliers": {"checked": 0, "formula_ok": 0, "stored_mismatch": 0, "fixed": 0, "issues": []},
        "partners": {"checked": 0, "formula_ok": 0, "stored_mismatch": 0, "fixed": 0, "issues": []},
        "policy": {"payment_document_links": 0, "invoice_sale_double_count": 0, "fixed": 0, "samples": []},
    }

    def _cap_issues(bucket: str, item: dict):
        if len(report[bucket]["issues"]) < 30:
            report[bucket]["issues"].append(item)

    # ——— زبائن ———
    cq = Customer.query.order_by(Customer.id.asc())
    if not include_archived:
        cq = cq.filter(Customer.is_archived == False)  # noqa: E712
    if limit:
        cq = cq.limit(limit)
    for c in cq.all():
        report["customers"]["checked"] += 1
        comp = calculate_customer_balance_components(c.id, db.session)
        if not comp:
            _cap_issues("customers", {"id": c.id, "issue": "components_failed"})
            continue
        opening = _opening_ils(c.opening_balance, c.currency)
        rights = customer_rights_total(comp)
        obligations = customer_obligations_total(comp)
        calc = customer_balance_from_components(opening, comp)
        stored = _d(c.current_balance)
        if (calc - stored).copy_abs() <= TOLERANCE:
            report["customers"]["formula_ok"] += 1
        else:
            report["customers"]["stored_mismatch"] += 1
            _cap_issues(
                "customers",
                {
                    "id": c.id,
                    "name": c.name,
                    "issue": "stored_balance_mismatch",
                    "stored": float(stored),
                    "calculated": float(calc),
                    "rights": float(rights),
                    "obligations": float(obligations),
                },
            )
            if fix:
                try:
                    update_customer_balance_components(c.id, db.session)
                    db.session.commit()
                    report["customers"]["fixed"] += 1
                except Exception:
                    db.session.rollback()
        view = build_customer_balance_view(c.id, db.session)
        if view.get("success") and not view.get("balance", {}).get("matches_stored"):
            _cap_issues("customers", {"id": c.id, "issue": "view_breakdown_mismatch", "diff": view["balance"].get("difference")})

    # ——— موردون ———
    sq = Supplier.query.order_by(Supplier.id.asc())
    if not include_archived and hasattr(Supplier, "is_archived"):
        sq = sq.filter(Supplier.is_archived == False)  # noqa: E712
    if limit:
        sq = sq.limit(limit)
    for s in sq.all():
        report["suppliers"]["checked"] += 1
        comp = calculate_supplier_balance_components(s.id, db.session)
        if not comp:
            _cap_issues("suppliers", {"id": s.id, "issue": "components_failed"})
            continue
        opening = _opening_ils(s.opening_balance, s.currency)
        rights = supplier_rights_total(comp)
        obligations = supplier_obligations_total(comp)
        calc = supplier_balance_from_components(opening, comp)
        stored = _d(s.current_balance)
        if (calc - stored).copy_abs() <= TOLERANCE:
            report["suppliers"]["formula_ok"] += 1
        else:
            report["suppliers"]["stored_mismatch"] += 1
            _cap_issues(
                "suppliers",
                {
                    "id": s.id,
                    "name": s.name,
                    "issue": "stored_balance_mismatch",
                    "stored": float(stored),
                    "calculated": float(calc),
                    "rights": float(rights),
                    "obligations": float(obligations),
                },
            )
            if fix:
                try:
                    update_supplier_balance_components(s.id, db.session)
                    db.session.commit()
                    report["suppliers"]["fixed"] += 1
                except Exception:
                    db.session.rollback()
        view = build_supplier_balance_view(s.id, db.session)
        if view.get("success") and not view.get("balance", {}).get("matches_stored"):
            _cap_issues("suppliers", {"id": s.id, "issue": "view_breakdown_mismatch", "diff": view["balance"].get("difference")})

    # ——— شركاء ———
    pq = Partner.query.order_by(Partner.id.asc())
    if not include_archived and hasattr(Partner, "is_archived"):
        pq = pq.filter(Partner.is_archived == False)  # noqa: E712
    if limit:
        pq = pq.limit(limit)
    for p in pq.all():
        report["partners"]["checked"] += 1
        from utils.partner_balance_calculator import calculate_partner_balance_components

        comp = calculate_partner_balance_components(p.id, db.session)
        if not comp:
            _cap_issues("partners", {"id": p.id, "issue": "components_failed"})
            continue
        opening = _opening_ils(p.opening_balance, p.currency)
        rights = partner_rights_total(comp)
        obligations = partner_obligations_total(comp)
        calc = partner_balance_from_components(opening, comp)
        stored = _d(p.current_balance)
        prepaid_dup = _d(comp.get("preorders_prepaid_balance"))
        pay_in = _d(comp.get("payments_in_balance"))
        if prepaid_dup > 0 and pay_in >= prepaid_dup:
            _cap_issues(
                "partners",
                {
                    "id": p.id,
                    "issue": "prepaid_in_payments_in",
                    "preorders_prepaid": float(prepaid_dup),
                    "payments_in": float(pay_in),
                },
            )
        if (calc - stored).copy_abs() <= TOLERANCE:
            report["partners"]["formula_ok"] += 1
        else:
            report["partners"]["stored_mismatch"] += 1
            _cap_issues(
                "partners",
                {
                    "id": p.id,
                    "name": p.name,
                    "issue": "stored_balance_mismatch",
                    "stored": float(stored),
                    "calculated": float(calc),
                    "rights": float(rights),
                    "obligations": float(obligations),
                },
            )
            if fix:
                try:
                    update_partner_balance_components(p.id, db.session)
                    db.session.commit()
                    report["partners"]["fixed"] += 1
                except Exception:
                    db.session.rollback()
        view = build_partner_balance_view(p.id, db.session)
        if view.get("success") and not view.get("balance", {}).get("matches_stored"):
            _cap_issues("partners", {"id": p.id, "issue": "view_breakdown_mismatch", "diff": view["balance"].get("difference")})

    _audit_payment_policy(report, fix=fix_policy)
    _audit_invoice_double_count(report)

    report["summary"] = {
        "customers_mismatch": report["customers"]["stored_mismatch"],
        "suppliers_mismatch": report["suppliers"]["stored_mismatch"],
        "partners_mismatch": report["partners"]["stored_mismatch"],
        "policy_issues": report["policy"]["payment_document_links"]
        + report["policy"]["invoice_sale_double_count"],
    }
    return report


def _audit_payment_policy(report: dict, *, fix: bool = False) -> None:
    from models import Payment, PaymentDirection, PaymentStatus, Sale, Invoice, ServiceRequest, PreOrder
    from utils.payment_allocation_policy import payment_auto_allocate_enabled

    if payment_auto_allocate_enabled():
        return
    from sqlalchemy import or_

    q = Payment.query.filter(
        Payment.direction == PaymentDirection.IN.value,
        Payment.status == PaymentStatus.COMPLETED.value,
        or_(
            Payment.sale_id.isnot(None),
            Payment.invoice_id.isnot(None),
            Payment.service_id.isnot(None),
            Payment.preorder_id.isnot(None),
        ),
    )
    for p in q.all():
        report["policy"]["payment_document_links"] += 1
        cid = p.customer_id
        if not cid and p.sale_id:
            s = db.session.get(Sale, int(p.sale_id))
            cid = getattr(s, "customer_id", None) if s else None
        if not cid and p.invoice_id:
            inv = db.session.get(Invoice, int(p.invoice_id))
            cid = getattr(inv, "customer_id", None) if inv else None
        if not cid and p.service_id:
            svc = db.session.get(ServiceRequest, int(p.service_id))
            cid = getattr(svc, "customer_id", None) if svc else None
        if not cid and p.preorder_id:
            po = db.session.get(PreOrder, int(p.preorder_id))
            cid = getattr(po, "customer_id", None) if po else None

        if fix and cid:
            try:
                p.customer_id = int(cid)
                p.entity_type = "CUSTOMER"
                p.sale_id = None
                p.invoice_id = None
                p.service_id = None
                p.preorder_id = None
                db.session.add(p)
                report["policy"]["fixed"] += 1
                continue
            except Exception:
                db.session.rollback()

        if len(report["policy"]["samples"]) < 25:
            report["policy"]["samples"].append(
                {
                    "payment_id": p.id,
                    "issue": "payment_linked_to_document_while_auto_allocate_off",
                    "sale_id": p.sale_id,
                    "invoice_id": p.invoice_id,
                    "service_id": p.service_id,
                    "customer_id": p.customer_id,
                    "derived_customer_id": cid,
                }
            )
    if fix and report["policy"]["fixed"]:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            report["policy"]["fixed"] = 0


def _audit_invoice_double_count(report: dict) -> None:
    from models import Invoice
    from sqlalchemy import func

    row = (
        db.session.query(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(
            Invoice.cancelled_at.is_(None),
            Invoice.sale_id.isnot(None),
        )
        .first()
    )
    cnt = int(row[0] or 0)
    total = float(row[1] or 0)
    if cnt > 0:
        report["policy"]["invoice_sale_double_count"] = cnt
        report["policy"]["samples"].append(
            {
                "issue": "invoices_linked_to_sales_exist",
                "count": cnt,
                "total_amount_ils_approx": total,
                "note": "يجب ألا تُجمع في invoices_balance إذا sale_id معيّن (تم إصلاح الحساب)",
            }
        )


def format_audit_report_text(report: dict) -> str:
    lines = [
        "=== تدقيق محاسبي صارم ===",
        f"زبائن: فُحص {report['customers']['checked']} | متطابق {report['customers']['formula_ok']} | فرق مخزّن {report['customers']['stored_mismatch']}",
        f"موردون: فُحص {report['suppliers']['checked']} | متطابق {report['suppliers']['formula_ok']} | فرق مخزّن {report['suppliers']['stored_mismatch']}",
        f"شركاء: فُحص {report['partners']['checked']} | متطابق {report['partners']['formula_ok']} | فرق مخزّن {report['partners']['stored_mismatch']}",
        f"سياسة: دفعات مربوطة بمستندات {report['policy']['payment_document_links']} | مُصلَحة {report['policy'].get('fixed', 0)} | فواتير مربوطة بمبيعات {report['policy']['invoice_sale_double_count']}",
    ]
    for key in ("customers", "suppliers", "partners"):
        for item in report[key].get("issues", [])[:5]:
            lines.append(f"  [{key}] {item}")
    for item in report["policy"].get("samples", [])[:5]:
        lines.append(f"  [policy] {item}")
    return "\n".join(lines)
