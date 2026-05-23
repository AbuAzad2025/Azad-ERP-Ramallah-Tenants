from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from functools import lru_cache
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload, selectinload

from extensions import db, cache
from models import (
    GLBatch, GLEntry, Account, Sale, Expense, Payment, ServiceRequest,
    Customer, Supplier, Partner, Product, StockLevel, Invoice, PreOrder,
    Shipment, Check, Employee, PaymentSplit
)


class LedgerCache:
    CACHE_TIMEOUT_FX = 3600
    CACHE_TIMEOUT_ACCOUNTS = 1800
    CACHE_TIMEOUT_ENTITIES = 1800
    CACHE_TIMEOUT_STOCK = 600

    @staticmethod
    def get_fx_rate(from_currency: str, to_currency: str, date: datetime) -> Optional[float]:
        if from_currency == to_currency:
            return 1.0
        
        cache_key = f"fx_rate_{from_currency}_{to_currency}_{date.strftime('%Y%m%d')}"
        cached = cache.get(cache_key)
        if cached is not None:
            return float(cached)
        
        try:
            from models import fx_rate
            rate = fx_rate(from_currency, to_currency, date, raise_on_missing=False)
            if rate and rate > 0:
                cache.set(cache_key, float(rate), timeout=LedgerCache.CACHE_TIMEOUT_FX)
                return float(rate)
        except Exception:
            pass
        
        return None

    @staticmethod
    def get_account(code: str) -> Optional[Dict]:
        cache_key = f"account_{code}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        account = Account.query.filter_by(code=code, is_active=True).first()
        if account:
            result = {
                'id': account.id,
                'code': account.code,
                'name': account.name,
                'type': account.type
            }
            cache.set(cache_key, result, timeout=LedgerCache.CACHE_TIMEOUT_ACCOUNTS)
            return result
        return None

    @staticmethod
    def get_entity(entity_type: str, entity_id: int) -> Optional[Dict]:
        if not entity_type or not entity_id:
            return None
        
        cache_key = f"entity_{entity_type}_{entity_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        entity = None
        entity_name = None
        entity_type_ar = None
        
        try:
            if entity_type == 'CUSTOMER':
                entity = db.session.get(Customer, entity_id)
                if entity:
                    entity_name = entity.name
                    entity_type_ar = 'زبون'
            elif entity_type == 'SUPPLIER':
                entity = db.session.get(Supplier, entity_id)
                if entity:
                    entity_name = entity.name
                    entity_type_ar = 'مورد'
            elif entity_type == 'PARTNER':
                entity = db.session.get(Partner, entity_id)
                if entity:
                    entity_name = entity.name
                    entity_type_ar = 'شريك'
            elif entity_type == 'EMPLOYEE':
                entity = db.session.get(Employee, entity_id)
                if entity:
                    entity_name = entity.name
                    entity_type_ar = 'موظف'
        except Exception:
            pass
        
        if entity_name:
            result = {
                'id': entity_id,
                'name': entity_name,
                'type': entity_type,
                'type_ar': entity_type_ar
            }
            cache.set(cache_key, result, timeout=LedgerCache.CACHE_TIMEOUT_ENTITIES)
            return result
        
        return None

    @staticmethod
    def clear_entity_cache(entity_type: str = None, entity_id: int = None):
        if entity_type and entity_id:
            cache.delete(f"entity_{entity_type}_{entity_id}")
        else:
            cache.delete_memoized(LedgerCache.get_entity)


