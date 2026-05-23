from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from extensions import db
from models import AuditLog

SAFE_ACTION_ALIASES = {
    "create_customer": "add_customer",
    "create_supplier": "add_supplier",
    "create_product": "add_product",
    "create_warehouse": "add_warehouse",
}


class ActionExecutor:
    def __init__(self, user_id: int = None):
        self.user_id = user_id
        self.last_action = None
        self.errors = []

    def execute_action(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            action = SAFE_ACTION_ALIASES.get(str(action_type or "").strip().lower(), str(action_type or "").strip().lower())
            action_map = {
                "add_customer": self.add_customer,
                "add_supplier": self.add_supplier,
                "add_product": self.add_product,
                "create_sale": self.create_sale,
                "create_invoice": self.create_invoice,
                "create_payment": self.create_payment,
                "create_expense": self.create_expense,
                "create_service": self.create_service,
                "add_warehouse": self.add_warehouse,
                "transfer_stock": self.transfer_stock,
                "adjust_stock": self.adjust_stock,
            }
            if action not in action_map:
                return {"success": False, "message": f"❌ العملية '{action_type}' غير مسموحة أو غير معروفة", "available_actions": sorted(action_map)}
            from AI.engine.ai_permissions import can_ai_execute_action
            if not can_ai_execute_action(action, ""):
                return {"success": False, "message": "❌ لا توجد صلاحية لتنفيذ هذا الإجراء"}
            result = action_map[action](params or {})
            if result.get("success"):
                self._log_action(action, params or {}, result)
            self.last_action = {"type": action, "params": params or {}, "result": result, "timestamp": datetime.now(timezone.utc).isoformat()}
            return result
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ خطأ في التنفيذ: {exc}", "error": str(exc)}

    def _columns(self, model) -> set[str]:
        return {c.name for c in getattr(model, "__table__", []).columns} if hasattr(model, "__table__") else set()

    def _new_model(self, model, values: Dict[str, Any]):
        cols = self._columns(model)
        return model(**{k: v for k, v in values.items() if k in cols})

    def _decimal(self, value: Any, default: str = "0") -> Decimal:
        try:
            return Decimal(str(value if value not in (None, "") else default))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(default)

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value if value not in (None, "") else default)
        except (ValueError, TypeError):
            return default

    def _clean(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _current_user_id(self) -> Optional[int]:
        if self.user_id:
            return int(self.user_id)
        try:
            from flask_login import current_user
            if getattr(current_user, "is_authenticated", False) and getattr(current_user, "id", None):
                return int(current_user.id)
        except Exception:
            pass
        return None

    def _vat_rate(self, enabled: bool = True) -> Decimal:
        if not enabled:
            return Decimal("0")
        try:
            from utils import get_vat_rate, is_vat_enabled
            return self._decimal(get_vat_rate()) if is_vat_enabled() else Decimal("0")
        except Exception:
            try:
                from models import SystemSettings
                return self._decimal(SystemSettings.get_setting("vat_rate", 0))
            except Exception:
                return Decimal("0")

    def _amount_value(self, obj) -> Decimal:
        for name in ("total_amount", "amount", "price", "selling_price", "total"):
            if hasattr(obj, name):
                return self._decimal(getattr(obj, name))
        return Decimal("0")

    def add_customer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Customer
            name = self._clean(params.get("name"))
            phone = self._clean(params.get("phone"))
            if not name or not phone:
                return {"success": False, "message": "❌ الاسم ورقم الهاتف مطلوبان"}
            if Customer.query.filter_by(phone=phone).first():
                return {"success": False, "message": "❌ الزبون موجود مسبقاً بنفس رقم الهاتف"}
            customer = self._new_model(Customer, {"name": name, "phone": phone, "whatsapp": self._clean(params.get("whatsapp")) or phone, "email": self._clean(params.get("email")), "address": self._clean(params.get("address")), "opening_balance": self._decimal(params.get("opening_balance")), "notes": self._clean(params.get("notes")), "currency": self._clean(params.get("currency")) or "ILS", "is_active": True})
            db.session.add(customer)
            db.session.commit()
            return {"success": True, "message": f"✅ تم إضافة الزبون '{customer.name}'", "customer_id": customer.id, "data": customer.to_dict() if hasattr(customer, "to_dict") else {"id": customer.id, "name": customer.name, "phone": customer.phone}}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إضافة الزبون: {exc}", "error": str(exc)}

    def add_supplier(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Supplier
            name = self._clean(params.get("name"))
            phone = self._clean(params.get("phone"))
            if not name or not phone:
                return {"success": False, "message": "❌ الاسم ورقم الهاتف مطلوبان"}
            if Supplier.query.filter_by(phone=phone).first():
                return {"success": False, "message": "❌ المورد موجود مسبقاً بنفس رقم الهاتف"}
            supplier = self._new_model(Supplier, {"name": name, "phone": phone, "contact": self._clean(params.get("contact")), "email": self._clean(params.get("email")), "address": self._clean(params.get("address")), "identity_number": self._clean(params.get("identity_number") or params.get("tax_id")), "opening_balance": self._decimal(params.get("opening_balance")), "notes": self._clean(params.get("notes")), "currency": self._clean(params.get("currency")) or "ILS"})
            db.session.add(supplier)
            db.session.commit()
            return {"success": True, "message": f"✅ تم إضافة المورد '{supplier.name}'", "supplier_id": supplier.id, "data": supplier.to_dict() if hasattr(supplier, "to_dict") else {"id": supplier.id, "name": supplier.name, "phone": supplier.phone}}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إضافة المورد: {exc}", "error": str(exc)}

    def add_product(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Product
            name = self._clean(params.get("name"))
            sku = self._clean(params.get("sku"))
            price = params.get("price", params.get("selling_price"))
            if not name or not sku or price in (None, ""):
                return {"success": False, "message": "❌ اسم المنتج والرمز وسعر البيع مطلوبة"}
            if Product.query.filter_by(sku=sku).first():
                return {"success": False, "message": "❌ رمز المنتج موجود مسبقاً"}
            purchase_price = params.get("purchase_price", params.get("cost", params.get("cost_price", 0)))
            product = self._new_model(Product, {"name": name, "sku": sku, "barcode": self._clean(params.get("barcode")), "description": self._clean(params.get("description")), "part_number": self._clean(params.get("part_number")), "brand": self._clean(params.get("brand")), "category": self._clean(params.get("category")), "category_name": self._clean(params.get("category")), "price": self._decimal(price), "selling_price": self._decimal(price), "purchase_price": self._decimal(purchase_price), "min_qty": self._int(params.get("min_qty", params.get("min_stock"))), "reorder_point": self._int(params.get("reorder_point")) if params.get("reorder_point") not in (None, "") else None, "currency": self._clean(params.get("currency")) or "ILS", "is_active": True})
            db.session.add(product)
            db.session.commit()
            return {"success": True, "message": f"✅ تم إضافة المنتج '{product.name}'", "product_id": product.id, "data": {"id": product.id, "name": product.name, "sku": product.sku, "price": float(self._decimal(product.price))}}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إضافة المنتج: {exc}", "error": str(exc)}

    def create_payment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Payment
            amount = params.get("amount", params.get("total_amount"))
            direction = (self._clean(params.get("direction")) or "").upper()
            method = self._clean(params.get("payment_method", params.get("method")))
            if amount in (None, "") or direction not in {"IN", "OUT"} or not method:
                return {"success": False, "message": "❌ المبلغ والاتجاه وطريقة الدفع مطلوبة"}
            target_fields = ["customer_id", "supplier_id", "partner_id", "sale_id", "invoice_id", "service_id", "preorder_id", "expense_id", "shipment_id"]
            selected = [field for field in target_fields if params.get(field)]
            if len(selected) != 1:
                return {"success": False, "message": "❌ يجب تحديد جهة واحدة فقط للدفعة"}
            etype = {"customer_id": "CUSTOMER", "supplier_id": "SUPPLIER", "partner_id": "PARTNER", "sale_id": "SALE", "invoice_id": "INVOICE", "service_id": "SERVICE", "preorder_id": "PREORDER", "expense_id": "EXPENSE", "shipment_id": "SHIPMENT"}[selected[0]]
            payment = self._new_model(Payment, {"total_amount": self._decimal(amount), "subtotal": self._decimal(params.get("subtotal", amount)), "tax_rate": self._decimal(params.get("tax_rate", 0)), "tax_amount": self._decimal(params.get("tax_amount", 0)), "direction": direction, "method": method, "status": self._clean(params.get("status")) or "COMPLETED", "entity_type": etype, selected[0]: params.get(selected[0]), "notes": self._clean(params.get("notes")), "reference": self._clean(params.get("reference")), "payment_date": datetime.now(timezone.utc), "currency": self._clean(params.get("currency")) or "ILS", "created_by": self._current_user_id()})
            db.session.add(payment)
            db.session.commit()
            return {"success": True, "message": f"✅ تم تسجيل الدفعة بمبلغ {float(self._decimal(payment.total_amount))} ₪", "payment_id": payment.id, "data": payment.to_dict() if hasattr(payment, "to_dict") else {"id": payment.id}}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل تسجيل الدفعة: {exc}", "error": str(exc)}

    def create_invoice(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Invoice, InvoiceSource, Supplier, run_invoice_gl_sync_after_commit
            total = params.get("total", params.get("total_amount"))
            if total in (None, ""):
                return {"success": False, "message": "❌ الإجمالي مطلوب"}
            customer_id = params.get("customer_id")
            supplier_id = params.get("supplier_id")
            if supplier_id and not customer_id:
                supplier = db.session.get(Supplier, int(supplier_id))
                customer_id = getattr(supplier, "customer_id", None) if supplier else None
                if not customer_id:
                    return {"success": False, "message": "❌ فاتورة المورد تحتاج customer_id فعلي مرتبط بالمورد"}
            if not customer_id:
                return {"success": False, "message": "❌ customer_id مطلوب حسب موديل الفواتير"}
            source = params.get("source") or (InvoiceSource.SUPPLIER.value if supplier_id else InvoiceSource.MANUAL.value)
            invoice = self._new_model(Invoice, {"invoice_number": params.get("invoice_number") or f"AI-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}", "invoice_date": datetime.now(timezone.utc), "customer_id": customer_id, "supplier_id": supplier_id, "partner_id": params.get("partner_id"), "total_amount": self._decimal(total), "tax_amount": self._decimal(params.get("tax_amount", 0)), "discount_amount": self._decimal(params.get("discount_amount", 0)), "notes": self._clean(params.get("notes")), "source": source, "currency": self._clean(params.get("currency")) or "ILS"})
            db.session.add(invoice)
            db.session.commit()
            try:
                run_invoice_gl_sync_after_commit(invoice.id)
            except Exception:
                pass
            return {"success": True, "message": f"✅ تم إنشاء الفاتورة بمبلغ {float(self._decimal(invoice.total_amount))} ₪", "invoice_id": invoice.id}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إنشاء الفاتورة: {exc}", "error": str(exc)}

    def create_sale(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Sale, SaleLine, run_sale_gl_sync_after_commit
            user_id = self._current_user_id()
            if not user_id:
                return {"success": False, "message": "❌ لا يمكن إنشاء بيع بدون seller_id فعلي"}
            customer_id = params.get("customer_id")
            warehouse_id = params.get("warehouse_id")
            items = params.get("items") or []
            if not customer_id or not warehouse_id or not items:
                return {"success": False, "message": "❌ الزبون والمستودع وبند واحد على الأقل مطلوبة"}
            tax_rate = self._vat_rate(bool(params.get("vat_enabled", True)))
            sale = self._new_model(Sale, {"customer_id": customer_id, "seller_id": user_id, "sale_date": datetime.now(timezone.utc), "tax_rate": tax_rate, "discount_total": self._decimal(params.get("discount")), "shipping_cost": self._decimal(params.get("shipping_cost")), "notes": self._clean(params.get("notes")), "status": self._clean(params.get("status")) or "CONFIRMED", "currency": self._clean(params.get("currency")) or "ILS"})
            db.session.add(sale)
            db.session.flush()
            subtotal = Decimal("0")
            for item in items:
                if not all(k in item for k in ("product_id", "quantity", "price")):
                    return {"success": False, "message": "❌ بيانات المنتج غير كاملة"}
                quantity = self._int(item["quantity"])
                if quantity <= 0:
                    return {"success": False, "message": "❌ الكمية يجب أن تكون أكبر من صفر"}
                unit_price = self._decimal(item["price"])
                discount_value = self._decimal(item.get("discount", 0))
                gross = unit_price * Decimal(quantity)
                discount_rate = Decimal("0") if gross <= 0 else max(Decimal("0"), min(Decimal("100"), (discount_value / gross) * Decimal("100")))
                db.session.add(self._new_model(SaleLine, {"sale_id": sale.id, "product_id": item["product_id"], "warehouse_id": item.get("warehouse_id") or warehouse_id, "quantity": quantity, "unit_price": unit_price, "discount_rate": discount_rate, "tax_rate": item.get("tax_rate", tax_rate), "note": self._clean(item.get("note"))}))
                subtotal += gross - discount_value
            base = max(Decimal("0"), subtotal - self._decimal(params.get("discount")) + self._decimal(params.get("shipping_cost")))
            sale.total_amount = base + (base * tax_rate / Decimal("100"))
            sale.balance_due = sale.total_amount
            db.session.commit()
            try:
                run_sale_gl_sync_after_commit(sale.id)
            except Exception:
                pass
            return {"success": True, "message": f"✅ تم إنشاء عملية البيع بمبلغ {float(self._decimal(sale.total_amount))} ₪", "sale_id": sale.id, "data": {"id": sale.id, "sale_number": sale.sale_number, "customer_id": sale.customer_id, "total_amount": float(self._decimal(sale.total_amount)), "items_count": len(items)}}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إنشاء البيع: {exc}", "error": str(exc)}

    def create_expense(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Expense
            amount = params.get("amount", params.get("total_amount"))
            description = self._clean(params.get("description", params.get("notes")))
            if amount in (None, "") or not description:
                return {"success": False, "message": "❌ المبلغ والوصف مطلوبان"}
            expense = self._new_model(Expense, {"amount": self._decimal(amount), "description": description, "date": datetime.now(timezone.utc), "currency": self._clean(params.get("currency")) or "ILS", "payment_method": self._clean(params.get("payment_method")) or "cash", "paid_to": self._clean(params.get("paid_to")), "notes": self._clean(params.get("notes")), "created_by": self._current_user_id(), "created_by_id": self._current_user_id()})
            db.session.add(expense)
            db.session.commit()
            return {"success": True, "message": f"✅ تم تسجيل المصروف بمبلغ {float(self._amount_value(expense))} ₪", "expense_id": expense.id}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل تسجيل المصروف: {exc}", "error": str(exc)}

    def create_service(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import ServiceRequest
            if not params.get("customer_id"):
                return {"success": False, "message": "❌ معرف الزبون مطلوب"}
            description = self._clean(params.get("problem_description", params.get("issue_description", params.get("description"))))
            if not description:
                return {"success": False, "message": "❌ وصف العطل مطلوب"}
            service = self._new_model(ServiceRequest, {"customer_id": params["customer_id"], "problem_description": description, "description": description, "vehicle_model": self._clean(params.get("vehicle_model")), "vehicle_vrn": self._clean(params.get("vehicle_vrn", params.get("vehicle_plate"))), "status": self._clean(params.get("status")) or "PENDING", "priority": self._clean(params.get("priority")) or "MEDIUM", "estimated_cost": self._decimal(params.get("estimated_cost", 0)) if params.get("estimated_cost") not in (None, "") else None, "currency": self._clean(params.get("currency")) or "ILS"})
            db.session.add(service)
            db.session.commit()
            return {"success": True, "message": f"✅ تم إنشاء طلب الصيانة رقم {service.id}", "service_id": service.id}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إنشاء طلب الصيانة: {exc}", "error": str(exc)}

    def add_warehouse(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Warehouse
            name = self._clean(params.get("name"))
            if not name:
                return {"success": False, "message": "❌ اسم المستودع مطلوب"}
            warehouse = self._new_model(Warehouse, {"name": name, "warehouse_type": (self._clean(params.get("warehouse_type", params.get("type"))) or "MAIN").upper(), "location": self._clean(params.get("location")), "partner_id": params.get("partner_id"), "supplier_id": params.get("supplier_id"), "is_active": True, "notes": self._clean(params.get("notes"))})
            db.session.add(warehouse)
            db.session.commit()
            return {"success": True, "message": f"✅ تم إضافة المستودع '{warehouse.name}'", "warehouse_id": warehouse.id}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل إضافة المستودع: {exc}", "error": str(exc)}

    def transfer_stock(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import Transfer
            if not all(params.get(k) for k in ["product_id", "from_warehouse_id", "to_warehouse_id", "quantity"]):
                return {"success": False, "message": "❌ بيانات التحويل ناقصة"}
            transfer = self._new_model(Transfer, {"product_id": params["product_id"], "source_id": params["from_warehouse_id"], "destination_id": params["to_warehouse_id"], "quantity": self._int(params["quantity"]), "direction": "OUT", "notes": self._clean(params.get("notes")), "user_id": self._current_user_id()})
            db.session.add(transfer)
            db.session.commit()
            return {"success": True, "message": "✅ تم إنشاء تحويل المخزون", "transfer_id": transfer.id, "reference": getattr(transfer, "reference", None)}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل تحويل المخزون: {exc}", "error": str(exc)}

    def adjust_stock(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from models import StockLevel
            if not all(params.get(k) for k in ["product_id", "warehouse_id", "new_quantity", "reason"]):
                return {"success": False, "message": "❌ بيانات الجرد ناقصة"}
            product_id = int(params["product_id"])
            warehouse_id = int(params["warehouse_id"])
            new_quantity = self._int(params["new_quantity"])
            if new_quantity < 0:
                return {"success": False, "message": "❌ الكمية الجديدة لا يمكن أن تكون سالبة"}
            stock = StockLevel.query.filter_by(product_id=product_id, warehouse_id=warehouse_id).first()
            old_quantity = self._int(getattr(stock, "quantity", 0)) if stock else 0
            if stock:
                stock.quantity = new_quantity
            else:
                db.session.add(self._new_model(StockLevel, {"product_id": product_id, "warehouse_id": warehouse_id, "quantity": new_quantity, "reserved_quantity": 0}))
            db.session.commit()
            return {"success": True, "message": f"✅ تم تعديل المخزون من {old_quantity} إلى {new_quantity}", "difference": new_quantity - old_quantity}
        except Exception as exc:
            db.session.rollback()
            return {"success": False, "message": f"❌ فشل تعديل المخزون: {exc}", "error": str(exc)}

    def _log_action(self, action_type: str, params: Dict, result: Dict) -> None:
        try:
            entity_id = result.get("customer_id") or result.get("supplier_id") or result.get("product_id") or result.get("sale_id") or result.get("invoice_id") or result.get("payment_id") or result.get("expense_id") or result.get("service_id") or result.get("warehouse_id") or result.get("transfer_id") or result.get("adjustment_id") or result.get("id")
            log = self._new_model(AuditLog, {"user_id": self._current_user_id(), "action": f"ai_action_{action_type}", "entity_type": action_type.replace("add_", "").replace("create_", ""), "entity_id": entity_id, "details": f"AI executed: {action_type}", "ip_address": "AI_SYSTEM", "user_agent": "AI Assistant"})
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()


def parse_user_request(message: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    message = str(message or "")
    if any(word in message.lower() for word in ["أضف زبون", "اضف زبون", "إضافة زبون", "add customer"]):
        params: Dict[str, Any] = {}
        name_match = re.search(r"اسمه?\s+([^\s،,]+)", message)
        if name_match:
            params["name"] = name_match.group(1)
        phone_match = re.search(r"(?:هاتفه?|موبايل|phone|رقمه?)\s*[:：]?\s*([\d\-+]+)", message)
        if phone_match:
            params["phone"] = phone_match.group(1)
        if params:
            return "add_customer", params
    return None


__all__ = ["ActionExecutor", "parse_user_request", "SAFE_ACTION_ALIASES"]
