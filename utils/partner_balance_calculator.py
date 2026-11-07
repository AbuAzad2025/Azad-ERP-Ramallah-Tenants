from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import func, or_, and_
from extensions import db


def convert_amount(amount, from_currency, to_currency, date=None):
    from models import convert_amount as _convert_amount
    try:
        return Decimal(str(_convert_amount(amount, from_currency, to_currency, date)))
    except Exception:
        return Decimal(str(amount or 0))


def calculate_partner_balance_components(partner_id, session=None, _retried: bool = False):
    if not partner_id:
        return None
    
    from models import Partner
    from sqlalchemy.orm import Session, sessionmaker
    
    use_new_session = False
    if not session:
        try:
            session = db.session
            try:
                session.execute(db.text("SELECT 1"))
            except Exception as e:
                error_str = str(e).lower()
                if "committed" in error_str or "closed" in error_str or "no further sql" in error_str:
                    session = sessionmaker(bind=db.engine)()
                    use_new_session = True
                else:
                    raise
        except Exception as e:
            error_str = str(e).lower()
            if "committed" in error_str or "closed" in error_str or "no further sql" in error_str:
                session = sessionmaker(bind=db.engine)()
                use_new_session = True
            else:
                raise
    elif isinstance(session, Session):
        try:
            try:
                session.execute(db.text("SELECT 1"))
            except Exception as e:
                error_str = str(e).lower()
                if "committed" in error_str or "closed" in error_str or "no further sql" in error_str:
                    session = sessionmaker(bind=db.engine)()
                    use_new_session = True
                else:
                    raise
        except Exception as e:
            error_str = str(e).lower()
            if "committed" in error_str or "closed" in error_str or "no further sql" in error_str:
                session = sessionmaker(bind=db.engine)()
                use_new_session = True
            else:
                raise
    
    try:
        partner = session.get(Partner, partner_id)
        if not partner:
            if use_new_session:
                try:
                    session.close()
                except:
                    pass
            return None
    except Exception as e:
        if use_new_session:
            try:
                session.close()
            except:
                pass
        return None
    
    result = {
        'inventory_balance': Decimal('0.00'),
        'sales_share_balance': Decimal('0.00'),
        'shipments_share_balance': Decimal('0.00'),
        'sales_to_partner_balance': Decimal('0.00'),
        'service_fees_balance': Decimal('0.00'),
        'preorders_to_partner_balance': Decimal('0.00'),
        'preorders_prepaid_balance': Decimal('0.00'),
        'damaged_items_balance': Decimal('0.00'),
        'payments_in_balance': Decimal('0.00'),
        'payments_out_balance': Decimal('0.00'),
        'returned_checks_in_balance': Decimal('0.00'),
        'returned_checks_out_balance': Decimal('0.00'),
        'expenses_balance': Decimal('0.00'),
        'service_expenses_balance': Decimal('0.00'),
    }
    
    try:
        from routes.partner_settlements import (
            _get_partner_inventory,
            _get_partner_sales_share,
            _get_partner_sales_returns,
            _get_partner_payments_received,
            _get_partner_preorders_prepaid,
            _get_partner_shipments_share,
            _get_payments_to_partner,
            _get_partner_sales_as_customer,
            _get_partner_service_fees,
            _get_partner_preorders_as_customer,
            _get_partner_damaged_items,
            _get_partner_expenses,
            _get_returned_checks_from_partner,
            _get_returned_checks_to_partner
        )
        from models import Expense, ExpenseType
        
        date_from = datetime(2024, 1, 1)
        date_to = datetime.now(timezone.utc).replace(tzinfo=None)
        
        inventory = _get_partner_inventory(partner_id, date_from, date_to, session=session)
        if isinstance(inventory, dict):
            result['inventory_balance'] = Decimal(str(inventory.get("total_ils", 0) or 0))
        
        sales_share = _get_partner_sales_share(partner_id, date_from, date_to, session=session)
        sales_share_total = Decimal('0.00')
        if isinstance(sales_share, dict):
            sales_share_total = Decimal(str(sales_share.get("total_share_ils", 0) or 0))
        
        sales_returns = _get_partner_sales_returns(partner_id, date_from, date_to, session=session)
        sales_returns_total = Decimal('0.00')
        if isinstance(sales_returns, dict):
            sales_returns_total = Decimal(str(sales_returns.get("total_return_share_ils", 0) or 0))
        
        result['sales_share_balance'] = sales_share_total - sales_returns_total
        
        payments_from_partner = _get_partner_payments_received(partner_id, partner, date_from, date_to, session=session)
        payments_in_total = Decimal('0.00')
        if isinstance(payments_from_partner, dict):
            payments_in_total = Decimal(str(payments_from_partner.get("total_ils", 0) or 0))
        
        preorders_prepaid = _get_partner_preorders_prepaid(partner_id, partner, date_from, date_to, session=session)
        preorders_prepaid_total = Decimal('0.00')
        if isinstance(preorders_prepaid, dict):
            preorders_prepaid_total = Decimal(str(preorders_prepaid.get("total_ils", 0) or 0))

        shipments_share = _get_partner_shipments_share(partner_id, date_from, date_to)
        shipments_share_total = Decimal('0.00')
        if isinstance(shipments_share, dict):
            shipments_share_total = Decimal(str(shipments_share.get("total_ils", 0) or 0))

        result['shipments_share_balance'] = shipments_share_total
        result['payments_in_balance'] = payments_in_total + preorders_prepaid_total
        result['preorders_prepaid_balance'] = preorders_prepaid_total
        
        payments_to_partner = _get_payments_to_partner(partner_id, partner, date_from, date_to, session=session)
        if isinstance(payments_to_partner, dict):
            result['payments_out_balance'] = Decimal(str(payments_to_partner.get("total_ils", 0) or 0))
        
        sales_to_partner = _get_partner_sales_as_customer(partner_id, partner, date_from, date_to, session=session)
        if isinstance(sales_to_partner, dict):
            result['sales_to_partner_balance'] = Decimal(str(sales_to_partner.get("total_ils", 0) or 0))
        
        service_fees = _get_partner_service_fees(partner_id, partner, date_from, date_to, session=session)
        if isinstance(service_fees, dict):
            result['service_fees_balance'] = Decimal(str(service_fees.get("total_ils", 0) or 0))
        
        preorders_to_partner = _get_partner_preorders_as_customer(partner_id, partner, date_from, date_to, session=session)
        if isinstance(preorders_to_partner, dict):
            result['preorders_to_partner_balance'] = Decimal(str(preorders_to_partner.get("total_ils", 0) or 0))
        
        damaged_items = _get_partner_damaged_items(partner_id, date_from, date_to, session=session)
        if isinstance(damaged_items, dict):
            result['damaged_items_balance'] = Decimal(str(damaged_items.get("total_ils", 0) or 0))
        
        expenses_deducted = _get_partner_expenses(partner_id, date_from, date_to, session=session)
        result['expenses_balance'] = Decimal(str(expenses_deducted or 0))
        
        from models import Check, CheckStatus, PaymentDirection
        manual_checks_in = session.query(Check).filter(
            Check.partner_id == partner_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.IN,
            ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
        ).all()
        
        for check in manual_checks_in:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date or datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception:
                    pass
            result['payments_in_balance'] += amt
        
        manual_checks_out = session.query(Check).filter(
            Check.partner_id == partner_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.OUT,
            ~Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED, CheckStatus.CANCELLED, CheckStatus.ARCHIVED])
        ).all()
        
        for check in manual_checks_out:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date or datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception:
                    pass
            result['payments_out_balance'] += amt
        
        manual_returned_checks_in = session.query(Check).filter(
            Check.partner_id == partner_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.IN,
            Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
        ).all()
        
        for check in manual_returned_checks_in:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date or datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception:
                    pass
            result['returned_checks_in_balance'] += amt
        
        manual_returned_checks_out = session.query(Check).filter(
            Check.partner_id == partner_id,
            Check.payment_id.is_(None),
            Check.direction == PaymentDirection.OUT,
            Check.status.in_([CheckStatus.RETURNED, CheckStatus.BOUNCED])
        ).all()
        
        for check in manual_returned_checks_out:
            amt = Decimal(str(check.amount or 0))
            if check.currency != "ILS":
                try:
                    amt = convert_amount(amt, check.currency, "ILS", check.check_date or datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception:
                    pass
            result['returned_checks_out_balance'] += amt
        
        returned_checks_from_partner = _get_returned_checks_from_partner(partner_id, partner, date_from, date_to, session=session)
        if isinstance(returned_checks_from_partner, dict):
            result['returned_checks_in_balance'] = Decimal(str(returned_checks_from_partner.get("total_ils", 0) or 0))
        
        returned_checks_to_partner = _get_returned_checks_to_partner(partner_id, partner, date_from, date_to, session=session)
        if isinstance(returned_checks_to_partner, dict):
            result['returned_checks_out_balance'] = Decimal(str(returned_checks_to_partner.get("total_ils", 0) or 0))
        
        from sqlalchemy import func
        expenses_to_partner = session.query(Expense).join(ExpenseType).filter(
            or_(
                Expense.partner_id == partner_id,
                and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
            ),
            func.upper(ExpenseType.code) == "PARTNER_EXPENSE"
        ).all()
        
        partner_service_total = Decimal('0.00')
        for exp in expenses_to_partner:
            amt = Decimal(str(exp.amount or 0))
            if exp.currency == "ILS":
                partner_service_total += amt
            else:
                try:
                    amt_ils = convert_amount(amt, exp.currency, "ILS", exp.date)
                    partner_service_total += amt_ils
                except Exception:
                    pass
        
        result['service_expenses_balance'] = partner_service_total
        
    except Exception as e:
        err = str(e).lower()
        if not _retried and ("closed transaction" in err or ("context manager" in err and ("closed" in err or "committed" in err)) or "no further sql" in err):
            from sqlalchemy.orm import sessionmaker
            retry_session = sessionmaker(bind=db.engine)()
            try:
                return calculate_partner_balance_components(partner_id, retry_session, _retried=True)
            finally:
                try:
                    retry_session.close()
                except Exception:
                    pass
        from flask import current_app
        try:
            current_app.logger.error(f"خطأ في حساب مكونات رصيد الشريك #{partner_id}: {e}")
        except:
            pass
        return None
    finally:
        if use_new_session:
            try:
                session.close()
            except:
                pass
    
    return result

