from __future__ import annotations
import enum
import logging
import re, hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps, lru_cache
from flask import current_app, has_app_context, has_request_context, request
from flask_login import UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    and_,
    case,
    event,
    func,
    insert,
    or_,
    select,
    text as sa_text,
    update,
    inspect,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Session as _SA_Session, relationship, object_session, validates, joinedload, declared_attr

from extensions import db
from barcodes import normalize_barcode

_EVENT_LOGGER = logging.getLogger("models.listeners")
_ORIGINAL_EVENT_LISTEN = event.listen
_EVENT_REGISTRY = {}


def get_event_registry_snapshot():
    return [
        {
            "target": entry["target"],
            "identifier": entry["identifier"],
            "count": len(entry["functions"]),
            "functions": sorted(entry["functions"]),
        }
        for entry in _EVENT_REGISTRY.values()
    ]


def _wrap_listener(fn, descriptor):
    if getattr(fn, "_listener_wrapped", False):
        return fn

    @wraps(fn)
    def _inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            _EVENT_LOGGER.exception("Listener failure: %s", descriptor)
            raise

    _inner._listener_wrapped = True
    return _inner


def _tracked_listen(target, identifier, fn, *args, **kwargs):
    descriptor = f"{fn.__module__}.{getattr(fn, '__qualname__', getattr(fn, '__name__', '<lambda>'))}"
    target_name = getattr(target, "__name__", str(target))

    is_internal = descriptor.startswith("sqlalchemy.") or descriptor.startswith("alembic.")
    if "MetaData" in target_name:
        is_internal = True

    if not is_internal:
        key = (id(target), identifier)
        entry = _EVENT_REGISTRY.setdefault(
            key,
            {
                "target": target_name,
                "identifier": identifier,
                "functions": set(),
            },
        )
        if descriptor in entry["functions"]:
            _EVENT_LOGGER.warning(
                "Duplicate listener detected: %s on %s:%s",
                descriptor,
                entry["target"],
                identifier,
            )
        else:
            entry["functions"].add(descriptor)
        wrapped = _wrap_listener(fn, descriptor)
    else:
        wrapped = fn

    return _ORIGINAL_EVENT_LISTEN(target, identifier, wrapped, *args, **kwargs)


event.listen = _tracked_listen

class Archive(db.Model):
    __tablename__ = 'archives'
    
    id = Column(Integer, primary_key=True)
    record_type = Column(String(50), nullable=False, index=True)
    record_id = Column(Integer, nullable=False, index=True)
    table_name = Column(String(100), nullable=False)
    archived_data = Column(Text, nullable=False)
    archive_reason = Column(String(200))
    archived_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    archived_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    original_created_at = Column(DateTime)
    original_updated_at = Column(DateTime)
    user = relationship('User', backref='archives')
    
    def __repr__(self):
        return f'<Archive {self.record_type}:{self.record_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'record_type': self.record_type,
            'record_id': self.record_id,
            'table_name': self.table_name,
            'archived_data': json.loads(self.archived_data) if self.archived_data else {},
            'archive_reason': self.archive_reason,
            'archived_by': self.archived_by,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None,
            'original_created_at': self.original_created_at.isoformat() if self.original_created_at else None,
            'original_updated_at': self.original_updated_at.isoformat() if self.original_updated_at else None,
            'user_name': self.user.username if self.user else None
        }
    
    @classmethod
    def archive_record(cls, record, reason=None, user_id=None):
        if not user_id:
            user_id = current_user.id if current_user and current_user.is_authenticated else None
        
        record_dict = {}
        for column in record.__table__.columns:
            value = getattr(record, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = float(value)
            record_dict[column.name] = value
        archive = cls(
            record_type=record.__tablename__,
            record_id=record.id,
            table_name=record.__tablename__,
            archived_data=json.dumps(record_dict, ensure_ascii=False, default=str),
            archive_reason=reason,
            archived_by=user_id,
            original_created_at=getattr(record, 'created_at', None),
            original_updated_at=getattr(record, 'updated_at', None)
        )
        
        db.session.add(archive)
        db.session.flush()
        return archive

user_permissions = db.Table(
    "user_permissions",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)

import constants
from constants import (
    DEFAULT_CURRENCY, CURRENCY_CHOICES, CENT, TWOPLACES, ZERO_PLACES
)

def sa_str_enum(enum_or_values, name=None):
    native = False
    if isinstance(enum_or_values, type) and issubclass(enum_or_values, enum.Enum):
        try:
            return SAEnum(enum_or_values, name=name, values_callable=lambda e: [m.value for m in e], native_enum=native)
        except TypeError:
            vals = [m.value for m in enum_or_values]
            return SAEnum(*vals, name=name, native_enum=native)
    try:
        vals = [(m.value if isinstance(m, enum.Enum) else str(m)) for m in enum_or_values]
    except TypeError:
        vals = [str(enum_or_values)]
    return SAEnum(*vals, name=name, native_enum=native)

TWO = TWOPLACES

def D(x):
    try:
        return Decimal(str(x)) if x is not None else Decimal("0.00")
    except Exception:
        return Decimal("0.00")

def q(x) -> Decimal:
    try:
        return Decimal(str(x or 0)).quantize(TWOPLACES, ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def _ar_label(val, mapping):
    return mapping.get(val, val)

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).translate(_AR_DIGITS)
    s = re.sub(r"\D+", "", s)
    return s[:20]

def normalize_email(raw: str | None) -> str:
    return (raw or "").strip().lower()

class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    BANK = "bank"
    CARD = "card"
    CHEQUE = "cheque"
    ONLINE = "online"
    # Added uppercase variants for compatibility
    CASH_UPPER = "CASH"
    BANK_UPPER = "BANK"
    CARD_UPPER = "CARD"
    CHEQUE_UPPER = "CHEQUE"
    ONLINE_UPPER = "ONLINE"

    @property
    def label(self):
        val = self.value.lower()
        mapping = {
            "cash": "نقدًا",
            "bank": "تحويل بنكي",
            "card": "بطاقة",
            "cheque": "شيك",
            "online": "أونلاين",
        }
        return mapping.get(val, val)


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "COMPLETED": "مكتمل",
            "FAILED": "فشل",
            "REFUNDED": "مسترجع",
            "CANCELLED": "ملغي",
        }[self.value]


class PaymentDirection(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"

    @property
    def label(self):
        return {"IN": "وارد", "OUT": "صادر"}[self.value]


class InvoiceStatus(str, enum.Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

    @property
    def label(self):
        return {
            "UNPAID": "غير مدفوعة",
            "PARTIAL": "مدفوعة جزئيًا",
            "PAID": "مدفوعة",
            "CANCELLED": "ملغاة",
            "REFUNDED": "مسترجعة",
        }[self.value]


class PaymentProgress(str, enum.Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    COMPLETED = "COMPLETED"  # Added for compatibility
    CANCELLED = "CANCELLED"  # Added to support cancellation checks


class TimesheetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def label(self):
        return {
            "DRAFT": "مسودة",
            "SUBMITTED": "تم التقديم",
            "APPROVED": "موافق عليه",
            "REJECTED": "مرفوض",
        }[self.value]


class TaskStatus(str, enum.Enum):
    TODO = "TODO"
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            "TODO": "للقيام به",
            "PENDING": "قيد الانتظار",
            "ASSIGNED": "تم التعيين",
            "IN_PROGRESS": "قيد التنفيذ",
            "COMPLETED": "مكتمل",
            "ON_HOLD": "معلق",
            "CANCELLED": "ملغي",
        }[self.value]


class SaleStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"  # للتوافق مع البيانات القديمة
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    RETURNED = "RETURNED"

    @property
    def label(self):
        return {
            "DRAFT": "مسودة",
            "CONFIRMED": "مؤكدة",
            "COMPLETED": "مكتملة",  # للتوافق مع البيانات القديمة
            "CANCELLED": "ملغاة",
            "REFUNDED": "مسترجعة",
            "RETURNED": "مرتجعة",
        }[self.value]


_ALLOWED_SALE_TRANSITIONS = {
    SaleStatus.DRAFT.value: {SaleStatus.CONFIRMED.value, SaleStatus.CANCELLED.value},
    SaleStatus.CONFIRMED.value: {SaleStatus.CANCELLED.value, SaleStatus.REFUNDED.value, SaleStatus.RETURNED.value},
    SaleStatus.COMPLETED.value: {SaleStatus.CANCELLED.value, SaleStatus.REFUNDED.value, SaleStatus.RETURNED.value},  # للتوافق مع البيانات القديمة
    SaleStatus.CANCELLED.value: set(),
    SaleStatus.REFUNDED.value: set(),
    SaleStatus.RETURNED.value: set(),
}


class ServiceStatus(str, enum.Enum):
    PENDING = "PENDING"
    DIAGNOSIS = "DIAGNOSIS"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ON_HOLD = "ON_HOLD"
    DELIVERED = "DELIVERED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "DIAGNOSIS": "تشخيص",
            "IN_PROGRESS": "قيد التنفيذ",
            "COMPLETED": "مكتملة",
            "CANCELLED": "ملغاة",
            "ON_HOLD": "معلقة",
            "DELIVERED": "تم التسليم",
        }[self.value]


class ServicePriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"

    @property
    def label(self):
        return {
            "LOW": "منخفضة",
            "MEDIUM": "متوسطة",
            "HIGH": "عالية",
            "URGENT": "عاجلة",
        }[self.value]


class TransferDirection(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"
    ADJUSTMENT = "ADJUSTMENT"

    @property
    def label(self):
        return {
            "IN": "وارد",
            "OUT": "صادر",
            "ADJUSTMENT": "تسوية",
        }[self.value]


class OnlinePaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "SUCCESS": "ناجحة",
            "FAILED": "فاشلة",
            "REFUNDED": "مسترجعة",
        }[self.value]


class OnlineCartStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"
    CONVERTED = "CONVERTED"

    @property
    def label(self):
        return {
            "ACTIVE": "نشطة",
            "ABANDONED": "مهجورة",
            "CONVERTED": "محولة",
        }[self.value]


class PreOrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "CONFIRMED": "مؤكدة",
            "FULFILLED": "مكتملة",
            "CANCELLED": "ملغاة",
        }[self.value]


class CustomerCategory(str, enum.Enum):
    NORMAL = "عادي"
    GOLD = "ذهبي"
    PLATINUM = "بلاتيني"

    @property
    def label(self):
        return {
            "عادي": "عادي",
            "ذهبي": "ذهبي",
            "بلاتيني": "بلاتيني",
        }[self.value]


class WarehouseType(str, enum.Enum):
    MAIN = "MAIN"
    PARTNER = "PARTNER"
    INVENTORY = "INVENTORY"
    EXCHANGE = "EXCHANGE"
    ONLINE = "ONLINE"
    TEMP = "TEMP"
    OUTLET = "OUTLET"

    @property
    def label(self):
        return {
            "MAIN": "رئيسي",
            "PARTNER": "شريك",
            "INVENTORY": "ملكيتي",
            "EXCHANGE": "تبادل",
            "ONLINE": "أونلاين",
            "TEMP": "مؤقت",
            "OUTLET": "منفذ بيع",
        }[self.value]


class PaymentEntityType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    PARTNER = "PARTNER"
    SHIPMENT = "SHIPMENT"
    EXPENSE = "EXPENSE"
    LOAN = "LOAN"
    SALE = "SALE"
    INVOICE = "INVOICE"
    PREORDER = "PREORDER"
    SERVICE = "SERVICE"
    MISCELLANEOUS = "MISCELLANEOUS"  # ✅ متفرقات
    OTHER = "OTHER"  # ✅ أخرى

    @property
    def label(self):
        return {
            "CUSTOMER": "عميل",
            "SUPPLIER": "مورد",
            "PARTNER": "شريك",
            "SHIPMENT": "شحنة",
            "EXPENSE": "مصاريف",
            "LOAN": "قرض",
            "SALE": "بيع",
            "INVOICE": "فاتورة",
            "PREORDER": "طلب مسبق",
            "SERVICE": "صيانة",
            "MISCELLANEOUS": "متفرقات",
            "OTHER": "أخرى",
        }[self.value]


class InvoiceSource(str, enum.Enum):
    MANUAL = "MANUAL"
    SALE = "SALE"
    SERVICE = "SERVICE"
    PREORDER = "PREORDER"
    SUPPLIER = "SUPPLIER"
    PARTNER = "PARTNER"
    ONLINE = "ONLINE"

    @property
    def label(self):
        return {
            "MANUAL": "يدوي",
            "SALE": "بيع",
            "SERVICE": "صيانة",
            "PREORDER": "طلب مسبق",
            "SUPPLIER": "مورد",
            "PARTNER": "شريك",
            "ONLINE": "أونلاين",
        }[self.value]


class PartnerSettlementStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            "DRAFT": "مسودة",
            "CONFIRMED": "مؤكدة",
            "CANCELLED": "ملغاة",
        }[self.value]


class SupplierSettlementStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            "DRAFT": "مسودة",
            "CONFIRMED": "مؤكدة",
            "CANCELLED": "ملغاة",
        }[self.value]


class SupplierSettlementMode(str, enum.Enum):
    ON_RECEIPT = "ON_RECEIPT"
    ON_CONSUME = "ON_CONSUME"

    @property
    def label(self):
        return {
            "ON_RECEIPT": "عند الاستلام",
            "ON_CONSUME": "عند الاستهلاك",
        }[self.value]


class ProductCondition(str, enum.Enum):
    NEW = "NEW"
    USED = "USED"
    REFURBISHED = "REFURBISHED"

    @property
    def label(self):
        return {
            "NEW": "جديد",
            "USED": "مستعمل",
            "REFURBISHED": "مجدّد",
        }[self.value]


class ShipmentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CREATED = "CREATED"
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    IN_CUSTOMS = "IN_CUSTOMS"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"

    @property
    def label(self):
        return {
            "DRAFT": "مسودة",
            "CREATED": "تم الإنشاء",
            "PENDING": "قيد الانتظار",
            "IN_TRANSIT": "قيد النقل",
            "IN_CUSTOMS": "في الجمارك",
            "ARRIVED": "وصلت",
            "DELIVERED": "تم التسليم",
            "CANCELLED": "ملغاة",
            "RETURNED": "مرتجعة",
        }[self.value]

    @property
    def color(self):
        return {
            "DRAFT": "secondary",
            "CREATED": "primary",
            "PENDING": "warning",
            "IN_TRANSIT": "info",
            "IN_CUSTOMS": "primary",
            "ARRIVED": "success",
            "DELIVERED": "success",
            "CANCELLED": "danger",
            "RETURNED": "warning",
        }[self.value]

    @property
    def icon(self):
        return {
            "DRAFT": "fa-edit",
            "CREATED": "fa-plus-circle",
            "PENDING": "fa-clock",
            "IN_TRANSIT": "fa-truck",
            "IN_CUSTOMS": "fa-building",
            "ARRIVED": "fa-check-circle",
            "DELIVERED": "fa-check-double",
            "CANCELLED": "fa-times-circle",
            "RETURNED": "fa-undo",
        }[self.value]


class ShipmentPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"

    @property
    def label(self):
        return {
            "LOW": "منخفضة",
            "NORMAL": "عادية",
            "HIGH": "عالية",
            "URGENT": "عاجلة",
        }[self.value]

    @property
    def color(self):
        return {
            "LOW": "success",
            "NORMAL": "info",
            "HIGH": "warning",
            "URGENT": "danger",
        }[self.value]

    @property
    def icon(self):
        return {
            "LOW": "fa-arrow-down",
            "NORMAL": "fa-minus",
            "HIGH": "fa-arrow-up",
            "URGENT": "fa-exclamation-triangle",
        }[self.value]


class DeliveryMethod(str, enum.Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    OVERNIGHT = "OVERNIGHT"
    SAME_DAY = "SAME_DAY"
    PICKUP = "PICKUP"

    @property
    def label(self):
        return {
            "STANDARD": "عادي",
            "EXPRESS": "سريع",
            "OVERNIGHT": "ليلي",
            "SAME_DAY": "نفس اليوم",
            "PICKUP": "استلام",
        }[self.value]

    @property
    def color(self):
        return {
            "STANDARD": "info",
            "EXPRESS": "warning",
            "OVERNIGHT": "primary",
            "SAME_DAY": "success",
            "PICKUP": "secondary",
        }[self.value]


class AccountType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"

    @property
    def label(self):
        return {
            "ASSET": "أصل",
            "LIABILITY": "التزام",
            "EQUITY": "حقوق ملكية",
            "REVENUE": "إيراد",
            "EXPENSE": "مصروف",
        }[self.value]


class DeletionType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    PARTNER = "PARTNER"
    SALE = "SALE"
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"
    PURCHASE = "PURCHASE"
    EXPENSE = "EXPENSE"
    SERVICE = "SERVICE"
    CHECK = "CHECK"
    SHIPMENT = "SHIPMENT"
    PREORDER = "PREORDER"

    @property
    def label(self):
        return {
            "CUSTOMER": "عميل",
            "SUPPLIER": "مورد",
            "PARTNER": "شريك",
            "SALE": "بيع",
            "INVOICE": "فاتورة",
            "PAYMENT": "دفعة",
            "PURCHASE": "مشتريات",
            "EXPENSE": "مصروف",
            "SERVICE": "طلب صيانة",
            "CHECK": "شيك",
            "SHIPMENT": "شحنة",
            "PREORDER": "حجز مسبق"
        }[self.value]


class DeletionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RESTORED = "RESTORED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "COMPLETED": "مكتمل",
            "FAILED": "فشل",
            "RESTORED": "مستعاد",
        }[self.value]

    @property
    def color(self):
        return {
            "PENDING": "warning",
            "COMPLETED": "success",
            "FAILED": "danger",
            "RESTORED": "info",
        }[self.value]

class TenantRegistry(db.Model):
    __tablename__ = "tenants"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False, index=True)
    schema_name = db.Column(db.String(63), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200))
    domain = db.Column(db.String(255), unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class SystemSettings(db.Model):
    __tablename__ = "system_settings"


    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.Text)
    data_type = db.Column(db.String(20), default='string')  # string, boolean, number, json
    is_public = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get_setting(cls, key, default=None):
        """Get a system setting value with transaction safety"""
        try:
            from extensions import cache
            cache_key = f"system_setting_{key}"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
        except Exception:
            pass
        
        try:
            setting = cls.query.filter_by(key=key).first()
        except Exception as e:
            # Handle failed transactions gracefully - Stronger Catch
            try:
                # Always rollback on any DB error here to be safe
                db.session.rollback()
                setting = cls.query.filter_by(key=key).first()
            except Exception:
                # If everything fails, return default to keep system running
                return default

        if not setting:
            return default
        
        if setting.data_type == 'boolean':
            return setting.value.lower() in ('true', '1', 'yes', 'on')
        elif setting.data_type == 'number':
            try:
                return float(setting.value)
            except (ValueError, TypeError):
                return default
        elif setting.data_type == 'json':
            try:
                result = json.loads(setting.value)
            except (ValueError, TypeError):
                result = default
        else:
            result = setting.value or default
        
        try:
            cache.set(cache_key, result, timeout=600)
        except Exception:
            pass
        return result

    @classmethod
    def set_setting(cls, key, value, description=None, data_type='string', is_public=False, commit=True):
        """Set a system setting value"""
        # Force Clear All Related Caches
        try:
            from extensions import cache
            cache.delete(f"system_setting_{key}")
            cache.delete("system_settings:bundle:v2") # Also clear bundle cache
            cache.delete("system_settings:template_settings:v1")
        except Exception:
            pass
        
        setting = cls.query.filter_by(key=key).first()
        if not setting:
            setting = cls(
                key=key,
                description=description,
                data_type=data_type,
                is_public=is_public
            )
            db.session.add(setting)
        
        if data_type == 'json':
            setting.value = json.dumps(value)
        else:
            setting.value = str(value)
        
        if description:
            setting.description = description
        if data_type:
            setting.data_type = data_type
        
        setting.is_public = is_public
        setting.updated_at = datetime.now(timezone.utc)
        if commit:
            db.session.commit()
            
        # Ensure change is reflected immediately
        try:
            db.session.expire(setting)
        except:
            pass
            
        return setting


class NotificationLog(db.Model):
    """سجل الإشعارات - Email & SMS"""
    __tablename__ = "notification_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False, index=True)  # email, sms, whatsapp
    recipient = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(500))
    content = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)  # pending, sent, failed, delivered
    provider_id = db.Column(db.String(100))  # Twilio SID, etc
    error_message = db.Column(db.Text)
    extra_data = db.Column(db.Text)  # JSON: {invoice_id, customer_id, etc} - renamed from metadata (reserved)
    sent_at = db.Column(db.DateTime, index=True)
    delivered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relations (optional)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), index=True)
    
    customer = db.relationship('Customer', backref='notifications')
    user = db.relationship('User', backref='notifications_sent')
    
    def __repr__(self):
        return f'<NotificationLog {self.type} to {self.recipient} - {self.status}>'
    
    @property
    def data(self):
        """Parse extra_data JSON"""
        if self.extra_data:
            try:
                return json.loads(self.extra_data)
            except Exception:
                return {}
        return {}
    
    @data.setter
    def data(self, value):
        """Set extra_data as JSON"""
        if value:
            self.extra_data = json.dumps(value, ensure_ascii=False)
        else:
            self.extra_data = None


class TaxEntry(db.Model):
    """سجلات الضرائب - VAT Tracking"""
    __tablename__ = "tax_entries"
    
    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(20), nullable=False, index=True)  # INPUT_VAT, OUTPUT_VAT, INCOME_TAX, WITHHOLDING
    transaction_type = db.Column(db.String(50), nullable=False, index=True)  # SALE, PURCHASE, SERVICE, PAYMENT
    transaction_id = db.Column(db.Integer, index=True)  # ID of Sale, Purchase, etc
    transaction_reference = db.Column(db.String(50), index=True)
    
    # Tax details
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False)  # 16.00 for 16%
    base_amount = db.Column(db.Numeric(12, 2), nullable=False)  # المبلغ الأساسي
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False)  # مبلغ الضريبة
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)  # الإجمالي
    currency = db.Column(db.String(3), default='ILS')
    
    # Accounting integration
    debit_account = db.Column(db.String(20))  # رقم الحساب المدين
    credit_account = db.Column(db.String(20))  # رقم الحساب الدائن
    gl_entry_id = db.Column(db.Integer)  # ربط مع GeneralLedgerEntry
    
    # Period tracking
    fiscal_year = db.Column(db.Integer, index=True)
    fiscal_month = db.Column(db.Integer, index=True)
    tax_period = db.Column(db.String(7), index=True)  # YYYY-MM
    
    # Status
    is_reconciled = db.Column(db.Boolean, default=False, index=True)
    is_filed = db.Column(db.Boolean, default=False, index=True)  # هل تم تقديمها في إقرار؟
    filing_reference = db.Column(db.String(100))  # رقم الإقرار
    
    # Relations
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id', ondelete='SET NULL'), index=True)
    
    # Metadata
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    customer = db.relationship('Customer', backref='tax_entries')
    supplier = db.relationship('Supplier', backref='tax_entries')
    creator = db.relationship('User', backref='tax_entries_created')
    
    __table_args__ = (
        Index('idx_tax_period_type', 'tax_period', 'entry_type'),
        Index('idx_tax_transaction', 'transaction_type', 'transaction_id'),
    )
    
    def __repr__(self):
        return f'<TaxEntry {self.entry_type} {self.tax_amount} {self.currency}>'


class Currency(db.Model):
    __tablename__ = "currencies"
    code = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    symbol = db.Column(db.String(10))
    decimals = db.Column(db.Integer, nullable=False, server_default=sa_text("2"), default=2)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), default=True)


class DeletionLog(db.Model):
    """سجل عمليات الحذف القوي مع إمكانية الاستعادة"""
    __tablename__ = "deletion_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    deletion_type = db.Column(db.String(20), nullable=False, index=True)  # DeletionType
    entity_id = db.Column(db.Integer, nullable=False, index=True)  # معرف الكيان المحذوف
    entity_name = db.Column(db.String(200), nullable=False)  # اسم الكيان المحذوف
    status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)  # DeletionStatus
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # تفاصيل الحذف
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    deletion_reason = db.Column(db.Text)  # سبب الحذف
    confirmation_code = db.Column(db.String(50), unique=True, index=True)  # كود التأكيد
    
    # البيانات المحذوفة (JSON)
    deleted_data = db.Column(db.JSON)  # البيانات المحذوفة للاستعادة
    related_entities = db.Column(db.JSON)  # الكيانات المرتبطة المحذوفة
    
    # تفاصيل العمليات العكسية
    stock_reversals = db.Column(db.JSON)  # عمليات إرجاع المخزون
    accounting_reversals = db.Column(db.JSON)  # عمليات إرجاع المحاسبة
    balance_reversals = db.Column(db.JSON)  # عمليات إرجاع الأرصدة
    
    # تفاصيل الاستعادة
    restored_at = db.Column(db.DateTime)
    restored_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    restoration_notes = db.Column(db.Text)
    
    # علاقات
    deleted_by_user = db.relationship("User", foreign_keys=[deleted_by], backref="deletions_made")
    restored_by_user = db.relationship("User", foreign_keys=[restored_by], backref="deletions_restored")
    
    __table_args__ = (
        db.Index('ix_deletion_type_status', 'deletion_type', 'status'),
        db.Index('ix_deletion_entity', 'deletion_type', 'entity_id'),
        db.CheckConstraint("status IN ('PENDING','COMPLETED','FAILED','RESTORED')", name='chk_deletion_status'),
    )
    
    def __repr__(self):
        return f"<DeletionLog {self.deletion_type}:{self.entity_id} by {self.deleted_by}>"
    
    @property
    def can_restore(self):
        """هل يمكن استعادة هذا الحذف؟"""
        return self.status == DeletionStatus.COMPLETED.value and self.deleted_data is not None
    
    @property
    def is_restored(self):
        """هل تم استعادة هذا الحذف؟"""
        return self.status == DeletionStatus.RESTORED.value
    
    def mark_completed(self, deleted_data=None, related_entities=None, 
                      stock_reversals=None, accounting_reversals=None, balance_reversals=None):
        """تسجيل اكتمال الحذف"""
        self.status = DeletionStatus.COMPLETED.value
        self.deleted_data = deleted_data
        self.related_entities = related_entities
        self.stock_reversals = stock_reversals
        self.accounting_reversals = accounting_reversals
        self.balance_reversals = balance_reversals
    
    def mark_failed(self, error_message):
        """تسجيل فشل الحذف"""
        self.status = DeletionStatus.FAILED.value
        self.deletion_reason = f"{self.deletion_reason or ''}\nخطأ: {error_message}"
    
    def mark_restored(self, restored_by, notes=None):
        """تسجيل الاستعادة"""
        self.status = DeletionStatus.RESTORED.value
        self.restored_at = datetime.now(timezone.utc)
        self.restored_by = restored_by
        self.restoration_notes = notes

class ExchangeRate(db.Model):
    __tablename__ = "exchange_rates"
    id = db.Column(db.Integer, primary_key=True)
    base_code = db.Column(db.String(10), db.ForeignKey("currencies.code"), nullable=False, index=True)
    quote_code = db.Column(db.String(10), db.ForeignKey("currencies.code"), nullable=False, index=True)
    rate = db.Column(Numeric(18, 8), nullable=False)
    valid_from = db.Column(db.DateTime, nullable=False, index=True, server_default=func.now(), default=func.now())
    source = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), default=True)
    __table_args__ = (
        db.UniqueConstraint("base_code", "quote_code", "valid_from", name="uq_fx_pair_from"),
    )

class BlockedIP(db.Model):
    __tablename__ = 'blocked_ips'
    
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(50), unique=True, nullable=False, index=True)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)
    blocked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

class BlockedCountry(db.Model):
    __tablename__ = 'blocked_countries'
    
    id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(db.String(2), unique=True, nullable=False, index=True)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    blocked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

def _currency_codes_from_db() -> set[str]:
    try:
        with db.session.no_autoflush:
            rows = db.session.query(Currency.code).filter(Currency.is_active.is_(True)).all()
        s = {str(r[0]).upper().strip() for r in rows}
        return {c for c in s if c}
    except Exception:
        return set()

def currency_codes() -> set[str]:
    dynamic = _currency_codes_from_db()
    if dynamic:
        return dynamic
    return {c for c, _ in CURRENCY_CHOICES}

def currency_decimals(code: str | None) -> int:
    c = (code or "").upper().strip()
    try:
        with db.session.no_autoflush:
            row = db.session.query(Currency.decimals).filter(Currency.code == c).one_or_none()
        if row and isinstance(row[0], int):
            return row[0]
    except Exception:
        pass
    return 2

ALLOWED_PAYMENT_DIRECTIONS: dict[PaymentEntityType, set[str]] = {
    PaymentEntityType.CUSTOMER: {"IN", "OUT"},
    PaymentEntityType.SUPPLIER: {"IN", "OUT"},
    PaymentEntityType.PARTNER: {"IN", "OUT"},
    PaymentEntityType.SALE: {"IN", "OUT"},
    PaymentEntityType.SERVICE: {"IN", "OUT"},
    PaymentEntityType.INVOICE: {"IN", "OUT"},
    PaymentEntityType.PREORDER: {"IN", "OUT"},
    PaymentEntityType.LOAN: {"IN", "OUT"},
    PaymentEntityType.EXPENSE: {"OUT"},  # المصاريف دائماً صادرة
    PaymentEntityType.SHIPMENT: {"IN", "OUT"},
}

def is_direction_allowed(entity_type: PaymentEntityType | str, direction: PaymentDirection | str) -> bool:
    try:
        # إذا كان entity_type هو بالفعل PaymentEntityType، نستخدمه مباشرة
        if isinstance(entity_type, PaymentEntityType):
            et = entity_type
        else:
            # إذا كان string، نحوله
            et = PaymentEntityType(str(entity_type))
    except Exception:
        return False
    try:
        # إذا كان direction هو بالفعل PaymentDirection، نحصل على value
        if isinstance(direction, PaymentDirection):
            d = direction.value
        else:
            # نحاول التحويل
            d = PaymentDirection(str(direction)).value
    except Exception:
        # إذا فشل، نستخدم الـ string مباشرة
        d = str(direction).upper()
    allowed = ALLOWED_PAYMENT_DIRECTIONS.get(et, set())
    return d in allowed

MONEY_QUANT = TWOPLACES

def money(x) -> Decimal:
    try:
        return Decimal(str(x or 0)).quantize(MONEY_QUANT, ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def generate_idempotency_key(prefix: str = "pay") -> str:
    raw = f"{prefix}:{uuid.uuid4()}:{datetime.now(timezone.utc).timestamp()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]

def ensure_currency(cur: str | None, default: str = "ILS") -> str:
    base = (default or "ILS").upper().strip()
    c = (cur or base).upper().strip()
    pool = currency_codes()
    return c if c in pool else base

def _get_payment_model():
    P = globals().get("Payment")
    if P is not None:
        return P
    try:
        from models import Payment as _P
        return _P
    except Exception:
        return None

@lru_cache(maxsize=2048)
def _get_rate_cached(base: str, quote: str, date_str: str) -> Decimal | None:
    """نسخة مخزنة مؤقتاً (Cached) لجلب سعر الصرف لليوم المحدد"""
    try:
        # نستخدم نهاية اليوم لضمان شمول أي سعر تم تحديده خلال اليوم
        # date_str is YYYY-MM-DD
        t = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        
        # 1. البحث المحلي
        try:
            with db.engine.connect() as conn:
                local_rate = _fx_rate_local_via_connection(conn, base, quote, t)
            if local_rate and local_rate > Decimal("0"):
                return local_rate
        except Exception:
            pass

        # 2. البحث الخارجي (فقط إذا لم يوجد محلي)
        online_rate = _fetch_external_fx_rate(base, quote, t)
        if online_rate and online_rate > Decimal("0"):
            return online_rate
            
    except Exception:
        pass
    return None


def _fx_rate_local_via_connection(connection, base: str, quote: str, at: datetime | None = None) -> Decimal:
    b = ensure_currency(base)
    qv = ensure_currency(quote)
    if b == qv:
        return Decimal("1")
    t = at or datetime.now(timezone.utc)
    try:
        from sqlalchemy import select as sa_select
        
        # 1. Priority: Manual Rate for TODAY (Overrides any online rate for same day)
        today_start = t.replace(hour=0, minute=0, second=0, microsecond=0)
        manual_today = connection.execute(
            sa_select(ExchangeRate.rate)
            .where(
                ExchangeRate.base_code == b,
                ExchangeRate.quote_code == qv,
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from >= today_start,
                ExchangeRate.valid_from <= t,
                ExchangeRate.source != 'External API' # Not auto-generated
            )
            .order_by(ExchangeRate.valid_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        
        if manual_today is not None:
            try:
                val = Decimal(str(manual_today))
                if val > Decimal("0"):
                    return val
            except Exception:
                pass # Invalid manual rate, fallback to online/latest

        # 2. Fallback: Latest Rate (Manual or Online)
        row = connection.execute(
            sa_select(ExchangeRate.rate)
            .where(
                ExchangeRate.base_code == b,
                ExchangeRate.quote_code == qv,
                ExchangeRate.is_active.is_(True),
                ExchangeRate.valid_from <= t,
            )
            .order_by(ExchangeRate.valid_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        return Decimal(str(row)) if row is not None else Decimal("0")
    except Exception:
        return Decimal("0")

def fx_rate(base: str, quote: str, at: datetime | None = None, raise_on_missing: bool = False) -> Decimal:
    """سعر الصرف الذكي - محلي أولاً، ثم عالمي
    
    Args:
        base: العملة الأساسية
        quote: العملة المقابلة
        at: التاريخ (اختياري)
        raise_on_missing: إذا True، يرمي استثناء بدلاً من إرجاع صفر
    
    Returns:
        سعر الصرف أو Decimal("0") أو يرمي استثناء
    """
    b = ensure_currency(base)
    qv = ensure_currency(quote)
    if b == qv:
        return Decimal("1")
    
    t = at or datetime.now(timezone.utc)
    # استخدام التاريخ كـ Key للكاش (يومياً)
    date_key = t.strftime("%Y-%m-%d")
    
    try:
        rate = _get_rate_cached(b, qv, date_key)
        if rate is not None:
            return rate
    except Exception:
        pass

    # إذا فشل الكاش أو لم يجد نتيجة
    if raise_on_missing:
        raise ValueError(f"⚠️ سعر الصرف غير متوفر لـ {b}/{qv}. يرجى:\n1. إدخال سعر يدوي من إعدادات العملات\n2. تفعيل السيرفر الأونلاين\n3. إعادة المحاولة لاحقاً")
    
    return Decimal("0")

def _fetch_external_fx_rate(base: str, quote: str, at: datetime) -> Decimal:
    """سحب سعر الصرف من السيرفرات العالمية مع التحكم في الإعدادات"""
    import requests
    import json
    from decimal import Decimal
    
    # التحقق من إعدادات النظام
    try:
        from models import SystemSettings
        online_fx_enabled = SystemSettings.get_setting('online_fx_enabled', True)
        if not online_fx_enabled:
            return None
    except Exception:
        # في حالة عدم وجود SystemSettings، استمر بالطريقة العادية
        pass
    
    # قائمة السيرفرات العالمية (بترتيب الأولوية)
    fx_services = [
        _fetch_from_fixer_io,
        _fetch_from_exchangerate_api,
        _fetch_from_currencylayer,
        _fetch_from_exchangerate_host
    ]
    
    for service in fx_services:
        try:
            rate = service(base, quote, at)
            if rate and rate > Decimal("0"):
                # حفظ السعر في قاعدة البيانات للاستخدام المستقبلي
                _save_external_rate(base, quote, rate, at)
                return rate
        except Exception:
            continue
    
    raise ValueError("fx.external_services_unavailable")

def _fetch_from_fixer_io(base: str, quote: str, at: datetime) -> Decimal:
    """سحب من Fixer.io"""
    import requests
    from decimal import Decimal
    
    # Fixer.io API (مجاني مع حدود)
    url = f"http://data.fixer.io/api/latest"
    params = {
        'access_key': 'YOUR_FIXER_API_KEY',  # يحتاج API key
        'base': base,
        'symbols': quote
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    if data.get('success') and quote in data.get('rates', {}):
        return Decimal(str(data['rates'][quote]))
    
    raise ValueError("fixer_io_failed")

def _fetch_from_exchangerate_api(base: str, quote: str, at: datetime) -> Decimal:
    """سحب من ExchangeRate-API.com"""
    import requests
    from decimal import Decimal
    
    # ExchangeRate-API.com (مجاني بدون API key)
    url = f"https://api.exchangerate-api.com/v4/latest/{base}"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if 'rates' in data and quote in data['rates']:
        return Decimal(str(data['rates'][quote]))
    
    raise ValueError("exchangerate_api_failed")

def _fetch_from_currencylayer(base: str, quote: str, at: datetime) -> Decimal:
    """سحب من CurrencyLayer"""
    import requests
    from decimal import Decimal
    
    # CurrencyLayer API
    url = f"http://api.currencylayer.com/live"
    params = {
        'access_key': 'YOUR_CURRENCYLAYER_API_KEY',  # يحتاج API key
        'currencies': quote,
        'source': base
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    if data.get('success') and f"{base}{quote}" in data.get('quotes', {}):
        return Decimal(str(data['quotes'][f"{base}{quote}"]))
    
    raise ValueError("currencylayer_failed")

def _fetch_from_exchangerate_host(base: str, quote: str, at: datetime) -> Decimal:
    """سحب من ExchangeRate-Host"""
    import requests
    from decimal import Decimal
    
    # ExchangeRate-Host (مجاني)
    url = f"https://api.exchangerate.host/latest"
    params = {
        'base': base,
        'symbols': quote
    }
    
    response = requests.get(url, params=params, timeout=10)
    data = response.json()
    
    if data.get('success') and 'rates' in data and quote in data['rates']:
        return Decimal(str(data['rates'][quote]))
    
    raise ValueError("exchangerate_host_failed")

def _save_external_rate(base: str, quote: str, rate: Decimal, at: datetime):
    """حفظ السعر الخارجي في قاعدة البيانات"""
    try:
        from sqlalchemy import text as sa_text
        
        with db.engine.begin() as conn:
            result = conn.execute(
                sa_text(
                    """
                    SELECT id FROM exchange_rates
                    WHERE base_code = :base
                    AND quote_code = :quote
                    AND DATE(valid_from) = DATE(:valid_from)
                    LIMIT 1
                    """
                ),
                {"base": base, "quote": quote, "valid_from": at},
            ).fetchone()
            if not result:
                conn.execute(
                    sa_text(
                        """
                        INSERT INTO exchange_rates
                        (base_code, quote_code, rate, valid_from, source, is_active)
                        VALUES (:base, :quote, :rate, :valid_from, 'External API', 1)
                        """
                    ),
                    {"base": base, "quote": quote, "rate": float(rate), "valid_from": at},
                )
    except Exception:
        pass

def convert_amount(amount: Decimal | float | str, from_code: str, to_code: str, at: datetime | None = None) -> Decimal:
    amt = money(amount)
    r = fx_rate(from_code, to_code, at)
    if r <= Decimal("0"):
        raise ValueError("fx.rate_unavailable")
    return money(amt * r)

def auto_update_missing_rates():
    """تحديث تلقائي للأسعار المفقودة من السيرفرات العالمية"""
    try:
        # الحصول على جميع العملات النشطة
        currencies = db.session.query(Currency).filter_by(is_active=True).all()
        currency_codes = [c.code for c in currencies]
        
        updated_count = 0
        today = datetime.now(timezone.utc).date()
        
        for base_code in currency_codes:
            for quote_code in currency_codes:
                if base_code == quote_code:
                    continue
                
                # التحقق من وجود سعر لهذا اليوم
                existing_rate = db.session.query(ExchangeRate).filter(
                    ExchangeRate.base_code == base_code,
                    ExchangeRate.quote_code == quote_code,
                    ExchangeRate.valid_from == today
                ).first()
                
                if not existing_rate:
                    try:
                        # محاولة سحب السعر من السيرفرات العالمية
                        rate = _fetch_external_fx_rate(base_code, quote_code, datetime.now(timezone.utc))
                        if rate and rate > Decimal("0"):
                            updated_count += 1
                    except Exception:
                        continue
        
        return {
            'success': True,
            'updated_rates': updated_count,
            'message': f'تم تحديث {updated_count} سعر صرف'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'فشل في التحديث التلقائي'
        }

def get_fx_rate_with_fallback(base: str, quote: str, at: datetime | None = None) -> dict:
    """الحصول على سعر الصرف مع معلومات المصدر والبديل الذكي - يدوي أولاً، ثم أونلاين"""
    try:
        b = ensure_currency(base)
        qv = ensure_currency(quote)
        if b == qv:
            return {
                'rate': 1.0,
                'source': 'same_currency',
                'base': base,
                'quote': quote,
                'timestamp': at or datetime.now(timezone.utc),
                'success': True
            }
        
        t = at or datetime.now(timezone.utc)
        
        local_rate_value = None
        try:
            with db.session.no_autoflush:
                q = (
                    db.session.query(ExchangeRate.rate, ExchangeRate.source)
                    .filter(
                        ExchangeRate.base_code == b,
                        ExchangeRate.quote_code == qv,
                        ExchangeRate.is_active.is_(True),
                        ExchangeRate.valid_from <= t,
                    )
                    .order_by(ExchangeRate.valid_from.desc())
                )
                v = q.first()
            if v:
                local_rate_value = Decimal(str(v[0]))
                rate_source = v[1]
                
                if local_rate_value and local_rate_value > Decimal("0"):
                    is_manual = (rate_source != 'External API')
                    return {
                        'rate': float(local_rate_value),
                        'source': 'manual' if is_manual else 'online_cached',
                        'base': base,
                        'quote': quote,
                        'timestamp': at or datetime.now(timezone.utc),
                        'success': True
                    }
        except Exception:
            pass
        
        try:
            online_rate = _fetch_external_fx_rate(b, qv, t)
            if online_rate and online_rate > Decimal("0"):
                return {
                    'rate': float(online_rate),
                    'source': 'online',
                    'base': base,
                    'quote': quote,
                    'timestamp': at or datetime.now(timezone.utc),
                    'success': True
                }
        except Exception:
            pass
        
        return {
            'rate': 0.0,
            'source': 'unavailable',
            'base': base,
            'quote': quote,
            'timestamp': at or datetime.now(timezone.utc),
            'success': False,
            'error': f'سعر الصرف غير متوفر لـ {b}/{qv}. يرجى إدخال سعر يدوي من صفحة إدارة العملات أو تفعيل السيرفر الأونلاين.',
            'message_ar': f'⚠️ سعر الصرف غير متوفر لـ {b}/{qv}',
            'instructions': [
                '1. إدخال سعر يدوي من صفحة إدارة العملات',
                '2. تفعيل السيرفر الأونلاين من إعدادات العملات',
                '3. التحقق من اتصال الإنترنت إذا كان الأونلاين مفعّل'
            ]
        }
        
    except Exception as e:
        return {
            'rate': 0.0,
            'source': 'failed',
            'base': base,
            'quote': quote,
            'timestamp': at or datetime.now(timezone.utc),
            'success': False,
            'error': str(e)
        }

def _payment_fk_column_for_type(PaymentModel, et: PaymentEntityType | str):
    etv = PaymentEntityType(str(et)).value
    mapping = {
        "CUSTOMER": PaymentModel.customer_id,
        "SUPPLIER": PaymentModel.supplier_id,
        "PARTNER": PaymentModel.partner_id,
        "SHIPMENT": PaymentModel.shipment_id,
        "EXPENSE": PaymentModel.expense_id,
        "LOAN": PaymentModel.loan_settlement_id,
        "SALE": PaymentModel.sale_id,
        "INVOICE": PaymentModel.invoice_id,
        "PREORDER": PaymentModel.preorder_id,
        "SERVICE": PaymentModel.service_id,
    }
    return mapping.get(etv)

def refundable_amount_for(entity_type: PaymentEntityType | str, entity_id: int, currency: str | None = None) -> Decimal:
    PaymentModel = _get_payment_model()
    if PaymentModel is None:
        return Decimal("0.00")

    et = PaymentEntityType(str(entity_type))
    ccy = ensure_currency(currency)
    fk_col = _payment_fk_column_for_type(PaymentModel, et)
    if fk_col is None:
        return Decimal("0.00")

    sess = db.session

    total_in_completed = Decimal(str(
        sess.query(func.coalesce(func.sum(PaymentModel.total_amount), 0))
        .filter(
            PaymentModel.entity_type == et.value,
            fk_col == int(entity_id),
            PaymentModel.currency == ccy,
            PaymentModel.direction == PaymentDirection.IN.value,
            PaymentModel.status == PaymentStatus.COMPLETED.value,
        ).scalar() or 0
    ))

    total_out_pending_completed = Decimal(str(
        sess.query(func.coalesce(func.sum(PaymentModel.total_amount), 0))
        .filter(
            PaymentModel.entity_type == et.value,
            fk_col == int(entity_id),
            PaymentModel.currency == ccy,
            PaymentModel.direction == PaymentDirection.OUT.value,
            PaymentModel.status.in_([PaymentStatus.PENDING.value, PaymentStatus.COMPLETED.value]),
        ).scalar() or 0
    ))

    remaining = total_in_completed - total_out_pending_completed
    return money(remaining)

def receivable_amount_for(entity_type: PaymentEntityType | str, entity_id: int, currency: str | None = None) -> Decimal:
    PaymentModel = _get_payment_model()
    if PaymentModel is None:
        return Decimal("0.00")

    et = PaymentEntityType(str(entity_type))
    ccy = ensure_currency(currency)
    fk_col = _payment_fk_column_for_type(PaymentModel, et)
    if fk_col is None:
        return Decimal("0.00")

    sess = db.session

    total_out_completed = Decimal(str(
        sess.query(func.coalesce(func.sum(PaymentModel.total_amount), 0))
        .filter(
            PaymentModel.entity_type == et.value,
            fk_col == int(entity_id),
            PaymentModel.currency == ccy,
            PaymentModel.direction == PaymentDirection.OUT.value,
            PaymentModel.status == PaymentStatus.COMPLETED.value,
        ).scalar() or 0
    ))

    total_in_pending_completed = Decimal(str(
        sess.query(func.coalesce(func.sum(PaymentModel.total_amount), 0))
        .filter(
            PaymentModel.entity_type == et.value,
            fk_col == int(entity_id),
            PaymentModel.currency == ccy,
            PaymentModel.direction == PaymentDirection.IN.value,
            PaymentModel.status.in_([PaymentStatus.PENDING.value, PaymentStatus.COMPLETED.value]),
        ).scalar() or 0
    ))

    remaining = total_out_completed - total_in_pending_completed
    return money(remaining)


def validate_payment_policies(*, entity_type: PaymentEntityType | str, entity_id: int, direction: PaymentDirection | str, amount, currency: str | None = None) -> None:
    amt = money(amount)
    if amt <= Decimal("0.00"):
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")

    cur = ensure_currency(currency)

    try:
        dval = PaymentDirection(str(direction)).value
    except Exception:
        dval = str(direction).upper()

    et = PaymentEntityType(str(entity_type))

    # السماح بجميع الاتجاهات للجميع عدا النفقات
    # النفقات دائماً صادرة فقط
    if et == PaymentEntityType.EXPENSE and dval == "IN":
        raise ValueError("النفقات دائماً صادرة فقط")

    # إزالة القيود الأخرى للسماح بمرونة أكبر في الدفعات
    # يمكن إضافة قيود إضافية هنا حسب الحاجة

class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), default=func.now(), index=True)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), default=func.now(), onupdate=func.now(), index=True)

class AuditMixin:
    @classmethod
    def __declare_last__(cls):
        from sqlalchemy import event as _evt

        @_evt.listens_for(cls, "before_update", propagate=True)
        def _capture_prev_state(mapper, connection, target):
            try:
                insp = inspect(target)
                prev = {}
                for attr in mapper.column_attrs:
                    hist = insp.attrs[attr.key].history
                    if hist.has_changes() and hist.deleted:
                        prev[attr.key] = hist.deleted[0]
                setattr(target, "_previous_state", prev)
            except Exception:
                setattr(target, "_previous_state", {})

class AuthEvent(str, enum.Enum):
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAIL = "LOGIN_FAIL"
    PASSWORD_SET = "PASSWORD_SET"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    USER_ACTIVATE = "USER_ACTIVATE"
    USER_DEACTIVATE = "USER_DEACTIVATE"
    ROLE_CHANGE = "ROLE_CHANGE"
    PERM_GRANT = "PERM_GRANT"
    PERM_REVOKE = "PERM_REVOKE"


class AuthAudit(db.Model):
    __tablename__ = "auth_audit"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)
    event = db.Column(db.String(40), nullable=False, index=True)
    success = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"))
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    note = db.Column(db.String(255))
    meta = db.Column("metadata", db.JSON, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), index=True)

    user = relationship("User", backref=db.backref("auth_events", lazy="dynamic"))



def _auth_log(
    event: AuthEvent | str,
    *,
    user_id: int | None,
    success: bool = True,
    note: str | None = None,
    meta: dict | None = None,
) -> None:
    try:
        ip = request.remote_addr if has_request_context() else None
        ua = request.user_agent.string if has_request_context() and request.user_agent else None
    except Exception:
        ip, ua = None, None

    rec = AuthAudit(
        user_id=user_id,
        event=str(event),
        success=bool(success),
        ip=ip,
        user_agent=ua,
        note=note,
        meta=meta or {},
    )

    try:
        cu = getattr(current_user, "_get_current_object", lambda: None)()
    except Exception:
        cu = None

    sess = None
    if cu is not None:
        try:
            sess = object_session(cu)
        except Exception:
            sess = None
    if sess is None:
        sess = db.session

    try:
        sess.add(rec)
    except Exception:
        pass

class User(db.Model, UserMixin, TimestampMixin, AuditMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), index=True)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"))
    is_system_account = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)
    last_login = db.Column(db.DateTime)
    last_seen = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(64))
    login_count = db.Column(db.Integer, nullable=False, server_default=sa_text("0"))
    avatar_url = db.Column(db.String(500))
    notes_text = db.Column(db.Text)
    role = relationship("Role", backref="users", lazy="select")
    extra_permissions = relationship(
        "Permission",
        secondary=user_permissions,
        backref=db.backref("extra_users", lazy="dynamic"),
        lazy="dynamic",
    )

    mechanic_service_requests = relationship(
        "ServiceRequest",
        back_populates="mechanic",
        lazy="dynamic",
        foreign_keys="[ServiceRequest.mechanic_id]",
    )
    cancelled_service_requests = relationship(
        "ServiceRequest",
        back_populates="cancelled_by_user",
        lazy="dynamic",
        foreign_keys="[ServiceRequest.cancelled_by]",
    )

    sales = relationship(
        "Sale",
        back_populates="seller",
        lazy="dynamic",
        foreign_keys="[Sale.seller_id]",
    )
    cancelled_sales = relationship(
        "Sale",
        back_populates="cancelled_by_user",
        lazy="dynamic",
        foreign_keys="[Sale.cancelled_by]",
    )

    __table_args__ = ()

    @validates("email")
    def _v_email(self, key, value):
        return (value or "").strip().lower()

    @validates("username")
    def _v_username(self, key, value):
        return (value or "").strip()

    @property
    def role_name_l(self) -> str:
        return (getattr(self.role, "name", "") or "").strip().lower()

    @property
    def is_system(self) -> bool:
        """حساب نظام محمي ومخفي"""
        return bool(getattr(self, 'is_system_account', False)) or self.username == '__OWNER__'
    
    @property
    def is_super_role(self) -> bool:
        from permissions_config.permissions import PermissionsRegistry
        return self.role_name_l in {r.lower() for r in PermissionsRegistry.get_super_roles()} or self.is_system

    @property
    def is_admin_role(self) -> bool:
        return self.role_name_l == "admin"

    def set_password(self, password: str) -> None:
        if not password or not isinstance(password, str):
            raise ValueError("password required")
        prev = bool(self.password_hash)
        try:
            method = None
            try:
                from flask import has_app_context, current_app
                if has_app_context():
                    method = current_app.config.get("PASSWORD_HASH_METHOD")
            except Exception:
                method = None
            if method:
                self.password_hash = generate_password_hash(password, method=method)
            else:
                self.password_hash = generate_password_hash(password)
        except Exception:
            self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        try:
            from flask import has_request_context
            if has_request_context():
                _auth_log(
                    AuthEvent.PASSWORD_CHANGE if prev else AuthEvent.PASSWORD_SET,
                    user_id=getattr(self, "id", None),
                    success=True,
                )
        except Exception:
            pass

    def check_password(self, password: str) -> bool:
        try:
            ok = bool(self.password_hash) and check_password_hash(self.password_hash, password or "")
            if not ok:
                try:
                    from flask import has_request_context
                    if has_request_context():
                        _auth_log(AuthEvent.LOGIN_FAIL, user_id=getattr(self, "id", None), success=False)
                except Exception:
                    pass
            return ok
        except Exception:
            try:
                from flask import has_request_context
                if has_request_context():
                    _auth_log(AuthEvent.LOGIN_FAIL, user_id=getattr(self, "id", None), success=False, note="exception")
            except Exception:
                pass
            return False

    def mark_login(self, ip: str | None = None) -> None:
        self.last_login = datetime.now(timezone.utc)
        self.last_seen = self.last_login
        if ip:
            self.last_login_ip = ip
        try:
            self.login_count = int(self.login_count or 0) + 1
        except Exception:
            self.login_count = 1
        try:
            from flask import has_request_context
            if has_request_context():
                _auth_log(AuthEvent.LOGIN_SUCCESS, user_id=getattr(self, "id", None), success=True)
        except Exception:
            pass

    def has_role(self, *names: str) -> bool:
        r = self.role_name_l
        return any(r == (n or "").strip().lower() for n in names if n)

    def has_permission(self, code: str) -> bool:
        if not code:
            return False
        from utils.tenant_permissions import is_tenant_request, tenant_owner_has_permission

        if is_tenant_request():
            if self.is_system or self.is_super_role:
                return tenant_owner_has_permission(self, code)
        elif self.is_system or self.is_super_role:
            return True
        from utils import _expand_perms, _get_user_permissions
        targets = {c.strip().lower() for c in _expand_perms(code)}
        perms = _get_user_permissions(self) or set()
        return bool(perms & targets)

    def touch(self) -> None:
        self.last_seen = datetime.now(timezone.utc)

    @property
    def avatar_or_initials(self) -> str:
        """Returns avatar URL if available, otherwise returns initials"""
        if self.avatar_url:
            return self.avatar_url
        
        # Generate initials from username or email
        name = self.username or self.email or "U"
        initials = "".join([word[0].upper() for word in name.split()[:2]])
        return initials[:2] if initials else "U"

    @property
    def display_name(self) -> str:
        """Returns display name for the user"""
        return self.username or self.email or f"User {self.id}"

    def __repr__(self):
        return f"<User {self.username or self.id}>"

class Permission(db.Model, AuditMixin):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    code = db.Column(db.String(100), unique=True, index=True)
    description = db.Column(db.String(255))
    name_ar = db.Column(db.String(120))
    module = db.Column(db.String(50), index=True)
    is_protected = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), default=False)
    aliases = db.Column(db.JSON, default=list)

    __table_args__ = ()

    @validates("name", "code")
    def _v_norm(self, key, value):
        v = (value or "").strip()
        if key == "code":
            v = v.lower()
        return v

    @validates("module")
    def _v_module(self, _, v):
        v = (v or "").strip().lower()
        return v or None

    @validates("is_protected")
    def _v_protected(self, _, v):
        return bool(v)

    @validates("aliases")
    def _v_aliases(self, _, v):
        if not v:
            return []
        if isinstance(v, str):
            try:
                arr = json.loads(v)
            except Exception:
                arr = [x for x in v.split(",")]
        elif isinstance(v, (list, tuple, set)):
            arr = list(v)
        else:
            arr = []
        out = []
        for a in arr:
            s = str(a or "").strip().lower()
            s = re.sub(r"[\s\-]+", "_", s)
            s = re.sub(r"[^a-z0-9_]+", "", s)
            s = re.sub(r"_+", "_", s).strip("_")
            if s and s not in out:
                out.append(s)
        return out

    @property
    def display_name(self) -> str:
        try:
            nm_ar = getattr(self, "name_ar", None)
            return (nm_ar or self.name or "").strip()
        except Exception:
            return (self.name or "").strip()

    def key(self) -> str:
        return (self.code or self.name or "").strip().lower()

    @property
    def aliases_set(self) -> set[str]:
        return set(self.aliases or [])

    @property
    def all_keys(self) -> set[str]:
        base = {self.key()}
        nm = (self.name or "").strip().lower()
        if nm:
            base.add(nm)
        return base | self.aliases_set

    def __repr__(self):
        return f"<Permission {self.code or self.name}>"

class Role(db.Model, AuditMixin):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200))
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    permissions = relationship(
        "Permission",
        secondary=role_permissions,
        lazy="selectin",
        backref=db.backref("role_permissions", lazy="selectin"),
    )

    __table_args__ = ()

    @validates("name")
    def _v_name(self, key, value):
        return (value or "").strip()

    def has_permission(self, code: str) -> bool:
        from utils import _expand_perms, get_role_permissions
        if not code:
            return False
        targets = {c.strip().lower() for c in _expand_perms(code)}
        perms = get_role_permissions(self) or set()
        return bool(perms & targets)

    def __repr__(self):
        return f"<Role {self.name}>"

class Customer(db.Model, TimestampMixin, AuditMixin, UserMixin):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    whatsapp = Column(String(20), nullable=True)  # ✅ يسمح بـ NULL
    email = Column(String(120), unique=True, nullable=True)  # ✅ يسمح بـ NULL
    address = Column(String(200))
    password_hash = Column(String(512))
    category = Column(String(20), default="عادي")
    notes = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False, server_default=sa_text("true"))
    is_online = Column(Boolean, default=False, nullable=False, server_default=sa_text("false"))
    is_archived = Column(Boolean, default=False, nullable=False, server_default=sa_text("false"))
    archived_at = Column(DateTime, index=True)
    archived_by = Column(Integer, ForeignKey("users.id"), index=True)
    archive_reason = Column(String(200))
    credit_limit = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    discount_rate = Column(Numeric(5, 2), default=0, nullable=False, server_default=sa_text("0"))
    currency = Column(String(10), default="ILS", nullable=False, server_default=sa_text("'ILS'"))
    opening_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="الرصيد الافتتاحي (موجب=له رصيد عندنا، سالب=لنا رصيد عنده)")
    
    current_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), index=True, comment="الرصيد الحالي المحدث")
    sales_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المبيعات")
    returns_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المرتجعات")
    invoices_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الفواتير")
    services_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الخدمات")
    preorders_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الحجوزات المسبقة")
    online_orders_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الطلبات الأونلاين")
    payments_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الواردة")
    payments_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الصادرة")
    checks_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات الواردة")
    checks_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات الصادرة")
    returned_checks_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الواردة")
    returned_checks_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الصادرة")
    expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المصروفات العادية (تُطرح)")
    service_expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد مصروفات توريد الخدمات (تُضاف)")

    sales = relationship("Sale", back_populates="customer")
    preorders = relationship("PreOrder", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")
    payments = relationship("Payment", back_populates="customer")
    service_requests = relationship("ServiceRequest", back_populates="customer")
    online_carts = relationship("OnlineCart", back_populates="customer")
    online_preorders = relationship("OnlinePreOrder", back_populates="customer")
    expenses = relationship("Expense", back_populates="customer")
    archived_by_user = relationship("User", foreign_keys=[archived_by])

    __table_args__ = (
        CheckConstraint("credit_limit >= 0", name="ck_customer_credit_limit_non_negative"),
        CheckConstraint("discount_rate >= 0 AND discount_rate <= 100", name="ck_customer_discount_0_100"),
        Index("ix_customers_active_name", "is_active", "name"),
        Index("ix_customers_online_active", "is_online", "is_active"),
        Index("ix_customers_opening_balance", "opening_balance"),
        Index("ix_customers_credit_limit", "credit_limit"),
        Index("ix_customers_sales_balance", "sales_balance"),
        Index("ix_customers_returns_balance", "returns_balance"),
        Index("ix_customers_invoices_balance", "invoices_balance"),
        Index("ix_customers_services_balance", "services_balance"),
        Index("ix_customers_preorders_balance", "preorders_balance"),
        Index("ix_customers_online_orders_balance", "online_orders_balance"),
        Index("ix_customers_payments_in_balance", "payments_in_balance"),
        Index("ix_customers_payments_out_balance", "payments_out_balance"),
        Index("ix_customers_checks_in_balance", "checks_in_balance"),
        Index("ix_customers_checks_out_balance", "checks_out_balance"),
        Index("ix_customers_returned_checks_in_balance", "returned_checks_in_balance"),
        Index("ix_customers_returned_checks_out_balance", "returned_checks_out_balance"),
        Index("ix_customers_expenses_balance", "expenses_balance"),
        Index("ix_customers_service_expenses_balance", "service_expenses_balance"),
    )

    @property
    def password(self):
        raise AttributeError("Password access not allowed")

    @password.setter
    def password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password or "")

    def set_password(self, password):
        self.password = password

    def check_password(self, password):
        try:
            return bool(self.password_hash) and check_password_hash(self.password_hash, password or "")
        except Exception:
            return False

    def has_permission(self, *_args, **_kwargs) -> bool:
        return False

    def is_valid_email(self):
        return bool(self.email and "@" in self.email)

    @validates("email")
    def _v_email(self, _, v):
        result = (v or "").strip().lower()
        return result or None  # ✅ تحويل الفارغ إلى None

    @validates("name", "address", "notes")
    def _v_strip(self, _, v):
        s = (v or "").strip()
        return s or None

    @validates("phone", "whatsapp")
    def _v_phone_like(self, key, v):
        s = (v or "").strip()
        s = re.sub(r"\s+", "", s)
        s = "+" + re.sub(r"\D", "", s[1:]) if s.startswith("+") else re.sub(r"\D", "", s)
        digits = re.sub(r"\D", "", s)
        if len(digits) < 7 or len(digits) > 15:
            field_name = "رقم الجوال" if key == "mobile" else "رقم الهاتف"
            raise ValueError(f"{field_name} يجب أن يكون بين 7 و 15 رقماً")
        return s

    @validates("category")
    def _v_category(self, _, v):
        allowed = {"عادي", "ذهبي", "بلاتيني"}
        val = (v or "عادي").strip()
        return val if val in allowed else "عادي"

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("discount_rate")
    def _v_discount_rate(self, _, v):
        if v is None:
            return 0
        f = float(v)
        if f < 0 or f > 100:
            raise ValueError("نسبة الخصم يجب أن تكون بين 0 و 100")
        return v

    @validates("credit_limit")
    def _v_credit_limit(self, _, v):
        if v is None:
            return 0
        if float(v) < 0:
            raise ValueError("حد الائتمان لا يمكن أن يكون سالباً")
        return v

    @hybrid_property
    def total_invoiced(self):
        from decimal import Decimal, ROUND_HALF_UP
        invoices = db.session.query(Invoice).filter(
            Invoice.customer_id == self.id,
            Invoice.cancelled_at.is_(None)
        ).all()
        total = Decimal('0.00')
        for inv in invoices:
            amt = Decimal(str(inv.total_amount or 0))
            if inv.currency == "ILS":
                total += amt
            else:
                try:
                    total += convert_amount(amt, inv.currency, "ILS", inv.invoice_date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        return float(total)

    @total_invoiced.expression
    def total_invoiced(cls):
        return (
            select(func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(
                (Invoice.customer_id == cls.id)
                & (Invoice.cancelled_at.is_(None))
            )
            .scalar_subquery()
        )

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        payments = db.session.query(Payment).filter(
            Payment.customer_id == self.id,
            Payment.direction == PaymentDirection.IN.value,
            Payment.status == PaymentStatus.COMPLETED.value
        ).all()
        total = Decimal('0.00')
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == DEFAULT_CURRENCY:
                total += amt
            else:
                try:
                    total += convert_amount(amt, p.currency, DEFAULT_CURRENCY, p.payment_date)
                except Exception:
                    pass
        
        active_preorders = db.session.query(PreOrder).filter(
            PreOrder.customer_id == self.id,
            PreOrder.prepaid_amount > 0,
            PreOrder.status != 'FULFILLED',
            PreOrder.status != 'CANCELLED'
        ).all()
        
        for po in active_preorders:
            has_payment_for_sale = db.session.query(Payment).filter(
                Payment.preorder_id == po.id,
                Payment.sale_id.isnot(None)
            ).first() is not None
            
            if not has_payment_for_sale:
                prepaid_amt = Decimal(str(po.prepaid_amount or 0))
                if po.currency == "ILS":
                    total += prepaid_amt
                else:
                    try:
                        total += convert_amount(prepaid_amt, po.currency, "ILS", po.preorder_date or po.created_at)
                    except Exception:
                        pass
        
        return float(total)

    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.customer_id == cls.id)
                & (Payment.direction == PaymentDirection.IN.value)
                & (Payment.status == PaymentStatus.COMPLETED.value)
            )
            .scalar_subquery()
        )

    @hybrid_property
    def balance(self):
        try:
            return float(self.current_balance or 0)
        except Exception:
            return 0.0
    
    @balance.expression
    def balance(cls):
        return func.coalesce(cls.current_balance, 0)

    @hybrid_property
    def balance_in_ils(self):
        """الرصيد بالشيكل - استخدام المعادلة الموحدة"""
        try:
            return Decimal(str(self.balance or 0))
        except Exception:
            return Decimal("0.00")

    @hybrid_property
    def credit_status(self):
        try:
            if float(self.credit_limit or 0) > 0 and float(self.balance or 0) >= float(self.credit_limit or 0):
                return "معلق"
        except Exception:
            pass
        return "نشط"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone or "",
            "whatsapp": self.whatsapp or "",
            "email": self.email or "",
            "address": self.address or "",
            "category": self.category,
            "currency": self.currency,
            "is_active": bool(self.is_active),
            "is_online": bool(self.is_online),
            "is_archived": bool(self.is_archived),
            "discount_rate": float(self.discount_rate or 0),
            "credit_limit": float(self.credit_limit or 0),
            "total_invoiced": self.total_invoiced,
            "total_paid": self.total_paid,
            "balance": self.balance,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_id(self) -> str:
        return f"c:{self.id}"

    def __repr__(self):
        return f"<Customer {self.name}>"


@event.listens_for(Customer, "before_insert")
@event.listens_for(Customer, "before_update")
def _customer_normalize(_m, _c, t: Customer):
    t.email = (t.email or "").strip().lower() or None
    for key in ("phone", "whatsapp"):
        val = getattr(t, key, None)
        if val is not None:
            s = str(val).strip()
            s = re.sub(r"\s+", "", s)
            s = "+" + re.sub(r"\D", "", s[1:]) if s.startswith("+") else re.sub(r"\D", "", s)
            setattr(t, key, s)
    t.category = (t.category or "عادي").strip() or "عادي"
    t.currency = (t.currency or DEFAULT_CURRENCY).upper()


def _opening_balance_expected_net(opening_balance: float) -> float:
    if opening_balance > 0:
        return -abs(opening_balance)
    return abs(opening_balance)


def _opening_balance_posted_batch(connection, *, source_type: str, source_id: int, account_code: str):
    dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
    batch_table = "public.gl_batches" if dialect_name == "postgresql" else "gl_batches"
    entry_table = "public.gl_entries" if dialect_name == "postgresql" else "gl_entries"
    return connection.execute(
        sa_text(
            f"""
            SELECT b.id AS id, COALESCE(SUM(e.debit - e.credit), 0) AS net
            FROM {batch_table} b
            JOIN {entry_table} e ON e.batch_id = b.id
            WHERE b.source_type = :st AND b.source_id = :sid AND b.purpose = 'OPENING_BALANCE'
              AND b.status = 'POSTED' AND e.account = :acc
            GROUP BY b.id
            ORDER BY b.id DESC
            LIMIT 1
            """
        ),
        {"st": source_type, "sid": int(source_id), "acc": str(account_code or "").strip().upper()},
    ).mappings().first()


def _delete_opening_balance_batches(connection, *, source_type: str, source_id: int):
    dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
    batch_table = "public.gl_batches" if dialect_name == "postgresql" else "gl_batches"
    entry_table = "public.gl_entries" if dialect_name == "postgresql" else "gl_entries"
    connection.execute(
        sa_text(
            f"""
            DELETE FROM {entry_table}
            WHERE batch_id IN (
                SELECT id FROM {batch_table}
                WHERE source_type = :st AND source_id = :sid AND purpose = 'OPENING_BALANCE'
            )
            """
        ),
        {"st": source_type, "sid": int(source_id)},
    )
    connection.execute(
        sa_text(
            f"""
            DELETE FROM {batch_table}
            WHERE source_type = :st AND source_id = :sid AND purpose = 'OPENING_BALANCE'
            """
        ),
        {"st": source_type, "sid": int(source_id)},
    )


@event.listens_for(Customer, "after_insert")
@event.listens_for(Customer, "after_update")
def _customer_opening_balance_gl(mapper, connection, target: "Customer"):
    try:
        opening_balance = float(getattr(target, 'opening_balance', 0) or 0)
        if opening_balance == 0:
            _delete_opening_balance_batches(connection, source_type="CUSTOMER", source_id=target.id)
            return
        expected_net = _opening_balance_expected_net(opening_balance)
        account_code = GL_ACCOUNTS.get("AR", "1100_AR")
        existing = _opening_balance_posted_batch(
            connection,
            source_type="CUSTOMER",
            source_id=target.id,
            account_code=account_code,
        )
        if existing and abs(float(existing["net"] or 0) - float(expected_net)) <= 0.01:
            return
        if existing:
            _delete_opening_balance_batches(connection, source_type="CUSTOMER", source_id=target.id)
        
        if opening_balance > 0:
            entries = [
                ("3000_EQUITY", abs(opening_balance), 0),
                (account_code, 0, abs(opening_balance)),
            ]
        else:
            entries = [
                (account_code, abs(opening_balance), 0),
                ("3000_EQUITY", 0, abs(opening_balance)),
            ]
        
        memo = f"رصيد افتتاحي - {target.name}"
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="CUSTOMER",
            source_id=target.id,
            purpose="OPENING_BALANCE",
            currency=DEFAULT_CURRENCY,
            memo=memo,
            entries=entries,
            ref=f"OB-CUST-{target.id}",
            entity_type="CUSTOMER",
            entity_id=target.id
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في إنشاء GLBatch للرصيد الافتتاحي للعميل #{target.id}: {e}")


@event.listens_for(Customer, "after_insert")
@event.listens_for(Customer, "after_update")
def _customer_enqueue_balance_update(mapper, connection, target: "Customer"):
    try:
        _queue_customer_balance(target, getattr(target, "id", None))
    except Exception:
        pass


def _ensure_customer_for_counterparty(connection, *, name, phone, whatsapp=None, email=None, address=None, currency=DEFAULT_CURRENCY, source_label=None, source_id=None):
    from datetime import datetime
    from sqlalchemy import insert as sa_insert, select as sa_select, func as sa_func
    from sqlalchemy.exc import IntegrityError
    trimmed_name = (name or "").strip()
    name_filter = trimmed_name.lower() if trimmed_name else None
    mail = normalize_email(email)
    trimmed_address = (address or "").strip() or None
    raw_phone = normalize_phone(phone)
    wa = normalize_phone(whatsapp) if whatsapp else None

    def _fallback_phone():
        token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        digits = re.sub(r"\D+", "", token)
        if len(digits) < 7:
            digits = digits.rjust(7, "0")
        return digits[:15]

    if not raw_phone:
        raw_phone = _fallback_phone()

    if not wa:
        wa = raw_phone

    if name_filter:
        existing = connection.execute(
            sa_select(Customer.id).where(sa_func.lower(Customer.name) == name_filter)
        ).first()
        if existing:
            return existing[0]

    attempt_phone = raw_phone
    note_text = None
    if source_label and source_id:
        note_text = f"AUTO-{source_label}-{source_id}"

    for _ in range(3):
        stmt = sa_insert(Customer).values(
            name=trimmed_name or attempt_phone,
            phone=attempt_phone,
            whatsapp=wa or attempt_phone,
            email=mail or None,
            address=trimmed_address,
            category="عادي",
            currency=(currency or DEFAULT_CURRENCY).upper(),
            is_active=True,
            notes=note_text,
        )
        try:
            result = connection.execute(stmt)
            inserted = result.inserted_primary_key
            return inserted[0] if inserted else None
        except IntegrityError:
            attempt_phone = _fallback_phone()
            wa = attempt_phone
        except Exception:
            break

    fallback_existing = connection.execute(
        sa_select(Customer.id).where(Customer.name == (trimmed_name or attempt_phone))
    ).first()
    return fallback_existing[0] if fallback_existing else None


class Supplier(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_local = db.Column(db.Boolean, default=True, nullable=False, server_default=sa_text("true"))
    identity_number = db.Column(db.String(100), unique=True)
    contact = db.Column(db.String(200))
    phone = db.Column(db.String(20), index=True)
    email = db.Column(db.String(120), unique=True, index=True, nullable=True)
    address = db.Column(db.String(200))
    notes = db.Column(db.Text)
    payment_terms = db.Column(db.String(50))
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False, server_default=sa_text(f"'{DEFAULT_CURRENCY}'"))
    opening_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="الرصيد الافتتاحي (موجب=له رصيد عندنا، سالب=لنا رصيد عنده)")
    
    current_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), index=True, comment="الرصيد الحالي المحدث")
    exchange_items_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد قطع التبادل")
    sale_returns_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد مرتجعات المبيعات")
    sales_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المبيعات")
    services_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الخدمات")
    preorders_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الحجوزات المسبقة")
    payments_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الواردة")
    payments_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الصادرة")
    preorders_prepaid_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد أرصدة الحجوزات")
    returns_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المرتجعات Exchange")
    expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المصروفات العادية (تُطرح)")
    service_expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد مصروفات توريد الخدمة (تُضاف)")
    returned_checks_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الواردة")
    returned_checks_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الصادرة")
    
    # ربط تلقائي مع جدول العملاء
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True, nullable=True)
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))

    # العلاقات
    customer = db.relationship("Customer", foreign_keys=[customer_id], backref="supplier_link")
    payments = db.relationship("Payment", back_populates="supplier")
    invoices = db.relationship("Invoice", back_populates="supplier")
    preorders = db.relationship("PreOrder", back_populates="supplier")
    expenses = db.relationship("Expense", back_populates="supplier")
    warehouses = db.relationship("Warehouse", back_populates="supplier")
    loan_settlements = db.relationship("SupplierLoanSettlement", back_populates="supplier", cascade="all, delete-orphan")
    archived_by_user = db.relationship("User", foreign_keys=[archived_by])

    __table_args__ = (
        db.Index("ix_supp_name_active", "name", "is_archived"),
        db.Index("ix_supp_contact", "contact"),
        db.Index("ix_supp_opening_balance", "opening_balance"),
    )

    @validates("email")
    def _v_email(self, _, v):
        return (v or "").strip().lower() or None

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("name", "contact", "address", "notes", "payment_terms", "phone", "identity_number")
    def _v_strip(self, _, v):
        s = (v or "").strip()
        return s or None

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        from sqlalchemy import or_, and_
        direct_payments = db.session.query(Payment).filter(
            Payment.supplier_id == self.id,
            Payment.direction == PaymentDirection.OUT.value,
            Payment.status == PaymentStatus.COMPLETED.value
        ).all()
        direct = Decimal('0.00')
        for p in direct_payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == DEFAULT_CURRENCY:
                direct += amt
            else:
                try:
                    direct += convert_amount(amt, p.currency, DEFAULT_CURRENCY, p.payment_date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        
        via_loans_payments = db.session.query(Payment).join(
            SupplierLoanSettlement, SupplierLoanSettlement.id == Payment.loan_settlement_id
        ).filter(
            Payment.direction == PaymentDirection.OUT.value,
            Payment.status == PaymentStatus.COMPLETED.value,
            SupplierLoanSettlement.supplier_id == self.id
        ).all()
        via_loans = Decimal('0.00')
        for p in via_loans_payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == DEFAULT_CURRENCY:
                via_loans += amt
            else:
                try:
                    via_loans += convert_amount(amt, p.currency, DEFAULT_CURRENCY, p.payment_date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        
        expenses = db.session.query(Expense).filter(
            or_(
                Expense.supplier_id == self.id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == self.id)
            )
        ).all()
        expenses_total = Decimal('0.00')
        for exp in expenses:
            amt = Decimal(str(exp.amount or 0))
            if exp.currency == DEFAULT_CURRENCY:
                expenses_total += amt
            else:
                try:
                    expenses_total += convert_amount(amt, exp.currency, DEFAULT_CURRENCY, exp.date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        
        return float(direct + via_loans + expenses_total)

    @total_paid.expression
    def total_paid(cls):
        direct_subq = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.supplier_id == cls.id)
                & (Payment.direction == PaymentDirection.OUT.value)
                & (Payment.status == PaymentStatus.COMPLETED.value)
            )
            .scalar_subquery()
        )
        via_loans_subq = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .select_from(Payment.__table__.join(SupplierLoanSettlement, SupplierLoanSettlement.id == Payment.loan_settlement_id))
            .where(
                (Payment.direction == PaymentDirection.OUT.value)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (SupplierLoanSettlement.supplier_id == cls.id)
            )
            .scalar_subquery()
        )
        return direct_subq + via_loans_subq

    @hybrid_property
    def balance(self):
        try:
            return float(self.current_balance or 0)
        except Exception:
            return 0.0
    
    @balance.expression
    def balance(cls):
        return func.coalesce(cls.current_balance, 0)

    @hybrid_property
    def balance_in_ils(self):
        return self.balance

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "currency": self.currency,
            "balance": float(q(self.balance or 0)),
            "total_paid": float(q(self.total_paid or 0)),
        }

    def __repr__(self):
        return f"<Supplier {self.name}>"
    
    def ensure_customer_link(self):
        """ربط عميل تلقائياً - يبحث بالهاتف فقط (الأدق)"""
        if not self.customer_id and self.id and self.phone:
            existing = Customer.query.filter(Customer.phone == self.phone).first()
            if existing:
                self.customer_id = existing.id


@event.listens_for(Supplier, "after_insert")  
def supplier_after_insert_create_customer(mapper, connection, target):
    """ربط أو إنشاء عميل تلقائياً للمورد الجديد"""
    if target.customer_id:
        return
    from sqlalchemy import update as sa_update
    customer_id = _ensure_customer_for_counterparty(
        connection,
        name=target.name,
        phone=target.phone,
        whatsapp=target.phone,
        email=target.email,
        address=target.address,
        currency=target.currency,
        source_label="SUPPLIER",
        source_id=target.id,
    )
    if customer_id:
        connection.execute(
            sa_update(Supplier).where(Supplier.id == target.id).values(customer_id=customer_id)
        )
        target.customer_id = customer_id


@event.listens_for(Supplier, "before_insert")
@event.listens_for(Supplier, "before_update")
def _supplier_normalize(_m, _c, t: Supplier):
    t.email = (t.email or "").strip().lower() or None
    t.currency = (t.currency or DEFAULT_CURRENCY).upper()


@event.listens_for(Supplier, "after_insert")
@event.listens_for(Supplier, "after_update")
def _supplier_opening_balance_gl(mapper, connection, target: "Supplier"):
    try:
        opening_balance = float(getattr(target, 'opening_balance', 0) or 0)
        if opening_balance == 0:
            _delete_opening_balance_batches(connection, source_type="SUPPLIER", source_id=target.id)
            return
        expected_net = _opening_balance_expected_net(opening_balance)
        account_code = GL_ACCOUNTS.get("AP", "2000_AP")
        existing = _opening_balance_posted_batch(
            connection,
            source_type="SUPPLIER",
            source_id=target.id,
            account_code=account_code,
        )
        if existing and abs(float(existing["net"] or 0) - float(expected_net)) <= 0.01:
            return
        if existing:
            _delete_opening_balance_batches(connection, source_type="SUPPLIER", source_id=target.id)
        
        if opening_balance > 0:
            entries = [
                ("3000_EQUITY", abs(opening_balance), 0),
                (account_code, 0, abs(opening_balance)),
            ]
        else:
            entries = [
                (account_code, abs(opening_balance), 0),
                ("3000_EQUITY", 0, abs(opening_balance)),
            ]
        
        memo = f"رصيد افتتاحي - {target.name}"
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="SUPPLIER",
            source_id=target.id,
            purpose="OPENING_BALANCE",
            currency=DEFAULT_CURRENCY,
            memo=memo,
            entries=entries,
            ref=f"OB-SUP-{target.id}",
            entity_type="SUPPLIER",
            entity_id=target.id
        )
    except Exception as e:
        from flask import current_app
        import traceback
        error_msg = f"⚠️ خطأ في إنشاء GLBatch للرصيد الافتتاحي للمورد #{target.id}: {e}"
        current_app.logger.error(error_msg)
        current_app.logger.debug(traceback.format_exc())


class SupplierSettlement(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "supplier_settlements"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    from_date = db.Column(db.DateTime, nullable=False, index=True)
    to_date = db.Column(db.DateTime, nullable=False, index=True)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    status = db.Column(
        sa_str_enum(SupplierSettlementStatus, name="supplier_settlement_status"),
        default=SupplierSettlementStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    mode = db.Column(
        sa_str_enum(SupplierSettlementMode, name="supplier_settlement_mode"),
        default=SupplierSettlementMode.ON_RECEIPT.value,
        nullable=False,
        index=True,
    )
    notes = db.Column(db.Text)
    total_gross = db.Column(db.Numeric(12, 2), default=0)
    total_due = db.Column(db.Numeric(12, 2), default=0)

    previous_settlement_id = db.Column(db.Integer, db.ForeignKey("supplier_settlements.id"), nullable=True, index=True)
    
    opening_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    rights_exchange = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    rights_total = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    obligations_sales = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_services = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_preorders = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_expenses = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_total = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    payments_out = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    payments_in = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    payments_returns = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    payments_net = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    closing_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True, server_default=sa_text("false"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    supplier = db.relationship("Supplier", backref="settlements")
    lines = db.relationship("SupplierSettlementLine", back_populates="settlement", cascade="all, delete-orphan")
    previous_settlement = db.relationship("SupplierSettlement", remote_side=[id], foreign_keys=[previous_settlement_id], backref="next_settlements")
    approved_by_user = db.relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        db.Index("ix_supplier_settle_closing_balance", "closing_balance"),
        db.Index("ix_supplier_settle_total_due", "total_due"),
        db.Index("ix_supplier_settle_opening_balance", "opening_balance"),
    )

    @validates("status", "mode")
    def _v_str_enums(self, _, v):
        return getattr(v, "value", v)

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @hybrid_property
    def total_paid(self):
        ref = f"SupplierSettle:{self.code or ''}"
        if not self.code:
            return 0.0
        val = (
            db.session.query(func.coalesce(func.sum(Payment.total_amount), 0))
            .filter(
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.direction == PaymentDirection.OUT.value,
                Payment.entity_type == PaymentEntityType.SUPPLIER.value,
                Payment.supplier_id == self.supplier_id,
                Payment.reference == ref,
            )
            .scalar()
            or 0
        )
        return float(q(val))

    @hybrid_property
    def remaining(self):
        return float(q(self.total_due or 0) - q(self.total_paid or 0))

    def ensure_code(self, connection=None):
        if self.code:
            return
        prefix = datetime.now(timezone.utc).strftime("SS-%Y%m")
        if connection is not None:
            try:
                cnt = connection.execute(
                    sa_text("SELECT COUNT(1) FROM supplier_settlements WHERE code LIKE :like"),
                    {"like": f"{prefix}-%"},
                ).scalar() or 0
            except Exception:
                cnt = 0
        else:
            cnt = db.session.query(func.count(SupplierSettlement.id)).filter(SupplierSettlement.code.like(f"{prefix}-%")).scalar() or 0
        self.code = f"{prefix}-{cnt + 1:04d}"

    def mark_confirmed(self):
        self.status = SupplierSettlementStatus.CONFIRMED.value


class SupplierSettlementLine(db.Model, TimestampMixin):
    __tablename__ = "supplier_settlement_lines"

    id = db.Column(db.Integer, primary_key=True)
    settlement_id = db.Column(db.Integer, db.ForeignKey("supplier_settlements.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = db.Column(db.String(30), nullable=False)
    source_id = db.Column(db.Integer, index=True)
    description = db.Column(db.String(255))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    quantity = db.Column(db.Numeric(12, 3))
    unit_price = db.Column(db.Numeric(12, 2))
    gross_amount = db.Column(db.Numeric(12, 2))
    needs_pricing = db.Column(db.Boolean, default=False, nullable=False, index=True)
    cost_source = db.Column(db.String(20))

    settlement = db.relationship("SupplierSettlement", back_populates="lines")
    product = db.relationship("Product")

    __table_args__ = (
        db.Index("ix_supplier_settle_line_product", "product_id"),
    )


def _ex_dir_sign(direction: str) -> int:
    d = (getattr(direction, "value", direction) or "").upper()
    if d == "IN":
        return 1
    if d == "OUT":
        return -1
    if d == "ADJUSTMENT":
        return 1
    raise ValueError(f"Unknown exchange direction: {direction}")


class SupplierLoanSettlement(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "supplier_loan_settlements"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("product_supplier_loans.id", ondelete="CASCADE"), nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    settled_price = db.Column(db.Numeric(12, 2), nullable=False)
    settlement_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text)

    loan = db.relationship("ProductSupplierLoan", back_populates="settlements")
    supplier = db.relationship("Supplier", back_populates="loan_settlements")
    payment = db.relationship("Payment", back_populates="loan_settlement", cascade="all, delete-orphan", passive_deletes=True, uselist=False)

    __table_args__ = (db.CheckConstraint("settled_price >= 0", name="chk_settlement_price_non_negative"),)

    @hybrid_property
    def has_payment(self) -> bool:
        return self.payment is not None

    @property
    def product(self):
        return getattr(self.loan, "product", None)

    def build_payment(
        self,
        method: "PaymentMethod" = None,
        status: "PaymentStatus" = None,
        direction: "PaymentDirection" = None,
        currency: str = None,
        reference: str = None,
        notes: str = None,
        created_by: int = None,
    ) -> "Payment":
        return Payment(
            total_amount=self.settled_price,
            payment_date=datetime.now(timezone.utc),
            method=method or PaymentMethod.BANK,
            status=status or PaymentStatus.PENDING,
            direction=direction or PaymentDirection.OUT,
            entity_type=PaymentEntityType.LOAN,
            currency=currency or (getattr(self.supplier, "currency", None) or "ILS"),
            supplier_id=getattr(self.supplier, "id", None),
            loan_settlement_id=self.id,
            reference=reference or f"Loan #{self.loan_id} settlement",
            notes=notes,
            created_by=created_by,
        )

    def __repr__(self):
        return f"<SupplierLoanSettlement Loan{self.loan_id} - {self.settled_price}>"


@event.listens_for(SupplierLoanSettlement, "after_insert")
def _sync_loan_on_settlement(_m, connection, target: "SupplierLoanSettlement"):
    if target.loan_id:
        connection.execute(
            update(ProductSupplierLoan)
            .where(ProductSupplierLoan.id == target.loan_id)
            .values(deferred_price=target.settled_price, is_settled=True)
        )


def _recompute_supplier_settlement_totals(connection, settlement_id: int):
    mode = connection.execute(
        select(SupplierSettlement.mode).where(SupplierSettlement.id == settlement_id)
    ).scalar_one_or_none()
    mode = (mode or SupplierSettlementMode.ON_RECEIPT.value).upper()

    if mode == SupplierSettlementMode.ON_RECEIPT.value:
        gross_sum = connection.execute(
            select(func.coalesce(func.sum(SupplierSettlementLine.gross_amount), 0)).where(
                SupplierSettlementLine.settlement_id == settlement_id,
                SupplierSettlementLine.source_type != "EXCHANGE_RETURN",
            )
        ).scalar_one() or 0
        returns_sum = connection.execute(
            select(func.coalesce(func.sum(SupplierSettlementLine.gross_amount), 0)).where(
                SupplierSettlementLine.settlement_id == settlement_id,
                SupplierSettlementLine.source_type == "EXCHANGE_RETURN",
            )
        ).scalar_one() or 0
        due_sum = Decimal(str(gross_sum or 0)) - Decimal(str(returns_sum or 0))
    else:
        gross_sum = connection.execute(
            select(func.coalesce(func.sum(SupplierSettlementLine.gross_amount), 0)).where(SupplierSettlementLine.settlement_id == settlement_id)
        ).scalar_one() or 0
        due_sum = Decimal(str(gross_sum or 0))

    connection.execute(
        update(SupplierSettlement)
        .where(SupplierSettlement.id == settlement_id)
        .values(total_gross=gross_sum, total_due=q(due_sum))
    )


@event.listens_for(SupplierSettlement, "before_insert")
def _ss_before_insert(_m, _c, t: SupplierSettlement):
    t.currency = (t.currency or "ILS").upper()
    t.status = getattr(t.status, "value", t.status)
    t.mode = getattr(t.mode, "value", t.mode)
    if not t.code:
        t.ensure_code(connection=_c)

@event.listens_for(SupplierSettlement, "before_update")
def _ss_before_update(_m, connection, t: SupplierSettlement):
    t.currency = (t.currency or "ILS").upper()
    t.status = getattr(t.status, "value", t.status)
    t.mode = getattr(t.mode, "value", t.mode)
    if t.status == SupplierSettlementStatus.CONFIRMED.value:
        cnt_unpriced = (
            connection.execute(
                select(func.count(SupplierSettlementLine.id)).where(
                    SupplierSettlementLine.settlement_id == t.id, SupplierSettlementLine.needs_pricing.is_(True)
                )
            ).scalar_one()
            or 0
        )
        if int(cnt_unpriced) > 0:
            raise ValueError("لا يمكن تأكيد التسوية وفيها بنود بحاجة تسعير")
        dup_cnt = (
            connection.execute(
                select(func.count(SupplierSettlementLine.id))
                .select_from(
                    SupplierSettlementLine.__table__.join(SupplierSettlement.__table__, SupplierSettlementLine.settlement_id == SupplierSettlement.id)
                )
                .where(
                    SupplierSettlement.id != t.id,
                    SupplierSettlement.supplier_id == t.supplier_id,
                    SupplierSettlement.status == SupplierSettlementStatus.CONFIRMED.value,
                    SupplierSettlementLine.source_type.in_(select(SupplierSettlementLine.source_type).where(SupplierSettlementLine.settlement_id == t.id)),
                    SupplierSettlementLine.source_id.in_(select(SupplierSettlementLine.source_id).where(SupplierSettlementLine.settlement_id == t.id)),
                )
            ).scalar_one()
            or 0
        )
        if int(dup_cnt) > 0:
            raise ValueError("يوجد مصادر مستخدمة سابقًا في تسويات مؤكّدة لنفس المورد")

@event.listens_for(SupplierSettlement, "after_update")
def _ss_after_update(_m, connection, t: SupplierSettlement):
    from sqlalchemy import inspect
    try:
        hist = inspect(t)
        if hist.attrs.get('status'):
            status_hist = hist.attrs['status'].history
            old_status = status_hist.deleted[0] if status_hist.deleted else None
            new_status = status_hist.added[0] if status_hist.added else getattr(t, 'status', None)
            if old_status != new_status and new_status == SupplierSettlementStatus.CONFIRMED.value:
                if t.supplier_id:
                    _queue_supplier_balance(t, t.supplier_id)
    except Exception:
        pass

@event.listens_for(SupplierSettlement, "before_delete")
def _ss_before_delete(_m, _c, t: SupplierSettlement):
    if t.status == SupplierSettlementStatus.CONFIRMED.value:
        raise ValueError("لا يمكن حذف تسوية مؤكّدة")

@event.listens_for(SupplierSettlementLine, "before_insert")
@event.listens_for(SupplierSettlementLine, "before_update")
def _ssl_before_save(_m, connection, t: SupplierSettlementLine):
    if t.quantity is not None and float(t.quantity) < 0:
        raise ValueError("الكمية يجب أن تكون ≥ 0")
    if t.unit_price is not None and float(t.unit_price) < 0:
        raise ValueError("سعر الوحدة يجب أن يكون ≥ 0")
    if t.gross_amount is None:
        qv = Decimal(str(t.quantity or 0))
        uv = Decimal(str(t.unit_price or 0))
        t.gross_amount = q(qv * uv)
    if float(t.gross_amount or 0) < 0:
        raise ValueError("القيمة الإجمالية يجب أن تكون ≥ 0")

@event.listens_for(SupplierSettlementLine, "after_insert")
@event.listens_for(SupplierSettlementLine, "after_update")
@event.listens_for(SupplierSettlementLine, "after_delete")
def _ssl_touch_settlement(_m, connection, t: SupplierSettlementLine):
    if t.settlement_id:
        _recompute_supplier_settlement_totals(connection, int(t.settlement_id))

@event.listens_for(SupplierSettlementLine, "before_delete")
def _ssl_before_delete(_m, _c, t: SupplierSettlementLine):
    s = t.settlement
    if s and s.status == SupplierSettlementStatus.CONFIRMED.value:
        raise ValueError("لا يمكن حذف بنود من تسوية مؤكّدة")


def _ok(data=None, http=200, **extra):
    payload = {"success": True}
    if data is not None:
        payload.update(data if isinstance(data, dict) else {"data": data})
    payload.update(extra)
    return jsonify(payload), http

def _created(location: str = None, data=None):
    headers = {}
    payload = {"success": True}
    if location:
        headers["Location"] = location
        payload["location"] = location
    if data is not None:
        payload.update(data if isinstance(data, dict) else {"data": data})
    return jsonify(payload), 201, headers

def _err(code: str, message: str = "", http: int = 400, details=None):
    body = {"success": False, "code": code}
    if message:
        body["message"] = message
    if details:
        body["details"] = details
    return jsonify(body), http


class Partner(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "partners"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    contact_info = db.Column(db.String(200))
    identity_number = db.Column(db.String(100), unique=True)
    phone_number = db.Column(db.String(20), unique=True)
    email = db.Column(db.String(120), unique=True, index=True, nullable=True)
    address = db.Column(db.String(200))
    share_percentage = db.Column(db.Numeric(5, 2), default=0, nullable=False, server_default=sa_text("0"))
    currency = db.Column(db.String(10), default="ILS", nullable=False, server_default=sa_text("'ILS'"))
    opening_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="الرصيد الافتتاحي (موجب=له رصيد عندنا، سالب=لنا رصيد عنده)")
    
    current_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), index=True, comment="الرصيد الحالي المحدث")
    inventory_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المخزون")
    sales_share_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد نصيب المبيعات")
    sales_to_partner_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المبيعات له")
    service_fees_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد رسوم الصيانة")
    preorders_to_partner_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الحجوزات له")
    preorders_prepaid_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد العربونات المدفوعة")
    damaged_items_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد القطع التالفة")
    payments_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الواردة")
    payments_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الدفعات الصادرة")
    returned_checks_in_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الواردة")
    returned_checks_out_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد الشيكات المرتدة الصادرة")
    expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد المصروفات العادية (تُطرح)")
    service_expenses_balance = Column(Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"), comment="رصيد توريد الخدمة (تُضاف)")
    
    notes = db.Column(db.Text)
    
    # ربط تلقائي مع جدول العملاء
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True, nullable=True)
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))

    # العلاقات
    customer = db.relationship("Customer", foreign_keys=[customer_id], backref="partner_link")
    warehouses = db.relationship("Warehouse", back_populates="partner")
    payments = db.relationship("Payment", back_populates="partner")
    preorders = db.relationship("PreOrder", back_populates="partner")
    invoices = db.relationship("Invoice", back_populates="partner")
    shipment_partners = db.relationship("ShipmentPartner", back_populates="partner")
    archived_by_user = db.relationship("User", foreign_keys=[archived_by])

    warehouse_shares = db.relationship("WarehousePartnerShare", back_populates="partner", cascade="all, delete-orphan", overlaps="shares,product_shares")
    shares = db.relationship("WarehousePartnerShare", back_populates="partner", cascade="all, delete-orphan", overlaps="warehouse_shares,product_shares")
    product_shares = db.relationship("ProductPartnerShare", back_populates="partner", cascade="all, delete-orphan", overlaps="shares,warehouse_shares")
    product_links = db.relationship("ProductPartner", back_populates="partner", cascade="all, delete-orphan")
    service_parts = db.relationship("ServicePart", back_populates="partner")
    service_tasks = db.relationship("ServiceTask", back_populates="partner")
    expenses = db.relationship("Expense", back_populates="partner")

    __table_args__ = (
        db.Index("ix_partners_opening_balance", "opening_balance"),
    )

    @validates("email")
    def _v_email(self, _, v):
        return (v or "").strip().lower() or None

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("share_percentage")
    def _v_share(self, _, v):
        if v is None:
            return 0
        fv = float(v)
        if fv < 0 or fv > 100:
            raise ValueError("share_percentage must be between 0 and 100")
        return v

    @validates("name", "contact_info", "address", "identity_number", "phone_number", "notes")
    def _v_strip(self, _, v):
        s = (v or "").strip()
        return s or None

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        from sqlalchemy import or_, and_
        payments = db.session.query(Payment).filter(
            Payment.partner_id == self.id,
            Payment.direction == PaymentDirection.OUT.value,
            Payment.status == PaymentStatus.COMPLETED.value
        ).all()
        total = Decimal('0.00')
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == DEFAULT_CURRENCY:
                total += amt
            else:
                try:
                    total += convert_amount(amt, p.currency, DEFAULT_CURRENCY, p.payment_date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        
        from models import ExpenseType
        from sqlalchemy import func
        expenses = db.session.query(Expense).join(ExpenseType).filter(
            or_(
                Expense.partner_id == self.id,
                and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == self.id)
            ),
            func.upper(ExpenseType.code) != "PARTNER_EXPENSE"
        ).all()
        for exp in expenses:
            amt = Decimal(str(exp.amount or 0))
            if exp.currency == DEFAULT_CURRENCY:
                total += amt
            else:
                try:
                    total += convert_amount(amt, exp.currency, DEFAULT_CURRENCY, exp.date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        
        return float(total)

    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.partner_id == cls.id)
                & (Payment.direction == PaymentDirection.OUT.value)
                & (Payment.status == PaymentStatus.COMPLETED.value)
            )
            .scalar_subquery()
        )

    @hybrid_property
    def balance(self):
        return float(self.current_balance or 0)

    @balance.expression
    def balance(cls):
        return cls.current_balance

    @hybrid_property
    def balance_in_ils(self):
        return self.balance

    @hybrid_property
    def net_balance(self):
        return q(self.balance or 0) - q(self.total_paid or 0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "currency": self.currency,
            "balance": float(q(self.balance or 0)),
            "total_paid": float(q(self.total_paid or 0)),
            "net_balance": float(q(self.net_balance or 0)),
        }

    def __repr__(self):
        return f"<Partner {self.name}>"
    
    def ensure_customer_link(self):
        """ربط عميل تلقائياً - يبحث بالهاتف فقط (الأدق)"""
        if not self.customer_id and self.id and self.phone_number:
            existing = Customer.query.filter(Customer.phone == self.phone_number).first()
            if existing:
                self.customer_id = existing.id


@event.listens_for(Partner, "after_insert")
def partner_after_insert_create_customer(mapper, connection, target):
    """ربط أو إنشاء عميل تلقائياً للشريك الجديد"""
    if target.customer_id:
        return
    from sqlalchemy import update as sa_update
    customer_id = _ensure_customer_for_counterparty(
        connection,
        name=target.name,
        phone=target.phone_number,
        whatsapp=target.phone_number,
        email=target.email,
        address=target.address,
        currency=target.currency,
        source_label="PARTNER",
        source_id=target.id,
    )
    if customer_id:
        connection.execute(
            sa_update(Partner).where(Partner.id == target.id).values(customer_id=customer_id)
        )
        target.customer_id = customer_id


# ==========================================
@event.listens_for(Partner, "before_insert")
@event.listens_for(Partner, "before_update")
def _partner_normalize(_m, _c, t: Partner):
    t.email = (t.email or "").strip().lower() or None
    t.currency = (t.currency or DEFAULT_CURRENCY).upper()
    t.name = (t.name or "").strip()


@event.listens_for(Partner, "after_insert")
@event.listens_for(Partner, "after_update")
def _partner_opening_balance_gl(mapper, connection, target: "Partner"):
    try:
        opening_balance = float(getattr(target, 'opening_balance', 0) or 0)
        if opening_balance == 0:
            _delete_opening_balance_batches(connection, source_type="PARTNER", source_id=target.id)
            return
        expected_net = _opening_balance_expected_net(opening_balance)
        account_code = GL_ACCOUNTS.get("AP", "2000_AP")
        existing = _opening_balance_posted_batch(
            connection,
            source_type="PARTNER",
            source_id=target.id,
            account_code=account_code,
        )
        if existing and abs(float(existing["net"] or 0) - float(expected_net)) <= 0.01:
            return
        if existing:
            _delete_opening_balance_batches(connection, source_type="PARTNER", source_id=target.id)
        
        if opening_balance > 0:
            entries = [
                ("3000_EQUITY", abs(opening_balance), 0),
                (account_code, 0, abs(opening_balance)),
            ]
        else:
            entries = [
                (account_code, abs(opening_balance), 0),
                ("3000_EQUITY", 0, abs(opening_balance)),
            ]
        
        memo = f"رصيد افتتاحي - {target.name}"
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="PARTNER",
            source_id=target.id,
            purpose="OPENING_BALANCE",
            currency="ILS",
            memo=memo,
            entries=entries,
            ref=f"OB-PARTNER-{target.id}",
            entity_type="PARTNER",
            entity_id=target.id
        )
    except Exception as e:
        from flask import current_app
        import traceback
        error_msg = f"⚠️ خطأ في إنشاء GLBatch للرصيد الافتتاحي للشريك #{target.id}: {e}"
        current_app.logger.error(error_msg)
        current_app.logger.debug(traceback.format_exc())


def update_supplier_balance(supplier_id: int, connection=None):
    try:
        from utils.supplier_balance_updater import update_supplier_balance_components
        update_supplier_balance_components(supplier_id, connection)
    except Exception:
        pass

def update_partner_balance(partner_id: int, connection=None):
    from utils.partner_balance_updater import update_partner_balance_components
    if connection:
        from sqlalchemy.orm import Session
        if isinstance(connection, Session):
            update_partner_balance_components(partner_id, connection)
        else:
            from extensions import db
            with db.session.begin():
                update_partner_balance_components(partner_id, db.session)
    else:
        update_partner_balance_components(partner_id)


class PartnerSettlement(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "partner_settlements"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id"), nullable=False, index=True)
    from_date = db.Column(db.DateTime, nullable=False, index=True)
    to_date = db.Column(db.DateTime, nullable=False, index=True)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    status = db.Column(sa_str_enum(PartnerSettlementStatus, name="partner_settlement_status"), default=PartnerSettlementStatus.DRAFT.value, nullable=False, index=True)
    notes = db.Column(db.Text)
    total_gross = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_share = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_costs = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_due = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    previous_settlement_id = db.Column(db.Integer, db.ForeignKey("partner_settlements.id"), nullable=True, index=True)
    
    opening_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    rights_inventory = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    rights_sales_share = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    rights_preorders = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    rights_total = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    obligations_sales_to_partner = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_services = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_damaged = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_expenses = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_returns = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    obligations_total = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    payments_out = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    payments_in = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    payments_net = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    closing_balance = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True, server_default=sa_text("false"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    partner = db.relationship("Partner", backref="settlements")
    lines = db.relationship("PartnerSettlementLine", back_populates="settlement", cascade="all, delete-orphan")
    previous_settlement = db.relationship("PartnerSettlement", remote_side=[id], foreign_keys=[previous_settlement_id], backref="next_settlements")
    approved_by_user = db.relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        db.Index("ix_partner_settle_closing_balance", "closing_balance"),
        db.Index("ix_partner_settle_total_due", "total_due"),
        db.Index("ix_partner_settle_opening_balance", "opening_balance"),
    )

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        ref = f"PartnerSettle:{self.code or ''}"
        if not self.code:
            return 0.0
        
        payments = db.session.query(Payment).filter(
            Payment.partner_id == self.partner_id,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.direction == PaymentDirection.OUT.value,
            Payment.entity_type == PaymentEntityType.PARTNER.value,
            Payment.reference == ref
        ).all()
        
        total = Decimal('0.00')
        settlement_currency = self.currency or "ILS"
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == settlement_currency:
                total += amt
            else:
                try:
                    total += convert_amount(amt, p.currency, settlement_currency, p.payment_date)
                except Exception:
                    pass
        return float(total)

    @hybrid_property
    def remaining(self):
        return float(q(self.total_due or 0) - q(self.total_paid or 0))

    def ensure_code(self, connection=None):
        if self.code:
            return
        prefix = datetime.now(timezone.utc).strftime("PS-%Y%m")
        if connection is not None:
            try:
                cnt = connection.execute(
                    sa_text("SELECT COUNT(1) FROM partner_settlements WHERE code LIKE :like"),
                    {"like": f"{prefix}-%"},
                ).scalar() or 0
            except Exception:
                cnt = 0
        else:
            cnt = db.session.query(func.count(PartnerSettlement.id)).filter(PartnerSettlement.code.like(f"{prefix}-%")).scalar() or 0
        self.code = f"{prefix}-{cnt + 1:04d}"

    def mark_confirmed(self):
        self.status = PartnerSettlementStatus.CONFIRMED.value


@event.listens_for(PartnerSettlement, "before_insert")
def _ps_before_insert(_m, _c, t: PartnerSettlement):
    t.currency = (t.currency or "ILS").upper()
    if not t.code:
        t.ensure_code(connection=_c)
    if t.from_date and t.to_date and t.to_date < t.from_date:
        t.from_date, t.to_date = t.to_date, t.from_date

@event.listens_for(PartnerSettlement, "before_update")
def _ps_before_update(_m, _c, t: PartnerSettlement):
    t.currency = (t.currency or "ILS").upper()
    if not t.code:
        t.ensure_code(connection=_c)
    if t.from_date and t.to_date and t.to_date < t.from_date:
        t.from_date, t.to_date = t.to_date, t.from_date

@event.listens_for(PartnerSettlement, "after_update", propagate=True)
def _ps_after_update_approved(mapper, connection, target: PartnerSettlement):
    try:
        if target.is_approved and target.partner_id:
            from sqlalchemy import text as sa_text
            connection.execute(
                sa_text("UPDATE partners SET opening_balance = :ob WHERE id = :pid"),
                {"ob": float(target.closing_balance or 0), "pid": target.partner_id}
            )
            _queue_partner_balance(target, target.partner_id)
    except Exception:
        pass

@event.listens_for(PartnerSettlement, "after_update", propagate=True)
def _ps_after_update(mapper, connection, target: PartnerSettlement):
    from sqlalchemy import inspect
    try:
        hist = inspect(target)
        if hist.attrs.get('status'):
            status_hist = hist.attrs['status'].history
            old_status = status_hist.deleted[0] if status_hist.deleted else None
            new_status = status_hist.added[0] if status_hist.added else getattr(target, 'status', None)
            if old_status != new_status and new_status == PartnerSettlementStatus.CONFIRMED.value:
                if target.partner_id:
                    _queue_partner_balance(target, target.partner_id)
    except Exception:
        pass


class PartnerSettlementLine(db.Model, TimestampMixin):
    __tablename__ = "partner_settlement_lines"

    id = db.Column(db.Integer, primary_key=True)
    settlement_id = db.Column(db.Integer, db.ForeignKey("partner_settlements.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = db.Column(db.String(30), nullable=False, index=True)
    source_id = db.Column(db.Integer, index=True)
    description = db.Column(db.String(255))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"))
    quantity = db.Column(db.Numeric(12, 3))
    unit_price = db.Column(db.Numeric(12, 2))
    gross_amount = db.Column(db.Numeric(12, 2))
    share_percent = db.Column(db.Numeric(6, 3))
    share_amount = db.Column(db.Numeric(12, 2))

    settlement = db.relationship("PartnerSettlement", back_populates="lines")
    product = db.relationship("Product")
    warehouse = db.relationship("Warehouse")

    __table_args__ = (
        db.Index("ix_partner_settle_line_product", "product_id"),
        db.Index("ix_partner_settle_line_warehouse", "warehouse_id"),
    )


def _find_partner_share_percentage(partner_id: int, product_id: int | None, warehouse_id: int | None) -> float:
    pct = 0.0
    if product_id:
        row2 = (
            db.session.query(ProductPartner.share_percent)
            .filter(ProductPartner.partner_id == partner_id, ProductPartner.product_id == product_id)
            .first()
        )
        if row2:
            return float(row2[0] or 0)
        if warehouse_id:
            row = (
                db.session.query(WarehousePartnerShare.share_percentage)
                .filter(
                    WarehousePartnerShare.partner_id == partner_id,
                    WarehousePartnerShare.product_id == product_id,
                    WarehousePartnerShare.warehouse_id == warehouse_id,
                )
                .first()
            )
            if row:
                return float(row[0] or 0)
        row = (
            db.session.query(WarehousePartnerShare.share_percentage)
            .filter(
                WarehousePartnerShare.partner_id == partner_id,
                WarehousePartnerShare.product_id == product_id,
                WarehousePartnerShare.warehouse_id.is_(None),
            )
            .first()
        )
        if row:
            return float(row[0] or 0)
    if warehouse_id:
        row3 = (
            db.session.query(WarehousePartnerShare.share_percentage)
            .filter(
                WarehousePartnerShare.partner_id == partner_id,
                WarehousePartnerShare.warehouse_id == warehouse_id,
                WarehousePartnerShare.product_id.is_(None),
            )
            .first()
        )
        if row3:
            return float(row3[0] or 0)
    return pct


def _partner_ids_for_product_warehouse(product_id: int | None, warehouse_id: int | None):
    partner_ids = set()
    if product_id:
        for (pid,) in db.session.query(ProductPartner.partner_id).filter(ProductPartner.product_id == product_id).all():
            partner_ids.add(pid)
        for (pid,) in db.session.query(WarehousePartnerShare.partner_id).filter(
            WarehousePartnerShare.product_id == product_id,
            WarehousePartnerShare.warehouse_id == warehouse_id,
        ).all():
            partner_ids.add(pid)
    if warehouse_id:
        for (pid,) in db.session.query(WarehousePartnerShare.partner_id).filter(
            WarehousePartnerShare.warehouse_id == warehouse_id,
            WarehousePartnerShare.product_id.is_(None),
        ).all():
            partner_ids.add(pid)
    return list(partner_ids)


def _compute_service_partner_shares(service_id: int):
    total_amount = Decimal("0")
    partner_shares = {}
    service = db.session.get(ServiceRequest, service_id)
    if not service:
        return total_amount, partner_shares
    total_amount = _D(service.total_amount or 0)
    for sp in getattr(service, "parts", []) or []:
        base = _D(sp.quantity or 0) * _D(sp.unit_price or 0) - _D(sp.discount or 0)
        if base <= 0:
            continue
        if sp.partner_id and float(sp.share_percentage or 0) > 0:
            share_amt = base * Decimal(str(float(sp.share_percentage or 0) / 100.0))
            partner_shares[sp.partner_id] = partner_shares.get(sp.partner_id, Decimal("0")) + share_amt
        else:
            for pid in _partner_ids_for_product_warehouse(sp.part_id, sp.warehouse_id):
                pct = _find_partner_share_percentage(pid, sp.part_id, sp.warehouse_id)
                if pct > 0:
                    share_amt = base * Decimal(str(pct / 100.0))
                    partner_shares[pid] = partner_shares.get(pid, Decimal("0")) + share_amt
    for k in list(partner_shares.keys()):
        partner_shares[k] = _Q2(partner_shares[k])
    return total_amount, partner_shares


def build_partner_settlement_draft(partner_id: int, date_from: datetime, date_to: datetime, *, currency: str = "ILS") -> PartnerSettlement:
    ps = PartnerSettlement(partner_id=partner_id, from_date=date_from, to_date=date_to, currency=(currency or "ILS").upper(), status=PartnerSettlementStatus.DRAFT.value)
    total_gross = Decimal("0.00")
    total_share = Decimal("0.00")

    parts_q = (
        db.session.query(ServicePart)
        .join(ServiceRequest, ServiceRequest.id == ServicePart.service_id)
        .filter(
            ServiceRequest.received_at >= date_from,
            ServiceRequest.received_at <= date_to,
            or_(ServicePart.partner_id == partner_id, ServicePart.partner_id.is_(None)),
        )
    )
    for sp in parts_q:
        base = q(sp.line_total)
        sp_share_pct = float(sp.share_percentage or 0)
        if sp.partner_id != partner_id:
            sp_share_pct = _find_partner_share_percentage(partner_id, sp.part_id, sp.warehouse_id)
        pct_dec = Decimal(str(sp_share_pct)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        share_amt = q(base * Decimal(str(sp_share_pct / 100.0))) if sp_share_pct else Decimal("0.00")
        if share_amt > 0:
            ps.lines.append(
                PartnerSettlementLine(
                    source_type="SERVICE_PART",
                    source_id=sp.id,
                    description=f"ServicePart #{sp.id}",
                    product_id=sp.part_id,
                    warehouse_id=sp.warehouse_id,
                    quantity=sp.quantity,
                    unit_price=sp.unit_price,
                    gross_amount=base,
                    share_percent=pct_dec,
                    share_amount=share_amt,
                )
            )
            total_gross += q(base)
            total_share += q(share_amt)

    sl_q = db.session.query(SaleLine).join(Sale, Sale.id == SaleLine.sale_id).filter(Sale.sale_date >= date_from, Sale.sale_date <= date_to)
    for sl in sl_q:
        base = q(getattr(sl, "line_total", (Decimal(str(sl.quantity or 0)) * Decimal(str(sl.unit_price or 0)))))
        pct = float(getattr(sl, "share_percentage", 0) or 0)
        if not pct:
            pct = _find_partner_share_percentage(partner_id, getattr(sl, "product_id", None), getattr(sl, "warehouse_id", None))
        pct_dec = Decimal(str(pct)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        share_amt = q(base * Decimal(str(pct / 100.0))) if pct else Decimal("0.00")
        if share_amt > 0:
            ps.lines.append(
                PartnerSettlementLine(
                    source_type="SALE_LINE",
                    source_id=sl.id,
                    description=f"SaleLine #{sl.id}",
                    product_id=getattr(sl, "product_id", None),
                    warehouse_id=getattr(sl, "warehouse_id", None),
                    quantity=getattr(sl, "quantity", None),
                    unit_price=getattr(sl, "unit_price", None),
                    gross_amount=base,
                    share_percent=pct_dec,
                    share_amount=share_amt,
                )
            )
            total_gross += q(base)
            total_share += q(share_amt)

    # 3. Sale Returns (Deduct from Settlement)
    srl_q = (
        db.session.query(SaleReturnLine)
        .join(SaleReturn, SaleReturn.id == SaleReturnLine.sale_return_id)
        .filter(
            SaleReturn.return_date >= date_from,
            SaleReturn.return_date <= date_to,
            SaleReturn.status == 'CONFIRMED'
        )
    )
    
    for srl in srl_q:
        pid = getattr(srl, "product_id", None)
        wid = getattr(srl, "warehouse_id", None)
        pct = _find_partner_share_percentage(partner_id, pid, wid)
        
        if pct > 0:
            qty = Decimal(str(srl.quantity or 0))
            # Use Product selling_price as approximation for "Lost Revenue" since return line might lack price
            u_price = Decimal("0")
            if srl.product:
                 u_price = Decimal(str(srl.product.selling_price or 0))
            
            base = q(u_price * qty)
            share_amt = q(base * Decimal(str(pct / 100.0)))
            pct_dec = Decimal(str(pct)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

            if share_amt > 0:
                ps.lines.append(
                    PartnerSettlementLine(
                        source_type="SALE_RETURN_LINE",
                        source_id=srl.id,
                        description=f"Return #{srl.sale_return_id} - Product #{pid}",
                        product_id=pid,
                        warehouse_id=wid,
                        quantity=-qty,
                        unit_price=u_price,
                        gross_amount=-base,
                        share_percent=pct_dec,
                        share_amount=-share_amt,
                    )
                )
                total_gross -= base
                total_share -= share_amt

    # 4. Inventory Share (Current Stock - For Information/Liquidation)
    # Only include if stock > 0
    # Note: Usually this is not paid out unless liquidating, but added per request.
    # We will mark it as INVENTORY_SHARE source_type.
    
    # A. ProductPartner Shares
    pp_q = (
        db.session.query(ProductPartner, StockLevel)
        .join(StockLevel, StockLevel.product_id == ProductPartner.product_id)
        .filter(
            ProductPartner.partner_id == partner_id,
            StockLevel.quantity > 0
        )
    )
    
    for pp, sl in pp_q:
        pct = float(pp.share_percent or 0)
        if pct > 0:
            qty = Decimal(str(sl.quantity or 0))
            # Use Purchase Price for Inventory Valuation
            prod = pp.product
            u_cost = Decimal(str(prod.purchase_price or 0)) if prod else Decimal("0")
            
            base = q(u_cost * qty)
            share_amt = q(base * Decimal(str(pct / 100.0)))
            pct_dec = Decimal(str(pct)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            
            if share_amt > 0:
                ps.lines.append(
                    PartnerSettlementLine(
                        source_type="INVENTORY_SHARE",
                        source_id=sl.id, # Using StockLevel ID as source
                        description=f"Inventory Share - Product #{pp.product_id} (WH: {sl.warehouse_id})",
                        product_id=pp.product_id,
                        warehouse_id=sl.warehouse_id,
                        quantity=qty,
                        unit_price=u_cost,
                        gross_amount=base,
                        share_percent=pct_dec,
                        share_amount=share_amt,
                    )
                )
                # Option: Do we add this to total_due? 
                # If we do, it means we are PAYING the partner for the inventory.
                # If the user wants to see it but not pay, it should be separate.
                # Given the prompt "calculate shares... for products in stock", I will add it to totals
                # but maybe the UI should distinguish it.
                total_gross += base
                total_share += share_amt

    # B. WarehousePartnerShare
    wps_q = (
        db.session.query(WarehousePartnerShare, StockLevel)
        .join(StockLevel, 
              and_(
                  StockLevel.product_id == WarehousePartnerShare.product_id,
                  StockLevel.warehouse_id == WarehousePartnerShare.warehouse_id
              )
        )
        .filter(
            WarehousePartnerShare.partner_id == partner_id,
            StockLevel.quantity > 0
        )
    )

    for wps, sl in wps_q:
        pct = float(wps.share_percentage or 0)
        if pct > 0:
            # Check if already covered by ProductPartner to avoid double counting?
            # Assuming additive or mutually exclusive for now.
            
            qty = Decimal(str(sl.quantity or 0))
            prod = sl.product
            u_cost = Decimal(str(prod.purchase_price or 0)) if prod else Decimal("0")
            
            base = q(u_cost * qty)
            share_amt = q(base * Decimal(str(pct / 100.0)))
            pct_dec = Decimal(str(pct)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            
            if share_amt > 0:
                ps.lines.append(
                    PartnerSettlementLine(
                        source_type="INVENTORY_SHARE_WH",
                        source_id=sl.id,
                        description=f"WH Share - Product #{wps.product_id} (WH: {wps.warehouse_id})",
                        product_id=wps.product_id,
                        warehouse_id=wps.warehouse_id,
                        quantity=qty,
                        unit_price=u_cost,
                        gross_amount=base,
                        share_percent=pct_dec,
                        share_amount=share_amt,
                    )
                )
                total_gross += base
                total_share += share_amt

    ps.total_gross = q(total_gross)
    ps.total_share = q(total_share)
    ps.total_costs = q(0)
    ps.total_due = q(total_share)
    ps.ensure_code()
    return ps

class Employee(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    position = db.Column(db.String(100))
    salary = db.Column(db.Numeric(15, 2), default=0, nullable=True)  # الراتب الشهري
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120), unique=True, index=True, nullable=True)
    hire_date = db.Column(db.Date, nullable=True, index=True)  # تاريخ التعيين
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    currency = db.Column(db.String(10), default="ILS", nullable=False, server_default=sa_text("'ILS'"))
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=True, index=True)

    expenses = relationship("Expense", back_populates="employee", cascade="all, delete-orphan")
    branch = relationship('Branch', back_populates='employees', foreign_keys=[branch_id])
    site = relationship('Site', back_populates='employees', foreign_keys=[site_id])
    deductions = relationship('EmployeeDeduction', back_populates='employee', cascade="all, delete-orphan")
    advances = relationship('EmployeeAdvance', back_populates='employee', cascade="all, delete-orphan")
    advance_installments = relationship('EmployeeAdvanceInstallment', back_populates='employee', cascade="all, delete-orphan")

    __table_args__ = ()

    @validates("email")
    def _v_email(self, _, v):
        return (v or "").strip().lower() or None

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("name", "position", "phone", "bank_name", "account_number", "notes")
    def _v_strip(self, _, v):
        s = (v or "").strip()
        return s or None

    @hybrid_property
    def total_expenses(self):
        from decimal import Decimal
        expenses = db.session.query(Expense).filter(Expense.employee_id == self.id).all()
        total = Decimal('0.00')
        for exp in expenses:
            amt = Decimal(str(exp.amount or 0))
            if exp.currency == DEFAULT_CURRENCY:
                total += amt
            else:
                try:
                    total += convert_amount(amt, exp.currency, DEFAULT_CURRENCY, exp.date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        return float(total)

    @total_expenses.expression
    def total_expenses(cls):
        return select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.employee_id == cls.id).scalar_subquery()

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        payments = db.session.query(Payment).join(Expense, Payment.expense_id == Expense.id).filter(
            Expense.employee_id == self.id,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.direction == PaymentDirection.OUT.value
        ).all()
        total = Decimal('0.00')
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == DEFAULT_CURRENCY:
                total += amt
            else:
                try:
                    total += convert_amount(amt, p.currency, DEFAULT_CURRENCY, p.payment_date)
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        return float(total)

    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .select_from(Payment.__table__.join(Expense, Payment.expense_id == Expense.id))
            .where(
                (Expense.employee_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.OUT.value)
            )
            .scalar_subquery()
        )

    @hybrid_property
    def balance(self):
        return self.total_expenses - self.total_paid

    @balance.expression
    def balance(cls):
        return cls.total_expenses - cls.total_paid

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "position": self.position,
            "phone": self.phone,
            "currency": self.currency,
            "total_expenses": self.total_expenses,
            "total_paid": self.total_paid,
            "balance": self.balance,
        }

    @hybrid_property
    def total_advances(self):
        """مجموع السلف غير المسددة"""
        from models import ExpenseType
        advance_type = db.session.query(ExpenseType).filter_by(code='EMPLOYEE_ADVANCE').first()
        if not advance_type:
            return 0.0
        return float(
            db.session.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.employee_id == self.id, Expense.type_id == advance_type.id)
            .scalar()
        )

    @hybrid_property
    def total_deductions(self):
        """مجموع الخصومات الشهرية النشطة"""
        from datetime import date
        today = date.today()
        return float(
            db.session.query(func.coalesce(func.sum(EmployeeDeduction.amount), 0))
            .filter(
                EmployeeDeduction.employee_id == self.id,
                EmployeeDeduction.is_active == True,
                or_(EmployeeDeduction.end_date.is_(None), EmployeeDeduction.end_date >= today)
            )
            .scalar()
        )

    @hybrid_property
    def net_salary(self):
        """الراتب الصافي = الراتب الأساسي - الخصومات"""
        return float(self.salary or 0) - self.total_deductions
    
    @property
    def social_insurance_employee_amount(self):
        """مبلغ التأمينات - حصة الموظف (من الثوابت)"""
        try:
            from utils import get_social_insurance_rates
            rates = get_social_insurance_rates()
            if not rates['enabled']:
                return 0.0
            return float(self.salary or 0) * (rates['employee_rate'] / 100)
        except Exception:
            return 0.0
    
    @property
    def social_insurance_company_amount(self):
        """مبلغ التأمينات - حصة الشركة (من الثوابت)"""
        try:
            from utils import get_social_insurance_rates
            rates = get_social_insurance_rates()
            if not rates['enabled']:
                return 0.0
            return float(self.salary or 0) * (rates['company_rate'] / 100)
        except Exception:
            return 0.0
    
    @property
    def income_tax_amount(self):
        """ضريبة الدخل على الراتب (تقريبية - 5% حتى 75k، ثم 10%...)"""
        try:
            salary_annual = float(self.salary or 0) * 12
            
            # فلسطين: معفى حتى 75,000 سنوياً
            if salary_annual <= 75000:
                return salary_annual * 0.05 / 12
            elif salary_annual <= 150000:
                return ((75000 * 0.05) + ((salary_annual - 75000) * 0.10)) / 12
            elif salary_annual <= 300000:
                return ((75000 * 0.05) + (75000 * 0.10) + ((salary_annual - 150000) * 0.15)) / 12
            else:
                return ((75000 * 0.05) + (75000 * 0.10) + (150000 * 0.15) + ((salary_annual - 300000) * 0.20)) / 12
        except Exception:
            return 0.0
    
    @property
    def eosb_amount(self):
        """مكافأة نهاية الخدمة (EOSB) - راتب شهر عن كل سنة"""
        try:
            from datetime import date
            if not self.hire_date:
                return 0.0
            years_of_service = (date.today() - self.hire_date).days / 365.25
            return float(self.salary or 0) * years_of_service
        except Exception:
            return 0.0
    
    @property
    def total_company_cost(self):
        """التكلفة الكلية على الشركة = الراتب + التأمينات"""
        return float(self.salary or 0) + self.social_insurance_company_amount
    
    @property
    def net_salary_after_all(self):
        """الراتب الصافي بعد كل الاستقطاعات (خصومات + تأمينات + ضرائب)"""
        return (
            float(self.salary or 0) 
            - self.total_deductions 
            - self.social_insurance_employee_amount 
            - self.income_tax_amount
        )

    def __repr__(self):
        return f"<Employee {self.name}>"


class EmployeeDeduction(db.Model, TimestampMixin, AuditMixin):
    """خصومات شهرية من راتب الموظف (تأمين، هاتف، قرض، إلخ)"""
    __tablename__ = "employee_deductions"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    deduction_type = db.Column(db.String(50), nullable=False, index=True)  # تأمين/هاتف/قرض/أخرى
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    notes = db.Column(db.Text)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=True, index=True)  # ربط بمصروف إن وجد

    employee = relationship('Employee', back_populates='deductions')
    expense = relationship('Expense')

    def __repr__(self):
        return f"<EmployeeDeduction {self.deduction_type} {self.amount}>"


class EmployeeAdvance(db.Model, TimestampMixin, AuditMixin):
    """سلف الموظفين"""
    __tablename__ = "employee_advances"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    advance_date = db.Column(db.Date, nullable=False, index=True)
    reason = db.Column(db.Text)
    total_installments = db.Column(db.Integer, nullable=False, default=1)
    installments_paid = db.Column(db.Integer, nullable=False, default=0)
    fully_paid = db.Column(db.Boolean, nullable=False, default=False, index=True)
    notes = db.Column(db.Text)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=True, index=True)

    employee = relationship('Employee', back_populates='advances')
    expense = relationship('Expense')

    def __repr__(self):
        return f"<EmployeeAdvance {self.amount} for {self.employee.name if self.employee else 'N/A'}>"


class EmployeeAdvanceInstallment(db.Model, TimestampMixin, AuditMixin):
    """أقساط سداد السلف من الرواتب"""
    __tablename__ = "employee_advance_installments"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    advance_expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False, index=True)
    installment_number = db.Column(db.Integer, nullable=False)
    total_installments = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    paid = db.Column(db.Boolean, default=False, nullable=False, index=True)
    paid_date = db.Column(db.Date, nullable=True, index=True)
    paid_in_salary_expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=True, index=True)
    
    # Relations
    employee = relationship('Employee', back_populates='advance_installments')
    advance_expense = relationship('Expense', foreign_keys=[advance_expense_id])
    salary_expense = relationship('Expense', foreign_keys=[paid_in_salary_expense_id])

    __table_args__ = ()


class EquipmentType(db.Model, TimestampMixin):
    __tablename__ = 'equipment_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    model_number = db.Column(db.String(100))
    chassis_number = db.Column(db.String(100))
    notes = db.Column(db.Text)
    category = db.Column(db.String(50))
    products = db.relationship('Product', back_populates='vehicle_type')
    service_requests = db.relationship('ServiceRequest', back_populates='vehicle_type')
    def __repr__(self): return f"<EquipmentType {self.name}>"

class ProductCategory(db.Model, TimestampMixin):
    __tablename__ = 'product_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('product_categories.id'))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    parent = db.relationship('ProductCategory', remote_side=[id], backref='subcategories')
    products = db.relationship('Product', back_populates='category')
    __table_args__ = ()
    @validates("name", "description", "image_url")
    def _v_strip(self, _, v):
        return (v or "").strip() or None
    def __repr__(self): return f"<ProductCategory {self.name}>"

class Product(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    sku = Column(String(50))
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    part_number = Column(String(100), index=True)
    brand = Column(String(100), index=True)
    commercial_name = Column(String(100))
    chassis_number = Column(String(100))
    serial_no = Column(String(100))
    barcode = Column(String(100))
    unit = Column(String(50))
    category_name = Column(String(100))
    purchase_price = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    selling_price = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    cost_before_shipping = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    cost_after_shipping = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    unit_price_before_tax = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    price = Column(Numeric(12, 2), nullable=False, default=0, server_default=sa_text("0"))
    min_price = Column(Numeric(12, 2))
    max_price = Column(Numeric(12, 2))
    tax_rate = Column(Numeric(5, 2), nullable=False, default=0, server_default=sa_text("0"))
    min_qty = Column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    reorder_point = Column(Integer)
    image = Column(String(255))
    notes = Column(Text)
    condition = Column(sa_str_enum(ProductCondition, name="product_condition"), default=ProductCondition.NEW.value, nullable=False, server_default=sa_text("'NEW'"))
    origin_country = Column(String(50))
    warranty_period = Column(Integer)
    weight = Column(Numeric(10, 2))
    dimensions = Column(String(50))
    is_active = Column(Boolean, default=True, nullable=False, server_default=sa_text("true"))
    is_digital = Column(Boolean, default=False, nullable=False, server_default=sa_text("false"))
    is_exchange = Column(Boolean, default=False, nullable=False, server_default=sa_text("false"))
    is_published = Column(Boolean, default=True, nullable=False, server_default=sa_text("true"))
    vehicle_type_id = Column(Integer, ForeignKey("equipment_types.id"))
    category_id = Column(Integer, ForeignKey("product_categories.id"))
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    supplier_international_id = Column(Integer, ForeignKey("suppliers.id"))
    supplier_local_id = Column(Integer, ForeignKey("suppliers.id"))
    online_name = Column(String(255))
    online_price = Column(Numeric(12, 2), default=0, server_default=sa_text("0"))
    online_image = Column(String(255))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    
    # ✅ حقول العملة وسعر الصرف
    currency = Column(String(10), default='ILS', nullable=False, server_default=sa_text("'ILS'"))
    fx_rate_used = Column(Numeric(10, 6))
    fx_rate_source = Column(String(20))
    fx_rate_timestamp = Column(DateTime)
    fx_base_currency = Column(String(10))
    fx_quote_currency = Column(String(10))
    
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_product_price_ge_0"),
        CheckConstraint("purchase_price >= 0", name="ck_product_purchase_ge_0"),
        CheckConstraint("selling_price >= 0", name="ck_product_selling_ge_0"),
        CheckConstraint("cost_before_shipping >= 0", name="ck_product_cost_before_ge_0"),
        CheckConstraint("cost_after_shipping >= 0", name="ck_product_cost_after_ge_0"),
        CheckConstraint("unit_price_before_tax >= 0", name="ck_product_unit_before_tax_ge_0"),
        CheckConstraint("min_price IS NULL OR min_price >= 0", name="ck_product_min_price_ge_0"),
        CheckConstraint("max_price IS NULL OR max_price >= 0", name="ck_product_max_price_ge_0"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_product_tax_rate_0_100"),
        CheckConstraint("min_qty >= 0", name="ck_product_min_qty_ge_0"),
        CheckConstraint("reorder_point IS NULL OR reorder_point >= 0", name="ck_product_reorder_ge_0"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_product_weight_ge_0"),
        CheckConstraint("online_price IS NULL OR online_price >= 0", name="ck_product_online_price_ge_0"),
        Index("ix_products_brand_part", "brand", "part_number"),
        Index("uq_products_name_wh_ci", func.lower(name), "warehouse_id", unique=True, postgresql_where=warehouse_id.isnot(None)),
        Index("uq_products_name_global_ci", func.lower(name), unique=True, postgresql_where=warehouse_id.is_(None)),
        Index("uq_products_sku_ci", func.lower(sku), unique=True, postgresql_where=sku.isnot(None)),
        Index("uq_products_barcode", barcode, unique=True, postgresql_where=barcode.isnot(None)),
        Index("uq_products_serial_ci", func.lower(serial_no), unique=True, postgresql_where=serial_no.isnot(None)),
        Index("ix_products_category_active", "category_id", "is_active"),
        Index("ix_products_is_published", "is_published"),
        Index("ix_products_supplier", "supplier_id"),
        Index("ix_products_warehouse", "warehouse_id"),
        Index("ix_products_vehicle_type", "vehicle_type_id"),
    )
    category = relationship("ProductCategory", back_populates="products")
    vehicle_type = relationship("EquipmentType", back_populates="products")
    supplier_general = relationship("Supplier", foreign_keys=[supplier_id])
    supplier_international = relationship("Supplier", foreign_keys=[supplier_international_id])
    supplier_local = relationship("Supplier", foreign_keys=[supplier_local_id])
    partners = relationship("ProductPartner", back_populates="product")
    partner_shares = relationship("ProductPartnerShare", back_populates="product")
    supplier_loans = relationship("ProductSupplierLoan", back_populates="product")
    transfers = relationship("Transfer", back_populates="product")
    preorders = relationship("PreOrder", back_populates="product")
    shipment_items = relationship("ShipmentItem", back_populates="product")
    exchange_transactions = relationship("ExchangeTransaction", back_populates="product")
    sale_lines = relationship("SaleLine", back_populates="product")
    service_parts = relationship("ServicePart", back_populates="part")
    online_cart_items = relationship("OnlineCartItem", back_populates="product")
    online_preorder_items = relationship("OnlinePreOrderItem", back_populates="product")
    stock_levels = relationship("StockLevel", back_populates="product")
    stock_adjustment_items = relationship("StockAdjustmentItem", back_populates="product", cascade='all, delete-orphan')
    def __init__(self, **kwargs):
        self.category_name = (kwargs.pop("category", None) or None)
        self.unit = (kwargs.pop("unit", None) or None)
        self.purchase_price = kwargs.pop("purchase_price", 0)
        self.selling_price = kwargs.pop("selling_price", kwargs.get("price", 0))
        self.notes = kwargs.pop("notes", None)
        super().__init__(**kwargs)
    @validates('currency')
    def _v_currency(self, _, v):
        return ensure_currency(v or DEFAULT_CURRENCY)
    @validates("sku", "serial_no", "barcode")
    def _v_strip_norm_ids(self, key, v):
        if v is None: return None
        v = str(v).strip()
        if key in ("sku", "serial_no"): v = v.upper()
        if key == "barcode": v = normalize_barcode(v) or None
        return v
    @validates("name","brand","part_number","commercial_name","chassis_number","category_name","origin_country","dimensions","unit","online_name","online_image","image","description","notes")
    def _v_strip_texts(self, key, v):
        if v is None: return None
        v = str(v).strip()
        return v or None
    @validates("purchase_price","selling_price","cost_before_shipping","cost_after_shipping","unit_price_before_tax","price","min_price","max_price","tax_rate","weight","online_price")
    def _v_money_numeric(self, key, v):
        if v is None or v == "":
            return 0 if key in ("price","purchase_price","selling_price","cost_before_shipping","cost_after_shipping","unit_price_before_tax") else None
        if isinstance(v, str): v = v.replace("$","").replace(",","").strip()
        d = Decimal(str(v))
        if key == "tax_rate" and (d < 0 or d > Decimal("100")): raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        field_names = {"price": "السعر", "cost": "التكلفة", "min_price": "الحد الأدنى للسعر"}
        if d < 0: raise ValueError(f"{field_names.get(key, key)} لا يمكن أن يكون سالباً")
        return d
    @validates("min_qty","reorder_point","warranty_period")
    def _v_int_nonneg(self, key, v):
        if v in (None,""): return None if key == "reorder_point" else 0
        i = int(v)
        field_names = {"min_qty": "الحد الأدنى للكمية", "reorder_point": "نقطة إعادة الطلب", "warranty_period": "فترة الضمان"}
        if i < 0: raise ValueError(f"{field_names.get(key, key)} لا يمكن أن يكون سالباً")
        return i
    @hybrid_property
    def total_partner_percentage(self):
        return sum(float(share.share_percentage or 0) for share in (self.partner_shares or []))
    @hybrid_property
    def total_partner_amount(self):
        return sum(float(share.share_amount or 0) for share in (self.partner_shares or []))
    def quantity_in_warehouse(self, warehouse_id):
        level = next((s for s in (self.stock_levels or []) if s.warehouse_id == warehouse_id), None)
        return level.quantity if level else 0
    @hybrid_property
    def condition_display(self):
        m = {ProductCondition.NEW.value:"جديد", ProductCondition.USED.value:"مستعمل", ProductCondition.REFURBISHED.value:"مجدّد"}
        v = getattr(self.condition,"value",self.condition)
        return m.get(v, v)
    @hybrid_property
    def effective_name(self):
        return self.online_name or self.name
    @hybrid_property
    def effective_price(self):
        return self.online_price if self.online_price is not None else self.price
    @hybrid_property
    def effective_image(self):
        return self.online_image or self.image
    def __repr__(self): return f"<Product {self.name}>"

@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _product_before_save(mapper, connection, t: Product):
    from decimal import Decimal as _D
    if (t.selling_price or 0) == 0 and (t.price or 0) > 0: t.selling_price = t.price
    if (t.price or 0) == 0 and (t.selling_price or 0) > 0: t.price = t.selling_price
    if t.min_price is not None and t.max_price is not None:
        if _D(str(t.min_price)) > _D(str(t.max_price)):
            t.min_price, t.max_price = t.max_price, t.min_price
        mn = _D(str(t.min_price)); mx = _D(str(t.max_price))
        if t.price is not None:
            p = _D(str(t.price))
            if p < mn: t.price = mn
            elif p > mx: t.price = mx
    try:
        from flask import current_app
        if not t.image:
            t.image = current_app.config.get("DEFAULT_PRODUCT_IMAGE") or t.image
    except Exception:
        pass
    t.is_active = bool(t.is_active)
    t.is_digital = bool(t.is_digital)
    t.is_exchange = bool(t.is_exchange)
    t.is_published = bool(t.is_published)

class Branch(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    geo_lat = db.Column(db.Numeric(10, 6))
    geo_lng = db.Column(db.Numeric(10, 6))
    phone = db.Column(db.String(32))
    email = db.Column(db.String(120))
    manager_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    manager_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', use_alter=True, name='fk_branches_manager_employee_id'), index=True)
    timezone = db.Column(db.String(64))
    currency = db.Column(db.String(10), nullable=False, server_default=sa_text("'ILS'"))
    tax_id = db.Column(db.String(64))
    notes = db.Column(db.Text)
    is_archived = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    archive_reason = db.Column(db.String(200))

    manager_user = db.relationship('User', foreign_keys=[manager_user_id])
    manager_employee = db.relationship('Employee', foreign_keys=[manager_employee_id], post_update=True)
    archived_by_user = db.relationship('User', foreign_keys=[archived_by])

    sites = db.relationship('Site', back_populates='branch', cascade="all, delete-orphan")
    employees = db.relationship('Employee', back_populates='branch', foreign_keys='Employee.branch_id')
    expenses = db.relationship('Expense', back_populates='branch')
    warehouses = db.relationship('Warehouse', back_populates='branch')

    def __repr__(self):
        return f"<Branch {self.code}:{self.name}>"


class Site(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'sites'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(32), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    geo_lat = db.Column(db.Numeric(10, 6))
    geo_lng = db.Column(db.Numeric(10, 6))
    manager_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    manager_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', use_alter=True, name='fk_sites_manager_employee_id'), index=True)
    notes = db.Column(db.Text)
    is_archived = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    archive_reason = db.Column(db.String(200))

    branch = db.relationship('Branch', back_populates='sites')
    manager_user = db.relationship('User', foreign_keys=[manager_user_id])
    manager_employee = db.relationship('Employee', foreign_keys=[manager_employee_id], post_update=True)
    archived_by_user = db.relationship('User', foreign_keys=[archived_by])

    employees = db.relationship('Employee', back_populates='site', foreign_keys='Employee.site_id')
    expenses = db.relationship('Expense', back_populates='site')

    def __repr__(self):
        return f"<Site {self.code}@{self.branch_id}>"


class UserBranch(db.Model, TimestampMixin):
    """ربط المستخدمين بالفروع (Many-to-Many)"""
    __tablename__ = "user_branches"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, index=True)
    can_manage = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship('User', backref='user_branches')
    branch = db.relationship('Branch', backref='user_branches')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'branch_id', name='uq_user_branch'),
    )

    def __repr__(self):
        return f"<UserBranch user={self.user_id} branch={self.branch_id}>"


class Warehouse(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'warehouses'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    warehouse_type = db.Column(sa_str_enum(WarehouseType, name='warehouse_type'), default=WarehouseType.MAIN.value, nullable=False, index=True, server_default=sa_text("'MAIN'"))
    location = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, server_default=sa_text("true"))
    parent_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'))
    share_percent = db.Column(db.Numeric(5, 2), default=0, server_default=sa_text("0"))
    capacity = db.Column(db.Integer)
    current_occupancy = db.Column(db.Integer, default=0, server_default=sa_text("0"))
    notes = db.Column(db.Text)
    online_slug = db.Column(db.String(150), unique=True)
    online_is_default = db.Column(db.Boolean, nullable=False, default=False, server_default=sa_text("false"))
    parent = db.relationship('Warehouse', remote_side=[id], backref='children')
    supplier = db.relationship('Supplier', back_populates='warehouses')
    branch = db.relationship('Branch', back_populates='warehouses')
    partner = db.relationship('Partner', back_populates='warehouses')
    stock_levels = db.relationship('StockLevel', back_populates='warehouse')
    transfers_source = db.relationship('Transfer', back_populates='source_warehouse', foreign_keys='Transfer.source_id')
    transfers_destination = db.relationship('Transfer', back_populates='destination_warehouse', foreign_keys='Transfer.destination_id')
    sale_lines = db.relationship('SaleLine', back_populates='warehouse')
    service_parts = db.relationship('ServicePart', back_populates='warehouse')
    exchange_transactions = db.relationship('ExchangeTransaction', back_populates='warehouse')
    shipment_items = db.relationship('ShipmentItem', back_populates='warehouse')
    shipments_received = db.relationship('Shipment', back_populates='destination_warehouse', foreign_keys='Shipment.destination_id')
    preorders = db.relationship('PreOrder', back_populates='warehouse')
    partner_shares = db.relationship('WarehousePartnerShare', back_populates='warehouse')
    expenses = db.relationship('Expense', back_populates='warehouse')
    stock_adjustments = db.relationship('StockAdjustment', back_populates='warehouse', passive_deletes=True)
    __table_args__ = (
        Index("ix_warehouses_parent", "parent_id"),
        Index("ix_warehouses_supplier", "supplier_id"),
        Index("ix_warehouses_partner", "partner_id"),
        Index("ix_warehouses_share_percent", "share_percent"),
    )
    @validates('name','location','notes','online_slug')
    def _v_strip(self,_,v): return (v or '').strip() or None
    @validates('warehouse_type')
    def _v_warehouse_type(self,_,v):
        if isinstance(v,WarehouseType): return v.value
        s=(str(v or '')).strip().upper()
        allowed={e.value for e in WarehouseType}
        return s if s in allowed else WarehouseType.MAIN.value
    @validates('share_percent')
    def _v_share_percent(self,_,v):
        if v is None: return 0
        f=float(v)
        if f<0 or f>100: raise ValueError('share_percent must be between 0 and 100')
        return f
    @validates('capacity')
    def _v_capacity(self,_,v):
        if v is None: return None
        iv=int(v)
        if iv<0: raise ValueError('capacity must be >= 0')
        if self.current_occupancy is not None and self.current_occupancy>iv:
            raise ValueError('current_occupancy cannot exceed capacity')
        return iv
    @validates('current_occupancy')
    def _v_current_occupancy(self,_,v):
        if v is None: return 0
        iv=int(v)
        if iv<0: raise ValueError('current_occupancy must be >= 0')
        if self.capacity is not None and iv>int(self.capacity):
            raise ValueError('current_occupancy cannot exceed capacity')
        return iv
    @hybrid_property
    def warehouse_type_display(self):
        try:
            from utils.tenant_org_structure import warehouse_type_labels

            m = warehouse_type_labels()
        except Exception:
            m = {t.value: t.label for t in WarehouseType}
        wt = getattr(self, 'warehouse_type', None)
        key = getattr(wt, 'value', wt)
        return m.get(key, key)
    @hybrid_property
    def is_online(self):
        wt=getattr(self,'warehouse_type',None); key=getattr(wt,'value',wt)
        return key==WarehouseType.ONLINE.value
    def __repr__(self): return f"<Warehouse {self.name}>"

@event.listens_for(Warehouse, 'before_insert')
@event.listens_for(Warehouse, 'before_update')
def _warehouse_guard(mapper, connection, target: Warehouse):
    wt = (
        target.warehouse_type.value
        if isinstance(target.warehouse_type, WarehouseType)
        else str(target.warehouse_type or "")
    ).upper()

    if wt == WarehouseType.PARTNER.value:
        target.supplier_id = None
    elif wt == WarehouseType.EXCHANGE.value:
        target.partner_id = None
        target.share_percent = 0
    elif wt == WarehouseType.INVENTORY.value:
        target.partner_id = None
        target.supplier_id = None
        target.share_percent = 0
    elif wt == WarehouseType.MAIN.value:
        target.partner_id = None
        target.supplier_id = None
        target.share_percent = 0
    elif wt == WarehouseType.ONLINE.value:
        if not (target.online_slug or "").strip():
            nm = (target.name or "").strip().lower()
            slug = re.sub(r"[^a-z0-9]+", "-", nm).strip("-") if nm else None
            target.online_slug = slug or target.online_slug
        target.supplier_id = None
        target.partner_id = None
        target.share_percent = 0

@event.listens_for(Warehouse, "before_insert")
@event.listens_for(Warehouse, "before_update")
def _enforce_single_online_default(mapper, connection, target):
    try:
        wt = (
            target.warehouse_type.value
            if isinstance(target.warehouse_type, WarehouseType)
            else str(target.warehouse_type or "")
        ).upper()
        if wt != WarehouseType.ONLINE.value or not getattr(target, "online_is_default", False):
            return
        q = """
            SELECT id
            FROM warehouses
            WHERE warehouse_type = :wt
              AND online_is_default IS TRUE
              AND (:cur_id IS NULL OR id <> :cur_id)
            LIMIT 1
            """
        other = connection.execute(
            sa_text(q),
            {"wt": WarehouseType.ONLINE.value, "cur_id": getattr(target, "id", None)},
        ).first()
        if other:
            connection.execute(
                sa_text("UPDATE warehouses SET online_is_default = FALSE WHERE id = :id"),
                {"id": other[0]},
            )
    except Exception:
        pass

class StockLevel(db.Model, TimestampMixin):
    __tablename__ = 'stock_levels'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    reserved_quantity = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    min_stock = db.Column(db.Integer)
    max_stock = db.Column(db.Integer)
    __table_args__ = (
        db.CheckConstraint('quantity >= 0', name='ck_stock_non_negative'),
        db.CheckConstraint('reserved_quantity >= 0', name='ck_reserved_non_negative'),
        # تم تعطيل هذا القيد لأننا لم نعد نستخدم نظام الحجز
        # db.CheckConstraint('(quantity - reserved_quantity) >= 0', name='ck_stock_reserved_leq_qty'),
        db.CheckConstraint('(min_stock IS NULL OR min_stock >= 0)', name='ck_min_non_negative'),
        db.CheckConstraint('(max_stock IS NULL OR max_stock >= 0)', name='ck_max_non_negative'),
        db.CheckConstraint('(min_stock IS NULL OR max_stock IS NULL OR max_stock >= min_stock)', name='ck_max_ge_min'),
        db.UniqueConstraint('product_id', 'warehouse_id', name='uq_stock_product_wh'),
        db.Index('ix_stock_product_wh', 'product_id', 'warehouse_id'),
        db.Index('ix_stock_quantity', 'quantity'),
    )
    product = db.relationship('Product', back_populates='stock_levels')
    warehouse = db.relationship('Warehouse', back_populates='stock_levels')
    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v or 0)
        if v < 0: raise ValueError("الكمية لا يمكن أن تكون سالبة")
        return v
    @validates('reserved_quantity')
    def _v_reserved_qty(self, _, v):
        v = int(v or 0)
        if v < 0: raise ValueError("الكمية المحجوزة لا يمكن أن تكون سالبة")
        return v
    @hybrid_property
    def available_quantity(self):
        return max(0, int(self.quantity or 0) - int(self.reserved_quantity or 0))
    @hybrid_property
    def partner_share_quantity(self):
        wh = getattr(self, 'warehouse', None)
        if not wh: return 0
        wt = getattr(wh.warehouse_type, 'value', wh.warehouse_type)
        share = float(getattr(wh, 'share_percent', 0) or 0)
        return self.quantity * share / 100.0 if wt == WarehouseType.PARTNER.value and share else 0
    @hybrid_property
    def company_share_quantity(self):
        wh = getattr(self, 'warehouse', None)
        if not wh: return self.quantity
        wt = getattr(wh.warehouse_type, 'value', wh.warehouse_type)
        return self.quantity - self.partner_share_quantity if wt == WarehouseType.PARTNER.value and wh.share_percent else self.quantity
    @hybrid_property
    def status(self):
        qv = int(self.quantity or 0); mn = int(self.min_stock or 0); mx = self.max_stock
        if qv == mn: return "عند الحد الأدنى"
        elif qv < mn: return "تحت الحد الأدنى"
        elif mx is not None:
            if qv == int(mx): return "عند الحد الأقصى"
            elif qv > int(mx): return "فوق الحد الأقصى"
        return "طبيعي"
    @property
    def last_updated(self): return self.updated_at
    def __repr__(self): return f"<StockLevel P{self.product_id} W{self.warehouse_id} Q{self.quantity} R{self.reserved_quantity}>"

class StockMovement(db.Model, TimestampMixin):
    __tablename__ = 'stock_movements'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    quantity_change = db.Column(db.Numeric(10, 2), nullable=False)
    balance_after = db.Column(db.Numeric(10, 2))
    movement_type = db.Column(db.String(50), nullable=False, index=True) # PURCHASE, SERVICE, ADJUSTMENT, TRANSFER, SALE
    reference_type = db.Column(db.String(50)) # SERVICE, INVOICE, IMPORT, TRANSFER
    reference_id = db.Column(db.Integer)
    notes = db.Column(db.String(255))
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    product = db.relationship('Product', backref=db.backref('stock_movements', lazy='dynamic'))
    warehouse = db.relationship('Warehouse', backref=db.backref('stock_movements', lazy='dynamic'))

class ImportRun(db.Model, TimestampMixin):
    __tablename__ = "import_runs"
    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    filename = db.Column(db.String(255))
    file_sha256 = db.Column(db.String(64))
    dry_run = db.Column(db.Boolean, nullable=False, default=False, server_default=sa_text("false"), index=True)
    inserted = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    updated = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    skipped = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    errors = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    duration_ms = db.Column(db.Integer, nullable=False, default=0, server_default=sa_text("0"))
    report_path = db.Column(db.String(255))
    notes = db.Column(db.String(255))
    meta = db.Column(db.JSON, default=dict)
    warehouse = db.relationship("Warehouse", backref=db.backref("import_runs", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("import_runs", lazy="dynamic"))
    __table_args__ = ()
    def __repr__(self) -> str:
        return f"<ImportRun id={self.id} wh={self.warehouse_id} dry={self.dry_run} ins={self.inserted} upd={self.updated} skp={self.skipped} err={self.errors}>"

def _ensure_stock_row(connection, product_id: int, warehouse_id: int):
    row = connection.execute(sa_text("SELECT id FROM stock_levels WHERE product_id = :p AND warehouse_id = :w"), {"p": product_id, "w": warehouse_id}).first()
    if row: return row
    dialect = getattr(connection, "dialect", None); dname = getattr(dialect, "name", "") if dialect else ""
    try:
        connection.execute(
            sa_text(
                "INSERT INTO stock_levels (product_id, warehouse_id, quantity, reserved_quantity) "
                "SELECT :p, :w, 0, 0 WHERE NOT EXISTS "
                "(SELECT 1 FROM stock_levels WHERE product_id = :p AND warehouse_id = :w)"
            ),
            {"p": product_id, "w": warehouse_id}
        )
    except Exception:
        pass
    return connection.execute(sa_text("SELECT id FROM stock_levels WHERE product_id = :p AND warehouse_id = :w"), {"p": product_id, "w": warehouse_id}).first()

def _apply_stock_delta(connection, product_id: int, warehouse_id: int, delta_qty: int, 
                       movement_type: str = "ADJUSTMENT", ref_type: str = None, ref_id: int = None, notes: str = None, user_id: int = None):
    row = _ensure_stock_row(connection, product_id, warehouse_id); sid = row._mapping["id"]; qv = int(delta_qty or 0)
    if qv == 0:
        qty = connection.execute(sa_text("SELECT quantity FROM stock_levels WHERE id = :id"), {"id": sid}).scalar_one()
        return int(qty)
    if qv > 0:
        connection.execute(sa_text("UPDATE stock_levels SET quantity = quantity + :q WHERE id = :id"), {"id": sid, "q": qv})
    else:
        res = connection.execute(sa_text("UPDATE stock_levels SET quantity = quantity + :q WHERE id = :id AND quantity + :q >= 0 AND quantity + :q >= reserved_quantity"), {"id": sid, "q": qv})
        if getattr(res, "rowcount", None) != 1:
            raise ValueError(f"الكمية غير كافية للمنتج {product_id} في المستودع {warehouse_id}")
    qty = connection.execute(sa_text("SELECT quantity FROM stock_levels WHERE id = :id"), {"id": sid}).scalar_one()
    
    # Log Movement
    try:
        connection.execute(
            sa_text("""
                INSERT INTO stock_movements (product_id, warehouse_id, quantity_change, balance_after, movement_type, reference_type, reference_id, notes, created_by, created_at, updated_at)
                VALUES (:pid, :wh, :qty, :bal, :type, :ref_type, :ref_id, :notes, :uid, :now, :now)
            """),
            {
                "pid": product_id,
                "wh": warehouse_id,
                "qty": qv,
                "bal": qty,
                "type": movement_type or "ADJUSTMENT",
                "ref_type": ref_type,
                "ref_id": ref_id,
                "notes": notes,
                "uid": user_id,
                "now": datetime.now(timezone.utc)
            }
        )
    except Exception:
        pass

    return int(qty)

def _apply_reservation_delta(connection, product_id: int, warehouse_id: int, delta_qty: int):
    row = _ensure_stock_row(connection, product_id, warehouse_id); sid = row._mapping["id"]; qv = int(delta_qty or 0)
    if qv == 0: return
    if qv > 0:
        res = connection.execute(sa_text("UPDATE stock_levels SET reserved_quantity = reserved_quantity + :q WHERE id = :id AND (quantity - reserved_quantity) >= :q"), {"id": sid, "q": qv})
        if getattr(res, "rowcount", 0) != 1:
            raise ValueError("الكمية المتاحة غير كافية للحجز")
    else:
        connection.execute(sa_text("UPDATE stock_levels SET reserved_quantity = CASE WHEN reserved_quantity + :q < 0 THEN 0 ELSE reserved_quantity + :q END WHERE id = :id"), {"id": sid, "q": qv})

class Transfer(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'transfers'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False)
    destination_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    direction = db.Column(sa_str_enum(TransferDirection, name='transfer_direction'), nullable=False)
    transfer_date = db.Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    product = db.relationship('Product', back_populates='transfers')
    source_warehouse = db.relationship('Warehouse', foreign_keys=[source_id], back_populates='transfers_source')
    destination_warehouse = db.relationship('Warehouse', foreign_keys=[destination_id], back_populates='transfers_destination')
    user = db.relationship('User')
    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_transfer_qty_positive'),
        db.CheckConstraint('source_id <> destination_id', name='chk_transfer_diff_wh'),
    )
    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v or 0)
        if v <= 0: raise ValueError("الكمية يجب أن تكون أكبر من الصفر")
        return v
    def __repr__(self): return f"<Transfer {self.reference}>"

@event.listens_for(Transfer, 'before_insert', propagate=True)
def _ensure_transfer_reference(mapper, connection, target: "Transfer"):
    if getattr(target, 'reference', None): return
    prefix = datetime.now(timezone.utc).strftime("TRF%Y%m%d"); unique = uuid.uuid4().hex[:8].upper()
    target.reference = f"{prefix}-{unique}"

@event.listens_for(Transfer, "after_insert", propagate=True)
def _transfer_after_insert(mapper, connection, target: "Transfer"):
    if getattr(target, "_skip_stock_apply", False): return
    qty = int(target.quantity or 0)
    if qty <= 0: return
    _apply_stock_delta(connection, target.product_id, target.source_id, -qty)
    _apply_stock_delta(connection, target.product_id, target.destination_id, +qty)

@event.listens_for(Transfer, "after_update", propagate=True)
def _transfer_after_update(mapper, connection, target: "Transfer"):
    hist = inspect(target)
    def _old_new(attr):
        h = hist.attrs[attr].history
        old = h.deleted[0] if h.deleted else getattr(target, attr)
        new = h.added[0]   if h.added   else getattr(target, attr)
        return old, new
    touched = any(hist.attrs[a].history.has_changes() for a in ("product_id", "source_id", "destination_id", "quantity"))
    if not touched: return
    p_old, p_new = _old_new("product_id"); s_old, s_new = _old_new("source_id"); d_old, d_new = _old_new("destination_id"); q_old, q_new = _old_new("quantity")
    _apply_stock_delta(connection, int(p_old), int(s_old), +int(q_old or 0))
    _apply_stock_delta(connection, int(p_old), int(d_old), -int(q_old or 0))
    _apply_stock_delta(connection, int(p_new), int(s_new), -int(q_new or 0))
    _apply_stock_delta(connection, int(p_new), int(d_new), +int(q_new or 0))

@event.listens_for(Transfer, "after_delete", propagate=True)
def _transfer_after_delete(mapper, connection, target: "Transfer"):
    qty = int(target.quantity or 0)
    _apply_stock_delta(connection, target.product_id, target.source_id, +qty)
    _apply_stock_delta(connection, target.product_id, target.destination_id, -qty)

def _ex_dir_sign(direction: str) -> int:
    d = (getattr(direction, "value", direction) or "").upper()
    if d == "IN": return 1
    if d == "OUT": return -1
    if d == "ADJUSTMENT": return 1
    raise ValueError(f"Unknown exchange direction: {direction}")

class ExchangeTransaction(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'exchange_transactions'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'))
    quantity = db.Column(db.Integer, nullable=False)
    direction = db.Column(sa_str_enum(TransferDirection, name='exchange_direction'), default='IN', nullable=False, index=True, server_default=sa_text("'IN'"))
    unit_cost = db.Column(db.Numeric(12, 2))
    is_priced = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"))
    notes = db.Column(db.Text)
    product = db.relationship('Product', back_populates='exchange_transactions')
    warehouse = db.relationship('Warehouse', back_populates='exchange_transactions')
    supplier = db.relationship('Supplier')
    partner = db.relationship('Partner')
    gl_batches = db.relationship("GLBatch", primaryjoin="and_(foreign(GLBatch.source_id)==ExchangeTransaction.id, GLBatch.source_type=='EXCHANGE')", viewonly=True, order_by="GLBatch.id")
    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_exchange_qty_positive'),
        db.Index('ix_exchange_prod_wh', 'product_id', 'warehouse_id'),
        db.Index('ix_exchange_supplier', 'supplier_id'),
        db.Index('ix_exchange_supplier_dir_created_at', 'supplier_id', 'direction', 'created_at'),
        db.Index('ix_exchange_partner_dir_created_at', 'partner_id', 'direction', 'created_at'),
        CheckConstraint('unit_cost IS NULL OR unit_cost >= 0', name='ck_exchange_unit_cost_non_negative'),
    )
    @validates('direction')
    def _v_direction(self, _, v):
        return (getattr(v, 'value', v) or '').strip().upper()
    def __repr__(self): return f"<ExchangeTransaction P{self.product_id} W{self.warehouse_id} Q{self.quantity}>"

@event.listens_for(ExchangeTransaction, "before_insert")
@event.listens_for(ExchangeTransaction, "before_update")
def _xt_guard_and_price(mapper, connection, target: "ExchangeTransaction"):
    wh = connection.execute(sa_text("SELECT id, warehouse_type, supplier_id FROM warehouses WHERE id=:wid"), {"wid": target.warehouse_id}).mappings().first()
    if not wh: raise ValueError("Warehouse not found.")
    wt = (wh["warehouse_type"] or "").upper()
    
    # ملاحظة: المستودع ليس مرتبطاً بمورد محدد
    # المورد يُحدد في ExchangeTransaction نفسه (target.supplier_id)
    # لذلك نستخدم supplier_id من المعاملة وليس من المستودع
    if wt == WarehouseType.EXCHANGE.value:
        # إذا لم يكن supplier_id محدد في المعاملة، نستخدم من المستودع (إن وجد)
        if not target.supplier_id and wh["supplier_id"]:
            target.supplier_id = wh["supplier_id"]
    else:
        target.supplier_id = None
    
    uc = D(target.unit_cost or 0)
    if uc <= 0:
        price = connection.execute(sa_text("SELECT COALESCE(purchase_price,0) AS p FROM products WHERE id=:pid"), {"pid": target.product_id}).scalar() or 0
        target.unit_cost = q(price); target.is_priced = bool(D(price) > 0)
    else:
        target.unit_cost = q(uc); target.is_priced = True
    target.direction = (getattr(target.direction, "value", target.direction) or "").strip().upper()

@event.listens_for(ExchangeTransaction, "after_insert")
def _exchange_after_insert(mapper, connection, target: "ExchangeTransaction"):
    if getattr(target, "_skip_stock_apply", False): return
    delta = _ex_dir_sign(target.direction) * int(target.quantity or 0)
    if delta: _apply_stock_delta(connection, target.product_id, target.warehouse_id, delta)
    _maybe_post_gl_exchange(connection, target)
    if target.supplier_id:
        _queue_supplier_balance(target, target.supplier_id)

@event.listens_for(ExchangeTransaction, "after_update")
def _exchange_after_update(mapper, connection, target: "ExchangeTransaction"):
    hist = inspect(target)
    def old_new(attr):
        h = hist.attrs[attr].history
        old = h.deleted[0] if h.deleted else getattr(target, attr)
        new = h.added[0]   if h.added   else getattr(target, attr)
        return old, new
    p_old, p_new = old_new("product_id"); w_old, w_new = old_new("warehouse_id"); q_old, q_new = old_new("quantity"); d_old, d_new = old_new("direction")
    touched = any(hist.attrs[a].history.has_changes() for a in ("product_id","warehouse_id","quantity","direction"))
    if touched:
        undo_delta = -_ex_dir_sign(d_old) * int(q_old or 0)
        if undo_delta: _apply_stock_delta(connection, int(p_old), int(w_old), undo_delta)
        redo_delta = _ex_dir_sign(d_new) * int(q_new or 0)
        if redo_delta: _apply_stock_delta(connection, int(p_new), int(w_new), redo_delta)
    _maybe_post_gl_exchange(connection, target)
    supplier_id = target.supplier_id
    if not supplier_id and hist.attrs.get('supplier_id'):
        try:
            supplier_hist = hist.attrs['supplier_id'].history
            if supplier_hist.deleted:
                supplier_id = supplier_hist.deleted[0]
        except:
            pass
    if supplier_id:
        _queue_supplier_balance(target, supplier_id)

@event.listens_for(ExchangeTransaction, "after_delete")
def _exchange_after_delete(mapper, connection, target: "ExchangeTransaction"):
    delta = -_ex_dir_sign(target.direction) * int(target.quantity or 0)
    if delta: _apply_stock_delta(connection, target.product_id, target.warehouse_id, delta)
    if target.supplier_id:
        _queue_supplier_balance(target, target.supplier_id)

def _maybe_post_gl_exchange(connection, tx: "ExchangeTransaction"):
    try:
        from flask import current_app
        cfg = current_app.config or {}
    except Exception:
        cfg = {}
    if not bool(cfg.get("GL_AUTO_POST_ON_EXCHANGE", False)): return
    # استخدام الدالة من models.py مباشرة بدلاً من accounting module المفقود
    # GL_ACCOUNTS و _gl_upsert_batch_and_entries موجودين في نهاية models.py
    inv_acc  = (cfg.get("GL_EXCHANGE_INV_ACCOUNT")  or GL_ACCOUNTS.get("INV_EXCHANGE"))
    cogs_acc = (cfg.get("GL_EXCHANGE_COGS_ACCOUNT") or GL_ACCOUNTS.get("COGS_EXCHANGE"))
    ap_acc   = (cfg.get("GL_EXCHANGE_AP_ACCOUNT")   or GL_ACCOUNTS.get("AP"))
    if not inv_acc: return
    direction = (getattr(tx, "direction", "") or "").upper()
    qty = int(tx.quantity or 0)
    if qty <= 0: return
    unit_cost = D(tx.unit_cost or 0); amount = float(q(qty * unit_cost))
    if amount <= 0: return
    currency = (cfg.get("DEFAULT_CURRENCY") or "ILS")
    ref = f"EX-{tx.id}"; memo = f"Exchange {direction} P{tx.product_id} W{tx.warehouse_id} Q{qty}"
    if direction in ("IN", "ADJUSTMENT"):
        if not ap_acc: return
        entries = [(str(inv_acc).upper(), amount, 0.0), (str(ap_acc).upper(), 0.0, amount)]
        purpose = direction
    elif direction == "OUT":
        if not cogs_acc: return
        entries = [(str(cogs_acc).upper(), amount, 0.0), (str(inv_acc).upper(), 0.0, amount)]
        purpose = "OUT"
    else:
        return
    _gl_upsert_batch_and_entries(
        connection,
        source_type="EXCHANGE",
        source_id=int(tx.id),
        purpose=str(purpose).upper(),
        currency=str(currency).upper(),
        memo=memo,
        entries=entries,
        ref=ref,
        entity_type="SUPPLIER" if tx.supplier_id else None,
        entity_id=int(tx.supplier_id) if tx.supplier_id else None
    )

class WarehousePartnerShare(db.Model, TimestampMixin):
    __tablename__ = 'warehouse_partner_shares'
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), index=True, nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), index=True, nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), index=True, nullable=True)
    share_percentage = db.Column(db.Float, nullable=False, default=0.0)
    share_amount = db.Column(db.Numeric(12, 2), nullable=True)
    notes = db.Column(db.Text)
    partner = db.relationship('Partner', back_populates='shares', overlaps="product_shares,warehouse_shares,shares")
    warehouse = db.relationship('Warehouse', back_populates='partner_shares')
    product = db.relationship('Product', foreign_keys=[product_id], viewonly=True)
    __table_args__ = (
        db.UniqueConstraint('partner_id', 'warehouse_id', 'product_id', name='uq_wps_partner_wh_prod'),
        db.Index('ix_wps_partner_wh_prod', 'partner_id', 'warehouse_id', 'product_id'),
        db.Index('ix_wps_share_percentage', 'share_percentage'),
        CheckConstraint('share_percentage >= 0 AND share_percentage <= 100', name='ck_wps_share_percentage_range'),
        CheckConstraint('share_amount >= 0', name='ck_wps_share_amount_non_negative'),
    )
    def __repr__(self): return f"<WarehousePartnerShare partner={self.partner_id} warehouse={self.warehouse_id} product={self.product_id} {self.share_percentage}%>"

class ProductPartnerShare(db.Model):
    __table__ = WarehousePartnerShare.__table__
    partner = db.relationship('Partner', foreign_keys=[WarehousePartnerShare.partner_id], viewonly=True)
    warehouse = db.relationship('Warehouse', foreign_keys=[WarehousePartnerShare.warehouse_id], viewonly=True)
    product = db.relationship('Product', back_populates='partner_shares', foreign_keys=[WarehousePartnerShare.product_id])
    def __repr__(self): return f"<ProductPartnerShare partner={self.partner_id} warehouse={self.warehouse_id} product={self.product_id}>"

class ProductPartner(db.Model):
    __tablename__ = 'product_partners'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
    share_percent = db.Column(db.Float, nullable=False, default=0.0)
    share_amount = db.Column(db.Numeric(12, 2), nullable=True)
    notes = db.Column(db.Text)
    product = db.relationship('Product', back_populates='partners')
    partner = db.relationship('Partner', back_populates='product_links')
    __table_args__ = (
        db.CheckConstraint('share_percent >= 0 AND share_percent <= 100', name='chk_partner_share'),
        db.Index('ix_product_partner_pair', 'product_id', 'partner_id'),
        CheckConstraint('share_amount >= 0', name='ck_product_partner_share_amount_non_negative'),
    )
    def __repr__(self): return f"<ProductPartner {self.partner_id} {self.share_percent}%>"

class PreOrder(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'preorders'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, index=True)
    preorder_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expected_date = db.Column(db.DateTime)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    prepaid_amount = db.Column(db.Numeric(12, 2), default=0, server_default=sa_text("0"))
    tax_rate = db.Column(db.Numeric(5, 2), default=0, server_default=sa_text("0"))
    status = db.Column(sa_str_enum(PreOrderStatus, name='preorder_status'), default=PreOrderStatus.PENDING.value, nullable=False, index=True, server_default=sa_text("'PENDING'"))
    notes = db.Column(db.Text)
    payment_method = db.Column(sa_str_enum(PaymentMethod, name='preorder_payment_method'), default=PaymentMethod.CASH.value, nullable=False, server_default=sa_text("'cash'"))
    currency = db.Column(db.String(10), default='ILS', nullable=False, server_default=sa_text("'ILS'"))
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    refunded_total = db.Column(db.Numeric(12, 2), default=0, nullable=False, server_default=sa_text("0"))
    refund_of_id = db.Column(db.Integer, db.ForeignKey('preorders.id', ondelete='SET NULL'), index=True)
    idempotency_key = db.Column(db.String(64), unique=True, index=True)
    cancelled_at = db.Column(db.DateTime, index=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    cancel_reason = db.Column(db.String(200))
    customer = db.relationship('Customer', back_populates='preorders')
    supplier = db.relationship('Supplier', back_populates='preorders')
    partner = db.relationship('Partner', back_populates='preorders')
    product = db.relationship('Product', back_populates='preorders')
    warehouse = db.relationship('Warehouse', back_populates='preorders')
    cancelled_by_user = db.relationship('User', foreign_keys=[cancelled_by])
    refund_of = db.relationship('PreOrder', remote_side=[id])
    payments = db.relationship('Payment', back_populates='preorder', cascade='all, delete-orphan')
    sale = db.relationship('Sale', back_populates='preorder', uselist=False)
    invoice = db.relationship('Invoice', back_populates='preorder', uselist=False)
    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_preorder_quantity_positive'),
        db.CheckConstraint('prepaid_amount >= 0', name='chk_preorder_prepaid_non_negative'),
        db.CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='chk_preorder_tax_rate'),
        db.CheckConstraint('refunded_total >= 0', name='chk_preorder_refunded_total_non_negative'),
        db.Index('ix_preorders_cust_status', 'customer_id', 'status'),
        db.Index('ix_preorders_partner_status', 'partner_id', 'status'),
        db.Index('ix_preorders_supplier_status', 'supplier_id', 'status'),
        db.Index('ix_preorders_prod_wh', 'product_id', 'warehouse_id'),
        db.Index('ix_preorders_date_status', 'preorder_date', 'status'),
        db.Index('ix_preorders_pay_method', 'payment_method'),
        db.Index('ix_preorders_prepaid', 'prepaid_amount'),
    )
    @property
    def reservation_code(self): return self.reference
    @reservation_code.setter
    def reservation_code(self, v): self.reference = v
    @validates('quantity')
    def _v_qty(self, _, v):
        i = int(v or 0)
        if i <= 0: raise ValueError('quantity must be > 0')
        return i
    @validates('prepaid_amount', 'refunded_total')
    def _v_money(self, _, v):
        if v in (None, ''): return D('0.00')
        dv = q(v)
        if dv < 0: raise ValueError('amount must be >= 0')
        return dv
    @validates('currency')
    def _v_curr(self, _, v): return ensure_currency(v or DEFAULT_CURRENCY)
    @hybrid_property
    def total_before_tax(self):
        price = D(getattr(self.product, "price", 0)); qty = D(self.quantity or 0)
        return qty * price
    @total_before_tax.expression
    def total_before_tax(cls):
        return (select(func.coalesce(Product.price, 0) * cls.quantity).select_from(Product).where(Product.id == cls.product_id).scalar_subquery())
    @hybrid_property
    def total_with_tax(self):
        base = D(self.total_before_tax); tr = D(self.tax_rate or 0)
        return base * (Decimal("1") + tr / Decimal("100"))
    @total_with_tax.expression
    def total_with_tax(cls):
        base = (select(func.coalesce(Product.price, 0) * cls.quantity).select_from(Product).where(Product.id == cls.product_id).scalar_subquery())
        return base * (1 + (func.coalesce(cls.tax_rate, 0) / 100.0))
    @hybrid_property
    def total_amount(self): return self.total_with_tax
    @total_amount.expression
    def total_amount(cls): return cls.total_with_tax
    @hybrid_property
    def total_paid(self):
        return float(
            db.session.query(func.coalesce(func.sum(Payment.total_amount), 0))
            .filter(
                Payment.preorder_id == self.id,
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.direction == PaymentDirection.IN.value
            )
            .scalar() or 0
        )
    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.preorder_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.IN.value)
            )
            .scalar_subquery()
        )
    @hybrid_property
    def balance_due(self): return D(self.total_amount) - D(self.total_paid or 0)
    @balance_due.expression
    def balance_due(cls):
        total_expr = (
            select((Product.price * cls.quantity) * (1 + (func.coalesce(cls.tax_rate, 0) / 100.0)))
            .select_from(Product)
            .where(Product.id == cls.product_id)
            .scalar_subquery()
        )
        paid_expr = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.preorder_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.IN.value)
            )
            .scalar_subquery()
        )
        return total_expr - paid_expr
    @hybrid_property
    def net_balance(self): return self.balance_due
    @hybrid_property
    def refundable_amount(self): return float(q(self.prepaid_amount or 0) - q(self.refunded_total or 0))
    def can_refund(self, amount): amt = q(amount or 0); return amt > 0 and amt <= q(self.refundable_amount)
    def apply_refund(self, amount):
        if not self.can_refund(amount): raise ValueError("preorder.refund_exceeds_allowed")
        self.refunded_total = q(self.refunded_total or 0) + q(amount or 0)
    def cancel(self, by_user_id: int | None = None, reason: str | None = None):
        self.cancelled_at = datetime.now(timezone.utc); self.cancelled_by = by_user_id; self.cancel_reason = (reason or None); self.status = PreOrderStatus.CANCELLED.value
    def __repr__(self): return f"<PreOrder {self.reference or self.id}>"

_ALLOWED_PREORDER_TRANSITIONS = {
    PreOrderStatus.PENDING.value: {PreOrderStatus.CONFIRMED.value, PreOrderStatus.CANCELLED.value, PreOrderStatus.FULFILLED.value},
    PreOrderStatus.CONFIRMED.value: {PreOrderStatus.FULFILLED.value, PreOrderStatus.CANCELLED.value},
    PreOrderStatus.FULFILLED.value: set(),
    PreOrderStatus.CANCELLED.value: set()
}

@event.listens_for(PreOrder, 'before_insert')
def _preorder_before_insert(mapper, connection, target):
    if not getattr(target, 'reference', None):
        prefix = datetime.now(timezone.utc).strftime("PRE%Y%m%d"); unique = uuid.uuid4().hex[:8].upper()
        target.reference = f"{prefix}-{unique}"
    target.currency = ensure_currency(target.currency or DEFAULT_CURRENCY)

@event.listens_for(PreOrder, 'before_update')
def _preorder_before_update(mapper, connection, target):
    from sqlalchemy.orm.attributes import get_history
    target.currency = ensure_currency(target.currency or DEFAULT_CURRENCY)
    h = get_history(target, "status")
    oldv = (getattr(h, "deleted", None) or [getattr(target, "status", None)])[0]
    newv = getattr(target, "status", None)
    o = (getattr(oldv, "value", oldv) or "PENDING"); n = getattr(newv, "value", newv)
    if o != n:
        allowed = _ALLOWED_PREORDER_TRANSITIONS.get(o, set())
        if n not in allowed: raise ValueError("preorder.invalid_status_transition")

# ===== إنشاء قيود GL تلقائية للحجوزات =====
def _preorder_gl_upsert_core(connection, target: "PreOrder") -> None:
    """منطق إنشاء/تحديث قيد GL للحجز (يُستدعى من معاملة منفصلة بعد commit)."""
    if hasattr(target, "_skip_gl_entry") and target._skip_gl_entry:
        return
    status_val = getattr(target, "status", None)
    status_val = getattr(status_val, "value", status_val)
    if status_val == "CANCELLED" or (hasattr(target, "cancelled_at") and target.cancelled_at):
        prepaid = float(target.prepaid_amount or 0)
        if prepaid <= 0:
            return
        amount_ils = prepaid
        if target.currency and target.currency != "ILS":
            try:
                rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.preorder_date or datetime.now(timezone.utc))
                if rate and rate > 0:
                    amount_ils = float(prepaid * float(rate))
            except Exception:
                pass
        ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
        advance_account = GL_ACCOUNTS.get("ADVANCE", "2300_ADV_PAY")
        entries = [(advance_account, amount_ils, 0), (ar_account, 0, amount_ils)]
        _gl_upsert_batch_and_entries(
            connection,
            source_type="PREORDER_REVERSAL",
            source_id=target.id,
            purpose="REVERSAL",
            currency="ILS",
            memo=f"Reversal - cancelled preorder #{target.id}",
            entries=entries,
            ref=f"REV-PRE-{target.id}",
            entity_type="CUSTOMER",
            entity_id=target.customer_id,
        )
        return
    prepaid = float(target.prepaid_amount or 0)
    if prepaid <= 0:
        return
    payment_check = connection.execute(
        sa_text("""
            SELECT COUNT(1) FROM payments
            WHERE preorder_id = :pid AND status = :status AND direction = :direction
        """),
        {"pid": target.id, "status": PaymentStatus.COMPLETED.value, "direction": PaymentDirection.IN.value},
    ).scalar() or 0
    if payment_check > 0:
        return
    amount_ils = prepaid
    if target.currency and target.currency != "ILS":
        try:
            rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.preorder_date or datetime.now(timezone.utc))
            if rate and rate > 0:
                amount_ils = float(prepaid * float(rate))
        except Exception:
            pass
    ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
    advance_account = GL_ACCOUNTS.get("ADVANCE", "2300_ADV_PAY")
    entries = [(ar_account, amount_ils, 0), (advance_account, 0, amount_ils)]
    _gl_upsert_batch_and_entries(
        connection,
        source_type="PREORDER",
        source_id=target.id,
        purpose="PREORDER",
        currency="ILS",
        memo=f"Preorder - {target.reference or target.id}",
        entries=entries,
        ref=target.reference or f"PRE-{target.id}",
        entity_type="CUSTOMER" if target.customer_id else "SUPPLIER",
        entity_id=target.customer_id or target.supplier_id,
    )


def run_preorder_gl_sync_after_commit(preorder_id: int) -> None:
    """إنشاء/تحديث قيد GL للحجز في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not preorder_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session
        session = Session(db.engine)
        try:
            pre = session.get(PreOrder, preorder_id)
            if not pre:
                return
            _preorder_gl_upsert_core(session.connection(), pre)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        if current_app:
            current_app.logger.warning("PreOrder GL sync failed for preorder_id=%s: %s", preorder_id, e, exc_info=True)


@event.listens_for(PreOrder, "after_insert")
@event.listens_for(PreOrder, "after_update")
def _preorder_gl_batch_upsert(mapper, connection, target: "PreOrder"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_preorder_gl_sync_after_commit."""
    return

@event.listens_for(PreOrder, "after_update")
def _preorder_reservation_flow(mapper, connection, target: "PreOrder"):
    if getattr(target, "_skip_reservation_flow", False):
        return
    hist = inspect(target); h = hist.attrs['status'].history
    old_status = (h.deleted[0] if h.deleted else getattr(target, "status", "") or "").upper()
    new_status = (h.added[0] if h.added else getattr(target, "status", "") or "").upper()
    if old_status == new_status: return
    wid = getattr(target, "warehouse_id", None); pid = getattr(target, "product_id", None); qty = int(getattr(target, "quantity", 0) or 0)
    if not (wid and pid and qty > 0): return
    if new_status == "CONFIRMED" and old_status != "CONFIRMED":
        try: _apply_reservation_delta(connection, pid, wid, +qty)
        except Exception: pass
    elif new_status == "FULFILLED":
        try:
            _apply_reservation_delta(connection, pid, wid, -qty)
            _apply_stock_delta(connection, pid, wid, -qty)
        except Exception: pass
    elif old_status == "CONFIRMED" and new_status != "CONFIRMED":
        try: _apply_reservation_delta(connection, pid, wid, -qty)
        except Exception: pass

class Sale(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    sale_number = db.Column(db.String(50), unique=True, index=True)
    sale_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    seller_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    preorder_id = db.Column(db.Integer, db.ForeignKey("preorders.id"), index=True)

    tax_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    discount_total = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.Text)
    receiver_name = db.Column(db.String(200))  # اسم مستلم البضاعة

    status = db.Column(sa_str_enum(SaleStatus, name="sale_status"), default=SaleStatus.DRAFT.value, nullable=False, index=True)
    payment_status = db.Column(sa_str_enum(PaymentProgress, name="sale_payment_progress"), default=PaymentProgress.PENDING.value, nullable=False, index=True)

    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    shipping_address = db.Column(db.Text)
    billing_address = db.Column(db.Text)
    shipping_cost = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_paid = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    balance_due = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    refunded_total = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    refund_of_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="SET NULL"), index=True)
    idempotency_key = db.Column(db.String(64), unique=True, index=True)

    stock_deducted = db.Column(db.Boolean, default=False, nullable=False)

    cancelled_at = db.Column(db.DateTime, index=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    cancel_reason = db.Column(db.String(200))
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"), index=True)

    customer = db.relationship("Customer", back_populates="sales")
    cost_center = db.relationship("CostCenter", backref=db.backref("sales", lazy="dynamic"))
    seller = db.relationship("User", back_populates="sales", foreign_keys=[seller_id])
    seller_employee = db.relationship("Employee", foreign_keys=[seller_employee_id])
    cancelled_by_user = db.relationship("User", back_populates="cancelled_sales", foreign_keys=[cancelled_by])
    archived_by_user = db.relationship("User", foreign_keys=[archived_by])
    preorder = db.relationship("PreOrder", back_populates="sale")
    refund_of = db.relationship("Sale", remote_side=[id])

    lines = db.relationship("SaleLine", back_populates="sale", cascade="all,delete-orphan", order_by="SaleLine.id")
    payments = db.relationship("Payment", back_populates="sale", cascade="all,delete-orphan", order_by="Payment.id")
    invoice = db.relationship("Invoice", back_populates="sale", uselist=False)
    shipments = db.relationship("Shipment", back_populates="sale", cascade="all,delete-orphan", order_by="Shipment.id")

    gl_batches = db.relationship("GLBatch", primaryjoin="and_(foreign(GLBatch.source_id)==Sale.id, GLBatch.source_type=='SALE')", viewonly=True, order_by="GLBatch.id")

    __table_args__ = (
        db.CheckConstraint("discount_total >= 0", name="ck_sale_discount_non_negative"),
        db.CheckConstraint("shipping_cost >= 0", name="ck_sale_shipping_cost_non_negative"),
        db.CheckConstraint("total_amount >= 0", name="ck_sale_total_amount_non_negative"),
        db.CheckConstraint("total_paid >= 0", name="ck_sale_total_paid_non_negative"),
        # السماح بـ balance_due سالب للمبيعات للموردين/الشركاء
        # db.CheckConstraint("balance_due >= 0", name="ck_sale_balance_due_non_negative"),
        db.CheckConstraint("refunded_total >= 0", name="ck_sale_refunded_total_non_negative"),
        db.Index("ix_sales_customer_status_date", "customer_id", "status", "sale_date"),
        db.Index("ix_sales_payment_status_date", "payment_status", "sale_date"),
        db.Index("ix_sales_seller_date", "seller_id", "sale_date"),
        db.Index("ix_sales_archived", "is_archived", "archived_at"),
        db.Index("ix_sales_total_amount", "total_amount"),
        db.Index("ix_sales_balance_due", "balance_due"),
    )

    @hybrid_property
    def subtotal(self):
        return sum(D(l.net_amount) for l in (self.lines or [])) if self.lines else Decimal("0.00")

    @hybrid_property
    def tax_amount(self):
        base = D(self.subtotal) - D(self.discount_total or 0) + D(self.shipping_cost or 0)
        return base * D(self.tax_rate or 0) / Decimal("100.0")

    @hybrid_property
    def total(self):
        """المجموع المحسوب ديناميكياً من بنود المبيعة (subtotal - discount + shipping + tax).
        يختلف عن total_amount المخزّن في قاعدة البيانات الذي يُحدَّث عبر event listener."""
        return (D(self.subtotal) - D(self.discount_total or 0) + D(self.shipping_cost or 0)) + D(self.tax_amount)

    @hybrid_property
    def refundable_amount(self):
        return float(q(self.total_amount or 0) - q(self.refunded_total or 0))

    def can_refund(self, amount: Decimal | float | int) -> bool:
        amt = q(amount or 0)
        return amt > 0 and amt <= q(self.refundable_amount)

    def apply_refund(self, amount: Decimal | float | int):
        if not self.can_refund(amount):
            raise ValueError("sale.refund_exceeds_allowed")
        self.refunded_total = q(self.refunded_total or 0) + q(amount or 0)
        if q(self.refunded_total) >= q(self.total_amount or 0):
            self.status = SaleStatus.REFUNDED.value

    def cancel(self, by_user_id: int | None = None, reason: str | None = None):
        self.status = SaleStatus.CANCELLED.value
        self.cancelled_at = datetime.now(timezone.utc)
        self.cancelled_by = by_user_id
        self.cancel_reason = (reason or None)

    def reserve_stock(self):
        for l in (self.lines or []):
            lvl = (
                StockLevel.query.filter_by(product_id=l.product_id, warehouse_id=l.warehouse_id)
                .with_for_update()
                .first()
            )
            if not lvl:
                raise Exception("لا يوجد صف مخزون لهذا المنتج/المستودع")
            available = int(lvl.quantity or 0) - int(lvl.reserved_quantity or 0)
            need = int(l.quantity or 0)
            if available < need:
                raise Exception("الكمية المتاحة للحجز غير كافية في هذا المستودع")
            lvl.reserved_quantity = int(lvl.reserved_quantity or 0) + need

    def release_stock(self):
        for l in (self.lines or []):
            lvl = (
                StockLevel.query.filter_by(product_id=l.product_id, warehouse_id=l.warehouse_id)
                .with_for_update()
                .first()
            )
            if lvl:
                need = int(l.quantity or 0)
                cur = int(lvl.reserved_quantity or 0)
                lvl.reserved_quantity = max(0, cur - need)

    def update_payment_status(self):
        """تحديث حالة الدفع وحساب المبلغ المدفوع من الدفعات المرتبطة"""
        from sqlalchemy import func
        from decimal import Decimal as D
        
        sale_currency = (self.currency or DEFAULT_CURRENCY).upper()
        payments = db.session.query(Payment).options(
            joinedload(Payment.splits)
        ).filter(
            Payment.sale_id == self.id,
            Payment.status == PaymentStatus.COMPLETED,
            Payment.direction == PaymentDirection.IN
        ).all()
        
        total_paid = D('0.00')
        
        for payment in payments:
            splits = payment.splits if hasattr(payment, 'splits') else []
            
            if splits:
                payment_checks = db.session.query(Check).filter(
                    Check.payment_id == payment.id,
                    Check.status.in_(['RETURNED', 'BOUNCED'])
                ).all()
                
                returned_check_amounts = {}
                for check in payment_checks:
                    if check.reference_number and 'PMT-SPLIT-' in check.reference_number:
                        try:
                            split_id = int(check.reference_number.split('PMT-SPLIT-')[1].split('-')[0])
                            returned_check_amounts[split_id] = D(str(check.amount or 0))
                        except:
                            pass
                    elif check.check_number:
                        for split in splits:
                            split_details = split.details or {}
                            if isinstance(split_details, str):
                                try:
                                    split_details = json.loads(split_details)
                                except:
                                    split_details = {}
                            if split_details.get('check_number') == check.check_number:
                                returned_check_amounts[split.id] = D(str(check.amount or 0))
                                break
                
                for split in splits:
                    split_amt = D(str(split.amount or 0))
                    
                    if split.id in returned_check_amounts:
                        returned_amount = returned_check_amounts[split.id]
                        if split_amt > returned_amount:
                            split_amt = split_amt - returned_amount
                        else:
                            split_amt = D('0.00')
                    
                    if split_amt > 0:
                        if (split.currency or sale_currency).upper() == sale_currency:
                            total_paid += split_amt
                        else:
                            try:
                                from models import convert_amount
                                total_paid += D(str(convert_amount(split_amt, split.currency, sale_currency, payment.payment_date)))
                            except Exception as fx_err:
                                import logging
                                logging.getLogger(__name__).warning(
                                    f"فشل تحويل العملة من {split.currency} إلى {sale_currency} "
                                    f"للدفعة {payment.id} (split {split.id}): {fx_err}"
                                )
            else:
                amt = D(str(payment.total_amount or 0))
                if (payment.currency or sale_currency).upper() == sale_currency:
                    total_paid += amt
                else:
                    try:
                        from models import convert_amount
                        total_paid += D(str(convert_amount(amt, payment.currency, sale_currency, payment.payment_date)))
                    except Exception as fx_err:
                        import logging
                        logging.getLogger(__name__).warning(
                            f"فشل تحويل العملة من {payment.currency} إلى {sale_currency} "
                            f"للدفعة {payment.id}: {fx_err}"
                        )
        
        # كمّي رصيد المدفوع والمتبقي وفق عملة الفاتورة
        self.total_paid = float(q(total_paid))
        total_amount = float(q(self.total_amount or self.total or 0))
        self.balance_due = float(q(total_amount) - q(self.total_paid))
        
        self.payment_status = (
            PaymentProgress.PAID.value if q(self.total_paid) >= q(total_amount)
            else PaymentProgress.PARTIAL.value if self.total_paid > 0
            else PaymentProgress.PENDING.value
        )
        
        if self.status == SaleStatus.DRAFT.value and self.total_paid > 0:
            self.status = SaleStatus.CONFIRMED.value

    @validates("currency")
    def _v_currency(self, _, v):
        return ensure_currency(v or "ILS")

    @validates("tax_rate", "discount_total", "shipping_cost", "total_amount", "total_paid", "balance_due", "refunded_total")
    def _v_amounts(self, key, v):
        dv = q(v or 0)
        if key == "tax_rate" and (dv < 0 or dv > 100):
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        if key == "balance_due" and dv < 0:
            return q(0)
        if dv < 0:
            field_names = {
                "discount_total": "الخصم",
                "shipping_cost": "تكلفة الشحن",
                "total_amount": "المبلغ الإجمالي",
                "total_paid": "المبلغ المدفوع",
                "balance_due": "المبلغ المستحق",
                "refunded_total": "المبلغ المسترد"
            }
            raise ValueError(f"{field_names.get(key, key)} لا يمكن أن يكون سالباً")
        return dv

    def __repr__(self):
        return f"<Sale {self.sale_number}>"

@event.listens_for(Sale, "before_insert")
def _sale_before_insert_ref(mapper, connection, target: "Sale"):
    if not getattr(target, "sale_number", None):
        prefix = datetime.now(timezone.utc).strftime("SAL%Y%m%d")
        count = connection.execute(sa_text("SELECT COUNT(*) FROM sales WHERE sale_number LIKE :pfx"), {"pfx": f"{prefix}-%"}).scalar() or 0
        target.sale_number = f"{prefix}-{count+1:04d}"
    
    # حفظ سعر الصرف تلقائياً للمبيعات (فقط عند الإنشاء)
    sale_currency = target.currency or DEFAULT_CURRENCY
    default_currency = DEFAULT_CURRENCY
    
    if sale_currency != default_currency:
        try:
            at = getattr(target, "sale_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, sale_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = sale_currency
                target.fx_quote_currency = DEFAULT_CURRENCY
        except Exception:
            pass

@event.listens_for(Sale, "before_insert")
@event.listens_for(Sale, "before_update")
def _compute_total_amount(mapper, connection, target: "Sale"):
    subtotal = sum(q(l.net_amount) for l in (target.lines or []))
    discount = q(target.discount_total)
    tax_rate = q(target.tax_rate)
    shipping = q(target.shipping_cost)
    base = subtotal - discount + shipping
    if base < 0:
        base = Decimal("0.00")
    tax = q(base * tax_rate / Decimal("100"))
    total = base + tax
    if total < 0:
        total = Decimal("0.00")
    target.total_amount = q(total)
    target.balance_due = q(target.total_amount or 0) - q(target.total_paid or 0)

@event.listens_for(Sale, "before_update")
def _sale_enforce_status(mapper, connection, target: "Sale"):
    from sqlalchemy.orm.attributes import get_history
    h = get_history(target, "status")
    oldv = (getattr(h, "deleted", None) or [getattr(target, "status", None)])[0]
    newv = getattr(target, "status", None)
    o = (getattr(oldv, "value", oldv) or SaleStatus.DRAFT.value)
    n = getattr(newv, "value", newv)
    if o != n:
        allowed = _ALLOWED_SALE_TRANSITIONS.get(o, set())
        if n not in allowed:
            raise ValueError("sale.invalid_status_transition")

@event.listens_for(Sale.status, "set")
def _reserve_release_on_status_change(target, value, oldvalue, initiator):
    """
    تم تعطيل نظام الحجز - الخصم يتم مباشرة عند الدفع
    """
    newv = getattr(value, "value", value)
    oldv = getattr(oldvalue, "value", oldvalue)
    if newv == SaleStatus.CONFIRMED.value and oldv != SaleStatus.CONFIRMED.value:
        # التحقق من حد الائتمان فقط
        if target.customer and float(target.customer.credit_limit or 0) > 0:
            cur_bal = float(target.customer.balance or 0)
            new_total = float(getattr(target, "total", None) or getattr(target, "total_amount", 0) or 0)
            if cur_bal + new_total > float(target.customer.credit_limit or 0):
                raise Exception("تأكيد البيع مرفوض: حد الائتمان للعميل سيتجاوز المسموح.")
        # تم تعطيل: target.reserve_stock()
    # elif oldv == SaleStatus.CONFIRMED.value and newv != SaleStatus.CONFIRMED.value:
        # تم تعطيل: target.release_stock()


# ═══════════════════════════════════════════════════════════════════════
# 📊 Accounting Listeners - إنشاء GLBatch تلقائي للمبيعات
# ═══════════════════════════════════════════════════════════════════════

@event.listens_for(Sale, "after_insert")
@event.listens_for(Sale, "after_update")
def _sale_clear_balance_cache(mapper, connection, target: "Sale"):
    try:
        from extensions import cache
        if target.customer_id:
            cache.delete(f"customer_balance_{target.customer_id}")
            cache.delete(f"entity_balance_CUSTOMER_{target.customer_id}")
    except Exception:
        pass

@event.listens_for(Sale, "after_insert")
@event.listens_for(Sale, "after_update")
def _sale_create_tax_entry(mapper, connection, target: "Sale"):
    """إنشاء/تحديث سجل ضريبي للبيع تلقائياً"""
    if target.status != SaleStatus.CONFIRMED.value:
        return
    
    tax_rate = float(target.tax_rate or 0)
    if tax_rate <= 0:
        return
    
    try:
        from sqlalchemy import select as sa_select, delete as sa_delete, insert as sa_insert
        
        sale_date = target.sale_date or datetime.now(timezone.utc)
        subtotal = sum(float(l.net_amount or 0) for l in (target.lines or []))
        discount = float(target.discount_total or 0)
        shipping = float(target.shipping_cost or 0)
        base_amount = max(subtotal - discount + shipping, 0)
        tax_amount = base_amount * (tax_rate / 100.0)
        total_amount = base_amount + tax_amount
        
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SALE',
                TaxEntry.transaction_id == target.id
            )
        )
        
        connection.execute(
            sa_insert(TaxEntry).values(
                entry_type='OUTPUT_VAT',
                transaction_type='SALE',
                transaction_id=target.id,
                transaction_reference=target.sale_number,
                tax_rate=tax_rate,
                base_amount=base_amount,
                tax_amount=tax_amount,
                total_amount=total_amount,
                currency=target.currency or DEFAULT_CURRENCY,
                fiscal_year=sale_date.year,
                fiscal_month=sale_date.month,
                tax_period=f"{sale_date.year}-{sale_date.month:02d}",
                customer_id=target.customer_id,
                notes=f'بيع: {target.sale_number}',
                created_at=datetime.now(timezone.utc)
            )
        )
    except Exception:
        pass

@event.listens_for(Sale, "before_delete")
def _sale_delete_tax_entry(mapper, connection, target: "Sale"):
    """حذف سجل الضريبة عند حذف البيع"""
    try:
        from sqlalchemy import delete as sa_delete
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SALE',
                TaxEntry.transaction_id == target.id
            )
        )
    except Exception:
        pass

def _sale_gl_upsert_core(connection, target: "Sale") -> None:
    """منطق إنشاء/تحديث قيد GL للبيع (يُستدعى من معاملة منفصلة بعد commit)."""
    from decimal import Decimal, ROUND_HALF_UP
    from sqlalchemy import select as sa_select
    if target.status != SaleStatus.CONFIRMED.value:
        return
    amount = Decimal(str(target.total_amount or 0))
    if amount <= 0:
        return
    amount_ils = amount
    exchange_rate = Decimal(1)
    if target.currency and target.currency != DEFAULT_CURRENCY:
        try:
            rate = _fx_rate_local_via_connection(connection, target.currency, DEFAULT_CURRENCY, target.sale_date or datetime.now(timezone.utc))
            if rate and rate > 0:
                exchange_rate = Decimal(str(rate))
                amount_ils = amount * exchange_rate
        except Exception:
            pass
    # Modified Query to include purchase_price for COGS calculation
    sale_lines = connection.execute(
        sa_text("""
            SELECT sl.id, sl.product_id, sl.warehouse_id, sl.quantity, sl.unit_price, 
                   sl.discount_rate, sl.tax_rate, p.purchase_price
            FROM sale_lines sl
            JOIN products p ON p.id = sl.product_id
            WHERE sl.sale_id = :sid
        """),
        {"sid": target.id}
    ).fetchall()

    if not sale_lines:
        return
    entries = []
    def _q2(v: Decimal) -> Decimal:
        return (v or Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    global_discount = _q2(Decimal(str(target.discount_total or 0)) * exchange_rate)
    shipping_income = _q2(Decimal(str(target.shipping_cost or 0)) * exchange_rate)
    total_revenue_partners = {}
    total_cogs_suppliers = {}
    total_cogs_inventory = Decimal(0) # New: Track inventory COGS
    line_details = []
    subtotal_base_ils = Decimal(0)
    total_tax_ils = Decimal(0)
    for line in sale_lines:
        line_id, product_id, warehouse_id, qty, unit_price, disc_rate, tax_rate, purchase_price = line
        gross = Decimal(str(qty or 0)) * Decimal(str(unit_price or 0))
        discount = gross * (Decimal(str(disc_rate or 0)) / Decimal(100))
        taxable = gross - discount
        tax = taxable * (Decimal(str(tax_rate or 0)) / Decimal(100))
        line_base_ils = taxable * exchange_rate
        line_tax_ils = tax * exchange_rate
        line_total = line_base_ils + line_tax_ils
        subtotal_base_ils += line_base_ils
        total_tax_ils += line_tax_ils
        
        unit_cost_ils = Decimal(str(purchase_price or 0))
        line_details.append(
            (product_id, warehouse_id, qty, line_base_ils, line_total, unit_cost_ils)
        )
    for product_id, warehouse_id, qty, line_base_ils, line_total, unit_cost_ils in line_details:
        cogs_amount = Decimal(str(qty or 0)) * unit_cost_ils
        wh_result = connection.execute(
            sa_text("SELECT warehouse_type, partner_id, supplier_id, share_percent FROM warehouses WHERE id = :wid"),
            {"wid": warehouse_id},
        ).fetchone()
        if wh_result:
            wh_type, wh_partner_id, wh_supplier_id, wh_share_pct = wh_result
        else:
            wh_type = None
        if wh_type == 'PARTNER':
            partners_result = connection.execute(
                sa_text("SELECT partner_id, share_percent FROM product_partners WHERE product_id = :pid"),
                {"pid": product_id},
            ).fetchall()
            if not partners_result:
                partners_result = connection.execute(
                    sa_text("SELECT partner_id, share_percentage FROM warehouse_partner_shares WHERE product_id = :pid"),
                    {"pid": product_id},
                ).fetchall()
            if not partners_result and warehouse_id:
                partners_result = connection.execute(
                    sa_text(
                        "SELECT partner_id, share_percentage FROM warehouse_partner_shares WHERE warehouse_id = :wid AND product_id IS NULL"
                    ),
                    {"wid": warehouse_id},
                ).fetchall()
            if partners_result:
                if subtotal_base_ils > 0:
                    allocated_discount = (line_base_ils / subtotal_base_ils) * global_discount
                else:
                    allocated_discount = Decimal(0)
                line_base_after_discount = line_base_ils - allocated_discount
                if line_base_after_discount < 0:
                    line_base_after_discount = Decimal(0)
                for partner_id, share_pct in partners_result:
                    partner_amount = line_base_after_discount * (Decimal(str(share_pct or 0)) / Decimal(100))
                    total_revenue_partners[partner_id] = total_revenue_partners.get(partner_id, Decimal(0)) + partner_amount
            
            # Add COGS for Partner Warehouse
            total_cogs_inventory += cogs_amount
        elif wh_type == 'EXCHANGE':
            exchange_result = connection.execute(
                sa_text("""
                    SELECT supplier_id, unit_cost FROM exchange_transactions
                    WHERE product_id = :pid AND warehouse_id = :wid AND supplier_id IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"pid": product_id, "wid": warehouse_id},
            ).fetchone()
            if exchange_result:
                supplier_id, unit_cost = exchange_result
                # Note: Using unit_cost from exchange table for supplier COGS
                ex_cogs_amount = Decimal(str(qty or 0)) * Decimal(str(unit_cost or 0))
                total_cogs_suppliers[supplier_id] = total_cogs_suppliers.get(supplier_id, Decimal(0)) + ex_cogs_amount
            else:
                total_cogs_inventory += cogs_amount
        else:
            # Normal Warehouse
            total_cogs_inventory += cogs_amount
    total_revenue_company_base = _q2(subtotal_base_ils)
    total_revenue_company_tax = _q2(total_tax_ils)
    total_credits = _q2(total_revenue_company_base + total_revenue_company_tax + shipping_income)
    ar_amount = _q2(total_credits - global_discount)
    if ar_amount <= 0:
        return
    entries.append((GL_ACCOUNTS.get("AR", "1100_AR"), ar_amount, Decimal(0)))
    if global_discount > 0:
        entries.append((GL_ACCOUNTS.get("DISCOUNT_ALLOWED", "4050_SALES_DISCOUNT"), global_discount, Decimal(0)))
    if shipping_income > 0:
        entries.append((GL_ACCOUNTS.get("SHIPPING_INCOME", "4200_SHIPPING_INCOME"), Decimal(0), shipping_income))
    if total_revenue_company_base > 0:
        entries.append((GL_ACCOUNTS.get("REV", "4000_SALES"), Decimal(0), total_revenue_company_base))
    if total_revenue_company_tax > 0:
        entries.append((GL_ACCOUNTS.get("VAT", "2100_VAT_PAYABLE"), Decimal(0), total_revenue_company_tax))
    for supplier_id, cogs in total_cogs_suppliers.items():
        cogs_amt = _q2(Decimal(cogs))
        if cogs_amt > 0:
            entries.append((GL_ACCOUNTS.get("COGS", "5100_COGS"), cogs_amt, Decimal(0)))
            entries.append((GL_ACCOUNTS.get("AP", "2000_AP"), Decimal(0), cogs_amt))
            
    # 7. COGS for Normal/Partner Warehouses (Debit COGS / Credit Inventory)
    total_cogs_inv_amt = _q2(total_cogs_inventory)
    if total_cogs_inv_amt > 0:
        entries.append((GL_ACCOUNTS.get("COGS", "5100_COGS"), total_cogs_inv_amt, Decimal(0)))
        entries.append((GL_ACCOUNTS.get("INVENTORY", "1200_INVENTORY"), Decimal(0), total_cogs_inv_amt))
    customer_name = getattr(getattr(target, "customer", None), "name", None) or "Customer"
    memo = f"Sale #{target.sale_number or target.id} - {customer_name}"
    batch_ids = connection.execute(
        sa_text("SELECT id FROM gl_batches WHERE source_type = 'SALE' AND source_id = :sid AND purpose = 'REVENUE'"),
        {"sid": target.id},
    ).fetchall()
    for (bid,) in batch_ids:
        connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": int(bid)})
        connection.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": int(bid)})
    _gl_upsert_batch_and_entries(
        connection,
        source_type="SALE",
        source_id=target.id,
        purpose="REVENUE",
        currency=DEFAULT_CURRENCY,
        memo=memo,
        entries=entries,
        ref=target.sale_number or f"SALE-{target.id}",
        entity_type="CUSTOMER",
        entity_id=target.customer_id,
    )

    batch_ids_ps = connection.execute(
        sa_text("SELECT id FROM gl_batches WHERE source_type = 'SALE_PARTNER_SHARE' AND source_id = :sid"),
        {"sid": target.id},
    ).fetchall()
    for (bid,) in batch_ids_ps:
        connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": int(bid)})
        connection.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": int(bid)})
    for partner_id, amount in total_revenue_partners.items():
        amt = _q2(Decimal(amount))
        if amt > 0:
            _gl_upsert_batch_and_entries(
                connection,
                source_type="SALE_PARTNER_SHARE",
                source_id=target.id,
                purpose=f"PARTNER_{partner_id}",
                currency=DEFAULT_CURRENCY,
                memo=f"حصة شريك من بيع #{target.sale_number or target.id}",
                entries=[
                    (GL_ACCOUNTS.get("REV", "4000_SALES"), amt, Decimal(0)),
                    (GL_ACCOUNTS.get("AP", "2000_AP"), Decimal(0), amt),
                ],
                ref=f"SALE-{target.id}-P{partner_id}",
                entity_type="PARTNER",
                entity_id=partner_id,
            )


def run_sale_gl_sync_after_commit(sale_id: int) -> None:
    """إنشاء/تحديث قيد GL للبيع في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not sale_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session, joinedload
        session = Session(db.engine)
        try:
            sale = session.execute(
                select(Sale).options(joinedload(Sale.customer)).where(Sale.id == sale_id)
            ).unique().scalar_one_or_none()
            if not sale:
                return
            _sale_gl_upsert_core(session.connection(), sale)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        if current_app:
            current_app.logger.warning("Sale GL sync failed for sale_id=%s: %s", sale_id, e, exc_info=True)


def build_sale_reversal_snapshot(sale: "Sale") -> dict:
    """لقطة بيانات البيع لاستخدامها في قيد العكس بعد الحذف."""
    try:
        return {
            "sale_id": sale.id,
            "amount": float(sale.total_amount or 0),
            "currency": sale.currency or DEFAULT_CURRENCY,
            "sale_date": getattr(sale, "sale_date", None),
            "ar_account": GL_ACCOUNTS.get("AR", "1100_AR"),
            "revenue_account": GL_ACCOUNTS.get("SALES", "4000_SALES"),
            "entity_type": "CUSTOMER",
            "entity_id": sale.customer_id,
        }
    except Exception:
        return {"sale_id": getattr(sale, "id", None), "amount": 0}


def run_sale_gl_reversal_after_delete(snapshot: dict) -> None:
    """تسجيل قيد عكسي SALE_REVERSAL بعد حذف البيع، في معاملة منفصلة."""
    if not snapshot or not snapshot.get("sale_id"):
        return
    try:
        from extensions import db
        sale_id = int(snapshot["sale_id"])
        amount = float(snapshot.get("amount") or 0)
        if amount <= 0:
            return
        currency = (str(snapshot.get("currency") or DEFAULT_CURRENCY).strip().upper() or DEFAULT_CURRENCY)
        amount_ils = amount
        if currency != DEFAULT_CURRENCY:
            try:
                with db.engine.connect() as c:
                    rate = _fx_rate_local_via_connection(
                        c, currency, DEFAULT_CURRENCY, snapshot.get("sale_date") or datetime.now(timezone.utc)
                    )
                    if rate and rate > 0:
                        amount_ils = amount * float(rate)
            except Exception:
                pass
        ar_account = (str(snapshot.get("ar_account") or "1100_AR").strip().upper())
        revenue_account = (str(snapshot.get("revenue_account") or "4000_SALES").strip().upper())
        entity_type = snapshot.get("entity_type")
        entity_id = snapshot.get("entity_id")
        try:
            entity_id = int(entity_id) if entity_id is not None else None
        except (TypeError, ValueError):
            entity_id = None
        entries = [(revenue_account, 0, amount_ils), (ar_account, amount_ils, 0)]
        memo = f"Reversal - deleted sale #{sale_id}"
        ref = f"REV-SALE-{sale_id}"
        with db.engine.connect() as conn:
            with conn.begin():
                batch_ids_ps = conn.execute(
                    sa_text("SELECT id FROM gl_batches WHERE source_type = 'SALE_PARTNER_SHARE' AND source_id = :sid"),
                    {"sid": sale_id},
                ).fetchall()
                for (bid,) in batch_ids_ps:
                    conn.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": int(bid)})
                    conn.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": int(bid)})
                _gl_upsert_batch_and_entries(
                    conn,
                    source_type="SALE_REVERSAL",
                    source_id=sale_id,
                    purpose="REVERSAL",
                    currency=DEFAULT_CURRENCY,
                    memo=memo,
                    entries=entries,
                    ref=ref,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
    except Exception as e:
        if current_app:
            current_app.logger.warning("Sale GL reversal failed for sale_id=%s: %s", snapshot.get("sale_id"), e, exc_info=True)


@event.listens_for(Sale, "after_insert")
@event.listens_for(Sale, "after_update")
def _sale_gl_batch_upsert(mapper, connection, target: "Sale"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_sale_gl_sync_after_commit."""
    return


@event.listens_for(Sale, "before_delete")
def _sale_gl_batch_reverse(mapper, connection, target: "Sale"):
    """معطّل: القيد العكسي يُنفّذ من المسار بعد الحذف عبر run_sale_gl_reversal_after_delete."""
    return


class SaleLine(db.Model, TimestampMixin):
    __tablename__ = "sale_lines"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    discount_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    line_receiver = db.Column(db.String(200))  # مستلم البضاعة لهذا البند
    note = db.Column(db.String(200))  # ملاحظات البند

    sale = db.relationship("Sale", back_populates="lines")
    product = db.relationship("Product", back_populates="sale_lines")
    warehouse = db.relationship("Warehouse", back_populates="sale_lines")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="chk_sale_line_qty_positive"),
        db.CheckConstraint("unit_price >= 0", name="chk_sale_line_unit_price_non_negative"),
        db.CheckConstraint("discount_rate >= 0 AND discount_rate <= 100", name="chk_sale_line_discount_rate_range"),
        db.CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="chk_sale_line_tax_rate_range"),
        db.Index("ix_sale_line_sale", "sale_id"),
    )

    @hybrid_property
    def gross_amount(self):
        return D(self.unit_price) * D(self.quantity)

    @hybrid_property
    def discount_amount(self):
        return self.gross_amount * (D(self.discount_rate or 0) / Decimal("100"))

    @hybrid_property
    def net_amount(self):
        return self.gross_amount - self.discount_amount

    @hybrid_property
    def line_tax(self):
        return self.net_amount * (D(self.tax_rate or 0) / Decimal("100"))

    @hybrid_property
    def line_total(self):
        return self.net_amount + self.line_tax

    def __repr__(self):
        pname = getattr(self.product, "name", None)
        return f"<SaleLine {pname or self.product_id} in Sale {self.sale_id}>"

def _recompute_sale_total_amount(connection, sale_id: int):
    subtotal_float = connection.execute(
        select(
            func.coalesce(
                func.sum(
                    (SaleLine.quantity * SaleLine.unit_price)
                    * (1 - (func.coalesce(SaleLine.discount_rate, 0) / 100.0))
                ),
                0.0,
            )
        ).where(SaleLine.sale_id == sale_id)
    ).scalar_one() or 0.0
    tr, sh, disc = connection.execute(select(Sale.tax_rate, Sale.shipping_cost, Sale.discount_total).where(Sale.id == sale_id)).first()
    subtotal = Decimal(str(subtotal_float))
    tax_rate = Decimal(str(tr or 0))
    shipping = Decimal(str(sh or 0))
    discount = Decimal(str(disc or 0))
    base = subtotal - discount
    if base < Decimal("0"):
        base = Decimal("0")
    tax = ((base + shipping) * tax_rate / Decimal("100"))
    total = (base + shipping) + tax
    if total < Decimal("0"):
        total = Decimal("0")
    connection.execute(
        update(Sale)
        .where(Sale.id == sale_id)
        .values(
            total_amount=total,
            balance_due=(total - func.coalesce(Sale.total_paid, 0))
        )
    )

@event.listens_for(SaleLine, "after_insert")
@event.listens_for(SaleLine, "after_update")
@event.listens_for(SaleLine, "after_delete")
def _sale_line_touch_sale_total(mapper, connection, target: "SaleLine"):
    sid = getattr(target, "sale_id", None)
    if sid:
        # تحديث أرصدة الشركاء/الموردين المرتبطين بالقطعة
        try:
            from sqlalchemy import text as sa_text
            pid = getattr(target, "product_id", None)
            if pid:
                # تحديث أرصدة الشركاء المرتبطين بهذه القطعة
                partner_results = connection.execute(
                    sa_text("""
                        SELECT DISTINCT partner_id 
                        FROM warehouse_partner_shares 
                        WHERE product_id = :pid
                        UNION
                        SELECT DISTINCT partner_id 
                        FROM product_partners 
                        WHERE product_id = :pid
                    """),
                    {"pid": pid}
                ).fetchall()
                
                for partner_row in partner_results:
                    if partner_row[0]:
                        _queue_partner_balance(target, partner_row[0])
        except Exception as e:
            pass
    if sid:
        _recompute_sale_total_amount(connection, int(sid))
        
        # إنشاء/تحديث GLBatch للمبيعة بعد تحديث المجموع
        sale_data = connection.execute(
            sa_text("""
                SELECT id, sale_number, total_amount, status, customer_id, currency
                FROM sales WHERE id = :id
            """),
            {"id": sid}
        ).first()
        
        if sale_data and sale_data[2] > 0 and sale_data[3] == 'CONFIRMED':  # total > 0 and CONFIRMED
            # استدعاء _sale_gl_batch_upsert يدوياً
            from models import Sale as SaleModel
            sale_obj = SaleModel()
            sale_obj.id = sale_data[0]
            sale_obj.sale_number = sale_data[1]
            sale_obj.total_amount = sale_data[2]
            sale_obj.status = sale_data[3]
            sale_obj.customer_id = sale_data[4]
            sale_obj.currency = sale_data[5]
            
            _sale_gl_batch_upsert(None, connection, sale_obj)

class SaleReturn(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "sale_returns"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="SET NULL"), index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    return_date = db.Column(db.DateTime, default=datetime.now, index=True)
    reason = db.Column(db.String(200))
    status = db.Column(sa_str_enum(["DRAFT","CONFIRMED","CANCELLED"], name="sale_return_status"), nullable=False, default="DRAFT", index=True)
    notes = db.Column(db.Text)
    total_amount = db.Column(db.Numeric(12,2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    currency = db.Column(db.String(10), nullable=False, default=DEFAULT_CURRENCY)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    credit_note_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="SET NULL"), index=True)

    sale = db.relationship("Sale")
    customer = db.relationship("Customer")
    warehouse = db.relationship("Warehouse")
    credit_note = db.relationship("Invoice")
    lines = db.relationship("SaleReturnLine", back_populates="sale_return", cascade="all, delete-orphan", order_by="SaleReturnLine.id")

    __table_args__ = (
        db.CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_sale_return_tax_rate_0_100"),
        db.CheckConstraint("tax_amount >= 0", name="ck_sale_return_tax_non_negative"),
    )

class SaleReturnLine(db.Model):
    __tablename__ = "sale_return_lines"

    id = db.Column(db.Integer, primary_key=True)
    sale_return_id = db.Column(db.Integer, db.ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12,2), nullable=False, default=0)
    notes = db.Column(db.String(200))
    
    # حالة المرتجع: سليم، تالف، للصيانة، غير قابل للاستخدام
    condition = db.Column(
        sa_str_enum(["GOOD", "DAMAGED", "FOR_REPAIR", "UNUSABLE"], name="return_line_condition"),
        nullable=False,
        default="GOOD",
        index=True
    )
    
    # الجهة المسؤولة عن الخسارة (للتالف فقط)
    # COMPANY = الشركة، SUPPLIER = المورد، PARTNER = الشريك، CUSTOMER = العميل
    liability_party = db.Column(
        sa_str_enum(["COMPANY", "SUPPLIER", "PARTNER", "CUSTOMER", "NONE"], name="return_liability_party"),
        nullable=True,
        default=None,
        index=True
    )

    sale_return = db.relationship("SaleReturn", back_populates="lines")
    product = db.relationship("Product")
    warehouse = db.relationship("Warehouse")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_sale_return_qty_pos"),
        db.CheckConstraint("unit_price >= 0", name="ck_sale_return_price_ge0"),
        db.Index("ix_sale_return_line_prod_wh", "product_id", "warehouse_id"),
    )

@event.listens_for(SaleReturnLine, "after_insert")
@event.listens_for(SaleReturnLine, "after_update")
def _srl_after_insert(mapper, connection, t: "SaleReturnLine"):
    # فقط المرتجعات بحالة GOOD تُضاف للمخزون القابل للبيع
    # الحالات الأخرى (DAMAGED, FOR_REPAIR, UNUSABLE) تُسجّل لكن لا تُعاد للمخزون
    if t.warehouse_id and (t.condition or 'GOOD') == 'GOOD':
        _apply_stock_delta(connection, t.product_id, t.warehouse_id, +int(t.quantity or 0))
    
    # حساب الإجمالي
    if t.sale_return_id:
        sr = connection.execute(
            select(SaleReturn.id, SaleReturn.sale_id).where(SaleReturn.id == t.sale_return_id)
        ).first()
        if sr and sr.sale_id:
            items_total = connection.execute(
                select(func.coalesce(func.sum(SaleReturnLine.quantity * SaleReturnLine.unit_price), 0)).where(SaleReturnLine.sale_return_id == t.sale_return_id)
            ).scalar_one() or 0
            sale_subtotal = connection.execute(
                select(
                    func.coalesce(
                        func.sum(
                            (SaleLine.quantity * SaleLine.unit_price)
                            * (1 - (func.coalesce(SaleLine.discount_rate, 0) / 100.0))
                        ),
                        0.0,
                    )
                ).where(SaleLine.sale_id == sr.sale_id)
            ).scalar_one() or 0
            sale_row = connection.execute(
                select(Sale.tax_rate, Sale.shipping_cost, Sale.discount_total).where(Sale.id == sr.sale_id)
            ).first()
            tr = Decimal(str((sale_row[0] if sale_row else 0) or 0))
            sh = Decimal(str((sale_row[1] if sale_row else 0) or 0))
            disc = Decimal(str((sale_row[2] if sale_row else 0) or 0))
            items_total_d = Decimal(str(items_total or 0))
            sale_subtotal_d = Decimal(str(sale_subtotal or 0))
            if sale_subtotal_d > Decimal("0"):
                ratio = items_total_d / sale_subtotal_d
            else:
                ratio = Decimal("1") if items_total_d > Decimal("0") else Decimal("0")
            if ratio < Decimal("0"):
                ratio = Decimal("0")
            if ratio > Decimal("1"):
                ratio = Decimal("1")
            disc_share = disc * ratio
            sh_share = sh * ratio
            base = items_total_d - disc_share
            if base < Decimal("0"):
                base = Decimal("0")
            base = base + sh_share
            tax_amount = (base * tr / Decimal("100.0")) if tr > 0 else Decimal("0")
            total_amount = base + tax_amount
            if total_amount < Decimal("0"):
                total_amount = Decimal("0")
            connection.execute(
                update(SaleReturn)
                .where(SaleReturn.id == t.sale_return_id)
                .values(
                    total_amount=q(total_amount),
                    tax_rate=q(tr),
                    tax_amount=q(tax_amount),
                )
            )
        else:
            total = connection.execute(
                select(func.coalesce(func.sum(SaleReturnLine.quantity * SaleReturnLine.unit_price), 0)).where(SaleReturnLine.sale_return_id == t.sale_return_id)
            ).scalar_one() or 0
            connection.execute(update(SaleReturn).where(SaleReturn.id == t.sale_return_id).values(total_amount=q(total)))
        
        sr_row = connection.execute(
            sa_text("SELECT id, status, customer_id, total_amount FROM sale_returns WHERE id=:id"),
            {"id": int(t.sale_return_id)},
        ).mappings().first()
        if sr_row and str(sr_row.get("status") or "").upper() == "CONFIRMED" and float(sr_row.get("total_amount") or 0) > 0:
            amt = float(sr_row["total_amount"])
            entries = [
                (GL_ACCOUNTS.get("REV", "4000_SALES"), amt, 0.0),
                (GL_ACCOUNTS.get("AR", "1100_AR"), 0.0, amt),
            ]
            _gl_upsert_batch_and_entries(
                connection,
                source_type="SALE_RETURN",
                source_id=int(sr_row["id"]),
                purpose="RETURN",
                currency="ILS",
                memo=f"مرتجع مبيعات - {sr_row.get('id')}",
                entries=entries,
                ref=str(f"RET-{sr_row.get('id')}"),
                entity_type="CUSTOMER",
                entity_id=int(sr_row.get("customer_id") or 0) or None,
            )
        else:
            bids = connection.execute(
                sa_text("SELECT id FROM gl_batches WHERE source_type='SALE_RETURN' AND source_id=:sid AND purpose='RETURN'"),
                {"sid": int(t.sale_return_id)},
            ).fetchall()
            for (bid,) in bids:
                connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id=:bid"), {"bid": int(bid)})
                connection.execute(sa_text("DELETE FROM gl_batches WHERE id=:bid"), {"bid": int(bid)})
    
    # 🔥 المنتجات التالفة: تخصم من الجهة المسؤولة فقط
    # المنتجات السليمة: لا تأثير (البيع طبيعي والإرجاع طبيعي)
    condition = (t.condition or 'GOOD').upper()
    liability = (t.liability_party or '').upper()
    
    if condition in ('DAMAGED', 'UNUSABLE') and liability:  # التالف وفيه جهة مسؤولة
        try:
            # جلب معلومات المنتج
            product_row = connection.execute(
                select(Product.id, Product.cost_price, Product.supplier_id).where(Product.id == t.product_id)
            ).first()
            
            if product_row:
                cost_price = float(product_row.cost_price or 0)
                supplier_id = product_row.supplier_id
                damaged_value = cost_price * int(t.quantity or 0)
                
                if damaged_value <= 0:
                    return  # لا قيمة للخصم
                
                # خصم حسب الجهة المسؤولة
                if liability == 'SUPPLIER' and supplier_id:
                    _queue_supplier_balance(t, supplier_id)
                
                elif liability == 'PARTNER' and t.warehouse_id:
                    # الشريك مسؤول (سوء تخزين، إهمال)
                    wh_row = connection.execute(
                        select(Warehouse.partner_id).where(Warehouse.id == t.warehouse_id)
                    ).first()
                    
                    if wh_row and wh_row.partner_id:
                        _queue_partner_balance(t, wh_row.partner_id)
                
                elif liability == 'CUSTOMER':
                    # العميل مسؤول (سوء استخدام) - لا نخفض دينه، يدفع التعويض
                    # يمكن إضافة قيد إضافي أو فاتورة تعويض هنا
                    pass
                
                # COMPANY أو None = الشركة تتحمل (لا نحتاج action)
                
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"⚠️ خطأ في حساب خسارة المنتج التالف: {e}")

@event.listens_for(SaleReturnLine, "after_delete")
def _srl_after_delete(mapper, connection, t: "SaleReturnLine"):
    # عند حذف سطر مرتجع: إذا كان سليماً، نعكس التغيير في المخزون
    if t.warehouse_id and (t.condition or 'GOOD') == 'GOOD':
        _apply_stock_delta(connection, t.product_id, t.warehouse_id, -int(t.quantity or 0))
    if t.sale_return_id:
        sr = connection.execute(
            select(SaleReturn.id, SaleReturn.sale_id).where(SaleReturn.id == t.sale_return_id)
        ).first()
        if sr and sr.sale_id:
            items_total = connection.execute(
                select(func.coalesce(func.sum(SaleReturnLine.quantity * SaleReturnLine.unit_price), 0)).where(SaleReturnLine.sale_return_id == t.sale_return_id)
            ).scalar_one() or 0
            sale_subtotal = connection.execute(
                select(
                    func.coalesce(
                        func.sum(
                            (SaleLine.quantity * SaleLine.unit_price)
                            * (1 - (func.coalesce(SaleLine.discount_rate, 0) / 100.0))
                        ),
                        0.0,
                    )
                ).where(SaleLine.sale_id == sr.sale_id)
            ).scalar_one() or 0
            sale_row = connection.execute(
                select(Sale.tax_rate, Sale.shipping_cost, Sale.discount_total).where(Sale.id == sr.sale_id)
            ).first()
            tr = Decimal(str((sale_row[0] if sale_row else 0) or 0))
            sh = Decimal(str((sale_row[1] if sale_row else 0) or 0))
            disc = Decimal(str((sale_row[2] if sale_row else 0) or 0))
            items_total_d = Decimal(str(items_total or 0))
            sale_subtotal_d = Decimal(str(sale_subtotal or 0))
            if sale_subtotal_d > Decimal("0"):
                ratio = items_total_d / sale_subtotal_d
            else:
                ratio = Decimal("1") if items_total_d > Decimal("0") else Decimal("0")
            if ratio < Decimal("0"):
                ratio = Decimal("0")
            if ratio > Decimal("1"):
                ratio = Decimal("1")
            disc_share = disc * ratio
            sh_share = sh * ratio
            base = items_total_d - disc_share
            if base < Decimal("0"):
                base = Decimal("0")
            base = base + sh_share
            tax_amount = (base * tr / Decimal("100.0")) if tr > 0 else Decimal("0")
            total_amount = base + tax_amount
            if total_amount < Decimal("0"):
                total_amount = Decimal("0")
            connection.execute(
                update(SaleReturn)
                .where(SaleReturn.id == t.sale_return_id)
                .values(
                    total_amount=q(total_amount),
                    tax_rate=q(tr),
                    tax_amount=q(tax_amount),
                )
            )
        else:
            total = connection.execute(
                select(func.coalesce(func.sum(SaleReturnLine.quantity * SaleReturnLine.unit_price), 0)).where(SaleReturnLine.sale_return_id == t.sale_return_id)
            ).scalar_one() or 0
            connection.execute(update(SaleReturn).where(SaleReturn.id == t.sale_return_id).values(total_amount=q(total)))
        
        sr_row = connection.execute(
            sa_text("SELECT id, status, customer_id, total_amount FROM sale_returns WHERE id=:id"),
            {"id": int(t.sale_return_id)},
        ).mappings().first()
        if sr_row and str(sr_row.get("status") or "").upper() == "CONFIRMED" and float(sr_row.get("total_amount") or 0) > 0:
            amt = float(sr_row["total_amount"])
            entries = [
                (GL_ACCOUNTS.get("REV", "4000_SALES"), amt, 0.0),
                (GL_ACCOUNTS.get("AR", "1100_AR"), 0.0, amt),
            ]
            _gl_upsert_batch_and_entries(
                connection,
                source_type="SALE_RETURN",
                source_id=int(sr_row["id"]),
                purpose="RETURN",
                currency="ILS",
                memo=f"مرتجع مبيعات - {sr_row.get('id')}",
                entries=entries,
                ref=str(f"RET-{sr_row.get('id')}"),
                entity_type="CUSTOMER",
                entity_id=int(sr_row.get("customer_id") or 0) or None,
            )
        else:
            bids = connection.execute(
                sa_text("SELECT id FROM gl_batches WHERE source_type='SALE_RETURN' AND source_id=:sid AND purpose='RETURN'"),
                {"sid": int(t.sale_return_id)},
            ).fetchall()
            for (bid,) in bids:
                connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id=:bid"), {"bid": int(bid)})
                connection.execute(sa_text("DELETE FROM gl_batches WHERE id=:bid"), {"bid": int(bid)})

# ═══════════════════════════════════════════════════════════════════════
# 💰 Tax Listeners for SaleReturn - مستمعات الضرائب للمرتجعات
# ═══════════════════════════════════════════════════════════════════════

@event.listens_for(SaleReturn, "after_insert")
@event.listens_for(SaleReturn, "after_update")
def _sale_return_create_tax_entry(mapper, connection, target: "SaleReturn"):
    """إنشاء/تحديث سجل ضريبي عكسي للمرتجع تلقائياً"""
    if target.status != 'CONFIRMED':
        return
    
    total_amount = float(target.total_amount or 0)
    if total_amount <= 0:
        return
    
    tax_rate = 0.0
    
    if target.sale_id:
        try:
            from sqlalchemy import select as sa_select
            sale_data = connection.execute(
                sa_select(Sale.tax_rate).where(Sale.id == target.sale_id)
            ).first()
            if sale_data:
                tax_rate = float(sale_data[0] or 0)
        except Exception:
            pass
    
    if tax_rate <= 0:
        return
    
    try:
        from sqlalchemy import select as sa_select, delete as sa_delete
        
        base_amount = total_amount / (1 + (tax_rate / 100.0))
        tax_amount = total_amount - base_amount
        
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SALE_RETURN',
                TaxEntry.transaction_id == target.id
            )
        )
        
        return_date = datetime.now(timezone.utc)
        connection.execute(
            sa_insert(TaxEntry).values(
                entry_type='OUTPUT_VAT',
                transaction_type='SALE_RETURN',
                transaction_id=target.id,
                transaction_reference=str(target.id),
                tax_rate=tax_rate,
                base_amount=-abs(base_amount),
                tax_amount=-abs(tax_amount),
                total_amount=-abs(total_amount),
                currency=target.currency or DEFAULT_CURRENCY,
                fiscal_year=return_date.year,
                fiscal_month=return_date.month,
                tax_period=f"{return_date.year}-{return_date.month:02d}",
                customer_id=target.customer_id,
                notes=f'مرتجع بيع: {target.id}',
                created_at=return_date
            )
        )
    except Exception:
        pass

@event.listens_for(SaleReturn, "before_delete")
def _sale_return_delete_tax_entry(mapper, connection, target: "SaleReturn"):
    """حذف سجل الضريبة عند حذف المرتجع"""
    try:
        from sqlalchemy import delete as sa_delete
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SALE_RETURN',
                TaxEntry.transaction_id == target.id
            )
        )
    except Exception:
        pass

class Invoice(db.Model, TimestampMixin):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), unique=True, index=True, nullable=False)
    invoice_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    due_date = Column(DateTime, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), index=True)
    service_id = Column(Integer, ForeignKey("service_requests.id"), index=True)
    preorder_id = Column(Integer, ForeignKey("preorders.id"), index=True)

    source = Column(sa_str_enum(InvoiceSource, name="invoice_source"), default=InvoiceSource.MANUAL.value, nullable=False, index=True)
    # status تم حذفه - يُحسب تلقائياً من total_paid (انظر @property status أدناه)
    kind = Column(sa_str_enum(["INVOICE", "CREDIT_NOTE"], name="invoice_kind"), default="INVOICE", nullable=False, index=True)

    credit_for_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), index=True)
    refund_of_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), index=True)

    currency = Column(String(10), default=DEFAULT_CURRENCY, nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = Column(Numeric(10, 6))
    fx_rate_source = Column(String(20))
    fx_rate_timestamp = Column(DateTime)
    fx_base_currency = Column(String(10))
    fx_quote_currency = Column(String(10))
    
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(12, 2), default=0, nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    notes = Column(Text)
    terms = Column(Text)

    refunded_total = Column(Numeric(12, 2), default=0, nullable=False)
    idempotency_key = Column(String(64), unique=True, index=True)
    cancelled_at = Column(DateTime, index=True)
    cancelled_by = Column(Integer, ForeignKey("users.id"), index=True)
    cancel_reason = Column(String(200))

    customer = relationship("Customer", back_populates="invoices", lazy="joined")
    supplier = relationship("Supplier", back_populates="invoices", lazy="joined")
    partner = relationship("Partner", back_populates="invoices", lazy="joined")
    sale = relationship("Sale", back_populates="invoice", uselist=False, lazy="joined")
    service = relationship("ServiceRequest", back_populates="invoice", lazy="joined")
    preorder = relationship("PreOrder", back_populates="invoice", lazy="joined")

    cancelled_by_user = relationship("User", foreign_keys=[cancelled_by], lazy="joined")

    refund_of = relationship("Invoice", remote_side=[id], foreign_keys=[refund_of_id], backref=db.backref("refunds", lazy="selectin"), lazy="joined")
    credit_for = relationship("Invoice", remote_side=[id], foreign_keys=[credit_for_id], backref=db.backref("credit_notes", lazy="selectin"), lazy="joined")

    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.id", lazy="selectin")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan", passive_deletes=True, order_by="Payment.id", lazy="selectin")

    gl_batches = relationship("GLBatch", primaryjoin="and_(foreign(GLBatch.source_id)==Invoice.id, GLBatch.source_type=='INVOICE')", viewonly=True, order_by="GLBatch.id", lazy="selectin")

    __table_args__ = (
        Index("ix_inv_customer_date", "customer_id", "invoice_date"),
        Index("ix_inv_kind_date", "kind", "invoice_date"),
        Index("ix_inv_cust_cancelled", "customer_id", "cancelled_at"),
        Index("ix_inv_total_amount", "total_amount"),
    )

    @validates("source", "kind")
    def _uppercase_enum(self, key, value):
        return getattr(value, "value", value).upper() if value else value

    @validates("currency")
    def _v_currency(self, _, v):
        return ensure_currency(v or "ILS")

    @validates("invoice_number")
    def _v_norm_number(self, _, v):
        s = (v or "").strip()
        s = re.sub(r"\s+", "", s)
        return s.upper() or None

    @hybrid_property
    def is_credit_note(self):
        k = getattr(self.kind, "value", self.kind)
        return (k or "").upper() == "CREDIT_NOTE"

    @hybrid_property
    def computed_total(self):
        return sum(D(l.line_total) for l in (self.lines or [])) if self.lines else Decimal("0.00")

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal

        total = Decimal("0.00")
        invoice_currency = self.currency or "ILS"

        payments = [
            p
            for p in (self.payments or [])
            if getattr(p, "invoice_id", None) == self.id
            and getattr(p, "status", None) == PaymentStatus.COMPLETED.value
            and getattr(p, "direction", None) == PaymentDirection.IN.value
        ]

        for p in payments:
            amt = Decimal(str(getattr(p, "total_amount", 0) or 0))
            p_currency = getattr(p, "currency", None)
            if not p_currency or p_currency == invoice_currency:
                total += amt
                continue
            try:
                total += convert_amount(amt, p_currency, invoice_currency, getattr(p, "payment_date", None))
            except Exception:
                pass

        return float(total)

    @total_paid.expression
    def total_paid(cls):
        """SQL expression — لا تدعم تحويل العملات.
        النتائج قد تكون غير دقيقة للفواتير متعددة العملات.
        استخدم النسخة Python (hybrid property) للحسابات الدقيقة."""
        from sqlalchemy.orm import aliased

        p = aliased(Payment)
        return (
            select(func.coalesce(func.sum(p.total_amount), 0))
            .where(
                (p.invoice_id == cls.id)
                & (p.status == PaymentStatus.COMPLETED.value)
                & (p.direction == PaymentDirection.IN.value)
            ).scalar_subquery()
        )

    @hybrid_property
    def balance_due(self):
        return float(q(self.total_amount or 0) - q(self.total_paid or 0))

    @hybrid_property
    def status(self):
        """
        حالة الفاتورة - محسوبة تلقائياً من total_paid
        UNPAID: غير مدفوعة (total_paid = 0)
        PARTIAL: مدفوعة جزئياً (0 < total_paid < total_amount)
        PAID: مدفوعة كاملاً (total_paid >= total_amount)
        """
        if self.cancelled_at:
            return 'CANCELLED'
        
        total = float(self.total_amount or 0)
        paid = float(self.total_paid or 0)
        
        if paid == 0:
            return 'UNPAID'
        elif paid >= total:
            return 'PAID'
        else:
            return 'PARTIAL'

    @status.expression
    def status(cls):
        from sqlalchemy import case, literal

        return case(
            (cls.cancelled_at.is_not(None), literal("CANCELLED")),
            (cls.total_paid <= 0, literal("UNPAID")),
            (cls.total_paid >= cls.total_amount, literal("PAID")),
            else_=literal("PARTIAL"),
        )

    @hybrid_property
    def refundable_amount(self):
        return float(q(self.total_amount or 0) - q(self.refunded_total or 0))

    def apply_refund(self, amount):
        amt = q(amount or 0)
        if amt <= 0 or amt > q(self.refundable_amount):
            raise ValueError("invoice.refund_exceeds_allowed")
        self.refunded_total = q(self.refunded_total or 0) + amt

    def cancel(self, by_user_id: int | None = None, reason: str | None = None):
        self.cancelled_at = datetime.now(timezone.utc)
        self.cancelled_by = by_user_id
        self.cancel_reason = (reason or None)
        # status سيُحسب تلقائياً = CANCELLED (لأن cancelled_at موجود)

    # update_status تم حذفها - status الآن محسوب تلقائياً

    def __repr__(self):
        return f"<Invoice {self.invoice_number}>"

class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    discount = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), index=True)

    invoice = db.relationship("Invoice", back_populates="lines")
    product = db.relationship("Product")

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_invoice_line_quantity_non_negative"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_line_unit_price_non_negative"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_invoice_line_tax_rate_range"),
        CheckConstraint("discount >= 0 AND discount <= 100", name="ck_invoice_line_discount_range"),
    )

    @hybrid_property
    def line_total(self):
        gross = D(self.quantity) * D(self.unit_price)
        discount_amount = gross * (D(self.discount or 0) / Decimal("100.0"))
        taxable = gross - discount_amount
        tax_amount = taxable * (D(self.tax_rate or 0) / Decimal("100.0"))
        return taxable + tax_amount

@event.listens_for(Invoice, "before_insert")
def _invoice_normalize_and_total_insert(mapper, connection, target: "Invoice"):
    target.currency = ensure_currency(target.currency or "ILS")
    
    # حفظ سعر الصرف تلقائياً للفواتير (فقط عند الإنشاء)
    invoice_currency = target.currency
    default_currency = "ILS"
    
    if invoice_currency != default_currency:
        try:
            at = getattr(target, "invoice_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, invoice_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = invoice_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass
    
    target.total_amount = q(target.total_amount or 0)
    target.tax_amount = q(target.tax_amount or 0)
    target.discount_amount = q(target.discount_amount or 0)
    target.refunded_total = q(target.refunded_total or 0)
    k = getattr(target, "kind", None)
    if hasattr(k, "value"):
        k = k.value
    target.kind = (k or "INVOICE").upper()


@event.listens_for(Invoice, "before_update")
def _invoice_normalize_and_total_update(mapper, connection, target: "Invoice"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = ensure_currency(target.currency or "ILS")
    target.total_amount = q(target.total_amount or 0)
    target.tax_amount = q(target.tax_amount or 0)
    target.discount_amount = q(target.discount_amount or 0)
    target.refunded_total = q(target.refunded_total or 0)
    k = getattr(target, "kind", None)
    if hasattr(k, "value"):
        k = k.value
    target.kind = (k or "INVOICE").upper()
    # ملاحظة: status الآن property محسوب تلقائياً - لا حاجة لتحديثه
    src = getattr(target, "source", None)
    if hasattr(src, "value"):
        src = src.value
    target.source = (src or InvoiceSource.MANUAL.value).upper()

def _recompute_invoice_totals(connection, invoice_id: int):
    """إعادة حساب مجاميع الفاتورة من بنودها - بدون cartesian product"""
    from sqlalchemy import select
    
    # حساب المجاميع من البنود باستخدام subquery
    totals = connection.execute(
        select(
            func.coalesce(
                func.sum(InvoiceLine.quantity * InvoiceLine.unit_price), 0.0
            ).label('gross'),
            func.coalesce(
                func.sum(
                    (InvoiceLine.quantity * InvoiceLine.unit_price)
                    * (func.coalesce(InvoiceLine.discount, 0) / 100.0)
                ), 0.0
            ).label('disc'),
            func.coalesce(
                func.sum(
                    ((InvoiceLine.quantity * InvoiceLine.unit_price)
                     * (1 - (func.coalesce(InvoiceLine.discount, 0) / 100.0)))
                    * (func.coalesce(InvoiceLine.tax_rate, 0) / 100.0)
                ), 0.0
            ).label('tax')
        ).where(InvoiceLine.invoice_id == invoice_id)
    ).first()
    
    if totals:
        gross, disc, tax = totals
        taxable = gross - disc
        # حماية من القيم السالبة - لو الخصم أكبر من الإجمالي
        if taxable < 0:
            taxable = 0
        total = taxable + tax
        # تأكد إن الـ total مش سالب
        if total < 0:
            total = 0
        
        # تحديث الفاتورة
        connection.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(total_amount=total, tax_amount=tax, discount_amount=disc)
        )

@event.listens_for(Invoice, "after_insert")
@event.listens_for(Invoice, "after_update")
def _inv_touch_totals(mapper, connection, target: "Invoice"):
    if target.id:
        _recompute_invoice_totals(connection, int(target.id))

# ===== إنشاء سجلات ضريبية تلقائية للفواتير =====
@event.listens_for(Invoice, "after_insert")
@event.listens_for(Invoice, "after_update")
def _invoice_create_tax_entry(mapper, connection, target: "Invoice"):
    """إنشاء/تحديث سجل ضريبي للفاتورة تلقائياً"""
    if target.cancelled_at:
        return
    
    tax_amount = float(target.tax_amount or 0)
    if tax_amount <= 0:
        return
    
    try:
        from sqlalchemy import select as sa_select, delete as sa_delete
        
        invoice_date = target.invoice_date or datetime.now(timezone.utc)
        total_amount = float(target.total_amount or 0)
        base_amount = total_amount - tax_amount
        
        if base_amount > 0:
            tax_rate = (tax_amount / base_amount) * 100.0
        else:
            return
        
        entry_type = 'OUTPUT_VAT'
        customer_id = target.customer_id
        supplier_id = None
        
        if target.supplier_id:
            entry_type = 'INPUT_VAT'
            supplier_id = target.supplier_id
            customer_id = None
        
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'INVOICE',
                TaxEntry.transaction_id == target.id
            )
        )
        
        connection.execute(
            sa_insert(TaxEntry).values(
                entry_type=entry_type,
                transaction_type='INVOICE',
                transaction_id=target.id,
                transaction_reference=target.invoice_number,
                tax_rate=tax_rate,
                base_amount=base_amount,
                tax_amount=tax_amount,
                total_amount=total_amount,
                currency=target.currency or DEFAULT_CURRENCY,
                fiscal_year=invoice_date.year,
                fiscal_month=invoice_date.month,
                tax_period=f"{invoice_date.year}-{invoice_date.month:02d}",
                customer_id=customer_id,
                supplier_id=supplier_id,
                notes=f'فاتورة: {target.invoice_number}',
                created_at=datetime.now(timezone.utc)
            )
        )
    except Exception:
        pass

@event.listens_for(Invoice, "before_delete")
def _invoice_delete_tax_entry(mapper, connection, target: "Invoice"):
    """حذف سجل الضريبة عند حذف الفاتورة"""
    try:
        from sqlalchemy import delete as sa_delete
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'INVOICE',
                TaxEntry.transaction_id == target.id
            )
        )
    except Exception:
        pass

# ===== إنشاء قيود GL تلقائية للفواتير =====
def _invoice_gl_upsert_core(connection, target: "Invoice") -> None:
    """منطق إنشاء/تحديث قيد GL للفاتورة (يُستدعى من معاملة منفصلة بعد commit)."""
    if target.cancelled_at:
        amount = float(target.total_amount or 0)
        if amount <= 0:
            return
        amount_ils = amount
        if target.currency and target.currency != "ILS":
            try:
                rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.invoice_date or datetime.now(timezone.utc))
                if rate and rate > 0:
                    amount_ils = float(amount * float(rate))
            except Exception:
                pass
        entity_type = "CUSTOMER" if target.customer_id else ("SUPPLIER" if target.supplier_id else "PARTNER")
        entity_id = target.customer_id or target.supplier_id or target.partner_id
        if entity_type == "CUSTOMER":
            ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
            revenue_account = (
                GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE")
                if target.service_id
                else GL_ACCOUNTS.get("SALES", "4000_SALES")
            )
            entries = [(revenue_account, amount_ils, 0), (ar_account, 0, amount_ils)]
        else:
            ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
            purchase_account = GL_ACCOUNTS.get("PURCHASES", "5100_PURCHASES")
            entries = [(purchase_account, amount_ils, 0), (ap_account, 0, amount_ils)]
        _gl_upsert_batch_and_entries(
            connection,
            source_type="INVOICE_REVERSAL",
            source_id=target.id,
            purpose="REVERSAL",
            currency="ILS",
            memo=f"Reversal - cancelled invoice #{target.id}",
            entries=entries,
            ref=f"REV-INV-{target.id}",
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return
    amount = float(target.total_amount or 0)
    if amount <= 0:
        return
    amount_ils = amount
    if target.currency and target.currency != "ILS":
        try:
            rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.invoice_date or datetime.now(timezone.utc))
            if rate and rate > 0:
                amount_ils = float(amount * float(rate))
        except Exception:
            pass
    entity_type = "CUSTOMER"
    entity_id = target.customer_id
    ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
    if target.supplier_id:
        entity_type = "SUPPLIER"
        entity_id = target.supplier_id
        ar_account = GL_ACCOUNTS.get("AP", "2000_AP")
    elif target.partner_id:
        entity_type = "PARTNER"
        entity_id = target.partner_id
        ar_account = GL_ACCOUNTS.get("AP", "2000_AP")
    if entity_type == "CUSTOMER":
        revenue_account = (
            GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE")
            if target.service_id
            else GL_ACCOUNTS.get("REV", "4000_SALES")
        )
        entries = [(ar_account, amount_ils, 0), (revenue_account, 0, amount_ils)]
        memo = f"Invoice sale - {target.invoice_number}"
    else:
        entries = [(GL_ACCOUNTS.get("PURCHASES", "5100_PURCHASES"), amount_ils, 0), (ar_account, 0, amount_ils)]
        memo = f"Invoice purchase - {target.invoice_number}"
    _gl_upsert_batch_and_entries(
        connection,
        source_type="INVOICE",
        source_id=target.id,
        purpose="INVOICE",
        currency="ILS",
        memo=memo,
        entries=entries,
        ref=target.invoice_number,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def run_invoice_gl_sync_after_commit(invoice_id: int) -> None:
    """إنشاء/تحديث قيد GL للفاتورة في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not invoice_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session
        session = Session(db.engine)
        try:
            inv = session.get(Invoice, invoice_id)
            if not inv:
                return
            _invoice_gl_upsert_core(session.connection(), inv)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        if current_app:
            current_app.logger.warning("Invoice GL sync failed for invoice_id=%s: %s", invoice_id, e, exc_info=True)


@event.listens_for(Invoice, "after_insert")
@event.listens_for(Invoice, "after_update")
def _invoice_gl_batch_upsert(mapper, connection, target: "Invoice"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_invoice_gl_sync_after_commit."""
    return

@event.listens_for(InvoiceLine, "after_insert")
@event.listens_for(InvoiceLine, "after_update")
@event.listens_for(InvoiceLine, "after_delete")
def _inv_line_touch_invoice(mapper, connection, target: "InvoiceLine"):
    """عند تعديل بنود الفاتورة: إعادة حساب المجموع + إنشاء GLBatch"""
    if target.invoice_id:
        invoice_id = int(target.invoice_id)
        
        # 1. إعادة حساب المجموع
        _recompute_invoice_totals(connection, invoice_id)
        
        # 2. GL للفاتورة يُنفّذ من المسار بعد commit عبر run_invoice_gl_sync_after_commit(invoice_id)

class ProductSupplierLoan(db.Model, TimestampMixin):
    __tablename__ = 'product_supplier_loans'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)

    loan_value = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    deferred_price = db.Column(db.Numeric(12, 2))
    is_settled = db.Column(db.Boolean, default=False, index=True)

    partner_share_quantity = db.Column(db.Integer, default=0, nullable=False)
    partner_share_value = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    notes = db.Column(db.Text)

    product = db.relationship('Product', back_populates='supplier_loans')
    supplier = db.relationship('Supplier', backref='loaned_products')
    settlements = db.relationship('SupplierLoanSettlement', back_populates='loan', cascade='all, delete-orphan')

    __table_args__ = (
        db.CheckConstraint('loan_value >= 0', name='ck_psl_loan_value_ge_0'),
        db.CheckConstraint('deferred_price IS NULL OR deferred_price >= 0', name='ck_psl_deferred_price_ge_0'),
        db.CheckConstraint('partner_share_quantity >= 0', name='ck_psl_share_qty_ge_0'),
        db.CheckConstraint('partner_share_value >= 0', name='ck_psl_share_val_ge_0'),
        db.Index('ix_psl_product_supplier', 'product_id', 'supplier_id'),
        db.Index('ix_psl_supplier_settled', 'supplier_id', 'is_settled'),
    )

    @validates('loan_value', 'deferred_price', 'partner_share_value')
    def _v_money(self, _, v):
        if v in (None, ''):
            return None
        d = Decimal(str(v))
        if d < 0:
            raise ValueError("monetary values must be >= 0")
        return d

    @validates('partner_share_quantity')
    def _v_share_qty(self, _, v):
        iv = int(v or 0)
        if iv < 0:
            raise ValueError("partner_share_quantity must be >= 0")
        return iv

    @validates('notes')
    def _v_notes(self, _, v):
        return (str(v).strip() or None) if v is not None else None

    @hybrid_property
    def effective_price(self):
        v = self.deferred_price if self.deferred_price not in (None, 0) else self.loan_value
        if not v or v <= 0:
            pp = getattr(self.product, 'purchase_price', 0) or 0
            return float(pp or 0)
        return float(v)

    @hybrid_property
    def outstanding_value(self):
        return 0.0 if bool(self.is_settled) else float(self.effective_price or 0)

    def mark_settled(self, final_price: Decimal | float | int):
        self.deferred_price = Decimal(str(final_price))
        self.is_settled = True

    def __repr__(self):
        return f"<ProductSupplierLoan P{self.product_id}-S{self.supplier_id}>"

@event.listens_for(ProductSupplierLoan, 'before_insert')
def _psl_before_insert(mapper, connection, target: 'ProductSupplierLoan'):
    if not target.loan_value or Decimal(str(target.loan_value)) <= 0:
        if target.product_id:
            try:
                from sqlalchemy import select as sa_select
                pp = connection.execute(
                    sa_select(Product.purchase_price).where(Product.id == target.product_id)
                ).scalar_one_or_none()
                target.loan_value = Decimal(str(pp or 0))
            except Exception:
                target.loan_value = Decimal("0")
        else:
            target.loan_value = Decimal("0")
    if target.deferred_price is not None and Decimal(str(target.deferred_price)) >= 0:
        target.is_settled = True
    target.partner_share_quantity = int(target.partner_share_quantity or 0)
    target.partner_share_value = Decimal(str(target.partner_share_value or 0))

@event.listens_for(ProductSupplierLoan, 'before_update')
def _psl_before_update(mapper, connection, target: 'ProductSupplierLoan'):
    if not target.loan_value or Decimal(str(target.loan_value)) <= 0:
        if target.product_id:
            try:
                from sqlalchemy import select as sa_select
                pp = connection.execute(
                    sa_select(Product.purchase_price).where(Product.id == target.product_id)
                ).scalar_one_or_none()
                target.loan_value = Decimal(str(pp or 0))
            except Exception:
                target.loan_value = Decimal("0")
        else:
            target.loan_value = Decimal("0")
    if target.deferred_price is not None and Decimal(str(target.deferred_price)) >= 0:
        target.is_settled = True
    target.partner_share_quantity = int(target.partner_share_quantity or 0)
    target.partner_share_value = Decimal(str(target.partner_share_value or 0))

class Payment(db.Model, TimestampMixin):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    payment_number = Column(String(50), unique=True, nullable=False, index=True)
    payment_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    subtotal = Column(Numeric(12, 2))
    tax_rate = Column(Numeric(5, 2))
    tax_amount = Column(Numeric(12, 2))
    total_amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="ILS", nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = Column(Numeric(10, 6))  # السعر المستخدم في التحويل
    fx_rate_source = Column(String(20))    # مصدر السعر (online, manual, default)
    fx_rate_timestamp = Column(DateTime)   # وقت الحصول على السعر
    fx_base_currency = Column(String(10))  # العملة الأساسية
    fx_quote_currency = Column(String(10))  # العملة المقابلة

    method = Column(sa_str_enum(PaymentMethod, name="payment_method"), nullable=False, index=True)
    status = Column(sa_str_enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING.value, nullable=False)
    direction = Column(sa_str_enum(PaymentDirection, name="payment_direction"), default=PaymentDirection.IN.value, nullable=False)
    entity_type = Column(sa_str_enum(PaymentEntityType, name="payment_entity_type"), default=PaymentEntityType.CUSTOMER.value, nullable=False, index=True)

    reference = Column(String(100))
    receipt_number = Column(String(50), unique=True, index=True)
    notes = Column(Text)
    receiver_name = Column(String(200))  # اسم مستلم الدفعة
    deliverer_name = Column(String(200))

    check_number = Column(String(100))
    check_bank = Column(String(100))
    check_due_date = Column(DateTime)
    card_holder = Column(String(100))
    card_expiry = Column(String(10))
    card_last4 = Column(String(4))
    bank_transfer_ref = Column(String(100))

    created_by = Column(Integer, ForeignKey("users.id"), index=True)
    creator = relationship("User", backref="payments_created", foreign_keys=[created_by])

    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), index=True)
    partner_id = Column(Integer, ForeignKey("partners.id", ondelete="CASCADE"), index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), index=True)
    loan_settlement_id = Column(Integer, ForeignKey("supplier_loan_settlements.id", ondelete="CASCADE"), index=True)
    sale_id = Column(Integer, ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    preorder_id = Column(Integer, ForeignKey("preorders.id", ondelete="CASCADE"), index=True)
    service_id = Column(Integer, ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)

    refund_of_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"))
    is_refunded = Column(Boolean, default=False, nullable=False, index=True)
    idempotency_key = Column(String(64), unique=True, index=True)
    
    # حقول الأرشيف
    is_archived = Column(Boolean, default=False, nullable=False, index=True)
    archived_at = Column(DateTime, index=True)
    archived_by = Column(Integer, ForeignKey("users.id"), index=True)
    archive_reason = Column(String(200))

    customer = relationship("Customer", back_populates="payments")
    supplier = relationship("Supplier", back_populates="payments")
    partner = relationship("Partner", back_populates="payments")
    shipment = relationship("Shipment", back_populates="payments")
    expense = relationship("Expense", back_populates="payments")
    loan_settlement = relationship("SupplierLoanSettlement", back_populates="payment")
    sale = relationship("Sale", back_populates="payments")
    invoice = relationship("Invoice", back_populates="payments")
    preorder = relationship("PreOrder", back_populates="payments")
    service = relationship("ServiceRequest", back_populates="payments")
    refund_of = relationship("Payment", remote_side=[id])
    archived_by_user = relationship("User", foreign_keys=[archived_by])

    splits = relationship("PaymentSplit", back_populates="payment", cascade="all,delete-orphan", passive_deletes=True, order_by="PaymentSplit.id")

    gl_batches = relationship(
        "GLBatch",
        primaryjoin="and_(foreign(GLBatch.source_id)==Payment.id, GLBatch.source_type=='PAYMENT')",
        viewonly=True,
        order_by="GLBatch.id",
    )

    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_payment_total_positive"),
        CheckConstraint("""(
            (CASE WHEN customer_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN supplier_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN partner_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN shipment_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN expense_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN loan_settlement_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN sale_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN invoice_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN preorder_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN service_id IS NOT NULL THEN 1 ELSE 0 END)
        ) <= 1""", name="ck_payment_one_target"),
        db.Index("ix_pay_sale_status_dir", "sale_id", "status", "direction"),
        db.Index("ix_pay_inv_status_dir", "invoice_id", "status", "direction"),
        db.Index("ix_pay_supplier_status_dir", "supplier_id", "status", "direction"),
        db.Index("ix_pay_partner_status_dir", "partner_id", "status", "direction"),
        db.Index("ix_pay_preorder_status_dir", "preorder_id", "status", "direction"),
        db.Index("ix_pay_supplier_dir_status_date", "supplier_id", "direction", "status", "payment_date"),
        db.Index("ix_pay_partner_dir_status_date", "partner_id", "direction", "status", "payment_date"),
        db.Index("ix_pay_customer_dir_status_date", "customer_id", "direction", "status", "payment_date"),
        db.Index("ix_pay_reversal", "refund_of_id"),
        db.Index("ix_pay_dir_stat_type", "direction", "status", "entity_type"),
        db.Index("ix_pay_status", "status"),
        db.Index("ix_pay_direction", "direction"),
        db.Index("ix_pay_currency", "currency"),
        db.Index("ix_pay_created_at", "payment_date"),
        db.Index("ix_pay_cust_stat_dir", "customer_id", "status", "direction"),
        db.Index("ix_pay_srv_stat_dir", "service_id", "status", "direction"),
        db.Index("ix_pay_shp_stat_dir", "shipment_id", "status", "direction"),
        db.Index("ix_pay_exp_stat_dir", "expense_id", "status", "direction"),
        db.Index("ix_pay_method_date", "method", "payment_date"),
        db.Index("ix_pay_created_by", "created_by"),
        db.Index("ix_pay_total_amount", "total_amount"),
    )

    @property
    def entity(self):
        for attr in ("customer", "supplier", "partner", "shipment", "expense", "loan_settlement", "sale", "invoice", "preorder", "service"):
            if getattr(self, f"{attr}_id", None):
                obj = getattr(self, attr, None)
                if obj is not None:
                    return obj
                raise ValueError("Bad link")
        raise ValueError("No link")

    def entity_label(self):
        if self.customer: return f"العميل: {self.customer.name}"
        if self.supplier: return f"المورد: {self.supplier.name}"
        if self.partner: return f"الشريك: {self.partner.name}"
        if self.invoice:
            parts = [f"فاتورة #{self.invoice.invoice_number or self.invoice.id}"]
            for attr, label in (("customer", "العميل"), ("supplier", "المورد"), ("partner", "الشريك")):
                obj = getattr(self.invoice, attr, None)
                if obj:
                    parts.append(f"{label}: {obj.name}")
                    break
            return " — ".join(parts)
        if self.sale:
            parts = [f"فاتورة مبيعات #{self.sale.sale_number or self.sale.id}"]
            customer = getattr(self.sale, "customer", None)
            if customer:
                parts.append(f"العميل: {customer.name}")
            return " — ".join(parts)
        if self.shipment: return f"شحنة #{self.shipment.shipment_number or self.shipment.id}"
        if self.service:
            identifier = self.service.service_number or self.service.id
            vehicle_info = self.service.vehicle_model or self.service.vehicle_vrn or getattr(getattr(self.service, "vehicle_type", None), "name", None)
            customer_name = getattr(getattr(self.service, "customer", None), "name", None)
            parts = []
            if vehicle_info:
                parts.append(f"المركبة: {vehicle_info}")
            if customer_name:
                parts.append(f"العميل: {customer_name}")
            suffix = " — ".join(parts)
            return f"طلب صيانة #{identifier}" + (f" — {suffix}" if suffix else "")
        if self.preorder:
            parts = [f"طلب مسبق #{self.preorder.reference or self.preorder.id}"]
            for attr, label in (("customer", "العميل"), ("supplier", "المورد"), ("partner", "الشريك")):
                obj = getattr(self.preorder, attr, None)
                if obj:
                    parts.append(f"{label}: {obj.name}")
                    break
            return " — ".join(parts)
        if self.expense:
            parts = []
            expense_type_name = getattr(getattr(self.expense, "type", None), "name", None)
            if expense_type_name:
                parts.append(expense_type_name)
            payee = self.expense.paid_to or self.expense.payee_name or self.expense.beneficiary_name
            if payee:
                parts.append(payee)
            desc = self.expense.description
            if desc and desc not in parts:
                parts.append(desc)
            details = " - ".join([str(p).strip() for p in parts if p])
            if not details:
                details = f"#{self.expense.id}"
            return f"مصروف: {details}"
        if self.loan_settlement: return f"تسوية قرض #{self.loan_settlement.id}"
        return "غير مرتبط"

    @validates("payment_number", "receipt_number")
    def _v_norm_numbers(self, _, v):
        s = (v or "").strip()
        s = re.sub(r"\s+", "", s)
        return s.upper() or None

    @validates("subtotal", "tax_rate", "tax_amount", "total_amount")
    def _v_amounts(self, key, value):
        if value is None:
            return None if key in ("subtotal", "tax_rate", "tax_amount") else D("0.00")
        v = q(value)
        if key == "tax_rate" and (v < 0 or v > 100):
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        if key in ("subtotal", "tax_amount", "total_amount") and v < 0:
            field_names = {
                "subtotal": "المجموع الفرعي",
                "tax_amount": "مبلغ الضريبة",
                "total_amount": "المبلغ الإجمالي"
            }
            raise ValueError(f"{field_names.get(key, key)} لا يمكن أن يكون سالباً")
        return v

    @validates("method", "status", "direction", "entity_type")
    def _coerce_enums(self, key, value):
        return getattr(value, "value", value) if value else None

    @validates("currency")
    def _v_payment_currency(self, key, v):
        return ensure_currency((v or "ILS"))

    def to_dict(self):
        _v = lambda x: getattr(x, "value", x)
        _f = lambda x: float(q(x or 0))
        return {
            "id": self.id,
            "payment_number": self.payment_number,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "subtotal": _f(self.subtotal),
            "tax_rate": _f(self.tax_rate),
            "tax_amount": _f(self.tax_amount),
            "total_amount": _f(self.total_amount),
            "currency": self.currency,
            "method": _v(self.method),
            "status": _v(self.status),
            "direction": _v(self.direction),
            "entity_type": _v(self.entity_type),
            "entity_display": self.entity_label(),
            "reference": self.reference,
            "receipt_number": self.receipt_number,
            "notes": self.notes,
            "created_by": self.created_by,
            "customer_id": self.customer_id,
            "supplier_id": self.supplier_id,
            "partner_id": self.partner_id,
            "shipment_id": self.shipment_id,
            "expense_id": self.expense_id,
            "loan_settlement_id": self.loan_settlement_id,
            "sale_id": self.sale_id,
            "invoice_id": self.invoice_id,
            "preorder_id": self.preorder_id,
            "service_id": self.service_id,
            "refund_of_id": self.refund_of_id,
            "idempotency_key": self.idempotency_key,
            "splits": [s.to_dict() for s in self.splits or []],
        }

    def __repr__(self):
        return f"<Payment {self.payment_number or self.id} - {self.total_amount} {self.currency}>"


def _payment_target_fk_for_type(et: str) -> str | None:
    m = {
        "CUSTOMER": "customer_id",
        "SUPPLIER": "supplier_id",
        "PARTNER": "partner_id",
        "SHIPMENT": "shipment_id",
        "EXPENSE": "expense_id",
        "LOAN": "loan_settlement_id",
        "SALE": "sale_id",
        "INVOICE": "invoice_id",
        "PREORDER": "preorder_id",
        "SERVICE": "service_id",
    }
    return m.get((et or "").upper())


def _payment_detect_entity_type(target: "Payment") -> str | None:
    pairs = [
        ("SHIPMENT", target.shipment_id),
        ("EXPENSE", target.expense_id),
        ("LOAN", target.loan_settlement_id),
        ("SALE", target.sale_id),
        ("INVOICE", target.invoice_id),
        ("PREORDER", target.preorder_id),
        ("SERVICE", target.service_id),
        ("CUSTOMER", target.customer_id),
        ("SUPPLIER", target.supplier_id),
        ("PARTNER", target.partner_id),
    ]
    for et, vid in pairs:
        if vid:
            return et
    return None


def _payment_validate_linkage(target: "Payment") -> None:
    core_fields = [
        "shipment_id",
        "expense_id",
        "loan_settlement_id",
        "sale_id",
        "invoice_id",
        "preorder_id",
        "service_id",
    ]
    core_set = [f for f in core_fields if getattr(target, f, None)]
    if len(core_set) > 1:
        raise ValueError("payment.multiple_targets")

    et = getattr(target, "entity_type", None)
    if hasattr(et, "value"):
        et = et.value
    et = (et or "").upper()
    fk = _payment_target_fk_for_type(et)
    if fk and not getattr(target, fk, None):
        raise ValueError("payment.missing_target_fk")


_EXPENSE_LEDGER_BEHAVIORS = {"IMMEDIATE", "PARTIAL", "ON_ACCOUNT"}


def _expense_type_meta_from_connection(connection, expense_type_id: int | None) -> dict:
    """يُستدعى من داخل savepoint عند مزامنة GL للمصروف؛ عند الفشل يُترك الاستثناء لينتشر."""
    if not expense_type_id:
        return {}
    value = connection.execute(
        select(ExpenseType.fields_meta).where(ExpenseType.id == expense_type_id)
    ).scalar_one_or_none()
    return value if isinstance(value, dict) else {}


def _expense_type_ledger_settings(connection, expense_type_id: int | None) -> dict:
    meta = _expense_type_meta_from_connection(connection, expense_type_id)
    ledger = (meta.get("ledger") or {}) if isinstance(meta, dict) else {}
    behavior = str(meta.get("payment_behavior") or "IMMEDIATE").strip().upper()
    if behavior not in _EXPENSE_LEDGER_BEHAVIORS:
        behavior = "IMMEDIATE"

    def _code(value):
        return (str(value or "").strip().upper() or None)

    return {
        "expense_account": _code(ledger.get("expense_account")),
        "counterparty_account": _code(ledger.get("counterparty_account")),
        "cash_account": _code(ledger.get("cash_account")),
        "behavior": behavior,
    }


def _payment_expense_ledger(connection, payment: "Payment"):
    expense = getattr(payment, "expense", None)
    type_id = getattr(expense, "type_id", None)
    if not type_id and getattr(payment, "expense_id", None):
        try:
            type_id = connection.execute(
                select(Expense.type_id).where(Expense.id == payment.expense_id)
            ).scalar_one_or_none()
        except Exception:
            type_id = None
    if not type_id:
        return None
    return _expense_type_ledger_settings(connection, type_id)


def _expense_entity_pair(expense_obj):
    if getattr(expense_obj, "customer_id", None):
        return ("CUSTOMER", expense_obj.customer_id)
    if getattr(expense_obj, "supplier_id", None):
        return ("SUPPLIER", expense_obj.supplier_id)
    if getattr(expense_obj, "partner_id", None):
        return ("PARTNER", expense_obj.partner_id)
    if getattr(expense_obj, "employee_id", None):
        return ("EMPLOYEE", expense_obj.employee_id)
    payee_type = (getattr(expense_obj, "payee_type", "") or "").upper()
    payee_entity_id = getattr(expense_obj, "payee_entity_id", None)
    if payee_type in {"SUPPLIER", "PARTNER", "CUSTOMER", "EMPLOYEE"} and payee_entity_id:
        try:
            return (payee_type, int(payee_entity_id))
        except (TypeError, ValueError):
            return (payee_type, None)
    return (None, None)


_ALLOWED_TRANSITIONS = {
    "PENDING": {"COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": {"REFUNDED", "FAILED", "CANCELLED"},
    "FAILED": {"PENDING", "COMPLETED"},  # ✅ السماح بإعادة تقديم شيك مرفوض أو إكمال الدفعة عند تسوية الشيك أو وجود نقدي
    "CANCELLED": set(),
    "REFUNDED": set(),
}


def _payment_enforce_transition(old: str | None, new: str) -> None:
    o = (old or "PENDING").upper()
    n = (new or "").upper()
    if o == n:
        return
    allowed = _ALLOWED_TRANSITIONS.get(o, set())
    if n not in allowed:
        raise ValueError("payment.invalid_status_transition")


def _payment_entity_id_for(target: "Payment") -> int:
    et = (getattr(target, "entity_type", "") or "").upper()
    fk = _payment_target_fk_for_type(et)
    if fk:
        return int(getattr(target, fk) or 0)
    return 0


# ═══════════════════════════════════════════════════════════════════════
# 📊 Accounting Listeners - إنشاء GLBatch تلقائي للدفعات
# ═══════════════════════════════════════════════════════════════════════

@event.listens_for(Payment, "after_insert")
@event.listens_for(Payment, "after_update")
def _payment_clear_balance_cache(mapper, connection, target: "Payment"):
    try:
        from extensions import cache
        if target.customer_id:
            cache.delete(f"customer_balance_{target.customer_id}")
            cache.delete(f"entity_balance_CUSTOMER_{target.customer_id}")
        if target.supplier_id:
            cache.delete(f"entity_balance_SUPPLIER_{target.supplier_id}")
        if target.partner_id:
            cache.delete(f"entity_balance_PARTNER_{target.partner_id}")
    except Exception:
        pass

@event.listens_for(Payment, "after_delete")
def _payment_update_supplier_balance_on_delete(mapper, connection, target: "Payment"):
    try:
        if target.supplier_id:
            _queue_supplier_balance(target, target.supplier_id)
    except Exception:
        pass

def _payment_gl_upsert_core(connection, target: "Payment") -> None:
    """منطق إنشاء/تحديث قيد GL للدفعة (يُستدعى من معاملة منفصلة بعد commit)."""
    if hasattr(target, "_skip_gl_entry") and target._skip_gl_entry:
        return
    if "[SETTLED=true]" in (target.notes or ""):
        return
    if "[FROM_MANUAL_CHECK=true]" in (target.notes or ""):
        return
    splits_count = connection.execute(
        sa_text("SELECT COUNT(1) FROM payment_splits WHERE payment_id = :pid"),
        {"pid": target.id},
    ).scalar() or 0
    if splits_count > 0:
        split_ids = connection.execute(
            sa_text("SELECT id FROM payment_splits WHERE payment_id = :pid"),
            {"pid": target.id},
        ).scalars().all()
        for sid in split_ids:
            _payment_split_gl_batch_upsert_by_id(connection, split_id=int(sid))
        return
    if target.status in [PaymentStatus.FAILED.value, PaymentStatus.REFUNDED.value, PaymentStatus.CANCELLED.value] or getattr(target, "is_refunded", False):
        amount = float(target.total_amount or 0)
        if amount <= 0:
            return
        amount_ils = amount
        if target.currency and target.currency != "ILS":
            try:
                rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.payment_date or datetime.now(timezone.utc))
                if rate and rate > 0:
                    amount_ils = float(amount * float(rate))
            except Exception:
                pass
        method_val = getattr(target, "method", "CASH")
        if hasattr(method_val, "value"):
            method_val = method_val.value
        payment_method = str(method_val or "CASH").upper()
        cash_account = GL_ACCOUNTS.get(PAYMENT_GL_MAP.get(payment_method, "CASH"), "1000_CASH")
        direction = target.direction
        entity_type = target.entity_type or "OTHER"
        ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
        ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
        if direction == PaymentDirection.IN.value:
            if entity_type == "CUSTOMER":
                entries = [(ar_account, amount_ils, 0), (cash_account, 0, amount_ils)]
            else:
                entries = [(cash_account, 0, amount_ils), (ap_account, amount_ils, 0)]
        else:
            if entity_type == "SUPPLIER":
                entries = [(ap_account, 0, amount_ils), (cash_account, amount_ils, 0)]
            else:
                entries = [(cash_account, 0, amount_ils), (ar_account, amount_ils, 0)]
        _gl_upsert_batch_and_entries(
            connection,
            source_type="PAYMENT_CANCELLATION",
            source_id=target.id,
            purpose="REVERSAL",
            currency="ILS",
            memo=f"Reversal - cancelled payment #{target.id}",
            entries=entries,
            ref=f"REV-CANCEL-PAY-{target.id}",
            entity_type=entity_type,
            entity_id=target.customer_id or target.supplier_id or target.partner_id,
        )
        return
    if target.status not in [PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value]:
        return
    is_pending_check = (
        target.status == PaymentStatus.PENDING.value
        and target.method == PaymentMethod.CHEQUE.value
    )
    amount = float(target.total_amount or 0)
    if amount <= 0:
        return
    amount_ils = amount
    if target.currency and target.currency != "ILS":
        try:
            rate = _fx_rate_local_via_connection(connection, target.currency, "ILS", target.payment_date or datetime.now(timezone.utc))
            if rate and rate > 0:
                amount_ils = float(amount * float(rate))
        except Exception:
            pass
    if is_pending_check:
        cash_account = "1150_CHQ_REC" if target.direction == PaymentDirection.IN.value else "2150_CHQ_PAY"
    elif target.method == PaymentMethod.BANK.value:
        cash_account = GL_ACCOUNTS.get("BANK", "1010_BANK")
    elif target.method == PaymentMethod.CARD.value:
        cash_account = GL_ACCOUNTS.get("CARD", "1020_CARD_CLEARING")
    else:
        cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")
    expense_ledger_ctx = _payment_expense_ledger(connection, target) if target.expense_id else None
    is_preorder = (
        (target.entity_type == PaymentEntityType.PREORDER.value if hasattr(PaymentEntityType, "PREORDER") else str(target.entity_type or "") == "PREORDER")
        or target.preorder_id
    )
    if is_preorder:
        entity_account = GL_ACCOUNTS.get("ADVANCE", "2300_ADV_PAY")
        entity_name = "Advance"
    elif target.entity_type == PaymentEntityType.SUPPLIER.value or target.supplier_id:
        entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
        entity_name = "Supplier"
    elif target.entity_type == PaymentEntityType.PARTNER.value or target.partner_id:
        entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
        entity_name = "Partner"
    elif target.entity_type == PaymentEntityType.EXPENSE.value or target.expense_id:
        entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
        entity_name = "Expense"
    elif target.service_id or target.sale_id or target.invoice_id or target.customer_id:
        entity_account = GL_ACCOUNTS.get("AR", "1100_AR")
        entity_name = "Customer"
    else:
        entity_account = GL_ACCOUNTS.get("AR", "1100_AR")
        entity_name = "Customer"
    if expense_ledger_ctx:
        if expense_ledger_ctx.get("counterparty_account"):
            entity_account = expense_ledger_ctx["counterparty_account"]
        elif expense_ledger_ctx.get("behavior") == "IMMEDIATE" and expense_ledger_ctx.get("cash_account"):
            entity_account = expense_ledger_ctx["cash_account"]
        if not is_pending_check and expense_ledger_ctx.get("cash_account"):
            cash_account = expense_ledger_ctx["cash_account"]
    if target.direction == PaymentDirection.IN.value:
        entries = [(cash_account, amount_ils, 0), (entity_account, 0, amount_ils)]
        memo = f"Payment IN from {entity_name} - {target.payment_number or target.id}"
    else:
        entries = [(entity_account, amount_ils, 0), (cash_account, 0, amount_ils)]
        memo = f"Payment OUT to {entity_name} - {target.payment_number or target.id}"
    entity_type_for_gl = target.entity_type
    entity_id_for_gl = _payment_entity_id_for(target)
    if target.expense_id:
        exp_entity_type = None
        exp_entity_id = None
        expense_obj = getattr(target, "expense", None)
        if expense_obj is not None:
            exp_entity_type, exp_entity_id = _expense_entity_pair(expense_obj)
        else:
            try:
                exp_row = connection.execute(
                    sa_text("""
                        SELECT customer_id, supplier_id, partner_id, employee_id, payee_type, payee_entity_id
                        FROM expenses
                        WHERE id = :eid
                    """),
                    {"eid": int(target.expense_id)},
                ).mappings().first()
                if exp_row:
                    if exp_row.get("customer_id"):
                        exp_entity_type, exp_entity_id = "CUSTOMER", int(exp_row["customer_id"])
                    elif exp_row.get("supplier_id"):
                        exp_entity_type, exp_entity_id = "SUPPLIER", int(exp_row["supplier_id"])
                    elif exp_row.get("partner_id"):
                        exp_entity_type, exp_entity_id = "PARTNER", int(exp_row["partner_id"])
                    elif exp_row.get("employee_id"):
                        exp_entity_type, exp_entity_id = "EMPLOYEE", int(exp_row["employee_id"])
                    else:
                        payee_type = (str(exp_row.get("payee_type") or "")).strip().upper()
                        payee_entity_id = exp_row.get("payee_entity_id")
                        if payee_type in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"} and payee_entity_id:
                            exp_entity_type, exp_entity_id = payee_type, int(payee_entity_id)
            except Exception:
                pass
        if exp_entity_type and exp_entity_id:
            entity_type_for_gl = exp_entity_type
            entity_id_for_gl = exp_entity_id

    _gl_upsert_batch_and_entries(
        connection,
        source_type="PAYMENT",
        source_id=target.id,
        purpose="PREORDER_PAYMENT" if is_preorder else "PAYMENT",
        currency=DEFAULT_CURRENCY,
        memo=memo,
        entries=entries,
        ref=target.payment_number or f"PMT-{target.id}",
        entity_type=entity_type_for_gl,
        entity_id=entity_id_for_gl,
    )


def run_payment_gl_sync_after_commit(payment_id: int) -> None:
    """إنشاء/تحديث قيد GL للدفعة في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not payment_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session
        session = Session(db.engine)
        try:
            payment = session.get(Payment, payment_id)
            if not payment:
                return
            _payment_gl_upsert_core(session.connection(), payment)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        if current_app:
            current_app.logger.warning("Payment GL sync failed for payment_id=%s: %s", payment_id, e, exc_info=True)


def build_payment_reversal_snapshot(payment: "Payment") -> dict:
    """لقطة بيانات الدفعة لاستخدامها في قيد العكس بعد الحذف."""
    try:
        expense_entity_type = None
        expense_entity_id = None
        expense_obj = getattr(payment, "expense", None)
        if getattr(payment, "expense_id", None) and expense_obj is not None:
            expense_entity_type, expense_entity_id = _expense_entity_pair(expense_obj)
        return {
            "payment_id": payment.id,
            "amount": float(payment.total_amount or 0),
            "currency": payment.currency or DEFAULT_CURRENCY,
            "payment_date": getattr(payment, "payment_date", None),
            "direction": getattr(payment, "direction", None),
            "entity_type": getattr(payment, "entity_type", None),
            "customer_id": getattr(payment, "customer_id", None),
            "supplier_id": getattr(payment, "supplier_id", None),
            "partner_id": getattr(payment, "partner_id", None),
            "expense_id": getattr(payment, "expense_id", None),
            "expense_entity_type": expense_entity_type,
            "expense_entity_id": expense_entity_id,
            "method": getattr(payment, "method", "CASH"),
        }
    except Exception:
        return {"payment_id": getattr(payment, "id", None), "amount": 0}


def run_payment_gl_reversal_after_delete(snapshot: dict) -> None:
    """تسجيل قيد عكسي PAYMENT_REVERSAL بعد حذف الدفعة، في معاملة منفصلة."""
    if not snapshot or not snapshot.get("payment_id"):
        return
    try:
        from extensions import db
        payment_id = int(snapshot["payment_id"])
        amount = float(snapshot.get("amount") or 0)
        if amount <= 0:
            return
        currency = (str(snapshot.get("currency") or DEFAULT_CURRENCY).strip().upper() or DEFAULT_CURRENCY)
        amount_ils = amount
        if currency != DEFAULT_CURRENCY:
            try:
                with db.engine.connect() as c:
                    rate = _fx_rate_local_via_connection(c, currency, DEFAULT_CURRENCY, snapshot.get("payment_date") or datetime.now(timezone.utc))
                    if rate and rate > 0:
                        amount_ils = amount * float(rate)
            except Exception:
                pass
        method_val = snapshot.get("method", "CASH")
        if hasattr(method_val, "value"):
            method_val = method_val.value
        payment_method = str(method_val or "CASH").upper()
        cash_account = GL_ACCOUNTS.get(PAYMENT_GL_MAP.get(payment_method, "CASH"), "1000_CASH")
        direction_raw = snapshot.get("direction")
        direction = str(getattr(direction_raw, "value", direction_raw) or "OUT").upper()
        entity_type = str(snapshot.get("entity_type") or "").strip().upper()
        ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
        ap_account = GL_ACCOUNTS.get("AP", "2000_AP")
        if direction == "IN":
            if entity_type == "CUSTOMER":
                entries = [(ar_account, amount_ils, 0), (cash_account, 0, amount_ils)]
            else:
                entries = [(cash_account, 0, amount_ils), (ap_account, amount_ils, 0)]
        else:
            if entity_type == "SUPPLIER":
                entries = [(ap_account, 0, amount_ils), (cash_account, amount_ils, 0)]
            else:
                entries = [(cash_account, 0, amount_ils), (ar_account, amount_ils, 0)]
        entity_id = snapshot.get("customer_id") or snapshot.get("supplier_id") or snapshot.get("partner_id")
        expense_entity_type = snapshot.get("expense_entity_type")
        expense_entity_id = snapshot.get("expense_entity_id")
        if (not entity_type or entity_type == "OTHER") and expense_entity_type:
            entity_type = str(expense_entity_type).strip().upper()
        if not entity_id and expense_entity_id:
            entity_id = expense_entity_id
        if not entity_type:
            entity_type = "OTHER"
        try:
            entity_id = int(entity_id) if entity_id is not None else None
        except (TypeError, ValueError):
            entity_id = None
        with db.engine.connect() as conn:
            with conn.begin():
                _gl_upsert_batch_and_entries(
                    conn,
                    source_type="PAYMENT_REVERSAL",
                    source_id=payment_id,
                    purpose="REVERSAL",
                    currency=DEFAULT_CURRENCY,
                    memo=f"Reversal - deleted payment #{payment_id}",
                    entries=entries,
                    ref=f"REV-PAY-{payment_id}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
    except Exception as e:
        if current_app:
            current_app.logger.warning("Payment GL reversal failed for payment_id=%s: %s", snapshot.get("payment_id"), e, exc_info=True)


@event.listens_for(Payment, "after_update")
def _payment_gl_batch_upsert(mapper, connection, target: "Payment"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_payment_gl_sync_after_commit."""
    return


@event.listens_for(Payment, "before_delete")
def _payment_gl_batch_reverse(mapper, connection, target: "Payment"):
    """معطّل: القيد العكسي يُنفّذ من المسار بعد الحذف عبر run_payment_gl_reversal_after_delete."""
    return


@event.listens_for(Payment, "after_insert", propagate=True)
def _payment_create_check_auto(mapper, connection, target: "Payment"):
    """✅ إنشاء سجل Check تلقائياً عند إنشاء دفعة بطريقة شيك"""
    try:
        # فحص طريقة الدفع
        method_str = str(getattr(target, 'method', '')).upper()
        if 'CHECK' not in method_str and 'CHEQUE' not in method_str:
            return
        
        # فحص معلومات الشيك
        check_number = (getattr(target, 'check_number', None) or '').strip()
        check_bank = (getattr(target, 'check_bank', None) or '').strip()
        
        if not check_number or not check_bank:
            return
        
        # تحويل check_due_date
        check_due_date = getattr(target, 'check_due_date', None)
        if not check_due_date:
            payment_date = getattr(target, 'payment_date', None)
            check_due_date = payment_date or datetime.now(timezone.utc)
        
        # التحقق من created_by_id
        created_by_id = getattr(target, 'created_by', None)
        if not created_by_id or created_by_id == 0:
            # جلب أول مستخدم كـ fallback
            from models import User
            first_user_result = connection.execute(
                sa_text("SELECT id FROM users ORDER BY id LIMIT 1")
            ).scalar()
            created_by_id = first_user_result if first_user_result else 1
        
        # ✅ تحديد الجهة المرتبطة (customer/supplier/partner)
        customer_id = getattr(target, 'customer_id', None)
        supplier_id = getattr(target, 'supplier_id', None)
        partner_id = getattr(target, 'partner_id', None)
        
        # إذا لم يكن هناك customer_id مباشر، جرّب من Sale
        if not customer_id and not supplier_id and not partner_id:
            sale_id = getattr(target, 'sale_id', None)
            if sale_id:
                sale_row = connection.execute(
                    sa_text("SELECT customer_id FROM sales WHERE id = :sid"),
                    {"sid": sale_id}
                ).fetchone()
                if sale_row:
                    customer_id = sale_row[0]
        
        check_currency = (getattr(target, 'currency', None) or DEFAULT_CURRENCY).upper()
        check_values = {
            "check_number": check_number,
            "check_bank": check_bank,
            "check_date": getattr(target, 'payment_date', None) or datetime.now(timezone.utc),
            "check_due_date": check_due_date,
            "amount": float(getattr(target, 'total_amount', 0) or 0),
            "currency": check_currency,
            "direction": str(getattr(target, 'direction', 'IN')).upper(),
            "status": 'PENDING',
            "payment_id": target.id,
            "customer_id": customer_id,
            "supplier_id": supplier_id,
            "partner_id": partner_id,
            "reference_number": f"PMT-{target.id}",
            "notes": f"شيك من دفعة رقم {getattr(target, 'payment_number', None) or target.id}",
            "created_by_id": created_by_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        check_values.update(_compute_issue_fx_fields(connection, check_currency, check_values.get("check_date")))

        connection.execute(Check.__table__.insert().values(**check_values))
        
        from flask import current_app
        current_app.logger.info(f"✅ تم إنشاء سجل شيك رقم {check_number} من دفعة #{target.id}")
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ فشل إنشاء سجل شيك من دفعة #{target.id}: {str(e)}")


class PaymentSplit(db.Model):
    __tablename__ = "payment_splits"

    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    method = Column(sa_str_enum(PaymentMethod, name="split_payment_method"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    details = Column(db.JSON, default=dict, nullable=False)
    currency = Column(String(10), nullable=False, default=DEFAULT_CURRENCY)
    converted_amount = Column(Numeric(12, 2), nullable=False, default=D("0.00"))
    converted_currency = Column(String(10), nullable=False, default=DEFAULT_CURRENCY)
    fx_rate_used = Column(Numeric(10, 6))
    fx_rate_source = Column(String(20))
    fx_rate_timestamp = Column(DateTime)
    fx_base_currency = Column(String(10))
    fx_quote_currency = Column(String(10))

    payment = relationship("Payment", back_populates="splits")

    __table_args__ = (CheckConstraint("amount > 0", name="chk_split_amount_positive"),)

    @validates("currency")
    def _v_split_currency(self, _, value):
        return ensure_currency(value or DEFAULT_CURRENCY)

    @validates("converted_currency")
    def _v_split_converted_currency(self, _, value):
        return ensure_currency(value or DEFAULT_CURRENCY)

    @validates("fx_base_currency", "fx_quote_currency")
    def _v_split_fx_currencies(self, key, value):
        if not value:
            return None
        return ensure_currency(value)

    @validates("converted_amount")
    def _v_split_converted_amount(self, _, value):
        if value is None:
            return D("0.00")
        v = q(value)
        if v < 0:
            raise ValueError("converted_amount must be non-negative")
        return v

    def clean_details(self):
        if not isinstance(self.details, dict):
            try:
                if isinstance(self.details, str):
                    self.details = json.loads(self.details)
                else:
                    self.details = {}
            except Exception:
                self.details = {}
        self.details = {k: v for k, v in self.details.items() if v not in (None, "", [])}

    def label(self):
        self.clean_details()
        m = getattr(self.method, "value", self.method)
        names = {
            PaymentMethod.CASH.value: "نقدًا",
            PaymentMethod.CHEQUE.value: "شيك",
            PaymentMethod.CARD.value: "بطاقة",
            PaymentMethod.BANK.value: "تحويل بنكي",
            PaymentMethod.ONLINE.value: "دفع إلكتروني",
        }
        return f"{names.get(m, m)} - {q(self.amount):,.2f}"

    def __repr__(self):
        return f"<PaymentSplit {self.label()}>"

    def to_dict(self):
        self.clean_details()
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "method": getattr(self.method, "value", self.method),
            "amount": float(q(self.amount)),
            "currency": self.currency,
            "converted_amount": float(q(self.converted_amount)),
            "converted_currency": self.converted_currency,
            "fx_rate_used": float(self.fx_rate_used) if self.fx_rate_used is not None else None,
            "fx_rate_source": self.fx_rate_source,
            "fx_rate_timestamp": self.fx_rate_timestamp.isoformat() if self.fx_rate_timestamp else None,
            "fx_base_currency": self.fx_base_currency,
            "fx_quote_currency": self.fx_quote_currency,
            "details": self.details,
            "label": self.label(),
        }


def _next_payment_number(connection) -> str:
    prefix = datetime.now(timezone.utc).strftime("PMT%Y%m%d")
    # استخدام MAX بدلاً من COUNT لتجنب التكرار
    result = connection.execute(
        sa_text("SELECT payment_number FROM payments WHERE payment_number LIKE :pfx ORDER BY payment_number DESC LIMIT 1"), 
        {"pfx": f"{prefix}-%"}
    ).scalar()
    
    if result:
        # استخراج الرقم الأخير وزيادته
        try:
            last_num = int(result.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    # محاولة إنشاء رقم فريد، وفي حالة الفشل نحاول حتى نجد رقم متاح
    max_attempts = 100
    for attempt in range(max_attempts):
        candidate = f"{prefix}-{next_num:04d}"
        # التحقق من عدم وجود الرقم
        exists = connection.execute(
            sa_text("SELECT 1 FROM payments WHERE payment_number = :num LIMIT 1"),
            {"num": candidate}
        ).scalar()
        if not exists:
            return candidate
        next_num += 1
    
    # في حالة الفشل، استخدم timestamp
    import time
    return f"{prefix}-{int(time.time() * 1000) % 10000:04d}"


@event.listens_for(Payment, "before_insert")
@event.listens_for(Payment, "before_update")
def _payment_policy_shipment(mapper, connection, t: "Payment"):
    et = getattr(t, "entity_type", None)
    if hasattr(et, "value"):
        et = et.value
    if (et or "").upper() != "SHIPMENT":
        return
    if not getattr(t, "shipment_id", None):
        raise ValueError("shipment_id مطلوب عند entity_type=SHIPMENT")
    dirv = getattr(t, "direction", None)
    if hasattr(dirv, "value"):
        dirv = dirv.value
    dirv = (dirv or "").upper()
    if dirv == "OUT":
        return
    if dirv == "IN":
        ref = (getattr(t, "reference", None) or "").strip()
        notes = (getattr(t, "notes", None) or "").strip()
        if not (ref or notes):
            raise ValueError("لا يُسمح بقبض لشحنة إلا كتعويض/استرداد مع توثيق السبب في reference أو notes")
        return
    raise ValueError("اتجاه غير مسموح لدفعات الشحن")


@event.listens_for(Payment, "before_insert", propagate=True)
def _payment_before_insert(mapper, connection, target: "Payment"):
    if not getattr(target, "payment_number", None):
        target.payment_number = _next_payment_number(connection)
    for k in ("method", "status", "direction", "entity_type"):
        v = getattr(target, k, None)
        if v is not None:
            setattr(target, k, getattr(v, "value", v))
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")
    
    payment_currency = target.currency
    default_currency = "ILS"
    
    if payment_currency != default_currency:
        try:
            at = getattr(target, "payment_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, payment_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = payment_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass
    
    detected = _payment_detect_entity_type(target)
    if detected:
        target.entity_type = detected
    _payment_validate_linkage(target)
    et = target.entity_type
    eid = _payment_entity_id_for(target)
    validate_payment_policies(
        entity_type=et,
        entity_id=eid,
        direction=getattr(target, "direction", PaymentDirection.IN),
        amount=getattr(target, "total_amount", 0),
        currency=getattr(target, "currency", "ILS"),
    )
    from utils.payment_allocation_policy import enforce_open_item_payment_booking
    enforce_open_item_payment_booking(target)


@event.listens_for(Payment, "before_update", propagate=True)
def _payment_before_update(mapper, connection, target: "Payment"):
    from sqlalchemy.orm.attributes import get_history
    for k in ("method", "status", "direction", "entity_type"):
        v = getattr(target, k, None)
        if v is not None:
            setattr(target, k, getattr(v, "value", v))
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")
    detected = _payment_detect_entity_type(target)
    if detected:
        target.entity_type = detected
    _payment_validate_linkage(target)
    h = get_history(target, "status")
    prev = (h.deleted[0] if h.deleted else getattr(target, "status", None))
    _payment_enforce_transition(prev, getattr(target, "status", None))
    et = target.entity_type
    eid = _payment_entity_id_for(target)
    validate_payment_policies(
        entity_type=et,
        entity_id=eid,
        direction=getattr(target, "direction", PaymentDirection.IN),
        amount=getattr(target, "total_amount", 0),
        currency=getattr(target, "currency", "ILS"),
    )
    from utils.payment_allocation_policy import enforce_open_item_payment_booking
    enforce_open_item_payment_booking(target)


@event.listens_for(Payment, "before_insert")
@event.listens_for(Payment, "before_update")
def _payment_refund_guard(mapper, connection, t: "Payment"):
    rid = getattr(t, "refund_of_id", None)
    if not rid:
        return
    row = connection.execute(
        sa_text("""
            SELECT id, total_amount, currency, direction, entity_type,
                   customer_id, supplier_id, partner_id, shipment_id,
                   expense_id, loan_settlement_id, sale_id, invoice_id,
                   preorder_id, service_id
              FROM payments
             WHERE id = :rid
        """),
        {"rid": rid},
    ).mappings().first()
    if not row:
        raise ValueError("دفعة الأصل غير موجودة للاسترداد")
    if (row["currency"] or "").upper() != (getattr(t, "currency", None) or "ILS").upper():
        raise ValueError("عملة الاسترداد يجب أن تطابق دفعة الأصل")
    dirv = (getattr(t, "direction", "") or "")
    if hasattr(dirv, "value"):
        dirv = dirv.value
    dirv = dirv.upper()
    orig_dir = (row["direction"] or "").upper()
    if orig_dir == "IN" and dirv != "OUT":
        raise ValueError("استرداد دفعة IN يجب أن يكون OUT")
    if orig_dir == "OUT" and dirv != "IN":
        raise ValueError("استرداد دفعة OUT يجب أن يكون IN")
    for fk in ("customer_id","supplier_id","partner_id","shipment_id","expense_id","loan_settlement_id","sale_id","invoice_id","preorder_id","service_id"):
        if getattr(t, fk) != row[fk]:
            raise ValueError("هدف الاسترداد يجب أن يطابق دفعة الأصل")
    used = connection.execute(
        sa_text("""
            SELECT COALESCE(SUM(total_amount),0) AS s
              FROM payments
             WHERE refund_of_id = :rid
               AND id <> COALESCE(:cid, -1)
               AND status IN ('PENDING','COMPLETED')
        """),
        {"rid": rid, "cid": getattr(t, "id", None)},
    ).scalar() or 0
    if Decimal(str(used)) + Decimal(str(t.total_amount or 0)) - Decimal(str(row["total_amount"])) > Decimal("0"):
        raise ValueError("قيمة الاسترداد تتجاوز المبلغ الأصلي")


@event.listens_for(PaymentSplit, "before_insert", propagate=True)
@event.listens_for(PaymentSplit, "before_update", propagate=True)
def _split_before_save(mapper, connection, target: "PaymentSplit"):
    target.amount = q(target.amount)
    m = getattr(target, "method", None)
    if hasattr(m, "value"):
        target.method = m.value
    if not isinstance(target.details, dict) or target.details is None:
        target.details = {}
    else:
        target.details = {k: v for k, v in target.details.items() if v not in (None, "", [])}


@event.listens_for(PaymentSplit, "after_insert", propagate=True)
def _payment_split_create_check_auto(mapper, connection, target: "PaymentSplit"):
    """✅ إنشاء سجل Check تلقائياً عند إنشاء دفعة جزئية بطريقة شيك"""
    try:
        # فحص طريقة الدفع
        method_str = str(getattr(target, 'method', '')).upper()
        if 'CHECK' not in method_str and 'CHEQUE' not in method_str:
            return
        
        # جلب معلومات الشيك من details
        details = getattr(target, 'details', {}) or {}
        if not isinstance(details, dict):
            try:
                import json
                details = json.loads(details) if isinstance(details, str) else {}
            except Exception:
                details = {}
        
        check_number = (details.get('check_number', '') or '').strip()
        check_bank = (details.get('check_bank', '') or '').strip()
        
        if not check_number or not check_bank:
            return
        
        # جلب معلومات الدفعة الأصلية
        payment_row = connection.execute(
            sa_text("""
                SELECT id, payment_number, payment_date, currency, direction, 
                       customer_id, supplier_id, partner_id, created_by
                FROM payments 
                WHERE id = :pid
            """),
            {"pid": target.payment_id}
        ).mappings().first()
        
        if not payment_row:
            return
        
        def _coerce_datetime(value):
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if isinstance(value, date):
                return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
            if isinstance(value, str):
                parsed = None
                try:
                    from dateutil import parser as date_parser
                    parsed = date_parser.isoparse(value)
                except Exception:
                    try:
                        parsed = datetime.fromisoformat(value)
                    except Exception:
                        parsed = None
                if parsed and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            return None
        
        payment_date = _coerce_datetime(payment_row['payment_date']) or datetime.now(timezone.utc)
        check_due_date = _coerce_datetime(details.get('check_due_date')) or payment_date
        
        # التحقق من created_by_id
        created_by_id = payment_row['created_by']
        if not created_by_id or created_by_id == 0:
            first_user_result = connection.execute(
                sa_text("SELECT id FROM users ORDER BY id LIMIT 1")
            ).scalar()
            created_by_id = first_user_result if first_user_result else 1
        
        # ✅ تحديد الجهة - من Payment أو Sale
        customer_id = payment_row['customer_id']
        supplier_id = payment_row['supplier_id']
        partner_id = payment_row['partner_id']
        
        # إذا لم يكن هناك جهة مباشرة، جرّب من Sale
        if not customer_id and not supplier_id and not partner_id:
            # البحث عن sale_id في Payment
            sale_id_row = connection.execute(
                sa_text("SELECT sale_id FROM payments WHERE id = :pid"),
                {"pid": target.payment_id}
            ).fetchone()
            
            if sale_id_row and sale_id_row[0]:
                sale_customer_row = connection.execute(
                    sa_text("SELECT customer_id FROM sales WHERE id = :sid"),
                    {"sid": sale_id_row[0]}
                ).fetchone()
                if sale_customer_row:
                    customer_id = sale_customer_row[0]
        
        with connection.begin_nested():
            connection.execute(
                Check.__table__.insert().values(
                    check_number=check_number,
                    check_bank=check_bank,
                    check_date=payment_date,
                    check_due_date=check_due_date,
                    amount=float(getattr(target, 'amount', 0) or 0),
                    currency=(payment_row['currency'] or 'ILS').upper(),
                    direction=str(payment_row['direction'] or 'IN').upper(),
                    status='PENDING',
                    payment_id=target.payment_id,
                    customer_id=customer_id,
                    supplier_id=supplier_id,
                    partner_id=partner_id,
                    reference_number=f"PMT-SPLIT-{target.id}",
                    notes=f"شيك من دفعة جزئية #{target.id} - دفعة رقم {payment_row['payment_number']}",
                    created_by_id=created_by_id,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
            )
        
        from flask import current_app
        current_app.logger.info(f"✅ تم إنشاء سجل شيك رقم {check_number} من دفعة جزئية #{target.id}")
    except Exception as e:
        from flask import current_app
        import traceback
        current_app.logger.warning(f"⚠️ فشل إنشاء سجل شيك من دفعة جزئية #{target.id}: {str(e)}")
        current_app.logger.error(traceback.format_exc())


@event.listens_for(PaymentSplit, "after_insert")
@event.listens_for(PaymentSplit, "after_update")
def _payment_split_gl_batch_upsert(mapper, connection, target: "PaymentSplit"):
    try:
        _payment_split_gl_batch_upsert_by_id(connection, split_id=int(getattr(target, "id", 0) or 0))
    except Exception:
        pass


@event.listens_for(PaymentSplit, "after_insert")
@event.listens_for(PaymentSplit, "after_update")
@event.listens_for(PaymentSplit, "after_delete")
def _payment_split_update_entity_balances(mapper, connection, target: "PaymentSplit"):
    try:
        session = _balance_get_session(target)
        payment_id = getattr(target, "payment_id", None)
        if not payment_id:
            return
        try:
            payment_id = int(payment_id)
        except Exception:
            return

        payment = None
        try:
            if session is not None:
                payment = session.get(Payment, payment_id)
        except Exception:
            payment = None

        if payment is not None:
            customer_ids = _get_customer_ids_from_payment(payment, session)
            for customer_id in customer_ids:
                _queue_customer_balance(session, customer_id)
            _queue_supplier_balance(session, getattr(payment, "supplier_id", None))
            _queue_partner_balance(session, getattr(payment, "partner_id", None))
            return

        row = connection.execute(
            sa_text(
                """
                SELECT id, customer_id, supplier_id, partner_id, sale_id, invoice_id, service_id, preorder_id
                FROM payments
                WHERE id = :pid
                """
            ),
            {"pid": payment_id},
        ).mappings().first()
        if not row:
            return

        _queue_customer_balance(session, row.get("customer_id"))
        _queue_supplier_balance(session, row.get("supplier_id"))
        _queue_partner_balance(session, row.get("partner_id"))

        if row.get("sale_id"):
            cid = connection.execute(
                sa_text("SELECT customer_id FROM sales WHERE id = :sid"),
                {"sid": int(row["sale_id"])},
            ).scalar()
            _queue_customer_balance(session, cid)
        if row.get("invoice_id"):
            cid = connection.execute(
                sa_text("SELECT customer_id FROM invoices WHERE id = :iid"),
                {"iid": int(row["invoice_id"])},
            ).scalar()
            _queue_customer_balance(session, cid)
        if row.get("service_id"):
            cid = connection.execute(
                sa_text("SELECT customer_id FROM service_requests WHERE id = :sid"),
                {"sid": int(row["service_id"])},
            ).scalar()
            _queue_customer_balance(session, cid)
        if row.get("preorder_id"):
            cid = connection.execute(
                sa_text("SELECT customer_id FROM preorders WHERE id = :pid"),
                {"pid": int(row["preorder_id"])},
            ).scalar()
            _queue_customer_balance(session, cid)
    except Exception:
        pass


def _payment_split_gl_batch_upsert_by_id(connection, *, split_id: int) -> None:
    if not split_id:
        return
    try:
        with connection.begin_nested():
            split_row = connection.execute(
                sa_text("""
                    SELECT id, payment_id, method, amount, currency, converted_amount, converted_currency, details
                    FROM payment_splits
                    WHERE id = :sid
                """),
                {"sid": split_id},
            ).mappings().first()
            if not split_row:
                return

            payment_row = connection.execute(
                sa_text("""
                    SELECT id, payment_number, payment_date, currency, direction, status,
                           customer_id, supplier_id, partner_id, entity_type, expense_id, created_by,
                           sale_id, invoice_id, service_id, preorder_id, shipment_id, is_refunded
                    FROM payments
                    WHERE id = :pid
                """),
                {"pid": split_row["payment_id"]},
            ).mappings().first()
            if not payment_row:
                return

            connection.execute(
                sa_text("DELETE FROM gl_batches WHERE source_type = 'PAYMENT' AND source_id = :pid"),
                {"pid": int(split_row["payment_id"])},
            )

            payment_status = str(payment_row["status"] or "").upper()
            if payment_status == PaymentStatus.FAILED.value:
                return
            if payment_status not in {
                PaymentStatus.COMPLETED.value,
                PaymentStatus.PENDING.value,
                PaymentStatus.REFUNDED.value,
                PaymentStatus.CANCELLED.value,
            }:
                return

            split_details = split_row.get("details") or {}
            if isinstance(split_details, str):
                try:
                    import json as _json
                    split_details = _json.loads(split_details)
                except Exception:
                    split_details = {}
            is_split_refunded = isinstance(split_details, dict) and bool(split_details.get("refunded") or False)
            is_refunded = (
                payment_status == PaymentStatus.REFUNDED.value
                or bool(payment_row.get("is_refunded") or False)
                or is_split_refunded
            )
            is_cancelled = payment_status == PaymentStatus.CANCELLED.value
            if not (is_refunded or is_cancelled):
                dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
                batch_table = "public.gl_batches" if dialect_name == "postgresql" else "gl_batches"
                entry_table = "public.gl_entries" if dialect_name == "postgresql" else "gl_entries"
                connection.execute(
                    sa_text(
                        f"""
                        DELETE FROM {entry_table}
                        WHERE batch_id IN (
                            SELECT id FROM {batch_table}
                            WHERE source_type = 'PAYMENT_SPLIT' AND source_id = :sid
                        )
                        """
                    ),
                    {"sid": int(split_id)},
                )
                connection.execute(
                    sa_text(
                        f"""
                        DELETE FROM {batch_table}
                        WHERE source_type = 'PAYMENT_SPLIT' AND source_id = :sid
                        """
                    ),
                    {"sid": int(split_id)},
                )

            amount = float(split_row["converted_amount"] or split_row["amount"] or 0)
            if amount <= 0:
                return

            split_currency = (split_row["converted_currency"] or split_row["currency"] or payment_row["currency"] or "ILS").upper()
            amount_ils = amount
            if split_currency != "ILS" and not float(split_row["converted_amount"] or 0):
                try:
                    rate = _fx_rate_local_via_connection(
                        connection,
                        split_currency,
                        "ILS",
                        payment_row["payment_date"] or datetime.now(timezone.utc),
                    )
                    if rate and float(rate) > 0:
                        amount_ils = float(amount * float(rate))
                except Exception:
                    pass

            split_method = str(split_row["method"] or PaymentMethod.CASH.value).strip().lower()
            is_check = ("check" in split_method) or ("cheque" in split_method)
            is_pending_check = (payment_status == PaymentStatus.PENDING.value and is_check)

            if is_pending_check:
                if payment_row["direction"] == PaymentDirection.IN.value:
                    cash_account = "1150_CHQ_REC"
                else:
                    cash_account = "2150_CHQ_PAY"
            elif split_method == PaymentMethod.BANK.value:
                cash_account = GL_ACCOUNTS.get("BANK", "1010_BANK")
            elif split_method == PaymentMethod.CARD.value:
                cash_account = GL_ACCOUNTS.get("CARD", "1020_CARD_CLEARING")
            else:
                cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")

            payment_entity_type = payment_row["entity_type"] or "OTHER"
            customer_id = payment_row["customer_id"]
            supplier_id = payment_row["supplier_id"]
            partner_id = payment_row["partner_id"]
            sale_id = payment_row.get("sale_id")
            invoice_id = payment_row.get("invoice_id")
            service_id = payment_row.get("service_id")
            preorder_id = payment_row.get("preorder_id")

            batch_entity_type = None
            batch_entity_id = None
            derived_customer_id = customer_id
            try:
                if not derived_customer_id and sale_id:
                    derived_customer_id = connection.execute(sa_text("SELECT customer_id FROM sales WHERE id=:id"), {"id": int(sale_id)}).scalar()
                if not derived_customer_id and invoice_id:
                    derived_customer_id = connection.execute(sa_text("SELECT customer_id FROM invoices WHERE id=:id"), {"id": int(invoice_id)}).scalar()
                if not derived_customer_id and service_id:
                    derived_customer_id = connection.execute(sa_text("SELECT customer_id FROM service_requests WHERE id=:id"), {"id": int(service_id)}).scalar()
                if not derived_customer_id and preorder_id:
                    derived_customer_id = connection.execute(sa_text("SELECT customer_id FROM preorders WHERE id=:id"), {"id": int(preorder_id)}).scalar()
            except Exception:
                pass

            if derived_customer_id:
                batch_entity_type = "CUSTOMER"
                batch_entity_id = int(derived_customer_id)
            elif supplier_id:
                batch_entity_type = "SUPPLIER"
                batch_entity_id = int(supplier_id)
            elif partner_id:
                batch_entity_type = "PARTNER"
                batch_entity_id = int(partner_id)
            elif payment_row.get("expense_id"):
                try:
                    exp_row = connection.execute(
                        sa_text("""
                            SELECT customer_id, supplier_id, partner_id, employee_id, payee_type, payee_entity_id
                            FROM expenses
                            WHERE id = :eid
                        """),
                        {"eid": int(payment_row["expense_id"])},
                    ).mappings().first()
                    if exp_row:
                        if exp_row.get("customer_id"):
                            batch_entity_type, batch_entity_id = "CUSTOMER", int(exp_row["customer_id"])
                        elif exp_row.get("supplier_id"):
                            batch_entity_type, batch_entity_id = "SUPPLIER", int(exp_row["supplier_id"])
                        elif exp_row.get("partner_id"):
                            batch_entity_type, batch_entity_id = "PARTNER", int(exp_row["partner_id"])
                        elif exp_row.get("employee_id"):
                            batch_entity_type, batch_entity_id = "EMPLOYEE", int(exp_row["employee_id"])
                        else:
                            payee_type = (str(exp_row.get("payee_type") or "")).strip().upper()
                            payee_entity_id = exp_row.get("payee_entity_id")
                            if payee_type in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"} and payee_entity_id:
                                batch_entity_type, batch_entity_id = payee_type, int(payee_entity_id)
                except Exception:
                    pass

            entity_account = GL_ACCOUNTS.get("AR", "1100_AR")
            entity_name = "عميل"

            if payment_entity_type == PaymentEntityType.SUPPLIER.value or supplier_id:
                entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                entity_name = "مورد"
            elif payment_entity_type == PaymentEntityType.PARTNER.value or partner_id:
                entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                entity_name = "شريك"
            elif payment_entity_type == PaymentEntityType.EXPENSE.value or payment_row["expense_id"]:
                entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                entity_name = "مصروف"

            expense_id = payment_row["expense_id"]
            if expense_id:
                try:
                    expense_type_id = connection.execute(
                        sa_text("SELECT type_id FROM expenses WHERE id = :eid"),
                        {"eid": expense_id},
                    ).scalar()
                    if expense_type_id:
                        expense_ledger_ctx = _expense_type_ledger_settings(connection, expense_type_id)
                        if expense_ledger_ctx:
                            lock_entity_account = batch_entity_type in {"CUSTOMER", "SUPPLIER", "PARTNER"}
                            if not lock_entity_account:
                                if expense_ledger_ctx.get("counterparty_account"):
                                    entity_account = expense_ledger_ctx["counterparty_account"]
                                elif expense_ledger_ctx.get("behavior") == "IMMEDIATE" and expense_ledger_ctx.get("cash_account"):
                                    entity_account = expense_ledger_ctx["cash_account"]
                            if not is_pending_check and expense_ledger_ctx.get("cash_account"):
                                cash_account = expense_ledger_ctx["cash_account"]
                except Exception:
                    pass

            if payment_row["direction"] == PaymentDirection.IN.value:
                entries = [(cash_account, amount_ils, 0), (entity_account, 0, amount_ils)]
                if is_pending_check:
                    memo = f"شيك معلق من {entity_name} - Split #{split_id} - {payment_row['payment_number'] or payment_row['id']}"
                else:
                    if split_method == PaymentMethod.CASH.value:
                        method_display = "نقد"
                    elif is_check:
                        method_display = "شيك"
                    else:
                        method_display = "بنك"
                    memo = f"قبض {method_display} من {entity_name} - Split #{split_id} - {payment_row['payment_number'] or payment_row['id']}"
            else:
                entries = [(entity_account, amount_ils, 0), (cash_account, 0, amount_ils)]
                if is_pending_check:
                    memo = f"شيك صادر لـ {entity_name} - Split #{split_id} - {payment_row['payment_number'] or payment_row['id']}"
                else:
                    if split_method == PaymentMethod.CASH.value:
                        method_display = "نقد"
                    elif is_check:
                        method_display = "شيك"
                    else:
                        method_display = "بنك"
                    memo = f"سداد {method_display} لـ {entity_name} - Split #{split_id} - {payment_row['payment_number'] or payment_row['id']}"

            original_batch_id = None
            if not is_cancelled:
                original_batch_id = _gl_upsert_batch_and_entries(
                    connection,
                    source_type="PAYMENT_SPLIT",
                    source_id=split_id,
                    purpose="PAYMENT",
                    currency="ILS",
                    memo=memo,
                    entries=entries,
                    ref=(f"SPLIT-{split_id}-PMT-{payment_row['payment_number'] or payment_row['id']}")[:50],
                    entity_type=batch_entity_type,
                    entity_id=batch_entity_id,
                )
            else:
                dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
                batch_table = "public.gl_batches" if dialect_name == "postgresql" else "gl_batches"
                original_batch_id = connection.execute(
                    sa_text(f"""
                        SELECT id FROM {batch_table}
                         WHERE source_type='PAYMENT_SPLIT' AND source_id=:sid AND purpose='PAYMENT' AND status='POSTED'
                         ORDER BY id DESC LIMIT 1
                    """),
                    {"sid": split_id},
                ).scalar()
                if original_batch_id:
                    original_batch_id = int(original_batch_id)

            if (is_refunded or is_cancelled) and original_batch_id:
                dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
                batch_table = "public.gl_batches" if dialect_name == "postgresql" else "gl_batches"
                entry_table = "public.gl_entries" if dialect_name == "postgresql" else "gl_entries"

                existing_rev = connection.execute(
                    sa_text(f"""
                        SELECT id FROM {batch_table}
                         WHERE source_type='PAYMENT_SPLIT' AND source_id=:sid AND purpose='PAYMENT_REVERSAL' AND status='POSTED'
                         ORDER BY id DESC LIMIT 1
                    """),
                    {"sid": split_id},
                ).scalar()
                if not existing_rev:
                    bmeta = connection.execute(
                        sa_text(f"SELECT currency, entity_type, entity_id, memo FROM {batch_table} WHERE id=:bid"),
                        {"bid": int(original_batch_id)},
                    ).mappings().first()

                    entry_rows = connection.execute(
                        sa_text(f"SELECT account, debit, credit FROM {entry_table} WHERE batch_id=:bid ORDER BY id"),
                        {"bid": int(original_batch_id)},
                    ).mappings().all()
                    rev_entries = []
                    for r in entry_rows:
                        acc = str(r["account"] or "").strip().upper()
                        d = float(r["debit"] or 0)
                        c = float(r["credit"] or 0)
                        if d <= 0 and c <= 0:
                            continue
                        rev_entries.append((acc, c, d))
                    if rev_entries:
                        memo_rev = f"عكس: {(bmeta or {}).get('memo') or memo}".strip()
                        _gl_upsert_batch_and_entries(
                            connection,
                            source_type="PAYMENT_SPLIT",
                            source_id=split_id,
                            purpose="PAYMENT_REVERSAL",
                            currency=(bmeta or {}).get("currency") or "ILS",
                            memo=memo_rev[:255],
                            entries=rev_entries,
                            ref=(f"REV-SPLIT-{split_id}-PMT-{payment_row['payment_number'] or payment_row['id']}")[:50],
                            entity_type=(bmeta or {}).get("entity_type") or batch_entity_type,
                            entity_id=(bmeta or {}).get("entity_id") or batch_entity_id,
                        )
    except Exception:
        return


# ===== تحديث total_paid و balance_due في Sales تلقائياً =====
def _update_sale_payment_totals(connection, sale_id):
    """تحديث total_paid و balance_due في جدول Sales"""
    if not sale_id:
        return
    
    # حساب total_paid من جدول Payments
    total_paid_result = connection.execute(
        sa_text("""
            SELECT COALESCE(SUM(total_amount), 0) 
            FROM payments 
            WHERE sale_id = :sale_id 
              AND direction = 'IN'
              AND status = 'COMPLETED'
        """),
        {"sale_id": sale_id}
    ).scalar() or 0
    
    # جلب total_amount من Sale
    sale_total = connection.execute(
        sa_text("SELECT total_amount FROM sales WHERE id = :sale_id"),
        {"sale_id": sale_id}
    ).scalar() or 0
    
    # حساب balance_due
    balance_due = float(sale_total) - float(total_paid_result)
    
    # تحديث الحقول في جدول Sales
    connection.execute(
        sa_text("""
            UPDATE sales 
            SET total_paid = :total_paid,
                balance_due = :balance_due,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :sale_id
        """),
        {
            "sale_id": sale_id,
            "total_paid": float(total_paid_result),
            "balance_due": balance_due
        }
    )


@event.listens_for(Payment, "after_insert", propagate=True)
@event.listens_for(Payment, "after_update", propagate=True)
@event.listens_for(Payment, "after_delete", propagate=True)
def _update_sale_on_payment_change(mapper, connection, target: "Payment"):
    if hasattr(target, 'sale_id') and target.sale_id:
        _update_sale_payment_totals(connection, target.sale_id)




def _avg_cost_until(product_id: int, supplier_id: int, as_of: datetime) -> Decimal:
    qsum = db.session.query(
        func.coalesce(func.sum(ExchangeTransaction.quantity * func.nullif(ExchangeTransaction.unit_cost, 0)), 0),
        func.coalesce(func.sum(ExchangeTransaction.quantity), 0)
    ).filter(
        ExchangeTransaction.product_id == product_id,
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.created_at <= as_of,
        ExchangeTransaction.direction.in_(("IN", "ADJUSTMENT")),
        func.coalesce(ExchangeTransaction.unit_cost, 0) > 0
    ).first()
    total_val = Decimal(str(qsum[0] or 0))
    total_qty = Decimal(str(qsum[1] or 0))
    if total_qty > 0:
        return (total_val / total_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    prod = db.session.get(Product, product_id) if product_id else None
    pp = Decimal(str(getattr(prod, "purchase_price", 0) or 0))
    if pp > 0:
        return pp.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal("0.00")


def _default_mode_for_supplier(supplier_id: int) -> str:
    sup = db.session.get(Supplier, supplier_id)
    terms = (getattr(sup, "payment_terms", "") or "").upper()
    if "CONSUME" in terms or "ON_CONSUME" in terms or "CONSUMPTION" in terms:
        return SupplierSettlementMode.ON_CONSUME.value
    return SupplierSettlementMode.ON_RECEIPT.value


def _used_sources_for_supplier(supplier_id: int):
    rows = (
        db.session.query(SupplierSettlementLine.source_type, SupplierSettlementLine.source_id)
        .join(SupplierSettlement, SupplierSettlement.id == SupplierSettlementLine.settlement_id)
        .filter(
            SupplierSettlement.supplier_id == supplier_id,
            SupplierSettlement.status == SupplierSettlementStatus.CONFIRMED.value
        ).all()
    )
    return {(r[0], int(r[1] or 0)) for r in rows if r[1] is not None}


def build_supplier_settlement_draft(
    supplier_id: int,
    date_from: datetime,
    date_to: datetime,
    *,
    currency: str = "ILS",
    mode: str | None = None
) -> SupplierSettlement:
    from sqlalchemy.orm import joinedload

    final_mode = (mode or _default_mode_for_supplier(supplier_id)).upper()
    ss = SupplierSettlement(
        supplier_id=supplier_id,
        from_date=date_from,
        to_date=date_to,
        currency=(currency or DEFAULT_CURRENCY).upper(),
        status=SupplierSettlementStatus.DRAFT.value,
        mode=final_mode
    )

    used = _used_sources_for_supplier(supplier_id)

    total_purchases = Decimal("0.00")
    total_returns = Decimal("0.00")
    total_loans = Decimal("0.00")
    total_consumption = Decimal("0.00")
    total_invoices = Decimal("0.00")

    if final_mode == SupplierSettlementMode.ON_RECEIPT.value:
        txs = (
            db.session.query(ExchangeTransaction)
            .join(Warehouse, Warehouse.id == ExchangeTransaction.warehouse_id)
            .options(joinedload(ExchangeTransaction.product))
            .filter(
                Warehouse.warehouse_type == WarehouseType.EXCHANGE.value,
                Warehouse.supplier_id == supplier_id,
                ExchangeTransaction.created_at >= date_from,
                ExchangeTransaction.created_at <= date_to,
            )
            .all()
        )
        for tx in txs:
            if ("EXCHANGE_PURCHASE", tx.id) in used or ("EXCHANGE_RETURN", tx.id) in used or ("EXCHANGE_ADJUST", tx.id) in used:
                continue
            dirv = (getattr(tx, "direction", "") or "").upper()
            qty = Decimal(str(tx.quantity or 0))
            unit_price = Decimal(str(tx.unit_cost or 0))
            cost_source = "TX_PRICE"
            if unit_price <= 0:
                unit_price = _avg_cost_until(tx.product_id, supplier_id, date_to)
                cost_source = "TX_AVG" if unit_price > 0 else "MISSING"
            amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            needs_pricing = bool(unit_price <= 0)
            if dirv == "IN":
                total_purchases += amount
                ss.lines.append(SupplierSettlementLine(
                    source_type="EXCHANGE_PURCHASE",
                    source_id=tx.id,
                    description=f"توريد تبادل #{tx.id}",
                    product_id=tx.product_id,
                    quantity=qty,
                    unit_price=unit_price if unit_price > 0 else None,
                    gross_amount=amount,
                    needs_pricing=needs_pricing,
                    cost_source=cost_source
                ))
            elif dirv == "OUT":
                total_returns += amount
                ss.lines.append(SupplierSettlementLine(
                    source_type="EXCHANGE_RETURN",
                    source_id=tx.id,
                    description=f"مرتجع تبادل #{tx.id}",
                    product_id=tx.product_id,
                    quantity=qty,
                    unit_price=unit_price if unit_price > 0 else None,
                    gross_amount=amount,
                    needs_pricing=needs_pricing,
                    cost_source=cost_source
                ))
            elif dirv == "ADJUSTMENT":
                total_purchases += amount
                ss.lines.append(SupplierSettlementLine(
                    source_type="EXCHANGE_ADJUST",
                    source_id=tx.id,
                    description=f"تسوية مخزون (تبادل) #{tx.id}",
                    product_id=tx.product_id,
                    quantity=qty,
                    unit_price=unit_price if unit_price > 0 else None,
                    gross_amount=amount,
                    needs_pricing=needs_pricing,
                    cost_source=cost_source
                ))

    if final_mode == SupplierSettlementMode.ON_CONSUME.value:
        s_lines = (
            db.session.query(SaleLine)
            .join(Warehouse, Warehouse.id == SaleLine.warehouse_id)
            .filter(
                Warehouse.warehouse_type == WarehouseType.EXCHANGE.value,
                Warehouse.supplier_id == supplier_id,
                SaleLine.created_at >= date_from,
                SaleLine.created_at <= date_to
            ).all()
        )
        for sl in s_lines:
            if ("CONSUME_SALE", sl.id) in used:
                continue
            qty = Decimal(str(sl.quantity or 0))
            unit_price = _avg_cost_until(sl.product_id, supplier_id, date_to)
            cost_source = "TX_AVG" if unit_price > 0 else "MISSING"
            needs_pricing = bool(unit_price <= 0)
            amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_consumption += amount
            ss.lines.append(SupplierSettlementLine(
                source_type="CONSUME_SALE",
                source_id=sl.id,
                description=f"استهلاك بيع #{sl.sale_id}-{sl.id}",
                product_id=sl.product_id,
                quantity=qty,
                unit_price=unit_price if unit_price > 0 else None,
                gross_amount=amount,
                needs_pricing=needs_pricing,
                cost_source=cost_source
            ))
        sp_lines = (
            db.session.query(ServicePart)
            .join(Warehouse, Warehouse.id == ServicePart.warehouse_id)
            .filter(
                Warehouse.warehouse_type == WarehouseType.EXCHANGE.value,
                Warehouse.supplier_id == supplier_id,
                ServicePart.created_at >= date_from,
                ServicePart.created_at <= date_to
            ).all()
        )
        for sp in sp_lines:
            if ("CONSUME_SERVICE", sp.id) in used:
                continue
            qty = Decimal(str(sp.quantity or 0))
            unit_price = _avg_cost_until(sp.part_id, supplier_id, date_to)
            cost_source = "TX_AVG" if unit_price > 0 else "MISSING"
            needs_pricing = bool(unit_price <= 0)
            amount = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_consumption += amount
            ss.lines.append(SupplierSettlementLine(
                source_type="CONSUME_SERVICE",
                source_id=sp.id,
                description=f"استهلاك صيانة #{sp.service_id}-{sp.id}",
                product_id=sp.part_id,
                quantity=qty,
                unit_price=unit_price if unit_price > 0 else None,
                gross_amount=amount,
                needs_pricing=needs_pricing,
                cost_source=cost_source
            ))

        # 5. Remaining Stock (Optional Buyout for Consignment)
        stock_q = (
             db.session.query(StockLevel, Product)
             .join(Product, Product.id == StockLevel.product_id)
             .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
             .filter(
                 Warehouse.supplier_id == supplier_id,
                 Warehouse.warehouse_type == WarehouseType.EXCHANGE.value,
                 StockLevel.quantity > 0
             )
         )
         
        for sl, prod in stock_q:
             qty = Decimal(str(sl.quantity or 0))
             u_price = _avg_cost_until(prod.id, supplier_id, date_to)
             cost_source = "TX_AVG" if u_price > 0 else "MISSING"
             needs_pricing = bool(u_price <= 0)
             base = (qty * u_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
             
             if base > 0 or qty > 0:
                 ss.lines.append(
                    SupplierSettlementLine(
                        source_type="INVENTORY_HOLDING",
                        source_id=sl.id,
                        description=f"Remaining Stock (Buyout) - {prod.name}",
                        product_id=prod.id,
                        warehouse_id=sl.warehouse_id,
                        quantity=qty,
                        unit_price=u_price if u_price > 0 else None,
                        gross_amount=base,
                        needs_pricing=needs_pricing,
                        cost_source=cost_source
                    )
                 )
                 total_consumption += base

    loans_q = (
        db.session.query(SupplierLoanSettlement)
        .options(joinedload(SupplierLoanSettlement.loan))
        .filter(
            SupplierLoanSettlement.supplier_id == supplier_id,
            SupplierLoanSettlement.settlement_date >= date_from,
            SupplierLoanSettlement.settlement_date <= date_to
        )
    )
    for ls in loans_q:
        if ("LOAN_SETTLEMENT", ls.id) in used:
            continue
        amount = q(ls.settled_price)
        prod_id = getattr(getattr(ls, "loan", None), "product_id", None)
        total_loans += amount
        ss.lines.append(SupplierSettlementLine(
            source_type="LOAN_SETTLEMENT",
            source_id=ls.id,
            description=f"تسوية قرض #{ls.id}",
            product_id=prod_id,
            quantity=None,
            unit_price=None,
            gross_amount=amount,
            needs_pricing=False,
            cost_source="FIXED"
        ))

    invs = db.session.query(Invoice).filter(Invoice.supplier_id == supplier_id).all()
    for inv in invs:
        if inv.balance_due > 0:
            if ("SUPPLIER_INVOICE", inv.id) in used:
                continue
            amount = Decimal(str(inv.balance_due or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_invoices += amount
            ss.lines.append(SupplierSettlementLine(
                source_type="SUPPLIER_INVOICE",
                source_id=inv.id,
                description=f"فاتورة مورد #{inv.invoice_number or inv.id}",
                product_id=None,
                quantity=None,
                unit_price=None,
                gross_amount=amount,
                needs_pricing=False,
                cost_source="INVOICE"
            ))

    if final_mode == SupplierSettlementMode.ON_RECEIPT.value:
        gross = q(total_purchases + total_loans + total_invoices)
        due = q(total_purchases + total_loans + total_invoices - total_returns)
    else:
        gross = q(total_consumption + total_loans + total_invoices)
        due = q(total_consumption + total_loans + total_invoices)

    ss.total_gross = gross
    ss.total_due = due
    ss.ensure_code()
    return ss

class ShipmentItem(db.Model):
    __tablename__ = "shipment_items"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    declared_value = db.Column(db.Numeric(12, 2))
    landed_extra_share = db.Column(db.Numeric(12, 2), default=0)
    landed_unit_cost = db.Column(db.Numeric(12, 2), default=0)
    notes = db.Column(db.String(200))

    shipment = db.relationship("Shipment", back_populates="items")
    product  = db.relationship("Product",  back_populates="shipment_items")
    warehouse= db.relationship("Warehouse",back_populates="shipment_items")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="chk_shipment_item_qty_positive"),
        db.UniqueConstraint("shipment_id","product_id","warehouse_id", name="uq_shipment_item_unique"),
        db.Index("ix_shipment_items_prod_wh", "product_id","warehouse_id"),
        db.CheckConstraint("unit_cost >= 0", name="ck_shipment_item_unit_cost_non_negative"),
        db.CheckConstraint("declared_value >= 0", name="ck_shipment_item_declared_value_non_negative"),
        db.CheckConstraint("landed_extra_share >= 0", name="ck_shipment_item_landed_extra_share_non_negative"),
        db.CheckConstraint("landed_unit_cost >= 0", name="ck_shipment_item_landed_unit_cost_non_negative"),
    )

    @validates("quantity")
    def _v_qty(self, _, v):
        v = int(v)
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v

    @hybrid_property
    def total_value(self):
        return q(D(self.quantity or 0) * D(self.unit_cost or 0))

    @hybrid_property
    def landed_total_value(self):
        return q(D(self.quantity or 0) * (D(self.unit_cost or 0) + D(self.landed_extra_share or 0) / (D(self.quantity or 1))))

    def __repr__(self):
        return f"<ShipmentItem {self.product_id} Q{self.quantity}>"

@event.listens_for(ShipmentItem, "before_insert")
@event.listens_for(ShipmentItem, "before_update")
def _shipitem_before_save(mapper, connection, it: "ShipmentItem"):
    q_qty = D(it.quantity or 0)
    base_uc = q(D(it.unit_cost or 0))
    extra   = q(D(it.landed_extra_share or 0))
    if q_qty <= 0:
        return
    it.landed_unit_cost = q(base_uc + (extra / q_qty))


class Shipment(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "shipments"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(50), unique=True, index=True)
    shipment_number = db.Column(db.String(50), unique=True, index=True)
    date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    shipment_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expected_arrival = db.Column(db.DateTime)
    actual_arrival   = db.Column(db.DateTime)
    delivered_date = db.Column(db.DateTime)

    origin = db.Column(db.String(100))
    destination = db.Column(db.String(100))
    destination_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    status = db.Column(db.String(20), default="DRAFT", nullable=False, index=True, server_default=sa_text("'DRAFT'"))

    value_before = db.Column(db.Numeric(12, 2))
    shipping_cost = db.Column(db.Numeric(12, 2))
    customs = db.Column(db.Numeric(12, 2))
    vat = db.Column(db.Numeric(12, 2))
    insurance = db.Column(db.Numeric(12, 2))
    total_cost = db.Column(db.Numeric(12, 2))

    carrier = db.Column(db.String(100))
    tracking_number = db.Column(db.String(100), index=True)
    notes = db.Column(db.Text)
    currency = db.Column(db.String(10), default="USD", nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), index=True)
    
    # حقول إضافية للشحنات
    weight = db.Column(db.Numeric(10, 3))  # الوزن بالكيلو
    dimensions = db.Column(db.String(100))  # الأبعاد
    package_count = db.Column(db.Integer, default=1)  # عدد الطرود
    priority = db.Column(db.String(20), default="NORMAL")  # الأولوية
    delivery_method = db.Column(db.String(50))  # طريقة التسليم
    delivery_instructions = db.Column(db.Text)  # تعليمات التسليم
    customs_declaration = db.Column(db.String(100))  # رقم البيان الجمركي
    customs_cleared_date = db.Column(db.DateTime)  # تاريخ التخليص الجمركي
    delivery_attempts = db.Column(db.Integer, default=0)  # محاولات التسليم
    last_delivery_attempt = db.Column(db.DateTime)  # آخر محاولة تسليم
    return_reason = db.Column(db.Text)  # سبب الإرجاع
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))

    items    = db.relationship("ShipmentItem", back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentItem.id")
    partners = db.relationship("ShipmentPartner", back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentPartner.id")
    payments = db.relationship("Payment", back_populates="shipment", order_by="Payment.id")
    sale     = db.relationship("Sale", back_populates="shipments")
    destination_warehouse = db.relationship("Warehouse", back_populates="shipments_received", foreign_keys=[destination_id])
    expenses = db.relationship("Expense", back_populates="shipment", passive_deletes=True, order_by="Expense.id")
    archived_by_user = db.relationship("User", foreign_keys=[archived_by])

    gl_batches = db.relationship(
        "GLBatch",
        primaryjoin="and_(foreign(GLBatch.source_id)==Shipment.id, GLBatch.source_type=='SHIPMENT')",
        viewonly=True,
        order_by="GLBatch.id",
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('DRAFT','PENDING','IN_TRANSIT','IN_CUSTOMS','ARRIVED','DELIVERED','CANCELLED','RETURNED','CREATED')", name="chk_shipment_status_allowed"),
        db.Index("ix_shipments_dest_status", "destination_id", "status"),
        db.CheckConstraint("value_before >= 0", name="ck_shipment_value_before_non_negative"),
        db.CheckConstraint("shipping_cost >= 0", name="ck_shipment_shipping_cost_non_negative"),
        db.CheckConstraint("customs >= 0", name="ck_shipment_customs_non_negative"),
        db.CheckConstraint("vat >= 0", name="ck_shipment_vat_non_negative"),
        db.CheckConstraint("insurance >= 0", name="ck_shipment_insurance_non_negative"),
    )

    @validates("status")
    def _v_status(self, _, v):
        return (str(v or "")).strip().upper()

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or "USD").upper()

    @hybrid_property
    def total_value(self):
        return q(
            D(self.value_before or 0)
            + D(self.shipping_cost or 0)
            + D(self.customs or 0)
            + D(self.vat or 0)
            + D(self.insurance or 0)
        )

    @hybrid_property
    def landed_total_value(self):
        return q(sum(q(it.landed_unit_cost) * D(it.quantity or 0) for it in (self.items or [])))

    def update_status(self, new_status: str):
        self.status = (new_status or "").strip().upper()
        if self.status == "ARRIVED" and not self.actual_arrival:
            self.actual_arrival = datetime.now(timezone.utc)

    def _apply_arrival_stock(self):
        if not getattr(self, "id", None):
            return
        with db.session.no_autoflush:
            connection = db.session.connection()
            dest_id = getattr(self, "destination_id", None)
            rows = connection.execute(
                sa_text(
                    "SELECT product_id, COALESCE(warehouse_id, :dest) AS wid, quantity "
                    "FROM shipment_items WHERE shipment_id = :sid"
                ),
                {"sid": int(self.id), "dest": dest_id},
            ).mappings().all()
            for r in rows:
                wid = r.get("wid")
                if not wid:
                    continue
                wh = connection.execute(
                    sa_text("SELECT warehouse_type, partner_id FROM warehouses WHERE id=:wid"),
                    {"wid": int(wid)},
                ).mappings().first()
                if wh and (wh.get("warehouse_type") or "").upper() == WarehouseType.PARTNER.value and not wh.get("partner_id"):
                    raise ValueError("Partner warehouse missing partner_id")
                qty = int(r.get("quantity") or 0)
                if qty > 0:
                    _apply_stock_delta(connection, int(r["product_id"]), int(wid), +qty)

    def _revert_arrival_stock(self):
        if not getattr(self, "id", None):
            return
        with db.session.no_autoflush:
            connection = db.session.connection()
            dest_id = getattr(self, "destination_id", None)
            rows = connection.execute(
                sa_text(
                    "SELECT product_id, COALESCE(warehouse_id, :dest) AS wid, quantity "
                    "FROM shipment_items WHERE shipment_id = :sid"
                ),
                {"sid": int(self.id), "dest": dest_id},
            ).mappings().all()
            for r in rows:
                wid = r.get("wid")
                if not wid:
                    continue
                qty = int(r.get("quantity") or 0)
                if qty > 0:
                    _apply_stock_delta(connection, int(r["product_id"]), int(wid), -qty)

    def __repr__(self):
        return f"<Shipment {self.number or self.shipment_number or self.id}>"

def _recompute_shipment_value_before(shp: "Shipment"):
    vb = sum(q(D(it.quantity or 0) * D(it.unit_cost or 0)) for it in (shp.items or []))
    shp.value_before = q(vb)

def _allocate_landed_costs(shp: "Shipment"):
    items = shp.items or []
    if not items:
        return
    base_vals = [q(D(it.quantity or 0) * D(it.unit_cost or 0)) for it in items]
    total_base = q(sum(base_vals))
    if total_base <= 0:
        per_item = q(D(shp.shipping_cost or 0) + D(shp.customs or 0) + D(shp.vat or 0) + D(shp.insurance or 0)) / D(len(items))
        for it in items:
            it.landed_extra_share = q(per_item)
        return

    total_extras = q(D(shp.shipping_cost or 0) + D(shp.customs or 0) + D(shp.vat or 0) + D(shp.insurance or 0))
    if total_extras <= 0:
        for it in items:
            it.landed_extra_share = q(0)
        return

    for it, base in zip(items, base_vals):
        share = q(total_extras * (base / total_base))
        it.landed_extra_share = q(share)

@event.listens_for(Shipment, "before_insert")
def _shipment_before_insert(mapper, connection, target: "Shipment"):
    if not getattr(target, "shipment_number", None) and not getattr(target, "number", None):
        import hashlib
        
        # نظام تسلسل ذكي عصري عالمي مثل FedEx/DHL/UPS
        # التنسيق: AZD-YYYYMMDD-XXXX-CCC
        # AZD = رمز الشركة (Azad)
        # YYYYMMDD = التاريخ
        # XXXX = رقم تسلسلي يومي (hexadecimal)
        # CCC = checksum للتحقق
        
        now = datetime.now(timezone.utc)
        date_part = now.strftime("%Y%m%d")
        
        # حساب العدد اليومي
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = connection.execute(
            sa_text("SELECT COUNT(*) FROM shipments WHERE shipment_date >= :start"),
            {"start": today_start},
        ).scalar() or 0
        
        # رقم تسلسلي hexadecimal (أكثر احترافية وأقصر)
        seq_hex = format(count + 1, '04X')  # 0001, 0002, ..., FFFF
        
        # بناء الرقم الأساسي
        base_number = f"AZD-{date_part}-{seq_hex}"
        
        # حساب checksum (آخر 3 أحرف من hash)
        hash_value = hashlib.md5(base_number.encode()).hexdigest()[:3].upper()
        
        # الرقم النهائي
        tracking_number = f"{base_number}-{hash_value}"
        
        target.shipment_number = tracking_number
        target.number = tracking_number
        
        # إذا لم يكن هناك tracking_number، نستخدم نفس الرقم
        if not getattr(target, "tracking_number", None):
            target.tracking_number = tracking_number
            
    elif getattr(target, "shipment_number", None) and not getattr(target, "number", None):
        target.number = target.shipment_number
    elif getattr(target, "number", None) and not getattr(target, "shipment_number", None):
        target.shipment_number = target.number

    # تم نقل ضبط العملة إلى _shipment_normalize_insert (السطر 7968)
    if not getattr(target, "date", None) and getattr(target, "shipment_date", None):
        target.date = target.shipment_date
    if not getattr(target, "shipment_date", None) and getattr(target, "date", None):
        target.shipment_date = target.date

    _recompute_shipment_value_before(target)
    _allocate_landed_costs(target)

@event.listens_for(Shipment, "before_update")
def _shipment_before_update(mapper, connection, target: "Shipment"):
    # تم نقل ضبط العملة إلى _shipment_normalize_update (السطر 7989)
    if not getattr(target, "date", None) and getattr(target, "shipment_date", None):
        target.date = target.shipment_date
    if not getattr(target, "shipment_date", None) and getattr(target, "date", None):
        target.shipment_date = target.date
    if getattr(target, "shipment_number", None) and not getattr(target, "number", None):
        target.number = target.shipment_number
    if getattr(target, "number", None) and not getattr(target, "shipment_number", None):
        target.shipment_number = target.number
    try:
        insp = inspect(target)
        extras_changed = False
        for k in ("shipping_cost", "customs", "vat", "insurance"):
            try:
                if insp.attrs[k].history.has_changes():
                    extras_changed = True
                    break
            except Exception:
                continue
        items_changed = False
        try:
            items_changed = bool(insp.attrs["items"].history.has_changes())
        except Exception:
            items_changed = False
        if extras_changed or items_changed:
            _recompute_shipment_value_before(target)
            _allocate_landed_costs(target)
    except Exception:
        pass

@event.listens_for(Shipment.status, "set")
def _shipment_status_toggle(target, value, oldvalue, initiator):
    def _normalize(val):
        if val is None:
            return ""
        if hasattr(val, "value"):
            val = val.value
        return str(val).strip().upper()

    old = _normalize(oldvalue)
    new = _normalize(value)
    if old == new:
        return

    if old != ShipmentStatus.ARRIVED.value and new == ShipmentStatus.ARRIVED.value:
        target._apply_arrival_stock()
        if not getattr(target, "actual_arrival", None):
            target.actual_arrival = datetime.now(timezone.utc)
    elif old == ShipmentStatus.ARRIVED.value and new != ShipmentStatus.ARRIVED.value:
        target._revert_arrival_stock()

@event.listens_for(Shipment, "before_delete")
def _shipment_gl_batch_reverse(mapper, connection, target: "Shipment"):
    """إنشاء قيد عكسي عند حذف الشحنة (أصح محاسبياً)"""
    try:
        if hasattr(target, '_skip_gl_reversal') and target._skip_gl_reversal:
            return
        if target.status != ShipmentStatus.ARRIVED.value or not target.destination_id:
            return
        
        total_cost = float(target.total_cost or 0)
        if total_cost <= 0:
            return
        
        amount_ils = total_cost
        if target.currency and target.currency != DEFAULT_CURRENCY:
            try:
                rate = _fx_rate_local_via_connection(connection, target.currency, DEFAULT_CURRENCY, target.date or datetime.now(timezone.utc))
                if rate and rate > 0:
                    amount_ils = float(total_cost * float(rate))
            except Exception:
                pass
        
        inventory_account = GL_ACCOUNTS.get("INV", "1300_INVENTORY")
        offset_account = GL_ACCOUNTS.get("AP", "2000_AP")
        
        entries = [
            (offset_account, amount_ils, 0),
            (inventory_account, 0, amount_ils),
        ]
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="SHIPMENT_REVERSAL",
            source_id=target.id,
            purpose="REVERSAL",
            currency=DEFAULT_CURRENCY,
            memo=f"عكس قيد - حذف شحنة #{target.id}",
            entries=entries,
            ref=f"REV-SHIP-{target.id}",
            entity_type="SUPPLIER",
            entity_id=target.supplier_id
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في عكس قيد الشحنة #{target.id}: {e}")

@event.listens_for(Shipment, "after_update")
def _gl_on_shipment_arrived(mapper, connection, target: "Shipment"):
    try:
        hist = inspect(target).attrs.status.history
        changed = hist.has_changes()
        oldv = str(hist.deleted[0]).upper() if hist.deleted else None
        newv = str(hist.added[0]).upper() if hist.added else str(getattr(target, "status", "")).upper()
    except Exception:
        changed = True
        oldv = None
        newv = str(getattr(target, "status", "")).upper()

    if not changed or newv != "ARRIVED" or oldv == "ARRIVED":
        return

    from flask import current_app
    cfg = {}
    try:
        cfg = current_app.config or {}
    except Exception:
        pass
    if not bool(cfg.get("GL_AUTO_POST_ON_SHIPMENT_ARRIVAL", False)):
        return

    inv_acc   = cfg.get("GL_SHIPMENT_INV_ACCOUNT")
    offset_acc= cfg.get("GL_SHIPMENT_OFFSET_ACCOUNT")
    if not inv_acc or not offset_acc:
        return

    total = float(q(sum(q(D(it.landed_unit_cost or it.unit_cost or 0)) * D(it.quantity or 0) for it in (target.items or []))))
    if total <= 0:
        return

    # استخدام الدالة من models.py مباشرة
    currency = (getattr(target, "currency", None) or "USD").upper()
    ref  = str(getattr(target, "shipment_number", None) or target.id)
    memo = f"Shipment {ref} arrived"

    entries = [
        (str(inv_acc).upper(),    total, 0.0),
        (str(offset_acc).upper(), 0.0,   total)
    ]
    _gl_upsert_batch_and_entries(
        connection,
        source_type="SHIPMENT",
        source_id=target.id,
        purpose="ARRIVAL",
        currency=currency,
        memo=memo,
        entries=entries,
        ref=ref,
        entity_type=None,
        entity_id=None,
    )

class ShipmentPartner(db.Model, TimestampMixin):
    __tablename__ = 'shipment_partners'

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id', ondelete='CASCADE'), nullable=False, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id', ondelete='CASCADE'), nullable=False, index=True)
    identity_number = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    address = db.Column(db.String(200))
    unit_price_before_tax = db.Column(db.Numeric(12, 2))
    expiry_date = db.Column(db.Date)
    share_percentage = db.Column(db.Numeric(5, 2), default=0)
    share_amount = db.Column(db.Numeric(12, 2), default=0)
    notes = db.Column(db.Text)

    __table_args__ = (
        db.CheckConstraint('share_percentage >= 0 AND share_percentage <= 100', name='chk_shipment_partner_share'),
        db.UniqueConstraint('shipment_id', 'partner_id', name='uq_shipment_partner_unique'),
        db.Index('ix_shipment_partner_pair', 'shipment_id', 'partner_id'),
        CheckConstraint('unit_price_before_tax >= 0', name='ck_shipment_partner_unit_price_non_negative'),
        CheckConstraint('share_amount >= 0', name='ck_shipment_partner_share_amount_non_negative'),
    )

    partner = db.relationship('Partner', back_populates='shipment_partners')
    shipment = db.relationship('Shipment', back_populates='partners')

    @hybrid_property
    def share_value(self):
        if self.share_amount and D(self.share_amount) > 0:
            return q(D(self.share_amount))
        return q(D(self.unit_price_before_tax or 0) * (D(self.share_percentage or 0) / Decimal("100")))

    @share_value.expression
    def share_value(cls):
        amt = func.coalesce(cls.share_amount, 0)
        base = func.coalesce(cls.unit_price_before_tax, 0)
        pct = func.coalesce(cls.share_percentage, 0)
        return case((amt > 0, amt), else_=(base * (pct / 100.0)))

    def __repr__(self):
        return f"<ShipmentPartner shipment={self.shipment_id} partner={self.partner_id}>"

class ServiceRequest(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "service_requests"

    id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, index=True, nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True, nullable=False)
    mechanic_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey("equipment_types.id"), index=True)

    status = db.Column(sa_str_enum(ServiceStatus, name="service_status"), default=ServiceStatus.PENDING.value, nullable=False, index=True)
    priority = db.Column(sa_str_enum(ServicePriority, name="service_priority"), default=ServicePriority.MEDIUM.value, nullable=False, index=True)

    vehicle_vrn = db.Column(db.String(50))
    vehicle_model = db.Column(db.String(100))
    chassis_number = db.Column(db.String(100))
    engineer_notes = db.Column(db.Text)
    description = db.Column(db.Text)
    estimated_duration = db.Column(db.Integer)
    actual_duration = db.Column(db.Integer)
    estimated_cost = db.Column(db.Numeric(12, 2))
    total_cost = db.Column(db.Numeric(12, 2))
    start_time = db.Column(db.Date)
    end_time = db.Column(db.Date)
    problem_description = db.Column(db.Text)
    diagnosis = db.Column(db.Text)
    resolution = db.Column(db.Text)
    notes = db.Column(db.Text)

    received_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = db.Column(db.DateTime)
    expected_delivery = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    currency = db.Column(db.String(10), nullable=False, default=DEFAULT_CURRENCY)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    discount_total = db.Column(db.Numeric(12, 2), default=0)
    parts_total = db.Column(db.Numeric(12, 2), default=0)
    labor_total = db.Column(db.Numeric(12, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    consume_stock = db.Column(db.Boolean, default=True, nullable=False)
    warranty_days = db.Column(db.Integer, default=0)

    refunded_total = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    refund_of_id = db.Column(db.Integer, db.ForeignKey("service_requests.id", ondelete="SET NULL"), index=True)
    idempotency_key = db.Column(db.String(64), unique=True, index=True)
    cancelled_at = db.Column(db.DateTime, index=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    cancel_reason = db.Column(db.String(200))
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"), index=True)

    customer = db.relationship("Customer", back_populates="service_requests")
    cost_center = db.relationship("CostCenter", backref=db.backref("service_requests", lazy="dynamic"))
    mechanic = db.relationship("User", back_populates="mechanic_service_requests", foreign_keys=[mechanic_id])
    cancelled_by_user = db.relationship("User", back_populates="cancelled_service_requests", foreign_keys=[cancelled_by])
    archived_by_user = db.relationship("User", foreign_keys=[archived_by])
    vehicle_type = db.relationship("EquipmentType", back_populates="service_requests")
    invoice = db.relationship("Invoice", back_populates="service", uselist=False)

    payments = db.relationship("Payment", back_populates="service", cascade="all, delete-orphan", order_by="Payment.id")
    parts = db.relationship("ServicePart", back_populates="request", cascade="all, delete-orphan", order_by="ServicePart.id")
    tasks = db.relationship("ServiceTask", back_populates="request", cascade="all, delete-orphan", order_by="ServiceTask.id")
    gl_batches = db.relationship("GLBatch", primaryjoin="and_(foreign(GLBatch.source_id)==ServiceRequest.id, GLBatch.source_type=='SERVICE')", viewonly=True, order_by="GLBatch.id")

    refund_of = db.relationship("ServiceRequest", remote_side=[id])

    __table_args__ = (
        db.Index("ix_srv_vehicle_vrn", "vehicle_vrn"),
        db.Index("ix_srv_chassis", "chassis_number"),
        db.Index("ix_srv_vehicle_model", "vehicle_model"),
        db.Index("ix_srv_cust_status", "customer_id", "status"),
        db.Index("ix_srv_mech_status", "mechanic_id", "status"),
        db.Index("ix_srv_cost_center", "cost_center_id"),
        db.Index("ix_srv_created_status", "created_at", "status"),
        db.Index("ix_srv_expected_delivery", "expected_delivery"),
        db.Index("ix_srv_completed_at", "completed_at"),
        db.Index("ix_srv_total_amount", "total_amount"),
    )

    @validates("status", "priority")
    def _v_enum_strings(self, _, v): return getattr(v, "value", v)

    @validates("currency")
    def _v_currency(self, _, v): return ensure_currency(v or "ILS")

    @validates("discount_total", "parts_total", "labor_total", "total_amount", "total_cost", "estimated_duration", "actual_duration", "warranty_days", "refunded_total")
    def _v_non_negative(self, key, v):
        if v in (None, ""):
            return 0 if key in ("estimated_duration", "actual_duration", "warranty_days") else _Q2(0)
        d = _D(v)
        if d < 0:
            field_names = {
                "discount_total": "الخصم الإجمالي",
                "parts_total": "إجمالي القطع",
                "labor_total": "إجمالي العمالة",
                "total_amount": "المبلغ الإجمالي",
                "total_cost": "التكلفة الإجمالية",
                "estimated_duration": "المدة المتوقعة",
                "actual_duration": "المدة الفعلية",
                "warranty_days": "أيام الضمان",
                "refunded_total": "المبلغ المسترد"
            }
            raise ValueError(f"{field_names.get(key, key)} لا يمكن أن يكون سالباً")
        
        if key == "discount_total" and d > 0:
            parts_sum = sum((_D(p.line_total or 0) for p in (getattr(self, 'parts', None) or [])), _D(0))
            tasks_sum = sum((_D(t.line_total or 0) for t in (getattr(self, 'tasks', None) or [])), _D(0))
            invoice_total = parts_sum + tasks_sum
            if d > invoice_total and invoice_total > 0:
                raise ValueError(f"الخصم الإجمالي ({d}) لا يمكن أن يتجاوز إجمالي الفاتورة ({invoice_total})")
        
        return int(d) if key in ("estimated_duration", "actual_duration", "warranty_days") else _Q2(d)

    @hybrid_property
    def subtotal(self): return float(_Q2(_D(self.parts_total or 0) + _D(self.labor_total or 0)))

    @subtotal.expression
    def subtotal(cls):
        return func.coalesce(cls.parts_total, 0) + func.coalesce(cls.labor_total, 0)

    @hybrid_property
    def tax_amount(self):
        base = _D(self.subtotal) - _D(self.discount_total or 0)
        if base < 0: base = Decimal("0.00")
        return float(_Q2(base * (_D(self.tax_rate or 0) / Decimal("100"))))

    @tax_amount.expression
    def tax_amount(cls):
        base = (func.coalesce(cls.parts_total, 0) + func.coalesce(cls.labor_total, 0)) - func.coalesce(cls.discount_total, 0)
        base_pos = case((base < 0, 0), else_=base)
        return base_pos * (func.coalesce(cls.tax_rate, 0) / 100.0)

    @hybrid_property
    def total(self):
        subtotal = _D(self.parts_total or 0) + _D(self.labor_total or 0)
        discount = _D(self.discount_total or 0)
        base = subtotal - discount
        if base < 0:
            base = Decimal("0.00")
        tax = base * (_D(self.tax_rate or 0) / Decimal("100"))
        total = base + tax
        return float(_Q2(total))

    @total.expression
    def total(cls):
        base = (func.coalesce(cls.parts_total, 0) + func.coalesce(cls.labor_total, 0)) - func.coalesce(cls.discount_total, 0)
        base_pos = case((base < 0, 0), else_=base)
        tax = base_pos * (func.coalesce(cls.tax_rate, 0) / 100.0)
        return base_pos + tax

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal as D
        from sqlalchemy.orm import joinedload
        
        payments = db.session.query(Payment).options(
            joinedload(Payment.splits)
        ).filter(
            Payment.service_id == self.id,
            Payment.direction == PaymentDirection.IN.value
        ).all()
        
        total = D('0.00')
        service_currency = self.currency or DEFAULT_CURRENCY
        
        for payment in payments:
            splits = payment.splits if hasattr(payment, 'splits') else []
            
            if splits:
                for split in splits:
                    split_amt = D(str(split.amount or 0))
                    split_currency = split.currency or payment.currency or service_currency
                    if split_currency == service_currency:
                        total += split_amt
                    else:
                        try:
                            total += D(str(convert_amount(split_amt, split_currency, service_currency, payment.payment_date)))
                        except Exception:
                            pass
            else:
                amt = D(str(payment.total_amount or 0))
                if payment.currency == service_currency:
                    total += amt
                else:
                    try:
                        total += D(str(convert_amount(amt, payment.currency, service_currency, payment.payment_date)))
                    except Exception:
                        pass
        
        return float(total)

    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.service_id == cls.id)
                & (Payment.direction == PaymentDirection.IN.value)
            )
            .scalar_subquery()
        )

    @hybrid_property
    def balance_due(self):
        val = _Q2(_D(self.total) - _D(self.total_paid))
        return float(val if val > 0 else Decimal("0.00"))

    @balance_due.expression
    def balance_due(cls):
        bd = (cls.total - cls.total_paid)
        return case((bd < 0, 0), else_=bd)

    @property
    def summary_parts_total(self):
        return float(_Q2(_D(self.parts_total or 0)))

    @property
    def summary_tasks_total(self):
        return float(_Q2(_D(self.labor_total or 0)))

    @property
    def summary_parts_discount(self):
        total = Decimal('0.00')
        for p in self.parts or []:
            total += _D(p.discount or 0)
        return float(_Q2(total))

    @property
    def summary_tasks_discount(self):
        total = Decimal('0.00')
        for t in self.tasks or []:
            total += _D(t.discount or 0)
        return float(_Q2(total))

    @property
    def summary_parts_base(self):
        total = Decimal('0.00')
        for p in self.parts or []:
            gross = _D(p.quantity or 0) * _D(p.unit_price or 0)
            discount = _D(p.discount or 0)
            total += gross - discount
        return float(_Q2(total))

    @property
    def summary_tasks_base(self):
        total = Decimal('0.00')
        for t in self.tasks or []:
            gross = _D(t.quantity or 0) * _D(t.unit_price or 0)
            discount = _D(t.discount or 0)
            total += gross - discount
        return float(_Q2(total))

    @property
    def summary_parts_tax(self):
        return 0.0

    @property
    def summary_tasks_tax(self):
        return 0.0

    @property
    def summary_subtotal(self):
        return float(_Q2(_D(self.parts_total or 0) + _D(self.labor_total or 0)))

    @property
    def summary_base_total(self):
        return self.summary_parts_base + self.summary_tasks_base

    @property
    def summary_tax_total(self):
        base_after = _D(self.summary_base_after_discount)
        tax_rate = _D(self.tax_rate or 0) / Decimal('100')
        return float(_Q2(base_after * tax_rate))

    @property
    def summary_subtotal_after_discount(self):
        subtotal = _D(self.parts_total or 0) + _D(self.labor_total or 0)
        discount = _D(self.discount_total or 0)
        result = subtotal - discount
        return float(_Q2(result if result > 0 else Decimal('0.00')))

    @property
    def summary_base_after_discount(self):
        base = _D(self.summary_base_total)
        discount = _D(self.discount_total or 0)
        result = base - discount
        return float(_Q2(result if result > 0 else Decimal('0.00')))

    @property
    def summary_tax_rate_display(self):
        return float(_Q2(_D(self.tax_rate or 0)))

    @hybrid_property
    def warranty_until(self):
        if not self.warranty_days: return None
        anchor = self.completed_at or self.updated_at or self.created_at
        return anchor + timedelta(days=self.warranty_days) if anchor else None

    @hybrid_property
    def refundable_amount(self):
        return float(_Q2(_D(self.total_paid or 0) - _D(self.refunded_total or 0)))

    def can_refund(self, amount):
        amt = _Q2(amount or 0)
        return amt > 0 and amt <= _Q2(self.refundable_amount)

    def apply_refund(self, amount):
        if not self.can_refund(amount):
            raise ValueError("service.refund_exceeds_allowed")
        self.refunded_total = _Q2(_D(self.refunded_total or 0) + _D(amount or 0))

    def cancel(self, by_user_id=None, reason=None):
        self.cancelled_at = datetime.now(timezone.utc)
        self.cancelled_by = by_user_id
        self.cancel_reason = (reason or None)
        self.status = ServiceStatus.CANCELLED.value

    def mark_started(self):
        if not self.started_at: self.started_at = datetime.now(timezone.utc)
        if self.status == ServiceStatus.PENDING.value: self.status = ServiceStatus.IN_PROGRESS.value

    def mark_completed(self):
        self.status = ServiceStatus.COMPLETED.value
        if not self.completed_at: self.completed_at = datetime.now(timezone.utc)

    def __repr__(self): return f"<ServiceRequest {self.service_number or self.id}>"

    def to_dict(self):
        return {
            "id": self.id,
            "service_number": self.service_number,
            "status": getattr(self.status, "value", self.status),
            "priority": getattr(self.priority, "value", self.priority),
            "customer_id": self.customer_id,
            "mechanic_id": self.mechanic_id,
            "vehicle_type_id": self.vehicle_type_id,
            "problem_description": self.problem_description,
            "diagnosis": self.diagnosis,
            "resolution": self.resolution,
            "notes": self.notes,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "expected_delivery": self.expected_delivery.isoformat() if self.expected_delivery else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "currency": self.currency,
            "tax_rate": float(self.tax_rate or 0),
            "discount_total": float(self.discount_total or 0),
            "parts_total": float(self.parts_total or 0),
            "labor_total": float(self.labor_total or 0),
            "total_amount": float(self.total_amount or 0),
            "subtotal": float(self.subtotal),
            "tax_amount": float(self.tax_amount),
            "total": float(self.total),
            "total_paid": float(self.total_paid),
            "balance_due": float(self.balance_due),
            "warranty_days": self.warranty_days,
            "warranty_until": self.warranty_until.isoformat() if self.warranty_until else None,
            "refunded_total": float(self.refunded_total or 0),
            "refundable_amount": float(self.refundable_amount),
            "refund_of_id": self.refund_of_id,
            "idempotency_key": self.idempotency_key,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancelled_by": self.cancelled_by,
            "cancel_reason": self.cancel_reason,
            "parts": [p.to_dict() for p in self.parts] if self.parts else [],
            "tasks": [t.to_dict() for t in self.tasks] if self.tasks else []
        }

def _D(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def _Q2(x):
    return _D(x).quantize(Decimal("0.01"), ROUND_HALF_UP)

def _calc_parts_sum(service_id: int) -> Decimal:
    rows = db.session.query(
        ServicePart.quantity, ServicePart.unit_price, ServicePart.discount
    ).filter(ServicePart.service_id == service_id).all()
    total = Decimal("0")
    for q, u, d in rows:
        qd = _D(q)
        ud = _D(u)
        dd = _D(d)
        gross = qd * ud
        taxable = gross - dd
        total += taxable
    return _Q2(total)

def _calc_tasks_sum(service_id: int) -> Decimal:
    rows = db.session.query(
        ServiceTask.quantity, ServiceTask.unit_price, ServiceTask.discount
    ).filter(ServiceTask.service_id == service_id).all()
    total = Decimal("0")
    for q, u, d in rows:
        qd = _D(q)
        ud = _D(u)
        dd = _D(d)
        gross = qd * ud
        taxable = gross - dd
        total += taxable
    return _Q2(total)

from flask import current_app

def _service_consumes_stock(sr: "ServiceRequest") -> bool:
    if not sr:
        return False
    if not bool(current_app.config.get("SERVICE_CONSUMES_STOCK", True)):
        return False
    status = str(getattr(sr, "status", "") or "").upper()
    # Handle both Enum and string values
    if "SERVICESTATUS." in status:
        status = status.replace("SERVICESTATUS.", "")
    return bool(getattr(sr, "consume_stock", True)) and status in ("PENDING", "DIAGNOSIS", "IN_PROGRESS", "ON_HOLD", "COMPLETED")

def _recalc_service_request_totals(sr: "ServiceRequest"):
    if sr is None:
        return
    parts_sum = Decimal('0.00')
    if hasattr(sr, "parts") and sr.parts:
        for p in sr.parts:
            parts_sum += _D(p.line_total or 0)
    elif getattr(sr, "id", None):
        try:
            parts = db.session.query(ServicePart.line_total).filter(ServicePart.service_id == sr.id).all()
            for (line_total,) in parts:
                parts_sum += _D(line_total or 0)
        except Exception:
            parts_sum = _Q2(getattr(sr, "parts_total", 0) or 0)
    else:
        parts_sum = _Q2(getattr(sr, "parts_total", 0) or 0)
    
    tasks_sum = Decimal('0.00')
    if hasattr(sr, "tasks") and sr.tasks:
        for t in sr.tasks:
            tasks_sum += _D(t.line_total or 0)
    elif getattr(sr, "id", None):
        try:
            tasks = db.session.query(ServiceTask.line_total).filter(ServiceTask.service_id == sr.id).all()
            for (line_total,) in tasks:
                tasks_sum += _D(line_total or 0)
        except Exception:
            tasks_sum = _Q2(getattr(sr, "labor_total", 0) or 0)
    else:
        tasks_sum = _Q2(getattr(sr, "labor_total", 0) or 0)
    
    discount_total = _Q2(getattr(sr, "discount_total", 0) or 0)
    sr.parts_total = _Q2(parts_sum)
    sr.labor_total = _Q2(tasks_sum)
    total = parts_sum + tasks_sum - discount_total
    if total < 0:
        total = Decimal("0.00")
    sr.total_amount = _Q2(total)
    sr.currency = ensure_currency(getattr(sr, "currency", None) or "ILS")
    tc = _D(getattr(sr, "total_cost", 0) or 0)
    base_for_cost = parts_sum + tasks_sum - discount_total
    if base_for_cost < 0:
        base_for_cost = Decimal("0.00")
    sr.total_cost = _Q2(base_for_cost) if tc < base_for_cost else _Q2(tc)


def _recalc_service_request_totals_sql(connection, service_id: int) -> None:
    sid = int(service_id or 0)
    if sid <= 0:
        return
    try:
        parts_sum = connection.execute(
            sa_text(
                """
                SELECT COALESCE(SUM(COALESCE(quantity, 0) * COALESCE(unit_price, 0) - COALESCE(discount, 0)), 0)
                FROM service_parts
                WHERE service_id = :sid
                """
            ),
            {"sid": sid},
        ).scalar() or 0
        tasks_sum = connection.execute(
            sa_text(
                """
                SELECT COALESCE(SUM(COALESCE(quantity, 0) * COALESCE(unit_price, 0) - COALESCE(discount, 0)), 0)
                FROM service_tasks
                WHERE service_id = :sid
                """
            ),
            {"sid": sid},
        ).scalar() or 0

        row = connection.execute(
            sa_text(
                """
                SELECT COALESCE(discount_total, 0), COALESCE(total_cost, 0), COALESCE(currency, 'ILS')
                FROM service_requests
                WHERE id = :sid
                """
            ),
            {"sid": sid},
        ).first()
        if not row:
            return
        discount_total, prev_cost, curr = row

        parts_d = Decimal(str(parts_sum or 0))
        tasks_d = Decimal(str(tasks_sum or 0))
        disc_d = Decimal(str(discount_total or 0))
        prev_cost_d = Decimal(str(prev_cost or 0))

        total_base = parts_d + tasks_d - disc_d
        if total_base < 0:
            total_base = Decimal("0.00")

        total_amount = q(total_base)
        total_cost = q(total_base) if prev_cost_d < total_base else q(prev_cost_d)

        connection.execute(
            sa_text(
                """
                UPDATE service_requests
                SET parts_total = :pt,
                    labor_total = :lt,
                    total_amount = :ta,
                    total_cost = :tc,
                    currency = :cur,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :sid
                """
            ),
            {
                "sid": sid,
                "pt": q(parts_d),
                "lt": q(tasks_d),
                "ta": total_amount,
                "tc": total_cost,
                "cur": (str(curr or "ILS")).upper(),
            },
        )
    except Exception:
        return

_ALLOWED_SERVICE_TRANSITIONS = {
    "PENDING": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    "COMPLETED": {"IN_PROGRESS"},
    "CANCELLED": set(),
}

@event.listens_for(ServiceRequest, "after_insert")
@event.listens_for(ServiceRequest, "after_update")
def _service_create_tax_entry(mapper, connection, target: ServiceRequest):
    """إنشاء/تحديث سجل ضريبي للصيانة تلقائياً"""
    if target.status not in ['COMPLETED', 'CLOSED']:
        return

    try:
        from sqlalchemy import delete as sa_delete, insert as sa_insert

        service_date = target.received_at or datetime.now(timezone.utc)
        base_amount = float(getattr(target, "total_amount", 0) or 0)
        if base_amount <= 0:
            return

        tax_rate = float(getattr(target, "tax_rate", 0) or 0)
        if tax_rate <= 0:
            connection.execute(
                sa_delete(TaxEntry).where(
                    TaxEntry.transaction_type == 'SERVICE',
                    TaxEntry.transaction_id == target.id
                )
            )
            return

        tax_amount = round(base_amount * (tax_rate / 100.0), 2)
        if tax_amount <= 0:
            return
        total_amount = round(base_amount + tax_amount, 2)
        
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SERVICE',
                TaxEntry.transaction_id == target.id
            )
        )
        
        connection.execute(
            sa_insert(TaxEntry).values(
                entry_type='OUTPUT_VAT',
                transaction_type='SERVICE',
                transaction_id=target.id,
                transaction_reference=target.service_number,
                tax_rate=float(tax_rate),
                base_amount=base_amount,
                tax_amount=tax_amount,
                total_amount=total_amount,
                currency=target.currency or DEFAULT_CURRENCY,
                fiscal_year=service_date.year,
                fiscal_month=service_date.month,
                tax_period=f"{service_date.year}-{service_date.month:02d}",
                customer_id=target.customer_id,
                notes=f'صيانة: {target.service_number}',
                created_at=datetime.now(timezone.utc)
            )
        )
    except Exception:
        pass

@event.listens_for(ServiceRequest, "before_delete")
def _service_delete_tax_entry(mapper, connection, target: ServiceRequest):
    """حذف سجل الضريبة عند حذف الصيانة"""
    try:
        from sqlalchemy import delete as sa_delete
        connection.execute(
            sa_delete(TaxEntry).where(
                TaxEntry.transaction_type == 'SERVICE',
                TaxEntry.transaction_id == target.id
            )
        )
    except Exception:
        pass

@event.listens_for(ServiceRequest, "before_insert")
@event.listens_for(ServiceRequest, "before_update")
def _compute_service_totals(mapper, connection, target: ServiceRequest):
    _recalc_service_request_totals(target)

@event.listens_for(ServiceRequest, "before_update")
def _srv_enforce_transitions(mapper, connection, target: ServiceRequest):
    """
    التحقق من صحة انتقالات حالة طلب الصيانة.
    
    يمنع الانتقالات غير المسموح بها مثل:
    - COMPLETED → PENDING (يجب استخدام "إعادة للصيانة")
    - CANCELLED → أي حالة أخرى
    """
    from sqlalchemy.orm.attributes import get_history
    h = get_history(target, "status")
    oldv = (h.deleted[0] if h.deleted else getattr(target, "status", None))
    newv = getattr(target, "status", None)
    o = (getattr(oldv, "value", oldv) or "PENDING")
    n = getattr(newv, "value", newv)
    if o != n:
        allowed = _ALLOWED_SERVICE_TRANSITIONS.get(o, set())
        if n not in allowed:
            # ترجمة الحالات للعربية للرسالة
            status_names = {
                "PENDING": "قيد الانتظار",
                "DIAGNOSIS": "التشخيص",
                "IN_PROGRESS": "قيد التنفيذ",
                "ON_HOLD": "معلق",
                "COMPLETED": "مكتمل",
                "CANCELLED": "ملغي",
                "CLOSED": "مغلق"
            }
            old_name = status_names.get(o, o)
            new_name = status_names.get(n, n)
            allowed_names = [status_names.get(s, s) for s in allowed]
            raise ValueError(
                f"❌ لا يمكن تغيير حالة الصيانة من '{old_name}' إلى '{new_name}'. "
                f"الحالات المسموح بها: {', '.join(allowed_names)}"
            )

@event.listens_for(ServiceRequest, "before_insert")
def _ensure_service_number(mapper, connection, target: ServiceRequest):
    """
    توليد رقم صيانة فريد تلقائياً إذا لم يتم تحديده.
    
    صيغة الرقم: SRVYYYYMMDD-XXXX
    مثال: SRV20240422-0001
    """
    if getattr(target, "service_number", None):
        # التحقق من عدم تكرار الرقم
        existing = connection.execute(
            sa_text("SELECT id FROM service_requests WHERE service_number = :sn"),
            {"sn": target.service_number}
        ).fetchone()
        if existing:
            raise ValueError(f"❌ رقم الصيانة '{target.service_number}' مستخدم بالفعل في طلب آخر")
        return
    
    prefix = datetime.now(timezone.utc).strftime("SRV%Y%m%d")
    cnt = connection.execute(
        sa_text("SELECT COUNT(*) FROM service_requests WHERE service_number LIKE :pfx"),
        {"pfx": f"{prefix}-%"},
    ).scalar() or 0
    target.service_number = f"{prefix}-{cnt + 1:04d}"

@event.listens_for(ServiceRequest.status, "set")
def _set_completed_at_on_status_change(target, value, oldvalue, initiator):
    newv = getattr(value, "value", value)
    if newv == ServiceStatus.COMPLETED.value and not target.completed_at:
        target.completed_at = datetime.now(timezone.utc)

def run_service_gl_sync_after_commit(service_id: int) -> None:
    """إنشاء/تحديث قيد GL للصيانة في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not service_id:
        return
    try:
        from extensions import db
        with db.engine.connect() as conn:
            with conn.begin():
                _service_gl_batch_upsert_sql(conn, service_id)
    except Exception as e:
        if current_app:
            current_app.logger.warning("Service GL sync failed for service_id=%s: %s", service_id, e, exc_info=True)


def build_service_reversal_snapshot(service: "ServiceRequest") -> dict:
    """لقطة بيانات الصيانة لاستخدامها في قيد العكس بعد الحذف."""
    try:
        amount_ils = float(service.total_amount or 0)
        if service.currency and service.currency != "ILS":
            try:
                from extensions import db
                with db.engine.connect() as c:
                    rate = _fx_rate_local_via_connection(c, service.currency, "ILS", service.received_at or datetime.now(timezone.utc))
                    if rate and rate > 0:
                        amount_ils = float(service.total_amount or 0) * float(rate)
            except Exception:
                pass
        return {
            "service_id": service.id,
            "amount": amount_ils,
            "currency": service.currency or "ILS",
            "entity_type": "CUSTOMER",
            "entity_id": service.customer_id,
        }
    except Exception:
        return {"service_id": getattr(service, "id", None), "amount": 0}


def run_service_gl_reversal_after_delete(snapshot: dict) -> None:
    """تسجيل قيد عكسي SERVICE_REVERSAL بعد حذف الصيانة، في معاملة منفصلة."""
    if not snapshot or not snapshot.get("service_id"):
        return
    try:
        from extensions import db
        service_id = int(snapshot["service_id"])
        amount = float(snapshot.get("amount") or 0)
        if amount <= 0:
            return
        currency = (str(snapshot.get("currency") or "ILS").strip().upper() or "ILS")
        ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
        revenue_account = GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE")
        entity_type = snapshot.get("entity_type")
        entity_id = snapshot.get("entity_id")
        try:
            entity_id = int(entity_id) if entity_id is not None else None
        except (TypeError, ValueError):
            entity_id = None
        entries = [(revenue_account, 0, amount), (ar_account, amount, 0)]
        with db.engine.connect() as conn:
            with conn.begin():
                batch_ids_ps = conn.execute(
                    sa_text("SELECT id FROM gl_batches WHERE source_type = 'SERVICE_PARTNER_SHARE' AND source_id = :sid"),
                    {"sid": service_id},
                ).fetchall()
                for (bid,) in batch_ids_ps:
                    conn.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": int(bid)})
                    conn.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": int(bid)})
                _gl_upsert_batch_and_entries(
                    conn,
                    source_type="SERVICE_REVERSAL",
                    source_id=service_id,
                    purpose="REVERSAL",
                    currency=currency,
                    memo=f"Reversal - deleted service #{service_id}",
                    entries=entries,
                    ref=f"REV-SRV-{service_id}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
    except Exception as e:
        if current_app:
            current_app.logger.warning("Service GL reversal failed for service_id=%s: %s", snapshot.get("service_id"), e, exc_info=True)


@event.listens_for(ServiceRequest, "after_insert")
@event.listens_for(ServiceRequest, "after_update")
def _service_gl_batch_upsert(mapper, connection, target: "ServiceRequest"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_service_gl_sync_after_commit."""
    return


def _service_gl_batch_upsert_sql(connection, service_id: int) -> None:
    sid = int(service_id or 0)
    if sid <= 0:
        return
    try:
        invoice_exists = connection.execute(
            sa_text("SELECT id FROM invoices WHERE service_id = :sid"),
            {"sid": sid}
        ).scalar()
        if invoice_exists:
            return

        row = connection.execute(
            sa_text(
                """
                SELECT
                    id,
                    COALESCE(total_amount, 0),
                    COALESCE(currency, 'ILS'),
                    fx_rate_used,
                    received_at,
                    service_number,
                    customer_id
                FROM service_requests
                WHERE id = :sid
                """
            ),
            {"sid": sid},
        ).first()
        if not row:
            return

        _, total_amount, currency, fx_rate_used, received_at, service_number, customer_id = row

        amount = float(total_amount or 0)
        if amount <= 0:
            return

        cur = (str(currency or "ILS")).upper()
        amount_ils = amount
        if cur != "ILS":
            try:
                if fx_rate_used and float(fx_rate_used) > 0:
                    amount_ils = float(amount * float(fx_rate_used))
                else:
                    rate = _fx_rate_local_via_connection(connection, cur, "ILS", received_at or datetime.now(timezone.utc))
                    if rate and rate > 0:
                        amount_ils = float(amount * float(rate))
            except Exception:
                pass

        total_local = float(total_amount or 0)
        partner_totals = {}
        parts_rows = connection.execute(
            sa_text(
                "SELECT part_id, warehouse_id, quantity, unit_price, discount, partner_id, share_percentage FROM service_parts WHERE service_id = :sid"
            ),
            {"sid": sid},
        ).fetchall()
        for prow in parts_rows:
            qty = float(prow.quantity or 0)
            up = float(prow.unit_price or 0)
            disc = float(prow.discount or 0)
            line_total = qty * up - disc
            if line_total <= 0:
                continue
            pid_cur = prow.partner_id
            pct_cur = float(prow.share_percentage or 0)
            if pid_cur and pct_cur > 0:
                partner_totals[pid_cur] = partner_totals.get(pid_cur, 0.0) + line_total * (pct_cur / 100.0)
            else:
                part_id = prow.part_id
                wh_id = prow.warehouse_id
                partners_rows = connection.execute(
                    sa_text("SELECT partner_id, share_percent FROM product_partners WHERE product_id = :pid"),
                    {"pid": part_id},
                ).fetchall()
                if not partners_rows:
                    partners_rows = connection.execute(
                        sa_text("SELECT partner_id, share_percentage FROM warehouse_partner_shares WHERE product_id = :pid"),
                        {"pid": part_id},
                    ).fetchall()
                if not partners_rows and wh_id:
                    partners_rows = connection.execute(
                        sa_text(
                            "SELECT partner_id, share_percentage FROM warehouse_partner_shares WHERE warehouse_id = :wid AND product_id IS NULL"
                        ),
                        {"wid": wh_id},
                    ).fetchall()
                for (pid2, pct2) in partners_rows:
                    pct2 = float(pct2 or 0)
                    if pct2 > 0:
                        partner_totals[pid2] = partner_totals.get(pid2, 0.0) + line_total * (pct2 / 100.0)

        total_partner_local = sum(partner_totals.values())
        company_share_local = max(0.0, total_local - total_partner_local)
        if total_local > 0:
            company_share_ils = amount_ils * (company_share_local / total_local)
            partner_shares_ils = {int(pid): round(amount_ils * (amt / total_local), 2) for pid, amt in partner_totals.items() if amt > 0}
        else:
            company_share_ils = amount_ils
            partner_shares_ils = {}

        existing_batch = connection.execute(
            sa_text(
                """
                SELECT id FROM gl_batches
                WHERE source_type = 'SERVICE'
                  AND source_id = :sid
                  AND purpose = 'SERVICE'
                  AND status = 'POSTED'
                """
            ),
            {"sid": sid},
        ).scalar()
        if existing_batch:
            connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": existing_batch})
            connection.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": existing_batch})

        batch_ids_ps = connection.execute(
            sa_text("SELECT id FROM gl_batches WHERE source_type = 'SERVICE_PARTNER_SHARE' AND source_id = :sid"),
            {"sid": sid},
        ).fetchall()
        for (bid,) in batch_ids_ps:
            connection.execute(sa_text("DELETE FROM gl_entries WHERE batch_id = :bid"), {"bid": int(bid)})
            connection.execute(sa_text("DELETE FROM gl_batches WHERE id = :bid"), {"bid": int(bid)})

        entries = [
            (GL_ACCOUNTS.get("AR", "1100_AR"), amount_ils, 0),
            (GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE"), 0, amount_ils),
        ]
        memo = f"صيانة - {service_number or sid}"
        _gl_upsert_batch_and_entries(
            connection,
            source_type="SERVICE",
            source_id=sid,
            purpose="SERVICE",
            currency=cur,
            memo=memo,
            entries=entries,
            ref=service_number or f"SRV-{sid}",
            entity_type="CUSTOMER",
            entity_id=customer_id,
        )
        ap_code = (GL_ACCOUNTS.get("AP", "2000_AP") or "2000_AP").upper()
        service_rev_code = (GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE") or "4100_SERVICE_REVENUE").upper()
        for partner_id, amt in partner_shares_ils.items():
            if amt > 0:
                _gl_upsert_batch_and_entries(
                    connection,
                    source_type="SERVICE_PARTNER_SHARE",
                    source_id=sid,
                    purpose=f"PARTNER_{partner_id}",
                    currency=cur,
                    memo=f"حصة شريك من صيانة #{service_number or sid}",
                    entries=[
                        (service_rev_code, amt, 0),
                        (ap_code, 0, amt),
                    ],
                    ref=f"SRV-{sid}-P{partner_id}",
                    entity_type="PARTNER",
                    entity_id=partner_id,
                )
    except Exception:
        return

@event.listens_for(ServiceRequest, "before_delete")
def _service_gl_batch_reverse(mapper, connection, target: "ServiceRequest"):
    """معطّل: القيد العكسي يُنفّذ من المسار بعد الحذف عبر run_service_gl_reversal_after_delete."""
    return

@event.listens_for(ServiceRequest, "after_update")
def _gl_on_service_complete(mapper, connection, target: "ServiceRequest"):
    # معطّل: القيد يُنشأ مباشرة عند إنشاء الصيانة
    return

class ServicePart(db.Model, TimestampMixin):
    __tablename__ = 'service_parts'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service_requests.id', ondelete="CASCADE"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    note = db.Column(db.String(200))
    notes = db.Column(db.Text)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'))
    share_percentage = db.Column(db.Numeric(5, 2), default=0)

    request = db.relationship('ServiceRequest', back_populates='parts')
    part = db.relationship('Product', back_populates='service_parts')
    warehouse = db.relationship('Warehouse', back_populates='service_parts')
    partner = db.relationship('Partner', back_populates='service_parts')

    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_service_part_qty_positive'),
        db.CheckConstraint('unit_price >= 0', name='chk_service_part_price_non_negative'),
        db.CheckConstraint('discount >= 0', name='chk_service_part_discount_positive'),
        db.CheckConstraint('discount <= quantity * unit_price', name='chk_service_part_discount_max'),
        db.CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='chk_service_part_tax_range'),
        db.CheckConstraint('share_percentage >= 0 AND share_percentage <= 100', name='chk_service_part_share_range'),
        db.UniqueConstraint('service_id', 'part_id', 'warehouse_id', name='uq_service_part_unique'),
        db.Index('ix_service_part_pair', 'service_id', 'part_id'),
        db.Index('ix_service_part_partner', 'partner_id'),
    )

    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v)
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @validates('unit_price', 'discount', 'tax_rate', 'share_percentage')
    def _v_money_pct(self, key, v):
        if v in (None, ''):
            return 0
        d = _D(v)
        if key in ('tax_rate', 'share_percentage') and (d < 0 or d > _D(100)):
            raise ValueError(f"{key} must be between 0 and 100")
        if key in ('unit_price', 'discount') and d < 0:
            raise ValueError(f"{key} must be >= 0")
        return _Q2(d)

    @validates('note', 'notes')
    def _v_strip(self, _, v):
        return (str(v).strip() or None) if v is not None else None

    @hybrid_property
    def gross_amount(self):
        return _Q2(_D(self.quantity or 0) * _D(self.unit_price or 0))

    @hybrid_property
    def discount_amount(self):
        return _Q2(_D(self.discount or 0))

    @hybrid_property
    def taxable_amount(self):
        return _Q2(_D(self.gross_amount) - _D(self.discount_amount))

    @hybrid_property
    def tax_amount(self):
        rate = _D(self.tax_rate or 0) / _D(100)
        taxable = _D(self.taxable_amount)
        if taxable < _D(0):
            taxable = _D(0)
        return _Q2(taxable * rate)

    @hybrid_property
    def line_total(self):
        return _Q2(_D(self.taxable_amount))

    @hybrid_property
    def net_total(self):
        share = _D(self.share_percentage or 0) / _D(100)
        return _Q2(_D(self.line_total) * (_D(1) - share))

    def to_dict(self):
        return {
            "id": self.id,
            "service_id": self.service_id,
            "part_id": self.part_id,
            "warehouse_id": self.warehouse_id,
            "partner_id": self.partner_id,
            "share_percentage": float(self.share_percentage or 0),
            "quantity": int(self.quantity or 0),
            "unit_price": float(self.unit_price or 0),
            "discount": float(self.discount or 0),
            "tax_rate": float(self.tax_rate or 0),
            "note": self.note,
            "notes": self.notes,
            "gross_amount": float(self.gross_amount),
            "discount_amount": float(self.discount_amount),
            "taxable_amount": float(self.taxable_amount),
            "tax_amount": float(self.tax_amount),
            "line_total": float(self.line_total),
            "net_total": float(self.net_total),
        }

    def __repr__(self):
        pname = getattr(self.part, "name", None)
        return f"<ServicePart {pname or self.part_id} for Service {self.service_id}>"

class ServiceTask(db.Model, TimestampMixin):
    __tablename__ = 'service_tasks'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service_requests.id', ondelete="CASCADE"), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'))
    share_percentage = db.Column(db.Numeric(5, 2), default=0)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    note = db.Column(db.String(200))

    request = db.relationship('ServiceRequest', back_populates='tasks')
    partner = db.relationship('Partner', back_populates='service_tasks')

    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_service_task_qty_positive'),
        db.CheckConstraint('unit_price >= 0', name='chk_service_task_price_non_negative'),
        db.CheckConstraint('discount >= 0', name='chk_service_task_discount_positive'),
        db.CheckConstraint('discount <= quantity * unit_price', name='chk_service_task_discount_max'),
        db.CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='chk_service_task_tax_range'),
        db.CheckConstraint('share_percentage >= 0 AND share_percentage <= 100', name='chk_service_task_share_range'),
        db.Index('ix_service_task_service', 'service_id'),
        db.Index('ix_service_task_partner', 'partner_id'),
    )

    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v)
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @validates('unit_price', 'discount', 'tax_rate', 'share_percentage')
    def _v_money_pct(self, key, v):
        if v in (None, ''):
            return 0
        d = _D(v)
        if key in ('tax_rate', 'share_percentage') and (d < 0 or d > _D(100)):
            raise ValueError(f"{key} must be between 0 and 100")
        if key in ('unit_price', 'discount') and d < 0:
            raise ValueError(f"{key} must be >= 0")
        return _Q2(d)

    @validates('description', 'note')
    def _v_strip(self, _, v):
        return (str(v).strip() or None) if v is not None else None

    @hybrid_property
    def gross_amount(self):
        return _Q2(_D(self.quantity or 0) * _D(self.unit_price or 0))

    @hybrid_property
    def discount_amount(self):
        return _Q2(_D(self.discount or 0))

    @hybrid_property
    def taxable_amount(self):
        return _Q2(_D(self.gross_amount) - _D(self.discount_amount))

    @hybrid_property
    def tax_amount(self):
        rate = _D(self.tax_rate or 0) / _D(100)
        taxable = _D(self.taxable_amount)
        if taxable < _D(0):
            taxable = _D(0)
        return _Q2(taxable * rate)

    @hybrid_property
    def line_total(self):
        return _Q2(_D(self.taxable_amount))

    @hybrid_property
    def net_total(self):
        share = _D(self.share_percentage or 0) / _D(100)
        return _Q2(_D(self.line_total) * (_D(1) - share))

    def to_dict(self):
        return {
            "id": self.id,
            "service_id": self.service_id,
            "partner_id": self.partner_id,
            "share_percentage": float(self.share_percentage or 0),
            "description": self.description,
            "quantity": int(self.quantity or 0),
            "unit_price": float(self.unit_price or 0),
            "discount": float(self.discount or 0),
            "tax_rate": float(self.tax_rate or 0),
            "note": self.note,
            "gross_amount": float(self.gross_amount),
            "discount_amount": float(self.discount_amount),
            "taxable_amount": float(self.taxable_amount),
            "tax_amount": float(self.tax_amount),
            "line_total": float(self.line_total),
            "net_total": float(self.net_total),
        }

    def __repr__(self):
        return f"<ServiceTask {self.description} for Service {self.service_id}>"

def _recalc_service_totals_orm_safe(session, service_id: int):
    sid = int(service_id or 0)
    if sid <= 0: return
    try:
        parts_sum = session.execute(
            sa_text("SELECT COALESCE(SUM(COALESCE(quantity, 0) * COALESCE(unit_price, 0) - COALESCE(discount, 0)), 0) FROM service_parts WHERE service_id = :sid"),
            {"sid": sid}
        ).scalar() or 0
        tasks_sum = session.execute(
            sa_text("SELECT COALESCE(SUM(COALESCE(quantity, 0) * COALESCE(unit_price, 0) - COALESCE(discount, 0)), 0) FROM service_tasks WHERE service_id = :sid"),
            {"sid": sid}
        ).scalar() or 0
        
        row = session.execute(
            sa_text("SELECT discount_total, total_cost, currency FROM service_requests WHERE id = :sid"),
            {"sid": sid}
        ).first()
        
        if not row: return
        discount_total, prev_cost, curr = row
        
        parts_d = Decimal(str(parts_sum))
        tasks_d = Decimal(str(tasks_sum))
        disc_d = Decimal(str(discount_total or 0))
        
        total_base = parts_d + tasks_d - disc_d
        if total_base < 0: total_base = Decimal("0.00")
        
        prev_cost_d = Decimal(str(prev_cost or 0))
        new_cost = total_base if prev_cost_d < total_base else prev_cost_d
        
        session.connection().execute(
            sa_text("""
                UPDATE service_requests 
                SET parts_total = :pt, 
                    labor_total = :lt, 
                    total_amount = :ta, 
                    total_cost = :tc,
                    currency = :cur,
                    updated_at = :now
                WHERE id = :sid
            """),
            {
                "sid": sid,
                "pt": parts_d,
                "lt": tasks_d,
                "ta": total_base,
                "tc": new_cost,
                "cur": (curr or "ILS").upper(),
                "now": datetime.now(timezone.utc)
            }
        )
        
        sr = session.get(ServiceRequest, sid)
        if sr:
            session.expire(sr)
    except Exception:
        pass

@event.listens_for(ServiceRequest, "before_update")
def _deduct_stock_on_complete(mapper, connection, target):
    """
    Stock on completion/reopen is handled in routes/service.toggle_service via
    _consume_service_stock_once / _release_service_stock_once (AuditLog-aware, idempotent).

    The previous implementation deducted again here on COMPLETED while add_part() already
    applied STOCK_CONSUME_PART via utils._apply_stock_delta — double deduction from inventory.
    """
    return

@event.listens_for(ServicePart, "after_insert")
def _sp_after_insert(mapper, connection, target: ServicePart):
    """
    بعد إضافة قطعة جديدة لطلب الصيانة:
    1. إعادة حساب إجماليات الطلب
    2. تحديث قيد المحاسبة (GL)
    3. تحديث رصيد الشريك إن وجد
    """
    sid = int(getattr(target, "service_id", 0) or 0)
    session = object_session(target)
    if sid and session:
        _recalc_service_totals_orm_safe(session, sid)
    elif sid:
        _recalc_service_request_totals_sql(connection, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    if hasattr(target, 'partner_id') and target.partner_id:
        _queue_partner_balance(target, target.partner_id)

@event.listens_for(ServicePart, "after_update")
def _sp_after_update(mapper, connection, target: ServicePart):
    """
    بعد تعديل قطعة في طلب الصيانة:
    1. إعادة حساب إجماليات الطلب
    2. تحديث قيد المحاسبة (GL)
    3. تحديث رصيد الشريك إن وجد
    
    ملاحظة: تحديث المخزون يتم في routes/service.edit_part وليس هنا
    لتجنب تكرار الخصم (double deduction)
    """
    sid = int(getattr(target, "service_id", 0) or 0)
    session = object_session(target)
    if sid and session:
        _recalc_service_totals_orm_safe(session, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    elif sid:
        _recalc_service_request_totals_sql(connection, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    if hasattr(target, 'partner_id') and target.partner_id:
        _queue_partner_balance(target, target.partner_id)

@event.listens_for(ServicePart, "after_delete")
def _sp_after_delete(mapper, connection, target: ServicePart):
    """
    بعد حذف قطعة من طلب الصيانة:
    1. إعادة حساب إجماليات الطلب
    2. تحديث قيد المحاسبة (GL)
    3. تحديث رصيد الشريك إن وجد
    
    ملاحظة: إرجاع المخزون يتم في routes/service.delete_part وليس هنا
    """
    sid = int(getattr(target, "service_id", 0) or 0)
    session = object_session(target)
    if sid and session:
        _recalc_service_totals_orm_safe(session, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    elif sid:
        _recalc_service_request_totals_sql(connection, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    partner_id = None
    try:
        partner_id = target.__dict__.get("partner_id")
    except Exception:
        partner_id = None
    if partner_id:
        _queue_partner_balance(target, partner_id)

@event.listens_for(ServiceTask, "after_insert")
@event.listens_for(ServiceTask, "after_update")
@event.listens_for(ServiceTask, "after_delete")
def _st_sync_totals(mapper, connection, target: ServiceTask):
    sid = int(getattr(target, "service_id", 0) or 0)
    session = object_session(target)
    if sid and session:
        _recalc_service_totals_orm_safe(session, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    elif sid:
        _recalc_service_request_totals_sql(connection, sid)
        _service_gl_batch_upsert_sql(connection, sid)
    partner_id = None
    try:
        partner_id = target.__dict__.get("partner_id")
    except Exception:
        partner_id = None
    if partner_id:
        _queue_partner_balance(target, partner_id)

class OnlineCart(db.Model, TimestampMixin):
    __tablename__ = 'online_carts'

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.String(50), unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), index=True)
    session_id = db.Column(db.String(100), index=True)
    status = db.Column(sa_str_enum(OnlineCartStatus, name='cart_status'),
                       default=OnlineCartStatus.ACTIVE.value, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, index=True)

    customer = db.relationship('Customer', back_populates='online_carts')
    items = db.relationship('OnlineCartItem', back_populates='cart', cascade='all, delete-orphan')

    __table_args__ = ()

    @hybrid_property
    def subtotal(self) -> float:
        total = _D(0)
        for i in (self.items or []):
            total += _D(i.line_total or 0)
        return float(_Q2(total))

    @hybrid_property
    def item_count(self) -> int:
        return sum(int(i.quantity or 0) for i in (self.items or []))

    @hybrid_property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def to_dict(self):
        return {
            "id": self.id,
            "cart_id": self.cart_id,
            "customer_id": self.customer_id,
            "session_id": self.session_id,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "item_count": self.item_count,
            "subtotal": self.subtotal,
            "is_expired": self.is_expired,
        }

    def __repr__(self):
        return f"<OnlineCart {self.cart_id or self.id}>"


@event.listens_for(OnlineCart, 'before_insert')
def _cart_before_insert(mapper, connection, target: 'OnlineCart'):
    if not getattr(target, 'cart_id', None):
        prefix = datetime.now(timezone.utc).strftime("CRT%Y%m%d")
        count = connection.execute(
            sa_text("SELECT COUNT(*) FROM online_carts WHERE cart_id LIKE :pfx"),
            {"pfx": f"{prefix}-%"},
        ).scalar() or 0
        target.cart_id = f"{prefix}-{count+1:04d}"
    if not getattr(target, 'expires_at', None):
        target.expires_at = datetime.now(timezone.utc) + timedelta(days=7)


class OnlineCartItem(db.Model):
    __tablename__ = 'online_cart_items'

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('online_carts.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='RESTRICT'),
                           nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    cart = db.relationship('OnlineCart', back_populates='items')
    product = db.relationship('Product', back_populates='online_cart_items')

    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_cart_item_qty_positive'),
        db.CheckConstraint('price >= 0', name='chk_cart_item_price_non_negative'),
        db.Index('ix_cart_item_cart_product', 'cart_id', 'product_id'),
        db.UniqueConstraint('cart_id', 'product_id', name='uq_cart_item_cart_product'),
    )

    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v)
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @hybrid_property
    def line_total(self) -> Decimal:
        return _Q2(_D(self.quantity or 0) * _D(self.price or 0))

    def to_dict(self):
        return {
            "id": self.id,
            "cart_id": self.cart_id,
            "product_id": self.product_id,
            "quantity": int(self.quantity or 0),
            "price": float(self.price or 0),
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "line_total": float(self.line_total),
        }

    def __repr__(self):
        pname = getattr(self.product, 'name', None)
        return f"<OnlineCartItem {pname or self.product_id} x{self.quantity}>"


@event.listens_for(OnlineCartItem, 'before_insert')
@event.listens_for(OnlineCartItem, 'before_update')
def _cart_item_price_default(mapper, connection, target: 'OnlineCartItem'):
    if target.price in (None, 0):
        price = connection.execute(
            sa_text("SELECT COALESCE(online_price, price) FROM products WHERE id = :pid"),
            {"pid": target.product_id}
        ).scalar()
        target.price = _Q2(price or 0)


class OnlinePreOrder(db.Model, TimestampMixin):
    __tablename__ = 'online_preorders'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('online_carts.id', ondelete='SET NULL'))
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='SET NULL'), index=True)
    warehouse = db.relationship('Warehouse')

    prepaid_amount = db.Column(db.Numeric(12, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    base_amount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    currency = db.Column(db.String(10), default='ILS', nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    expected_fulfillment = db.Column(db.DateTime)
    actual_fulfillment = db.Column(db.DateTime)

    status = db.Column(sa_str_enum(PreOrderStatus, name='online_preorder_status'),
                       default=PreOrderStatus.PENDING.value, nullable=False, index=True, server_default=sa_text("'PENDING'"))
    payment_status = db.Column(sa_str_enum(PaymentProgress, name='online_preorder_payment_status'),
                               default=PaymentProgress.PENDING.value, nullable=False, index=True, server_default=sa_text("'PENDING'"))

    payment_method = db.Column(db.String(50))
    notes = db.Column(db.Text)
    shipping_address = db.Column(db.Text)
    billing_address = db.Column(db.Text)

    customer = db.relationship('Customer', back_populates='online_preorders')
    cart = db.relationship('OnlineCart')
    items = db.relationship('OnlinePreOrderItem', back_populates='order', cascade='all, delete-orphan')
    payments = db.relationship('OnlinePayment', back_populates='order')
    gl_batches = db.relationship("GLBatch", primaryjoin="and_(foreign(GLBatch.source_id)==OnlinePreOrder.id, GLBatch.source_type=='ONLINE_PREORDER')", viewonly=True, order_by="GLBatch.id")

    __table_args__ = (
        db.CheckConstraint('prepaid_amount >= 0', name='chk_online_prepaid_non_negative'),
        db.CheckConstraint('total_amount  >= 0', name='chk_online_total_non_negative'),
        db.CheckConstraint('base_amount >= 0', name='chk_online_base_non_negative'),
        db.CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='chk_online_tax_rate_0_100'),
        db.CheckConstraint('tax_amount >= 0', name='chk_online_tax_non_negative'),
        db.Index('ix_online_preorders_customer_status', 'customer_id', 'status'),
        db.Index('ix_online_preorders_status_paystatus', 'status', 'payment_status'),
    )

    @validates('status', 'payment_status')
    def _upper(self, _, v):
        return v.upper() if isinstance(v, str) else v

    @hybrid_property
    def items_subtotal(self) -> float:
        total = _D(0)
        for i in (self.items or []):
            total += _D(i.line_total or 0)
        return float(_Q2(total))

    @hybrid_property
    def total_paid(self) -> float:
        total = _D(0)
        for p in (self.payments or []):
            if getattr(p, 'status', None) == 'SUCCESS':
                total += _D(p.amount or 0)
        return float(_Q2(total))

    @hybrid_property
    def balance_due(self) -> float:
        return float(_Q2(_D(self.total_amount or 0) - (_D(self.prepaid_amount or 0) + _D(self.total_paid or 0))))

    def update_totals_and_status(self):
        total = _D(0)
        for i in (self.items or []):
            total += _D(i.line_total or 0)
        self.total_amount = _Q2(total)

        paid_total = float(_Q2(_D(self.total_paid or 0) + _D(self.prepaid_amount or 0)))
        total_num = float(self.total_amount or 0)
        if total_num > 0 and paid_total >= total_num:
            self.payment_status = 'PAID'
        elif paid_total > 0:
            self.payment_status = 'PARTIAL'
        else:
            self.payment_status = 'PENDING'

    def to_dict(self):
        return {
            "id": self.id,
            "order_number": self.order_number,
            "customer_id": self.customer_id,
            "cart_id": self.cart_id,
            "prepaid_amount": float(self.prepaid_amount or 0),
            "total_amount": float(self.total_amount or 0),
            "expected_fulfillment": self.expected_fulfillment.isoformat() if self.expected_fulfillment else None,
            "actual_fulfillment": self.actual_fulfillment.isoformat() if self.actual_fulfillment else None,
            "status": self.status,
            "payment_status": self.payment_status,
            "payment_method": self.payment_method,
            "notes": self.notes,
            "shipping_address": self.shipping_address,
            "billing_address": self.billing_address,
            "items_subtotal": self.items_subtotal,
            "total_paid": self.total_paid,
            "balance_due": self.balance_due,
        }

    def __repr__(self):
        return f"<OnlinePreOrder {self.order_number or self.id}>"


@event.listens_for(OnlinePreOrder, 'before_insert')
def _op_before_insert(mapper, connection, target: 'OnlinePreOrder'):
    if not getattr(target, 'order_number', None):
        prefix = datetime.now(timezone.utc).strftime("OPR%Y%m%d")
        count = connection.execute(
            sa_text("SELECT COUNT(*) FROM online_preorders WHERE order_number LIKE :pfx"),
            {"pfx": f"{prefix}-%"},
        ).scalar() or 0
        target.order_number = f"{prefix}-{count + 1:04d}"

    if not getattr(target, 'warehouse_id', None):
        tval = WarehouseType.ONLINE.value
        row = connection.execute(
            sa_text("SELECT id FROM warehouses WHERE warehouse_type = :t AND is_active = 1 ORDER BY id LIMIT 1"),
            {"t": tval}
        ).first()
        if row:
            target.warehouse_id = row._mapping["id"]
        else:
            connection.execute(
                sa_text("INSERT INTO warehouses (name, warehouse_type, is_active) VALUES (:n, :t, 1)"),
                {"n": "ONLINE", "t": tval}
            )
            row2 = connection.execute(
                sa_text("SELECT id FROM warehouses WHERE warehouse_type = :t AND name = :n ORDER BY id DESC LIMIT 1"),
                {"t": tval, "n": "ONLINE"}
            ).first()
            if row2:
                target.warehouse_id = row2._mapping["id"]

    target.update_totals_and_status()


@event.listens_for(OnlinePreOrder, 'before_update')
def _op_before_update(mapper, connection, target: 'OnlinePreOrder'):
    target.update_totals_and_status()


# ===== إنشاء قيود GL تلقائية للطلبات الأونلاين =====
@event.listens_for(OnlinePreOrder, "after_insert")
@event.listens_for(OnlinePreOrder, "after_update")
def _online_preorder_gl_batch_upsert(mapper, connection, target: "OnlinePreOrder"):
    """إنشاء/تحديث GLBatch للطلب الأونلاين تلقائياً"""
    
    # إذا الطلب ملغى، عكس القيد بدلاً من حذفه
    if target.payment_status == 'CANCELLED':
        try:
            amount = float(target.total_amount or 0)
            if amount > 0:
                amount_ils = amount
                if target.currency and target.currency != 'ILS':
                    try:
                        rate = _fx_rate_local_via_connection(connection, target.currency, 'ILS', target.created_at or datetime.now(timezone.utc))
                        if rate and rate > 0:
                            amount_ils = float(amount * float(rate))
                    except Exception:
                        pass
                
                ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
                revenue_account = GL_ACCOUNTS.get("SALES", "4000_SALES")
                
                entries = [(revenue_account, amount_ils, 0), (ar_account, 0, amount_ils)]
                
                _gl_upsert_batch_and_entries(
                    connection,
                    source_type="ONLINE_ORDER_REVERSAL",
                    source_id=target.id,
                    purpose="REVERSAL",
                    currency="ILS",
                    memo=f"عكس قيد - إلغاء طلب أونلاين #{target.id}",
                    entries=entries,
                    ref=f"REV-ONL-{target.id}",
                    entity_type="CUSTOMER",
                    entity_id=target.customer_id
                )
        except Exception:
            pass
        return
    
    # التحقق من وجود مبلغ
    amount = float(target.total_amount or 0)
    if amount <= 0:
        return
    
    try:
        # القيد المحاسبي للطلب الأونلاين:
        # مدين: 1100_AR (حساب العملاء)
        # دائن: 2300_ADV_PAY (دفعات مقدمة)
        entries = [
            (GL_ACCOUNTS.get("AR", "1100_AR"), amount, 0),
            (GL_ACCOUNTS.get("ADVANCE", "2300_ADV_PAY"), 0, amount),
        ]
        
        memo = f"طلب أونلاين - {target.order_number or target.id}"
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="ONLINE_ORDER",
            source_id=target.id,
            purpose="ONLINE_ORDER",
            currency="ILS",
            memo=memo,
            entries=entries,
            ref=target.order_number or f"ONL-{target.id}",
            entity_type="CUSTOMER",
            entity_id=target.customer_id
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في إنشاء GLBatch للطلب الأونلاين #{target.id}: {e}")

@event.listens_for(OnlinePreOrder, "after_update")
def _op_reservation_flow(mapper, connection, target: "OnlinePreOrder"):
    hist = inspect(target)
    h = hist.attrs['status'].history
    old_status = (h.deleted[0] if h.deleted else getattr(target, "status", "") or "").upper()
    new_status = (h.added[0] if h.added else getattr(target, "status", "") or "").upper()
    if old_status == new_status:
        return

    wid = getattr(target, "warehouse_id", None)
    if not wid:
        tval = WarehouseType.ONLINE.value
        row = connection.execute(
            sa_text("SELECT id FROM warehouses WHERE warehouse_type = :t AND is_active = 1 ORDER BY id LIMIT 1"),
            {"t": tval}
        ).first()
        if row:
            wid = row._mapping["id"]
        else:
            return

    def _each_item(fn):
        for it in (target.items or []):
            pid = getattr(it, "product_id", None)
            qty = int(getattr(it, "quantity", 0) or 0)
            if pid and qty > 0:
                fn(pid, qty)

    if new_status == "CONFIRMED" and old_status != "CONFIRMED":
        _each_item(lambda pid, qty: _apply_reservation_delta(connection, pid, wid, +qty))
    elif new_status == "FULFILLED":
        def _consume(pid, qty):
            _apply_reservation_delta(connection, pid, wid, -qty)
            _apply_stock_delta(connection, pid, wid, -qty)
        _each_item(_consume)
    elif old_status == "CONFIRMED" and new_status != "CONFIRMED":
        _each_item(lambda pid, qty: _apply_reservation_delta(connection, pid, wid, -qty))


class OnlinePreOrderItem(db.Model):
    __tablename__ = 'online_preorder_items'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('online_preorders.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='RESTRICT'),
                           nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)

    order = db.relationship('OnlinePreOrder', back_populates='items')
    product = db.relationship('Product', back_populates='online_preorder_items')

    __table_args__ = (
        db.CheckConstraint('quantity > 0', name='chk_online_item_qty_positive'),
        db.CheckConstraint('price >= 0', name='chk_online_item_price_non_negative'),
        db.Index('ix_online_item_order_product', 'order_id', 'product_id'),
        db.UniqueConstraint('order_id', 'product_id', name='uq_online_item_order_product'),
    )

    @validates('quantity')
    def _v_qty(self, _, v):
        v = int(v)
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @hybrid_property
    def line_total(self) -> Decimal:
        return _Q2(_D(self.quantity or 0) * _D(self.price or 0))

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "quantity": int(self.quantity or 0),
            "price": float(self.price or 0),
            "line_total": float(self.line_total),
        }

    def __repr__(self):
        pname = getattr(self.product, 'name', None)
        return f"<OnlinePreOrderItem {pname or self.product_id} x{self.quantity}>"


@event.listens_for(OnlinePreOrderItem, 'before_insert')
@event.listens_for(OnlinePreOrderItem, 'before_update')
def _op_item_price_default(mapper, connection, target: 'OnlinePreOrderItem'):
    if target.price in (None, 0):
        price = connection.execute(
            sa_text("SELECT COALESCE(online_price, price) FROM products WHERE id = :pid"),
            {"pid": target.product_id}
        ).scalar()
        target.price = _Q2(price or 0)

@event.listens_for(_SA_Session, "before_flush")
def _op_items_before_flush(session, flush_context, instances):
    try:
        orders = []
        seen = set()
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            try:
                if not isinstance(obj, (OnlinePreOrderItem, OnlinePayment)):
                    continue
                order_obj = getattr(obj, "order", None)
                if order_obj is None:
                    oid = getattr(obj, "order_id", None)
                    if oid:
                        order_obj = session.get(OnlinePreOrder, int(oid))
                if order_obj is None:
                    continue
                oid2 = getattr(order_obj, "id", None)
                if oid2 is not None and oid2 in seen:
                    continue
                if oid2 is not None:
                    seen.add(oid2)
                orders.append(order_obj)
            except Exception:
                continue
        for order_obj in orders:
            try:
                order_obj.update_totals_and_status()
            except Exception:
                pass
    except Exception:
        pass


class OnlinePayment(db.Model, TimestampMixin):
    __tablename__ = 'online_payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_ref = db.Column(db.String(100), unique=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('online_preorders.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(10), default='ILS', nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))
    
    method = db.Column(db.String(50))
    gateway = db.Column(db.String(50))
    status = db.Column(sa_str_enum(OnlinePaymentStatus, name='online_payment_status'),
                       default=OnlinePaymentStatus.PENDING.value, nullable=False, index=True, server_default=sa_text("'PENDING'"))
    transaction_data = db.Column(db.JSON)
    processed_at = db.Column(db.DateTime)
    card_last4 = db.Column(db.String(4), index=True)
    card_encrypted = db.Column(db.LargeBinary)
    card_expiry = db.Column(db.String(5))
    cardholder_name = db.Column(db.String(128))
    card_brand = db.Column(db.String(20))
    card_fingerprint = db.Column(db.String(64), index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id', ondelete='SET NULL'), index=True)
    idempotency_key = db.Column(db.String(64), unique=True, index=True)

    order = db.relationship('OnlinePreOrder', back_populates='payments')

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='chk_online_payment_amount_positive'),
        db.Index('ix_online_payments_order_status', 'order_id', 'status'),
        db.Index('ix_online_payments_gateway_status', 'gateway', 'status'),
    )

    @validates('amount')
    def _v_amount(self, _, v):
        if v is None or float(v) <= 0:
            raise ValueError("amount must be > 0")
        return _Q2(v)

    @validates('currency')
    def _v_currency(self, _, v):
        return ensure_currency(v or DEFAULT_CURRENCY)

    @validates('status')
    def _v_status(self, _, v):
        return v.upper() if isinstance(v, str) else v

    @validates('method', 'gateway')
    def _v_lower(self, _, v):
        return (v or None).lower() if isinstance(v, str) and v else v

    @staticmethod
    def _luhn_check(pan_digits: str) -> bool:
        if not pan_digits or not pan_digits.isdigit():
            return False
        s, alt = 0, False
        for d in pan_digits[::-1]:
            n = ord(d) - 48
            if alt:
                n *= 2
                if n > 9:
                    n -= 9
            s += n
            alt = not alt
        return s % 10 == 0

    @staticmethod
    def _is_valid_expiry_mm_yy(exp: str) -> bool:
        if not exp or not re.match(r'^\d{2}/\d{2}$', exp):
            return False
        mm, yy = exp.split('/')
        try:
            mm = int(mm)
            yy = int('20' + yy)
            if not (1 <= mm <= 12):
                return False
            now = datetime.now(timezone.utc)
            return (yy > now.year) or (yy == now.year and mm >= now.month)
        except Exception:
            return False

    @staticmethod
    def _detect_brand(pan_digits: str) -> str:
        if not pan_digits:
            return 'UNKNOWN'
        if pan_digits.startswith('4'):
            return 'VISA'
        i2 = int(pan_digits[:2]) if len(pan_digits) >= 2 else -1
        i4 = int(pan_digits[:4]) if len(pan_digits) >= 4 else -1
        if 51 <= i2 <= 55 or (2221 <= i4 <= 2720):
            return 'MASTERCARD'
        if i2 in (34, 37):
            return 'AMEX'
        return 'UNKNOWN'

    @staticmethod
    def _get_fernet():
        try:
            from cryptography.fernet import Fernet
            key = current_app.config.get('CARD_ENC_KEY')
            if not key:
                return None
            if isinstance(key, str):
                key = key.encode('utf-8')
            return Fernet(key)
        except Exception:
            return None

    def set_card_details(self, pan: str | None, holder: str | None,
                         expiry_mm_yy: str | None, *, validate: bool = True) -> None:
        pan_digits = ''.join((pan or '')).strip()
        pan_digits = ''.join(ch for ch in pan_digits if ch.isdigit())

        self.cardholder_name = (holder or '').strip() or None
        self.card_expiry = (expiry_mm_yy or '').strip() or None

        if pan_digits:
            if validate and not self._luhn_check(pan_digits):
                raise ValueError("Invalid card number (Luhn check failed)")
            self.card_last4 = pan_digits[-4:]
            self.card_fingerprint = hashlib.sha256(pan_digits.encode('utf-8')).hexdigest()
            self.card_brand = self._detect_brand(pan_digits)
            f = self._get_fernet()
            self.card_encrypted = f.encrypt(pan_digits.encode('utf-8')) if f else None
        else:
            self.card_last4 = None
            self.card_fingerprint = None
            self.card_brand = None
            self.card_encrypted = None

        if self.card_expiry and validate and not self._is_valid_expiry_mm_yy(self.card_expiry):
            raise ValueError("Invalid card expiry (MM/YY)")

    def decrypt_card_number(self) -> str | None:
        if not self.card_encrypted:
            return None
        f = self._get_fernet()
        if not f:
            return None
        try:
            return f.decrypt(self.card_encrypted).decode('utf-8')
        except Exception:
            return None

    def masked_card(self) -> str | None:
        return f"**** **** **** {self.card_last4}" if self.card_last4 else None

    @property
    def has_encrypted_card(self) -> bool:
        return bool(self.card_encrypted)

    def to_dict(self):
        return {
            "id": self.id,
            "payment_ref": self.payment_ref,
            "order_id": self.order_id,
            "amount": float(self.amount or 0),
            "currency": self.currency,
            "method": self.method,
            "gateway": self.gateway,
            "status": self.status,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "card_brand": self.card_brand,
            "card_last4": self.card_last4,
            "card_masked": self.masked_card(),
            "payment_id": self.payment_id,
            "idempotency_key": self.idempotency_key,
        }

    def __repr__(self):
        ref = self.payment_ref or f"OP-{self.id}"
        return f"<OnlinePayment {ref} {self.amount} {self.currency} {self.status}>"


_ALLOWED_OPAY_TRANSITIONS = {
    "PENDING": {"SUCCESS", "FAILED", "REFUNDED"},
    "SUCCESS": {"REFUNDED"},
    "FAILED": set(),
    "REFUNDED": set(),
}

def _opay_enforce_transition(old: str | None, new: str) -> None:
    o = (old or "PENDING").upper()
    n = (new or "").upper()
    if o == n:
        return
    allowed = _ALLOWED_OPAY_TRANSITIONS.get(o, set())
    if n not in allowed:
        raise ValueError("online_payment.invalid_status_transition")


@event.listens_for(OnlinePayment, "after_insert")
@event.listens_for(OnlinePayment, "after_update")
@event.listens_for(OnlinePayment, "after_delete")
def _opay_touch_order(mapper, connection, target: "OnlinePayment"):
    return


@event.listens_for(OnlinePayment, "before_insert")
def _opay_before_insert(mapper, connection, target: "OnlinePayment"):
    if not getattr(target, "payment_ref", None):
        prefix = datetime.now(timezone.utc).strftime("OPAY%Y%m%d")
        count = connection.execute(
            sa_text("SELECT COUNT(*) FROM online_payments WHERE payment_ref LIKE :pfx"),
            {"pfx": f"{prefix}-%"},
        ).scalar() or 0
        target.payment_ref = f"{prefix}-{count+1:04d}"
    target.currency = ensure_currency(target.currency or "ILS")
    st = (target.status or "").upper()
    if st in ("SUCCESS", "FAILED", "REFUNDED") and not target.processed_at:
        target.processed_at = datetime.now(timezone.utc)


@event.listens_for(OnlinePayment, "before_update")
def _opay_before_update(mapper, connection, target: "OnlinePayment"):
    from sqlalchemy.orm.attributes import get_history
    target.currency = ensure_currency(target.currency or "ILS")
    h = get_history(target, "status")
    prev = (h.deleted[0] if h.deleted else getattr(target, "status", None))
    _opay_enforce_transition(prev, getattr(target, "status", None))
    st = (target.status or "").upper()
    if st in ("SUCCESS", "FAILED", "REFUNDED") and not target.processed_at:
        target.processed_at = datetime.now(timezone.utc)


class UtilityAccount(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "utility_accounts"

    id = db.Column(db.Integer, primary_key=True)
    utility_type = db.Column(db.String(20), nullable=False, index=True)
    provider = db.Column(db.String(120), nullable=False)
    account_no = db.Column(db.String(100), index=True)
    meter_no = db.Column(db.String(100), index=True)
    alias = db.Column(db.String(120), index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    expenses = relationship("Expense", back_populates="utility_account", order_by="Expense.id")

    __table_args__ = (
        CheckConstraint("utility_type IN ('ELECTRICITY','WATER')", name="ck_utility_type_allowed"),
        db.UniqueConstraint("utility_type", "provider", "account_no", name="uq_utility_key"),
        db.Index("ix_utility_active_type", "is_active", "utility_type"),
    )

    @validates("utility_type")
    def _v_utype(self, _, v):
        s = (v or "").strip().upper()
        if s not in {"ELECTRICITY", "WATER"}:
            raise ValueError("invalid utility_type")
        return s

    @validates("provider", "account_no", "meter_no", "alias")
    def _v_strip(self, _, v):
        return (v or "").strip() or None

    def __repr__(self):
        return f"<UtilityAccount {self.utility_type}:{self.alias or self.account_no}>"


class StockAdjustment(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "stock_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    reason = db.Column(db.String(20), nullable=False, index=True)
    notes = db.Column(db.Text)
    total_cost = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    warehouse = db.relationship("Warehouse", back_populates="stock_adjustments")
    items = db.relationship("StockAdjustmentItem", back_populates="adjustment", cascade="all, delete-orphan", order_by="StockAdjustmentItem.id")
    expense = db.relationship("Expense", back_populates="stock_adjustment", uselist=False)

    __table_args__ = (
        CheckConstraint("reason IN ('DAMAGED','STORE_USE')", name="ck_stock_adjustment_reason_allowed"),
        CheckConstraint("total_cost >= 0", name="ck_stock_adjustment_total_cost_non_negative"),
        db.Index("ix_stock_adjust_wh_reason_date", "warehouse_id", "reason", "date"),
    )

    @validates("reason")
    def _v_reason(self, _, v):
        s = (v or "").strip().upper()
        if s not in {"DAMAGED", "STORE_USE"}:
            raise ValueError("invalid reason")
        return s

    def __repr__(self):
        return f"<StockAdjustment {self.reason} #{self.id}>"


class StockAdjustmentItem(db.Model):
    __tablename__ = "stock_adjustment_items"

    id = db.Column(db.Integer, primary_key=True)
    adjustment_id = db.Column(db.Integer, db.ForeignKey("stock_adjustments.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='SET NULL'), index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.String(200))

    adjustment = db.relationship("StockAdjustment", back_populates="items")
    product = db.relationship("Product", back_populates="stock_adjustment_items")
    warehouse = db.relationship('Warehouse')

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_adjustment_item_qty_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_stock_adjustment_item_cost_non_negative"),
        db.Index("ix_sai_prod_wh", "product_id", "warehouse_id"),
    )

    @validates("quantity")
    def _v_qty(self, _, v):
        v = int(v or 0)
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @validates("unit_cost")
    def _v_cost(self, _, v):
        d = q(v or 0)
        if d < 0:
            raise ValueError("unit_cost must be >= 0")
        return d

    @hybrid_property
    def line_total(self):
        return q(D(self.quantity or 0) * D(self.unit_cost or 0))

    def __repr__(self):
        return f"<StockAdjustmentItem P{self.product_id} Q{self.quantity}>"


def _recompute_stock_adjustment_total(connection, adjustment_id: int):
    total = connection.execute(
        select(func.coalesce(func.sum(StockAdjustmentItem.quantity * StockAdjustmentItem.unit_cost), 0.0))
        .where(StockAdjustmentItem.adjustment_id == adjustment_id)
    ).scalar_one() or 0.0
    connection.execute(
        update(StockAdjustment)
        .where(StockAdjustment.id == adjustment_id)
        .values(total_cost=q(total))
    )


@event.listens_for(StockAdjustment, "before_insert")
@event.listens_for(StockAdjustment, "before_update")
def _sa_normalize(mapper, connection, target: StockAdjustment):
    target.reason = (target.reason or "").strip().upper()


@event.listens_for(StockAdjustment, "after_update")
def _sa_sync_expense_amount(mapper, connection, target: StockAdjustment):
    if getattr(target, "expense", None) and target.id:
        connection.execute(
            update(Expense)
            .where(Expense.stock_adjustment_id == int(target.id))
            .values(amount=q(target.total_cost or 0))
        )


@event.listens_for(StockAdjustmentItem, "after_insert")
def _sai_after_insert(mapper, connection, target: StockAdjustmentItem):
    if target.warehouse_id:
        _apply_stock_delta(connection, target.product_id, target.warehouse_id, -int(target.quantity or 0))
    if target.adjustment_id:
        _recompute_stock_adjustment_total(connection, int(target.adjustment_id))


@event.listens_for(StockAdjustmentItem, "after_delete")
def _sai_after_delete(mapper, connection, target: StockAdjustmentItem):
    if target.warehouse_id:
        _apply_stock_delta(connection, target.product_id, target.warehouse_id, +int(target.quantity or 0))
    if target.adjustment_id:
        _recompute_stock_adjustment_total(connection, int(target.adjustment_id))


@event.listens_for(StockAdjustmentItem, "after_update")
def _sai_after_update(mapper, connection, target: StockAdjustmentItem):
    from sqlalchemy.orm.attributes import get_history
    pid_hist = get_history(target, "product_id")
    wid_hist = get_history(target, "warehouse_id")
    qty_hist = get_history(target, "quantity")

    old_pid = (pid_hist.deleted[0] if pid_hist.deleted else target.product_id)
    old_wid = (wid_hist.deleted[0] if wid_hist.deleted else target.warehouse_id)
    old_qty = (qty_hist.deleted[0] if qty_hist.deleted else target.quantity)

    new_pid = target.product_id
    new_wid = target.warehouse_id
    new_qty = target.quantity

    if old_wid:
        _apply_stock_delta(connection, int(old_pid), int(old_wid), +int(old_qty or 0))
    if new_wid:
        _apply_stock_delta(connection, int(new_pid), int(new_wid), -int(new_qty or 0))

    if target.adjustment_id:
        _recompute_stock_adjustment_total(connection, int(target.adjustment_id))

# ===================== ExpenseType =====================
class ExpenseType(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "expense_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    code = db.Column(db.String(50), unique=True, index=True)
    fields_meta = db.Column(db.JSON)

    expenses = relationship("Expense", back_populates="type", order_by="Expense.id")

    __table_args__ = ()

    @validates("name")
    def _v_name(self, _, v):
        s = (v or "").strip()
        if not s:
            raise ValueError("name is required")
        return s.title()

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "is_active": self.is_active, "code": self.code, "fields_meta": self.fields_meta}

    def __repr__(self):
        return f"<ExpenseType {self.name}>"


class Expense(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    
    # حقول سعر الصرف
    fx_rate_used = db.Column(db.Numeric(10, 6))
    fx_rate_source = db.Column(db.String(20))
    fx_rate_timestamp = db.Column(db.DateTime)
    fx_base_currency = db.Column(db.String(10))
    fx_quote_currency = db.Column(db.String(10))

    type_id = db.Column(db.Integer, db.ForeignKey("expense_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="SET NULL"), index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id", ondelete="SET NULL"), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), index=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id", ondelete="SET NULL"), index=True)
    utility_account_id = db.Column(db.Integer, db.ForeignKey("utility_accounts.id", ondelete="SET NULL"), index=True)
    stock_adjustment_id = db.Column(db.Integer, db.ForeignKey("stock_adjustments.id", ondelete="SET NULL"), index=True)

    payee_type = db.Column(db.String(20), nullable=False, default="OTHER", index=True)
    payee_entity_id = db.Column(db.Integer, index=True)
    payee_name = db.Column(db.String(200), index=True)

    beneficiary_name = db.Column(db.String(200))
    paid_to = db.Column(db.String(200), index=True)
    disbursed_by = db.Column(db.String(200))

    period_start = db.Column(db.Date, index=True)
    period_end = db.Column(db.Date, index=True)

    payment_method = db.Column(db.String(20), nullable=False, default="cash")
    payment_details = db.Column(db.Text)

    description = db.Column(db.String(200))
    notes = db.Column(db.Text)
    tax_invoice_number = db.Column(db.String(100), index=True)

    check_number = db.Column(db.String(100))
    check_bank = db.Column(db.String(100))
    check_due_date = db.Column(db.Date)
    check_payee = db.Column(db.String(200))

    bank_transfer_ref = db.Column(db.String(100))
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(100))
    account_holder = db.Column(db.String(200))

    card_number = db.Column(db.String(8))
    card_holder = db.Column(db.String(120))
    card_expiry = db.Column(db.String(10))

    online_gateway = db.Column(db.String(50))
    online_ref = db.Column(db.String(100))
    
    telecom_phone_number = db.Column(db.String(30))
    telecom_service_type = db.Column(db.String(20))
    insurance_company_name = db.Column(db.String(200))
    insurance_company_address = db.Column(db.String(200))
    insurance_company_phone = db.Column(db.String(30))
    marketing_company_name = db.Column(db.String(200))
    marketing_company_address = db.Column(db.String(200))
    marketing_coverage_details = db.Column(db.String(200))
    bank_fee_bank_name = db.Column(db.String(200))
    bank_fee_notes = db.Column(db.Text)
    gov_fee_entity_name = db.Column(db.String(200))
    gov_fee_entity_address = db.Column(db.String(200))
    gov_fee_notes = db.Column(db.Text)
    port_fee_port_name = db.Column(db.String(200))
    port_fee_notes = db.Column(db.Text)
    travel_destination = db.Column(db.String(200))
    travel_reason = db.Column(db.String(200))
    travel_notes = db.Column(db.Text)
    shipping_company_name = db.Column(db.String(200))
    shipping_notes = db.Column(db.Text)
    maintenance_provider_name = db.Column(db.String(200))
    maintenance_provider_address = db.Column(db.String(200))
    maintenance_notes = db.Column(db.Text)
    rent_property_address = db.Column(db.String(200))
    rent_property_notes = db.Column(db.Text)
    tech_provider_name = db.Column(db.String(200))
    tech_provider_phone = db.Column(db.String(30))
    tech_provider_address = db.Column(db.String(200))
    tech_subscription_id = db.Column(db.String(100))
    storage_property_address = db.Column(db.String(200))
    storage_expected_days = db.Column(db.Integer)
    storage_start_date = db.Column(db.Date)
    storage_notes = db.Column(db.Text)
    customs_arrival_date = db.Column(db.Date)
    customs_departure_date = db.Column(db.Date)
    customs_origin = db.Column(db.String(200))
    customs_port_name = db.Column(db.String(200))
    customs_notes = db.Column(db.Text)
    training_company_name = db.Column(db.String(200))
    training_location = db.Column(db.String(200))
    training_duration_days = db.Column(db.Integer)
    training_participants_count = db.Column(db.Integer)
    training_notes = db.Column(db.Text)
    training_participants_names = db.Column(db.Text)
    training_topics = db.Column(db.Text)
    entertainment_duration_days = db.Column(db.Integer)
    entertainment_notes = db.Column(db.Text)
    bank_fee_reference = db.Column(db.String(100))
    bank_fee_contact_name = db.Column(db.String(200))
    bank_fee_contact_phone = db.Column(db.String(30))
    gov_fee_reference = db.Column(db.String(100))
    port_fee_reference = db.Column(db.String(100))
    port_fee_agent_name = db.Column(db.String(200))
    port_fee_agent_phone = db.Column(db.String(30))
    salary_notes = db.Column(db.Text)
    salary_reference = db.Column(db.String(100))
    travel_duration_days = db.Column(db.Integer)
    travel_start_date = db.Column(db.Date)
    travel_companions = db.Column(db.Text)
    travel_cost_center = db.Column(db.String(100))
    employee_advance_period = db.Column(db.String(100))
    employee_advance_reason = db.Column(db.String(200))
    employee_advance_notes = db.Column(db.Text)
    shipping_date = db.Column(db.Date)
    shipping_reference = db.Column(db.String(100))
    shipping_mode = db.Column(db.String(50))
    shipping_tracking_number = db.Column(db.String(100))
    maintenance_details = db.Column(db.Text)
    maintenance_completion_date = db.Column(db.Date)
    maintenance_technician_name = db.Column(db.String(200))
    import_tax_reference = db.Column(db.String(100))
    import_tax_notes = db.Column(db.Text)
    hospitality_type = db.Column(db.String(20))
    hospitality_notes = db.Column(db.Text)
    hospitality_attendees = db.Column(db.Text)
    hospitality_location = db.Column(db.String(200))
    telecom_notes = db.Column(db.Text)
    office_supplier_name = db.Column(db.String(200))
    office_notes = db.Column(db.Text)
    office_items_list = db.Column(db.Text)
    office_purchase_reference = db.Column(db.String(100))
    home_relation_to_company = db.Column(db.String(100))
    home_address = db.Column(db.String(200))
    home_owner_name = db.Column(db.String(200))
    home_notes = db.Column(db.Text)
    home_cost_share = db.Column(db.Numeric(12, 2))
    partner_expense_reason = db.Column(db.String(200))
    partner_expense_notes = db.Column(db.Text)
    partner_expense_reference = db.Column(db.String(100))
    supplier_expense_reason = db.Column(db.String(200))
    supplier_expense_notes = db.Column(db.Text)
    supplier_expense_reference = db.Column(db.String(100))
    handling_notes = db.Column(db.Text)
    handling_quantity = db.Column(db.Numeric(12, 2))
    handling_unit = db.Column(db.String(50))
    handling_reference = db.Column(db.String(100))
    fuel_vehicle_number = db.Column(db.String(50))
    fuel_driver_name = db.Column(db.String(100))
    fuel_usage_type = db.Column(db.String(20))
    fuel_volume = db.Column(db.Numeric(12, 3))
    fuel_notes = db.Column(db.Text)
    fuel_station_name = db.Column(db.String(200))
    fuel_odometer_start = db.Column(db.Integer)
    fuel_odometer_end = db.Column(db.Integer)
    transport_beneficiary_name = db.Column(db.String(200))
    transport_reason = db.Column(db.String(200))
    transport_usage_type = db.Column(db.String(20))
    transport_notes = db.Column(db.Text)
    transport_route_details = db.Column(db.Text)
    insurance_policy_number = db.Column(db.String(100))
    insurance_notes = db.Column(db.Text)
    legal_company_name = db.Column(db.String(200))
    legal_company_address = db.Column(db.String(200))
    legal_case_notes = db.Column(db.Text)
    legal_case_number = db.Column(db.String(100))
    legal_case_type = db.Column(db.String(100))
    
    # حقول الأرشيف
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, index=True)
    archived_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    archive_reason = db.Column(db.String(200))
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"), index=True)

    employee = relationship("Employee", back_populates="expenses")
    customer = relationship("Customer", back_populates="expenses")
    cost_center = relationship("CostCenter", backref=db.backref("expenses", lazy="dynamic"))
    branch = relationship('Branch', back_populates='expenses')
    site = relationship('Site', back_populates='expenses')
    type = relationship("ExpenseType", back_populates="expenses")
    warehouse = relationship("Warehouse", back_populates="expenses")
    partner = relationship("Partner", back_populates="expenses")
    supplier = relationship("Supplier", back_populates="expenses")
    shipment = relationship("Shipment", back_populates="expenses")
    utility_account = relationship("UtilityAccount", back_populates="expenses")
    stock_adjustment = relationship("StockAdjustment", back_populates="expense")
    archived_by_user = relationship("User", foreign_keys=[archived_by])
    payments = relationship("Payment", back_populates="expense", cascade="all, delete-orphan", passive_deletes=True, order_by="Payment.id")

    gl_batches = relationship(
        "GLBatch",
        primaryjoin="and_(foreign(GLBatch.source_id)==Expense.id, GLBatch.source_type=='EXPENSE')",
        viewonly=True,
        order_by="GLBatch.id",
    )

    __table_args__ = (
        db.CheckConstraint("amount >= 0", name="chk_expense_amount_non_negative"),
        db.CheckConstraint("payment_method IN ('cash','cheque','bank','card','online','other')", name="chk_expense_payment_method_allowed"),
        CheckConstraint("payee_type IN ('EMPLOYEE','SUPPLIER','CUSTOMER','PARTNER','WAREHOUSE','SHIPMENT','UTILITY','OTHER')", name="ck_expense_payee_type_allowed"),
        db.UniqueConstraint("stock_adjustment_id", name="uq_expenses_stock_adjustment_id"),
        db.Index("ix_expense_type_date", "type_id", "date"),
        db.Index("ix_expense_partner_date", "partner_id", "date"),
        db.Index("ix_expense_supplier_date", "supplier_id", "date"),
        db.Index("ix_expense_shipment_date", "shipment_id", "date"),
        db.Index("ix_expense_customer_date", "customer_id", "date"),
        db.Index("ix_expense_payee_type_entity_date", "payee_type", "payee_entity_id", "date"),
        db.Index("ix_expense_amount", "amount"),
    )

    @validates("amount")
    def _v_amount(self, _, v):
        if v is None:
            raise ValueError("amount is required")
        if isinstance(v, str):
            v = v.replace("$", "").replace(",", "").strip()
        d = Decimal(str(v))
        if d < 0:
            raise ValueError("amount must be >= 0")
        return q(d)

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("payment_method")
    def _v_payment_method(self, _, v):
        allowed = {"cash", "cheque", "bank", "card", "online", "other"}
        val = (v or "cash").lower()
        if val not in allowed:
            raise ValueError(f"Invalid payment_method: {v}")
        return val

    @validates(
        "beneficiary_name",
        "paid_to",
        "payee_name",
        "check_number",
        "check_bank",
        "check_payee",
        "bank_transfer_ref",
        "bank_name",
        "account_number",
        "account_holder",
        "card_number",
        "card_holder",
        "card_expiry",
        "online_gateway",
        "online_ref",
        "telecom_phone_number",
        "telecom_service_type",
        "insurance_company_name",
        "insurance_company_address",
        "insurance_company_phone",
        "marketing_company_name",
        "marketing_company_address",
        "marketing_coverage_details",
        "bank_fee_bank_name",
        "bank_fee_notes",
        "gov_fee_entity_name",
        "gov_fee_entity_address",
        "gov_fee_notes",
        "port_fee_port_name",
        "port_fee_notes",
        "travel_destination",
        "travel_reason",
        "travel_notes",
        "shipping_company_name",
        "shipping_notes",
        "maintenance_provider_name",
        "maintenance_provider_address",
        "maintenance_notes",
        "rent_property_address",
        "rent_property_notes",
        "tech_provider_name",
        "tech_provider_phone",
        "tech_provider_address",
        "tech_subscription_id",
        "storage_property_address",
        "storage_notes",
        "customs_origin",
        "customs_port_name",
        "customs_notes",
        "training_company_name",
        "training_location",
        "training_notes",
        "training_participants_names",
        "training_topics",
        "entertainment_notes",
        "bank_fee_reference",
        "bank_fee_contact_name",
        "bank_fee_contact_phone",
        "gov_fee_reference",
        "port_fee_reference",
        "port_fee_agent_name",
        "port_fee_agent_phone",
        "salary_notes",
        "salary_reference",
        "travel_companions",
        "travel_cost_center",
        "employee_advance_period",
        "employee_advance_reason",
        "employee_advance_notes",
        "shipping_reference",
        "shipping_mode",
        "shipping_tracking_number",
        "maintenance_details",
        "tax_invoice_number",
        "description",
        "payment_details",
        "notes",
        "import_tax_reference",
        "import_tax_notes",
        "hospitality_type",
        "hospitality_notes",
        "hospitality_attendees",
        "hospitality_location",
        "telecom_notes",
        "office_supplier_name",
        "office_notes",
        "office_items_list",
        "office_purchase_reference",
        "home_relation_to_company",
        "home_address",
        "home_owner_name",
        "home_notes",
        "partner_expense_reason",
        "partner_expense_notes",
        "partner_expense_reference",
        "supplier_expense_reason",
        "supplier_expense_notes",
        "supplier_expense_reference",
        "handling_notes",
        "handling_unit",
        "handling_reference",
        "fuel_vehicle_number",
        "fuel_driver_name",
        "fuel_usage_type",
        "fuel_notes",
        "fuel_station_name",
        "transport_beneficiary_name",
        "transport_reason",
        "transport_usage_type",
        "transport_notes",
        "transport_route_details",
        "insurance_policy_number",
        "insurance_notes",
        "legal_company_name",
        "legal_company_address",
        "legal_case_notes",
        "legal_case_number",
        "legal_case_type",
    )
    def _v_strip(self, _, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @validates("payee_type")
    def _v_payee_type(self, _, v):
        s = (str(v or "OTHER")).strip().upper()
        allowed = {
            "EMPLOYEE",
            "SUPPLIER",
            "UTILITY",
            "CUSTOMER",
            "PARTNER",
            "WAREHOUSE",
            "SHIPMENT",
            "OTHER",
        }
        if s not in allowed:
            raise ValueError("invalid payee_type")
        return s

    @hybrid_property
    def total_paid(self):
        from decimal import Decimal
        payments = db.session.query(Payment).filter(
            Payment.expense_id == self.id,
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.direction == PaymentDirection.OUT.value
        ).all()
        total = Decimal('0.00')
        expense_currency = self.currency or "ILS"
        for p in payments:
            amt = Decimal(str(p.total_amount or 0))
            if p.currency == expense_currency:
                total += amt
            else:
                try:
                    total += convert_amount(amt, p.currency, expense_currency, p.payment_date)
                except Exception:
                    pass
        return float(total)

    @total_paid.expression
    def total_paid(cls):
        return (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.expense_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.OUT.value)
            )
            .scalar_subquery()
        )

    @hybrid_property
    def balance(self):
        return float(q(D(self.amount or 0) - D(self.total_paid or 0)))

    @balance.expression
    def balance(cls):
        paid_subq = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.expense_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.OUT.value)
            )
            .scalar_subquery()
        )
        return cls.amount - paid_subq

    @hybrid_property
    def is_paid(self):
        return self.balance <= 0

    @is_paid.expression
    def is_paid(cls):
        paid_subq = (
            select(func.coalesce(func.sum(Payment.total_amount), 0))
            .where(
                (Payment.expense_id == cls.id)
                & (Payment.status == PaymentStatus.COMPLETED.value)
                & (Payment.direction == PaymentDirection.OUT.value)
            )
            .scalar_subquery()
        )
        balance_expr = cls.amount - paid_subq
        return balance_expr <= 0

    def to_dict(self):
        def _iso(v):
            return v.isoformat() if v else None
        def _num(v):
            return float(v) if v is not None else None
        return {
            "id": self.id,
            "created_at": _iso(getattr(self, "created_at", None)),
            "updated_at": _iso(getattr(self, "updated_at", None)),
            "date": _iso(self.date),
            "amount": float(self.amount or 0),
            "currency": self.currency,
            "fx_rate_used": _num(self.fx_rate_used),
            "fx_rate_source": self.fx_rate_source,
            "fx_rate_timestamp": _iso(self.fx_rate_timestamp),
            "fx_base_currency": self.fx_base_currency,
            "fx_quote_currency": self.fx_quote_currency,
            "type_id": self.type_id,
            "branch_id": self.branch_id,
            "site_id": self.site_id,
            "employee_id": self.employee_id,
            "customer_id": self.customer_id,
            "warehouse_id": self.warehouse_id,
            "partner_id": self.partner_id,
            "supplier_id": self.supplier_id,
            "shipment_id": self.shipment_id,
            "utility_account_id": self.utility_account_id,
            "stock_adjustment_id": self.stock_adjustment_id,
            "cost_center_id": self.cost_center_id,
            "payee_type": self.payee_type,
            "payee_entity_id": self.payee_entity_id,
            "payee_name": self.payee_name,
            "beneficiary_name": self.beneficiary_name,
            "paid_to": self.paid_to,
            "disbursed_by": self.disbursed_by,
            "period_start": _iso(self.period_start),
            "period_end": _iso(self.period_end),
            "payment_method": self.payment_method,
            "payment_details": self.payment_details,
            "description": self.description,
            "notes": self.notes,
            "tax_invoice_number": self.tax_invoice_number,
            "check_number": self.check_number,
            "check_bank": self.check_bank,
            "check_due_date": _iso(self.check_due_date),
            "check_payee": self.check_payee,
            "bank_transfer_ref": self.bank_transfer_ref,
            "bank_name": self.bank_name,
            "account_number": self.account_number,
            "account_holder": self.account_holder,
            "card_number": self.card_number,
            "card_holder": self.card_holder,
            "card_expiry": self.card_expiry,
            "online_gateway": self.online_gateway,
            "online_ref": self.online_ref,
            "telecom_phone_number": self.telecom_phone_number,
            "telecom_service_type": self.telecom_service_type,
            "telecom_notes": self.telecom_notes,
            "insurance_company_name": self.insurance_company_name,
            "insurance_company_address": self.insurance_company_address,
            "insurance_company_phone": self.insurance_company_phone,
            "insurance_policy_number": self.insurance_policy_number,
            "insurance_notes": self.insurance_notes,
            "marketing_company_name": self.marketing_company_name,
            "marketing_company_address": self.marketing_company_address,
            "marketing_coverage_details": self.marketing_coverage_details,
            "bank_fee_bank_name": self.bank_fee_bank_name,
            "bank_fee_notes": self.bank_fee_notes,
            "bank_fee_reference": self.bank_fee_reference,
            "bank_fee_contact_name": self.bank_fee_contact_name,
            "bank_fee_contact_phone": self.bank_fee_contact_phone,
            "gov_fee_entity_name": self.gov_fee_entity_name,
            "gov_fee_entity_address": self.gov_fee_entity_address,
            "gov_fee_notes": self.gov_fee_notes,
            "gov_fee_reference": self.gov_fee_reference,
            "port_fee_port_name": self.port_fee_port_name,
            "port_fee_notes": self.port_fee_notes,
            "port_fee_reference": self.port_fee_reference,
            "port_fee_agent_name": self.port_fee_agent_name,
            "port_fee_agent_phone": self.port_fee_agent_phone,
            "travel_destination": self.travel_destination,
            "travel_reason": self.travel_reason,
            "travel_notes": self.travel_notes,
            "travel_duration_days": self.travel_duration_days,
            "travel_start_date": _iso(self.travel_start_date),
            "travel_companions": self.travel_companions,
            "travel_cost_center": self.travel_cost_center,
            "shipping_company_name": self.shipping_company_name,
            "shipping_notes": self.shipping_notes,
            "shipping_date": _iso(self.shipping_date),
            "shipping_reference": self.shipping_reference,
            "shipping_mode": self.shipping_mode,
            "shipping_tracking_number": self.shipping_tracking_number,
            "maintenance_provider_name": self.maintenance_provider_name,
            "maintenance_provider_address": self.maintenance_provider_address,
            "maintenance_notes": self.maintenance_notes,
            "maintenance_details": self.maintenance_details,
            "maintenance_completion_date": _iso(self.maintenance_completion_date),
            "maintenance_technician_name": self.maintenance_technician_name,
            "rent_property_address": self.rent_property_address,
            "rent_property_notes": self.rent_property_notes,
            "tech_provider_name": self.tech_provider_name,
            "tech_provider_phone": self.tech_provider_phone,
            "tech_provider_address": self.tech_provider_address,
            "tech_subscription_id": self.tech_subscription_id,
            "storage_property_address": self.storage_property_address,
            "storage_expected_days": self.storage_expected_days,
            "storage_start_date": _iso(self.storage_start_date),
            "storage_notes": self.storage_notes,
            "customs_arrival_date": _iso(self.customs_arrival_date),
            "customs_departure_date": _iso(self.customs_departure_date),
            "customs_origin": self.customs_origin,
            "customs_port_name": self.customs_port_name,
            "customs_notes": self.customs_notes,
            "training_company_name": self.training_company_name,
            "training_location": self.training_location,
            "training_duration_days": self.training_duration_days,
            "training_participants_count": self.training_participants_count,
            "training_notes": self.training_notes,
            "training_participants_names": self.training_participants_names,
            "training_topics": self.training_topics,
            "entertainment_duration_days": self.entertainment_duration_days,
            "entertainment_notes": self.entertainment_notes,
            "salary_notes": self.salary_notes,
            "salary_reference": self.salary_reference,
            "employee_advance_period": self.employee_advance_period,
            "employee_advance_reason": self.employee_advance_reason,
            "employee_advance_notes": self.employee_advance_notes,
            "hospitality_type": self.hospitality_type,
            "hospitality_notes": self.hospitality_notes,
            "hospitality_attendees": self.hospitality_attendees,
            "hospitality_location": self.hospitality_location,
            "office_supplier_name": self.office_supplier_name,
            "office_notes": self.office_notes,
            "office_items_list": self.office_items_list,
            "office_purchase_reference": self.office_purchase_reference,
            "home_relation_to_company": self.home_relation_to_company,
            "home_address": self.home_address,
            "home_owner_name": self.home_owner_name,
            "home_notes": self.home_notes,
            "home_cost_share": _num(self.home_cost_share),
            "partner_expense_reason": self.partner_expense_reason,
            "partner_expense_notes": self.partner_expense_notes,
            "partner_expense_reference": self.partner_expense_reference,
            "supplier_expense_reason": self.supplier_expense_reason,
            "supplier_expense_notes": self.supplier_expense_notes,
            "supplier_expense_reference": self.supplier_expense_reference,
            "handling_notes": self.handling_notes,
            "handling_quantity": _num(self.handling_quantity),
            "handling_unit": self.handling_unit,
            "handling_reference": self.handling_reference,
            "fuel_vehicle_number": self.fuel_vehicle_number,
            "fuel_driver_name": self.fuel_driver_name,
            "fuel_usage_type": self.fuel_usage_type,
            "fuel_volume": _num(self.fuel_volume),
            "fuel_notes": self.fuel_notes,
            "fuel_station_name": self.fuel_station_name,
            "fuel_odometer_start": self.fuel_odometer_start,
            "fuel_odometer_end": self.fuel_odometer_end,
            "transport_beneficiary_name": self.transport_beneficiary_name,
            "transport_reason": self.transport_reason,
            "transport_usage_type": self.transport_usage_type,
            "transport_notes": self.transport_notes,
            "transport_route_details": self.transport_route_details,
            "import_tax_reference": self.import_tax_reference,
            "import_tax_notes": self.import_tax_notes,
            "legal_company_name": self.legal_company_name,
            "legal_company_address": self.legal_company_address,
            "legal_case_notes": self.legal_case_notes,
            "legal_case_number": self.legal_case_number,
            "legal_case_type": self.legal_case_type,
            "total_paid": _num(self.total_paid),
            "balance": _num(self.balance),
            "is_paid": self.is_paid,
            "is_archived": self.is_archived,
            "archived_at": _iso(self.archived_at),
            "archived_by": self.archived_by,
            "archive_reason": self.archive_reason,
        }


@event.listens_for(Expense, "before_insert")
def _expense_normalize_insert(mapper, connection, target: "Expense"):
    target.payment_method = (target.payment_method or "cash").lower()
    target.currency = (target.currency or DEFAULT_CURRENCY).upper()
    
    # حفظ سعر الصرف تلقائياً للنفقات (فقط عند الإنشاء)
    expense_currency = target.currency
    default_currency = "ILS"
    
    if expense_currency != default_currency:
        try:
            at = getattr(target, "date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, expense_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = expense_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass
    
    target.payee_type = (target.payee_type or "OTHER").upper()
    if not target.paid_to:
        target.paid_to = (target.payee_name or None)
    _expense_require_entity(target)


@event.listens_for(Expense, "before_update")
def _expense_normalize_update(mapper, connection, target: "Expense"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.payment_method = (target.payment_method or "cash").lower()
    target.currency = (target.currency or "ILS").upper()
    target.payee_type = (target.payee_type or "OTHER").upper()
    if not target.paid_to:
        target.paid_to = (target.payee_name or None)


def _expense_require_entity(target: "Expense") -> None:
    if getattr(target, "customer_id", None):
        target.payee_type = "CUSTOMER"
        target.payee_entity_id = int(target.customer_id)
        return
    if getattr(target, "supplier_id", None):
        target.payee_type = "SUPPLIER"
        target.payee_entity_id = int(target.supplier_id)
        return
    if getattr(target, "partner_id", None):
        target.payee_type = "PARTNER"
        target.payee_entity_id = int(target.partner_id)
        return
    if getattr(target, "employee_id", None):
        target.payee_type = "EMPLOYEE"
        target.payee_entity_id = int(target.employee_id)
        return
    payee_type = (getattr(target, "payee_type", "") or "").strip().upper()
    payee_entity_id = getattr(target, "payee_entity_id", None)
    if payee_type in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"} and payee_entity_id:
        return
    raise ValueError("expense.entity_required")


def _ensure_account_exists(connection, account_code: str) -> bool:
    """التحقق من وجود الحساب وإنشاؤه إذا كان مفقوداً"""
    try:
        existing = connection.execute(
            select(Account.id).where(Account.code == account_code)
        ).scalar_one_or_none()
        if existing:
            return True
        
        account_name_map = {
            "1000_CASH": "الصندوق",
            "1010_BANK": "البنك",
            "1020_CARD_CLEARING": "البطاقات",
            "1100_AR": "ذمم العملاء",
            "1150_CHQ_REC": "شيكات تحت التحصيل",
            "1205_INV_EXCHANGE": "مخزون توريد تبادل",
            "1300_INVENTORY": "المخزون",
            "1300_INV_RSV": "احتياطي مخزون",
            "1599_ACC_DEP": "مخصص إهلاك متراكم",
            "2000_AP": "ذمم الموردين والخصوم",
            "2100_VAT_PAYABLE": "ضريبة القيمة المضافة",
            "2200_INCOME_TAX_PAYABLE": "ضريبة الدخل المستحقة",
            "2200_PARTNER_CLEARING": "تسوية الشركاء",
            "2150_CHQ_PAY": "شيكات تحت الدفع",
            "2150_PAYROLL_CLR": "قيد الرواتب",
            "2300_ADV_PAY": "إيرادات مقدمة",
            "3000_EQUITY": "حقوق الملكية",
            "3100_OWNER_CURRENT": "حساب المالك الجاري",
            "3200_CURRENT_EARNINGS": "أرباح محتجزة جارية",
            "4000_SALES": "المبيعات",
            "4050_SALES_DISCOUNT": "خصم المبيعات",
            "4100_SERVICE_REVENUE": "إيراد الخدمات",
            "4200_SHIPPING_INCOME": "إيراد الشحن",
            "5000_EXPENSES": "مصروفات",
            "5100_COGS": "تكلفة البضاعة المباعة",
            "5100_PURCHASES": "المشتريات",
            "5100_SUPPLIER_EXPENSES": "مصروفات موردين",
            "5100_SUPPLIER_EXPENS": "مصروفات موردين",
            "5105_COGS_EXCHANGE": "تكلفة توريد تبادل",
            "6100_SALARIES": "الرواتب",
            "6500_FUEL": "وقود",
            "6600_OFFICE": "مستلزمات مكتب",
            "6200_INCOME_TAX_EXPENSE": "ضريبة الدخل (مصروف)",
            "6800_DEPRECIATION": "إهلاك",
            "6960_HOME_EXPENSE": "مصروفات منزلية",
        }
        type_by_prefix = (
            ("1", "ASSET"),
            ("2", "LIABILITY"),
            ("3", "EQUITY"),
            ("4", "REVENUE"),
            ("5", "EXPENSE"),
            ("6", "EXPENSE"),
        )
        account_name = account_name_map.get(account_code, account_code.replace("_", " ").title())
        account_type = None
        for prefix, at in type_by_prefix:
            if account_code.startswith(prefix):
                account_type = at
                break
        if not account_type:
            account_type = "ASSET"
        
        connection.execute(
            sa_text("""
                INSERT INTO accounts (code, name, type, is_active, created_at, updated_at)
                VALUES (:code, :name, :type, :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"code": account_code, "name": account_name, "type": account_type, "is_active": True}
        )
        return True
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"❌ فشل إنشاء حساب محاسبي: {account_code} - {e}")
        raise


@event.listens_for(Expense, "after_insert")
@event.listens_for(Expense, "after_update")
def _expense_gl_batch_upsert(mapper, connection, target: "Expense"):
    """معطّل: القيد المحاسبي لا يُنفّذ أثناء الحفظ حتى لا يفشل حفظ المصروف."""
    return


@event.listens_for(Expense, "before_delete")
def _expense_gl_batch_reverse(mapper, connection, target: "Expense"):
    """معطّل: القيد العكسي يُنفّذ من المسار بعد الحذف في معاملة منفصلة (run_expense_gl_reversal_after_delete)."""
    return


def _expense_entity_pair_from_row(row) -> tuple[str | None, int | None]:
    """استخراج (entity_type, entity_id) من صف مصروف (dict أو Row)."""
    def _g(k, default=None):
        return row.get(k, default) if hasattr(row, "get") else getattr(row, k, default)
    if _g("customer_id"):
        return ("CUSTOMER", int(_g("customer_id")))
    if _g("supplier_id"):
        return ("SUPPLIER", int(_g("supplier_id")))
    if _g("partner_id"):
        return ("PARTNER", int(_g("partner_id")))
    if _g("employee_id"):
        return ("EMPLOYEE", int(_g("employee_id")))
    payee_type = (str(_g("payee_type") or "").strip().upper())
    payee_entity_id = _g("payee_entity_id")
    if payee_type in {"SUPPLIER", "PARTNER", "CUSTOMER", "EMPLOYEE"} and payee_entity_id:
        try:
            return (payee_type, int(payee_entity_id))
        except (TypeError, ValueError):
            return (payee_type, None)
    return (None, None)


def run_expense_gl_sync_after_commit(expense_id: int) -> bool:
    """
    إنشاء/تحديث قيد دفتر الأستاذ (ACCRUAL) للمصروف في معاملة منفصلة بعد حفظ المصروف.
    يُرجع True إذا تم إنشاء/تحديث القيد، False عند التخطي أو الفشل. لا يُلقي استثناءات.
    """
    if not expense_id:
        return False
    try:
        from extensions import db
        row = None
        with db.engine.connect() as conn_read:
            with conn_read.begin():
                row = conn_read.execute(
                    select(
                        Expense.id,
                        Expense.type_id,
                        Expense.amount,
                        Expense.currency,
                        Expense.supplier_id,
                        Expense.partner_id,
                        Expense.customer_id,
                        Expense.employee_id,
                        Expense.payee_type,
                        Expense.payee_entity_id,
                    ).where(Expense.id == expense_id)
                ).mappings().first()
        if not row:
            if current_app:
                current_app.logger.debug("Expense GL sync: مصروف غير موجود id=%s", expense_id)
            return False
        row = dict(row)
        type_id = row.get("type_id")
        amount = float(row.get("amount") or 0)
        if amount <= 0:
            if current_app:
                current_app.logger.debug("Expense GL sync: تخطي مبلغ غير موجب expense_id=%s amount=%s", expense_id, amount)
            return False
        currency = (str(row.get("currency") or "ILS").strip().upper() or "ILS")
        ledger = {"expense_account": "5000_EXPENSES", "counterparty_account": "2000_AP"}
        conn = db.engine.connect()
        try:
            conn.rollback()
            try:
                with conn.begin():
                    ledger = _expense_type_ledger_settings(conn, type_id)
            except Exception:
                conn.rollback()
            conn.rollback()
            expense_account = (ledger.get("expense_account") or "5000_EXPENSES").strip().upper()
            counterparty_account = (ledger.get("counterparty_account") or "2000_AP").strip().upper()
            entity_type, entity_id = _expense_entity_pair_from_row(row)
            if entity_type == "CUSTOMER":
                ar_account = (GL_ACCOUNTS.get("AR") or "1100_AR").strip().upper()
                entries = [
                    (ar_account, amount, 0),
                    (expense_account, 0, amount),
                ]
            else:
                entries = [
                    (expense_account, amount, 0),
                    (counterparty_account, 0, amount),
                ]
            memo = f"Expense #{expense_id}"
            ref = f"EXP-{expense_id}"
            with conn.begin():
                # استبدال قيد المصروف الحالي (عند التعديل) ليبقى دفتر الأستاذ يعكس البيانات الحالية
                conn.execute(
                    sa_text("""
                        DELETE FROM gl_batches
                        WHERE source_type = 'EXPENSE' AND source_id = :eid AND purpose = 'ACCRUAL'
                    """),
                    {"eid": expense_id}
                )
                batch_id = _gl_upsert_batch_and_entries(
                    conn,
                    source_type="EXPENSE",
                    source_id=expense_id,
                    purpose="ACCRUAL",
                    currency=currency,
                    memo=memo,
                    entries=entries,
                    ref=ref,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
        finally:
            conn.close()
        if current_app:
            current_app.logger.info("تم إنشاء/تحديث قيد دفتر الأستاذ للمصروف expense_id=%s batch_id=%s", expense_id, batch_id)
        return True
    except Exception as e:
        if current_app:
            current_app.logger.warning("Expense GL sync failed for expense_id=%s: %s", expense_id, e, exc_info=True)
        return False


def run_expense_gl_reversal_after_delete(snapshot: dict) -> None:
    """
    تسجيل قيد عكسي (EXPENSE_REVERSAL) بعد حذف المصروف، في معاملة منفصلة.
    snapshot يجب أن يحتوي: expense_id, amount, currency, expense_account, counterparty_account, entity_type, entity_id, payee_name (اختياري).
    لا يُلقي استثناءات.
    """
    if not snapshot or not snapshot.get("expense_id"):
        return
    try:
        from extensions import db
        expense_id = int(snapshot["expense_id"])
        amount = float(snapshot.get("amount") or 0)
        if amount <= 0:
            return
        currency = str(snapshot.get("currency") or "ILS").strip().upper() or "ILS"
        expense_account = str(snapshot.get("expense_account") or "5000_EXPENSES").strip().upper()
        counterparty_account = str(snapshot.get("counterparty_account") or "2000_AP").strip().upper()
        entity_type = snapshot.get("entity_type")
        entity_id = snapshot.get("entity_id")
        try:
            entity_id = int(entity_id) if entity_id is not None else None
        except (TypeError, ValueError):
            entity_id = None
        payee_name = snapshot.get("payee_name") or ""
        memo = f"Reversal - deleted expense #{expense_id}" + (f" - {payee_name}" if payee_name else "")
        ref = f"EXP-REV-{expense_id}"
        entries = [
            (expense_account, 0, amount),
            (counterparty_account, amount, 0),
        ]
        with db.engine.connect() as conn:
            with conn.begin():
                _gl_upsert_batch_and_entries(
                    conn,
                    source_type="EXPENSE_REVERSAL",
                    source_id=expense_id,
                    purpose="REVERSAL",
                    currency=currency,
                    memo=memo,
                    entries=entries,
                    ref=ref,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
    except Exception as e:
        if current_app:
            current_app.logger.warning("Expense GL reversal failed for expense_id=%s: %s", snapshot.get("expense_id"), e, exc_info=True)


def build_expense_reversal_snapshot(expense: "Expense") -> dict:
    """بناء لقطة بيانات المصروف لاستخدامها في قيد العكس بعد الحذف."""
    try:
        from extensions import db
        with db.engine.connect() as conn:
            with conn.begin():
                ledger = _expense_type_ledger_settings(conn, getattr(expense, "type_id", None))
        entity_type, entity_id = _expense_entity_pair(expense)
        return {
            "expense_id": getattr(expense, "id", None),
            "amount": float(getattr(expense, "amount", 0) or 0),
            "currency": (getattr(expense, "currency", None) or "ILS"),
            "expense_account": (ledger.get("expense_account") or "5000_EXPENSES").strip().upper(),
            "counterparty_account": (ledger.get("counterparty_account") or "2000_AP").strip().upper(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payee_name": (getattr(expense, "payee_name", None) or getattr(expense, "paid_to", None) or ""),
        }
    except Exception:
        # عند الفشل نُرجع الحد الأدنى لإنشاء قيد عكس بحسابات افتراضية حتى لا يبقى قيد بدون عكس
        return {
            "expense_id": getattr(expense, "id", None),
            "amount": float(getattr(expense, "amount", 0) or 0),
            "currency": (getattr(expense, "currency", None) or "ILS"),
            "expense_account": "5000_EXPENSES",
            "counterparty_account": "2000_AP",
            "entity_type": None,
            "entity_id": None,
            "payee_name": "",
        }


@event.listens_for(PreOrder, "before_insert")
def _preorder_normalize_insert(mapper, connection, target: "PreOrder"):
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")
    
    preorder_currency = target.currency
    default_currency = "ILS"
    
    if preorder_currency != default_currency:
        try:
            at = getattr(target, "preorder_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, preorder_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = preorder_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(PreOrder, "before_update")
def _preorder_normalize_update(mapper, connection, target: "PreOrder"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")


@event.listens_for(Sale, "before_insert")
def _sale_normalize_insert(mapper, connection, target: "Sale"):
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")
    
    sale_currency = target.currency
    default_currency = "ILS"
    
    if sale_currency != default_currency:
        try:
            at = getattr(target, "sale_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, sale_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = sale_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(Sale, "before_update")
def _sale_normalize_update(mapper, connection, target: "Sale"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")


# ===== إنشاء قيود GL تلقائية لمرتجعات المبيعات =====
def _sale_return_gl_upsert_core(connection, target: "SaleReturn") -> None:
    """منطق قيد GL لمرتجع المبيعات (يُستدعى من معاملة منفصلة بعد commit)."""
    if target.status != "CONFIRMED":
        return
    total_refund = float(target.total_amount or 0)
    if total_refund <= 0:
        return
        
    total_refund_dec = Decimal(str(total_refund))

    # 1. Calculate Tax Share
    tax_rate = Decimal("0")
    if target.sale_id:
        try:
            # Use SQL to get tax_rate to avoid ORM loading issues
            res = connection.execute(
                sa_text("SELECT tax_rate FROM sales WHERE id = :sid"), 
                {"sid": target.sale_id}
            ).scalar()
            if res:
                tax_rate = Decimal(str(res))
        except Exception:
            pass

    # Net = Total / (1 + Rate/100)
    if tax_rate > 0:
        net_sales = total_refund_dec / (Decimal("1") + (tax_rate / Decimal("100")))
        net_sales = net_sales.quantize(Decimal("0.01"), ROUND_HALF_UP)
        tax_amount = total_refund_dec - net_sales
    else:
        net_sales = total_refund_dec
        tax_amount = Decimal("0")

    # 2. Calculate Cost of Returned Goods (For Inventory/COGS reversal)
    total_cost = Decimal("0")
    try:
        lines = connection.execute(
            sa_text("""
                SELECT srl.quantity, p.purchase_price, p.cost_after_shipping
                FROM sale_return_lines srl
                JOIN products p ON srl.product_id = p.id
                WHERE srl.sale_return_id = :rid
            """),
            {"rid": target.id}
        ).fetchall()
        
        for ln in lines:
            qty = Decimal(str(ln[0] or 0))
            # Use cost_after_shipping if available (>0), else purchase_price
            c1 = Decimal(str(ln[2] or 0))
            c2 = Decimal(str(ln[1] or 0))
            cost = c1 if c1 > 0 else c2
            total_cost += qty * cost
    except Exception:
        pass

    entries = []
    
    # A. Reversing Revenue & Tax (Debit Sales, Debit Tax, Credit Customer)
    entries.append((GL_ACCOUNTS.get("REV", "4000_SALES"), float(net_sales), 0))
    if tax_amount > 0:
        entries.append((GL_ACCOUNTS.get("TAX_OUT", "2100_VAT_PAYABLE"), float(tax_amount), 0))
    
    entries.append((GL_ACCOUNTS.get("AR", "1100_AR"), 0, float(total_refund_dec)))

    # B. Reversing Cost (Debit Inventory, Credit COGS)
    if total_cost > 0:
        entries.append((GL_ACCOUNTS.get("INVENTORY", "1200_INVENTORY"), float(total_cost), 0))
        entries.append((GL_ACCOUNTS.get("COGS", "5000_COGS"), 0, float(total_cost)))

    _gl_upsert_batch_and_entries(
        connection,
        source_type="SALE_RETURN",
        source_id=target.id,
        purpose="RETURN",
        currency=target.currency or "ILS",
        memo=f"Sale return #{target.id} (Tax: {tax_rate}%)",
        entries=entries,
        ref=f"RET-{target.id}",
        entity_type="CUSTOMER",
        entity_id=target.customer_id,
    )


def run_sale_return_gl_sync_after_commit(sale_return_id: int) -> None:
    """إنشاء/تحديث قيد GL لمرتجع المبيعات في معاملة منفصلة بعد commit. لا يُلقي استثناءات."""
    if not sale_return_id:
        return
    try:
        from extensions import db
        from sqlalchemy.orm import Session
        session = Session(db.engine)
        try:
            sr = session.get(SaleReturn, sale_return_id)
            if not sr:
                return
            _sale_return_gl_upsert_core(session.connection(), sr)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        if current_app:
            current_app.logger.warning("SaleReturn GL sync failed for sale_return_id=%s: %s", sale_return_id, e, exc_info=True)


@event.listens_for(SaleReturn, "after_insert")
@event.listens_for(SaleReturn, "after_update")
def _sale_return_gl_batch_upsert(mapper, connection, target: "SaleReturn"):
    """معطّل: القيد يُنفّذ بعد commit عبر run_sale_return_gl_sync_after_commit."""
    return

@event.listens_for(SaleReturn, "before_insert")
def _sale_return_normalize_insert(mapper, connection, target: "SaleReturn"):
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")
    
    return_currency = target.currency
    default_currency = "ILS"
    
    if return_currency != default_currency:
        try:
            at = getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, return_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = return_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(SaleReturn, "before_update")
def _sale_return_normalize_update(mapper, connection, target: "SaleReturn"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = ensure_currency(getattr(target, "currency", None) or "ILS")


@event.listens_for(Shipment, "before_insert")
def _shipment_normalize_insert(mapper, connection, target: "Shipment"):
    target.currency = ensure_currency(getattr(target, "currency", None) or "USD")
    
    shipment_currency = target.currency
    default_currency = "ILS"
    
    if shipment_currency != default_currency:
        try:
            at = getattr(target, "shipment_date", None) or getattr(target, "date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, shipment_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = shipment_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(Shipment, "before_update")
def _shipment_normalize_update(mapper, connection, target: "Shipment"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = ensure_currency(getattr(target, "currency", None) or "USD")


@event.listens_for(ServiceRequest, "before_insert")
def _service_request_normalize_insert(mapper, connection, target: "ServiceRequest"):
    target.currency = (target.currency or "ILS").upper()
    
    if target.tax_rate is None:
        target.tax_rate = Decimal('0.00')
    
    service_currency = target.currency
    default_currency = "ILS"
    
    if service_currency != default_currency:
        try:
            at = getattr(target, "received_at", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, service_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = service_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(ServiceRequest, "before_update")
def _service_request_normalize_update(mapper, connection, target: "ServiceRequest"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = (target.currency or "ILS").upper()


@event.listens_for(OnlinePreOrder, "before_insert")
def _online_preorder_normalize_insert(mapper, connection, target: "OnlinePreOrder"):
    target.currency = (target.currency or "ILS").upper()
    
    online_currency = target.currency
    default_currency = "ILS"
    
    if online_currency != default_currency:
        try:
            at = getattr(target, "order_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, online_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = online_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(OnlinePreOrder, "before_update")
def _online_preorder_normalize_update(mapper, connection, target: "OnlinePreOrder"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = (target.currency or "ILS").upper()


@event.listens_for(OnlinePayment, "before_insert")
def _online_payment_normalize_insert(mapper, connection, target: "OnlinePayment"):
    target.currency = (target.currency or "ILS").upper()
    
    payment_currency = target.currency
    default_currency = "ILS"
    
    if payment_currency != default_currency:
        try:
            at = getattr(target, "payment_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, payment_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = payment_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(OnlinePayment, "before_update")
def _online_payment_normalize_update(mapper, connection, target: "OnlinePayment"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = (target.currency or "ILS").upper()


@event.listens_for(SupplierSettlement, "before_insert")
def _supplier_settlement_normalize_insert(mapper, connection, target: "SupplierSettlement"):
    target.currency = (target.currency or "ILS").upper()
    
    # حفظ سعر الصرف تلقائياً لتسويات الموردين (فقط عند الإنشاء)
    settlement_currency = target.currency
    default_currency = "ILS"
    
    if settlement_currency != default_currency:
        try:
            at = getattr(target, "from_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, settlement_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = settlement_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(SupplierSettlement, "before_update")
def _supplier_settlement_normalize_update(mapper, connection, target: "SupplierSettlement"):
    # تحديث الحقول فقط، بدون تغيير سعر الصرف
    target.currency = (target.currency or "ILS").upper()


@event.listens_for(PartnerSettlement, "before_insert")
def _partner_settlement_normalize_insert(mapper, connection, target: "PartnerSettlement"):
    target.currency = (target.currency or "ILS").upper()
    
    # حفظ سعر الصرف تلقائياً لتسويات الشركاء (فقط عند الإنشاء)
    settlement_currency = target.currency
    default_currency = "ILS"
    
    if settlement_currency != default_currency:
        try:
            at = getattr(target, "from_date", None) or getattr(target, "created_at", None) or datetime.now(timezone.utc)
            rate = _fx_rate_local_via_connection(connection, settlement_currency, default_currency, at)
            if rate and rate > 0:
                target.fx_rate_used = Decimal(str(rate))
                target.fx_rate_source = "manual"
                target.fx_rate_timestamp = datetime.now(timezone.utc)
                target.fx_base_currency = settlement_currency
                target.fx_quote_currency = default_currency
        except Exception:
            pass


@event.listens_for(PartnerSettlement, "before_update")
def _partner_settlement_normalize_update(mapper, connection, target: "PartnerSettlement"):
    target.currency = (target.currency or "ILS").upper()


# ===================== Audit Log Model =====================
class AuditLog(db.Model, TimestampMixin):
    __tablename__ = "audit_logs"

    id          = db.Column(db.Integer, primary_key=True)
    model_name  = db.Column(db.String(100), nullable=False, index=True)
    record_id   = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='SET NULL'), index=True, nullable=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), index=True, nullable=True)

    action      = db.Column(db.String(20), nullable=False, index=True)
    old_data    = db.Column(db.Text)
    new_data    = db.Column(db.Text)

    ip_address  = db.Column(db.String(45))
    user_agent  = db.Column(db.String(255))

    __table_args__ = ()

    @validates('action')
    def _v_action(self, _, v):
        return (v or '').strip().upper()

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if getattr(self, "created_at", None) else None,
            "model_name": self.model_name,
            "record_id": self.record_id,
            "customer_id": self.customer_id,
            "user_id": self.user_id,
            "action": self.action,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    def __repr__(self):
        return f"<AuditLog {self.model_name}#{self.record_id} {self.action}>"


@event.listens_for(_SA_Session, "before_flush")
def _capture_previous(session, ctx, instances=None):
    for obj in session.dirty:
        try:
            insp = inspect(obj)
        except Exception:
            continue
        prev = getattr(obj, "_previous_state", None)
        if prev is None:
            obj._previous_state = prev = {}
        for attr in insp.mapper.column_attrs:
            hist = insp.attrs[attr.key].history
            if hist.has_changes() and hist.deleted:
                if attr.key not in prev:
                    obj._previous_state[attr.key] = hist.deleted[0]


@event.listens_for(_SA_Session, "after_flush_postexec")
def _audit_after_flush_postexec(session, ctx):
    uid = None
    customer_id = None
    ip = None
    ua = None

    if has_request_context():
        if getattr(current_user, "is_authenticated", False):
            uid = current_user.id
            customer_id = getattr(current_user, "customer_id", None)
        ip = request.remote_addr
        ua = request.headers.get("User-Agent")

    rows = []

    def add_log(action, obj, old_data=None, new_data=None):
        try:
            rows.append(
                {
                    "model_name": obj.__class__.__name__,
                    "record_id": getattr(obj, "id", None),
                    "customer_id": customer_id,
                    "user_id": uid,
                    "action": (action or "").upper(),
                    "old_data": json.dumps(old_data, default=str) if old_data else None,
                    "new_data": json.dumps(new_data, default=str) if new_data else None,
                    "ip_address": ip,
                    "user_agent": ua,
                }
            )
        except Exception:
            pass

    for obj in session.new:
        if isinstance(obj, AuditMixin):
            try:
                curr = {c.key: getattr(obj, c.key, None) for c in inspect(obj).mapper.column_attrs}
            except Exception:
                curr = None
            add_log("CREATE", obj, new_data=curr)

    for obj in session.deleted:
        if isinstance(obj, AuditMixin):
            try:
                prev = {c.key: getattr(obj, c.key, None) for c in inspect(obj).mapper.column_attrs}
            except Exception:
                prev = None
            add_log("DELETE", obj, old_data=prev)

    for obj in session.dirty:
        if not isinstance(obj, AuditMixin):
            continue
        prev = getattr(obj, "_previous_state", None)
        if not prev:
            continue
        try:
            curr = {c.key: getattr(obj, c.key, None) for c in inspect(obj).mapper.column_attrs}
        except Exception:
            curr = None
        add_log("UPDATE", obj, old_data=prev, new_data=curr)

    if rows:
        try:
            session.connection().execute(AuditLog.__table__.insert(), rows)
        except Exception:
            pass

class Note(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    entity_type = db.Column(db.String(50), index=True)
    entity_id = db.Column(db.String(50), index=True)
    is_pinned = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)
    priority = db.Column(sa_str_enum(['LOW', 'MEDIUM', 'HIGH', 'URGENT'], name='note_priority'), default='MEDIUM', nullable=False, index=True)
    
    # حقول جديدة للمستهدفين والإشعارات
    target_type = db.Column(db.String(50), index=True)  # نوع المستهدفين
    target_ids = db.Column(db.Text)  # معرفات المستهدفين مفصولة بفاصلة
    notification_type = db.Column(db.String(50), index=True)  # نوع الإشعار
    notification_date = db.Column(db.DateTime, index=True)  # تاريخ الإشعار
    is_sent = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)  # تم الإرسال

    author = relationship('User', backref='notes')

    __table_args__ = ()

    @validates('content')
    def _v_content(self, _, v):
        v = (v or '').strip()
        if not v:
            raise ValueError("content must not be empty")
        return v

    @validates('entity_type')
    def _v_entity_type(self, _, v):
        s = (v or '').strip().upper()
        return s or None

    @validates('entity_id')
    def _v_entity_id(self, _, v):
        s = (str(v or '')).strip()
        return s or None

    @validates('priority')
    def _v_priority(self, _, v):
        return getattr(v, 'value', (v or '')).strip().upper() or 'MEDIUM'

    @hybrid_property
    def short_preview(self) -> str:
        c = (self.content or '').strip()
        return (c[:97] + '...') if len(c) > 100 else c

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "author_id": self.author_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "is_pinned": bool(self.is_pinned),
            "priority": getattr(self.priority, "value", self.priority),
            "created_at": self.created_at.isoformat() if getattr(self, "created_at", None) else None,
            "updated_at": self.updated_at.isoformat() if getattr(self, "updated_at", None) else None,
        }

    def __repr__(self):
        et = (self.entity_type or '').upper()
        return f"<Note {self.id} {et}#{self.entity_id} pinned={bool(self.is_pinned)}>"


class Account(db.Model, TimestampMixin):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(sa_str_enum(["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"], name="account_type"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = ()

    @validates("code", "name")
    def _v_req_strip(self, _, v):
        s = (v or "").strip()
        if not s:
            raise ValueError("value required")
        return s

    @validates("type")
    def _v_type(self, _, v):
        return getattr(v, "value", v)

    def __repr__(self):
        return f"<Account {self.code} {self.name}>"


class GLBatch(db.Model, TimestampMixin):
    __tablename__ = "gl_batches"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, index=True)
    source_type = db.Column(db.String(30), index=True)
    source_id = db.Column(db.Integer, index=True)
    purpose = db.Column(db.String(30), index=True)
    memo = db.Column(db.String(255))
    posted_at = db.Column(db.DateTime, index=True)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    entity_type = db.Column(db.String(30), index=True)
    entity_id = db.Column(db.Integer, index=True)
    status = db.Column(sa_str_enum(["DRAFT", "POSTED", "VOID"], name="gl_batch_status"), default="DRAFT", nullable=False, index=True)

    entries = db.relationship("GLEntry", backref="batch", cascade="all, delete-orphan", passive_deletes=True, order_by="GLEntry.id")

    __table_args__ = (
        db.UniqueConstraint("source_type", "source_id", "purpose", name="uq_gl_source_purpose"),
        db.Index("ix_gl_entity", "entity_type", "entity_id"),
        db.Index("ix_gl_status_source", "status", "source_type", "source_id"),
        db.Index("ix_gl_posted_status", "status", "posted_at"),
    )

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("status")
    def _v_status(self, _, v):
        return (getattr(v, "value", v) or "DRAFT").upper()

    def __repr__(self):
        return f"<GLBatch {self.code} {self.source_type}:{self.source_id}>"


def _assert_gl_batch_not_in_locked_period(target: "GLBatch") -> None:
    """منع ترحيل قيود في فترة مقفلة (ما عدا قيود الإقفال والعكس والافتتاح)."""
    st = (getattr(target, "status", None) or "DRAFT").upper()
    if st != "POSTED":
        return
    src = (getattr(target, "source_type", None) or "").upper()
    if src in ("CLOSING_ENTRY", "REVERSAL", "PERIOD_CLOSE", "OPENING_BALANCE"):
        return
    posted = getattr(target, "posted_at", None)
    if not posted:
        return
    try:
        from utils.period_close_service import assert_posting_allowed
        assert_posting_allowed(posted)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


@event.listens_for(GLBatch, "before_insert")
def _glb_before_insert(mapper, connection, target: "GLBatch"):
    target.currency = (target.currency or DEFAULT_CURRENCY).upper()
    if not target.code:
        target.code = f"{target.source_type or 'SRC'}-{target.source_id or 0}-{target.purpose or 'PUR'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    if (target.status or "DRAFT").upper() == "POSTED" and not target.posted_at:
        target.posted_at = datetime.now(timezone.utc)
    _assert_gl_batch_not_in_locked_period(target)


@event.listens_for(GLBatch, "before_update")
def _glb_before_update(mapper, connection, target: "GLBatch"):
    target.currency = (target.currency or DEFAULT_CURRENCY).upper()
    st = (target.status or "DRAFT").upper()
    if st == "POSTED" and not target.posted_at:
        target.posted_at = datetime.now(timezone.utc)
    if st != "POSTED":
        target.posted_at = None
    _assert_gl_batch_not_in_locked_period(target)


class GLEntry(db.Model, TimestampMixin):
    __tablename__ = "gl_entries"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("gl_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    account = db.Column(db.String(50), db.ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False, index=True)
    debit = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    credit = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    currency = db.Column(db.String(10), default=DEFAULT_CURRENCY, nullable=False)
    ref = db.Column(db.String(50))

    __table_args__ = (
        db.CheckConstraint("debit >= 0", name="ck_gl_debit_ge_0"),
        db.CheckConstraint("credit >= 0", name="ck_gl_credit_ge_0"),
        db.CheckConstraint("(debit > 0 OR credit > 0)", name="ck_gl_entry_nonzero"),
        db.CheckConstraint("(debit = 0 OR credit = 0)", name="ck_gl_entry_one_side"),
        db.Index("ix_gl_entries_account_currency", "account", "currency"),
        db.Index("ix_gl_entries_batch_account", "batch_id", "account"),
    )

    @validates("account")
    def _v_account(self, _, v):
        s = (v or "").strip().upper()
        if not s:
            raise ValueError("account required")
        return s

    @validates("currency")
    def _v_currency(self, _, v):
        return (v or DEFAULT_CURRENCY).upper()

    @validates("debit", "credit")
    def _v_amounts(self, key, v):
        if v is None:
            return 0
        if float(v) < 0:
            raise ValueError(f"{key} must be >= 0")
        return q(v)

    def __repr__(self):
        return f"<GLEntry {self.account} D:{self.debit} C:{self.credit}>"


PAYMENT_GL_MAP = {
    "CASH": "CASH",
    "CHEQUE": "BANK",
    "BANK": "BANK",
    "CARD": "CARD",
    "ONLINE": "BANK",
    "OTHER": "CASH",
}

GL_ACCOUNTS = {
    "AR": "1100_AR",
    "REV": "4000_SALES",
    "SALES": "4000_SALES",
    "SERVICE_REV": "4100_SERVICE_REVENUE",
    "VAT": "2100_VAT_PAYABLE",
    "INCOME_TAX_PAYABLE": "2200_INCOME_TAX_PAYABLE",
    "INCOME_TAX_EXP": "6200_INCOME_TAX_EXPENSE",
    "CASH": "1000_CASH",
    "BANK": "1010_BANK",
    "CARD": "1020_CARD_CLEARING",
    "AP": "2000_AP",
    "EXP": "5000_EXPENSES",
    "INV_EXCHANGE": "1205_INV_EXCHANGE",
    "COGS_EXCHANGE": "5105_COGS_EXCHANGE",
    "ADVANCE": "2300_ADV_PAY",
    "DEPRECIATION_EXP": "6800_DEPRECIATION",
    "ACCUMULATED_DEP": "1599_ACC_DEP",
    "INVENTORY_RESERVE": "1300_INV_RSV",  # احتياطي المخزون للشركاء
    "DISCOUNT_ALLOWED": "4050_SALES_DISCOUNT",
    "SHIPPING_INCOME": "4200_SHIPPING_INCOME",
}


def _gl_upsert_batch_and_entries(
    connection,
    *,
    source_type: str,
    source_id: int,
    purpose: str,
    currency: str,
    memo: str,
    entries: list[tuple[str, float, float]],
    ref: str,
    entity_type: str | None,
    entity_id: int | None,
):
    if not entries:
        raise ValueError("entries required")
    dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
    if dialect_name == "postgresql":
        batch_table = "public.gl_batches"
        entry_table = "public.gl_entries"
    else:
        batch_table = "gl_batches"
        entry_table = "gl_entries"
    rows = [(str(a or "").strip().upper(), float(d or 0), float(c or 0)) for a, d, c in entries]
    if any(d < 0 or c < 0 for _, d, c in rows):
        raise ValueError("negative amounts not allowed")
    total_debit = round(sum(d for _, d, _ in rows), 2)
    total_credit = round(sum(c for _, _, c in rows), 2)
    if total_debit != total_credit or total_debit <= 0:
        raise ValueError("unbalanced or zero batch")

    accs = [r[0] for r in rows]
    found_codes = connection.execute(
        select(Account.code).where(
            Account.code.in_(accs),
            Account.is_active.is_(True)
        )
    ).scalars().all()
    found_set = set((str(c or "").strip().upper() for c in found_codes))
    required_set = set((str(a or "").strip().upper() for a in accs))
    
    if found_set != required_set:
        missing = required_set - found_set
        with connection.begin_nested():
            for missing_code in missing:
                _ensure_account_exists(connection, missing_code)
        
        found_codes = connection.execute(
            select(Account.code).where(
                Account.code.in_(accs),
                Account.is_active.is_(True)
            )
        ).scalars().all()
        found_set = set((str(c or "").strip().upper() for c in found_codes))
        
        if found_set != required_set:
            still_missing = required_set - found_set
            from flask import current_app
            current_app.logger.warning(f"⚠️ حسابات مفقودة بعد المحاولة: {still_missing}")
            raise ValueError(f"invalid or inactive account(s): {still_missing}")

    existing_posted_id = connection.execute(
        sa_text(f"""
            SELECT id FROM {batch_table}
             WHERE source_type = :st AND source_id = :sid AND purpose = :p
               AND status = 'POSTED'
             ORDER BY id DESC LIMIT 1
        """),
        {"st": source_type, "sid": source_id, "p": purpose}
    ).scalar()
    if existing_posted_id:
        return int(existing_posted_id)

    connection.execute(
        sa_text(f"""
            DELETE FROM {batch_table}
             WHERE source_type = :st AND source_id = :sid AND purpose = :p
               AND status <> 'POSTED'
        """),
        {"st": source_type, "sid": source_id, "p": purpose}
    )

    batch_code = f"{source_type}-{source_id}-{purpose}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    posted_at = datetime.now(timezone.utc)
    
    cur = connection.execute(
        sa_text(f"""
            INSERT INTO {batch_table}
                (code, source_type, source_id, purpose, memo, posted_at, currency, entity_type, entity_id, status, created_at, updated_at)
            VALUES
                (:code, :st, :sid, :p, :memo, :posted_at, :cur, :etype, :eid, 'POSTED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
        """),
        {
            "code": batch_code,
            "st": source_type,
            "sid": source_id,
            "p": purpose,
            "memo": memo or "",
            "posted_at": posted_at,
            "cur": (currency or "ILS").upper(),
            "etype": entity_type,
            "eid": entity_id,
        }
    )
    batch_id = cur.scalar_one()

    for acct, debit, credit in rows:
        connection.execute(
            sa_text(f"""
                INSERT INTO {entry_table}
                    (batch_id, account, debit, credit, currency, ref, created_at, updated_at)
                VALUES
                    (:bid, :acc, :d, :c, :cur, :ref, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"bid": batch_id, "acc": acct, "d": debit, "c": credit, "cur": (currency or "ILS").upper(), "ref": (ref or "").strip()}
        )

    return int(batch_id)


# ===== نظام تقييمات المنتجات =====

class ProductRating(db.Model, TimestampMixin, AuditMixin):
    """تقييمات المنتجات"""
    __tablename__ = "product_ratings"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)  # يمكن أن يكون تقييم مجهول
    rating = Column(Integer, nullable=False)  # من 1 إلى 5
    title = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    is_verified_purchase = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=True, nullable=False)  # للمراجعة
    helpful_count = Column(Integer, default=0, nullable=False)
    
    # العلاقات
    product = relationship("Product", backref="ratings")
    customer = relationship("Customer", backref="product_ratings")
    
    # فهارس
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range"),
        Index("ix_product_ratings_product_id", "product_id"),
        Index("ix_product_ratings_customer_id", "customer_id"),
        Index("ix_product_ratings_rating", "rating"),
    )
    
    def to_dict(self):
        """تحويل التقييم إلى قاموس"""
        return {
            "id": self.id,
            "product_id": self.product_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else "عميل مجهول",
            "rating": self.rating,
            "title": self.title,
            "comment": self.comment,
            "is_verified_purchase": self.is_verified_purchase,
            "is_approved": self.is_approved,
            "helpful_count": self.helpful_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    @classmethod
    def get_product_ratings(cls, product_id, approved_only=True):
        """الحصول على تقييمات منتج معين"""
        query = cls.query.filter_by(product_id=product_id)
        if approved_only:
            query = query.filter_by(is_approved=True)
        return query.order_by(cls.created_at.desc()).all()
    
    @classmethod
    def get_product_average_rating(cls, product_id):
        """الحصول على متوسط تقييم المنتج"""
        result = cls.query.filter_by(
            product_id=product_id,
            is_approved=True
        ).with_entities(
            func.avg(cls.rating).label('avg_rating'),
            func.count(cls.id).label('total_ratings')
        ).first()
        
        if result and result.avg_rating:
            return {
                'average': round(float(result.avg_rating), 1),
                'total': result.total_ratings
            }
        return {'average': 0, 'total': 0}
    
    @classmethod
    def get_rating_distribution(cls, product_id):
        """الحصول على توزيع التقييمات"""
        results = cls.query.filter_by(
            product_id=product_id,
            is_approved=True
        ).with_entities(
            cls.rating,
            func.count(cls.id).label('count')
        ).group_by(cls.rating).all()
        
        distribution = {i: 0 for i in range(1, 6)}
        for result in results:
            distribution[result.rating] = result.count
        
        return distribution


class ProductRatingHelpful(db.Model, TimestampMixin):
    """تقييمات مفيدة للتقييمات"""
    __tablename__ = "product_rating_helpful"
    
    id = Column(Integer, primary_key=True)
    rating_id = Column(Integer, ForeignKey("product_ratings.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)  # للعملاء غير المسجلين
    is_helpful = Column(Boolean, nullable=False)
    
    # العلاقات
    rating = relationship("ProductRating")
    customer = relationship("Customer")
    
    # فهارس
    __table_args__ = (
        Index("ix_rating_helpful_rating_id", "rating_id"),
        Index("ix_rating_helpful_customer_id", "customer_id"),
        Index("ix_rating_helpful_ip", "ip_address"),
    )
    
    @classmethod
    def mark_helpful(cls, rating_id, customer_id=None, ip_address=None, is_helpful=True):
        """تحديد التقييم كمفيد أو غير مفيد"""
        # التحقق من عدم التكرار
        existing = cls.query.filter_by(rating_id=rating_id)
        if customer_id:
            existing = existing.filter_by(customer_id=customer_id)
        elif ip_address:
            existing = existing.filter_by(ip_address=ip_address)
        
        existing = existing.first()
        
        if existing:
            existing.is_helpful = is_helpful
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_helpful = cls(
                rating_id=rating_id,
                customer_id=customer_id,
                ip_address=ip_address,
                is_helpful=is_helpful
            )
            db.session.add(new_helpful)
        
        # تحديث عداد المفيد
        rating = db.session.get(ProductRating, rating_id)
        if rating:
            helpful_count = cls.query.filter_by(
                rating_id=rating_id,
                is_helpful=True
            ).count()
            rating.helpful_count = helpful_count
            db.session.add(rating)
        
        db.session.commit()


# ===== نظام الولاء للعملاء =====

class CustomerLoyalty(db.Model, TimestampMixin, AuditMixin):
    """نظام الولاء للعملاء"""
    __tablename__ = "customer_loyalty"
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, unique=True)
    total_points = Column(Integer, default=0, nullable=False)
    available_points = Column(Integer, default=0, nullable=False)
    used_points = Column(Integer, default=0, nullable=False)
    loyalty_tier = Column(String(50), default="BRONZE", nullable=False)  # BRONZE, SILVER, GOLD, PLATINUM
    total_spent = Column(Numeric(12, 2), default=0, nullable=False)
    last_activity = Column(DateTime, nullable=True)
    
    # العلاقات
    customer = relationship("Customer", backref="loyalty")
    
    # فهارس
    __table_args__ = (
        Index("ix_customer_loyalty_customer_id", "customer_id"),
        Index("ix_customer_loyalty_tier", "loyalty_tier"),
    )
    
    def to_dict(self):
        """تحويل بيانات الولاء إلى قاموس"""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "total_points": self.total_points,
            "available_points": self.available_points,
            "used_points": self.used_points,
            "loyalty_tier": self.loyalty_tier,
            "total_spent": float(self.total_spent),
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }
    
    def add_points(self, points, reason="شراء"):
        """إضافة نقاط للعميل"""
        self.total_points += points
        self.available_points += points
        self.last_activity = datetime.now(timezone.utc)
        
        # إنشاء سجل النقاط
        point_record = CustomerLoyaltyPoints(
            customer_id=self.customer_id,
            points=points,
            reason=reason,
            type="EARNED"
        )
        db.session.add(point_record)
        
        # تحديث المستوى
        self.update_tier()
        
        db.session.add(self)
        db.session.commit()
    
    def use_points(self, points, reason="استرداد"):
        """استخدام نقاط العميل"""
        if self.available_points < points:
            raise ValueError("نقاط غير كافية")
        
        self.available_points -= points
        self.used_points += points
        self.last_activity = datetime.now(timezone.utc)
        
        # إنشاء سجل النقاط
        point_record = CustomerLoyaltyPoints(
            customer_id=self.customer_id,
            points=-points,
            reason=reason,
            type="USED"
        )
        db.session.add(point_record)
        
        db.session.add(self)
        db.session.commit()
    
    def update_tier(self):
        """تحديث مستوى الولاء"""
        spent = float(self.total_spent)
        
        if spent >= 10000:
            self.loyalty_tier = "PLATINUM"
        elif spent >= 5000:
            self.loyalty_tier = "GOLD"
        elif spent >= 2000:
            self.loyalty_tier = "SILVER"
        else:
            self.loyalty_tier = "BRONZE"
    
    @classmethod
    def get_or_create(cls, customer_id):
        """الحصول على أو إنشاء سجل ولاء للعميل"""
        loyalty = cls.query.filter_by(customer_id=customer_id).first()
        if not loyalty:
            loyalty = cls(customer_id=customer_id)
            db.session.add(loyalty)
            db.session.commit()
        return loyalty


class CustomerLoyaltyPoints(db.Model, TimestampMixin):
    """سجل نقاط الولاء"""
    __tablename__ = "customer_loyalty_points"
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    points = Column(Integer, nullable=False)  # يمكن أن يكون سالب للاستخدام
    reason = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # EARNED, USED, EXPIRED, BONUS
    reference_id = Column(Integer, nullable=True)  # مرجع للعملية (مثل معرف الدفعة)
    reference_type = Column(String(50), nullable=True)  # نوع المرجع (PAYMENT, PURCHASE, etc.)
    expires_at = Column(DateTime, nullable=True)
    
    # العلاقات
    customer = relationship("Customer", backref="loyalty_points")
    
    # فهارس
    __table_args__ = (
        Index("ix_loyalty_points_customer_id", "customer_id"),
        Index("ix_loyalty_points_type", "type"),
        Index("ix_loyalty_points_expires", "expires_at"),
    )
    
    def to_dict(self):
        """تحويل سجل النقاط إلى قاموس"""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "points": self.points,
            "reason": self.reason,
            "type": self.type,
            "reference_id": self.reference_id,
            "reference_type": self.reference_type,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==========================================
# نموذج الشيكات المستقلة (Independent Checks)
# ==========================================

class CheckStatus(str, enum.Enum):
    """حالات الشيك"""
    PENDING = "PENDING"
    CASHED = "CASHED"
    RETURNED = "RETURNED"
    BOUNCED = "BOUNCED"
    RESUBMITTED = "RESUBMITTED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"
    OVERDUE = "OVERDUE"
    
    @property
    def label(self):
        return {
            "PENDING": "معلق",
            "CASHED": "تم الصرف",
            "RETURNED": "مرتجع",
            "BOUNCED": "مرفوض",
            "RESUBMITTED": "أعيد للبنك",
            "CANCELLED": "ملغي",
            "ARCHIVED": "مؤرشف",
            "OVERDUE": "متأخر"
        }[self.value]


class Check(db.Model, TimestampMixin, AuditMixin):
    """
    نموذج الشيكات المستقلة - للشيكات التي لا ترتبط بمدفوعات أو مصروفات
    يمكن إضافتها يدوياً من قبل المستخدم
    """
    __tablename__ = "checks"
    
    id = Column(Integer, primary_key=True)
    
    # معلومات الشيك الأساسية
    check_number = Column(String(100), nullable=False, index=True)
    check_bank = Column(String(200), nullable=False)
    check_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    check_due_date = Column(DateTime, nullable=False, index=True)
    
    # المبلغ والعملة
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="ILS", nullable=False)
    
    # سعر الصرف وقت إصدار الشيك (تاريخ المعاملة)
    fx_rate_issue = Column(Numeric(10, 6))  # سعر الصرف عند الإصدار
    fx_rate_issue_source = Column(String(20))  # مصدر السعر (online, manual, default)
    fx_rate_issue_timestamp = Column(DateTime)  # وقت الحصول على السعر
    fx_rate_issue_base = Column(String(10))  # العملة الأساسية
    fx_rate_issue_quote = Column(String(10))  # العملة المقابلة (ILS)
    
    # سعر الصرف وقت صرف الشيك (تاريخ الصرف الفعلي)
    fx_rate_cash = Column(Numeric(10, 6))  # سعر الصرف عند الصرف
    fx_rate_cash_source = Column(String(20))  # مصدر السعر
    fx_rate_cash_timestamp = Column(DateTime)  # وقت الصرف الفعلي
    fx_rate_cash_base = Column(String(10))  # العملة الأساسية
    fx_rate_cash_quote = Column(String(10))  # العملة المقابلة (ILS)
    
    # الاتجاه والحالة
    direction = Column(sa_str_enum(PaymentDirection, name="check_direction"), 
                      default=PaymentDirection.IN.value, nullable=False, index=True)
    status = Column(sa_str_enum(CheckStatus, name="check_status"), 
                   default=CheckStatus.PENDING.value, nullable=False, index=True)
    
    # معلومات الساحب (من يصدر الشيك)
    drawer_name = Column(String(200))  # اسم الساحب
    drawer_phone = Column(String(20))  # هاتف الساحب
    drawer_id_number = Column(String(50))  # رقم هوية الساحب
    drawer_address = Column(Text)  # عنوان الساحب
    
    # معلومات المستفيد (من يستلم الشيك)
    payee_name = Column(String(200))  # اسم المستفيد
    payee_phone = Column(String(20))  # هاتف المستفيد
    payee_account = Column(String(50))  # رقم حساب المستفيد
    
    # معلومات إضافية
    notes = Column(Text)  # ملاحظات عامة
    internal_notes = Column(Text)  # ملاحظات داخلية (لا تظهر للعميل)
    reference_number = Column(String(100))  # رقم مرجعي
    
    # تاريخ التغييرات (JSON)
    status_history = Column(Text)  # JSON array of status changes
    
    # الربط بعميل أو مورد (اختياري)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), index=True)
    partner_id = Column(Integer, ForeignKey("partners.id", ondelete="SET NULL"), index=True)
    
    # ✅ الربط بالدفعة (اختياري)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    
    # من أنشأ الشيك
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # حقول الأرشيف
    is_archived = Column(Boolean, default=False, nullable=False, index=True)
    archived_at = Column(DateTime, index=True)
    archived_by = Column(Integer, ForeignKey("users.id"), index=True)
    archive_reason = Column(String(200))
    
    # عدد مرات السماح بإعادة الإرسال والرجوع من الحالة القانونية
    resubmit_allowed_count = Column(Integer, default=1, nullable=False)  # عدد مرات السماح بإعادة الإرسال للبنك
    legal_return_allowed_count = Column(Integer, default=1, nullable=False)  # عدد مرات السماح بالرجوع من الحالة القانونية
    
    # العلاقات
    customer = relationship("Customer", backref="independent_checks")
    supplier = relationship("Supplier", backref="independent_checks")
    partner = relationship("Partner", backref="independent_checks")
    payment = relationship("Payment", backref="related_check", foreign_keys=[payment_id])
    created_by = relationship("User", backref="checks_created", foreign_keys=[created_by_id])
    archived_by_user = relationship("User", foreign_keys=[archived_by])
    
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_check_amount_positive"),
        Index("ix_checks_status_due_date", "status", "check_due_date"),
        Index("ix_checks_direction_status", "direction", "status"),
    )
    
    def __repr__(self):
        return f"<Check {self.check_number} - {self.check_bank} - {self.amount} {self.currency}>"
    
    @property
    def entity_name(self):
        """الحصول على اسم العميل/المورد/الشريك/الشركة المرتبط بالشيك"""
        # الأولوية: من Payment إذا كان موجوداً
        if self.payment_id and self.payment:
            if self.payment.customer:
                return self.payment.customer.name
            elif self.payment.supplier:
                return self.payment.supplier.name
            elif self.payment.partner:
                return self.payment.partner.name
        
        # إذا لم يكن هناك payment، نأخذ مباشرة
        if self.customer:
            return self.customer.name
        elif self.supplier:
            return self.supplier.name
        elif self.partner:
            return self.partner.name
        
        # ✅ إذا لم تكن هناك جهة، الشيك مرتبط بالشركة - جلب اسم الشركة من الثوابت
        if not self.customer_id and not self.supplier_id and not self.partner_id:
            try:
                from models import SystemSettings
                company_name = SystemSettings.get_setting('COMPANY_NAME', 'الشركة')
                return company_name or 'الشركة'
            except Exception:
                return 'الشركة'
        
        return "غير محدد"
    
    @property
    def entity_type(self):
        """نوع الكيان المرتبط (عميل/مورد/شريك)"""
        if self.payment_id and self.payment:
            if self.payment.customer_id:
                return "customer"
            elif self.payment.supplier_id:
                return "supplier"
            elif self.payment.partner_id:
                return "partner"
        
        if self.customer_id:
            return "customer"
        elif self.supplier_id:
            return "supplier"
        elif self.partner_id:
            return "partner"
        
        return None
    
    @property
    def entity_id(self):
        """ID الكيان المرتبط"""
        if self.payment_id and self.payment:
            if self.payment.customer_id:
                return self.payment.customer_id
            elif self.payment.supplier_id:
                return self.payment.supplier_id
            elif self.payment.partner_id:
                return self.payment.partner_id
        
        if self.customer_id:
            return self.customer_id
        elif self.supplier_id:
            return self.supplier_id
        elif self.partner_id:
            return self.partner_id
        
        return None
    
    @hybrid_property
    def is_overdue(self):
        """هل الشيك متأخر"""
        if self.status in [CheckStatus.CASHED.value, CheckStatus.CANCELLED.value]:
            return False
        due = self.check_due_date
        if isinstance(due, datetime):
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return due < datetime.now(timezone.utc)
        if due is None:
            return False
        return due < datetime.now(timezone.utc).date()
    
    @hybrid_property
    def days_until_due(self):
        """عدد الأيام حتى الاستحقاق"""
        if isinstance(self.check_due_date, datetime):
            due_date = self.check_due_date.date()
        else:
            due_date = self.check_due_date
        today = datetime.now(timezone.utc).date()
        return (due_date - today).days
    
    @hybrid_property
    def is_due_soon(self):
        """هل الشيك قريب من الاستحقاق (خلال 7 أيام)"""
        return 0 <= self.days_until_due <= 7
    
    def add_status_change(self, new_status, reason=None, user=None):
        """إضافة تغيير حالة إلى السجل"""
        import json
        
        # تحميل السجل الحالي
        history = []
        if self.status_history:
            try:
                history = json.loads(self.status_history)
            except Exception:
                history = []
        
        # إضافة التغيير الجديد
        change = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_status": self.status,
            "new_status": new_status,
            "reason": reason,
            "user": user.username if user else None
        }
        history.append(change)
        
        # حفظ السجل
        self.status_history = json.dumps(history, ensure_ascii=False)
        self.status = new_status
    
    def get_status_history(self):
        """الحصول على سجل التغييرات"""
        import json
        if not self.status_history:
            return []
        try:
            return json.loads(self.status_history)
        except Exception:
            return []
    
    def get_entity_name(self):
        """الحصول على اسم الجهة المرتبطة"""
        if self.customer:
            return self.customer.name
        elif self.supplier:
            return self.supplier.name
        elif self.partner:
            return self.partner.name
        elif self.direction == PaymentDirection.IN.value:
            return self.drawer_name or "غير محدد"
        else:
            return self.payee_name or "غير محدد"
    
    def to_dict(self):
        """تحويل إلى قاموس"""
        return {
            "id": self.id,
            "check_number": self.check_number,
            "check_bank": self.check_bank,
            "check_date": self.check_date.isoformat() if self.check_date else None,
            "check_due_date": self.check_due_date.isoformat() if self.check_due_date else None,
            "amount": float(self.amount),
            "currency": self.currency,
            "direction": self.direction,
            "status": self.status,
            "drawer_name": self.drawer_name,
            "drawer_phone": self.drawer_phone,
            "payee_name": self.payee_name,
            "payee_phone": self.payee_phone,
            "notes": self.notes,
            "reference_number": self.reference_number,
            "entity_name": self.get_entity_name(),
            "is_overdue": self.is_overdue,
            "days_until_due": self.days_until_due,
            "is_due_soon": self.is_due_soon,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

# ==================== Event Listeners للشيكات ====================

def _compute_issue_fx_fields(connection, currency: str | None, at: datetime | None = None) -> dict:
    check_currency = (currency or "ILS").upper()
    default_currency = "ILS"
    if check_currency == default_currency:
        return {}
    try:
        rate = _fx_rate_local_via_connection(connection, check_currency, default_currency, at or datetime.now(timezone.utc))
        if rate and rate > 0:
            now_ts = datetime.now(timezone.utc)
            return {
                "fx_rate_issue": Decimal(str(rate)),
                "fx_rate_issue_source": "manual",
                "fx_rate_issue_timestamp": now_ts,
                "fx_rate_issue_base": check_currency,
                "fx_rate_issue_quote": default_currency,
            }
    except Exception:
        pass
    return {}


def _check_backfill_counterparty_ids(connection, target: "Check") -> None:
    payment_id = getattr(target, "payment_id", None)
    if not payment_id:
        return
    row = None
    try:
        row = connection.execute(
            sa_text(
                """
                SELECT
                    COALESCE(
                        p.customer_id,
                        s.customer_id,
                        i.customer_id,
                        sr.customer_id,
                        pr.customer_id,
                        e.customer_id,
                        CASE WHEN UPPER(COALESCE(e.payee_type,'')) = 'CUSTOMER' THEN e.payee_entity_id END
                    ) AS customer_id,
                    COALESCE(
                        p.supplier_id,
                        e.supplier_id,
                        CASE WHEN UPPER(COALESCE(e.payee_type,'')) = 'SUPPLIER' THEN e.payee_entity_id END
                    ) AS supplier_id,
                    COALESCE(
                        p.partner_id,
                        e.partner_id,
                        CASE WHEN UPPER(COALESCE(e.payee_type,'')) = 'PARTNER' THEN e.payee_entity_id END
                    ) AS partner_id
                FROM payments p
                LEFT JOIN sales s ON s.id = p.sale_id
                LEFT JOIN invoices i ON i.id = p.invoice_id
                LEFT JOIN service_requests sr ON sr.id = p.service_id
                LEFT JOIN preorders pr ON pr.id = p.preorder_id
                LEFT JOIN expenses e ON e.id = p.expense_id
                WHERE p.id = :pid
                """
            ),
            {"pid": int(payment_id)},
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return

    pairs = [("customer_id", row[0]), ("supplier_id", row[1]), ("partner_id", row[2])]
    for key, expected in pairs:
        if expected is None:
            continue
        current = getattr(target, key, None)
        if current is None:
            setattr(target, key, int(expected))
            continue
        try:
            if int(current) != int(expected):
                raise ValueError("check.counterparty_mismatch")
        except Exception:
            raise ValueError("check.counterparty_mismatch")


@event.listens_for(Check, "before_insert", propagate=True)
def _check_before_insert(mapper, connection, target: "Check"):
    """تعيين سعر الصرف وقت إصدار الشيك تلقائياً"""
    _check_backfill_counterparty_ids(connection, target)
    for key, value in _compute_issue_fx_fields(connection, getattr(target, "currency", None), getattr(target, "check_date", None)).items():
        setattr(target, key, value)


@event.listens_for(Check, "after_update", propagate=True)
def _check_sync_payment_status(mapper, connection, target: "Check"):
    """✅ مزامنة حالة الدفعة عند تغيير حالة الشيك"""
    try:
        from sqlalchemy.orm.attributes import get_history
        history = get_history(target, 'status')
        
        payment_id = getattr(target, 'payment_id', None)
        if not payment_id:
            return
        
        if not history.has_changes():
            return
        
        try:
            from routes.checks import PaymentStatusSyncService
            PaymentStatusSyncService.sync_payment_status_from_check(target, connection)
        except ImportError:
            from flask import current_app
            current_app.logger.warning(f"⚠️ لا يمكن استيراد PaymentStatusSyncService - استخدام المنطق القديم")
            _check_sync_payment_status_legacy(connection, target, payment_id)
    
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في مزامنة حالة الدفعة للشيك #{getattr(target, 'id', '?')}: {e}")


def _check_sync_payment_status_legacy(connection, target, payment_id):
    from sqlalchemy import text as sa_text
    from models import PaymentStatus
    
    check_status = str(getattr(target, 'status', '')).upper()
    
    payment_query = connection.execute(
        sa_text("SELECT id, status FROM payments WHERE id = :payment_id"),
        {"payment_id": payment_id}
    ).fetchone()
    
    if not payment_query:
        return
    
    payment_status = payment_query[1] or 'PENDING'
    
    if check_status in ['RETURNED', 'BOUNCED']:
        new_payment_status = PaymentStatus.FAILED.value
    elif check_status == 'PENDING':
        new_payment_status = PaymentStatus.PENDING.value
    elif check_status == 'RESUBMITTED':
        new_payment_status = PaymentStatus.PENDING.value
    elif check_status == 'CASHED':
        new_payment_status = PaymentStatus.COMPLETED.value
    elif check_status == 'CANCELLED':
        new_payment_status = PaymentStatus.CANCELLED.value
    else:
        new_payment_status = None
    
    if new_payment_status and new_payment_status != payment_status:
        connection.execute(
            sa_text("UPDATE payments SET status = :new_status WHERE id = :payment_id"),
            {"new_status": new_payment_status, "payment_id": payment_id}
        )


@event.listens_for(Check, "before_update", propagate=True)
def _check_before_update(mapper, connection, target: "Check"):
    """تعيين سعر الصرف وقت صرف الشيك عند تغيير الحالة إلى CASHED"""
    _check_backfill_counterparty_ids(connection, target)
    check_currency = getattr(target, "currency", None) or DEFAULT_CURRENCY
    default_currency = DEFAULT_CURRENCY
    
    # الحصول على الحالة السابقة
    insp = inspect(target)
    hist = insp.attrs.status.history
    
    # إذا تم تغيير الحالة إلى CASHED وكانت العملة مختلفة
    if hist.has_changes() and target.status == CheckStatus.CASHED.value:
        if check_currency != default_currency and not target.fx_rate_cash:
            try:
                at = getattr(target, "check_date", None) or getattr(target, "check_due_date", None) or datetime.now(timezone.utc)
                rate = _fx_rate_local_via_connection(connection, check_currency, default_currency, at)
                if rate and rate > 0:
                    target.fx_rate_cash = Decimal(str(rate))
                    target.fx_rate_cash_source = "manual"
                    target.fx_rate_cash_timestamp = datetime.now(timezone.utc)
                    target.fx_rate_cash_base = check_currency
                    target.fx_rate_cash_quote = default_currency
            except Exception:
                pass


# إضافة العلاقات المطلوبة لحل تحذيرات SQLAlchemy
# هذه العلاقات مطلوبة لحل التحذيرات المتعلقة بالعلاقات المتداخلة

# إضافة العلاقة في User model
User.archived_records = relationship(
    "Archive",
    foreign_keys="[Archive.archived_by]",
    back_populates="archiver",
    overlaps="archives,user"
)

# إضافة العلاقة في Archive model
Archive.archiver = relationship(
    "User",
    foreign_keys="[Archive.archived_by]",
    back_populates="archived_records",
    overlaps="archives,user"
)


# ========================================================================
# Event Listeners - تحديث أرصدة الشركاء تلقائياً
# ========================================================================

@event.listens_for(WarehousePartnerShare, 'after_insert')
@event.listens_for(WarehousePartnerShare, 'after_update')
@event.listens_for(WarehousePartnerShare, 'after_delete')
def _update_partner_on_share_change(mapper, connection, target):
    """
    تحديث رصيد الشريك عند تغيير نسبته في منتج
    """
    try:
        partner_id = target.partner_id
        if partner_id:
            _queue_partner_balance(target, partner_id)
    except Exception as e:
        pass


@event.listens_for(ShipmentItem, 'after_insert')
@event.listens_for(ShipmentItem, 'after_update') 
@event.listens_for(ShipmentItem, 'after_delete')
def _update_partner_on_shipment_item_change(mapper, connection, target):
    """
    تحديث أرصدة الشركاء المرتبطين بالمنتج عند تغيير بند الشحنة
    """
    try:
        # جلب الشركاء المرتبطين بهذا المنتج
        if target.product_id:
            result = connection.execute(
                sa_text("""
                    SELECT DISTINCT partner_id 
                    FROM warehouse_partner_shares 
                    WHERE product_id = :pid AND partner_id IS NOT NULL
                """),
                {"pid": target.product_id}
            )
            partner_ids = [row[0] for row in result]
            
            # تحديث رصيد كل شريك
            for partner_id in partner_ids:
                _queue_partner_balance(target, partner_id)
    except Exception as e:
        pass


class SaaSPlan(db.Model, TimestampMixin):
    __tablename__ = 'saas_plans'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    price_monthly = Column(Numeric(10, 2), nullable=False)
    price_yearly = Column(Numeric(10, 2))
    currency = Column(String(10), default=DEFAULT_CURRENCY, nullable=False)
    max_users = Column(Integer)
    max_invoices = Column(Integer)
    storage_gb = Column(Integer)
    features = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False, server_default=sa_text("true"))
    is_popular = Column(Boolean, default=False, nullable=False, server_default=sa_text("false"))
    sort_order = Column(Integer, default=0)
    
    subscriptions = relationship("SaaSSubscription", back_populates="plan")
    
    def __repr__(self):
        return f"<SaaSPlan {self.name}>"


class SaaSSubscription(db.Model, TimestampMixin):
    __tablename__ = 'saas_subscriptions'
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey('saas_plans.id'), nullable=False, index=True)
    status = Column(String(20), default='trial', nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    trial_end_date = Column(DateTime)
    auto_renew = Column(Boolean, default=True, nullable=False, server_default=sa_text("true"))
    cancelled_at = Column(DateTime)
    cancelled_by = Column(Integer, ForeignKey('users.id'))
    cancellation_reason = Column(Text)
    
    customer = relationship("Customer", backref="saas_subscriptions")
    plan = relationship("SaaSPlan", back_populates="subscriptions")
    cancelled_by_user = relationship("User", foreign_keys=[cancelled_by])
    invoices = relationship("SaaSInvoice", back_populates="subscription")
    
    def __repr__(self):
        return f"<SaaSSubscription {self.id} - {self.customer.name if self.customer else 'N/A'}>"


class SaaSInvoice(db.Model, TimestampMixin):
    __tablename__ = 'saas_invoices'
    
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey('saas_subscriptions.id'), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), default=DEFAULT_CURRENCY, nullable=False)
    status = Column(String(20), default='pending', nullable=False)
    due_date = Column(DateTime)
    paid_at = Column(DateTime)
    payment_method = Column(String(50))
    notes = Column(Text)
    
    subscription = relationship("SaaSSubscription", back_populates="invoices")
    
    def __repr__(self):
        return f"<SaaSInvoice {self.invoice_number}>"


class RecurringInvoiceTemplate(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "recurring_invoice_templates"
    
    id = db.Column(db.Integer, primary_key=True)
    template_name = db.Column(db.String(200), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    description = db.Column(db.Text)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    currency = db.Column(db.String(10), default='ILS', nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    frequency = db.Column(db.String(20), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    next_invoice_date = db.Column(db.Date, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, server_default=sa_text("true"), index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), index=True)
    
    customer = db.relationship('Customer', backref='recurring_templates')
    branch = db.relationship('Branch')
    site = db.relationship('Site')
    schedules = db.relationship('RecurringInvoiceSchedule', back_populates='template', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.CheckConstraint('amount >= 0', name='ck_recurring_amount_ge_0'),
        db.CheckConstraint("frequency IN ('DAILY','WEEKLY','MONTHLY','QUARTERLY','YEARLY')", name='ck_recurring_frequency'),
    )
    
    def __repr__(self):
        return f"<RecurringTemplate {self.template_name}>"


class RecurringInvoiceSchedule(db.Model, TimestampMixin):
    __tablename__ = "recurring_invoice_schedules"
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('recurring_invoice_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), index=True)
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    generated_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='PENDING', nullable=False, index=True)
    error_message = db.Column(db.Text)
    
    template = db.relationship('RecurringInvoiceTemplate', back_populates='schedules')
    invoice = db.relationship('Invoice')
    
    __table_args__ = (
        db.CheckConstraint("status IN ('PENDING','GENERATED','FAILED','SKIPPED')", name='ck_schedule_status'),
    )
    
    def __repr__(self):
        return f"<RecurringSchedule {self.scheduled_date} - {self.status}>"


class FiscalPeriod(db.Model, TimestampMixin):
    """فترة محاسبية — شهر / ربع / نصف سنة / سنة مالية."""
    __tablename__ = "fiscal_periods"

    id = db.Column(db.Integer, primary_key=True)
    period_key = db.Column(db.String(32), nullable=False, unique=True, index=True)
    period_type = db.Column(
        sa_str_enum(["MONTH", "QUARTER", "HALF", "YEAR"], name="fiscal_period_type"),
        nullable=False,
        index=True,
    )
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    period_number = db.Column(db.Integer, nullable=False, default=1)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    status = db.Column(
        sa_str_enum(["OPEN", "CLOSED", "LOCKED"], name="fiscal_period_status"),
        nullable=False,
        default="OPEN",
        server_default=sa_text("'OPEN'"),
        index=True,
    )
    closed_at = db.Column(db.DateTime, index=True)
    closed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    notes = db.Column(db.Text)

    closed_by = db.relationship("User", foreign_keys=[closed_by_id])
    closes = db.relationship("PeriodClose", back_populates="fiscal_period", lazy="dynamic")

    __table_args__ = (
        db.Index("ix_fiscal_period_year_type", "fiscal_year", "period_type"),
        db.CheckConstraint("end_date >= start_date", name="ck_fiscal_period_dates"),
    )

    @property
    def is_closed(self) -> bool:
        return (self.status or "OPEN").upper() in ("CLOSED", "LOCKED")

    def __repr__(self):
        return f"<FiscalPeriod {self.period_key} {self.status}>"


class PeriodClose(db.Model, TimestampMixin):
    """سجل إقفال فترة — قيود GL + لقطات ذمم."""
    __tablename__ = "period_closes"

    id = db.Column(db.Integer, primary_key=True)
    fiscal_period_id = db.Column(
        db.Integer, db.ForeignKey("fiscal_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    close_scope = db.Column(
        sa_str_enum(["GL_ONLY", "FULL"], name="period_close_scope"),
        nullable=False,
        default="FULL",
    )
    net_income = db.Column(db.Numeric(14, 2))
    total_revenue = db.Column(db.Numeric(14, 2))
    total_expenses = db.Column(db.Numeric(14, 2))
    gl_batch_ids = db.Column(db.Text)
    carry_forward_done = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"))
    reopened_at = db.Column(db.DateTime)
    reopened_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)

    fiscal_period = db.relationship("FiscalPeriod", back_populates="closes")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    entity_snapshots = db.relationship(
        "EntityPeriodBalance", back_populates="period_close", cascade="all, delete-orphan", lazy="dynamic"
    )

    __table_args__ = (
        db.Index("ix_period_close_period_created", "fiscal_period_id", "created_at"),
    )

    def __repr__(self):
        return f"<PeriodClose period={self.fiscal_period_id} scope={self.close_scope}>"


class EntityPeriodBalance(db.Model, TimestampMixin):
    """رصيد إقفال عميل/مورد/شريك عند نهاية فترة."""
    __tablename__ = "entity_period_balances"

    id = db.Column(db.Integer, primary_key=True)
    period_close_id = db.Column(
        db.Integer, db.ForeignKey("period_closes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fiscal_period_id = db.Column(
        db.Integer, db.ForeignKey("fiscal_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type = db.Column(
        sa_str_enum(["CUSTOMER", "SUPPLIER", "PARTNER"], name="entity_period_entity_type"),
        nullable=False,
        index=True,
    )
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    closing_balance = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    currency = db.Column(db.String(10), default="ILS")
    applied_to_opening = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"))
    next_period_id = db.Column(db.Integer, db.ForeignKey("fiscal_periods.id", ondelete="SET NULL"), index=True)

    period_close = db.relationship("PeriodClose", back_populates="entity_snapshots")
    fiscal_period = db.relationship("FiscalPeriod", foreign_keys=[fiscal_period_id])

    __table_args__ = (
        db.UniqueConstraint(
            "fiscal_period_id", "entity_type", "entity_id", name="uq_entity_period_balance"
        ),
    )

    def __repr__(self):
        return f"<EntityPeriodBalance {self.entity_type}#{self.entity_id} {self.closing_balance}>"


class Budget(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    account_code = db.Column(db.String(50), db.ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    
    allocated_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    
    account = db.relationship("Account", backref=db.backref("budgets", lazy="dynamic"))
    branch = db.relationship("Branch", backref=db.backref("budgets", lazy="dynamic"))
    site = db.relationship("Site", backref=db.backref("budgets", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("fiscal_year", "account_code", "branch_id", "site_id", name="uq_budget_year_account_branch_site"),
        db.Index("ix_budget_year_branch", "fiscal_year", "branch_id"),
        db.Index("ix_budget_year_account", "fiscal_year", "account_code"),
        db.CheckConstraint("allocated_amount >= 0", name="ck_budget_allocated_ge_0"),
    )

    def get_actual_amount(self):
        from sqlalchemy import func
        expenses = db.session.query(func.sum(Expense.amount)).filter(
            db.extract('year', Expense.date) == self.fiscal_year,
            Expense.branch_id == self.branch_id
        )
        if self.site_id:
            expenses = expenses.filter(Expense.site_id == self.site_id)
        
        return float(expenses.scalar() or 0)

    def get_committed_amount(self):
        total = db.session.query(func.sum(BudgetCommitment.committed_amount)).filter(
            BudgetCommitment.budget_id == self.id,
            BudgetCommitment.status.in_(["PENDING", "APPROVED"])
        ).scalar()
        return float(total or 0)

    def get_available_amount(self):
        return float(self.allocated_amount) - self.get_actual_amount() - self.get_committed_amount()

    def __repr__(self):
        return f"<Budget {self.fiscal_year} {self.account_code} {self.branch_id}>"


class BudgetCommitment(db.Model, TimestampMixin):
    __tablename__ = "budget_commitments"

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = db.Column(sa_str_enum(["EXPENSE", "PURCHASE", "QUOTE"], name="commitment_source_type"), nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    
    committed_amount = db.Column(db.Numeric(12, 2), nullable=False)
    commitment_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    status = db.Column(sa_str_enum(["PENDING", "APPROVED", "PAID", "CANCELLED"], name="commitment_status"), nullable=False, default="PENDING", index=True)
    notes = db.Column(db.Text)
    
    budget = db.relationship("Budget", backref=db.backref("commitments", lazy="dynamic", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("source_type", "source_id", name="uq_commitment_source"),
        db.Index("ix_commitment_budget_status", "budget_id", "status"),
        db.CheckConstraint("committed_amount >= 0", name="ck_commitment_amount_ge_0"),
    )

    def __repr__(self):
        return f"<BudgetCommitment {self.source_type} {self.source_id} {self.committed_amount}>"


class FixedAssetCategory(db.Model, TimestampMixin):
    __tablename__ = "fixed_asset_categories"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    account_code = db.Column(db.String(50), db.ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False)
    depreciation_account_code = db.Column(db.String(50), db.ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False)
    
    useful_life_years = db.Column(db.Integer, nullable=False, default=5)
    depreciation_method = db.Column(sa_str_enum(["STRAIGHT_LINE", "DECLINING_BALANCE"], name="depreciation_method"), nullable=False, default="STRAIGHT_LINE")
    depreciation_rate = db.Column(db.Numeric(5, 2), default=0)
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    
    account = db.relationship("Account", foreign_keys=[account_code], backref=db.backref("asset_categories", lazy="dynamic"))
    depreciation_account = db.relationship("Account", foreign_keys=[depreciation_account_code], backref=db.backref("depreciation_categories", lazy="dynamic"))

    __table_args__ = (
        db.CheckConstraint("useful_life_years > 0", name="ck_useful_life_gt_0"),
        db.CheckConstraint("depreciation_rate >= 0 AND depreciation_rate <= 100", name="ck_depreciation_rate_range"),
    )

    def __repr__(self):
        return f"<FixedAssetCategory {self.code} {self.name}>"


class FixedAsset(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "fixed_assets"

    id = db.Column(db.Integer, primary_key=True)
    asset_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("fixed_asset_categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    
    purchase_date = db.Column(db.Date, nullable=False, index=True)
    purchase_price = db.Column(db.Numeric(12, 2), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("partners.id"), index=True)
    
    serial_number = db.Column(db.String(100), index=True)
    barcode = db.Column(db.String(100), index=True)
    location = db.Column(db.String(200))
    
    status = db.Column(sa_str_enum(["ACTIVE", "DISPOSED", "SOLD", "STOLEN", "DAMAGED"], name="asset_status"), nullable=False, default="ACTIVE", index=True)
    disposal_date = db.Column(db.Date, index=True)
    disposal_amount = db.Column(db.Numeric(12, 2))
    disposal_notes = db.Column(db.Text)
    
    notes = db.Column(db.Text)
    is_archived = db.Column(db.Boolean, nullable=False, server_default=sa_text("false"), index=True)
    
    category = db.relationship("FixedAssetCategory", backref=db.backref("assets", lazy="dynamic"))
    branch = db.relationship("Branch", backref=db.backref("assets", lazy="dynamic"))
    site = db.relationship("Site", backref=db.backref("assets", lazy="dynamic"))
    supplier = db.relationship("Partner", backref=db.backref("supplied_assets", lazy="dynamic"))

    __table_args__ = (
        db.Index("ix_asset_category_branch", "category_id", "branch_id"),
        db.Index("ix_asset_status_date", "status", "purchase_date"),
        db.CheckConstraint("purchase_price >= 0", name="ck_asset_price_ge_0"),
    )

    def get_current_book_value(self, as_of_date=None):
        if as_of_date is None:
            as_of_date = date.today()
        
        total_depreciation = db.session.query(func.sum(AssetDepreciation.depreciation_amount)).filter(
            AssetDepreciation.asset_id == self.id,
            AssetDepreciation.depreciation_date <= as_of_date
        ).scalar()
        
        return float(self.purchase_price) - float(total_depreciation or 0)

    def __repr__(self):
        return f"<FixedAsset {self.asset_number} {self.name}>"


class AssetDepreciation(db.Model, TimestampMixin):
    __tablename__ = "asset_depreciations"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    fiscal_month = db.Column(db.Integer, index=True)
    
    depreciation_date = db.Column(db.Date, nullable=False, index=True)
    depreciation_amount = db.Column(db.Numeric(12, 2), nullable=False)
    accumulated_depreciation = db.Column(db.Numeric(12, 2), nullable=False)
    book_value = db.Column(db.Numeric(12, 2), nullable=False)
    
    gl_batch_id = db.Column(db.Integer, db.ForeignKey("gl_batches.id"), index=True)
    notes = db.Column(db.Text)
    
    asset = db.relationship("FixedAsset", backref=db.backref("depreciations", lazy="dynamic", cascade="all, delete-orphan"))
    gl_batch = db.relationship("GLBatch", backref=db.backref("asset_depreciations", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("asset_id", "fiscal_year", "fiscal_month", name="uq_depreciation_asset_period"),
        db.Index("ix_depreciation_year_month", "fiscal_year", "fiscal_month"),
        db.CheckConstraint("depreciation_amount >= 0", name="ck_depreciation_amount_ge_0"),
        db.CheckConstraint("fiscal_month >= 1 AND fiscal_month <= 12", name="ck_fiscal_month_range"),
    )

    def __repr__(self):
        return f"<AssetDepreciation {self.asset_id} {self.fiscal_year}/{self.fiscal_month}>"


class AssetMaintenance(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "asset_maintenance"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    maintenance_date = db.Column(db.Date, nullable=False, index=True)
    maintenance_type = db.Column(db.String(100), index=True)
    
    cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"), index=True)
    
    description = db.Column(db.Text)
    next_maintenance_date = db.Column(db.Date, index=True)
    
    asset = db.relationship("FixedAsset", backref=db.backref("maintenance_records", lazy="dynamic", cascade="all, delete-orphan"))
    expense = db.relationship("Expense", backref=db.backref("asset_maintenance", uselist=False))

    __table_args__ = (
        db.Index("ix_maintenance_asset_date", "asset_id", "maintenance_date"),
        db.CheckConstraint("cost >= 0", name="ck_maintenance_cost_ge_0"),
    )

    def __repr__(self):
        return f"<AssetMaintenance {self.asset_id} {self.maintenance_date}>"


class BankAccount(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "bank_accounts"
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    bank_name = db.Column(db.String(200), nullable=False, index=True)
    account_number = db.Column(db.String(100), nullable=False)
    iban = db.Column(db.String(34))
    swift_code = db.Column(db.String(11))
    currency = db.Column(db.String(10), nullable=False, default="ILS", index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    gl_account_code = db.Column(db.String(50), db.ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False)
    opening_balance = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    current_balance = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    last_reconciled_date = db.Column(db.Date, index=True)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    branch = db.relationship("Branch", backref=db.backref("bank_accounts", lazy="dynamic"))
    gl_account = db.relationship("Account", backref=db.backref("bank_accounts", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by], backref=db.backref("created_bank_accounts", lazy="dynamic"))
    updater = db.relationship("User", foreign_keys=[updated_by], backref=db.backref("updated_bank_accounts", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_bank_account_code", "code"),
        db.CheckConstraint("current_balance IS NOT NULL", name="ck_bank_current_balance_not_null"),
    )
    
    def __repr__(self):
        return f"<BankAccount {self.code} {self.name}>"
    
    def get_unreconciled_balance(self):
        from sqlalchemy import func
        unmatched = db.session.query(func.sum(BankTransaction.debit - BankTransaction.credit)).filter(
            BankTransaction.bank_account_id == self.id,
            BankTransaction.matched == False
        ).scalar() or 0
        return float(unmatched)


class BankStatement(db.Model, TimestampMixin):
    __tablename__ = "bank_statements"
    
    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_number = db.Column(db.String(50), index=True)
    statement_date = db.Column(db.Date, nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    opening_balance = db.Column(db.Numeric(15, 2), nullable=False)
    closing_balance = db.Column(db.Numeric(15, 2), nullable=False)
    total_deposits = db.Column(db.Numeric(15, 2), default=0)
    total_withdrawals = db.Column(db.Numeric(15, 2), default=0)
    file_path = db.Column(db.String(500))
    imported_at = db.Column(db.DateTime, index=True)
    imported_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(sa_str_enum(["DRAFT", "IMPORTED", "RECONCILED"], name="statement_status"), nullable=False, default="DRAFT", index=True)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    bank_account = db.relationship("BankAccount", backref=db.backref("statements", lazy="dynamic", cascade="all, delete-orphan"))
    importer = db.relationship("User", foreign_keys=[imported_by], backref=db.backref("imported_statements", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by], backref=db.backref("created_statements", lazy="dynamic"))
    updater = db.relationship("User", foreign_keys=[updated_by], backref=db.backref("updated_statements", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_statement_account_date", "bank_account_id", "statement_date"),
        db.CheckConstraint("closing_balance = opening_balance + total_deposits - total_withdrawals", name="ck_statement_balance"),
    )
    
    def __repr__(self):
        return f"<BankStatement {self.bank_account_id} {self.statement_date}>"


class BankTransaction(db.Model, TimestampMixin):
    __tablename__ = "bank_transactions"
    
    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_id = db.Column(db.Integer, db.ForeignKey("bank_statements.id", ondelete="CASCADE"), index=True)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    value_date = db.Column(db.Date, index=True)
    reference = db.Column(db.String(100), index=True)
    description = db.Column(db.Text)
    debit = db.Column(db.Numeric(15, 2), default=0)
    credit = db.Column(db.Numeric(15, 2), default=0)
    balance = db.Column(db.Numeric(15, 2))
    matched = db.Column(db.Boolean, nullable=False, default=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), index=True)
    gl_batch_id = db.Column(db.Integer, db.ForeignKey("gl_batches.id"), index=True)
    reconciliation_id = db.Column(db.Integer, db.ForeignKey("bank_reconciliations.id"), index=True)
    notes = db.Column(db.Text)
    
    bank_account = db.relationship("BankAccount", backref=db.backref("transactions", lazy="dynamic", cascade="all, delete-orphan"))
    statement = db.relationship("BankStatement", backref=db.backref("transactions", lazy="dynamic", cascade="all, delete-orphan"))
    payment = db.relationship("Payment", backref=db.backref("bank_transactions", lazy="dynamic"))
    gl_batch = db.relationship("GLBatch", backref=db.backref("bank_transactions", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_bank_tx_account_date", "bank_account_id", "transaction_date"),
        db.Index("ix_bank_tx_matched", "matched", "bank_account_id"),
        db.CheckConstraint("(debit = 0 AND credit > 0) OR (credit = 0 AND debit > 0) OR (debit = 0 AND credit = 0)", name="ck_bank_tx_debit_credit"),
    )
    
    def __repr__(self):
        return f"<BankTransaction {self.reference} {self.transaction_date}>"


class BankReconciliation(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "bank_reconciliations"
    
    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    reconciliation_number = db.Column(db.String(50), unique=True, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    book_balance = db.Column(db.Numeric(15, 2), nullable=False)
    bank_balance = db.Column(db.Numeric(15, 2), nullable=False)
    unmatched_book_count = db.Column(db.Integer, default=0)
    unmatched_bank_count = db.Column(db.Integer, default=0)
    unmatched_book_amount = db.Column(db.Numeric(15, 2), default=0)
    unmatched_bank_amount = db.Column(db.Numeric(15, 2), default=0)
    reconciled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reconciled_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    status = db.Column(sa_str_enum(["DRAFT", "COMPLETED", "APPROVED"], name="reconciliation_status"), nullable=False, default="DRAFT", index=True)
    notes = db.Column(db.Text)
    
    bank_account = db.relationship("BankAccount", backref=db.backref("reconciliations", lazy="dynamic", cascade="all, delete-orphan"))
    reconciler = db.relationship("User", foreign_keys=[reconciled_by], backref=db.backref("reconciliations_done", lazy="dynamic"))
    approver = db.relationship("User", foreign_keys=[approved_by], backref=db.backref("reconciliations_approved", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_reconciliation_account_period", "bank_account_id", "period_start", "period_end"),
        db.CheckConstraint("period_end >= period_start", name="ck_reconciliation_period"),
    )
    
    def __repr__(self):
        return f"<BankReconciliation {self.reconciliation_number}>"


class CostCenter(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "cost_centers"
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"), index=True)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    gl_account_code = db.Column(db.String(50))
    budget_amount = db.Column(db.Numeric(15, 2), default=0)
    actual_amount = db.Column(db.Numeric(15, 2), default=0)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    parent = db.relationship("CostCenter", remote_side=[id], backref=db.backref("children", lazy="dynamic"))
    manager = db.relationship("User", foreign_keys=[manager_id], backref=db.backref("managed_cost_centers", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by], backref=db.backref("created_cost_centers", lazy="dynamic"))
    updater = db.relationship("User", foreign_keys=[updated_by], backref=db.backref("updated_cost_centers", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_cost_center_parent", "parent_id", "is_active"),
        db.CheckConstraint("budget_amount >= 0", name="ck_cost_center_budget_ge_0"),
    )
    
    def __repr__(self):
        return f"<CostCenter {self.code} {self.name}>"
    
    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.name}"
        return self.name
    
    def get_total_budget(self):
        total = float(self.budget_amount or 0)
        for child in self.children:
            total += child.get_total_budget()
        return total
    
    def get_total_actual(self):
        from sqlalchemy import func
        direct = db.session.query(func.sum(CostCenterAllocation.amount)).filter(
            CostCenterAllocation.cost_center_id == self.id
        ).scalar() or 0
        
        children_total = sum(child.get_total_actual() for child in self.children)
        return float(direct) + children_total


class CostCenterAllocation(db.Model, TimestampMixin):
    __tablename__ = "cost_center_allocations"
    
    id = db.Column(db.Integer, primary_key=True)
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = db.Column(sa_str_enum(["EXPENSE", "SALE", "SERVICE", "PAYMENT", "PURCHASE"], name="cc_source_type"), nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    percentage = db.Column(db.Numeric(5, 2), default=100)
    allocation_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    notes = db.Column(db.Text)
    
    cost_center = db.relationship("CostCenter", backref=db.backref("allocations", lazy="dynamic", cascade="all, delete-orphan"))
    
    __table_args__ = (
        db.UniqueConstraint("source_type", "source_id", "cost_center_id", name="uq_cost_center_allocation_source"),
        db.Index("ix_cost_center_alloc_date", "cost_center_id", "allocation_date"),
        db.CheckConstraint("amount >= 0", name="ck_cc_alloc_amount_ge_0"),
        db.CheckConstraint("percentage >= 0 AND percentage <= 100", name="ck_cc_alloc_percentage_range"),
    )
    
    def __repr__(self):
        return f"<CostCenterAllocation {self.source_type}:{self.source_id} -> CC:{self.cost_center_id}>"


class Project(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "projects"
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, index=True)
    planned_end_date = db.Column(db.Date)
    budget_amount = db.Column(db.Numeric(15, 2), default=0)
    estimated_cost = db.Column(db.Numeric(15, 2), default=0)
    estimated_revenue = db.Column(db.Numeric(15, 2), default=0)
    actual_cost = db.Column(db.Numeric(15, 2), default=0)
    actual_revenue = db.Column(db.Numeric(15, 2), default=0)
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"), index=True)
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    status = db.Column(sa_str_enum(["PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"], name="project_status"), nullable=False, default="PLANNED", index=True)
    completion_percentage = db.Column(db.Numeric(5, 2), default=0)
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text("true"), index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    client = db.relationship("Customer", backref=db.backref("projects", lazy="dynamic"))
    cost_center = db.relationship("CostCenter", backref=db.backref("projects", lazy="dynamic"))
    manager = db.relationship("User", foreign_keys=[manager_id], backref=db.backref("managed_projects", lazy="dynamic"))
    branch = db.relationship("Branch", backref=db.backref("projects", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by], backref=db.backref("created_projects", lazy="dynamic"))
    updater = db.relationship("User", foreign_keys=[updated_by], backref=db.backref("updated_projects", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_project_status_dates", "status", "start_date", "end_date"),
        db.CheckConstraint("budget_amount >= 0", name="ck_project_budget_ge_0"),
        db.CheckConstraint("completion_percentage >= 0 AND completion_percentage <= 100", name="ck_project_completion_range"),
    )
    
    def __repr__(self):
        return f"<Project {self.code} {self.name}>"
    
    def get_profit(self):
        return float(self.actual_revenue or 0) - float(self.actual_cost or 0)
    
    def get_profit_margin(self):
        if self.actual_revenue and self.actual_revenue > 0:
            return (self.get_profit() / float(self.actual_revenue)) * 100
        return 0


class ProjectPhase(db.Model, TimestampMixin):
    __tablename__ = "project_phases"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=1)
    start_date = db.Column(db.Date, index=True)
    end_date = db.Column(db.Date, index=True)
    planned_budget = db.Column(db.Numeric(15, 2), default=0)
    actual_cost = db.Column(db.Numeric(15, 2), default=0)
    status = db.Column(sa_str_enum(["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"], name="phase_status"), nullable=False, default="PENDING", index=True)
    completion_percentage = db.Column(db.Numeric(5, 2), default=0)
    description = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("phases", lazy="dynamic", cascade="all, delete-orphan", order_by="ProjectPhase.order"))
    
    __table_args__ = (
        db.Index("ix_project_phase_project_order", "project_id", "order"),
        db.CheckConstraint("planned_budget >= 0", name="ck_phase_budget_ge_0"),
        db.CheckConstraint("completion_percentage >= 0 AND completion_percentage <= 100", name="ck_phase_completion_range"),
    )
    
    def __repr__(self):
        return f"<ProjectPhase {self.project_id}:{self.name}>"


class ProjectCost(db.Model, TimestampMixin):
    __tablename__ = "project_costs"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey("project_phases.id", ondelete="SET NULL"), index=True)
    cost_type = db.Column(sa_str_enum(["EXPENSE", "PURCHASE", "SALARY", "SERVICE", "MATERIAL", "OTHER"], name="project_cost_type"), nullable=False, index=True)
    source_id = db.Column(db.Integer, index=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    cost_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    description = db.Column(db.Text)
    gl_batch_id = db.Column(db.Integer, db.ForeignKey("gl_batches.id"), index=True)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("costs", lazy="dynamic", cascade="all, delete-orphan"))
    phase = db.relationship("ProjectPhase", backref=db.backref("costs", lazy="dynamic"))
    gl_batch = db.relationship("GLBatch", backref=db.backref("project_costs", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_project_cost_date", "project_id", "cost_date"),
        db.CheckConstraint("amount >= 0", name="ck_project_cost_amount_ge_0"),
    )
    
    def __repr__(self):
        return f"<ProjectCost {self.project_id} {self.amount}>"


class ProjectRevenue(db.Model, TimestampMixin):
    __tablename__ = "project_revenues"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey("project_phases.id", ondelete="SET NULL"), index=True)
    revenue_type = db.Column(sa_str_enum(["SALE", "SERVICE", "INVOICE", "MILESTONE", "OTHER"], name="project_revenue_type"), nullable=False, index=True)
    source_id = db.Column(db.Integer, index=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    revenue_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    description = db.Column(db.Text)
    gl_batch_id = db.Column(db.Integer, db.ForeignKey("gl_batches.id"), index=True)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("revenues", lazy="dynamic", cascade="all, delete-orphan"))
    phase = db.relationship("ProjectPhase", backref=db.backref("revenues", lazy="dynamic"))
    gl_batch = db.relationship("GLBatch", backref=db.backref("project_revenues", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_project_revenue_date", "project_id", "revenue_date"),
        db.CheckConstraint("amount >= 0", name="ck_project_revenue_amount_ge_0"),
    )
    
    def __repr__(self):
        return f"<ProjectRevenue {self.project_id} {self.amount}>"


@event.listens_for(ProjectCost, "after_insert")
@event.listens_for(ProjectCost, "after_update")
def _project_cost_gl_batch_create(mapper, connection, target: "ProjectCost"):
    try:
        amount = float(target.amount or 0)
        if amount <= 0:
            return
        
        project = connection.execute(
            sa_text("SELECT id, code, name, cost_center_id FROM projects WHERE id = :pid"),
            {"pid": target.project_id}
        ).fetchone()
        
        if not project:
            return
        
        cost_center_id = project[3]
        if not cost_center_id:
            return
        
        cost_center = connection.execute(
            sa_text("SELECT gl_account_code FROM cost_centers WHERE id = :ccid"),
            {"ccid": cost_center_id}
        ).fetchone()
        
        if not cost_center or not cost_center[0]:
            return
        
        gl_account_code = cost_center[0]
        cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")
        
        entries = [
            (gl_account_code, amount, 0),
            (cash_account, 0, amount)
        ]
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="PROJECT_COST",
            source_id=target.id,
            purpose="EXPENSE",
            currency="ILS",
            memo=f"تكلفة مشروع: {project[2]} - {target.description or ''}",
            entries=entries,
            ref=f"PCOST-{target.id}",
            entity_type="PROJECT",
            entity_id=target.project_id
        )
        
        connection.execute(
            sa_text("UPDATE projects SET actual_cost = actual_cost + :amt WHERE id = :pid"),
            {"amt": amount, "pid": target.project_id}
        )
        
        if target.phase_id:
            connection.execute(
                sa_text("UPDATE project_phases SET actual_cost = actual_cost + :amt WHERE id = :phid"),
                {"amt": amount, "phid": target.phase_id}
            )
            
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في إنشاء GLBatch لتكلفة المشروع #{target.id}: {e}")


@event.listens_for(ProjectRevenue, "after_insert")
@event.listens_for(ProjectRevenue, "after_update")
def _project_revenue_gl_batch_create(mapper, connection, target: "ProjectRevenue"):
    try:
        amount = float(target.amount or 0)
        if amount <= 0:
            return
        
        project = connection.execute(
            sa_text("SELECT id, code, name, client_id FROM projects WHERE id = :pid"),
            {"pid": target.project_id}
        ).fetchone()
        
        if not project:
            return
        
        ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
        revenue_account = GL_ACCOUNTS.get("SALES", "4000_SALES")
        
        entries = [
            (ar_account, amount, 0),
            (revenue_account, 0, amount)
        ]
        
        _gl_upsert_batch_and_entries(
            connection,
            source_type="PROJECT_REVENUE",
            source_id=target.id,
            purpose="REVENUE",
            currency="ILS",
            memo=f"إيراد مشروع: {project[2]} - {target.description or ''}",
            entries=entries,
            ref=f"PREV-{target.id}",
            entity_type="PROJECT",
            entity_id=target.project_id
        )
        
        connection.execute(
            sa_text("UPDATE projects SET actual_revenue = actual_revenue + :amt WHERE id = :pid"),
            {"amt": amount, "pid": target.project_id}
        )
        
        if target.phase_id:
            connection.execute(
                sa_text("UPDATE project_phases SET actual_cost = actual_cost + :amt WHERE id = :phid"),
                {"amt": amount, "phid": target.phase_id}
            )
            
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ خطأ في إنشاء GLBatch لإيراد المشروع #{target.id}: {e}")


class ProjectTask(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_tasks"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey("project_phases.id", ondelete="SET NULL"), index=True)
    task_number = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False, index=True)
    description = db.Column(db.Text)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    priority = db.Column(sa_str_enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"], name="task_priority"), default="MEDIUM", nullable=False, index=True)
    status = db.Column(sa_str_enum(["TODO", "IN_PROGRESS", "BLOCKED", "REVIEW", "COMPLETED", "CANCELLED"], name="task_status"), default="TODO", nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    completed_date = db.Column(db.Date, index=True)
    estimated_hours = db.Column(db.Numeric(8, 2), default=0)
    actual_hours = db.Column(db.Numeric(8, 2), default=0)
    completion_percentage = db.Column(db.Numeric(5, 2), default=0)
    depends_on = db.Column(db.JSON)
    blocked_reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("tasks", lazy="dynamic", cascade="all, delete-orphan"))
    phase = db.relationship("ProjectPhase", backref=db.backref("tasks", lazy="dynamic"))
    assignee = db.relationship("User", foreign_keys=[assigned_to], backref=db.backref("assigned_tasks", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_project_task_project_status", "project_id", "status"),
        db.Index("ix_project_task_assigned_status", "assigned_to", "status"),
        db.CheckConstraint("estimated_hours >= 0", name="ck_task_est_hours_ge_0"),
        db.CheckConstraint("actual_hours >= 0", name="ck_task_actual_hours_ge_0"),
        db.CheckConstraint("completion_percentage >= 0 AND completion_percentage <= 100", name="ck_task_completion_range"),
    )
    
    def __repr__(self):
        return f"<ProjectTask {self.task_number} {self.name}>"
    
    @hybrid_property
    def is_overdue(self):
        if self.status in ['COMPLETED', 'CANCELLED']:
            return False
        return self.due_date < date.today() if self.due_date else False
    
    @hybrid_property
    def is_blocked_by_dependencies(self):
        if not self.depends_on:
            return False
        for task_id in (self.depends_on or []):
            dep_task = db.session.get(ProjectTask, task_id)
            if dep_task and dep_task.status != 'COMPLETED':
                return True
        return False


class ProjectResource(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_resources"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id", ondelete="CASCADE"), index=True)
    resource_type = db.Column(sa_str_enum(["EMPLOYEE", "MATERIAL", "EQUIPMENT", "SUBCONTRACTOR"], name="resource_type"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), index=True)
    resource_name = db.Column(db.String(200))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    total_cost = db.Column(db.Numeric(15, 2), nullable=False)
    allocation_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    start_date = db.Column(db.Date, index=True)
    end_date = db.Column(db.Date, index=True)
    hours_allocated = db.Column(db.Numeric(8, 2))
    hours_used = db.Column(db.Numeric(8, 2), default=0)
    status = db.Column(sa_str_enum(["PLANNED", "ALLOCATED", "IN_USE", "COMPLETED", "RELEASED"], name="resource_status"), default="PLANNED", nullable=False, index=True)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("resources", lazy="dynamic", cascade="all, delete-orphan"))
    task = db.relationship("ProjectTask", backref=db.backref("resources", lazy="dynamic"))
    employee = db.relationship("Employee", backref=db.backref("project_allocations", lazy="dynamic"))
    product = db.relationship("Product", backref=db.backref("project_usage", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_project_resource_project_type", "project_id", "resource_type"),
        db.CheckConstraint("quantity > 0", name="ck_resource_quantity_gt_0"),
        db.CheckConstraint("unit_cost >= 0", name="ck_resource_unit_cost_ge_0"),
        db.CheckConstraint("hours_allocated >= 0", name="ck_resource_hours_alloc_ge_0"),
        db.CheckConstraint("hours_used >= 0", name="ck_resource_hours_used_ge_0"),
    )
    
    def __repr__(self):
        return f"<ProjectResource {self.resource_type} {self.resource_name}>"


class ProjectMilestone(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_milestones"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey("project_phases.id", ondelete="SET NULL"), index=True)
    milestone_number = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date, nullable=False, index=True)
    completed_date = db.Column(db.Date, index=True)
    billing_amount = db.Column(db.Numeric(15, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    billing_percentage = db.Column(db.Numeric(5, 2), default=0)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), index=True)
    payment_terms_days = db.Column(db.Integer, default=30)
    status = db.Column(sa_str_enum(["PENDING", "IN_PROGRESS", "COMPLETED", "BILLED", "PAID"], name="milestone_status"), default="PENDING", nullable=False, index=True)
    completion_criteria = db.Column(db.Text)
    deliverables = db.Column(db.JSON)
    approval_required = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    approved_at = db.Column(db.DateTime, index=True)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("milestones", lazy="dynamic", cascade="all, delete-orphan"))
    phase = db.relationship("ProjectPhase", backref=db.backref("milestones", lazy="dynamic"))
    invoice = db.relationship("Invoice", backref=db.backref("milestone", uselist=False))
    approver = db.relationship("User", foreign_keys=[approved_by], backref=db.backref("approved_milestones", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_milestone_project_status", "project_id", "status"),
        db.CheckConstraint("billing_amount >= 0", name="ck_milestone_billing_ge_0"),
        db.CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_milestone_tax_rate_0_100"),
        db.CheckConstraint("tax_amount >= 0", name="ck_milestone_tax_non_negative"),
        db.CheckConstraint("billing_percentage >= 0 AND billing_percentage <= 100", name="ck_milestone_billing_pct"),
    )
    
    def __repr__(self):
        return f"<ProjectMilestone {self.milestone_number} {self.name}>"
    
    @hybrid_property
    def is_overdue(self):
        if self.status in ['COMPLETED', 'BILLED', 'PAID']:
            return False
        return self.due_date < date.today() if self.due_date else False


class ProjectRisk(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_risks"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_number = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(sa_str_enum(["FINANCIAL", "TECHNICAL", "RESOURCE", "SCHEDULE", "QUALITY", "EXTERNAL"], name="risk_category"), nullable=False, index=True)
    probability = db.Column(sa_str_enum(["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"], name="risk_probability"), nullable=False, index=True)
    impact = db.Column(sa_str_enum(["NEGLIGIBLE", "MINOR", "MODERATE", "MAJOR", "CRITICAL"], name="risk_impact"), nullable=False, index=True)
    risk_score = db.Column(db.Numeric(5, 2), nullable=False)
    status = db.Column(sa_str_enum(["IDENTIFIED", "ANALYZING", "MITIGATING", "MONITORING", "CLOSED"], name="risk_status"), default="IDENTIFIED", nullable=False, index=True)
    mitigation_plan = db.Column(db.Text)
    contingency_plan = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    identified_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    review_date = db.Column(db.Date, index=True)
    closed_date = db.Column(db.Date, index=True)
    actual_impact_cost = db.Column(db.Numeric(15, 2), default=0)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("risks", lazy="dynamic", cascade="all, delete-orphan"))
    owner = db.relationship("User", foreign_keys=[owner_id], backref=db.backref("owned_risks", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_risk_project_status", "project_id", "status"),
        db.Index("ix_risk_score", "risk_score", postgresql_ops={"risk_score": "DESC"}),
        db.CheckConstraint("risk_score >= 0 AND risk_score <= 25", name="ck_risk_score_range"),
    )
    
    def __repr__(self):
        return f"<ProjectRisk {self.risk_number} {self.title}>"
    
    @hybrid_property
    def risk_level(self):
        score = float(self.risk_score or 0)
        if score >= 15:
            return "CRITICAL"
        elif score >= 10:
            return "HIGH"
        elif score >= 5:
            return "MEDIUM"
        else:
            return "LOW"


class ProjectChangeOrder(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_change_orders"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    change_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    requested_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    reason = db.Column(db.Text)
    scope_change = db.Column(db.Text)
    cost_impact = db.Column(db.Numeric(15, 2), default=0)
    schedule_impact_days = db.Column(db.Integer, default=0)
    status = db.Column(sa_str_enum(["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "IMPLEMENTED"], name="change_order_status"), default="DRAFT", nullable=False, index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    approved_date = db.Column(db.Date, index=True)
    implemented_date = db.Column(db.Date, index=True)
    rejection_reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("change_orders", lazy="dynamic", cascade="all, delete-orphan"))
    requester = db.relationship("User", foreign_keys=[requested_by], backref=db.backref("change_requests", lazy="dynamic"))
    approver = db.relationship("User", foreign_keys=[approved_by], backref=db.backref("approved_changes", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_change_order_project_status", "project_id", "status"),
        db.CheckConstraint("cost_impact IS NOT NULL", name="ck_change_cost_not_null"),
        db.CheckConstraint("schedule_impact_days >= 0", name="ck_change_schedule_ge_0"),
    )
    
    def __repr__(self):
        return f"<ProjectChangeOrder {self.change_number} {self.title}>"


class ProjectIssue(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "project_issues"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id", ondelete="SET NULL"), index=True)
    issue_number = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(sa_str_enum(["BUG", "DELAY", "QUALITY", "RESOURCE", "SCOPE", "OTHER"], name="issue_category"), nullable=False, index=True)
    severity = db.Column(sa_str_enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"], name="issue_severity"), nullable=False, index=True)
    priority = db.Column(sa_str_enum(["LOW", "MEDIUM", "HIGH", "URGENT"], name="issue_priority"), nullable=False, index=True)
    status = db.Column(sa_str_enum(["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", "REOPENED"], name="issue_status"), default="OPEN", nullable=False, index=True)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    reported_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    resolved_date = db.Column(db.Date, index=True)
    resolution = db.Column(db.Text)
    cost_impact = db.Column(db.Numeric(15, 2), default=0)
    schedule_impact_days = db.Column(db.Integer, default=0)
    root_cause = db.Column(db.Text)
    preventive_action = db.Column(db.Text)
    
    project = db.relationship("Project", backref=db.backref("issues", lazy="dynamic", cascade="all, delete-orphan"))
    task = db.relationship("ProjectTask", backref=db.backref("issues", lazy="dynamic"))
    reporter = db.relationship("User", foreign_keys=[reported_by], backref=db.backref("reported_issues", lazy="dynamic"))
    assignee = db.relationship("User", foreign_keys=[assigned_to], backref=db.backref("assigned_issues", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_issue_project_status", "project_id", "status"),
        db.Index("ix_issue_severity_priority", "severity", "priority"),
    )
    
    def __repr__(self):
        return f"<ProjectIssue {self.issue_number} {self.title}>"


class ResourceTimeLog(db.Model, TimestampMixin):
    __tablename__ = "resource_time_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey("project_tasks.id", ondelete="CASCADE"), index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("project_resources.id", ondelete="CASCADE"), index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    hours_worked = db.Column(db.Numeric(8, 2), nullable=False)
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.Text)
    approved = db.Column(db.Boolean, default=False, index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    approved_at = db.Column(db.DateTime)
    
    project = db.relationship("Project", backref=db.backref("time_logs", lazy="dynamic"))
    task = db.relationship("ProjectTask", backref=db.backref("time_logs", lazy="dynamic"))
    resource = db.relationship("ProjectResource", backref=db.backref("time_logs", lazy="dynamic"))
    employee = db.relationship("Employee", backref=db.backref("time_logs", lazy="dynamic"))
    approver = db.relationship("User", foreign_keys=[approved_by], backref=db.backref("approved_time_logs", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_time_log_project_date", "project_id", "log_date"),
        db.Index("ix_time_log_employee_date", "employee_id", "log_date"),
        db.CheckConstraint("hours_worked > 0 AND hours_worked <= 24", name="ck_hours_worked_range"),
        db.CheckConstraint("hourly_rate >= 0", name="ck_hourly_rate_ge_0"),
    )
    
    def __repr__(self):
        return f"<ResourceTimeLog {self.log_date} {self.hours_worked}h>"


@event.listens_for(ResourceTimeLog, "after_insert")
@event.listens_for(ResourceTimeLog, "after_update")
def _time_log_update_task(mapper, connection, target: "ResourceTimeLog"):
    try:
        if target.task_id:
            connection.execute(
                sa_text("UPDATE project_tasks SET actual_hours = actual_hours + :hrs WHERE id = :tid"),
                {"hrs": float(target.hours_worked or 0), "tid": target.task_id}
            )
        
        if target.resource_id:
            connection.execute(
                sa_text("UPDATE project_resources SET hours_used = hours_used + :hrs WHERE id = :rid"),
                {"hrs": float(target.hours_worked or 0), "rid": target.resource_id}
            )
            
        if target.approved and target.total_cost:
            cost_entry = connection.execute(
                sa_text("SELECT id FROM project_costs WHERE source_id = :tl_id AND cost_type = 'SALARY'"),
                {"tl_id": target.id}
            ).fetchone()
            
            if not cost_entry:
                connection.execute(
                    sa_text("""INSERT INTO project_costs 
                            (project_id, cost_type, source_id, amount, cost_date, description) 
                            VALUES (:pid, 'SALARY', :sid, :amt, :dt, :desc)"""),
                    {
                        "pid": target.project_id,
                        "sid": target.id,
                        "amt": float(target.total_cost),
                        "dt": target.log_date,
                        "desc": f"تكلفة وقت موظف - {target.hours_worked} ساعة"
                    }
                )
    except Exception:
        pass


@event.listens_for(ProjectMilestone, "after_update")
def _milestone_auto_invoice(mapper, connection, target: "ProjectMilestone"):
    try:
        if target.status == 'COMPLETED' and not target.invoice_id and float(target.billing_amount or 0) > 0:
            from datetime import datetime, timedelta
            
            invoice_date = target.completed_date or date.today()
            due_date = invoice_date + timedelta(days=target.payment_terms_days or 30)
            
            project = connection.execute(
                sa_text("SELECT id, code, name, client_id FROM projects WHERE id = :pid"),
                {"pid": target.project_id}
            ).fetchone()
            
            if project and project[3]:
                invoice_number = f"MS-{target.milestone_number}"
                
                billing_amount = float(target.billing_amount or 0)
                tax_rate = float(target.tax_rate or 0)
                tax_amount = float(target.tax_amount or 0)
                
                if tax_amount <= 0 and tax_rate > 0:
                    tax_amount = billing_amount * (tax_rate / 100.0)
                
                total_with_tax = billing_amount + tax_amount
                
                connection.execute(
                    sa_text("""INSERT INTO invoices 
                            (invoice_number, invoice_date, due_date, customer_id, source, kind, 
                             currency, tax_amount, total_amount, notes) 
                            VALUES (:num, :inv_dt, :due_dt, :cust_id, 'MANUAL', 'INVOICE', 
                                    'ILS', :tax, :amt, :notes)"""),
                    {
                        "num": invoice_number,
                        "inv_dt": invoice_date,
                        "due_dt": due_date,
                        "cust_id": project[3],
                        "tax": tax_amount,
                        "amt": total_with_tax,
                        "notes": f"فاتورة محطة: {target.name} - مشروع: {project[2]}"
                    }
                )
                
                new_invoice_id = connection.execute(
                    sa_text("SELECT id FROM invoices WHERE invoice_number = :num"),
                    {"num": invoice_number}
                ).scalar()
                
                if new_invoice_id:
                    connection.execute(
                        sa_text("UPDATE project_milestones SET invoice_id = :inv_id, status = 'BILLED' WHERE id = :mid"),
                        {"inv_id": new_invoice_id, "mid": target.id}
                    )
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"⚠️ فشل إنشاء فاتورة تلقائية للمحطة #{target.id}: {e}")


@event.listens_for(ProjectChangeOrder, "after_update")
def _change_order_update_budget(mapper, connection, target: "ProjectChangeOrder"):
    try:
        if target.status == 'APPROVED' and target.cost_impact:
            connection.execute(
                sa_text("UPDATE projects SET budget_amount = budget_amount + :amt WHERE id = :pid"),
                {"amt": float(target.cost_impact), "pid": target.project_id}
            )
            
            if target.schedule_impact_days:
                connection.execute(
                    sa_text("UPDATE projects SET end_date = date(end_date, '+' || :days || ' days') WHERE id = :pid"),
                    {"days": target.schedule_impact_days, "pid": target.project_id}
                )
    except Exception:
        pass


@event.listens_for(ProjectResource, "after_insert")
def _resource_create_cost(mapper, connection, target: "ProjectResource"):
    try:
        if target.status == 'ALLOCATED' and float(target.total_cost or 0) > 0:
            connection.execute(
                sa_text("""INSERT INTO project_costs 
                        (project_id, cost_type, source_id, amount, cost_date, description) 
                        VALUES (:pid, 'OTHER', :sid, :amt, :dt, :desc)"""),
                {
                    "pid": target.project_id,
                    "sid": target.id,
                    "amt": float(target.total_cost),
                    "dt": target.allocation_date,
                    "desc": f"تخصيص مورد: {target.resource_type} - {target.resource_name}"
                }
            )
    except Exception:
        pass







class CostCenterAlert(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'cost_center_alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    alert_type = db.Column(sa_str_enum(['BUDGET_EXCEEDED', 'BUDGET_WARNING', 'NO_ACTIVITY', 'UNUSUAL_SPIKE'], name='cc_alert_type'), nullable=False)
    
    threshold_type = db.Column(sa_str_enum(['PERCENTAGE', 'AMOUNT'], name='cc_threshold_type'), nullable=False, server_default=sa_text("'PERCENTAGE'"))
    threshold_value = db.Column(db.Numeric(15, 2), nullable=False)
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'))
    
    notify_manager = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'))
    notify_emails = db.Column(db.JSON)
    notify_users = db.Column(db.JSON)
    
    last_triggered_at = db.Column(db.DateTime)
    trigger_count = db.Column(db.Integer, nullable=False, server_default=sa_text('0'))
    
    cost_center = db.relationship('CostCenter', backref=db.backref('alerts', lazy='dynamic', cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.Index('ix_cc_alert_center_active', 'cost_center_id', 'is_active'),
    )

class CostCenterAlertLog(db.Model, TimestampMixin):
    __tablename__ = 'cost_center_alert_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('cost_center_alerts.id', ondelete='CASCADE'), index=True)
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    
    triggered_at = db.Column(db.DateTime, nullable=False, server_default=sa_text('CURRENT_TIMESTAMP'))
    trigger_value = db.Column(db.Numeric(15, 2))
    threshold_value = db.Column(db.Numeric(15, 2))
    
    message = db.Column(db.Text)
    severity = db.Column(sa_str_enum(['INFO', 'WARNING', 'CRITICAL'], name='cc_alert_severity'))
    
    notified_users = db.Column(db.JSON)
    notification_sent = db.Column(db.Boolean, nullable=False, server_default=sa_text('false'))
    
    alert = db.relationship('CostCenterAlert', backref=db.backref('logs', lazy='dynamic', cascade='all, delete-orphan'))
    cost_center = db.relationship('CostCenter', backref=db.backref('alert_logs', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_cc_alert_log_date', 'triggered_at'),
    )

class CostAllocationRule(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'cost_allocation_rules'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    
    source_cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    
    allocation_method = db.Column(sa_str_enum(['PERCENTAGE', 'RATIO', 'EQUAL', 'EMPLOYEE_COUNT', 'REVENUE_BASED', 'AREA_BASED', 'CUSTOM'], name='allocation_method'), nullable=False)
    
    frequency = db.Column(sa_str_enum(['MANUAL', 'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY'], name='allocation_frequency'))
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'))
    auto_execute = db.Column(db.Boolean, nullable=False, server_default=sa_text('false'))
    
    last_executed_at = db.Column(db.DateTime)
    next_execution_at = db.Column(db.DateTime)
    
    source_cost_center = db.relationship('CostCenter', backref=db.backref('allocation_rules_source', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_allocation_rule_active', 'is_active'),
    )

class CostAllocationLine(db.Model):
    __tablename__ = 'cost_allocation_lines'
    
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('cost_allocation_rules.id', ondelete='CASCADE'), nullable=False)
    
    target_cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), nullable=False, index=True)
    
    percentage = db.Column(db.Numeric(5, 2))
    fixed_amount = db.Column(db.Numeric(15, 2))
    
    allocation_driver = db.Column(db.String(100))
    driver_value = db.Column(db.Numeric(15, 2))
    
    notes = db.Column(db.Text)
    
    rule = db.relationship('CostAllocationRule', backref=db.backref('lines', lazy='dynamic', cascade='all, delete-orphan'))
    target_cost_center = db.relationship('CostCenter', backref=db.backref('allocation_lines_target', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_allocation_line_rule', 'rule_id'),
        db.CheckConstraint('percentage >= 0 AND percentage <= 100', name='ck_allocation_line_percentage'),
    )

class CostAllocationExecution(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'cost_allocation_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('cost_allocation_rules.id'), index=True)
    
    execution_date = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), nullable=False)
    
    status = db.Column(sa_str_enum(['DRAFT', 'EXECUTED', 'REVERSED'], name='allocation_exec_status'), nullable=False, server_default=sa_text("'DRAFT'"))
    
    gl_batch_id = db.Column(db.Integer, db.ForeignKey('gl_batches.id'), index=True)
    
    notes = db.Column(db.Text)
    
    rule = db.relationship('CostAllocationRule', backref=db.backref('executions', lazy='dynamic'))
    gl_batch = db.relationship('GLBatch', backref=db.backref('cost_allocation_executions', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_allocation_exec_date', 'execution_date'),
    )

class CostAllocationExecutionLine(db.Model):
    __tablename__ = 'cost_allocation_execution_lines'
    
    id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey('cost_allocation_executions.id', ondelete='CASCADE'), nullable=False, index=True)
    
    source_cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    target_cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    percentage = db.Column(db.Numeric(5, 2))
    
    gl_batch_id = db.Column(db.Integer, db.ForeignKey('gl_batches.id'))
    
    execution = db.relationship('CostAllocationExecution', backref=db.backref('lines', lazy='dynamic', cascade='all, delete-orphan'))
    source_cost_center = db.relationship('CostCenter', foreign_keys=[source_cost_center_id], backref=db.backref('allocation_exec_lines_source', lazy='dynamic'))
    target_cost_center = db.relationship('CostCenter', foreign_keys=[target_cost_center_id], backref=db.backref('allocation_exec_lines_target', lazy='dynamic'))
    gl_batch = db.relationship('GLBatch', backref=db.backref('cost_allocation_execution_lines', lazy='dynamic'))

class EngineeringTeam(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'engineering_teams'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    
    team_leader_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    
    specialty = db.Column(sa_str_enum(['MECHANICAL', 'ELECTRICAL', 'CIVIL', 'AUTOMOTIVE', 'SOFTWARE', 'MAINTENANCE', 'HVAC', 'PLUMBING', 'GENERAL'], name='eng_specialty'), nullable=False)
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), index=True)
    
    max_concurrent_tasks = db.Column(db.Integer, nullable=False, server_default=sa_text('5'))
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'))
    
    description = db.Column(db.Text)
    equipment_inventory = db.Column(db.JSON)
    
    team_leader = db.relationship('Employee', foreign_keys=[team_leader_id], backref=db.backref('led_teams', lazy='dynamic'))
    cost_center = db.relationship('CostCenter', backref=db.backref('engineering_teams', lazy='dynamic'))
    branch = db.relationship('Branch', backref=db.backref('engineering_teams', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_eng_team_active', 'is_active'),
        db.Index('ix_eng_team_specialty', 'specialty'),
    )
    
    def __repr__(self):
        return f"<EngineeringTeam {self.code} - {self.name}>"


class EngineeringTeamMember(db.Model, TimestampMixin):
    __tablename__ = 'engineering_team_members'
    
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('engineering_teams.id', ondelete='CASCADE'), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    
    role = db.Column(sa_str_enum(['LEADER', 'SENIOR', 'ENGINEER', 'JUNIOR', 'TECHNICIAN', 'APPRENTICE'], name='team_member_role'), nullable=False)
    
    join_date = db.Column(db.Date, nullable=False, server_default=sa_text('CURRENT_DATE'))
    leave_date = db.Column(db.Date)
    
    hourly_rate = db.Column(db.Numeric(10, 2))
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'))
    
    team = db.relationship('EngineeringTeam', backref=db.backref('members', lazy='dynamic', cascade='all, delete-orphan'))
    employee = db.relationship('Employee', backref=db.backref('team_memberships', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('team_id', 'employee_id', name='uq_team_member'),
        db.Index('ix_team_member_active', 'is_active'),
    )
    
    def __repr__(self):
        return f"<EngineeringTeamMember Team#{self.team_id} Employee#{self.employee_id}>"


class EngineeringSkill(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'engineering_skills'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    name_ar = db.Column(db.String(200))
    
    category = db.Column(db.String(100))
    
    description = db.Column(db.Text)
    
    is_certification_required = db.Column(db.Boolean, nullable=False, server_default=sa_text('false'))
    certification_validity_months = db.Column(db.Integer)
    
    is_active = db.Column(db.Boolean, nullable=False, server_default=sa_text('true'), index=True)
    
    __table_args__ = (
        db.Index('ix_skill_category', 'category'),
    )
    
    def __repr__(self):
        return f"<EngineeringSkill {self.code} - {self.name}>"


class EmployeeSkill(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'employee_skills'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('engineering_skills.id'), nullable=False, index=True)
    
    proficiency_level = db.Column(sa_str_enum(['BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT'], name='proficiency_level'), nullable=False)
    
    years_experience = db.Column(db.Integer, nullable=False, server_default=sa_text('0'))
    
    certification_number = db.Column(db.String(100))
    certification_authority = db.Column(db.String(200))
    certification_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verification_date = db.Column(db.Date)
    
    notes = db.Column(db.Text)
    
    employee = db.relationship('Employee', backref=db.backref('skills', lazy='dynamic', cascade='all, delete-orphan'))
    skill = db.relationship('EngineeringSkill', backref=db.backref('employee_skills', lazy='dynamic'))
    verifier = db.relationship('User', backref=db.backref('verified_skills', lazy='dynamic'))
    
    __table_args__ = (
        db.UniqueConstraint('employee_id', 'skill_id', name='uq_employee_skill'),
        db.Index('ix_employee_skill_expiry', 'expiry_date'),
    )
    
    def __repr__(self):
        return f"<EmployeeSkill Employee#{self.employee_id} Skill#{self.skill_id}>"


class EngineeringTaskStatus(str, enum.Enum):
    """حالات مهمة الهندسة — يجب أن تطابق قيم عمود eng_task_status."""
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DEFERRED = "DEFERRED"

    @property
    def label(self):
        return {
            "PENDING": "قيد الانتظار",
            "ASSIGNED": "تم التعيين",
            "IN_PROGRESS": "قيد التنفيذ",
            "ON_HOLD": "معلق",
            "REVIEW": "مراجعة",
            "COMPLETED": "مكتمل",
            "CANCELLED": "ملغي",
            "DEFERRED": "مؤجل",
        }[self.value]


class EngineeringTask(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'engineering_tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    task_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    
    task_type = db.Column(
        sa_str_enum([
            'DESIGN', 'INSPECTION', 'MAINTENANCE', 'INSTALLATION', 'REPAIR',
            'CONSULTATION', 'TESTING', 'CALIBRATION', 'TRAINING', 'OTHER'
        ], name='eng_task_type'),
        nullable=False
    )
    
    priority = db.Column(
        sa_str_enum(['LOW', 'MEDIUM', 'HIGH', 'URGENT', 'CRITICAL'], name='eng_task_priority'),
        nullable=False,
        server_default=sa_text("'MEDIUM'"),
    )
    
    status = db.Column(
        sa_str_enum([
            'PENDING', 'ASSIGNED', 'IN_PROGRESS', 'ON_HOLD',
            'REVIEW', 'COMPLETED', 'CANCELLED', 'DEFERRED'
        ], name='eng_task_status'),
        nullable=False,
        server_default=sa_text("'PENDING'"),
    )
    
    assigned_team_id = db.Column(db.Integer, db.ForeignKey('engineering_teams.id'), index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    
    required_skills = db.Column(db.JSON)
    
    estimated_hours = db.Column(db.Numeric(8, 2))
    actual_hours = db.Column(db.Numeric(8, 2), nullable=False, server_default=sa_text('0'))
    
    estimated_cost = db.Column(db.Numeric(15, 2))
    actual_cost = db.Column(db.Numeric(15, 2), nullable=False, server_default=sa_text('0'))
    
    scheduled_start = db.Column(db.DateTime, index=True)
    scheduled_end = db.Column(db.DateTime, index=True)
    actual_start = db.Column(db.DateTime)
    actual_end = db.Column(db.DateTime)
    
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), index=True)
    location = db.Column(db.String(300))
    
    equipment_needed = db.Column(db.Text)
    tools_needed = db.Column(db.Text)
    materials_needed = db.Column(db.JSON)
    
    safety_requirements = db.Column(db.Text)
    quality_standards = db.Column(db.Text)
    
    completion_notes = db.Column(db.Text)
    completion_photos = db.Column(db.JSON)
    
    customer_satisfaction_rating = db.Column(db.Integer)
    customer_feedback = db.Column(db.Text)
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), index=True)
    service_request_id = db.Column(db.Integer, db.ForeignKey('service_requests.id'), index=True)
    
    parent_task_id = db.Column(db.Integer, db.ForeignKey('engineering_tasks.id'), index=True)
    
    gl_batch_id = db.Column(db.Integer, db.ForeignKey('gl_batches.id'))
    
    assigned_team = db.relationship('EngineeringTeam', backref=db.backref('tasks', lazy='dynamic'))
    assigned_to = db.relationship('Employee', foreign_keys=[assigned_to_id], backref=db.backref('assigned_tasks', lazy='dynamic'))
    customer = db.relationship('Customer', backref=db.backref('engineering_tasks', lazy='dynamic'))
    cost_center = db.relationship('CostCenter', backref=db.backref('engineering_tasks', lazy='dynamic'))
    project = db.relationship('Project', backref=db.backref('engineering_tasks', lazy='dynamic'))
    service_request = db.relationship('ServiceRequest', backref=db.backref('engineering_tasks', lazy='dynamic'))
    parent_task = db.relationship('EngineeringTask', remote_side=[id], backref=db.backref('subtasks', lazy='dynamic'))
    gl_batch = db.relationship('GLBatch', backref=db.backref('engineering_tasks', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_eng_task_status', 'status'),
        db.Index('ix_eng_task_priority', 'priority'),
        db.Index('ix_eng_task_assigned', 'assigned_to_id', 'status'),
        db.Index('ix_eng_task_scheduled', 'scheduled_start', 'scheduled_end'),
        db.CheckConstraint('customer_satisfaction_rating >= 1 AND customer_satisfaction_rating <= 5', name='ck_task_rating_range'),
    )
    
    def __repr__(self):
        return f"<EngineeringTask {self.task_number} - {self.title}>"


class EngineeringTimesheet(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = 'engineering_timesheets'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('engineering_tasks.id'))
    
    work_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    
    break_duration_minutes = db.Column(db.Integer, nullable=False, server_default=sa_text('0'))
    actual_work_hours = db.Column(db.Numeric(5, 2), nullable=False)
    
    billable_hours = db.Column(db.Numeric(5, 2))
    hourly_rate = db.Column(db.Numeric(10, 2))
    total_cost = db.Column(db.Numeric(15, 2))
    
    productivity_rating = db.Column(sa_str_enum(['POOR', 'FAIR', 'GOOD', 'VERY_GOOD', 'EXCELLENT'], name='productivity_rating'))
    
    work_description = db.Column(db.Text)
    issues_encountered = db.Column(db.Text)
    materials_used = db.Column(db.JSON)
    
    location = db.Column(db.String(300))
    
    status = db.Column(sa_str_enum(['DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED'], name='timesheet_status'), nullable=False, server_default=sa_text("'DRAFT'"))
    
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approval_date = db.Column(db.DateTime)
    approval_notes = db.Column(db.Text)
    
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_centers.id'), index=True)
    gl_batch_id = db.Column(db.Integer, db.ForeignKey('gl_batches.id'))
    
    employee = db.relationship('Employee', backref=db.backref('timesheets', lazy='dynamic', cascade='all, delete-orphan'))
    task = db.relationship('EngineeringTask', backref=db.backref('timesheets', lazy='dynamic'))
    approver = db.relationship('User', backref=db.backref('approved_timesheets', lazy='dynamic'))
    cost_center = db.relationship('CostCenter', backref=db.backref('engineering_timesheets', lazy='dynamic'))
    gl_batch = db.relationship('GLBatch', backref=db.backref('engineering_timesheets', lazy='dynamic'))
    
    __table_args__ = (
        db.Index('ix_timesheet_employee_date', 'employee_id', 'work_date'),     
        db.Index('ix_timesheet_task', 'task_id'),
        db.Index('ix_timesheet_status', 'status'),
        db.CheckConstraint('actual_work_hours > 0', name='ck_timesheet_hours_positive'),                                                                        
        db.CheckConstraint('break_duration_minutes >= 0', name='ck_timesheet_break_positive'),                                                                  
    )
    
    def __repr__(self):
        return f"<EngineeringTimesheet Employee#{self.employee_id} {self.work_date}>"


@event.listens_for(Sale, "after_insert")
@event.listens_for(Sale, "after_update")
def _auto_allocate_sale_to_cost_center(mapper, connection, target: "Sale"):
    try:
        if not target.cost_center_id or not target.total_amount:
            return
        
        if float(target.total_amount or 0) <= 0:
            return
        
        existing = connection.execute(
            sa_text("""SELECT id FROM cost_center_allocations 
                    WHERE source_type = 'SALE' AND source_id = :sid AND cost_center_id = :ccid"""),
            {"sid": target.id, "ccid": target.cost_center_id}
        ).fetchone()
        
        if existing:
            connection.execute(
                sa_text("""UPDATE cost_center_allocations 
                        SET amount = :amt, allocation_date = :dt 
                        WHERE id = :aid"""),
                {
                    "amt": float(target.total_amount),
                    "dt": target.sale_date.date() if hasattr(target.sale_date, 'date') else target.sale_date,
                    "aid": existing[0]
                }
            )
        else:
            connection.execute(
                sa_text("""INSERT INTO cost_center_allocations 
                        (cost_center_id, source_type, source_id, amount, percentage, allocation_date, notes)
                        VALUES (:ccid, 'SALE', :sid, :amt, 100, :dt, :notes)"""),
                {
                    "ccid": target.cost_center_id,
                    "sid": target.id,
                    "amt": float(target.total_amount),
                    "dt": target.sale_date.date() if hasattr(target.sale_date, 'date') else target.sale_date,
                    "notes": f"توزيع تلقائي - بيع #{target.sale_number or target.id}"
                }
            )
    except Exception:
        pass


@event.listens_for(Sale, "before_delete")
def _auto_remove_sale_cost_center_allocation(mapper, connection, target: "Sale"):
    try:
        if target.cost_center_id:
            connection.execute(
                sa_text("""DELETE FROM cost_center_allocations 
                        WHERE source_type = 'SALE' AND source_id = :sid"""),
                {"sid": target.id}
            )
    except Exception:
        pass


@event.listens_for(ServiceRequest, "after_insert")
@event.listens_for(ServiceRequest, "after_update")
def _auto_allocate_service_to_cost_center(mapper, connection, target: "ServiceRequest"):
    try:
        if not target.cost_center_id or not target.total_amount:
            return
        
        if float(target.total_amount or 0) <= 0:
            return
        
        existing = connection.execute(
            sa_text("""SELECT id FROM cost_center_allocations 
                    WHERE source_type = 'SERVICE' AND source_id = :sid AND cost_center_id = :ccid"""),
            {"sid": target.id, "ccid": target.cost_center_id}
        ).fetchone()
        
        alloc_date = target.completed_at or target.received_at or date.today()
        if hasattr(alloc_date, 'date'):
            alloc_date = alloc_date.date()
        
        if existing:
            connection.execute(
                sa_text("""UPDATE cost_center_allocations 
                        SET amount = :amt, allocation_date = :dt 
                        WHERE id = :aid"""),
                {
                    "amt": float(target.total_amount),
                    "dt": alloc_date,
                    "aid": existing[0]
                }
            )
        else:
            connection.execute(
                sa_text("""INSERT INTO cost_center_allocations 
                        (cost_center_id, source_type, source_id, amount, percentage, allocation_date, notes)
                        VALUES (:ccid, 'SERVICE', :sid, :amt, 100, :dt, :notes)"""),
                {
                    "ccid": target.cost_center_id,
                    "sid": target.id,
                    "amt": float(target.total_amount),
                    "dt": alloc_date,
                    "notes": f"توزيع تلقائي - صيانة #{target.service_number or target.id}"
                }
            )
    except Exception:
        pass


@event.listens_for(ServiceRequest, "before_delete")
def _auto_remove_service_cost_center_allocation(mapper, connection, target: "ServiceRequest"):
    try:
        if target.cost_center_id:
            connection.execute(
                sa_text("""DELETE FROM cost_center_allocations 
                        WHERE source_type = 'SERVICE' AND source_id = :sid"""),
                {"sid": target.id}
            )
    except Exception:
        pass


@event.listens_for(Expense, "after_insert")
@event.listens_for(Expense, "after_update")
def _auto_allocate_expense_to_cost_center(mapper, connection, target: "Expense"):
    try:
        cost_center_id = getattr(target, 'cost_center_id', None)
        if not cost_center_id or not target.amount:
            return
        
        if float(target.amount or 0) <= 0:
            return
        
        existing = connection.execute(
            sa_text("""SELECT id FROM cost_center_allocations 
                    WHERE source_type = 'EXPENSE' AND source_id = :eid AND cost_center_id = :ccid"""),
            {"eid": target.id, "ccid": cost_center_id}
        ).fetchone()
        
        alloc_date = target.date
        if hasattr(alloc_date, 'date'):
            alloc_date = alloc_date.date()
        
        if existing:
            connection.execute(
                sa_text("""UPDATE cost_center_allocations 
                        SET amount = :amt, allocation_date = :dt 
                        WHERE id = :aid"""),
                {
                    "amt": float(target.amount),
                    "dt": alloc_date,
                    "aid": existing[0]
                }
            )
        else:
            connection.execute(
                sa_text("""INSERT INTO cost_center_allocations 
                        (cost_center_id, source_type, source_id, amount, percentage, allocation_date, notes)
                        VALUES (:ccid, 'EXPENSE', :eid, :amt, 100, :dt, :notes)"""),
                {
                    "ccid": cost_center_id,
                    "eid": target.id,
                    "amt": float(target.amount),
                    "dt": alloc_date,
                    "notes": f"توزيع تلقائي - مصروف #{target.id}"
                }
            )
    except Exception:
        pass


@event.listens_for(Expense, "before_delete")
def _auto_remove_expense_cost_center_allocation(mapper, connection, target: "Expense"):
    try:
        cost_center_id = getattr(target, 'cost_center_id', None)
        if cost_center_id:
            connection.execute(
                sa_text("""DELETE FROM cost_center_allocations 
                        WHERE source_type = 'EXPENSE' AND source_id = :eid"""),
                {"eid": target.id}
            )
    except Exception:
        pass


class WorkflowDefinition(db.Model, TimestampMixin, AuditMixin):
    __tablename__ = "workflow_definitions"
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    workflow_name = db.Column(db.String(200), nullable=False)
    workflow_name_ar = db.Column(db.String(200))
    description = db.Column(db.Text)
    
    workflow_type = db.Column(
        sa_str_enum(['APPROVAL', 'REVIEW', 'NOTIFICATION', 'CUSTOM'], name='workflow_type'),
        nullable=False,
        default='APPROVAL',
        index=True
    )
    
    entity_type = db.Column(
        sa_str_enum(['MILESTONE', 'CHANGE_ORDER', 'RISK', 'TASK', 'RESOURCE', 'EXPENSE', 'PAYMENT'], name='workflow_entity_type'),
        nullable=False,
        index=True
    )
    
    steps_definition = db.Column(db.JSON, nullable=False)
    
    auto_start = db.Column(db.Boolean, default=False, nullable=False)
    auto_start_condition = db.Column(db.JSON)
    
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    version = db.Column(db.Integer, default=1, nullable=False)
    
    timeout_hours = db.Column(db.Integer)
    escalation_rules = db.Column(db.JSON)
    
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    creator = db.relationship("User", foreign_keys=[created_by], backref=db.backref("created_workflows", lazy="dynamic"))
    updater = db.relationship("User", foreign_keys=[updated_by], backref=db.backref("updated_workflows", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_workflow_def_entity_active", "entity_type", "is_active"),
    )
    
    def __repr__(self):
        return f"<WorkflowDefinition {self.workflow_code}>"


class WorkflowInstance(db.Model, TimestampMixin):
    __tablename__ = "workflow_instances"
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_definition_id = db.Column(db.Integer, db.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False, index=True)
    instance_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    
    entity_type = db.Column(db.String(50), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    
    status = db.Column(
        sa_str_enum(['INITIATED', 'IN_PROGRESS', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'COMPLETED', 'CANCELLED', 'TIMEOUT'], name='workflow_instance_status'),
        nullable=False,
        default='INITIATED',
        index=True
    )
    
    current_step = db.Column(db.Integer, default=1, nullable=False)
    total_steps = db.Column(db.Integer, nullable=False)
    
    started_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    completed_at = db.Column(db.DateTime, index=True)
    completed_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    
    cancelled_at = db.Column(db.DateTime, index=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    cancellation_reason = db.Column(db.Text)
    
    due_date = db.Column(db.DateTime, index=True)
    
    context_data = db.Column(db.JSON)
    
    workflow_definition = db.relationship("WorkflowDefinition", backref=db.backref("instances", lazy="dynamic"))
    starter = db.relationship("User", foreign_keys=[started_by], backref=db.backref("started_workflow_instances", lazy="dynamic"))
    completer = db.relationship("User", foreign_keys=[completed_by], backref=db.backref("completed_workflow_instances", lazy="dynamic"))
    canceller = db.relationship("User", foreign_keys=[cancelled_by], backref=db.backref("cancelled_workflow_instances", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_workflow_inst_entity", "entity_type", "entity_id"),
        db.Index("ix_workflow_inst_status_date", "status", "started_at"),
    )
    
    def __repr__(self):
        return f"<WorkflowInstance {self.instance_code}>"
    
    @hybrid_property
    def is_overdue(self):
        if self.status in ['COMPLETED', 'CANCELLED', 'APPROVED', 'REJECTED']:
            return False
        if self.due_date:
            return datetime.now(timezone.utc) > self.due_date
        return False
    
    @hybrid_property
    def progress_percentage(self):
        if self.total_steps == 0:
            return 0
        return (self.current_step / self.total_steps) * 100


class WorkflowAction(db.Model, TimestampMixin):
    __tablename__ = "workflow_actions"
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_instance_id = db.Column(db.Integer, db.ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    
    step_number = db.Column(db.Integer, nullable=False)
    step_name = db.Column(db.String(200), nullable=False)
    
    action_type = db.Column(
        sa_str_enum(['APPROVE', 'REJECT', 'REVIEW', 'COMMENT', 'DELEGATE', 'REQUEST_INFO', 'PROVIDE_INFO'], name='workflow_action_type'),
        nullable=False,
        index=True
    )
    
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action_date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    decision = db.Column(db.String(50))
    comments = db.Column(db.Text)
    
    attachments = db.Column(db.JSON)
    
    delegated_to = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    delegated_at = db.Column(db.DateTime)
    
    duration_hours = db.Column(db.Numeric(8, 2))
    
    workflow_instance = db.relationship("WorkflowInstance", backref=db.backref("actions", lazy="dynamic", cascade="all, delete-orphan", order_by="WorkflowAction.action_date"))
    actor = db.relationship("User", foreign_keys=[actor_id], backref=db.backref("workflow_actions", lazy="dynamic"))
    delegate = db.relationship("User", foreign_keys=[delegated_to], backref=db.backref("delegated_workflow_actions", lazy="dynamic"))
    
    __table_args__ = (
        db.Index("ix_workflow_action_instance_step", "workflow_instance_id", "step_number"),
        db.Index("ix_workflow_action_actor_date", "actor_id", "action_date"),
    )
    
    def __repr__(self):
        return f"<WorkflowAction {self.action_type} by User#{self.actor_id}>"


@event.listens_for(ProjectMilestone, "after_insert")
def _auto_start_milestone_workflow(mapper, connection, target: "ProjectMilestone"):
    try:
        if not target.approval_required:
            return
        
        workflow_def = connection.execute(
            sa_text("""SELECT id FROM workflow_definitions 
                    WHERE workflow_code = 'MILESTONE_APPROVAL' 
                    AND entity_type = 'MILESTONE' 
                    AND is_active = 1""")
        ).fetchone()
        
        if not workflow_def:
            return
        
        from services.workflow_engine import WorkflowEngine
        
        instance_code = f"MILESTONE_APPROVAL-MILESTONE-{target.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        connection.execute(
            sa_text("""INSERT INTO workflow_instances 
                    (workflow_definition_id, instance_code, entity_type, entity_id, 
                     status, current_step, total_steps, started_by, started_at)
                    VALUES (:wf_id, :code, 'MILESTONE', :eid, 'IN_PROGRESS', 1, 
                            (SELECT json_array_length(steps_definition) FROM workflow_definitions WHERE id = :wf_id),
                            :user_id, :started)"""),
            {
                "wf_id": workflow_def[0],
                "code": instance_code,
                "eid": target.id,
                "user_id": target.created_by or 1,
                "started": datetime.now(timezone.utc)
            }
        )
    except Exception:
        pass


@event.listens_for(ProjectChangeOrder, "after_insert")
def _auto_start_change_order_workflow(mapper, connection, target: "ProjectChangeOrder"):
    try:
        if target.status not in ['SUBMITTED', 'UNDER_REVIEW']:
            return
        
        workflow_def = connection.execute(
            sa_text("""SELECT id FROM workflow_definitions 
                    WHERE workflow_code = 'CHANGE_ORDER_APPROVAL' 
                    AND entity_type = 'CHANGE_ORDER' 
                    AND is_active = 1""")
        ).fetchone()
        
        if not workflow_def:
            return
        
        instance_code = f"CHANGE_ORDER_APPROVAL-CHANGE_ORDER-{target.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        connection.execute(
            sa_text("""INSERT INTO workflow_instances 
                    (workflow_definition_id, instance_code, entity_type, entity_id, 
                     status, current_step, total_steps, started_by, started_at)
                    VALUES (:wf_id, :code, 'CHANGE_ORDER', :eid, 'IN_PROGRESS', 1, 
                            (SELECT json_array_length(steps_definition) FROM workflow_definitions WHERE id = :wf_id),
                            :user_id, :started)"""),
            {
                "wf_id": workflow_def[0],
                "code": instance_code,
                "eid": target.id,
                "user_id": target.requested_by or 1,
                "started": datetime.now(timezone.utc)
            }
        )
    except Exception:
        pass


def _get_customer_ids_from_payment(payment, connection=None):
    customer_ids = set()
    
    if payment.customer_id:
        customer_ids.add(payment.customer_id)
    
    session = connection or db.session
    
    if payment.sale_id:
        try:
            sale = session.get(Sale, payment.sale_id)
            if sale and sale.customer_id:
                customer_ids.add(sale.customer_id)
        except Exception:
            pass
    
    if payment.invoice_id:
        try:
            invoice = session.get(Invoice, payment.invoice_id)
            if invoice and invoice.customer_id:
                customer_ids.add(invoice.customer_id)
        except Exception:
            pass
    
    if payment.service_id:
        try:
            service = session.get(ServiceRequest, payment.service_id)
            if service and service.customer_id:
                customer_ids.add(service.customer_id)
        except Exception:
            pass
    
    if payment.preorder_id:
        try:
            preorder = session.get(PreOrder, payment.preorder_id)
            if preorder and preorder.customer_id:
                customer_ids.add(preorder.customer_id)
        except Exception:
            pass
    
    return customer_ids


def _balance_get_session(target_or_session):
    if isinstance(target_or_session, _SA_Session):
        return target_or_session
    session = object_session(target_or_session)
    if session:
        return session
    try:
        insp = inspect(target_or_session)
        session = getattr(insp, "session", None)
        if session:
            return session
    except Exception:
        pass
    try:
        return db.session
    except Exception:
        return None


def _queue_balance_entity(target_or_session, entity_type, entity_id):
    if not entity_type or entity_id in (None, ''):
        return
    session = _balance_get_session(target_or_session)
    if not session:
        return
    try:
        if session.info.get("_skip_balance_queue") or session.info.get("_skip_balance_after_commit"):
            return
    except Exception:
        pass
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        return
    pending = session.info.setdefault('_pending_balance_updates', set())
    pending.add((str(entity_type).upper(), entity_id))


def _queue_customer_balance(target_or_session, customer_id):
    if customer_id:
        _queue_balance_entity(target_or_session, "CUSTOMER", customer_id)


def _queue_supplier_balance(target_or_session, supplier_id):
    if supplier_id:
        _queue_balance_entity(target_or_session, "SUPPLIER", supplier_id)


def _queue_partner_balance(target_or_session, partner_id):
    if partner_id:
        _queue_balance_entity(target_or_session, "PARTNER", partner_id)


@event.listens_for(_SA_Session, "after_commit")
def _process_pending_balance_updates(session):
    try:
        if session.info.get("_skip_balance_after_commit"):
            session.info.pop("_pending_balance_updates", None)
            return
    except Exception:
        pass
    pending = session.info.pop('_pending_balance_updates', None)
    if not pending:
        return
    try:
        import utils
        from utils.customer_balance_updater import update_customer_balance_components
        from utils.supplier_balance_updater import get_supplier_from_customer
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text as sa_text
        from flask import current_app
        import time
    except Exception:
        return
    start_ts = time.perf_counter()
    work_session = None
    try:
        SessionFactory = sessionmaker(bind=db.engine)
        work_session = SessionFactory()
        try:
            work_session.info["_skip_balance_after_commit"] = True
            work_session.info["_skip_balance_queue"] = True
        except Exception:
            pass
    except Exception:
        work_session = None
    try:
        current_app.logger.info(f"🔄 بدء معالجة رصيد الكيانات بعد الالتزام: pending={len(pending)}")
    except Exception:
        pass
    processed = set()
    processed_count = 0
    while pending:
        entity_type, entity_id = pending.pop()
        key = (entity_type, entity_id)
        if key in processed:
            continue
        processed.add(key)
        try:
            if entity_type == "CUSTOMER":
                sess_for_work = work_session or session
                update_customer_balance_components(entity_id, sess_for_work)
                try:
                    if work_session is not None:
                        work_session.commit()
                except Exception:
                    try:
                        if work_session is not None:
                            work_session.rollback()
                    except Exception:
                        pass
                processed_count += 1
                try:
                    current_app.logger.info(f"✅ تحديث رصيد عميل #{entity_id}")
                except Exception:
                    pass
                try:
                    supplier_id = get_supplier_from_customer(entity_id, work_session or session)
                    if supplier_id:
                        pending.add(("SUPPLIER", int(supplier_id)))
                except Exception:
                    pass
                try:
                    partner_id = (work_session or session).execute(
                        sa_text("SELECT id FROM partners WHERE customer_id = :cid"),
                        {"cid": entity_id}
                    ).scalar()
                    if partner_id:
                        pending.add(("PARTNER", int(partner_id)))
                except Exception:
                    pass
            else:
                utils.update_entity_balance(entity_type, entity_id)
                processed_count += 1
                try:
                    current_app.logger.info(f"✅ تحديث رصيد {entity_type} #{entity_id}")
                except Exception:
                    pass
        except Exception as exc:
            try:
                current_app.logger.warning(
                    f"⚠️ فشل تحديث رصيد {entity_type} #{entity_id} بعد commit: {exc}"
                )
            except Exception:
                pass
    end_ts = time.perf_counter()
    try:
        current_app.logger.info(f"✔️ اكتملت معالجة الأرصدة: processed={processed_count}, duration_ms={(end_ts - start_ts) * 1000:.2f}")
    except Exception:
        pass
    try:
        if work_session is not None:
            work_session.close()
    except Exception:
        pass


@event.listens_for(_SA_Session, "after_rollback")
def _clear_pending_balance_updates(session):
    session.info.pop('_pending_balance_updates', None)


@event.listens_for(Payment, "after_insert")
@event.listens_for(Payment, "after_update")
@event.listens_for(Payment, "after_delete")
def _payment_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        customer_ids = _get_customer_ids_from_payment(target, session)
        for customer_id in customer_ids:
            _queue_customer_balance(session, customer_id)
        _queue_supplier_balance(session, getattr(target, "supplier_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                partner_result = connection.execute(
                    sa_text("SELECT id FROM partners WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if partner_result:
                    _queue_partner_balance(session, partner_result[0])
            except Exception:
                pass
            
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
        
        if hasattr(target, 'sale_id') and target.sale_id:
            from sqlalchemy import text as sa_text
            try:
                sale_result = connection.execute(
                    sa_text("SELECT customer_id FROM sales WHERE id = :sid"),
                    {"sid": target.sale_id}
                ).fetchone()
                if sale_result and sale_result[0]:
                    try:
                        partner_result = connection.execute(
                            sa_text("SELECT id FROM partners WHERE customer_id = :cid"),
                            {"cid": sale_result[0]}
                        ).fetchone()
                        if partner_result:
                            _queue_partner_balance(session, partner_result[0])
                    except Exception:
                        pass
                    
                    try:
                        supplier_result = connection.execute(
                            sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                            {"cid": sale_result[0]}
                        ).fetchone()
                        if supplier_result:
                            _queue_supplier_balance(session, supplier_result[0])
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(Sale, "after_insert")
@event.listens_for(Sale, "after_update")
@event.listens_for(Sale, "after_delete")
def _sale_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(SaleReturn, "after_insert")
@event.listens_for(SaleReturn, "after_update")
@event.listens_for(SaleReturn, "after_delete")
def _sale_return_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        customer_id_to_check = None
        if hasattr(target, 'customer_id') and target.customer_id:
            customer_id_to_check = target.customer_id
        elif hasattr(target, 'sale_id') and target.sale_id:
            from sqlalchemy import text as sa_text
            try:
                sale_result = connection.execute(
                    sa_text("SELECT customer_id FROM sales WHERE id = :sid"),
                    {"sid": target.sale_id}
                ).fetchone()
                if sale_result and sale_result[0]:
                    customer_id_to_check = sale_result[0]
                    partner_result = connection.execute(
                        sa_text("SELECT id FROM partners WHERE customer_id = :cid"),
                        {"cid": sale_result[0]}
                    ).fetchone()
                    if partner_result:
                        _queue_partner_balance(session, partner_result[0])
            except Exception:
                pass
        
        if customer_id_to_check:
            from sqlalchemy import text as sa_text
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": customer_id_to_check}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
        
        if hasattr(target, 'lines') and target.lines:
            try:
                from sqlalchemy import text as sa_text
                product_ids = [line.product_id for line in target.lines if hasattr(line, 'product_id') and line.product_id]
                if product_ids:
                    placeholders = ", ".join(f":pid_{i}" for i in range(len(product_ids)))
                    params = {f"pid_{i}": pid for i, pid in enumerate(product_ids)}
                    partner_results = connection.execute(
                        sa_text(f"""
                            SELECT DISTINCT partner_id 
                            FROM warehouse_partner_shares 
                            WHERE product_id IN ({placeholders})
                            UNION
                            SELECT DISTINCT partner_id 
                            FROM product_partners 
                            WHERE product_id IN ({placeholders})
                        """),
                        params
                    ).fetchall()
                    
                    for partner_row in partner_results:
                        if partner_row[0]:
                            _queue_partner_balance(session, partner_row[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(Invoice, "after_insert")
@event.listens_for(Invoice, "after_update")
@event.listens_for(Invoice, "after_delete")
def _invoice_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(ServiceRequest, "after_insert")
@event.listens_for(ServiceRequest, "after_update")
@event.listens_for(ServiceRequest, "after_delete")
def _service_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                partner_result = connection.execute(
                    sa_text("SELECT id FROM partners WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if partner_result:
                    _queue_partner_balance(session, partner_result[0])
            except Exception:
                pass
            
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(PreOrder, "after_insert")
@event.listens_for(PreOrder, "after_update")
@event.listens_for(PreOrder, "after_delete")
def _preorder_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(OnlinePreOrder, "after_insert")
@event.listens_for(OnlinePreOrder, "after_update")
@event.listens_for(OnlinePreOrder, "after_delete")
def _online_preorder_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if hasattr(target, 'customer_id') and target.customer_id:
            from sqlalchemy import text as sa_text
            try:
                supplier_result = connection.execute(
                    sa_text("SELECT id FROM suppliers WHERE customer_id = :cid"),
                    {"cid": target.customer_id}
                ).fetchone()
                if supplier_result:
                    _queue_supplier_balance(session, supplier_result[0])
            except Exception:
                pass
    except Exception:
        pass


@event.listens_for(Expense, "after_insert")
@event.listens_for(Expense, "after_update")
@event.listens_for(Expense, "after_delete")
def _expense_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        supplier_id = getattr(target, "supplier_id", None)
        if supplier_id:
            _queue_supplier_balance(session, supplier_id)
        _queue_partner_balance(session, getattr(target, "partner_id", None))
    except Exception:
        pass


@event.listens_for(Check, "after_insert")
@event.listens_for(Check, "after_update")
@event.listens_for(Check, "after_delete")
def _check_update_customer_balance(mapper, connection, target):
    try:
        session = _balance_get_session(target)
        _queue_customer_balance(session, getattr(target, "customer_id", None))
        _queue_supplier_balance(session, getattr(target, "supplier_id", None))
        _queue_partner_balance(session, getattr(target, "partner_id", None))
        
        if target.payment_id:
            try:
                payment = session.get(Payment, target.payment_id)
            except Exception:
                payment = None
            if payment:
                customer_ids = _get_customer_ids_from_payment(payment, session)
                for customer_id in customer_ids:
                    _queue_customer_balance(session, customer_id)
                _queue_partner_balance(session, getattr(payment, "partner_id", None))
    except Exception:
        pass
