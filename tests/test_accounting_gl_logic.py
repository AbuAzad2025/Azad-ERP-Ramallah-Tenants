from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select

from models import (
    Account,
    GLBatch,
    GLEntry,
    _gl_reverse_posted_batches,
    _gl_upsert_batch_and_entries,
    _invoice_gl_upsert_core,
)


def _setup_gl_schema():
    engine = create_engine("sqlite:///:memory:")
    Account.__table__.create(engine)
    GLBatch.__table__.create(engine)
    GLEntry.__table__.create(engine)
    return engine


class _InvoiceTarget:
    id = 1
    cancelled_at = None
    total_amount = Decimal("100.00")
    tax_amount = Decimal("15.00")
    currency = "ILS"
    invoice_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    customer_id = 7
    supplier_id = None
    partner_id = None
    service_id = None
    invoice_number = "INV-1"


def test_customer_invoice_gl_splits_vat_from_revenue():
    engine = _setup_gl_schema()
    with engine.begin() as conn:
        _invoice_gl_upsert_core(conn, _InvoiceTarget())

        rows = conn.execute(
            select(GLEntry.account, GLEntry.debit, GLEntry.credit)
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .where(GLBatch.source_type == "INVOICE")
            .order_by(GLEntry.account)
        ).all()

    by_account = {account: (float(debit), float(credit)) for account, debit, credit in rows}
    assert by_account["1100_AR"] == (100.0, 0.0)
    assert by_account["2100_VAT_PAYABLE"] == (0.0, 15.0)
    assert by_account["4000_SALES"] == (0.0, 85.0)


def test_gl_reverse_posted_batches_reverses_original_entries():
    engine = _setup_gl_schema()
    with engine.begin() as conn:
        _gl_upsert_batch_and_entries(
            conn,
            source_type="SALE",
            source_id=10,
            purpose="REVENUE",
            currency="ILS",
            memo="Sale #10",
            entries=[("1100_AR", 100, 0), ("4000_SALES", 0, 85), ("2100_VAT_PAYABLE", 0, 15)],
            ref="SALE-10",
            entity_type="CUSTOMER",
            entity_id=2,
        )
        _gl_reverse_posted_batches(
            conn,
            source_type="SALE",
            source_id=10,
            reversal_source_type="SALE_REVERSAL",
            memo_prefix="Reversal",
            purposes=["REVENUE"],
        )

        rows = conn.execute(
            select(GLBatch.source_type, GLEntry.account, GLEntry.debit, GLEntry.credit)
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .where(GLBatch.source_id == 10)
            .order_by(GLBatch.source_type, GLEntry.account)
        ).all()

    original = {
        account: (float(debit), float(credit))
        for source_type, account, debit, credit in rows
        if source_type == "SALE"
    }
    reversal = {
        account: (float(debit), float(credit))
        for source_type, account, debit, credit in rows
        if source_type == "SALE_REVERSAL"
    }
    assert original["1100_AR"] == (100.0, 0.0)
    assert reversal["1100_AR"] == (0.0, 100.0)
    assert original["4000_SALES"] == (0.0, 85.0)
    assert reversal["4000_SALES"] == (85.0, 0.0)
    assert original["2100_VAT_PAYABLE"] == (0.0, 15.0)
    assert reversal["2100_VAT_PAYABLE"] == (15.0, 0.0)
