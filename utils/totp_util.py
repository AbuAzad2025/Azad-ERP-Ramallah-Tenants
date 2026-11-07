"""TOTP (RFC 6238) بدون تبعية خارجية."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


def generate_secret(length: int = 16) -> str:
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    s = (secret or "").strip().upper().replace(" ", "")
    pad = "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s + pad)


def totp_code(secret: str, *, when: int | None = None, interval: int = 30) -> str:
    key = _decode_secret(secret)
    counter = int((when if when is not None else time.time()) // interval)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % 1000000:06d}"


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    if not secret or not code:
        return False
    code = str(code).strip().zfill(6)
    now = int(time.time())
    for w in range(-window, window + 1):
        if totp_code(secret, when=now + w * 30) == code:
            return True
    return False
