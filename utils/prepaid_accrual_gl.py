"""قيود مقدمات ومصروفات مستحقة."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from extensions import db
from models import GL_ACCOUNTS, _gl_upsert_batch_and_entries, _ensure_account_exists
from utils.enterprise_security import assert_posting_date_allowed


def post_prepaid_expense(
    *,
    amount: float,
    expense_account: str,
    memo: str,
    posting_date: date | None = None,
    branch_id: int | None = None,
    cost_center_id: int | None = None,
) -> int:
    """مدين مصروف / دائن مقدمات."""
    assert_posting_date_allowed(posting_date or date.today())
    amt = float(amount)
    if amt <= 0:
        raise ValueError("المبلغ يجب أن يكون موجباً")
    prepaid = GL_ACCOUNTS.get("PREPAID", "1400_PREPAID_EXP")
    exp = expense_account.strip().upper()
    conn = db.session.connection()
    _ensure_account_exists(conn, prepaid)
    _ensure_account_exists(conn, exp)
    entries = [
        (exp, amt, 0.0, cost_center_id),
        (prepaid, 0.0, amt, cost_center_id),
    ]
    ref = f"PREPAID-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    batch_id = _gl_upsert_batch_and_entries(
        conn,
        source_type="JOURNAL",
        source_id=int(datetime.now().timestamp()) % 1000000,
        purpose="PREPAID_EXP",
        currency="ILS",
        memo=memo or "مصروف مقدم",
        entries=entries,
        ref=ref,
        entity_type=None,
        entity_id=None,
        branch_id=branch_id,
    )
    db.session.commit()
    return int(batch_id)


def post_accrual_expense(
    *,
    amount: float,
    expense_account: str,
    memo: str,
    posting_date: date | None = None,
    branch_id: int | None = None,
    cost_center_id: int | None = None,
) -> int:
    """مدين مصروف / دائن مستحقات."""
    assert_posting_date_allowed(posting_date or date.today())
    amt = float(amount)
    if amt <= 0:
        raise ValueError("المبلغ يجب أن يكون موجباً")
    accrued = GL_ACCOUNTS.get("ACCRUED_EXP", "2205_ACCRUED_EXP")
    exp = expense_account.strip().upper()
    conn = db.session.connection()
    _ensure_account_exists(conn, accrued)
    _ensure_account_exists(conn, exp)
    entries = [
        (exp, amt, 0.0, cost_center_id),
        (accrued, 0.0, amt, cost_center_id),
    ]
    ref = f"ACCRUAL-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    batch_id = _gl_upsert_batch_and_entries(
        conn,
        source_type="JOURNAL",
        source_id=int(datetime.now().timestamp()) % 1000000,
        purpose="ACCRUAL_EXP",
        currency="ILS",
        memo=memo or "مصروف مستحق",
        entries=entries,
        ref=ref,
        entity_type=None,
        entity_id=None,
        branch_id=branch_id,
    )
    db.session.commit()
    return int(batch_id)
