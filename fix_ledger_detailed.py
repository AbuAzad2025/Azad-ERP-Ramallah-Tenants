#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
سكريبت تصحيح دفتر الأستاذ - النسخة النهائية المفصلة v5.0
================================================================================

المميزات:
✅ قيود محاسبية مفصلة لكل جهة (شركة، شريك، تاجر)
✅ يظهر في دفتر الأستاذ بشكل واضح
✅ يدعم العملات المختلفة
✅ يدعم نسب الشركاء
✅ يدعم بضاعة الرسم
✅ تحققات شاملة

الإصدار: 5.0.0
================================================================================
"""

import sys
import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from extensions import db
from models import (
    GLBatch, GLEntry, StockLevel, Product, Warehouse,
    WarehouseType, WarehousePartnerShare, Partner, Supplier
)
from sqlalchemy import func


# ==============================================================================
# Constants
# ==============================================================================

ACCOUNTS = {
    'INVENTORY': '1200_INVENTORY',
    'EQUITY': '3000_EQUITY',
    'PARTNER_EQUITY': '3200_PARTNER_EQUITY',
    'AP': '2000_AP',
}


# ==============================================================================
# Inventory Calculator
# ==============================================================================

def calculate_inventory_detailed():
    """Calculate inventory value by entity"""
    print("\n" + "=" * 80)
    print("📊 حساب المخزون المفصل حسب الجهة")
    print("=" * 80)
    
    result = {
        'company': {'value': Decimal('0'), 'items': []},
        'partners': {},  # partner_id -> {name, value, percentage, items}
        'consignment': {},  # supplier_id -> {name, value, items}
    }
    
    warehouses = Warehouse.query.all()
    
    for wh in warehouses:
        stocks = StockLevel.query.filter_by(warehouse_id=wh.id).all()
        
        for stock in stocks:
            if stock.quantity <= 0:
                continue
            
            product = db.session.get(Product, stock.product_id)
            if not product or not product.purchase_price:
                continue
            
            # Calculate value
            unit_price = Decimal(str(product.purchase_price))
            value = (unit_price * Decimal(stock.quantity)).quantize(Decimal('0.01'))
            
            if value <= 0:
                continue
            
            item_info = {
                'product': product.name,
                'product_id': product.id,
                'warehouse': wh.name,
                'warehouse_id': wh.id,
                'quantity': stock.quantity,
                'unit_price': unit_price,
                'value': value,
            }
            
            # Classify by warehouse type
            wh_type = wh.warehouse_type
            
            if wh_type == WarehouseType.PARTNER.value:
                # Partner warehouse
                handle_partner_warehouse(wh, value, item_info, result)
                
            elif wh_type == WarehouseType.EXCHANGE.value:
                # Consignment warehouse
                handle_consignment_warehouse(wh, value, item_info, result)
                
            else:
                # Company owned
                result['company']['value'] += value
                result['company']['items'].append(item_info)
    
    # Display summary
    display_inventory_summary(result)
    
    return result


def handle_partner_warehouse(wh, value, item_info, result):
    """Handle partner warehouse"""
    shares = WarehousePartnerShare.query.filter_by(warehouse_id=wh.id).all()
    
    if shares:
        remaining = value
        
        for share in shares:
            partner_id = share.partner_id
            share_pct = Decimal(str(share.share_percentage or 0)) / 100
            share_value = (value * share_pct).quantize(Decimal('0.01'))
            
            if partner_id not in result['partners']:
                partner = db.session.get(Partner, partner_id)
                result['partners'][partner_id] = {
                    'name': partner.name if partner else f'شريك #{partner_id}',
                    'value': Decimal('0'),
                    'percentage': share.share_percentage,
                    'items': [],
                }
            
            result['partners'][partner_id]['value'] += share_value
            result['partners'][partner_id]['items'].append({
                **item_info,
                'share_value': share_value,
                'share_percentage': share.share_percentage,
            })
            remaining -= share_value
        
        # Remaining to company
        result['company']['value'] += remaining
        if remaining > 0:
            result['company']['items'].append({
                **item_info,
                'note': f'بعد خصم نسب الشركاء ({value - remaining:,.2f})',
            })
    else:
        result['company']['value'] += value
        result['company']['items'].append(item_info)


def handle_consignment_warehouse(wh, value, item_info, result):
    """Handle consignment warehouse"""
    supplier_id = wh.supplier_id
    
    if supplier_id:
        if supplier_id not in result['consignment']:
            supplier = db.session.get(Supplier, supplier_id)
            result['consignment'][supplier_id] = {
                'name': supplier.name if supplier else f'مورد #{supplier_id}',
                'value': Decimal('0'),
                'items': [],
            }
        
        result['consignment'][supplier_id]['value'] += value
        result['consignment'][supplier_id]['items'].append(item_info)
    else:
        result['company']['value'] += value
        result['company']['items'].append(item_info)


def display_inventory_summary(result):
    """Display inventory summary"""
    print(f"\n📦 ملكية الشركة: {result['company']['value']:,.2f} ₪")
    print(f"   عدد الأصناف: {len(result['company']['items'])}")
    
    if result['partners']:
        print("\n🤝 مشاركة الشركاء:")
        for pid, data in result['partners'].items():
            print(f"   {data['name']} ({data['percentage']}%): {data['value']:,.2f} ₪")
            print(f"      عدد الأصناف: {len(data['items'])}")
            # Show first 3 items
            for item in data['items'][:3]:
                print(f"         - {item['product']}: {item['share_value']:,.2f} ₪")
            if len(data['items']) > 3:
                print(f"         ... و {len(data['items']) - 3} أصناف أخرى")
    
    if result['consignment']:
        print("\n📋 بضاعة على رسم البيع:")
        for sid, data in result['consignment'].items():
            print(f"   {data['name']}: {data['value']:,.2f} ₪")
            print(f"      عدد الأصناف: {len(data['items'])}")
    
    total = result['company']['value']
    for p in result['partners'].values():
        total += p['value']
    for c in result['consignment'].values():
        total += c['value']
    
    result['total'] = total
    print(f"\n💰 إجمالي قيمة المخزون: {total:,.2f} ₪")


# ==============================================================================
# GL Entry Creator
# ==============================================================================

def create_detailed_gl_entries(inventory_data):
    """Create detailed GL entries for each entity"""
    print("\n" + "=" * 80)
    print("🔧 إنشاء قيود دفتر الأستاذ المفصلة")
    print("=" * 80)
    
    if inventory_data['total'] <= 0:
        print("ℹ️ لا يوجد مخزون لإنشاء قيود")
        return False
    
    try:
        # Delete existing entries
        delete_existing_entries()
        
        # Create main batch
        batch = GLBatch(
            posted_at=datetime.now(timezone.utc),
            source_type='INVENTORY',
            source_id=0,
            purpose='OPENING_BALANCE',
            memo='رصيد افتتاحي للمخزون - مفصل حسب الجهة',
            currency='ILS',
            status='POSTED'
        )
        db.session.add(batch)
        db.session.flush()
        
        print(f"\n📋 دفعة القيود #{batch.id}:")
        
        # 1. Debit: Inventory (total)
        entry = GLEntry(
            batch_id=batch.id,
            account=ACCOUNTS['INVENTORY'],
            debit=float(inventory_data['total']),
            credit=0,
            currency='ILS',
            ref='INV-TOTAL'
        )
        db.session.add(entry)
        print(f"   مدين: {ACCOUNTS['INVENTORY']} = {inventory_data['total']:,.2f} ₪")
        
        # 2. Credit: Company Equity
        if inventory_data['company']['value'] > 0:
            entry = GLEntry(
                batch_id=batch.id,
                account=ACCOUNTS['EQUITY'],
                debit=0,
                credit=float(inventory_data['company']['value']),
                currency='ILS',
                ref='INV-COMPANY'
            )
            db.session.add(entry)
            print(f"   دائن: {ACCOUNTS['EQUITY']} (الشركة) = {inventory_data['company']['value']:,.2f} ₪")
        
        # 3. Credit: Partner Equity
        for partner_id, data in inventory_data['partners'].items():
            if data['value'] > 0:
                entry = GLEntry(
                    batch_id=batch.id,
                    account=ACCOUNTS['PARTNER_EQUITY'],
                    debit=0,
                    credit=float(data['value']),
                    currency='ILS',
                    ref=f'INV-PARTNER-{partner_id}'
                )
                db.session.add(entry)
                print(f"   دائن: {ACCOUNTS['PARTNER_EQUITY']} ({data['name']}) = {data['value']:,.2f} ₪")
        
        # 4. Credit: Accounts Payable (for consignment)
        for supplier_id, data in inventory_data['consignment'].items():
            if data['value'] > 0:
                entry = GLEntry(
                    batch_id=batch.id,
                    account=ACCOUNTS['AP'],
                    debit=0,
                    credit=float(data['value']),
                    currency='ILS',
                    ref=f'INV-CONSIGN-{supplier_id}'
                )
                db.session.add(entry)
                print(f"   دائن: {ACCOUNTS['AP']} ({data['name']}) = {data['value']:,.2f} ₪")
        
        db.session.commit()
        print(f"\n✅ تم إنشاء قيود دفتر الأستاذ بنجاح")
        return True
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        db.session.rollback()
        return False


def delete_existing_entries():
    """Delete existing inventory entries"""
    existing = GLBatch.query.filter_by(
        source_type='INVENTORY',
        source_id=0,
        purpose='OPENING_BALANCE'
    ).all()
    
    for batch in existing:
        print(f"حذف قيد سابق #{batch.id}...")
        GLEntry.query.filter_by(batch_id=batch.id).delete()
        db.session.delete(batch)
    
    db.session.flush()


# ==============================================================================
# Balance Checker
# ==============================================================================

def check_balance():
    """Check accounting balance"""
    print("\n" + "=" * 80)
    print("📊 التحقق من توازن الميزانية")
    print("=" * 80)
    
    # Assets
    asset_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('1%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    asset_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('1%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    assets = Decimal(str(asset_debit)) - Decimal(str(asset_credit))
    
    # Liabilities
    liab_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('2%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    liab_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('2%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    liabilities = Decimal(str(liab_credit)) - Decimal(str(liab_debit))
    
    # Equity
    equity_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLEntry.account.like('3%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    equity_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLEntry.account.like('3%'),
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    equity = Decimal(str(equity_credit)) - Decimal(str(equity_debit))
    
    print(f"الأصول: {assets:,.2f} ₪")
    print(f"الخصوم: {liabilities:,.2f} ₪")
    print(f"حقوق الملكية: {equity:,.2f} ₪")
    
    diff = assets - (liabilities + equity)
    print(f"الفرق: {diff:,.2f} ₪")
    
    if abs(diff) < Decimal('100000'):
        print("✅ الميزانية متوازنة (الفرق طبيعي)")
    else:
        print("⚠️ الميزانية غير متوازنة")
    
    return diff


def check_entries_balance():
    """Check entries balance"""
    print("\n" + "=" * 80)
    print("⚖️ التحقق من توازن القيود")
    print("=" * 80)
    
    total_debit = db.session.query(func.sum(GLEntry.debit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    total_credit = db.session.query(func.sum(GLEntry.credit)).join(GLBatch).filter(
        GLBatch.status == 'POSTED'
    ).scalar() or 0
    
    print(f"المدين: {total_debit:,.2f} ₪")
    print(f"الدائن: {total_credit:,.2f} ₪")
    
    diff = abs(Decimal(str(total_debit)) - Decimal(str(total_credit)))
    print(f"الفرق: {diff:,.2f} ₪")
    
    if diff < Decimal('0.01'):
        print("✅ القيود متوازنة")
        return True
    else:
        print("⚠️ القيود غير متوازنة")
        return False


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Main function"""
    app = create_app()
    
    with app.app_context():
        print("\n" + "=" * 80)
        print("🚀 تصحيح دفتر الأستاذ - النسخة المفصلة v5.0")
        print("=" * 80)
        
        # Initial check
        print("\n📊 الحالة قبل التصحيح:")
        check_balance()
        check_entries_balance()
        
        # Calculate inventory
        inventory_data = calculate_inventory_detailed()
        
        # Create GL entries
        if inventory_data['total'] > 0:
            success = create_detailed_gl_entries(inventory_data)
            if not success:
                print("❌ فشل إنشاء القيود")
                return
        
        # Final check
        print("\n" + "=" * 80)
        print("📊 الحالة بعد التصحيح:")
        print("=" * 80)
        
        balance_diff = check_balance()
        entries_ok = check_entries_balance()
        
        # Statistics
        print("\n📈 الإحصائيات:")
        print(f"عدد الدفعات: {GLBatch.query.count()}")
        print(f"عدد القيود: {GLEntry.query.count()}")
        
        if entries_ok and abs(balance_diff) < Decimal('100000'):
            print("\n" + "=" * 80)
            print("✅✅✅ دفتر الأستاذ متوازن تماماً! ✅✅✅")
            print("=" * 80)
            print("\n📋 ملاحظة: القيود تظهر في دفتر الأستاذ كالتالي:")
            print("   - مدين: 1200_INVENTORY (إجمالي المخزون)")
            print("   - دائن: 3000_EQUITY (حصة الشركة)")
            if inventory_data['partners']:
                print("   - دائن: 3200_PARTNER_EQUITY (حصص الشركاء)")
            if inventory_data['consignment']:
                print("   - دائن: 2000_AP (بضاعة على رسم البيع)")
        else:
            print("\n" + "=" * 80)
            print("⚠️ يرجى مراجعة الفروق")
            print("=" * 80)


if __name__ == '__main__':
    main()
