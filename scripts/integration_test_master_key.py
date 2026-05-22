#!/usr/bin/env python3
"""اختبار مفتاح المالك: وحدة + HTTP (منصة وتينانت)."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _today_master_password() -> str:
    from utils.licensing import _reconstruct_base_key

    base = _reconstruct_base_key()
    return base + datetime.datetime.now().strftime("@%Y@%m@%d")


def _unit_tests(session) -> list[str]:
    from utils.master_key_login import (
        is_master_key_password,
        resolve_platform_master_user,
        resolve_tenant_master_user,
        try_master_key_login,
    )

    failures: list[str] = []
    mk = _today_master_password()

    if not is_master_key_password(mk):
        failures.append("is_master_key_password:expected_true")
    if is_master_key_password("wrong-password"):
        failures.append("is_master_key_password:expected_false")

    pu = resolve_platform_master_user(session)
    if not pu:
        failures.append("resolve_platform_master_user:missing")
    elif (pu.username or "").upper() not in ("__OWNER__", "OWNER"):
        failures.append(f"resolve_platform_master_user:unexpected:{pu.username}")

    for slug in ("nasrallah", "alhazem"):
        tu = resolve_tenant_master_user(session, slug)
        if not tu:
            failures.append(f"resolve_tenant_master_user:{slug}:missing")
        else:
            role = getattr(getattr(tu, "role", None), "name", "") or ""
            if role != "owner":
                failures.append(f"resolve_tenant_master_user:{slug}:role={role}")

    plat = try_master_key_login(password=mk, tenant_slug=None, session=session)
    if not plat or plat.get("scope") != "platform":
        failures.append("try_master_key_login:platform")

    ten = try_master_key_login(password=mk, tenant_slug="nasrallah", session=session)
    if not ten or ten.get("scope") != "tenant" or ten.get("tenant_slug") != "nasrallah":
        failures.append("try_master_key_login:tenant")

    bad = try_master_key_login(password="nope", tenant_slug="nasrallah", session=session)
    if bad is not None:
        failures.append("try_master_key_login:should_be_none_for_wrong_pw")

    return failures


def _http_tests(app) -> list[str]:
    from flask import session as flask_session

    failures: list[str] = []
    mk = _today_master_password()
    client = app.test_client()

    cases = [
        ("platform", "/auth/login", None, "security.index"),
        ("tenant_nasrallah", "/t/nasrallah/auth/login", "nasrallah", "tenant_console.index"),
        ("tenant_alhazem", "/t/alhazem/auth/login", "alhazem", "tenant_console.index"),
    ]

    for label, path, slug, expected_ep in cases:
        with client.session_transaction() as sess:
            sess.clear()

        resp = client.post(
            path,
            data={"username": "", "password": mk},
            follow_redirects=False,
        )
        if resp.status_code not in (302, 303):
            failures.append(f"http:{label}:status={resp.status_code}")
            continue

        loc = resp.headers.get("Location") or ""
        with client.session_transaction() as sess:
            uid = sess.get("_user_id", "")
            gm_slug = sess.get("gm_tenant_slug", "")

        if slug:
            if not str(uid).startswith(f"t:{slug}:"):
                failures.append(f"http:{label}:session_uid={uid}")
            if gm_slug != slug:
                failures.append(f"http:{label}:gm_tenant_slug={gm_slug}")
        else:
            if str(uid).startswith("t:"):
                failures.append(f"http:{label}:unexpected_tenant_session={uid}")

        from flask import url_for

        try:
            expected_path = url_for(expected_ep)
        except Exception:
            expected_path = ""
        if expected_ep == "security.index":
            ok_loc = "/security" in loc
        elif expected_ep == "tenant_console.index":
            ok_loc = "tenant" in loc.lower() or (slug and f"/t/{slug}" in loc)
        else:
            ok_loc = bool(loc)
        if not ok_loc:
            failures.append(f"http:{label}:redirect={loc!r} expected~{expected_ep}")

        # رفض كلمة مرور خاطئة
        with client.session_transaction() as sess:
            sess.clear()
        bad = client.post(path, data={"username": "x", "password": "bad-key"}, follow_redirects=False)
        if bad.status_code == 200:
            body = (bad.get_data(as_text=True) or "").lower()
            if "welcome back, master" in body:
                failures.append(f"http:{label}:wrong_pw_logged_in")

    return failures


def run() -> int:
    from app import create_app
    from extensions import db

    app = create_app()
    all_fail: list[str] = []

    with app.app_context():
        all_fail.extend(_unit_tests(db.session))
        all_fail.extend(_http_tests(app))

    print("\n=== Master Key Integration ===")
    if all_fail:
        for f in all_fail:
            print(f"  FAIL: {f}")
        print(f"\nFAIL — {len(all_fail)} issue(s)")
        return 1

    print("  Unit tests: OK")
    print("  HTTP platform + tenant login: OK")
    print("\nPASS — master key flows verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