class SmartEntityExtractor:
    @staticmethod
    def _extract_entity_from_expense(expense: Expense) -> Optional[Tuple[str, str, Optional[int], Optional[str]]]:
        if not expense:
            return None
        if expense.customer_id:
            entity_info = LedgerCache.get_entity("CUSTOMER", expense.customer_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if expense.supplier_id:
            entity_info = LedgerCache.get_entity("SUPPLIER", expense.supplier_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if expense.partner_id:
            entity_info = LedgerCache.get_entity("PARTNER", expense.partner_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if expense.employee_id:
            entity_info = LedgerCache.get_entity("EMPLOYEE", expense.employee_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        payee_type = (getattr(expense, "payee_type", "") or "").strip().upper()
        payee_entity_id = getattr(expense, "payee_entity_id", None)
        if payee_type in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"} and payee_entity_id:
            entity_info = LedgerCache.get_entity(payee_type, payee_entity_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        return None

    @staticmethod
    def _extract_entity_from_payment(payment: Payment) -> Optional[Tuple[str, str, Optional[int], Optional[str]]]:
        if not payment:
            return None
        if payment.customer_id:
            entity_info = LedgerCache.get_entity("CUSTOMER", payment.customer_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.supplier_id:
            entity_info = LedgerCache.get_entity("SUPPLIER", payment.supplier_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.partner_id:
            entity_info = LedgerCache.get_entity("PARTNER", payment.partner_id)
            if entity_info:
                return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.expense_id:
            exp_entity = SmartEntityExtractor._extract_entity_from_expense(payment.expense)
            if exp_entity:
                return exp_entity
        if payment.sale_id:
            sale = payment.sale or db.session.get(Sale, payment.sale_id)
            if sale and sale.customer_id:
                entity_info = LedgerCache.get_entity("CUSTOMER", sale.customer_id)
                if entity_info:
                    return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.invoice_id:
            invoice = payment.invoice or db.session.get(Invoice, payment.invoice_id)
            if invoice:
                if invoice.customer_id:
                    entity_info = LedgerCache.get_entity("CUSTOMER", invoice.customer_id)
                    if entity_info:
                        return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
                if invoice.supplier_id:
                    entity_info = LedgerCache.get_entity("SUPPLIER", invoice.supplier_id)
                    if entity_info:
                        return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.service_id:
            service = payment.service or db.session.get(ServiceRequest, payment.service_id)
            if service and service.customer_id:
                entity_info = LedgerCache.get_entity("CUSTOMER", service.customer_id)
                if entity_info:
                    return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        if payment.preorder_id:
            preorder = payment.preorder or db.session.get(PreOrder, payment.preorder_id)
            if preorder:
                if preorder.customer_id:
                    entity_info = LedgerCache.get_entity("CUSTOMER", preorder.customer_id)
                    if entity_info:
                        return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
                if preorder.supplier_id:
                    entity_info = LedgerCache.get_entity("SUPPLIER", preorder.supplier_id)
                    if entity_info:
                        return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
                if preorder.partner_id:
                    entity_info = LedgerCache.get_entity("PARTNER", preorder.partner_id)
                    if entity_info:
                        return (entity_info["name"], entity_info["type_ar"], entity_info["id"], entity_info["type"])
        return None

    @staticmethod
    def extract_from_batch(batch: GLBatch) -> Tuple[str, str, Optional[int], Optional[str]]:
        if batch.entity_type and batch.entity_id:
            entity_info = LedgerCache.get_entity(batch.entity_type, batch.entity_id)
            if entity_info:
                return (
                    entity_info['name'],
                    entity_info['type_ar'],
                    entity_info['id'],
                    entity_info['type']
                )
        
        if batch.source_type and batch.source_id:
            source_type = batch.source_type.upper()
            source_id = batch.source_id
            
            try:
                if source_type == 'PAYMENT':
                    payment = db.session.get(Payment, source_id)
                    if payment:
                        pay_entity = SmartEntityExtractor._extract_entity_from_payment(payment)
                        if pay_entity:
                            return pay_entity
                
                elif source_type == 'PAYMENT_SPLIT':
                    # ✅ دعم PAYMENT_SPLIT - جلب Payment من PaymentSplit
                    split = db.session.get(PaymentSplit, source_id)
                    if split and split.payment:
                        payment = split.payment
                        pay_entity = SmartEntityExtractor._extract_entity_from_payment(payment)
                        if pay_entity:
                            return pay_entity
                
                elif source_type == 'SALE':
                    sale = db.session.get(Sale, source_id)
                    if sale and sale.customer_id:
                        entity_info = LedgerCache.get_entity('CUSTOMER', sale.customer_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                
                elif source_type == 'INVOICE':
                    invoice = db.session.get(Invoice, source_id)
                    if invoice:
                        if invoice.customer_id:
                            entity_info = LedgerCache.get_entity('CUSTOMER', invoice.customer_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif invoice.supplier_id:
                            entity_info = LedgerCache.get_entity('SUPPLIER', invoice.supplier_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                
                elif source_type == 'EXPENSE':
                    expense = db.session.get(Expense, source_id)
                    if expense:
                        if expense.customer_id:
                            entity_info = LedgerCache.get_entity('CUSTOMER', expense.customer_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif expense.supplier_id:
                            entity_info = LedgerCache.get_entity('SUPPLIER', expense.supplier_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif expense.partner_id:
                            entity_info = LedgerCache.get_entity('PARTNER', expense.partner_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif expense.employee_id:
                            entity_info = LedgerCache.get_entity('EMPLOYEE', expense.employee_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif expense.paid_to:
                            return (expense.paid_to, 'جهة', None, 'OTHER')
                        elif expense.payee_name:
                            return (expense.payee_name, 'جهة', None, 'OTHER')
                
                elif source_type == 'SERVICE':
                    service = db.session.get(ServiceRequest, source_id)
                    if service and service.customer_id:
                        entity_info = LedgerCache.get_entity('CUSTOMER', service.customer_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                
                elif source_type == 'PREORDER':
                    preorder = db.session.get(PreOrder, source_id)
                    if preorder:
                        if preorder.customer_id:
                            entity_info = LedgerCache.get_entity('CUSTOMER', preorder.customer_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                        elif preorder.supplier_id:
                            entity_info = LedgerCache.get_entity('SUPPLIER', preorder.supplier_id)
                            if entity_info:
                                return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                
                elif source_type == 'SHIPMENT':
                    shipment = db.session.get(Shipment, source_id)
                    if shipment and shipment.supplier_id:
                        entity_info = LedgerCache.get_entity('SUPPLIER', shipment.supplier_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
            except Exception:
                pass
        
        return ('—', '', None, None)

    @staticmethod
    def extract_from_source(batch: GLBatch) -> Tuple[str, str, Optional[int], Optional[str]]:
        if not batch.source_type or not batch.source_id:
            return ('—', '', None, None)

        source_type = str(batch.source_type).upper()
        source_id = batch.source_id

        try:
            if source_type == 'PAYMENT':
                payment = db.session.get(Payment, source_id)
                if payment:
                    pay_entity = SmartEntityExtractor._extract_entity_from_payment(payment)
                    if pay_entity:
                        return pay_entity

            if source_type == 'PAYMENT_SPLIT':
                split = db.session.get(PaymentSplit, source_id)
                if split and split.payment:
                    payment = split.payment
                    pay_entity = SmartEntityExtractor._extract_entity_from_payment(payment)
                    if pay_entity:
                        return pay_entity

            if source_type == 'SALE':
                sale = db.session.get(Sale, source_id)
                if sale and sale.customer_id:
                    entity_info = LedgerCache.get_entity('CUSTOMER', sale.customer_id)
                    if entity_info:
                        return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])

            if source_type == 'INVOICE':
                invoice = db.session.get(Invoice, source_id)
                if invoice:
                    if invoice.customer_id:
                        entity_info = LedgerCache.get_entity('CUSTOMER', invoice.customer_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif invoice.supplier_id:
                        entity_info = LedgerCache.get_entity('SUPPLIER', invoice.supplier_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])

            if source_type == 'EXPENSE':
                expense = db.session.get(Expense, source_id)
                if expense:
                    if expense.customer_id:
                        entity_info = LedgerCache.get_entity('CUSTOMER', expense.customer_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif expense.supplier_id:
                        entity_info = LedgerCache.get_entity('SUPPLIER', expense.supplier_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif expense.partner_id:
                        entity_info = LedgerCache.get_entity('PARTNER', expense.partner_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif expense.employee_id:
                        entity_info = LedgerCache.get_entity('EMPLOYEE', expense.employee_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif expense.paid_to:
                        return (expense.paid_to, 'جهة', None, 'OTHER')
                    elif expense.payee_name:
                        return (expense.payee_name, 'جهة', None, 'OTHER')

            if source_type == 'SERVICE':
                service = db.session.get(ServiceRequest, source_id)
                if service and service.customer_id:
                    entity_info = LedgerCache.get_entity('CUSTOMER', service.customer_id)
                    if entity_info:
                        return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])

            if source_type == 'PREORDER':
                preorder = db.session.get(PreOrder, source_id)
                if preorder:
                    if preorder.customer_id:
                        entity_info = LedgerCache.get_entity('CUSTOMER', preorder.customer_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
                    elif preorder.supplier_id:
                        entity_info = LedgerCache.get_entity('SUPPLIER', preorder.supplier_id)
                        if entity_info:
                            return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])

            if source_type == 'SHIPMENT':
                shipment = db.session.get(Shipment, source_id)
                if shipment and shipment.supplier_id:
                    entity_info = LedgerCache.get_entity('SUPPLIER', shipment.supplier_id)
                    if entity_info:
                        return (entity_info['name'], entity_info['type_ar'], entity_info['id'], entity_info['type'])
        except Exception:
            pass

        return ('—', '', None, None)


class LedgerQueryOptimizer:
    @staticmethod
    def get_sales_optimized(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, limit: int = 50000):
        query = Sale.query.options(
            joinedload(Sale.customer)
        ).filter(Sale.status == 'CONFIRMED')
        
        if from_date:
            query = query.filter(Sale.sale_date >= from_date)
        if to_date:
            query = query.filter(Sale.sale_date <= to_date)
        
        return query.order_by(Sale.sale_date).limit(limit).all()

    @staticmethod
    def get_expenses_optimized(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, limit: int = 50000):
        query = Expense.query.options(
            joinedload(Expense.employee),
            joinedload(Expense.partner),
            joinedload(Expense.type)
        )
        
        if from_date:
            query = query.filter(Expense.date >= from_date)
        if to_date:
            query = query.filter(Expense.date <= to_date)
        
        return query.order_by(Expense.date).limit(limit).all()

    @staticmethod
    def get_payments_optimized(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, limit: int = 50000):
        query = Payment.query.options(
            joinedload(Payment.customer),
            joinedload(Payment.supplier),
            joinedload(Payment.partner),
            selectinload(Payment.splits)
        ).filter(
            Payment.status.in_(['COMPLETED', 'PENDING', 'FAILED'])
        )
        
        if from_date:
            query = query.filter(Payment.payment_date >= from_date)
        if to_date:
            query = query.filter(Payment.payment_date <= to_date)
        
        return query.order_by(Payment.payment_date).limit(limit).all()

    @staticmethod
    def get_services_optimized(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, limit: int = 10000):
        query = ServiceRequest.query.options(
            joinedload(ServiceRequest.customer)
        )
        
        if from_date:
            query = query.filter(ServiceRequest.created_at >= from_date)
        if to_date:
            query = query.filter(ServiceRequest.created_at <= to_date)
        
        return query.order_by(ServiceRequest.created_at).limit(limit).all()

    @staticmethod
    def get_checks_for_payment(payment_id: int) -> List[Check]:
        cache_key = f"payment_checks_{payment_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        checks = Check.query.filter(Check.payment_id == payment_id).all()
        cache.set(cache_key, checks, timeout=300)
        return checks

    @staticmethod
    def get_checks_for_splits(split_ids: List[int]) -> List[Check]:
        if not split_ids:
            return []
        
        cache_key = f"split_checks_{hash(tuple(split_ids))}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        checks = Check.query.filter(
            Check.reference_number.in_([f"PMT-SPLIT-{sid}" for sid in split_ids])
        ).all()
        cache.set(cache_key, checks, timeout=300)
        return checks


class CurrencyConverter:
    @staticmethod
    def convert_to_ils(amount: float, currency: str, date: datetime, fx_rate_used: Optional[float] = None) -> float:
        if currency == 'ILS':
            return amount
        
        if fx_rate_used and fx_rate_used > 0:
            return float(amount * float(fx_rate_used))
        
        rate = LedgerCache.get_fx_rate(currency, 'ILS', date)
        if rate and rate > 0:
            return float(amount * float(rate))
        
        return amount


class LedgerStatisticsCalculator:
    @staticmethod
    def calculate_sales_stats(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None) -> Dict[str, float]:
        cache_key = f"ledger_stats_sales_{from_date.strftime('%Y%m%d') if from_date else 'all'}_{to_date.strftime('%Y%m%d') if to_date else 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        sales = LedgerQueryOptimizer.get_sales_optimized(from_date, to_date)
        total = 0.0
        
        for sale in sales:
            amount = CurrencyConverter.convert_to_ils(
                float(sale.total_amount or 0),
                sale.currency or 'ILS',
                sale.sale_date,
                getattr(sale, 'fx_rate_used', None)
            )
            total += amount
        
        result = {'total_sales': total}
        cache.set(cache_key, result, timeout=600)
        return result

    @staticmethod
    def calculate_expenses_stats(from_date: Optional[datetime] = None, to_date: Optional[datetime] = None) -> Dict[str, float]:
        cache_key = f"ledger_stats_expenses_{from_date.strftime('%Y%m%d') if from_date else 'all'}_{to_date.strftime('%Y%m%d') if to_date else 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        expenses = LedgerQueryOptimizer.get_expenses_optimized(from_date, to_date)
        total = 0.0
        
        for expense in expenses:
            amount = CurrencyConverter.convert_to_ils(
                float(expense.amount or 0),
                expense.currency or 'ILS',
                expense.date,
                getattr(expense, 'fx_rate_used', None)
            )
            total += amount
        
        result = {'total_expenses': total}
        cache.set(cache_key, result, timeout=600)
        return result


def clear_ledger_cache():
    cache.delete_memoized(LedgerCache.get_fx_rate)
    cache.delete_memoized(LedgerCache.get_account)
    cache.delete_memoized(LedgerCache.get_entity)
    cache.delete_memoized(LedgerQueryOptimizer.get_checks_for_payment)
    cache.delete_memoized(LedgerQueryOptimizer.get_checks_for_splits)
    cache.delete_memoized(LedgerStatisticsCalculator.calculate_sales_stats)
    cache.delete_memoized(LedgerStatisticsCalculator.calculate_expenses_stats)


def clear_entity_cache_on_update(entity_type: str, entity_id: int):
    LedgerCache.clear_entity_cache(entity_type, entity_id)

