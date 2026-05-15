"""AI input/output protection helpers."""

from __future__ import annotations

import re
from typing import Any, Dict

BLOCK_MESSAGE = "⛔ تم رفض الطلب لأنه غير آمن أو خارج صلاحيات المستخدم الحالي."
MAX_TEXT = 6000

_OVERRIDE_WORDS = (
    "ignore previous",
    "disregard previous",
    "system prompt",
    "developer message",
    "jailbreak",
    "تجاهل التعليمات",
    "اكشف التعليمات",
    "اعرض التعليمات",
    "تجاوز الصلاحيات",
    "تصرف كمدير",
    "تصرف كمالك",
)

_SECRET_WORDS = (
    "api" + " key",
    "secret",
    "token",
    "cookie",
    "password",
    "passwd",
    "كلمة السر",
    "كلمه السر",
    "توكن",
    "رمز الدخول",
    "مفتاح سري",
)

_UNSAFE_WORDS = (
    "dr" + "op ",
    "trun" + "cate ",
    "de" + "lete from",
    "alter table",
    "grant all",
    "eval" + "(",
    "exec" + "(",
    "os." + "system",
    "sub" + "process",
    "احذف كل",
    "امسح كل",
    "عطل النظام",
    "خرب النظام",
)

_SECRET_VALUE_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*[^\s]{8,}")
_AUTH_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[a-z0-9._\-]{12,}")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200f", "").replace("\u200e", "").split()).lower()


def inspect_text(value: Any) -> Dict[str, Any]:
    raw = str(value or "")
    text = _norm(raw)
    issues = []
    if len(raw) > MAX_TEXT:
        issues.append("too_long")
    if any(word in text for word in _OVERRIDE_WORDS):
        issues.append("instruction_override")
    if any(word in text for word in _SECRET_WORDS):
        issues.append("secret_request")
    if any(word in text for word in _UNSAFE_WORDS):
        issues.append("unsafe_action")
    if re.search(r"(?i)select\s+.+\s+from\s+(users|auth|audit|permissions|roles|settings)", raw):
        issues.append("sensitive_query")
    return {"allowed": not issues, "issues": issues, "message": BLOCK_MESSAGE if issues else ""}


def deny(issues=None) -> Dict[str, Any]:
    return {"success": False, "denied": True, "response": BLOCK_MESSAGE, "error": BLOCK_MESSAGE, "confidence": 1.0, "sources": ["ai_input_filter"], "issues": issues or []}


def clean_text(value: Any) -> str:
    text = str(value or "")[:MAX_TEXT]
    text = _SECRET_VALUE_RE.sub("[REDACTED]", text)
    text = _AUTH_RE.sub(r"\1[REDACTED]", text)
    return text


def clean_data(value: Any):
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            k = str(key).lower()
            if any(term in k for term in ("password", "passwd", "token", "secret", "api_key", "apikey", "cookie", "hash")):
                output[key] = "[REDACTED]"
            else:
                output[key] = clean_data(item)
        return output
    if isinstance(value, list):
        return [clean_data(item) for item in value[:200]]
    if isinstance(value, str):
        return clean_text(value)
    return value


__all__ = ["inspect_text", "deny", "clean_text", "clean_data", "BLOCK_MESSAGE"]
