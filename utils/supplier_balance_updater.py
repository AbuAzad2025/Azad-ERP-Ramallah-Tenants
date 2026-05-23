from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session, joinedload
from extensions import db


def convert_amount(amount, from_currency, to_currency, date=None):
    try:
        from models import convert_amount as _convert_amount
        return _convert_amount(amount, from_currency, to_currency, date)
    except Exception:
        return Decimal(str(amount))


def get_supplier_from_customer(customer_id, session=None):
    if not customer_id:
        return None
    from models import Supplier
    if not session:
        session = db.session
    supplier = session.query(Supplier).filter(Supplier.customer_id == customer_id).first()
    return supplier.id if supplier else None


def calculate_supplier_balance_components(supplier_id, session=None):
    if not supplier_id:
        return None
    
    from models import (
        Supplier, ExchangeTransaction, Sale, SaleReturn, SaleReturnLine, ServiceRequest, PreOrder, Invoice,
        Payment, PaymentDirection, PaymentStatus, PaymentMethod, PaymentEntityType, Check, CheckStatus,
        Expense, ExpenseType, Warehouse, WarehouseType, Product
    )
    
    if not session:
        session = db.session
    
    supplier = session.get(Supplier, supplier_id)
    if not supplier:
        return None
    
    result = {
        'exchange_items_balance': Decimal('0.00'),
        'sale_returns_from_supplier': Decimal('0.00'),
        'sale_returns_from_customer': Decimal('0.00'),
        'sales_balance': Decimal('0.00'),
        'services_balance': Decimal('0.00'),
        'preorders_balance': Decimal('0.00'),
        'payments_in_balance': Decimal('0.00'),
        'payments_out_balance': Decimal('0.00'),
        'preorders_prepaid_balance': Decimal('0.00'),
        'returns_balance': Decimal('0.00'),
        'expenses_service_supply': Decimal('0.00'),
        'expenses_normal': Decimal('0.00'),
        'returned_checks_in_balance': Decimal('0.00'),
        'returned_checks_out_balance': Decimal('0.00'),
    }
    
    try:
        exchange_warehouses = session.query(Warehouse.id).filter(
            Warehouse.supplier_id == supplier_id,
            Warehouse.warehouse_type == WarehouseType.EXCHANGE.value
        ).all()
        warehouse_ids = [w[0] for w in exchange_warehouses]
        
        exchange_in_transactions = session.query(ExchangeTransaction).options(
            joinedload(ExchangeTransaction.product)
        ).filter(
            ExchangeTransaction.supplier_id == supplier_id,
            ExchangeTransaction.direction.in_(['IN', 'PURCHASE', 'CONSIGN_IN'])
        ).all()
        
        for tx in exchange_in_transactions:
            qty = Decimal(str(tx.quantity or 0))
            unit_cost = Decimal(str(tx.unit_cost or 0))
            
            if unit_cost == 0:
                if tx.product and tx.product.purchase_price:
                    unit_cost = Decimal(str(tx.product.purchase_price))
            
            if unit_cost > 0:
                value_ils = qty * unit_cost
                product_currency = getattr(tx.product, 'currency', 'ILS') if tx.product else 'ILS'
                if product_currency != 'ILS':
                    try:
                        value_ils = convert_amount(value_ils, product_currency, "ILS", tx.created_at)
                    except Exception:
                        pass
                result['exchange_items_balance'] += value_ils
        
        if warehouse_ids:
            exchange_out_transactions = session.query(ExchangeTransaction).options(
                joinedload(ExchangeTransaction.product)
            ).filter(
                ExchangeTransaction.warehouse_id.in_(warehouse_ids),
                ExchangeTransaction.direction.in_(['OUT', 'RETURN', 'CONSIGN_OUT'])
            ).all()
            
            for tx in exchange_out_transactions:
                qty = Decimal(str(tx.quantity or 0))
                unit_cost = Decimal(str(tx.unit_cost or 0))
                
                if unit_cost == 0:
                    if tx.product and tx.product.purchase_price:
                        unit_cost = Decimal(str(tx.product.purchase_price))
                
                if unit_cost > 0:
                    value_ils = qty * unit_cost
                    product_currency = getattr(tx.product, 'currency', 'ILS') if tx.product else 'ILS'
                    if product_currency != 'ILS':
                        try:
                            value_ils = convert_amount(value_ils, product_currency, "ILS", tx.created_at)
                        except Exception:
                            pass
                    result['exchange_items_balance'] -= value_ils
                    result['returns_balance'] += value_ils
        
        if supplier.customer_id:
            sale_returns = session.query(SaleReturn).filter(
                SaleReturn.customer_id == supplier.customer_id,
                SaleReturn.status == 'CONFIRMED'
            ).all()
            
            from models import SaleReturnLine
            for sr in sale_returns:
                amt = Decimal(str(sr.total_amount or 0))
                if sr.currency != "ILS":
                    try:
                        amt = convert_amount(amt, sr.currency, "ILS", sr.created_at)
                    except Exception:
                        pass
                
                has_supplier_liability = session.query(SaleReturnLine).filter(
                    SaleReturnLine.sale_return_id == sr.id,
                    SaleReturnLine.liability_party == 'SUPPLIER'
                ).first()
                
                if has_supplier_liability:
                    result['sale_returns_from_customer'] += amt
                else:
                    result['sale_returns_from_supplier'] += amt
            
            sales = session.query(Sale).filter(
                Sale.customer_id == supplier.customer_id,
                Sale.status == 'CONFIRMED'
            ).all()
            
            for sale in sales:
                amt = Decimal(str(sale.total_amount or 0))
                if sale.currency != "ILS":
                    try:
                        amt = convert_amount(amt, sale.currency, "ILS", sale.sale_date)
                    except Exception:
                        pass
                result['sales_balance'] += amt
            
            services = session.query(ServiceRequest).filter(
                ServiceRequest.customer_id == supplier.customer_id,
                ServiceRequest.status == 'COMPLETED'
            ).all()
            
            for service in services:
                amt = Decimal(str(service.total_amount or 0))
                if service.currency != "ILS":
                    try:
                        amt = convert_amount(amt, service.currency, "ILS", service.received_at)
                    except Exception:
                        pass
                result['services_balance'] += amt
            
            preorders = session.query(PreOrder).filter(
                PreOrder.customer_id == supplier.customer_id,
                PreOrder.status.in_(['CONFIRMED', 'COMPLETED', 'DELIVERED']),
                PreOrder.status != 'FULFILLED'
            ).all()
            
            for po in preorders:
                amt = Decimal(str(po.total_amount or 0))
                if po.currency != "ILS":
                    try:
                        amt = convert_amount(amt, po.currency, "ILS", po.created_at)
                    except Exception:
                        pass
                result['preorders_balance'] += amt
                
                prepaid = Decimal(str(po.prepaid_amount or 0))
                if prepaid > 0:
                    if po.currency != "ILS":
                        try:
                            prepaid = convert_amount(prepaid, po.currency, "ILS", po.preorder_date or po.created_at)
                        except Exception:
                            pass
                    result['payments_in_balance'] += prepaid
        
        direct_payments_in = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).outerjoin(
            PreOrder, Payment.preorder_id == PreOrder.id
        ).filter(
            Payment.supplier_id == supplier_id,
            Payment.direction == PaymentDirection.IN,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
            or_(
                Payment.preorder_id.is_(None),
                Payment.sale_id.isnot(None),
                PreOrder.status == 'FULFILLED'
            )
        ).all()
        
        for p in direct_payments_in:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency != "ILS":
                try:
                    amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                except Exception:
                    pass
            result['payments_in_balance'] += amt
        
        if supplier.customer_id:
            seen_ids = {p.id for p in direct_payments_in}
            customer_payments_in = (
                session.query(Payment)
                .outerjoin(Check, Check.payment_id == Payment.id)
                .outerjoin(Sale, Payment.sale_id == Sale.id)
                .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
                .outerjoin(ServiceRequest, Payment.service_id == ServiceRequest.id)
                .outerjoin(PreOrder, Payment.preorder_id == PreOrder.id)
                .outerjoin(Expense, Payment.expense_id == Expense.id)
                .filter(
                    Payment.direction == PaymentDirection.IN,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
                    or_(
                        Payment.customer_id == supplier.customer_id,
                        Sale.customer_id == supplier.customer_id,
                        Invoice.customer_id == supplier.customer_id,
                        ServiceRequest.customer_id == supplier.customer_id,
                        PreOrder.customer_id == supplier.customer_id,
                        Expense.customer_id == supplier.customer_id,
                    ),
                    or_(
                        Payment.preorder_id.is_(None),
                        Payment.sale_id.isnot(None),
                        PreOrder.status == 'FULFILLED',
                    ),
                )
                .distinct()
                .all()
            )
            for p in customer_payments_in:
                if p.id in seen_ids:
                    continue
                seen_ids.add(p.id)
                amt = Decimal(str(p.total_amount or 0))
                if p.currency != "ILS":
                    try:
                        amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                    except Exception:
                        pass
                result['payments_in_balance'] += amt
        
        direct_payments_out = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            Payment.supplier_id == supplier_id,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING])
        ).all()
        
        for p in direct_payments_out:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency != "ILS":
                try:
                    amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                except Exception:
                    pass
            result['payments_out_balance'] += amt
        
        # البحث عن دفعات مرتبطة بمصروفات المورد
        from models import Expense
        expense_payments_out = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).join(
            Expense, Expense.id == Payment.expense_id
        ).filter(
            or_(
                Expense.supplier_id == supplier_id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
            ),
            Payment.entity_type == PaymentEntityType.EXPENSE.value,
            Payment.direction == PaymentDirection.OUT,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING])
        ).all()
        
        seen_payment_ids = {p.id for p in direct_payments_out}
        for p in expense_payments_out:
            if p.id not in seen_payment_ids:
                seen_payment_ids.add(p.id)
                amt = Decimal(str(p.total_amount or 0))
                if p.currency != "ILS":
                    try:
                        amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                    except Exception:
                        pass
                result['payments_out_balance'] += amt
        
        if supplier.customer_id:
            seen_ids = {p.id for p in direct_payments_out} | {p.id for p in expense_payments_out}
            customer_payments_out = (
                session.query(Payment)
                .outerjoin(Check, Check.payment_id == Payment.id)
                .outerjoin(Sale, Payment.sale_id == Sale.id)
                .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
                .outerjoin(ServiceRequest, Payment.service_id == ServiceRequest.id)
                .outerjoin(PreOrder, Payment.preorder_id == PreOrder.id)
                .outerjoin(Expense, Payment.expense_id == Expense.id)
                .filter(
                    Payment.direction == PaymentDirection.OUT,
                    Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
                    or_(
                        Payment.customer_id == supplier.customer_id,
                        Sale.customer_id == supplier.customer_id,
                        Invoice.customer_id == supplier.customer_id,
                        ServiceRequest.customer_id == supplier.customer_id,
                        PreOrder.customer_id == supplier.customer_id,
                        Expense.customer_id == supplier.customer_id,
                    ),
                    or_(
                        Payment.preorder_id.is_(None),
                        Payment.sale_id.isnot(None),
                        PreOrder.status == 'FULFILLED',
                    ),
                )
                .distinct()
                .all()
            )
            for p in customer_payments_out:
                if p.id in seen_ids:
                    continue
                seen_ids.add(p.id)
                amt = Decimal(str(p.total_amount or 0))
                if p.currency != "ILS":
                    try:
                        amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                    except Exception:
                        pass
                result['payments_out_balance'] += amt
        
        returned_checks_in_conditions = [Payment.supplier_id == supplier_id]
        if supplier.customer_id:
            returned_checks_in_conditions.append(Payment.customer_id == supplier.customer_id)
        
        returned_checks_in = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            or_(*returned_checks_in_conditions),
            Payment.direction == PaymentDirection.IN,
            or_(
                Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED]),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE
                )
            )
        ).all()
        
        seen_ids = set()
        for p in returned_checks_in:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                amt = Decimal(str(p.total_amount or 0))
                if p.currency != "ILS":
                    try:
                        amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                    except Exception:
                        pass
                result['returned_checks_in_balance'] += amt
        
        returned_checks_out_conditions = [Payment.supplier_id == supplier_id]
        if supplier.customer_id:
            returned_checks_out_conditions.append(Payment.customer_id == supplier.customer_id)
        
        returned_checks_out = session.query(Payment).outerjoin(
            Check, Check.payment_id == Payment.id
        ).filter(
            or_(*returned_checks_out_conditions),
            Payment.direction == PaymentDirection.OUT,
            or_(
                Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED]),
                and_(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.method == PaymentMethod.CHEQUE
                )
            )
        ).all()
        
        seen_ids = set()
        for p in returned_checks_out:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                amt = Decimal(str(p.total_amount or 0))
                if p.currency != "ILS":
                    try:
                        amt = convert_amount(amt, p.currency, "ILS", p.payment_date)
                    except Exception:
                        pass
                result['returned_checks_out_balance'] += amt
        
        manual_checks_in = session.query(Check).filter(
            Check.supplier_id == supplier_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.IN,
            ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
        ).all()
        
        for check in manual_checks_in:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                except Exception:
                    pass
            result['payments_in_balance'] += amt
        
        manual_checks_out = session.query(Check).filter(
            Check.supplier_id == supplier_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.OUT,
            ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
        ).all()
        
        for check in manual_checks_out:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                except Exception:
                    pass
            result['payments_out_balance'] += amt
        
        manual_returned_checks_in = session.query(Check).filter(
            Check.supplier_id == supplier_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.IN,
            Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
        ).all()
        
        for check in manual_returned_checks_in:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                except Exception:
                    pass
            result['returned_checks_in_balance'] += amt
        
        manual_returned_checks_out = session.query(Check).filter(
            Check.supplier_id == supplier_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.OUT,
            Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
        ).all()
        
        for check in manual_returned_checks_out:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                except Exception:
                    pass
            result['returned_checks_out_balance'] += amt
        
        if supplier.customer_id:
            customer_manual_checks_in = session.query(Check).filter(
                Check.customer_id == supplier.customer_id,
                Check.payment_id.is_(None),
                Check.direction == PaymentDirection.IN,
                ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
            ).all()
            
            for check in customer_manual_checks_in:
                amt = Decimal(str(check.amount or 0))
                if check.currency != "ILS":
                    try:
                        amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                    except Exception:
                        pass
                result['payments_in_balance'] += amt
            
            customer_manual_checks_out = session.query(Check).filter(
                Check.customer_id == supplier.customer_id,
                Check.payment_id.is_(None),
                Check.direction == PaymentDirection.OUT,
                ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
            ).all()
            
            for check in customer_manual_checks_out:
                amt = Decimal(str(check.amount or 0))
                if check.currency != "ILS":
                    try:
                        amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                    except Exception:
                        pass
                result['payments_out_balance'] += amt
            
            customer_manual_returned_checks_in = session.query(Check).filter(
                Check.customer_id == supplier.customer_id,
                Check.payment_id.is_(None),
                Check.direction == PaymentDirection.IN,
                Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
            ).all()
            
            for check in customer_manual_returned_checks_in:
                amt = Decimal(str(check.amount or 0))
                if check.currency != "ILS":
                    try:
                        amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                    except Exception:
                        pass
                result['returned_checks_in_balance'] += amt
            
            customer_manual_returned_checks_out = session.query(Check).filter(
                Check.customer_id == supplier.customer_id,
                Check.payment_id.is_(None),
                Check.direction == PaymentDirection.OUT,
                Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
            ).all()
            
            for check in customer_manual_returned_checks_out:
                amt = Decimal(str(check.amount or 0))
                if check.currency != "ILS":
                    try:
                        amt = convert_amount(amt, check.currency, "ILS", check.check_date)
                    except Exception:
                        pass
                result['returned_checks_out_balance'] += amt
        
        damaged_items = session.query(SaleReturnLine).join(
            SaleReturn, SaleReturnLine.sale_return_id == SaleReturn.id
        ).join(
            Product, SaleReturnLine.product_id == Product.id
        ).filter(
            SaleReturnLine.condition.in_(['DAMAGED', 'UNUSABLE']),
            SaleReturnLine.liability_party == 'SUPPLIER',
            Product.supplier_id == supplier_id,
            SaleReturn.status == 'CONFIRMED'
        ).all()
        
        for damaged in damaged_items:
            qty = Decimal(str(damaged.quantity or 0))
            cost_price = Decimal(str(damaged.product.cost_price or 0))
            
            if cost_price == 0 and damaged.product.purchase_price:
                cost_price = Decimal(str(damaged.product.purchase_price))
            
            if cost_price > 0:
                value_ils = qty * cost_price
                product_currency = getattr(damaged.product, 'currency', 'ILS') or 'ILS'
                if product_currency != 'ILS':
                    try:
                        value_ils = convert_amount(value_ils, product_currency, "ILS", damaged.sale_return.created_at if damaged.sale_return else datetime.now(timezone.utc).replace(tzinfo=None))
                    except Exception:
                        pass
                result['exchange_items_balance'] -= value_ils
        
        expenses = session.query(Expense).join(ExpenseType).filter(
            or_(
                Expense.supplier_id == supplier_id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
            )
        ).all()
        
        for exp in expenses:
            amt = Decimal(str(exp.amount or 0))
            if exp.currency != "ILS":
                try:
                    amt = convert_amount(amt, exp.currency, "ILS", exp.date)
                except Exception:
                    pass
            
            exp_type = session.query(ExpenseType).filter(ExpenseType.id == exp.type_id).first()
            exp_type_code = exp_type.code.upper() if exp_type and exp_type.code else None
            
            if exp_type_code in ['SUPPLIER_EXPENSE', 'PARTNER_EXPENSE']:
                result['expenses_service_supply'] += amt
            else:
                result['expenses_normal'] += amt
        
    except Exception as e:
        from flask import current_app
        try:
            current_app.logger.error(f"خطأ في حساب مكونات رصيد المورد #{supplier_id}: {e}")
        except:
            pass
        return None
    
    return result


