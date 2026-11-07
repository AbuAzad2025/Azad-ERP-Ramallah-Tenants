"""ضوابط أمان مؤسسية: جدول دخول، تواريخ قفل إدخال."""
from __future__ import annotations

import json
from datetime import date, datetime, time

from flask import request
from flask_login import current_user

from models import SystemSettings


def get_posting_locked_before() -> date | None:
    raw = SystemSettings.get_setting("posting_locked_before", None)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def assert_posting_date_allowed(posting_date: date | datetime | None) -> None:
    locked = get_posting_locked_before()
    if not locked or not posting_date:
        return
    if isinstance(posting_date, datetime):
        posting_date = posting_date.date()
    if posting_date <= locked:
        raise ValueError(f"الإدخال مقفول قبل {locked.isoformat()}")


def user_may_login_now(user) -> tuple[bool, str]:
    if not user or not getattr(user, "is_active", True):
        return False, "الحساب غير نشط"
    sched_raw = getattr(user, "login_schedule_json", None)
    if sched_raw:
        try:
            sched = json.loads(sched_raw)
            if sched.get("enabled"):
                dow = datetime.now().weekday()
                allowed_days = sched.get("days") or list(range(7))
                if dow not in allowed_days:
                    return False, "خارج أيام الدخول المسموحة"
                start_s = sched.get("start", "00:00")
                end_s = sched.get("end", "23:59")
                sh, sm = map(int, start_s.split(":")[:2])
                eh, em = map(int, end_s.split(":")[:2])
                now_t = datetime.now().time()
                start_t = time(sh, sm)
                end_t = time(eh, em)
                if start_t <= end_t:
                    allowed = start_t <= now_t <= end_t
                else:
                    allowed = now_t >= start_t or now_t <= end_t
                if not allowed:
                    return False, "خارج ساعات الدخول المسموحة"
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass
    stations_raw = getattr(user, "allowed_stations_json", None)
    if stations_raw:
        try:
            allowed = json.loads(stations_raw)
            if allowed:
                station = (request.headers.get("X-Station-Id") or request.remote_addr or "").strip()
                if station and station not in allowed:
                    return False, "محطة غير مصرح بها"
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return True, ""
