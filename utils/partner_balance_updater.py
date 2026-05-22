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


def update_partner_balance_components(partner_id, session=None, emit: bool = True):
    if not partner_id:
        return
    
    from models import Partner
    from sqlalchemy.orm import Session
    from sqlalchemy import text as sa_text
    
    if not session:
        session = db.session
    
    try:
        if hasattr(session, "query") and hasattr(session, "get"):
            partner = session.get(Partner, partner_id)
            if not partner:
                return
            
            from utils.partner_balance_calculator import calculate_partner_balance_components
            from sqlalchemy.orm import sessionmaker
            calc_session = sessionmaker(bind=db.engine)()
            try:
                components = calculate_partner_balance_components(partner_id, calc_session)
            finally:
                try:
                    calc_session.close()
                except Exception:
                    pass
            
            if not components:
                return
            
            opening_balance = Decimal(str(partner.opening_balance or 0))
            if partner.currency and partner.currency != "ILS":
                try:
                    opening_balance = convert_amount(opening_balance, partner.currency, "ILS")
                except Exception:
                    pass
            
            # الرصيد = الرصيد الافتتاحي + الحقوق - الالتزامات
            # سالب = عليه لنا (عليه يدفع)، موجب = له عندنا (له رصيد)
            # 
            # ملاحظة: الصيغة التالية تطبق مبدأ Rights - Obligations مع الحفاظ على نفس النتيجة الرياضية
            # للصيغة الأصلية. payments_in يزيد الرصيد (يقلل الالتزامات) و payments_out يقلل الرصيد (يقلل الحقوق)
            #
            # الحقوق (Rights): ما للشريك علينا
            # - inventory_balance: نصيبه من البضاعة غير المباعة بسعر التكلفة
            # - sales_share_balance: نصيبه من المبيعات بسعر البيع (بعد خصم المرتجعات)
            # - payments_in_balance: دفعات واردة (دفع لنا - يقلل ما عليه، لذلك يزيد الرصيد)
            # - preorders_prepaid_balance: عربونات مدفوعة (دفع لنا - يقلل ما عليه)
            # - service_expenses_balance: مصروفات توريد خدمات (حق له)
            # - returned_checks_out_balance: شيكات مرتجعة صادرة (ناقص من ما عليه)
            #
            # الالتزامات (Obligations): ما على الشريك لنا
            # - sales_to_partner_balance: مبيعات له
            # - service_fees_balance: رسوم صيانة له
            # - preorders_to_partner_balance: حجوزات له
            # - damaged_items_balance: قطع تالفة
            # - payments_out_balance: دفعات صادرة (دفعنا له - يقلل ما له علينا، لذلك يقلل الرصيد)
            # - expenses_balance: مصروفات عادية
            # - returned_checks_in_balance: شيكات مرتجعة واردة (ناقص من ما عليه)
            
            from utils.accounting_formulas import (
                partner_balance_from_components,
                partner_obligations_total,
                partner_rights_total,
            )
            partner_rights = partner_rights_total(components)
            partner_obligations = partner_obligations_total(components)
            current_balance = partner_balance_from_components(opening_balance, components)
            
            partner.inventory_balance = Decimal(str(components.get('inventory_balance', 0)))
            partner.sales_share_balance = Decimal(str(components.get('sales_share_balance', 0)))
            partner.sales_to_partner_balance = Decimal(str(components.get('sales_to_partner_balance', 0)))
            partner.service_fees_balance = Decimal(str(components.get('service_fees_balance', 0)))
            partner.preorders_to_partner_balance = Decimal(str(components.get('preorders_to_partner_balance', 0)))
            partner.preorders_prepaid_balance = Decimal(str(components.get('preorders_prepaid_balance', 0)))
            partner.damaged_items_balance = Decimal(str(components.get('damaged_items_balance', 0)))
            partner.payments_in_balance = Decimal(str(components.get('payments_in_balance', 0)))
            partner.payments_out_balance = Decimal(str(components.get('payments_out_balance', 0)))
            partner.returned_checks_in_balance = Decimal(str(components.get('returned_checks_in_balance', 0)))
            partner.returned_checks_out_balance = Decimal(str(components.get('returned_checks_out_balance', 0)))
            partner.expenses_balance = Decimal(str(components.get('expenses_balance', 0)))
            partner.service_expenses_balance = Decimal(str(components.get('service_expenses_balance', 0)))
            partner.current_balance = current_balance
            
            session.flush()
            if emit:
                try:
                    from helpers.balance_events import emit_balance_update
                    emit_balance_update('partner', partner_id, float(current_balance))
                except Exception:
                    pass
        else:
            from utils.partner_balance_calculator import calculate_partner_balance_components
            from sqlalchemy.orm import Session as OrmSession
            calc_session = OrmSession(bind=session)
            try:
                components = calculate_partner_balance_components(partner_id, calc_session)
            finally:
                try:
                    calc_session.close()
                except Exception:
                    pass
            
            if not components:
                return
            
            result = session.execute(
                sa_text("SELECT opening_balance, currency FROM partners WHERE id = :id"),
                {"id": partner_id}
            ).fetchone()
            if not result:
                return
            
            opening_balance = Decimal(str(result[0] or 0))
            partner_currency = result[1] if len(result) > 1 else "ILS"
            
            if partner_currency and partner_currency != "ILS":
                try:
                    opening_balance = convert_amount(opening_balance, partner_currency, "ILS")
                except Exception:
                    pass
            
            # الرصيد = الرصيد الافتتاحي + الحقوق - الالتزامات
            # سالب = عليه لنا (عليه يدفع)، موجب = له عندنا (له رصيد)
            
            from utils.accounting_formulas import (
                partner_balance_from_components,
                partner_obligations_total,
                partner_rights_total,
            )
            partner_rights = partner_rights_total(components)
            partner_obligations = partner_obligations_total(components)
            current_balance = partner_balance_from_components(opening_balance, components)
            
            session.execute(
                sa_text("""
                    UPDATE partners 
                    SET current_balance = :balance,
                        inventory_balance = :inventory,
                        sales_share_balance = :sales_share,
                        sales_to_partner_balance = :sales_to_partner,
                        service_fees_balance = :service_fees,
                        preorders_to_partner_balance = :preorders_to_partner,
                        preorders_prepaid_balance = :preorders_prepaid,
                        damaged_items_balance = :damaged_items,
                        payments_in_balance = :payments_in,
                        payments_out_balance = :payments_out,
                        returned_checks_in_balance = :returned_checks_in,
                        returned_checks_out_balance = :returned_checks_out,
                        expenses_balance = :expenses,
                        service_expenses_balance = :service_expenses,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": partner_id,
                    "balance": float(current_balance),
                    "inventory": float(components.get('inventory_balance', 0)),
                    "sales_share": float(components.get('sales_share_balance', 0)),
                    "sales_to_partner": float(components.get('sales_to_partner_balance', 0)),
                    "service_fees": float(components.get('service_fees_balance', 0)),
                    "preorders_to_partner": float(components.get('preorders_to_partner_balance', 0)),
                    "preorders_prepaid": float(components.get('preorders_prepaid_balance', 0)),
                    "damaged_items": float(components.get('damaged_items_balance', 0)),
                    "payments_in": float(components.get('payments_in_balance', 0)),
                    "payments_out": float(components.get('payments_out_balance', 0)),
                    "returned_checks_in": float(components.get('returned_checks_in_balance', 0)),
                    "returned_checks_out": float(components.get('returned_checks_out_balance', 0)),
                    "expenses": float(components.get('expenses_balance', 0)),
                    "service_expenses": float(components.get('service_expenses_balance', 0))
                }
            )
            if emit:
                try:
                    from helpers.balance_events import emit_balance_update
                    emit_balance_update('partner', partner_id, float(current_balance))
                except Exception:
                    pass
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.debug(f"Error updating partner balance {partner_id}: {e}")
        except:
            pass


def build_partner_balance_view(partner_id, session=None):
    if not partner_id:
        return {"success": False, "error": "partner_id is required"}
    session = session or db.session
    from models import Partner
    partner = session.get(Partner, partner_id)
    if not partner:
        return {"success": False, "error": "Partner not found"}
    from utils.partner_balance_calculator import calculate_partner_balance_components
    components = calculate_partner_balance_components(partner_id, session)
    if not components:
        return {"success": False, "error": "Unable to calculate partner balance"}

    def _dec(value):
        return Decimal(str(value or 0))

    def _component(key):
        return _dec(components.get(key, 0))

    opening_balance = _dec(partner.opening_balance or 0)
    if partner.currency and partner.currency != "ILS":
        try:
            opening_balance = convert_amount(opening_balance, partner.currency, "ILS")
        except Exception:
            pass

    rights_rows = [
        {"key": "inventory_balance", "label": "نصيب المخزون", "amount": _component("inventory_balance"), "flow": "INVENTORY"},
        {"key": "sales_share_balance", "label": "نصيب المبيعات", "amount": _component("sales_share_balance"), "flow": "SALES_SHARE"},
        {"key": "shipments_share_balance", "label": "نصيب الشحنات", "amount": _component("shipments_share_balance"), "flow": "SHIPMENT_SHARE"},
        {"key": "payments_in_balance", "label": "دفعات دفع لنا", "amount": _component("payments_in_balance"), "flow": "PAYMENT_IN"},
        {"key": "service_expenses_balance", "label": "توريد خدمات", "amount": _component("service_expenses_balance"), "flow": "SERVICE_EXPENSE"},
        {"key": "returned_checks_out_balance", "label": "شيكات مرتجعة صادرة", "amount": _component("returned_checks_out_balance"), "flow": "CHECK_OUT"},
    ]

    obligations_rows = [
        {"key": "sales_to_partner_balance", "label": "مبيعات له", "amount": _component("sales_to_partner_balance"), "flow": "SALE"},
        {"key": "service_fees_balance", "label": "رسوم صيانة", "amount": _component("service_fees_balance"), "flow": "SERVICE"},
        {"key": "preorders_to_partner_balance", "label": "حجوزات له", "amount": _component("preorders_to_partner_balance"), "flow": "PREORDER"},
        {"key": "damaged_items_balance", "label": "قطع تالفة", "amount": _component("damaged_items_balance"), "flow": "DAMAGED"},
        {"key": "payments_out_balance", "label": "دفعات دفعنا له", "amount": _component("payments_out_balance"), "flow": "PAYMENT_OUT"},
        {"key": "expenses_balance", "label": "مصاريف", "amount": _component("expenses_balance"), "flow": "EXPENSE"},
        {"key": "returned_checks_in_balance", "label": "شيكات مرتجعة واردة", "amount": _component("returned_checks_in_balance"), "flow": "CHECK_IN"},
    ]

    from utils.accounting_formulas import (
        partner_balance_from_components,
        partner_obligations_total,
        partner_rights_total,
    )
    rights_total = partner_rights_total(components)
    obligations_total = partner_obligations_total(components)
    stored_balance = _dec(partner.current_balance or 0)
    calculated_balance = partner_balance_from_components(opening_balance, components)
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
            return "له عندنا"
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
        "partner": {
            "id": partner.id,
            "name": partner.name,
            "currency": partner.currency or "ILS",
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
