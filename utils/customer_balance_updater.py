from decimal import Decimal
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import object_session
from extensions import db


def convert_amount(amount, from_currency, to_currency, date=None):
    try:
        from models import convert_amount as _convert_amount
        return _convert_amount(amount, from_currency, to_currency, date)
    except Exception:
        return Decimal(str(amount))


def get_customer_from_payment(payment):
    if payment.customer_id:
        return payment.customer_id
    if payment.sale_id and payment.sale and payment.sale.customer_id:
        return payment.sale.customer_id
    if payment.invoice_id and payment.invoice and payment.invoice.customer_id:
        return payment.invoice.customer_id
    if payment.service_id and payment.service and payment.service.customer_id:
        return payment.service.customer_id
    if payment.preorder_id and payment.preorder and payment.preorder.customer_id:
        return payment.preorder.customer_id
    return None


# ⚠️ قبل التعديل: اقرأ ACCOUNTING_RULES.md - قواعد المحاسبة الأساسية
def update_customer_balance_components(customer_id, session=None):
    if not customer_id:
        return
    
    from models import (
        Customer, Sale, SaleReturn, Invoice, ServiceRequest, PreOrder, OnlinePreOrder,
        Payment, Check, PaymentMethod, PaymentStatus, PaymentDirection, Expense, ExpenseType
    )
    
    try:
        from sqlalchemy.orm import Session
        from sqlalchemy import text as sa_text
        
        use_new_session = False
        if session is None:
            session = db.session
        elif isinstance(session, Session):
            try:
                session.execute(sa_text("SELECT 1"))
            except Exception:
                use_new_session = True
        
        if use_new_session:
            from sqlalchemy.orm import sessionmaker
            new_session = sessionmaker(bind=db.engine)()
        else:
            new_session = None
        
        try:
            if isinstance(session, Session):
                from utils.balance_calculator import calculate_customer_balance_components
                components = calculate_customer_balance_components(customer_id, session)
                
                if not components:
                    return
                
                customer = session.get(Customer, customer_id)
                if not customer:
                    return
                
                opening_balance = Decimal(str(customer.opening_balance or 0))
                if customer.currency and customer.currency != "ILS":
                    try:
                        opening_balance = convert_amount(opening_balance, customer.currency, "ILS")
                    except Exception:
                        pass
                
                # الرصيد = الرصيد الافتتاحي + الحقوق - الالتزامات
                # سالب = عليه لنا (يجب أن يدفع)، موجب = له عندنا (دفع زيادة)
                #
                # الحقوق (Rights): ما قبضناه من العميل
                # - payments_in_balance: دفعات واردة (ما قبضناه)
                # - returns_balance: مرتجعات (تقلل ما عليه)
                # - returned_checks_out_balance: شيكات مرتجعة صادرة (تقلل ما عليه)
                # - service_expenses_balance: مصروفات توريد خدمات (حق له)
                #
                # الحقوق (Rights): ما له عندنا
                # - payments_in_balance: دفعات واردة (العميل دفع لنا = حق له = تقليل ما عليه)
                # - returns_balance: مرتجعات (تقلل ما عليه)
                # - returned_checks_out_balance: شيكات مرتجعة صادرة (تقلل ما عليه)
                # - service_expenses_balance: مصروفات توريد خدمات (حق له)
                #
                # الالتزامات (Obligations): ما على العميل
                # - sales_balance: مبيعات (يشمل المبيعات الناتجة من الحجوزات المسبقة عند التسليم)
                # - invoices_balance: فواتير مستقلة (غير المرتبطة ببيع/خدمة/حجز)
                # - services_balance: خدمات
                # - preorders_balance: ذمة الحجوزات المفتوحة (إجمالي − العربون)
                # - online_orders_balance: طلبات أونلاين
                # - payments_out_balance: دفعات صادرة (دفعنا له = التزام عليه = يجب أن يعيد المبلغ)
                # - returned_checks_in_balance: شيكات مرتجعة واردة
                # - expenses_balance: مصروفات عادية
                
                from utils.accounting_formulas import (
                    customer_balance_from_components,
                    customer_obligations_total,
                    customer_rights_total,
                )
                customer_rights = customer_rights_total(components)
                customer_obligations = customer_obligations_total(components)
                current_balance = customer_balance_from_components(opening_balance, components)
                
                customer.sales_balance = Decimal(str(components.get('sales_balance', 0)))
                customer.returns_balance = Decimal(str(components.get('returns_balance', 0)))
                customer.invoices_balance = Decimal(str(components.get('invoices_balance', 0)))
                customer.services_balance = Decimal(str(components.get('services_balance', 0)))
                customer.preorders_balance = Decimal(str(components.get('preorders_balance', 0)))
                customer.online_orders_balance = Decimal(str(components.get('online_orders_balance', 0)))
                customer.payments_in_balance = Decimal(str(components.get('payments_in_balance', 0)))
                customer.payments_out_balance = Decimal(str(components.get('payments_out_balance', 0)))
                customer.checks_in_balance = Decimal(str(components.get('checks_in_balance', 0)))
                customer.checks_out_balance = Decimal(str(components.get('checks_out_balance', 0)))
                customer.returned_checks_in_balance = Decimal(str(components.get('returned_checks_in_balance', 0)))
                customer.returned_checks_out_balance = Decimal(str(components.get('returned_checks_out_balance', 0)))
                customer.expenses_balance = Decimal(str(components.get('expenses_balance', 0)))
                customer.service_expenses_balance = Decimal(str(components.get('service_expenses_balance', 0)))
                customer.current_balance = current_balance
                
                session.flush()
                if use_new_session:
                    session.commit()
                else:
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        raise
                
                try:
                    from helpers.balance_events import emit_balance_update
                    emit_balance_update('customer', customer_id, float(current_balance))
                except Exception:
                    pass
            else:
                from utils.balance_calculator import calculate_customer_balance_components
                from sqlalchemy.orm import sessionmaker
                calc_session = sessionmaker(bind=db.engine)()
                try:
                    components = calculate_customer_balance_components(customer_id, calc_session)
                finally:
                    calc_session.close()
            
            if not components:
                return
            
            result = session.execute(
                sa_text("SELECT opening_balance, currency FROM customers WHERE id = :id"),
                {"id": customer_id}
            ).fetchone()
            if not result:
                return
            
            opening_balance = Decimal(str(result[0] or 0))
            customer_currency = result[1] if len(result) > 1 else "ILS"
            if customer_currency and customer_currency != "ILS":
                try:
                    opening_balance = convert_amount(opening_balance, customer_currency, "ILS")
                except Exception:
                    pass
            
            # الرصيد = الرصيد الافتتاحي + الحقوق - الالتزامات
            # سالب = عليه لنا (يجب أن يدفع)، موجب = له عندنا (دفع زيادة)
            
            from utils.accounting_formulas import (
                customer_balance_from_components,
                customer_obligations_total,
                customer_rights_total,
            )
            customer_rights = customer_rights_total(components)
            customer_obligations = customer_obligations_total(components)
            current_balance = customer_balance_from_components(opening_balance, components)
            
            session.execute(
                sa_text("""
                    UPDATE customers 
                    SET current_balance = :balance,
                        sales_balance = :sales,
                        returns_balance = :returns,
                        invoices_balance = :invoices,
                        services_balance = :services,
                        preorders_balance = :preorders,
                        online_orders_balance = :online_orders,
                        payments_in_balance = :payments_in,
                        payments_out_balance = :payments_out,
                        checks_in_balance = :checks_in,
                        checks_out_balance = :checks_out,
                        returned_checks_in_balance = :returned_checks_in,
                        returned_checks_out_balance = :returned_checks_out,
                        expenses_balance = :expenses,
                        service_expenses_balance = :service_expenses,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": customer_id,
                    "balance": float(current_balance),
                    "sales": float(components.get('sales_balance', 0)),
                    "returns": float(components.get('returns_balance', 0)),
                    "invoices": float(components.get('invoices_balance', 0)),
                    "services": float(components.get('services_balance', 0)),
                    "preorders": float(components.get('preorders_balance', 0)),
                    "online_orders": float(components.get('online_orders_balance', 0)),
                    "payments_in": float(components.get('payments_in_balance', 0)),
                    "payments_out": float(components.get('payments_out_balance', 0)),
                    "checks_in": float(components.get('checks_in_balance', 0)),
                    "checks_out": float(components.get('checks_out_balance', 0)),
                    "returned_checks_in": float(components.get('returned_checks_in_balance', 0)),
                    "returned_checks_out": float(components.get('returned_checks_out_balance', 0)),
                    "expenses": float(components.get('expenses_balance', 0)),
                    "service_expenses": float(components.get('service_expenses_balance', 0))
                }
            )
            
            try:
                from helpers.balance_events import emit_balance_update
                emit_balance_update('customer', customer_id, float(current_balance))
            except Exception:
                pass
        finally:
            if new_session:
                new_session.close()
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.debug(f"Error updating customer balance {customer_id}: {e}")
        except:
            pass

