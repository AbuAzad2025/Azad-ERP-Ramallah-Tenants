"""تقارير مقارنة سنوات/فترات للقوائم المالية."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import GLEntry, GLBatch, Account
from utils.gl_company_scope import gl_batch_branch_clause, resolve_branch_filter


def _period_bounds(year: int, month_start: int = 1, month_end: int = 12):
    start = date(year, month_start, 1)
    if month_end == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month_end + 1, 1)
        from datetime import timedelta

        end = end - timedelta(days=1)
    return (
        datetime.combine(start, datetime.min.time()),
        datetime.combine(end, datetime.max.time()),
    )


def account_balances_for_period(
    start_dt: datetime,
    end_dt: datetime,
    *,
    company_id: int | None = None,
    account_prefix: str | None = None,
) -> dict[str, dict]:
    """أرصدة صافية حسب حساب GL للفترة."""
    q = (
        db.session.query(
            GLEntry.account,
            func.coalesce(func.sum(GLEntry.debit), 0).label("debit"),
            func.coalesce(func.sum(GLEntry.credit), 0).label("credit"),
        )
        .join(GLBatch, GLBatch.id == GLEntry.batch_id)
        .filter(GLBatch.status == "POSTED", GLBatch.posted_at >= start_dt, GLBatch.posted_at <= end_dt)
    )
    branch_ids = resolve_branch_filter(company_id)
    if branch_ids is not None:
        if not branch_ids:
            q = q.filter(GLEntry.id == -1)
        else:
            q = q.filter(gl_batch_branch_clause(branch_ids))
    if account_prefix:
        q = q.filter(GLEntry.account.like(f"{account_prefix}%"))
    rows = q.group_by(GLEntry.account).all()
    out = {}
    for acct, deb, cred in rows:
        deb_f, cred_f = float(deb or 0), float(cred or 0)
        out[str(acct)] = {
            "debit": deb_f,
            "credit": cred_f,
            "net": deb_f - cred_f,
        }
    return out


def comparative_pl(
    year_a: int,
    year_b: int,
    *,
    company_id: int | None = None,
) -> dict:
    """مقارنة إيرادات/مصروفات (حسابات 4 و 5 و 6) بين سنتين."""
    sa, ea = _period_bounds(year_a)
    sb, eb = _period_bounds(year_b)
    bal_a = account_balances_for_period(sa, ea, company_id=company_id)
    bal_b = account_balances_for_period(sb, eb, company_id=company_id)
    codes = sorted(set(bal_a) | set(bal_b))
    accounts = {a.code: a for a in Account.query.filter(Account.code.in_(codes)).all()} if codes else {}
    lines = []
    rev_a = rev_b = exp_a = exp_b = 0.0
    for code in codes:
        if not (code.startswith("4") or code.startswith("5") or code.startswith("6")):
            continue
        na = bal_a.get(code, {}).get("net", 0)
        nb = bal_b.get(code, {}).get("net", 0)
        acc = accounts.get(code)
        name = acc.name if acc else code
        typ = (acc.type or "") if acc else ""
        if code.startswith("4"):
            rev_a += -na
            rev_b += -nb
        else:
            exp_a += na
            exp_b += nb
        var = nb - na
        pct = (var / abs(na) * 100) if na else (100.0 if nb else 0.0)
        lines.append(
            {
                "account": code,
                "name": name,
                "type": typ,
                "year_a": round(na if not code.startswith("4") else -na, 2),
                "year_b": round(nb if not code.startswith("4") else -nb, 2),
                "variance": round(var if not code.startswith("4") else -var, 2),
                "variance_pct": round(pct, 1),
            }
        )
    return {
        "year_a": year_a,
        "year_b": year_b,
        "lines": lines,
        "summary": {
            "revenue_a": round(rev_a, 2),
            "revenue_b": round(rev_b, 2),
            "expense_a": round(exp_a, 2),
            "expense_b": round(exp_b, 2),
            "net_income_a": round(rev_a - exp_a, 2),
            "net_income_b": round(rev_b - exp_b, 2),
        },
    }
