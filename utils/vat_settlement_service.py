"""تسوية ضريبة القيمة المضافة — إقرار فترة."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import TaxEntry, GLBatch, GLEntry, Account


def vat_settlement_for_period(start_dt: datetime, end_dt: datetime) -> dict:
    """مجموع مخرجات/مدخلات VAT من TaxEntry والـ GL."""
    output_q = (
        db.session.query(func.coalesce(func.sum(TaxEntry.tax_amount), 0))
        .filter(
            TaxEntry.entry_type == "OUTPUT",
            TaxEntry.created_at >= start_dt,
            TaxEntry.created_at <= end_dt,
        )
        .scalar()
    )
    input_q = (
        db.session.query(func.coalesce(func.sum(TaxEntry.tax_amount), 0))
        .filter(
            TaxEntry.entry_type == "INPUT",
            TaxEntry.created_at >= start_dt,
            TaxEntry.created_at <= end_dt,
        )
        .scalar()
    )
    output_vat = float(output_q or 0)
    input_vat = float(input_q or 0)
    net_payable = output_vat - input_vat

    gl_output = (
        db.session.query(func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0))
        .join(GLBatch)
        .join(Account, Account.code == GLEntry.account)
        .filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account.like("2200%"),
        )
        .scalar()
    )
    gl_input = (
        db.session.query(func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0))
        .join(GLBatch)
        .filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account.like("1500%"),
        )
        .scalar()
    )

    return {
        "output_vat_taxentry": round(output_vat, 2),
        "input_vat_taxentry": round(input_vat, 2),
        "net_payable": round(net_payable, 2),
        "gl_vat_payable_net": round(float(gl_output or 0), 2),
        "gl_vat_input_net": round(float(gl_input or 0), 2),
        "reconciled": abs(net_payable - float(gl_output or 0)) < 1.0,
    }


def post_vat_settlement_gl(start_dt: datetime, end_dt: datetime, *, branch_id: int | None = None) -> int:
    """ترحيل صافي VAT المستحق للفترة إلى GL."""
    from models import GL_ACCOUNTS, _gl_upsert_batch_and_entries, _ensure_account_exists

    data = vat_settlement_for_period(start_dt, end_dt)
    net = float(data.get("net_payable") or 0)
    if abs(net) < 0.01:
        raise ValueError("لا يوجد صافي VAT للترحيل")
    vat_pay = GL_ACCOUNTS.get("VAT", "2100_VAT_PAYABLE")
    vat_in = GL_ACCOUNTS.get("VAT_INPUT", "1500_VAT_INPUT")
    cash = GL_ACCOUNTS.get("BANK", "1010_BANK")
    conn = db.session.connection()
    _ensure_account_exists(conn, vat_pay)
    _ensure_account_exists(conn, vat_in)
    _ensure_account_exists(conn, cash)
    sid = int(start_dt.strftime("%Y%m%d"))
    if net > 0:
        entries = [(vat_pay, net, 0.0), (cash, 0.0, net)]
        memo = f"تسوية VAT مستحق {start_dt.date()} — {end_dt.date()}"
    else:
        amt = abs(net)
        entries = [(cash, amt, 0.0), (vat_in, 0.0, amt)]
        memo = f"استرداد VAT {start_dt.date()} — {end_dt.date()}"
    batch_id = _gl_upsert_batch_and_entries(
        conn,
        source_type="VAT_SETTLEMENT",
        source_id=sid,
        purpose="VAT_SETTLEMENT",
        currency="ILS",
        memo=memo,
        entries=entries,
        ref=f"VAT-{sid}",
        entity_type=None,
        entity_id=None,
        branch_id=branch_id,
    )
    db.session.commit()
    return int(batch_id)


def vat_declaration_rows(start_dt: datetime, end_dt: datetime) -> list[dict]:
    """صفوف تصدير إقرار VAT."""
    d = vat_settlement_for_period(start_dt, end_dt)
    return [
        {"field": "مخرجات VAT (TaxEntry)", "amount": d["output_vat_taxentry"]},
        {"field": "مدخلات VAT (TaxEntry)", "amount": d["input_vat_taxentry"]},
        {"field": "صافي مستحق", "amount": d["net_payable"]},
        {"field": "VAT payable GL", "amount": d["gl_vat_payable_net"]},
        {"field": "VAT input GL", "amount": d["gl_vat_input_net"]},
        {"field": "مطابق", "amount": 1 if d["reconciled"] else 0},
    ]
