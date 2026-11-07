"""سياسة كلمات المرور المؤسسية."""
from __future__ import annotations

import re

from models import SystemSettings

DEFAULT_MIN_LEN = 10


def password_policy_enabled() -> bool:
    return str(SystemSettings.get_setting("password_policy_enabled", "true")).lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def validate_password(password: str) -> tuple[bool, str]:
    if not password_policy_enabled():
        if len(password) >= 6:
            return True, ""
        return False, "كلمة المرور قصيرة جداً (6 أحرف على الأقل)"
    raw = SystemSettings.get_setting("password_min_length", DEFAULT_MIN_LEN) or DEFAULT_MIN_LEN
    try:
        min_len = int(raw)
    except (ValueError, TypeError):
        min_len = DEFAULT_MIN_LEN
    if len(password) < min_len:
        return False, f"كلمة المرور يجب أن تكون {min_len} أحرف على الأقل"
    if not re.search(r"[A-Za-z]", password):
        return False, "يجب أن تحتوي على حرف"
    if not re.search(r"\d", password):
        return False, "يجب أن تحتوي على رقم"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-\[\]\\;/+=]", password):
        return False, "يجب أن تحتوي على رمز خاص"
    return True, ""
