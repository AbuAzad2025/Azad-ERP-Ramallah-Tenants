"""
رسائل المستخدم الموحّدة — نجاح / خطأ / تحذير / معلومة.
"""
from __future__ import annotations

from flask import flash

# Bootstrap categories
VALID_CATEGORIES = frozenset({"success", "danger", "warning", "info"})

_CATEGORY_ALIASES = {
    "error": "danger",
    "danger": "danger",
    "success": "success",
    "warning": "warning",
    "info": "info",
    "message": "info",
}

# رسائل شائعة — عربية واضحة
MSG_SAVED = "تم الحفظ بنجاح."
MSG_DELETED = "تم الحذف بنجاح."
MSG_UPDATED = "تم التحديث بنجاح."
MSG_CREATED = "تم الإنشاء بنجاح."
MSG_INTERNAL_ERROR = "حدث خطأ غير متوقع. حاول مرة أخرى أو تواصل مع الدعم."
MSG_VALIDATION = "تحقق من الحقول المطلوبة وأعد المحاولة."
MSG_NOT_FOUND = "العنصر المطلوب غير موجود."
MSG_FORBIDDEN = "ليس لديك صلاحية لهذا الإجراء."
MSG_LOGIN_FAILED = "بيانات الدخول غير صحيحة."
MSG_LOGIN_BLOCKED = "تم حظر محاولات الدخول مؤقتاً. حاول بعد 10 دقائق."
MSG_LOGOUT_OK = "تم تسجيل الخروج بنجاح."
MSG_MASTER_OK = "تم الدخول بنجاح."


def normalize_flash_category(category: str | None) -> str:
    key = (category or "info").strip().lower()
    return _CATEGORY_ALIASES.get(key, "info")


def flash_user(message: str, category: str = "info") -> None:
    """عرض رسالة للمستخدم مع تصنيف Bootstrap موحّد."""
    text = (message or "").strip()
    if not text:
        return
    flash(text, normalize_flash_category(category))


def flash_success(message: str | None = None) -> None:
    flash_user(message or MSG_SAVED, "success")


def flash_error(message: str | None = None) -> None:
    flash_user(message or MSG_INTERNAL_ERROR, "danger")


def flash_warning(message: str) -> None:
    flash_user(message, "warning")


def flash_info(message: str) -> None:
    flash_user(message, "info")


def user_friendly_error(exc: Exception | str | None, *, fallback: str | None = None) -> str:
    """تحويل خطأ تقني إلى رسالة مفهومة دون كشف تفاصيل داخلية."""
    if exc is None:
        return fallback or MSG_INTERNAL_ERROR
    raw = str(exc).strip() if not isinstance(exc, Exception) else str(exc).strip()
    low = raw.lower()
    if not raw:
        return fallback or MSG_INTERNAL_ERROR
    if "unique constraint" in low or "duplicate key" in low:
        return "هذا السجل موجود مسبقاً (قيمة مكررة)."
    if "foreign key" in low or "violates foreign key" in low:
        return "لا يمكن تنفيذ العملية: السجل مرتبط ببيانات أخرى."
    if "permission" in low or "forbidden" in low:
        return MSG_FORBIDDEN
    if "not found" in low or "no row" in low:
        return MSG_NOT_FOUND
    if len(raw) > 180 or "traceback" in low or "sqlalchemy" in low:
        return fallback or MSG_INTERNAL_ERROR
    return raw
