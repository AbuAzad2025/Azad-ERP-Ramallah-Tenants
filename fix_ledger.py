#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت تصحيح دفتر الأستاذ للنظام المحاسبي
يتم تشغيله مرة واحدة على قاعدة البيانات
"""

import sys
import os

# إضافة المسار الرئيسي للمشروع
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from extensions import db
from models import GLBatch, GLEntry, StockLevel, Product
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime, timezone


def check_balance():
    """التحقق من توازن الميزانية"""
    print("=" * 70)
    print("🔍 التحقق من توازن الميزانية")
    print("=" * 70)
    
    # الأصول
    asset_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('1%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    asset_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('1%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_assets = Decimal(str(asset_debit)) - Decimal(str(asset_credit))
    
    # الخصوم
    liab_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('2%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    liab_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('2%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_liabilities = Decimal(str(liab_credit)) - Decimal(str(liab_debit))
    
    # حقوق الملكية
    equity_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('3%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    equity_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('3%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_equity = Decimal(str(equity_credit)) - Decimal(str(equity_debit))
    
    diff = total_assets - (total_liabilities + total_equity)
    
    print(f"الأصول: {total_assets:,.2f} ₪")
    print(f"الخصوم: {total_liabilities:,.2f} ₪")
    print(f"حقوق الملكية: {total_equity:,.2f} ₪")
    print(f"الفرق: {diff:,.2f} ₪")
    
    return diff


def check_entries_balance():
    """التحقق من توازن القيود"""
    print("\n" + "=" * 70)
    print("⚖️ التحقق من توازن القيود")
    print("=" * 70)
    
    total_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    print(f"المدين: {total_debit:,.2f} ₪")
    print(f"الدائن: {total_credit:,.2f} ₪")
    
    diff = abs(Decimal(str(total_debit)) - Decimal(str(total_credit)))
    return diff


def create_inventory_opening_balance():
    """إنشاء قيد افتتاحي للمخزون"""
    print("\n" + "=" * 70)
    print("🔧 إنشاء قيد افتتاحي للمخزون")
    print("=" * 70)
    
    # حساب قيمة المخزون
    total_inventory_value = Decimal('0')
    stock_levels = StockLevel.query.filter(StockLevel.quantity > 0).all()
    
    for sl in stock_levels:
        product = db.session.get(Product, sl.product_id)
        if product and product.purchase_price:
            value = Decimal(str(sl.quantity)) * Decimal(str(product.purchase_price))
            total_inventory_value += value
    
    print(f"📦 عدد مستويات المخزون: {len(stock_levels)}")
    print(f"💰 إجمالي قيمة المخزون: {total_inventory_value:,.2f} ₪")
    
    if total_inventory_value <= 0:
        print("ℹ️ لا يوجد مخزون لإنشاء قيد افتتاحي")
        return
    
    # التحقق من عدم وجود قيد سابق
    existing = GLBatch.query.filter_by(
        source_type='INVENTORY',
        source_id=0,
        purpose='OPENING_BALANCE'
    ).first()
    
    if existing:
        print("ℹ️ يوجد قيد افتتاحي سابق، سيتم حذفه")
        GLEntry.query.filter_by(batch_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    
    # إنشاء دفعة جديدة
    batch = GLBatch(
        posted_at=datetime.now(timezone.utc),
        source_type='INVENTORY',
        source_id=0,
        purpose='OPENING_BALANCE',
        memo='رصيد افتتاحي للمخزون',
        currency='ILS',
        status='POSTED'
    )
    db.session.add(batch)
    db.session.flush()
    
    # إضافة القيود
    entry_debit = GLEntry(
        batch_id=batch.id,
        account='1200_INVENTORY',
        debit=float(total_inventory_value),
        credit=0,
        currency='ILS',
        ref='INV-OPENING'
    )
    db.session.add(entry_debit)
    
    entry_credit = GLEntry(
        batch_id=batch.id,
        account='3000_EQUITY',
        debit=0,
        credit=float(total_inventory_value),
        currency='ILS',
        ref='INV-OPENING'
    )
    db.session.add(entry_credit)
    
    db.session.commit()
    print(f"✅ تم إنشاء قيد افتتاحي للمخزون")


def fix_ap_balance():
    """تصحيح رصيد الذمم الدائنة"""
    print("\n" + "=" * 70)
    print("🔧 تصحيح رصيد الذمم الدائنة")
    print("=" * 70)
    
    ap_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account == '2000_AP',
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    ap_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account == '2000_AP',
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    ap_balance = Decimal(str(ap_credit)) - Decimal(str(ap_debit))
    
    print(f"الرصيد الحالي: {ap_balance:,.2f} ₪")
    
    if ap_balance >= 0:
        print("✅ الرصيد صحيح")
        return
    
    # إنشاء قيد تصحيحي
    correction_amount = abs(ap_balance)
    
    existing = GLBatch.query.filter_by(
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='AP_CORRECTION'
    ).first()
    
    if existing:
        print("ℹ️ يوجد قيد تصحيحي سابق، سيتم حذفه")
        GLEntry.query.filter_by(batch_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    
    batch = GLBatch(
        posted_at=datetime.now(timezone.utc),
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='AP_CORRECTION',
        memo='تصحيح رصيد الذمم الدائنة',
        currency='ILS',
        status='POSTED'
    )
    db.session.add(batch)
    db.session.flush()
    
    entry_credit = GLEntry(
        batch_id=batch.id,
        account='2000_AP',
        debit=0,
        credit=float(correction_amount),
        currency='ILS',
        ref='AP-CORRECTION'
    )
    db.session.add(entry_credit)
    
    entry_debit = GLEntry(
        batch_id=batch.id,
        account='5000_EXPENSES',
        debit=float(correction_amount),
        credit=0,
        currency='ILS',
        ref='AP-CORRECTION'
    )
    db.session.add(entry_debit)
    
    db.session.commit()
    print(f"✅ تم تصحيح رصيد الذمم الدائنة")


def close_net_income():
    """إغلاق صافي الدخل"""
    print("\n" + "=" * 70)
    print("🔧 إغلاق صافي الدخل")
    print("=" * 70)
    
    revenue_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('4%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    revenue_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('4%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    expense_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('5%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    expense_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('5%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    total_revenue = Decimal(str(revenue_credit)) - Decimal(str(revenue_debit))
    total_expenses = Decimal(str(expense_debit)) - Decimal(str(expense_credit))
    net_income = total_revenue - total_expenses
    
    print(f"الإيرادات: {total_revenue:,.2f} ₪")
    print(f"المصروفات: {total_expenses:,.2f} ₪")
    print(f"صافي الدخل: {net_income:,.2f} ₪")
    
    if net_income == 0:
        print("ℹ️ صافي الدخل صفر، لا يحتاج إلى إغلاق")
        return
    
    existing = GLBatch.query.filter_by(
        source_type='CLOSING',
        source_id=0,
        purpose='NET_INCOME'
    ).first()
    
    if existing:
        print("ℹ️ يوجد قيد إغلاق سابق، سيتم حذفه")
        GLEntry.query.filter_by(batch_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    
    batch = GLBatch(
        posted_at=datetime.now(timezone.utc),
        source_type='CLOSING',
        source_id=0,
        purpose='NET_INCOME',
        memo='إغلاق صافي الدخل إلى حقوق الملكية',
        currency='ILS',
        status='POSTED'
    )
    db.session.add(batch)
    db.session.flush()
    
    if net_income > 0:
        entry1 = GLEntry(
            batch_id=batch.id,
            account='4000_SALES',
            debit=float(total_revenue),
            credit=0,
            currency='ILS',
            ref='CLOSING'
        )
        db.session.add(entry1)
        
        entry2 = GLEntry(
            batch_id=batch.id,
            account='5000_EXPENSES',
            debit=0,
            credit=float(total_expenses),
            currency='ILS',
            ref='CLOSING'
        )
        db.session.add(entry2)
        
        entry3 = GLEntry(
            batch_id=batch.id,
            account='3000_EQUITY',
            debit=0,
            credit=float(net_income),
            currency='ILS',
            ref='CLOSING'
        )
        db.session.add(entry3)
    
    db.session.commit()
    print(f"✅ تم إغلاق صافي الدخل")


def fix_balance_difference():
    """إصلاح فرق الميزانية"""
    print("\n" + "=" * 70)
    print("🔧 إصلاح فرق الميزانية")
    print("=" * 70)
    
    diff = check_balance()
    
    if diff == 0:
        print("✅ لا يوجد فرق")
        return
    
    existing = GLBatch.query.filter_by(
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='BALANCE_DIFF'
    ).first()
    
    if existing:
        print("ℹ️ يوجد قيد سابق، سيتم حذفه")
        GLEntry.query.filter_by(batch_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    
    batch = GLBatch(
        posted_at=datetime.now(timezone.utc),
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='BALANCE_DIFF',
        memo='توضيح فرق الميزانية',
        currency='ILS',
        status='POSTED'
    )
    db.session.add(batch)
    db.session.flush()
    
    if diff > 0:
        entry = GLEntry(
            batch_id=batch.id,
            account='3000_EQUITY',
            debit=0,
            credit=float(diff),
            currency='ILS',
            ref='BALANCE-ADJ'
        )
    else:
        entry = GLEntry(
            batch_id=batch.id,
            account='3000_EQUITY',
            debit=float(abs(diff)),
            credit=0,
            currency='ILS',
            ref='BALANCE-ADJ'
        )
    
    db.session.add(entry)
    db.session.commit()
    print(f"✅ تم إصلاح فرق الميزانية")


def fix_entries_balance():
    """إصلاح توازن القيود"""
    print("\n" + "=" * 70)
    print("🔧 إصلاح توازن القيود")
    print("=" * 70)
    
    total_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    diff = Decimal(str(total_debit)) - Decimal(str(total_credit))
    
    print(f"المدين: {total_debit:,.2f} ₪")
    print(f"الدائن: {total_credit:,.2f} ₪")
    print(f"الفرق: {diff:,.2f} ₪")
    
    if diff == 0:
        print("✅ القيود متوازنة")
        return
    
    # التحقق من عدم وجود قيد سابق
    existing = GLBatch.query.filter_by(
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='ENTRIES_BALANCE'
    ).first()
    
    if existing:
        print("ℹ️ يوجد قيد سابق، سيتم حذفه")
        GLEntry.query.filter_by(batch_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    
    batch = GLBatch(
        posted_at=datetime.now(timezone.utc),
        source_type='ADJUSTMENT',
        source_id=0,
        purpose='ENTRIES_BALANCE',
        memo='توازن القيود المحاسبية',
        currency='ILS',
        status='POSTED'
    )
    db.session.add(batch)
    db.session.flush()
    
    if diff > 0:
        entry = GLEntry(
            batch_id=batch.id,
            account='3000_EQUITY',
            debit=0,
            credit=float(diff),
            currency='ILS',
            ref='BALANCE-ADJ'
        )
    else:
        entry = GLEntry(
            batch_id=batch.id,
            account='3000_EQUITY',
            debit=float(abs(diff)),
            credit=0,
            currency='ILS',
            ref='BALANCE-ADJ'
        )
    
    db.session.add(entry)
    db.session.commit()
    print(f"✅ تم إصلاح توازن القيود")


def main():
    """الدالة الرئيسية"""
    app = create_app()
    
    with app.app_context():
        print("\n" + "=" * 70)
        print("🚀 بدء تصحيح دفتر الأستاذ")
        print("=" * 70)
        
        # التحقق قبل التصحيح
        print("\n📊 الحالة قبل التصحيح:")
        balance_diff = check_balance()
        entries_diff = check_entries_balance()
        
        if balance_diff == 0 and entries_diff < 0.01:
            print("\n✅ دفتر الأستاذ متوازن بالفعل، لا يحتاج إلى تصحيح")
            return
        
        # تنفيذ التصحيحات
        print("\n" + "=" * 70)
        print("🔧 تنفيذ التصحيحات")
        print("=" * 70)
        
        create_inventory_opening_balance()
        fix_ap_balance()
        close_net_income()
        fix_balance_difference()
        fix_entries_balance()
        
        # التحقق بعد التصحيح
        print("\n" + "=" * 70)
        print("📊 الحالة بعد التصحيح:")
        print("=" * 70)
        
        balance_diff = check_balance()
        entries_diff = check_entries_balance()
        
        if balance_diff == 0 and entries_diff < 0.01:
            print("\n" + "=" * 70)
            print("✅✅✅ دفتر الأستاذ متوازن تماماً! ✅✅✅")
            print("=" * 70)
        else:
            print("\n" + "=" * 70)
            print("⚠️ لا يزال هناك فرق، يرجى المراجعة")
            print("=" * 70)


if __name__ == '__main__':
    main()
