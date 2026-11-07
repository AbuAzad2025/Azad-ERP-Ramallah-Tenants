"""مسير رواتب وترحيل GL."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from extensions import db
from models import (
    Employee,
    EmployeeDeduction,
    PayrollRun,
    PayrollLine,
    GL_ACCOUNTS,
    _gl_upsert_batch_and_entries,
    _ensure_account_exists,
)


def build_payroll_run(period_key: str, branch_id: int) -> PayrollRun:
    existing = PayrollRun.query.filter_by(period_key=period_key, branch_id=branch_id).first()
    if existing and existing.status == "POSTED":
        raise ValueError("مسير الشهر مُرحّل مسبقاً")
    if existing:
        db.session.delete(existing)
        db.session.flush()
    run = PayrollRun(
        period_key=period_key,
        branch_id=branch_id,
        status="DRAFT",
        run_date=date.today(),
        currency="ILS",
    )
    db.session.add(run)
    db.session.flush()
    employees = Employee.query.filter_by(branch_id=branch_id).all()
    gross = Decimal("0")
    ded = Decimal("0")
    net = Decimal("0")
    for emp in employees:
        base = Decimal(str(emp.salary or 0))
        emp_ded = sum(
            Decimal(str(d.amount or 0))
            for d in EmployeeDeduction.query.filter_by(employee_id=emp.id, is_active=True).all()
        )
        allowances = Decimal("0")
        line_net = base + allowances - emp_ded
        if line_net <= 0 and base <= 0:
            continue
        db.session.add(
            PayrollLine(
                payroll_run_id=run.id,
                employee_id=emp.id,
                base_salary=base,
                allowances=allowances,
                deductions=emp_ded,
                net_pay=line_net,
            )
        )
        gross += base + allowances
        ded += emp_ded
        net += line_net
    run.total_gross = gross
    run.total_deductions = ded
    run.total_net = net
    return run


def post_payroll_gl(run_id: int) -> int:
    run = db.session.get(PayrollRun, run_id)
    if not run:
        raise ValueError("مسير غير موجود")
    if run.status == "POSTED":
        return 0
    amount = float(run.total_net or 0)
    if amount <= 0:
        raise ValueError("صافي المسير صفر")
    exp = GL_ACCOUNTS.get("PAYROLL_EXP", "6100_PAYROLL_EXPENSE")
    payable = GL_ACCOUNTS.get("PAYROLL_PAYABLE", "2100_PAYROLL_PAYABLE")
    conn = db.session.connection()
    _ensure_account_exists(conn, exp)
    _ensure_account_exists(conn, payable)
    batch_id = _gl_upsert_batch_and_entries(
        conn,
        source_type="PAYROLL",
        source_id=run.id,
        purpose="PAYROLL_ACCRUAL",
        currency=run.currency or "ILS",
        memo=f"مسير رواتب {run.period_key}",
        entries=[(exp, amount, 0.0), (payable, 0.0, amount)],
        ref=f"PAYROLL-{run.period_key}",
        entity_type=None,
        entity_id=None,
        branch_id=run.branch_id,
    )
    run.status = "POSTED"
    run.posted_at = datetime.now(timezone.utc)
    db.session.commit()
    return int(batch_id)
