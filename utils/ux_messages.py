"""رسائل موحّدة للأخطاء والتحذيرات والإرشادات — واجهة أزاد."""
from __future__ import annotations

import re
from typing import Any

FLASH_TITLES: dict[str, str] = {
    "success": "تم بنجاح",
    "danger": "تعذّر الإكمال",
    "error": "تعذّر الإكمال",
    "warning": "تنبيه",
    "info": "معلومة",
    "primary": "إشعار",
    "secondary": "إشعار",
}

FLASH_ICONS: dict[str, str] = {
    "success": "fa-check-circle",
    "danger": "fa-times-circle",
    "error": "fa-times-circle",
    "warning": "fa-exclamation-triangle",
    "info": "fa-info-circle",
    "primary": "fa-bell",
    "secondary": "fa-bell",
}

# رسائل قياسية — مفتاح → نص واضح مع إرشاد
STANDARD_MESSAGES: dict[str, str] = {
    "internal_error": (
        "تعذّر إكمال العملية. تحقق من البيانات وحاول مجدداً، "
        "أو تواصل مع مسؤول النظام إن استمر الخطأ."
    ),
    "validation_error": "يرجى مراجعة الحقول المظلّلة وتصحيحها قبل المتابعة.",
    "required_fields": "يرجى تعبئة جميع الحقول المطلوبة (*).",
    "permission_denied": "ليس لديك صلاحية تنفيذ هذا الإجراء. اطلب الصلاحية من المسؤول.",
    "not_found": "العنصر المطلوب غير موجود أو ربما تم حذفه.",
    "duplicate": "هذا السجل موجود مسبقاً. استخدم قيمة مختلفة.",
    "network_error": "تعذّر الاتصال بالخادم. تحقق من الشبكة وحاول مرة أخرى.",
    "session_expired": "انتهت الجلسة. سجّل الدخول مجدداً للمتابعة.",
    "csrf_error": "انتهت صلاحية النموذج. حدّث الصفحة وأعد المحاولة.",
    "saved": "تم حفظ البيانات بنجاح.",
    "deleted": "تم الحذف بنجاح.",
    "updated": "تم التحديث بنجاح.",
    "created": "تم الإنشاء بنجاح.",
    "cancelled": "تم إلغاء العملية.",
    "no_results": "لا توجد نتائج مطابقة لبحثك.",
    "confirm_delete": "هل أنت متأكد؟ لا يمكن التراجع عن الحذف.",
    "fx_missing": "لا يوجد سعر صرف متاح لهذه العملة. أضف سعراً في إدارة العملات.",
    "amount_positive": "المبلغ يجب أن يكون أكبر من صفر.",
    "date_invalid": "التاريخ غير صالح. تحقق من التنسيق (YYYY-MM-DD).",
    "check_due_before_issue": "تاريخ الاستحقاق لا يمكن أن يكون قبل تاريخ الشيك.",
}

# نصوص قديمة/مكررة → رسالة موحّدة
_MESSAGE_ALIASES: dict[str, str] = {
    "حدث خطأ داخلي": "internal_error",
    "حدث خطأ": "internal_error",
    "حدث خطأ داخلي في الخادم. تم تسجيل الخطأ للمراجعة.": "internal_error",
    "حدث خطأ غير متوقع": "internal_error",
    "حدث خطأ غير متوقع!": "internal_error",
    "فشل الاستعادة": "internal_error",
    "خطأ في إنشاء الفرع": "internal_error",
    "خطأ في تحديث الفرع": "internal_error",
    "حدث خطأ أثناء الحفظ": "internal_error",
    "حدث خطأ أثناء إصلاح الربط": "internal_error",
    "حدث خطأ أثناء رفع الشعار": "internal_error",
    "فشل جلب الشيكات": "network_error",
    "يرجى ملء جميع الحقول المطلوبة": "required_fields",
    "يرجى تصحيح الحقول المظللة أدناه.": "validation_error",
    "ليس لديك صلاحية": "permission_denied",
    "غير مصرح لك بهذا الإجراء": "permission_denied",
    "not found": "not_found",
    "bad request": "validation_error",
    "unauthorized": "session_expired",
    "too many requests": "network_error",
    "internal server error": "internal_error",
}

