#!/usr/bin/env python3
"""فحص سريع لروابط القوائم (منصة + تينانت)."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smoke_pages_http import (  # noqa: E402
    _collect_static_get_rules,
    _login,
    _master_password,
    _nav_endpoints,
    _path_for_endpoint,
    _probe,
)


def main() -> int:
    from app import create_app

    app = create_app()
    nav = sorted(_nav_endpoints())
    failures = []
    for scope, prefix, login in [
        ("platform", "", "/auth/login"),
        ("tenant", "/t/alhazem", "/t/alhazem/auth/login"),
    ]:
        client = app.test_client()
        if not _login(client, login):
            failures.append((scope, "login", 0))
            continue
        for ep in nav:
            path = _path_for_endpoint(app, ep, prefix)
            if not path:
                failures.append((scope, ep, "no_path"))
                continue
            if scope == "tenant" and path.startswith("/security"):
                continue
            res = _probe(client, ep, path)
            if res["fail"] or res["status"] >= 500:
                failures.append((scope, ep, res["status"], res.get("hint", "")))

    extra = [
        ("platform", "/security/control-center"),
        ("platform", "/security/fiscal-periods/"),
        ("tenant", "/t/alhazem/console/control"),
        ("tenant", "/t/alhazem/validation/accounting/"),
    ]
    for scope, path in extra:
        client = app.test_client()
        login = "/auth/login" if scope == "platform" else "/t/alhazem/auth/login"
        _login(client, login)
        res = _probe(client, path, path)
        if res["fail"] or res["status"] >= 500:
            failures.append((scope, path, res["status"], res.get("hint", "")))

    print("nav endpoints:", len(nav))
    print("failures:", len(failures))
    for row in failures:
        print(" ", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