def update_supplier_balance_components(supplier_id, session=None, emit: bool = True):
    if not supplier_id:
        return
    
    from models import Supplier
    from sqlalchemy.orm import Session as _SA_Session
    from sqlalchemy import text as sa_text
    from sqlalchemy.engine import Connection
    
    if not session:
        session = db.session
    
    try:
        from sqlalchemy.orm import Session
        
        if isinstance(session, Connection):
            session = Session(bind=session)
        
        if isinstance(session, Session):
            supplier = session.get(Supplier, supplier_id)
            if not supplier:
                return
            
            components = calculate_supplier_balance_components(supplier_id, session)
            
            if not components:
                return
            
            opening_balance = Decimal(str(supplier.opening_balance or 0))
            if supplier.currency and supplier.currency != "ILS":
                try:
                    opening_balance = convert_amount(opening_balance, supplier.currency, "ILS")
                except Exception:
                    pass
            
            sale_returns_total = (
                Decimal(str(components.get('sale_returns_from_supplier', 0) or 0)) +
                Decimal(str(components.get('sale_returns_from_customer', 0) or 0))
            )
            from utils.accounting_formulas import (
                supplier_balance_from_components,
                supplier_obligations_total,
                supplier_rights_total,
            )
            supplier_credits = supplier_rights_total(components)
            supplier_debits = supplier_obligations_total(components)
            current_balance = supplier_balance_from_components(opening_balance, components)
            
            supplier.exchange_items_balance = Decimal(str(components.get('exchange_items_balance', 0)))
            supplier.sale_returns_balance = sale_returns_total
            supplier.sales_balance = Decimal(str(components.get('sales_balance', 0)))
            supplier.services_balance = Decimal(str(components.get('services_balance', 0)))
            supplier.preorders_balance = Decimal(str(components.get('preorders_balance', 0)))
            supplier.payments_in_balance = Decimal(str(components.get('payments_in_balance', 0)))
            supplier.payments_out_balance = Decimal(str(components.get('payments_out_balance', 0)))
            supplier.returns_balance = Decimal(str(components.get('returns_balance', 0)))
            supplier.expenses_balance = Decimal(str(components.get('expenses_normal', 0) or 0))
            supplier.service_expenses_balance = Decimal(str(components.get('expenses_service_supply', 0) or 0))
            supplier.returned_checks_in_balance = Decimal(str(components.get('returned_checks_in_balance', 0)))
            supplier.returned_checks_out_balance = Decimal(str(components.get('returned_checks_out_balance', 0)))
            supplier.current_balance = current_balance
            
            session.flush()
            if emit:
                try:
                    from helpers.balance_events import emit_balance_update
                    emit_balance_update('supplier', supplier_id, float(current_balance))
                except Exception:
                    pass
        else:
            components = calculate_supplier_balance_components(supplier_id, session)
            
            if not components:
                return
            
            result = session.execute(
                sa_text("SELECT opening_balance, currency FROM suppliers WHERE id = :id"),
                {"id": supplier_id}
            ).fetchone()
            
            if not result:
                return
            
            opening_balance = Decimal(str(result[0] or 0))
            supplier_currency = result[1] if len(result) > 1 else "ILS"
            
            if supplier_currency and supplier_currency != "ILS":
                try:
                    opening_balance = convert_amount(opening_balance, supplier_currency, "ILS")
                except Exception:
                    pass
            
            sale_returns_total = (
                Decimal(str(components.get('sale_returns_from_supplier', 0) or 0)) +
                Decimal(str(components.get('sale_returns_from_customer', 0) or 0))
            )
            from utils.accounting_formulas import (
                supplier_balance_from_components,
                supplier_obligations_total,
                supplier_rights_total,
            )
            supplier_credits = supplier_rights_total(components)
            supplier_debits = supplier_obligations_total(components)
            current_balance = supplier_balance_from_components(opening_balance, components)
            
            session.execute(
                sa_text("""
                    UPDATE suppliers 
                    SET current_balance = :balance,
                        exchange_items_balance = :exchange_items,
                        sale_returns_balance = :sale_returns,
                        sales_balance = :sales,
                        services_balance = :services,
                        payments_in_balance = :payments_in,
                        payments_out_balance = :payments_out,
                        returns_balance = :returns,
                        expenses_balance = :expenses,
                        service_expenses_balance = :service_expenses,
                        returned_checks_in_balance = :returned_checks_in,
                        returned_checks_out_balance = :returned_checks_out,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": supplier_id,
                    "balance": float(current_balance),
                    "exchange_items": float(components.get('exchange_items_balance', 0)),
                    "sale_returns": float(sale_returns_total),
                    "sales": float(components.get('sales_balance', 0)),
                    "services": float(components.get('services_balance', 0)),
                    "payments_in": float(components.get('payments_in_balance', 0)),
                    "payments_out": float(components.get('payments_out_balance', 0)),
                    "returns": float(components.get('returns_balance', 0)),
                    "expenses": float(components.get('expenses_normal', 0) or 0),
                    "service_expenses": float(components.get('expenses_service_supply', 0) or 0),
                    "returned_checks_in": float(components.get('returned_checks_in_balance', 0)),
                    "returned_checks_out": float(components.get('returned_checks_out_balance', 0))
                }
            )
            if emit:
                try:
                    from helpers.balance_events import emit_balance_update
                    emit_balance_update('supplier', supplier_id, float(current_balance))
                except Exception:
                    pass
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.debug(f"Error updating supplier balance {supplier_id}: {e}")
        except:
            pass


def build_supplier_balance_view(supplier_id, session=None):
    if not supplier_id:
        return {"success": False, "error": "supplier_id is required"}
    session = session or db.session
    from models import Supplier
    supplier = session.get(Supplier, supplier_id)
    if not supplier:
        return {"success": False, "error": "Supplier not found"}
    components = calculate_supplier_balance_components(supplier_id, session)
    if not components:
        return {"success": False, "error": "Unable to calculate supplier balance"}

    def _dec(value):
        return Decimal(str(value or 0))

    def _component(key):
        return _dec(components.get(key, 0))

    opening_balance = _dec(supplier.opening_balance or 0)
    if supplier.currency and supplier.currency != "ILS":
        try:
            opening_balance = convert_amount(opening_balance, supplier.currency, "ILS")
        except Exception:
            pass

    from utils.accounting_formulas import (
        supplier_balance_from_components,
        supplier_obligations_total,
        supplier_rights_total,
    )

    rights_rows = [
        {"key": "exchange_items_balance", "label": "قطع التبادل", "amount": _component("exchange_items_balance"), "flow": "EXCHANGE"},
        {"key": "expenses_service_supply", "label": "توريد خدمة", "amount": _component("expenses_service_supply"), "flow": "SERVICE_SUPPLY"},
        {"key": "expenses_normal", "label": "مصروفات عادية", "amount": _component("expenses_normal"), "flow": "EXPENSE"},
        {"key": "sale_returns_from_supplier", "label": "مرتجع مبيعات (من المورد)", "amount": _component("sale_returns_from_supplier"), "flow": "SALE_RETURN_SUPPLIER"},
        {"key": "sale_returns_from_customer", "label": "مرتجع مبيعات (من زبون مرتبط)", "amount": _component("sale_returns_from_customer"), "flow": "SALE_RETURN_CUSTOMER"},
        {"key": "payments_in_balance", "label": "دفعات واردة منه", "amount": _component("payments_in_balance"), "flow": "PAYMENT_IN"},
        {"key": "returned_checks_out_balance", "label": "شيكات صادرة له ومرتجعة", "amount": _component("returned_checks_out_balance"), "flow": "RETURNED_OUT"},
    ]

    obligations_rows = [
        {"key": "returns_balance", "label": "مرتجعات توريد", "amount": _component("returns_balance"), "flow": "RETURN_SUPPLY"},
        {"key": "sales_balance", "label": "مبيعات له (زبون مرتبط)", "amount": _component("sales_balance"), "flow": "SALE"},
        {"key": "services_balance", "label": "خدمات له", "amount": _component("services_balance"), "flow": "SERVICE"},
        {"key": "preorders_balance", "label": "حجوزات له", "amount": _component("preorders_balance"), "flow": "PREORDER"},
        {"key": "payments_out_balance", "label": "دفعات دفعنا له", "amount": _component("payments_out_balance"), "flow": "PAYMENT_OUT"},
        {"key": "returned_checks_in_balance", "label": "شيكات واردة منه ومرتجعة", "amount": _component("returned_checks_in_balance"), "flow": "RETURNED_IN"},
    ]

    rights_total = supplier_rights_total(components)
    obligations_total = supplier_obligations_total(components)
    stored_balance = _dec(supplier.current_balance or 0)
    calculated_balance = supplier_balance_from_components(opening_balance, components)
    tolerance = Decimal("0.01")

    def _serialize(rows):
        ordered = sorted(rows, key=lambda r: (abs(r["amount"]), r["label"]), reverse=True)
        return [
            {
                "key": row["key"],
                "label": row["label"],
                "flow": row.get("flow"),
                "amount": float(row["amount"]),
            }
            for row in ordered
        ]

    def _direction_text(amount):
        if amount > 0:
            return "له علينا"
        if amount < 0:
            return "عليه لنا"
        return "متوازن"

    def _action_text(amount):
        if amount > 0:
            return "يجب أن ندفع له"
        if amount < 0:
            return "يجب أن يدفع لنا"
        return "لا يوجد رصيد مستحق"

    formula = (
        f"({float(opening_balance):.2f} + {float(rights_total):.2f} - {float(obligations_total):.2f}) "
        f"= {float(calculated_balance):.2f}"
    )

    return {
        "success": True,
        "supplier": {
            "id": supplier.id,
            "name": supplier.name,
            "currency": supplier.currency or "ILS",
        },
        "opening_balance": {
            "amount": float(opening_balance),
            "direction": _direction_text(opening_balance),
        },
        "rights": {
            "total": float(rights_total),
            "items": _serialize(rights_rows),
        },
        "obligations": {
            "total": float(obligations_total),
            "items": _serialize(obligations_rows),
        },
        "payments": {
            "total_paid": float(_component("payments_out_balance")),
            "total_received": float(_component("payments_in_balance")),
            "preorders_prepaid": float(_component("preorders_prepaid_balance")),
            "total_settled": float(_component("payments_out_balance") + _component("payments_in_balance")),
        },
        "checks": {
            "returned_in": float(_component("returned_checks_in_balance")),
            "returned_out": float(_component("returned_checks_out_balance")),
        },
        "balance": {
            "amount": float(calculated_balance),
            "direction": _direction_text(calculated_balance),
            "action": _action_text(calculated_balance),
            "formula": formula,
            "matches_stored": (calculated_balance - stored_balance).copy_abs() <= tolerance,
            "stored": float(stored_balance),
            "difference": float(calculated_balance - stored_balance),
        },
        "components": {key: float(_dec(val)) for key, val in components.items()},
    }
