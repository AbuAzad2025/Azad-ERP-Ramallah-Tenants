#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""التحقق من وجود البيانات في القاعدة المحلية بعد الاستعادة."""
import os
import sys

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, basedir)
os.chdir(basedir)

def main():
    from app import create_app
    from extensions import db
    from sqlalchemy import text

    app = create_app()
    with app.app_context():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        print("القاعدة:", uri.split("@")[-1] if "@" in uri else uri[:60] + "...")
        tables = [
            ("users", "المستخدمون"),
            ("roles", "الأدوار"),
            ("customers", "الزبائن"),
            ("sales", "المبيعات"),
            ("payments", "المدفوعات"),
            ("expenses", "المصاريف"),
            ("service_requests", "طلبات الصيانة"),
            ("warehouses", "المستودعات"),
            ("products", "المنتجات"),
        ]
        print("\n--- عدد السجلات ---")
        for table, label in tables:
            try:
                r = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"  {label} ({table}): {r}")
            except Exception as e:
                print(f"  {label} ({table}): خطأ - {e}")
        print("\nانتهى التحقق.")

if __name__ == "__main__":
    main()
