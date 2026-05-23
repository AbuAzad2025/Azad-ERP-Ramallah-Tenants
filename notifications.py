# notifications.py - Notifications Module
# Location: /garage_manager/notifications.py
# Description: Notification system and messaging functionality


import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, asdict
from flask import current_app, render_template
from flask_socketio import emit, join_room, leave_room
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from extensions import db, socketio
from models import TimestampMixin, AuditMixin


class NotificationType(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    ORDER = "order"
    PAYMENT = "payment"
    INVENTORY = "inventory"
    MAINTENANCE = "maintenance"
    SYSTEM = "system"


class NotificationPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationData:
    title: str
    message: str
    type: NotificationType = NotificationType.INFO
    priority: NotificationPriority = NotificationPriority.MEDIUM
    data: Optional[Dict[str, Any]] = None
    action_url: Optional[str] = None
    expires_at: Optional[datetime] = None


class Notification(db.Model, TimestampMixin, AuditMixin):
    """جدول الإشعارات"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # None = broadcast
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), nullable=False, default=NotificationType.INFO.value)
    priority = Column(String(20), nullable=False, default=NotificationPriority.MEDIUM.value)
    data = Column(JSON, nullable=True)
    action_url = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # العلاقات
    user = relationship("User", backref="notifications")
    
    def to_dict(self) -> Dict[str, Any]:
        """تحويل الإشعار إلى قاموس"""
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "type": self.type,
            "priority": self.priority,
            "data": self.data,
            "action_url": self.action_url,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat(),
        }
    
    def mark_as_read(self):
        """تحديد الإشعار كمقروء"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
    
    @classmethod
    def create_notification(
        cls,
        title: str,
        message: str,
        user_id: Optional[int] = None,
        notification_type: NotificationType = NotificationType.INFO,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        data: Optional[Dict[str, Any]] = None,
        action_url: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> "Notification":
        """إنشاء إشعار جديد"""
        notification = cls(
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type.value,
            priority=priority.value,
            data=data,
            action_url=action_url,
            expires_at=expires_at
        )
        db.session.add(notification)
        db.session.commit()
        
        # إرسال الإشعار عبر Socket.IO
        send_realtime_notification(notification)
        
        return notification
    
    @classmethod
    def get_user_notifications(
        cls,
        user_id: int,
        limit: int = 50,
        unread_only: bool = False
    ) -> List["Notification"]:
        """الحصول على إشعارات المستخدم"""
        query = cls.query.filter(
            (cls.user_id == user_id) | (cls.user_id.is_(None))
        ).filter(
            (cls.expires_at.is_(None)) | (cls.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))
        )
        
        if unread_only:
            query = query.filter(cls.is_read == False)
        
        return query.order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_unread_count(cls, user_id: int) -> int:
        """عدد الإشعارات غير المقروءة"""
        return cls.query.filter(
            (cls.user_id == user_id) | (cls.user_id.is_(None))
        ).filter(
            cls.is_read == False
        ).filter(
            (cls.expires_at.is_(None)) | (cls.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))
        ).count()
    
    @classmethod
    def cleanup_expired(cls):
        """تنظيف الإشعارات المنتهية الصلاحية"""
        expired_count = cls.query.filter(
            cls.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
        ).delete()
        db.session.commit()
        return expired_count