_EMOJI_PREFIX = re.compile(r"^[\s✅❌⚠️ℹ️🔴🟢🟡🔵⭐📌💡]+")
_EMOJI_ANYWHERE = re.compile(r"[\u2705\u274c\u26a0\ufe0f\u2139\ufe0f\U0001f4a1\U0001f4cc\U0001f534\U0001f7e2\U0001f7e1\U0001f535]+")


def normalize_flash_category(category: str | None) -> str:
    c = (category or "info").strip().lower()
    mapping = {
        "error": "danger",
        "fail": "danger",
        "failed": "danger",
        "dangerous": "danger",
        "warn": "warning",
        "alert": "warning",
        "ok": "success",
        "done": "success",
        "message": "info",
    }
    c = mapping.get(c, c)
    if c not in FLASH_TITLES:
        return "info"
    return c


def msg(key: str, default: str = "") -> str:
    return STANDARD_MESSAGES.get(key, default or key)


def flash_title(category: str | None) -> str:
    return FLASH_TITLES.get(normalize_flash_category(category), "إشعار")


def flash_icon(category: str | None) -> str:
    return FLASH_ICONS.get(normalize_flash_category(category), "fa-info-circle")


def clean_flash_text(text: str | None) -> str:
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    t = _EMOJI_PREFIX.sub("", t).strip()
    t = _EMOJI_ANYWHERE.sub("", t).strip()
    t = re.sub(r"\s{2,}", " ", t)
    low = t.lower()
    if t in _MESSAGE_ALIASES:
        return msg(_MESSAGE_ALIASES[t])
    if low in _MESSAGE_ALIASES:
        return msg(_MESSAGE_ALIASES[low])
    for prefix, key in _MESSAGE_ALIASES.items():
        if t == prefix or t.startswith(prefix + ".") or t.startswith(prefix + ":"):
            return msg(key)
    return t


def resolve_user_message(
    message: str | None = None,
    *,
    key: str | None = None,
    default_key: str = "internal_error",
) -> str:
    """رسالة واحدة واضحة للمستخدم — للـ API والواجهة."""
    if key:
        return msg(key)
    cleaned = clean_flash_text(message)
    if cleaned:
        return cleaned
    return msg(default_key)


def prepare_flash(category: str | None, message: str | None) -> dict[str, str]:
    cat = normalize_flash_category(category)
    body = clean_flash_text(message)
    return {
        "category": cat,
        "title": flash_title(cat),
        "icon": flash_icon(cat),
        "message": body,
    }


def api_payload(
    *,
    success: bool = False,
    message: str | None = None,
    key: str | None = None,
    errors: dict[str, Any] | list | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """استجابة JSON موحّدة للواجهة."""
    text = resolve_user_message(message, key=key, default_key="internal_error" if not success else "")
    if not text and success:
        text = msg("saved")
    payload: dict[str, Any] = {
        "success": success,
        "message": text,
        "error": None if success else text,
    }
    if errors is not None:
        payload["errors"] = errors
    payload.update(extra)
    return payload


def json_error(
    status: int = 400,
    *,
    key: str = "internal_error",
    message: str | None = None,
    **extra: Any,
):
    """استجابة JSON للأخطاء — نص عربي موحّد."""
    from flask import jsonify

    return jsonify(api_payload(success=False, key=key, message=message, **extra)), status


def flash_msg(category: str, message: str | None = None, *, key: str | None = None) -> None:
    """Flash موحّد — category: success|danger|warning|info أو مفتاح من UX_MSG."""
    from flask import flash

    cat = normalize_flash_category(category)
    text = msg(key) if key else clean_flash_text(message or "")
    if text:
        flash(text, cat)
