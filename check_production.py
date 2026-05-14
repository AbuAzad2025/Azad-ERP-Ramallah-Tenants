"""Production configuration checker for AzadAccounting-sys.

Run on the server before/after deployment:

    python check_production.py

This script only reads environment/config values. It does not connect to the
application database and does not modify files or data.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

# Load .env through config.py exactly like the application does.
from config import Config


DEFAULT_PASSWORDS = {
    "OWNER_PASSWORD": "OWNER123",
    "DEVELOPER_PASSWORD": "DEV123",
    "SUPER_ADMIN_PASSWORD": "AZ123456",
    "ADMIN_PASSWORD": "ADMIN123",
    "MANAGER_PASSWORD": "MANAGER123",
    "STAFF_PASSWORD": "STAFF123",
    "MECHANIC_PASSWORD": "MECH123",
    "REGISTERED_CUSTOMER_PASSWORD": "CUST123",
}

PLACEHOLDER_VALUES = {
    "",
    "change_me",
    "change_me_generate_a_long_random_secret",
    "change_me_owner_strong_password",
    "change_me_developer_strong_password",
    "change_me_super_admin_strong_password",
    "change_me_admin_strong_password",
    "change_me_manager_strong_password",
    "change_me_staff_strong_password",
    "change_me_mechanic_strong_password",
    "change_me_customer_strong_password",
}


def _mask_uri(uri: str) -> str:
    if not uri:
        return "<empty>"
    parsed = urlparse(uri)
    if not parsed.scheme:
        return uri
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    db = parsed.path or ""
    auth = f"{user}:***@" if user else ""
    return f"{parsed.scheme}://{auth}{host}{port}{db}"


def _env_value(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    app_env = str(getattr(Config, "APP_ENV", "production") or "production").lower()
    debug = bool(getattr(Config, "DEBUG", False))
    is_prod = (not debug) and app_env not in {"dev", "development", "local"}
    db_uri = str(getattr(Config, "SQLALCHEMY_DATABASE_URI", "") or "")

    print("AzadAccounting-sys production check")
    print("===================================")
    print(f"APP_ENV: {app_env}")
    print(f"DEBUG: {debug}")
    print(f"DATABASE: {_mask_uri(db_uri)}")

    if debug and is_prod:
        errors.append("DEBUG must be false in production.")
    if app_env in {"dev", "development", "local"}:
        warnings.append("APP_ENV is not production; this is fine only for local testing.")

    if db_uri.startswith("sqlite://"):
        if is_prod:
            errors.append("Production is using SQLite. Set DATABASE_URL to PostgreSQL.")
        else:
            warnings.append("SQLite is being used. This is OK for local testing only.")
    elif not db_uri.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://")):
        warnings.append("Database URL is not PostgreSQL. Confirm this is intentional.")

    secret_key = str(getattr(Config, "SECRET_KEY", "") or "")
    if is_prod and (not secret_key or secret_key in PLACEHOLDER_VALUES or len(secret_key) < 32):
        errors.append("SECRET_KEY is missing, too short, or still a placeholder.")

    if is_prod and not bool(getattr(Config, "SESSION_COOKIE_SECURE", False)):
        warnings.append("SESSION_COOKIE_SECURE is false. Use true when served over HTTPS.")

    cors = getattr(Config, "CORS_ORIGINS", "")
    socketio_cors = getattr(Config, "SOCKETIO_CORS_ORIGINS", "")
    if cors == "*" or socketio_cors == "*":
        warnings.append("CORS or SocketIO CORS allows '*'. Restrict it to your domain in production.")

    pool_size = int(getattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {}).get("pool_size", 0) or 0)
    max_overflow = int(getattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {}).get("max_overflow", 0) or 0)
    if is_prod and db_uri.startswith(("postgresql://", "postgres://")):
        if pool_size > 20 or max_overflow > 50:
            warnings.append(
                f"Database pool is large for shared hosting: pool_size={pool_size}, max_overflow={max_overflow}. "
                "Consider SQLALCHEMY_POOL_SIZE=5 and SQLALCHEMY_MAX_OVERFLOW=10 on PythonAnywhere."
            )

    for env_name, default_password in DEFAULT_PASSWORDS.items():
        actual = _env_value(env_name, default_password)
        if actual == default_password or actual in PLACEHOLDER_VALUES:
            if is_prod:
                errors.append(f"{env_name} is default or placeholder. Set a strong unique password.")
            else:
                warnings.append(f"{env_name} is default or placeholder.")

    print()
    if errors:
        print("ERRORS")
        for item in errors:
            print(f"  - {item}")
    else:
        print("ERRORS: none")

    print()
    if warnings:
        print("WARNINGS")
        for item in warnings:
            print(f"  - {item}")
    else:
        print("WARNINGS: none")

    print()
    if errors:
        print("Result: NOT READY for production.")
        return 1
    print("Result: basic production settings look acceptable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