class NotificationManager:
    """مدير الإشعارات"""
    
    @staticmethod
    def send_order_notification(order_id: int, order_data: Dict[str, Any]):
        """إشعار طلب جديد"""
        Notification.create_notification(
            title="طلب جديد",
            message=f"تم استلام طلب جديد رقم #{order_id}",
            notification_type=NotificationType.ORDER,
            priority=NotificationPriority.HIGH,
            data={"order_id": order_id, **order_data},
            action_url=f"/orders/{order_id}"
        )
    
    @staticmethod
    def send_payment_notification(payment_id: int, amount: float, currency: str):
        """إشعار دفعة جديدة"""
        Notification.create_notification(
            title="دفعة جديدة",
            message=f"تم استلام دفعة بقيمة {amount} {currency}",
            notification_type=NotificationType.PAYMENT,
            priority=NotificationPriority.MEDIUM,
            data={"payment_id": payment_id, "amount": amount, "currency": currency},
            action_url=f"/payments/{payment_id}"
        )
    
    @staticmethod
    def send_inventory_alert(product_id: int, product_name: str, current_stock: int, min_stock: int):
        """تنبيه مخزون منخفض"""
        Notification.create_notification(
            title="تنبيه مخزون",
            message=f"المخزون منخفض للمنتج {product_name} - المتبقي: {current_stock}",
            notification_type=NotificationType.INVENTORY,
            priority=NotificationPriority.HIGH,
            data={
                "product_id": product_id,
                "product_name": product_name,
                "current_stock": current_stock,
                "min_stock": min_stock
            },
            action_url=f"/products/{product_id}"
        )
    
    @staticmethod
    def send_maintenance_reminder(service_id: int, customer_name: str, vehicle_info: str):
        """تذكير صيانة"""
        Notification.create_notification(
            title="تذكير صيانة",
            message=f"موعد صيانة للزبون {customer_name} - {vehicle_info}",
            notification_type=NotificationType.MAINTENANCE,
            priority=NotificationPriority.MEDIUM,
            data={
                "service_id": service_id,
                "customer_name": customer_name,
                "vehicle_info": vehicle_info
            },
            action_url=f"/services/{service_id}"
        )
    
    @staticmethod
    def send_system_alert(title: str, message: str, priority: NotificationPriority = NotificationPriority.HIGH):
        """تنبيه نظام"""
        Notification.create_notification(
            title=title,
            message=message,
            notification_type=NotificationType.SYSTEM,
            priority=priority
        )


def send_realtime_notification(notification: Notification):
    """
    إرسال الإشعار في الوقت الفعلي
    
    ⚠️ معطّل: كان يسبب تعليق في النظام (خاصة مع المساعد الذكي)
    الإشعارات تُحفظ في قاعدة البيانات فقط بدون إرسال فوري
    """
    # ❌ معطّل مؤقتاً - كان يسبب مشاكل
    return
    
    # الكود القديم (معطّل):
    # try:
    #     if notification.user_id:
    #         # إشعار لمستخدم محدد
    #         socketio.emit('notification', notification.to_dict(), room=f'user_{notification.user_id}')
    #     else:
    #         # إشعار عام لجميع المستخدمين
    #         socketio.emit('notification', notification.to_dict(), broadcast=True)
    # except Exception as e:
    #     logging.error(f"Error sending realtime notification: {e}")


@socketio.on('join_user_room')
def on_join_user_room(data):
    """انضمام المستخدم لغرفته الخاصة"""
    user_id = data.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')


@socketio.on('leave_user_room')
def on_leave_user_room(data):
    """مغادرة المستخدم لغرفته الخاصة"""
    user_id = data.get('user_id')
    if user_id:
        leave_room(f'user_{user_id}')


@socketio.on('mark_notification_read')
def on_mark_notification_read(data):
    """تحديد الإشعار كمقروء"""
    notification_id = data.get('notification_id')
    if notification_id:
        notification = db.session.get(Notification, notification_id)
        if notification:
            notification.mark_as_read()
            emit('notification_read', {'notification_id': notification_id})


# وظائف مساعدة للاستخدام في التطبيق
def notify_order_created(order_id: int, order_data: Dict[str, Any]):
    """إشعار طلب جديد"""
    NotificationManager.send_order_notification(order_id, order_data)


def notify_payment_received(payment_id: int, amount: float, currency: str):
    """إشعار دفعة مستلمة"""
    NotificationManager.send_payment_notification(payment_id, amount, currency)


def notify_low_stock(product_id: int, product_name: str, current_stock: int, min_stock: int):
    """تنبيه مخزون منخفض"""
    NotificationManager.send_inventory_alert(product_id, product_name, current_stock, min_stock)


def notify_maintenance_due(service_id: int, customer_name: str, vehicle_info: str):
    """تذكير صيانة مستحق"""
    NotificationManager.send_maintenance_reminder(service_id, customer_name, vehicle_info)


def notify_system_alert(title: str, message: str, priority: NotificationPriority = NotificationPriority.HIGH):
    """تنبيه نظام"""
    NotificationManager.send_system_alert(title, message, priority)
