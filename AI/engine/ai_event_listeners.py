"""
👂 AI Event Listeners - مستمعين الأحداث الذكية
════════════════════════════════════════════════════════════════════

وظيفة هذا الملف:
- الاستماع لكل عملية في النظام
- كشف الأخطاء فوراً عند الحفظ
- إنشاء تنبيهات تلقائية

يجب تفعيله في app.py عبر:
from AI.engine.ai_event_listeners import register_ai_listeners
register_ai_listeners(app)

Created: 2025-11-01
"""

from sqlalchemy import event
from extensions import db
try:
    from AI.engine.ai_realtime_monitor import get_realtime_monitor
except ImportError:
    get_realtime_monitor = lambda: None

_listeners_registered = False


# ═══════════════════════════════════════════════════════════════════════════
# 👂 EVENT LISTENERS - المستمعين
# ═══════════════════════════════════════════════════════════════════════════

def register_ai_listeners(app):
    """
    تسجيل جميع Event Listeners للمراقبة الذكية
    
    يُستدعى مرة واحدة عند تشغيل التطبيق
    """
    global _listeners_registered
    if _listeners_registered:
        print("[AI] Event Listeners already registered; skipping duplicate setup")
        return
    with app.app_context():
        from models import (
            Sale, Payment, StockLevel, GLBatch, 
            Customer, Supplier, ServiceRequest
        )
        
        # 1. مراقبة المبيعات
        @event.listens_for(Sale, 'after_insert')
        @event.listens_for(Sale, 'after_update')
        def check_sale_on_save(mapper, connection, sale):
            """فحص البيع بعد الحفظ"""
            try:
                monitor = get_realtime_monitor()
                if monitor is None:
                    return
                
                # الحصول على user_id من العملية
                user_id = sale.created_by_id or 1
                
                alerts = monitor.check_operation('sale', sale, user_id)
                
                # التنبيهات ستظهر للمستخدم في الـ frontend تلقائياً
                
            except Exception as e:
                print(f"[AI Monitor] Error checking sale: {e}")
        
        # 2. مراقبة الدفعات
        @event.listens_for(Payment, 'after_insert')
        @event.listens_for(Payment, 'after_update')
        def check_payment_on_save(mapper, connection, payment):
            """فحص الدفعة بعد الحفظ"""
            try:
                monitor = get_realtime_monitor()
                if monitor is None:
                    return
                user_id = getattr(payment, "created_by", None) or getattr(payment, "created_by_id", None) or 1
                
                alerts = monitor.check_operation('payment', payment, user_id)
                
            except Exception as e:
                print(f"[AI Monitor] Error checking payment: {e}")
        
        # 3. مراقبة المخزون
        @event.listens_for(StockLevel, 'after_insert')
        @event.listens_for(StockLevel, 'after_update')
        def check_stock_on_save(mapper, connection, stock):
            """فحص المخزون بعد التحديث"""
            try:
                monitor = get_realtime_monitor()
                if monitor is None:
                    return
                user_id = 1  # سيتم تحديثها في الـ frontend
                
                alerts = monitor.check_operation('stock', stock, user_id)
                
            except Exception as e:
                print(f"[AI Monitor] Error checking stock: {e}")
        
        # 4. مراقبة القيود المحاسبية
        @event.listens_for(GLBatch, 'after_insert')
        @event.listens_for(GLBatch, 'after_update')
        def check_gl_batch_on_save(mapper, connection, gl_batch):
            """فحص القيد المحاسبي بعد الحفظ"""
            try:
                monitor = get_realtime_monitor()
                if monitor is None:
                    return
                user_id = 1
                
                alerts = monitor.check_operation('gl_batch', gl_batch, user_id)
                
            except Exception as e:
                print(f"[AI Monitor] Error checking GL batch: {e}")
        
        # 5. مراقبة الزبائن
        @event.listens_for(Customer, 'after_update')
        def check_customer_on_update(mapper, connection, customer):
            """فحص الزبون بعد التحديث"""
            try:
                monitor = get_realtime_monitor()
                if monitor is None:
                    return
                user_id = 1
                
                alerts = monitor.check_operation('customer', customer, user_id)
                
            except Exception as e:
                print(f"[AI Monitor] Error checking customer: {e}")
        
        _listeners_registered = True
        print("[AI] Event Listeners registered - Real-time monitoring active")


__all__ = ['register_ai_listeners']

