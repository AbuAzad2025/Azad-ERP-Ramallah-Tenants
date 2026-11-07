#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""إعداد شركتين + ربط البيانات القديمة + user_branches."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PHE_COMPANY = {
    "code": "PHE",
    "name": "المهندس الفلسطيني للمعدات الثقيلة",
    "legal_name": "المهندس الفلسطيني للمعدات الثقيلة",
    "currency": "ILS",
}
PHE_BRANCH = {
    "code": "RAMALLAH",
    "name": "رام الله",
    "city": "رام الله",
    "currency": "ILS",
}
NASR_COMPANY = {
    "code": "NASR",
    "name": "شركة نصر للاستيراد والتصدير",
    "legal_name": "شركة نصر للاستيراد والتصدير",
    "currency": "AED",
    "address": "الشارقة، الإمارات العربية المتحدة",
}
NASR_BRANCH = {
    "code": "SHARJAH",
    "name": "الشارقة",
    "city": "الشارقة",
    "currency": "AED",
    "address": "الشارقة، الإمارات العربية المتحدة",
}

# مستخدمون → فرع رام الله (شركة المهندس)
RAMALLAH_USERNAMES = ("manager", "staff", "mechanic", "customer")
# مستخدمون → فرع الشارقة (شركة نصر)
SHARJAH_USERNAMES = ("Naser",)


def main() -> int:
    from app import create_app
    from extensions import db
    from models import (
        Branch,
        Company,
        User,
        Warehouse,
        Expense,
        GLBatch,
        Employee,
        Budget,
        PayrollRun,
        PurchaseOrder,
        SupplierInvoice,
        UserBranch,
    )
    from services.user_branch_service import sync_user_branches
    from sqlalchemy import text

    app = create_app()
    with app.app_context():
        # --- الشركة الأولى (تحديث الموجود) ---
        co_phe = Company.query.filter_by(code="PHE").first() or Company.query.order_by(Company.id).first()
        if not co_phe:
            co_phe = Company(**PHE_COMPANY)
            db.session.add(co_phe)
            db.session.flush()
        else:
            for k, v in PHE_COMPANY.items():
                setattr(co_phe, k, v)

        br_ramallah = Branch.query.filter_by(code="RAMALLAH").first() or Branch.query.filter_by(id=1).first()
        if not br_ramallah:
            br_ramallah = Branch(company_id=co_phe.id, **PHE_BRANCH)
            db.session.add(br_ramallah)
            db.session.flush()
        else:
            br_ramallah.company_id = co_phe.id
            for k, v in PHE_BRANCH.items():
                setattr(br_ramallah, k, v)

        # --- شركة نصر ---
        co_nasr = Company.query.filter_by(code="NASR").first()
        if not co_nasr:
            co_nasr = Company(**NASR_COMPANY)
            db.session.add(co_nasr)
            db.session.flush()
        else:
            for k, v in NASR_COMPANY.items():
                setattr(co_nasr, k, v)

        br_sharjah = Branch.query.filter_by(code="SHARJAH").first()
        if not br_sharjah:
            br_sharjah = Branch(company_id=co_nasr.id, **NASR_BRANCH)
            db.session.add(br_sharjah)
            db.session.flush()
        else:
            br_sharjah.company_id = co_nasr.id
            for k, v in NASR_BRANCH.items():
                setattr(br_sharjah, k, v)

        ramallah_id = int(br_ramallah.id)
        sharjah_id = int(br_sharjah.id)

        # --- ربط كل المستودعات والبيانات التشغيلية برام الله ---
        Warehouse.query.filter(
            (Warehouse.branch_id.is_(None)) | (Warehouse.branch_id != ramallah_id)
        ).update({Warehouse.branch_id: ramallah_id}, synchronize_session=False)

        for model, col in (
            (Expense, Expense.branch_id),
            (Employee, Employee.branch_id),
            (Budget, Budget.branch_id),
            (PayrollRun, PayrollRun.branch_id),
            (PurchaseOrder, PurchaseOrder.branch_id),
            (SupplierInvoice, SupplierInvoice.branch_id),
        ):
            model.query.filter(col.is_(None)).update({col: ramallah_id}, synchronize_session=False)

        # GL batches بلا فرع → رام الله (البيانات التاريخية)
        GLBatch.query.filter(GLBatch.branch_id.is_(None)).update(
            {GLBatch.branch_id: ramallah_id}, synchronize_session=False
        )

        # --- user_branches ---
        UserBranch.query.delete(synchronize_session=False)
        for u in User.query.filter(User.is_system_account.is_(False)).all():
            uname = (u.username or "").strip()
            if uname in SHARJAH_USERNAMES:
                sync_user_branches(u.id, [sharjah_id], primary_branch_id=sharjah_id)
                if u.role_id == 2:  # super_admin → manager للعزل
                    u.role_id = 10
            else:
                sync_user_branches(u.id, [ramallah_id], primary_branch_id=ramallah_id)

        # صلاحية view_all_branches للمالك/النظام فقط — تُدار عبر sync_permissions
        db.session.commit()

        print("=== Companies / Branches ===")
        for c in Company.query.order_by(Company.id).all():
            print(f"  Co#{c.id} {c.code}: {c.name}")
            for b in Branch.query.filter_by(company_id=c.id).all():
                wh = Warehouse.query.filter_by(branch_id=b.id).count()
                ub = UserBranch.query.filter_by(branch_id=b.id).count()
                print(f"    Branch#{b.id} {b.code} {b.name} | warehouses={wh} users={ub}")

        print("\n=== User branch links ===")
        for ub in UserBranch.query.order_by(UserBranch.user_id).all():
            u = db.session.get(User, ub.user_id)
            b = db.session.get(Branch, ub.branch_id)
            print(f"  {getattr(u, 'username', '?')} -> {getattr(b, 'name', '?')} primary={ub.is_primary}")

        null_wh = Warehouse.query.filter(Warehouse.branch_id.is_(None)).count()
        null_gl = GLBatch.query.filter(GLBatch.branch_id.is_(None)).count()
        print(f"\nwarehouses without branch: {null_wh}")
        print(f"gl_batches without branch: {null_gl}")
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
