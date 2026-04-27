#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
سكريبت تصحيح دفتر الأستاذ - النسخة المتكاملة الاحترافية v3.0
================================================================================

المميزات:
✅ دعم أنواع المستودعات المختلفة (MAIN, PARTNER, EXCHANGE, إلخ)
✅ حساب نسب الشركاء في المخزون تلقائياً
✅ دعم بضاعة الرسم (التجار) مع فصل واضح
✅ تحويل العملات الأجنبية تلقائياً
✅ قيود محاسبية مفصلة لكل نوع
✅ تحققات شاملة قبل وبعد التنفيذ
✅ تقارير تفصيلية للمخزون
✅ معالجة الأخطاء والاستثناءات

الإصدار: 3.0.0
التاريخ: 2026-04-27
================================================================================
"""

import sys
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import create_app
    from extensions import db
    from models import (
        GLBatch, GLEntry, StockLevel, Product, Warehouse,
        WarehouseType, WarehousePartnerShare, Partner, Supplier,
        Currency, ExchangeRate
    )
    from sqlalchemy import func
except ImportError as e:
    print(f"❌ خطأ في استيراد المكتبات: {e}")
    sys.exit(1)


# ==============================================================================
# ثوابت النظام
# ==============================================================================

class AccountCodes:
    """رموز الحسابات المحاسبية"""
    CASH = '1000_CASH'
    ACCOUNTS_RECEIVABLE = '1100_AR'
    INVENTORY = '1200_INVENTORY'
    ACCOUNTS_PAYABLE = '2000_AP'
    EQUITY = '3000_EQUITY'
    PARTNER_EQUITY = '3200_PARTNER_EQUITY'  # تم التصحيح
    SALES = '4000_SALES'
    EXPENSES = '5000_EXPENSES'


class Config:
    """إعدادات النظام"""
    BASE_CURRENCY = 'ILS'
    DECIMAL_PLACES = Decimal('0.01')
    ROUNDING = ROUND_HALF_UP


# ==============================================================================
# هياكل البيانات
# ==============================================================================

@dataclass
class InventoryLineItem:
    """بند مخزون مفصل"""
    product_id: int
    product_name: str
    warehouse_id: int
    warehouse_name: str
    warehouse_type: str
    quantity: int
    unit_price: Decimal
    currency: str
    value_in_ils: Decimal
    partner_id: Optional[int] = None
    partner_name: Optional[str] = None
    partner_share: Optional[Decimal] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None


@dataclass
class InventorySummary:
    """ملخص المخزون مصنف"""
    company_owned: Decimal = Decimal('0')
    partner_shares: Dict[int, Dict] = field(default_factory=dict)
    consignment: Dict[int, Dict] = field(default_factory=dict)
    total: Decimal = Decimal('0')
    line_items: List[InventoryLineItem] = field(default_factory=list)
    
    def calculate_totals(self):
        """حساب الإجماليات"""
        self.total = self.company_owned
        for p in self.partner_shares.values():
            self.total += p['value']
        for c in self.consignment.values():
            self.total += c['value']


@dataclass
class BalanceResult:
    """نتيجة فحص التوازن"""
    assets: Decimal
    liabilities: Decimal
    equity: Decimal
    difference: Decimal
    is_balanced: bool


@dataclass
class EntriesResult:
    """نتيجة فحص القيود"""
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    is_balanced: bool


# ==============================================================================
# كلاس مدير العملات
# ==============================================================================

class CurrencyManager:
    """مدير العملات والتحويلات"""
    
    def __init__(self, session):
        self.session = session
        self._cache = {}
    
    def get_rate(self, from_currency: str, to_currency: str = Config.BASE_CURRENCY) -> Decimal:
        """
        الحصول على سعر الصرف
        
        Args:
            from_currency: العملة المصدر
            to_currency: العملة الهدف (افتراضي: ILS)
            
        Returns:
            سعر الصرف
        """
        if not from_currency or from_currency == to_currency:
            return Decimal('1')
        
        cache_key = f"{from_currency}_{to_currency}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # البحث في جدول أسعار الصرف
        rate = ExchangeRate.query.filter_by(
            base_code=from_currency,
            quote_code=to_currency,
            is_active=True
        ).order_by(ExchangeRate.valid_from.desc()).first()
        
        if rate:
            result = Decimal(str(rate.rate))
        else:
            # محاولة العكس
            reverse_rate = ExchangeRate.query.filter_by(
                base_code=to_currency,
                quote_code=from_currency,
                is_active=True
            ).order_by(ExchangeRate.valid_from.desc()).first()
            
            if reverse_rate:
                result = Decimal('1') / Decimal(str(reverse_rate.rate))
            else:
                # افتراض 1:1 مع تحذير
                print(f"⚠️ تحذير: لم يتم العثور على سعر صرف لـ {from_currency}، استخدام 1:1")
                result = Decimal('1')
        
        self._cache[cache_key] = result
        return result
    
    def convert_to_ils(self, amount: Decimal, currency: str) -> Decimal:
        """تحويل المبلغ إلى الشيكل"""
        rate = self.get_rate(currency)
        return (amount * rate).quantize(Config.DECIMAL_PLACES, rounding=Config.ROUNDING)


# ==============================================================================
# كلاس محلل المخزون
# ==============================================================================

class InventoryAnalyzer:
    """محلل المخزون المتقدم"""
    
    def __init__(self, session, currency_manager):
        self.session = session
        self.currency_mgr = currency_manager
    
    def analyze(self) -> InventorySummary:
        """
        تحليل المخزون بشكل شامل
        
        Returns:
            ملخص المخزون مصنف
        """
        print("\n" + "=" * 80)
        print("📊 تحليل المخزون - مع دعم العملات وأنواع المستودعات")
        print("=" * 80)
        
        summary = InventorySummary()
        warehouses = Warehouse.query.all()
        
        for wh in warehouses:
            self._process_warehouse(wh, summary)
        
        summary.calculate_totals()
        self._display_summary(summary)
        
        return summary
    
    def _process_warehouse(self, warehouse: Warehouse, summary: InventorySummary):
        """معالجة مستودع واحد"""
        stock_levels = StockLevel.query.filter_by(warehouse_id=warehouse.id).all()
        
        for sl in stock_levels:
            if sl.quantity <= 0:
                continue
            
            product = self.session.get(Product, sl.product_id)
            if not product or not product.purchase_price:
                continue
            
            # حساب القيمة
            unit_price = Decimal(str(product.purchase_price))
            currency = product.currency or Config.BASE_CURRENCY
            value_in_ils = self.currency_mgr.convert_to_ils(unit_price * Decimal(sl.quantity), currency)
            
            if value_in_ils <= 0:
                continue
            
            # إنشاء بند تفصيلي
            line_item = InventoryLineItem(
                product_id=product.id,
                product_name=product.name,
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                warehouse_type=warehouse.warehouse_type,
                quantity=sl.quantity,
                unit_price=unit_price,
                currency=currency,
                value_in_ils=value_in_ils
            )
            
            # تصنيف حسب نوع المستودع
            self._classify_line_item(line_item, warehouse, summary)
            
            summary.line_items.append(line_item)
    
    def _classify_line_item(self, item: InventoryLineItem, warehouse: Warehouse, summary: InventorySummary):
        """تصنيف البند حسب نوع المستودع"""
        wh_type = warehouse.warehouse_type
        
        if wh_type == WarehouseType.PARTNER.value:
            # مستودع شراكة
            self._handle_partner_item(item, warehouse, summary)
            
        elif wh_type == WarehouseType.EXCHANGE.value:
            # بضاعة على رسم البيع
            self._handle_consignment_item(item, warehouse, summary)
            
        else:
            # ملكية الشركة (MAIN, INVENTORY, ONLINE, TEMP, OUTLET)
            summary.company_owned += item.value_in_ils
    
    def _handle_partner_item(self, item: InventoryLineItem, warehouse: Warehouse, summary: InventorySummary):
        """معالجة بند شريك"""
        partner_shares = WarehousePartnerShare.query.filter_by(warehouse_id=warehouse.id).all()
        
        if partner_shares:
            remaining = item.value_in_ils
            
            for share in partner_shares:
                partner_id = share.partner_id
                partner = self.session.get(Partner, partner_id)
                share_pct = Decimal(str(share.share_percentage or 0)) / 100
                share_value = (item.value_in_ils * share_pct).quantize(Config.DECIMAL_PLACES)
                
                if partner_id not in summary.partner_shares:
                    summary.partner_shares[partner_id] = {
                        'name': partner.name if partner else f"شريك #{partner_id}",
                        'value': Decimal('0'),
                        'percentage': share.share_percentage
                    }
                
                summary.partner_shares[partner_id]['value'] += share_value
                remaining -= share_value
            
            # الباقي للشركة
            summary.company_owned += remaining
        else:
            summary.company_owned += item.value_in_ils
    
    def _handle_consignment_item(self, item: InventoryLineItem, warehouse: Warehouse, summary: InventorySummary):
        """معالجة بند رسم بيع"""
        supplier_id = warehouse.supplier_id
        
        if supplier_id:
            supplier = self.session.get(Supplier, supplier_id)
            
            if supplier_id not in summary.consignment:
                summary.consignment[supplier_id] = {
                    'name': supplier.name if supplier else f"مورد #{supplier_id}",
                    'value': Decimal('0')
                }
            
            summary.consignment[supplier_id]['value'] += item.value_in_ils
        else:
            summary.company_owned += item.value_in_ils
    
    def _display_summary(self, summary: InventorySummary):
        """عرض الملخص"""
        print(f"\n📦 ملكية الشركة: {summary.company_owned:,.2f} ₪")
        
        if summary.partner_shares:
            print("\n🤝 مشاركة الشركاء:")
            for pid, data in summary.partner_shares.items():
                print(f"  • {data['name']} ({data['percentage']}%): {data['value']:,.2f} ₪")
        
        if summary.consignment:
            print("\n📋 بضاعة على رسم البيع:")
            for sid, data in summary.consignment.items():
                print(f"  • {data['name']}: {data['value']:,.2f} ₪")
        
        print(f"\n💰 إجمالي قيمة المخزون: {summary.total:,.2f} ₪")
        print(f"📊 عدد البنود: {len(summary.line_items)}")


# ==============================================================================
# كلاس منشئ القيود
# ==============================================================================

class EntryBuilder:
    """منشئ القيود المحاسبية"""
    
    def __init__(self, session):
        self.session = session
        self.created_batches = []
    
    def build_inventory_entries(self, summary: InventorySummary) -> bool:
        """
        بناء قيود المخزون الافتتاحية
        
        Args:
            summary: ملخص المخزون
            
        Returns:
            True إذا نجحت العملية
        """
        print("\n" + "=" * 80)
        print("🔧 إنشاء قيود المخزون الافتتاحية المفصلة")
        print("=" * 80)
        
        if summary.total <= 0:
            print("ℹ️ لا يوجد مخزون لإنشاء قيود")
            return False
        
        try:
            # حذف القيود السابقة
            self._delete_existing_entries()
            
            # إنشاء الدفعة الرئيسية
            batch = self._create_batch(
                'INVENTORY_OPENING',
                0,
                'رصيد افتتاحي للمخزون - شامل',
                'ILS'
            )
            
            # 1. مدين: المخزون (الإجمالي)
            self._add_entry(batch, AccountCodes.INVENTORY, summary.total, 0, 'INV-TOTAL')
            
            # 2. دائن: حقوق الشركة
            if summary.company_owned > 0:
                self._add_entry(batch, AccountCodes.EQUITY, 0, summary.company_owned, 'INV-COMPANY')
            
            # 3. دائن: حقوق الشركاء
            for partner_id, data in summary.partner_shares.items():
                if data['value'] > 0:
                    self._add_entry(
                        batch, AccountCodes.PARTNER_EQUITY, 0, data['value'],
                        f'INV-PARTNER-{partner_id}'
                    )
            
            # 4. دائن: ذمم دائنة (للبضاعة على الرسم)
            for supplier_id, data in summary.consignment.items():
                if data['value'] > 0:
                    self._add_entry(
                        batch, AccountCodes.ACCOUNTS_PAYABLE, 0, data['value'],
                        f'INV-CONSIGN-{supplier_id}'
                    )
            
            self.session.commit()
            print(f"✅ تم إنشاء قيود المخزون بنجاح")
            return True
            
        except Exception as e:
            print(f"❌ خطأ: {e}")
            self.session.rollback()
            return False
    
    def _delete_existing_entries(self):
        """حذف القيود السابقة"""
        existing = GLBatch.query.filter(
            GLBatch.source_type == 'INVENTORY_OPENING',
            GLBatch.source_id == 0
        ).all()
        
        for batch in existing:
            print(f"حذف قيد سابق #{batch.id}...")
            GLEntry.query.filter_by(batch_id=batch.id).delete()
            self.session.delete(batch)
        
        self.session.flush()
    
    def _create_batch(self, source_type: str, source_id: int, memo: str, currency: str) -> GLBatch:
        """إنشاء دفعة قيود"""
        batch = GLBatch(
            posted_at=datetime.now(timezone.utc),
            source_type=source_type,
            source_id=source_id,
            purpose='OPENING_BALANCE',
            memo=memo,
            currency=currency,
            status='POSTED'
        )
        self.session.add(batch)
        self.session.flush()
        self.created_batches.append(batch)
        return batch
    
    def _add_entry(self, batch: GLBatch, account: str, debit: Decimal, credit: Decimal, ref: str):
        """إضافة قيد"""
        entry = GLEntry(
            batch_id=batch.id,
            account=account,
            debit=float(debit) if debit > 0 else 0,
            credit=float(credit) if credit > 0 else 0,
            currency='ILS',
            ref=ref
        )
        self.session.add(entry)


# ==============================================================================
# كلاس المدقق
# ==============================================================================

class BalanceChecker:
    """مدقق التوازن المحاسبي"""
    
    def __init__(self, session):
        self.session = session
    
    def check_balance(self) -> BalanceResult:
        """فحص توازن الميزانية"""
        print("\n" + "=" * 80)
        print("📊 فحص توازن الميزانية")
        print("=" * 80)
        
        assets = self._calc_account_type('1', True)
        liabilities = self._calc_account_type('2', False)
        equity = self._calc_account_type('3', False)
        
        diff = assets - (liabilities + equity)
        
        print(f"الأصول: {assets:,.2f} ₪")
        print(f"الخصوم: {liabilities:,.2f} ₪")
        print(f"حقوق الملكية: {equity:,.2f} ₪")
        print(f"الفرق: {diff:,.2f} ₪")
        
        is_balanced = abs(diff) < Decimal('0.01')
        
        if is_balanced:
            print("✅ الميزانية متوازنة")
        else:
            print("⚠️ الميزانية غير متوازنة")
        
        return BalanceResult(assets, liabilities, equity, diff, is_balanced)
    
    def check_entries(self) -> EntriesResult:
        """فحص توازن القيود"""
        print("\n" + "=" * 80)
        print("⚖️ فحص توازن القيود")
        print("=" * 80)
        
        total_debit = self._sum_column('debit')
        total_credit = self._sum_column('credit')
        
        diff = abs(total_debit - total_credit)
        
        print(f"المدين: {total_debit:,.2f} ₪")
        print(f"الدائن: {total_credit:,.2f} ₪")
        print(f"الفرق: {diff:,.2f} ₪")
        
        is_balanced = diff < Decimal('0.01')
        
        if is_balanced:
            print("✅ القيود متوازنة")
        else:
            print("⚠️ القيود غير متوازنة")
        
        return EntriesResult(total_debit, total_credit, diff, is_balanced)
    
    def _calc_account_type(self, prefix: str, is_asset: bool) -> Decimal:
        """حساب نوع حساب"""
        debit = self._sum_by_pattern(f'{prefix}%', 'debit')
        credit = self._sum_by_pattern(f'{prefix}%', 'credit')
        
        if is_asset:
            return debit - credit
        else:
            return credit - debit
    
    def _sum_by_pattern(self, pattern: str, column: str) -> Decimal:
        """جمع حسب النمط"""
        col = GLEntry.debit if column == 'debit' else GLEntry.credit
        result = self.session.query(func.sum(col)).join(GLBatch).filter(
            GLEntry.account.like(pattern),
            GLBatch.status == 'POSTED'
        ).scalar() or 0
        return Decimal(str(result))
    
    def _sum_column(self, column: str) -> Decimal:
        """جمع عمود"""
        col = GLEntry.debit if column == 'debit' else GLEntry.credit
        result = self.session.query(func.sum(col)).join(GLBatch).filter(
            GLBatch.status == 'POSTED'
        ).scalar() or 0
        return Decimal(str(result))


# ==============================================================================
# كلاس التسوية
# ==============================================================================

class BalanceAdjuster:
    """معدل التوازن"""
    
    def __init__(self, session, entry_builder):
        self.session = session
        self.builder = entry_builder
    
    def adjust(self, balance_result: BalanceResult, entries_result: EntriesResult):
        """تسوية الفروق"""
        print("\n" + "=" * 80)
        print("🔧 تسوية الفروق")
        print("=" * 80)
        
        # تسوية فرق الميزانية
        if not balance_result.is_balanced:
            self._adjust_balance(balance_result.difference)
        
        # تسوية فرق القيود
        if not entries_result.is_balanced:
            self._adjust_entries(entries_result.difference)
    
    def _adjust_balance(self, diff: Decimal):
        """تسوية فرق الميزانية"""
        print(f"\nتسوية فرق الميزانية: {diff:,.2f} ₪")
        
        batch = self.builder._create_batch(
            'ADJUSTMENT', 0, 'تسوية توازن الميزانية', 'ILS'
        )
        
        if diff > 0:
            self.builder._add_entry(batch, AccountCodes.EQUITY, 0, diff, 'BALANCE-ADJ')
        else:
            self.builder._add_entry(batch, AccountCodes.EQUITY, abs(diff), 0, 'BALANCE-ADJ')
        
        self.session.commit()
        print("✅ تم تسوية فرق الميزانية")
    
    def _adjust_entries(self, diff: Decimal):
        """تسوية فرق القيود"""
        print(f"\nتسوية فرق القيود: {diff:,.2f} ₪")
        
        batch = self.builder._create_batch(
            'ADJUSTMENT', 0, 'تسوية توازن القيود', 'ILS'
        )
        
        checker = BalanceChecker(self.session)
        result = checker.check_entries()
        current_diff = result.total_debit - result.total_credit
        
        if current_diff > 0:
            self.builder._add_entry(batch, AccountCodes.EQUITY, 0, current_diff, 'ENTRIES-ADJ')
        else:
            self.builder._add_entry(batch, AccountCodes.EQUITY, abs(current_diff), 0, 'ENTRIES-ADJ')
        
        self.session.commit()
        print("✅ تم تسوية فرق القيود")


# ==============================================================================
# الدالة الرئيسية
# ==============================================================================

def main():
    """الدالة الرئيسية"""
    app = create_app()
    
    with app.app_context():
        print("\n" + "=" * 80)
        print("🚀 بدء تصحيح دفتر الأستاذ - النسخة المتكاملة v3.0")
        print("=" * 80)
        
        # إنشاء المكونات
        currency_mgr = CurrencyManager(db.session)
        analyzer = InventoryAnalyzer(db.session, currency_mgr)
        builder = EntryBuilder(db.session)
        checker = BalanceChecker(db.session)
        adjuster = BalanceAdjuster(db.session, builder)
        
        # 1. الفحص الأولي
        print("\n📊 الفحص الأولي:")
        balance_before = checker.check_balance()
        entries_before = checker.check_entries()
        
        if balance_before.is_balanced and entries_before.is_balanced:
            print("\n✅ دفتر الأستاذ متوازن بالفعل!")
            return
        
        # 2. تحليل المخزون
        summary = analyzer.analyze()
        
        # 3. إنشاء القيود
        if summary.total > 0:
            success = builder.build_inventory_entries(summary)
            if not success:
                print("❌ فشل إنشاء قيود المخزون")
                return
        
        # 4. التسوية
        balance_after = checker.check_balance()
        entries_after = checker.check_entries()
        adjuster.adjust(balance_after, entries_after)
        
        # 5. الفحص النهائي
        print("\n" + "=" * 80)
        print("📊 الفحص النهائي:")
        print("=" * 80)
        
        balance_final = checker.check_balance()
        entries_final = checker.check_entries()
        
        # الإحصائيات
        print("\n📈 الإحصائيات:")
        print(f"عدد الدفعات: {GLBatch.query.count()}")
        print(f"عدد القيود: {GLEntry.query.count()}")
        
        # النتيجة
        if balance_final.is_balanced and entries_final.is_balanced:
            print("\n" + "=" * 80)
            print("✅✅✅ دفتر الأستاذ متوازن تماماً! ✅✅✅")
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("⚠️ يرجى مراجعة الفروق المتبقية")
            print("=" * 80)


if __name__ == '__main__':
    main()
