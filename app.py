import os
import sys

# Force UTF-8 to prevent emoji crashes on Windows consoles
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import uuid
import logging
import inspect
import time
import platform
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, timezone
from flask import Flask, url_for, request, current_app, render_template, g, redirect, make_response, jsonify
from werkzeug.routing import BuildError
try:
    from flask_cors import CORS
except ImportError:
    CORS = None
from flask_login import AnonymousUserMixin, current_user
from jinja2 import ChoiceLoader, FileSystemLoader

if os.name == "nt":
    try:
        # Patch platform.machine to avoid WMI calls that hang on some Windows environments
        platform.machine = lambda: (os.environ.get("PROCESSOR_ARCHITECTURE") or "AMD64")
        
        # Also patch _wmi_query if it exists, as it's used by other platform functions
        if hasattr(platform, "_wmi_query"):
             # Fix: _wmi_query must return a 5-element tuple. 
             # The second element (product_type) is used as int() in platform.py line 399: int(product_type) == 1
             # So we return '1' for it to avoid ValueError.
             platform._wmi_query = lambda *args, **kwargs: ('10', '1', 'Multiprocessor Free', '0', '0')
    except Exception:
        pass
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config, ensure_runtime_dirs, assert_production_sanity
from extensions import db, migrate, login_manager, socketio, mail, csrf, limiter, cache, setup_logging, setup_sentry
from extensions import init_extensions
import utils
from models import (
    User, Role, Permission, Customer, SystemSettings, TenantRegistry,
    PaymentStatus, PaymentDirection, PaymentMethod, PaymentEntityType,
    SaleStatus, ShipmentStatus, ServiceStatus, WarehouseType,
    OnlinePaymentStatus, OnlineCartStatus, PreOrderStatus, CheckStatus,
    TransferDirection, TimesheetStatus, TaskStatus, EngineeringTaskStatus
)

from acl import attach_acl
from permissions_config.blueprint_guards import get_blueprint_guard_config

from routes.auth import auth_bp
from routes.main import main_bp
from routes.users import users_bp
from routes.service import service_bp
from routes.customers import customers_bp
from routes.sales import sales_bp
from routes.notes import notes_bp
from routes.report_routes import reports_bp
from routes.shop import shop_bp
from routes.expenses import expenses_bp
from routes.vendors import vendors_bp
from routes.shipments import shipments_bp
from routes.warehouses import warehouse_bp
from routes.branches import branches_bp
from routes.payments import payments_bp
from routes.permissions import permissions_bp
from routes.roles import roles_bp
from routes.api import bp as api_bp
from routes.admin_reports import admin_reports_bp
from routes.parts import parts_bp
from routes.barcode import bp_barcode
from routes.partner_settlements import partner_settlements_bp
from routes.supplier_settlements import supplier_settlements_bp
from routes.ledger_blueprint import ledger_bp
from routes.ledger_control import ledger_control_bp
from routes.financial_reports import financial_reports_bp
from routes.accounting_validation import accounting_validation_bp
from routes.accounting_docs import accounting_docs_bp
from routes.ai_routes import ai_bp
from routes.ai_admin import ai_admin_bp
from routes.barcode_scanner import barcode_scanner_bp
from routes.currencies import currencies_bp
from routes.user_guide import user_guide_bp
from routes.other_systems import other_systems_bp
from routes.pricing import pricing_bp
from routes.checks import checks_bp
from routes.budgets import budgets_bp
from routes.assets import assets_bp
from routes.bank import bank_bp
from routes.cost_centers import cost_centers_bp
from routes.cost_centers_advanced import cost_centers_advanced_bp
from routes.engineering import engineering_bp
from routes.projects import projects_bp
from routes.project_advanced import project_advanced_bp
from routes.recurring_invoices import recurring_bp
from routes.health import health_bp
from routes.security import security_bp
from routes.security_expenses import security_expenses_bp
from routes.advanced_control import advanced_bp
from routes.workflows import workflows_bp
from routes.security_control import security_control_bp
from routes.archive import archive_bp
from routes.archive_routes import archive_routes_bp
from routes.sale_returns import returns_bp
from routes.balances_api import balances_api_bp
from routes.performance import performance_bp
from routes.tenant_console import tenant_console_bp


class MyAnonymousUser(AnonymousUserMixin):
    def has_permission(self, perm_name):
        return False


@login_manager.user_loader
def load_user(user_id):
    from sqlalchemy.orm import joinedload, lazyload
    from sqlalchemy import select

    uid_str = str(user_id or "").strip()
    if ":" in uid_str:
        try:
            prefix, ident = uid_str.split(":", 1)
            prefix = prefix.lower()
        except Exception:
            return None
        if prefix == "t":
            try:
                tenant_slug, raw_id = ident.split(":", 1)
                ident_int = int(raw_id)
            except Exception:
                return None
            req_slug = str(getattr(g, "tenant_slug", "") or "").strip().lower()
            if not req_slug or req_slug != str(tenant_slug or "").strip().lower():
                return None
            stmt = (
                select(User)
                .options(joinedload(User.role).joinedload(Role.permissions))
                .where(User.id == ident_int)
            )
            return db.session.execute(stmt).unique().scalar_one_or_none()
        try:
            ident_int = int(ident)
        except Exception:
            return None
        if prefix == "p":
            stmt = (
                select(User)
                .options(joinedload(User.role).joinedload(Role.permissions))
                .where(User.id == ident_int)
            )
            return db.session.execute(stmt).unique().scalar_one_or_none()
        if prefix == "u":
            stmt = (
                select(User)
                .options(joinedload(User.role).joinedload(Role.permissions))
                .where(User.id == ident_int)
            )
            return db.session.execute(stmt).unique().scalar_one_or_none()
        if prefix == "c":
            stmt = select(Customer).options(lazyload("*")).where(Customer.id == ident_int)
            return db.session.execute(stmt).scalar_one_or_none()
        return None

    try:
        ident = int(uid_str)
    except Exception:
        return None

    stmt_user = (
        select(User)
        .options(joinedload(User.role).joinedload(Role.permissions))
        .where(User.id == ident)
    )
    user = db.session.execute(stmt_user).unique().scalar_one_or_none()
    if user:
        return user

    stmt_cust = select(Customer).options(lazyload("*")).where(Customer.id == ident)
    return db.session.execute(stmt_cust).scalar_one_or_none()


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _safe_request_id(value) -> str:
    raw = str(value or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")
    if not raw or len(raw) > 64 or any(ch not in allowed for ch in raw):
        return uuid.uuid4().hex
    return raw


class TenantPathMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO") or ""
        if path.startswith("/t/"):
            rest = path[3:]
            parts = rest.split("/", 1)
            slug = (parts[0] or "").strip()
            if slug and all(ch.isalnum() or ch in {"_", "-"} for ch in slug):
                prefix = f"/t/{slug}"
                script_name = environ.get("SCRIPT_NAME") or ""
                if not script_name.endswith(prefix):
                    environ["SCRIPT_NAME"] = f"{script_name}{prefix}"
                environ["gm.tenant_slug"] = slug
                environ["PATH_INFO"] = f"/{parts[1]}" if len(parts) > 1 and parts[1] else "/"
        return self.app(environ, start_response)


def _configure_app(app: Flask, config_object):
    app.config.from_object(config_object)
    app.config.setdefault("JSON_AS_ASCII", False)
    app.config.setdefault("NUMBER_DECIMALS", 2)
    app.config.setdefault("PAGE_MICROCACHE_SECONDS", 8)
    app.config.setdefault("STATIC_VERSION", int(time.time()))
    app.config.setdefault("COMPRESS_LEVEL", 6)
    app.config.setdefault("COMPRESS_MIN_SIZE", 500)
    app.config.setdefault(
        "COMPRESS_MIMETYPES",
        [
            "text/html",
            "text/css",
            "application/javascript",
            "text/javascript",
            "application/json",
            "image/svg+xml",
            "application/xml",
            "text/xml",
        ],
    )

    is_production = not app.config.get("DEBUG", False) and app.config.get("APP_ENV", "production").lower() not in {"dev", "development", "local"}
    if is_production:
        app.config["TEMPLATES_AUTO_RELOAD"] = False
        app.jinja_env.auto_reload = False
        app.jinja_env.cache_size = 400
    else:
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True
        app.jinja_env.cache_size = 50

    ensure_runtime_dirs(config_object)
    assert_production_sanity(config_object)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if app.config.get("USE_PROXYFIX"):
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
        except Exception:
            pass

    app.wsgi_app = TenantPathMiddleware(app.wsgi_app)

    app.config.setdefault("SUPER_USER_EMAILS", os.getenv("SUPER_USER_EMAILS", ""))
    app.config.setdefault("SUPER_USER_IDS", os.getenv("SUPER_USER_IDS", ""))
    app.config.setdefault("ADMIN_USER_EMAILS", os.getenv("ADMIN_USER_EMAILS", ""))
    app.config.setdefault("ADMIN_USER_IDS", os.getenv("ADMIN_USER_IDS", ""))
    app.config.setdefault("SKIP_SYSTEM_INTEGRITY", _env_bool("SKIP_SYSTEM_INTEGRITY", False))
    app.config.setdefault("PERMISSIONS_REQUIRE_ALL", False)
    app.config.setdefault("AI_SYSTEMS_ENABLED", True)
    app.config.setdefault("ENABLE_AUTOMATED_BACKUPS", True)
    if os.getenv("SKIP_SYSTEM_INTEGRITY") is not None:
        app.config["SKIP_SYSTEM_INTEGRITY"] = _env_bool("SKIP_SYSTEM_INTEGRITY", bool(app.config.get("SKIP_SYSTEM_INTEGRITY", False)))

    engine_opts = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
    connect_args = engine_opts.get("connect_args", {})
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith(("postgresql", "postgres")):
        connect_args.setdefault("connect_timeout", int(os.getenv("DB_CONNECT_TIMEOUT", "10")))
        connect_args.setdefault("application_name", "garage_manager")
    engine_opts["connect_args"] = connect_args
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts

    setup_logging(app)
    setup_sentry(app)



def _ensure_minimum_postgres_schema(app):
    try:
        from sqlalchemy import inspect, text as sa_text
    except Exception:
        return
    try:
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if "invoices" not in tables:
            return
        cols = {c.get("name") for c in (insp.get_columns("invoices") or [])}
        stmts = []
        if "cancelled_at" not in cols:
            stmts.append("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;")
        if "cancelled_by" not in cols:
            stmts.append("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cancelled_by INTEGER;")
        if "cancel_reason" not in cols:
            stmts.append("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(200);")
        for sql in stmts:
            db.session.execute(sa_text(sql))
        if stmts:
            db.session.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_invoices_cancelled_at ON invoices (cancelled_at);"))
            db.session.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_invoices_cancelled_by ON invoices (cancelled_by);"))
            db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            app.logger.warning("schema_autofix_skipped: %s", e)
        except Exception:
            pass


def _init_extensions_stack(app):
    init_extensions(app)
    try:
        utils.init_app(app)
    except Exception as e:
        try:
            app.logger.warning("utils_init_skipped: %s", e)
        except Exception:
            pass

    # --- SYSTEM INTEGRITY & SELF-HEALING ---
    # This ensures the system is always ready-to-use (Currencies, Roles, Warehouses, COA)
    try:
        from services.system_initializer import SystemInitializer
        if not app.config.get("SKIP_SEED", False):
            SystemInitializer(app).ensure_integrity()
    except Exception as e:
        app.logger.error(f"System Initialization Failed: {e}")
    # ---------------------------------------

    try:
        from utils.performance_monitor import init_perf_monitor
        init_perf_monitor(app)
    except Exception as e:
        try:
            app.logger.warning("perf_monitor_init_skipped: %s", e)
        except Exception:
            pass

    try:
        from services.ghost_manager import ensure_ghost_owner
        if not app.config.get("SKIP_SYSTEM_INTEGRITY", False):
            with app.app_context():
                try:
                    ensure_ghost_owner()
                except Exception:
                    pass
    except Exception:
        pass

    try:
        from cli import register_cli
        register_cli(app)
    except Exception:
        pass
    try:
        with app.app_context():
            _ensure_minimum_postgres_schema(app)
    except Exception as _e:
        app.logger.warning(f"Bootstrap expense types skipped: {_e}")


def _register_template_support(app):
    extra_template_paths = [
        os.path.join(app.root_path, "templates"),
        os.path.join(app.root_path, "routes", "templates"),
    ]
    app.jinja_loader = ChoiceLoader(
        [FileSystemLoader(p) for p in extra_template_paths]
        + ([app.jinja_loader] if app.jinja_loader else [])
    )

    app.jinja_env.autoescape = True

    @app.template_global()
    def _get_action_icon(action):
        if not action:
            return 'info-circle'
        mapping = {
            'login': 'sign-in-alt', 'logout': 'sign-out-alt',
            'create': 'plus', 'update': 'edit', 'delete': 'trash',
            'view': 'eye', 'export': 'download', 'import': 'upload',
            'blocked': 'ban', 'security': 'shield-alt'
        }
        action_lower = str(action).lower()
        for key, icon in mapping.items():
            if key in action_lower:
                return icon
        return 'circle'

    @app.template_global()
    def _get_action_color(action):
        if not action:
            return 'secondary'
        mapping = {
            'login': 'success', 'logout': 'secondary',
            'create': 'primary', 'update': 'info', 'delete': 'danger',
            'blocked': 'danger', 'failed': 'danger', 'security': 'warning'
        }
        action_lower = str(action).lower()
        for key, color in mapping.items():
            if key in action_lower:
                return color
        return 'secondary'

    def _two_dec(v, digits=None, grouping=True):
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError):
            d = Decimal("0")
        digits = digits or app.config.get("NUMBER_DECIMALS", 2)
        q = (Decimal("1") / (Decimal("10") ** digits))
        d = d.quantize(q, rounding=ROUND_HALF_UP)
        if grouping:
            return f"{d:,.{digits}f}"
        return f"{d:.{digits}f}"

    def _safe_number_format(v, digits=None):
        return _two_dec(v, digits=digits or app.config.get("NUMBER_DECIMALS", 2), grouping=True)

    def get_unique_flashes(with_categories=True):
        from flask import get_flashed_messages
        msgs = get_flashed_messages(with_categories=with_categories)
        seen = set()
        if with_categories:
            uniq = []
            for cat, msg in msgs:
                if msg not in seen:
                    uniq.append((cat or "info", msg))
                    seen.add(msg)
            return uniq
        uniq = []
        for msg in msgs:
            if msg not in seen:
                uniq.append(msg)
                seen.add(msg)
        return uniq

    @app.template_filter('static_version')
    def static_version_filter(filename):
        version = app.config.get("STATIC_VERSION")
        if not version:
            try:
                from models import SystemSettings
                v = SystemSettings.get_setting("assets_version", None)
                if v is not None and str(v).strip() != "":
                    version = int(float(v))
            except Exception:
                version = None
        if not version:
            version = app.config.setdefault("STATIC_VERSION", int(time.time()))
        if '?' in filename:
            return f"{filename}&v={version}"
        return f"{filename}?v={version}"

    def static_url(filename):
        url = url_for('static', filename=filename)
        return static_version_filter(url)
        
    @app.context_processor
    def inject_config():
        return dict(config=app.config)

    @app.context_processor
    def inject_common():
        return {"current_app": current_app, "get_unique_flashes": get_unique_flashes, "static_url": static_url}

    @app.context_processor
    def inject_branding_helpers():
        from models import SystemSettings as _SS
        from utils.branding_assets import build_static_url, rel_path_platform, rel_path_tenant

        def branding_url(scope="platform", slug=None, asset_type="logos", name="primary.png"):
            try:
                ver = _SS.get_setting("assets_version", "") or ""
            except Exception:
                ver = ""
            if scope == "tenant" and slug:
                rel = rel_path_tenant(slug, asset_type, name)
            else:
                rel = rel_path_platform(asset_type, name)
            return build_static_url(rel, assets_version=ver)

        return {"branding_url": branding_url}

    @app.context_processor
    def inject_permissions():
        def _get_user_perms_cached(u) -> set:
            if not getattr(u, "is_authenticated", False):
                return set()
            cached = getattr(g, "user_permissions_set", None)
            if isinstance(cached, set):
                return cached
            fn = getattr(utils, "_get_user_permissions", None)
            perms = fn(u) if callable(fn) else set()
            try:
                perms = {str(p).strip().lower() for p in (perms or set()) if str(p).strip()}
            except Exception:
                perms = set()
            g.user_permissions_set = perms
            return perms

        def _get_module_flags_cached() -> dict:
            cached = getattr(g, "module_enabled_flags", None)
            if isinstance(cached, dict):
                return cached
            cache_key = "system_settings:module_flags:v1"
            flags = cache.get(cache_key)
            if not isinstance(flags, dict):
                keys = [
                    "module_customers_enabled",
                    "module_service_enabled",
                    "module_warehouses_enabled",
                    "module_sales_enabled",
                    "module_vendors_enabled",
                    "module_partners_enabled",
                    "module_shipments_enabled",
                    "module_payments_enabled",
                    "module_checks_enabled",
                    "module_expenses_enabled",
                    "module_ledger_enabled",
                    "module_currencies_enabled",
                    "module_projects_enabled",
                    "module_workflows_enabled",
                ]
                try:
                    rows = SystemSettings.query.filter(SystemSettings.key.in_(keys)).all()
                    raw_map = {r.key: (r.value if r else None) for r in rows}
                    flags = {}
                    for k in keys:
                        v = raw_map.get(k)
                        if v is None:
                            flags[k] = True
                        else:
                            flags[k] = str(v).lower() not in {"0", "false", "no"}
                except Exception:
                    flags = {k: True for k in keys}
                cache.set(cache_key, flags, timeout=300)
            g.module_enabled_flags = flags
            return flags

        def has_perm(perm):
            try:
                if utils.is_super():
                    return True
                return str(perm).strip().lower() in _get_user_perms_cached(current_user)
            except Exception:
                return False
        def has_any(*perms):
            try:
                if utils.is_super():
                    return True
                perm_set = _get_user_perms_cached(current_user)
                for p in perms:
                    if str(p).strip().lower() in perm_set:
                        return True
                return False
            except Exception:
                return False

        def is_module_enabled(module_key: str) -> bool:
            key = f"module_{str(module_key or '').strip()}_enabled"
            flags = _get_module_flags_cached()
            return bool(flags.get(key, True))

        return {
            "has_perm": has_perm,
            "has_any": has_any,
            "get_module_flags": _get_module_flags_cached,
            "is_module_enabled": is_module_enabled,
        }

    @app.context_processor
    def inject_enums():
        return {
            "PaymentStatus": PaymentStatus,
            "PaymentDirection": PaymentDirection,
            "PaymentMethod": PaymentMethod,
            "PaymentEntityType": PaymentEntityType,
            "SaleStatus": SaleStatus,
            "ShipmentStatus": ShipmentStatus,
            "ServiceStatus": ServiceStatus,
            "WarehouseType": WarehouseType,
            "OnlinePaymentStatus": OnlinePaymentStatus,
            "OnlineCartStatus": OnlineCartStatus,
            "PreOrderStatus": PreOrderStatus,
            "CheckStatus": CheckStatus,
            "TransferDirection": TransferDirection,
            "TimesheetStatus": TimesheetStatus,
            "TaskStatus": TaskStatus,
            "EngineeringTaskStatus": EngineeringTaskStatus,
        }

    def url_for_any(*endpoints, **values):
        last_err = None
        tried = []
        for ep in endpoints:
            try:
                return url_for(ep, **values)
            except BuildError as e:
                last_err = e
                tried.append(ep)
                current_app.logger.warning("url_for_any miss: endpoint=%s values=%r", ep, values)
        strict_urls = app.config.get("STRICT_URLS", bool(app.debug))
        if strict_urls:
            raise last_err or BuildError("url_for_any", values, "Tried: " + ", ".join(tried))
        current_app.logger.error("url_for_any fallback: tried=%s values=%r", tried, values)
        try:
            return url_for("main.dashboard", _anchor=f"missing:{'|'.join(tried)}")
        except Exception:
            return "/?missing=" + ",".join(tried)

    app.jinja_env.filters["qr_to_base64"] = utils.qr_to_base64

    def _format_currency_filter(value, code=None):
        try:
            amount = float(value)
        except Exception:
            amount = 0.0
        cur = (code or "ILS").strip().upper()
        if cur == "ILS":
            return utils.format_currency(amount)
        symbol = {"USD": "$", "EUR": "€", "JOD": "JOD", "ILS": "₪"}.get(cur, cur)
        try:
            return f"{amount:,.2f} {symbol}"
        except Exception:
            return str(amount)

    app.jinja_env.filters["format_currency"] = _format_currency_filter
    app.jinja_env.filters["format_percent"] = utils.format_percent
    app.jinja_env.filters["yes_no"] = utils.yes_no
    app.jinja_env.filters["number_format"] = _safe_number_format
    app.jinja_env.filters["format_number"] = _safe_number_format
    app.jinja_env.filters["format_date"] = utils.format_date
    app.jinja_env.filters["format_datetime"] = utils.format_datetime
    app.jinja_env.filters["two_dec"] = _two_dec

    app.jinja_env.filters["format_currency_in_ils"] = utils.format_currency_in_ils
    app.jinja_env.globals["get_entity_balance_in_ils"] = utils.get_entity_balance_in_ils
    app.jinja_env.globals["url_for_any"] = url_for_any
    app.jinja_env.globals["now"] = lambda: datetime.now(timezone.utc)
    from utils.print_branding import get_scoped_setting

    app.jinja_env.globals["get_setting"] = get_scoped_setting
    app.jinja_env.globals["system_component_map"] = app.config.get("SYSTEM_COMPONENT_MAP", {})

    from translations.accounting_ar import get_all_translations
    app.jinja_env.globals["translations"] = get_all_translations()

    def _three_digits_to_words_ar(n: int) -> str:
        ones_words = ["","واحد","اثنان","ثلاثة","أربعة","خمسة","ستة","سبعة","ثمانية","تسعة"]
        tens_words = ["","عشرة","عشرون","ثلاثون","أربعون","خمسون","ستون","سبعون","ثمانون","تسعون"]
        teens_words = ["","أحد عشر","اثنا عشر","ثلاثة عشر","أربعة عشر","خمسة عشر","ستة عشر","سبعة عشر","ثمانية عشر","تسعة عشر"]
        hundreds_words = ["","مائة","مائتان","ثلاثمائة","أربعمائة","خمسمائة","ستمائة","سبعمائة","ثمانمائة","تسعمائة"]
        parts = []
        h = n // 100
        tu = n % 100
        o = n % 10
        t = (n // 10) % 10
        if h:
            parts.append(hundreds_words[h])
        if tu:
            if tu < 10:
                parts.append(ones_words[o])
            elif 10 <= tu < 20:
                if tu == 10:
                    parts.append("عشرة")
                else:
                    parts.append(teens_words[tu - 10])
            else:
                if o:
                    parts.append(ones_words[o])
                parts.append(tens_words[t])
        return " و ".join([p for p in parts if p])

    def amount_in_words(value, currency="ILS") -> str:
        try:
            amt = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            amt = Decimal("0.00")
        integer = int(amt)
        fraction = int((amt - Decimal(integer)) * 100)
        if integer == 0:
            integer_words = "صفر"
        else:
            groups = []
            scales = ["","ألف","مليون","مليار"]
            plurals = {"ألف": "آلاف", "مليون": "ملايين", "مليار": "مليارات"}
            i = 0
            n = integer
            while n > 0 and i < len(scales):
                g = n % 1000
                if g:
                    w = _three_digits_to_words_ar(g)
                    s = scales[i]
                    if s:
                        if g == 1 and i > 0:
                            groups.append(s)
                        elif g == 2 and i > 0:
                            if s == "ألف":
                                groups.append("ألفان")
                            elif s == "مليون":
                                groups.append("مليونان")
                            elif s == "مليار":
                                groups.append("ملياران")
                        elif 3 <= g <= 10 and i > 0:
                            groups.append(f"{w} {plurals.get(s, s)}")
                        else:
                            groups.append(f"{w} {s}")
                    else:
                        groups.append(w)
                n //= 1000
                i += 1
            integer_words = " و ".join(reversed(groups)).strip()
        if (currency or "ILS").upper() == "ILS":
            main_unit = "شيكل"
            sub_unit = "أغورة"
        elif (currency or "USD").upper() == "USD":
            main_unit = "دولار أمريكي"
            sub_unit = "سنت"
        elif (currency or "JOD").upper() == "JOD":
            main_unit = "دينار أردني"
            sub_unit = "قرش"
        else:
            main_unit = currency or "عملة"
            sub_unit = "جزء"
        result = f"{integer_words} {main_unit}"
        if fraction:
            frac_words = _three_digits_to_words_ar(fraction)
            result = f"{result} و {frac_words} {sub_unit}"
        return result

    app.jinja_env.filters["amount_in_words"] = amount_in_words
    app.jinja_env.filters["status_label"] = utils.status_label

    def currency_name_ar(code: str) -> str:
        code = (code or "").upper()
        if code == "ILS":
            return "شيكل"
        if code == "USD":
            return "دولار أمريكي"
        if code == "EUR":
            return "يورو"
        if code == "JOD":
            return "دينار أردني"
        return code or "عملة"

    app.jinja_env.globals["currency_name_ar"] = currency_name_ar

    @app.template_global()
    def csrf_token():
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()


def _register_blueprints(app):
    blueprints = [
        auth_bp,
        main_bp,
        tenant_console_bp,
        users_bp,
        service_bp,
        customers_bp,
        sales_bp,
        returns_bp,
        notes_bp,
        reports_bp,
        shop_bp,
        expenses_bp,
        vendors_bp,
        shipments_bp,
        warehouse_bp,
        branches_bp,
        payments_bp,
        permissions_bp,
        roles_bp,
        parts_bp,
        admin_reports_bp,
        bp_barcode,
        partner_settlements_bp,
        supplier_settlements_bp,
        api_bp,
        ledger_bp,
        currencies_bp,
        barcode_scanner_bp,
        ledger_control_bp,
        ai_bp,
        ai_admin_bp,
        user_guide_bp,
        other_systems_bp,
        pricing_bp,
        checks_bp,
        health_bp,
        security_bp,
        security_expenses_bp,
        advanced_bp,
        security_control_bp,
        archive_bp,
        archive_routes_bp,
        financial_reports_bp,
        accounting_validation_bp,
        accounting_docs_bp,
        budgets_bp,
        assets_bp,
        bank_bp,
        cost_centers_bp,
        cost_centers_advanced_bp,
        engineering_bp,
        projects_bp,
        project_advanced_bp,
        recurring_bp,
        workflows_bp,
        balances_api_bp,
        performance_bp,
    ]
    for bp in blueprints:
        app.register_blueprint(bp)


def _collect_model_classes():
    collected = []
    seen = set()
    stack = [db.Model]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            collected.append(sub)
            stack.append(sub)
    return [cls for cls in collected if hasattr(cls, "__tablename__")]


def _validate_system_integrity(app):
    allowed_route_duplicates = {
        ('/sales', ('GET',)),
        ('/reports', ('GET',)),
        ('/shipments', ('GET',)),
        ('/barcode/check-product', ('GET',)),
    }
    errors = []
    rule_index = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("static"):
            continue
        normalized_path = rule.rule.rstrip("/") or "/"
        methods = tuple(sorted(m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"}))
        key = (normalized_path, methods)
        if key in rule_index:
            if key not in allowed_route_duplicates:
                errors.append(f"Route conflict {normalized_path} {methods}: {rule.endpoint} duplicates {rule_index[key]}")
        else:
            rule_index[key] = rule.endpoint

    models = _collect_model_classes()
    table_map = {}
    for model_cls in models:
        table_name = getattr(model_cls, "__tablename__", None)
        if not table_name:
            continue
        if table_name in table_map and table_map[table_name] is not model_cls:
            errors.append(f"Duplicate model table name '{table_name}' between {model_cls.__name__} and {table_map[table_name].__name__}")
        else:
            table_map[table_name] = model_cls

    try:
        import forms as forms_module
        from flask_wtf import FlaskForm
        form_classes = []
        for attr in dir(forms_module):
            obj = getattr(forms_module, attr)
            if inspect.isclass(obj) and issubclass(obj, FlaskForm) and obj is not FlaskForm:
                form_classes.append(obj)
        form_names = {}
        for form_cls in form_classes:
            name = form_cls.__name__
            if name in form_names and form_names[name] is not form_cls:
                errors.append(f"Duplicate form class '{name}' detected")
            else:
                form_names[name] = form_cls
            meta = getattr(form_cls, "Meta", None)
            bound_model = getattr(meta, "model", None) if meta else None
            if bound_model is not None:
                if inspect.isclass(bound_model) and issubclass(bound_model, db.Model):
                    continue
                errors.append(f"Form {name} references invalid model '{bound_model}'")
    except Exception as exc:
        errors.append(f"Forms integrity check failed: {exc}")

    if errors:
        for msg in errors:
            app.logger.error("SYSTEM_INTEGRITY: %s", msg)
        raise RuntimeError("System integrity validation failed. Review logs for details.")

    app.logger.info("System integrity check passed: %s routes, %s models, %s forms",
                    len(rule_index), len(table_map), len(form_names if 'form_names' in locals() else []))


def _register_cors(app):
    if CORS is not None:
        origins = app.config.get("CORS_ORIGINS", ["http://localhost:5000"])
        supports_credentials = app.config.get("CORS_SUPPORTS_CREDENTIALS", True)
        has_wildcard = origins == "*" or (isinstance(origins, (list, tuple, set)) and "*" in origins)
        if supports_credentials and has_wildcard:
            app.logger.warning("CORS wildcard origin cannot be used safely with credentials; disabling CORS credentials for /api/*")
            supports_credentials = False
        CORS(
            app,
            resources={
                r"/api/*": {
                    "origins": origins,
                    "supports_credentials": supports_credentials,
                    "allow_headers": ["Content-Type", "Authorization", "X-CSRF-TOKEN"],
                    "methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "max_age": 3600,
                }
            },
        )


def _register_app_handlers(app):
    @app.after_request
    def security_headers(response):
        # Core security headers are now set in middleware/security_middleware.py
        # (apply_security_headers) to avoid duplication and conflicts.
        # This handler only sets CSP and cache / fingerprint headers.
        if not app.config.get('DEBUG'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://cdn.datatables.net https://cdnjs.cloudflare.com https://cdn.socket.io; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdn.datatables.net https://cdnjs.cloudflare.com; "
                "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://cdn.socket.io;"
            )

        response.headers.pop('Server', None)
        response.headers.pop('X-Powered-By', None)

        if request.path.startswith('/auth/') or request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        elif request.path.startswith('/static/'):
            response.cache_control.max_age = 31536000
            response.cache_control.public = True
        return response

    @app.shell_context_processor
    def _ctx():
        return {"db": db, "User": User}

    @app.after_request
    def _log_status(resp):
        if resp.status_code in (302, 401, 403, 404):
            loc = resp.headers.get("Location")
            app.logger.warning("HTTP %s %s -> %s", resp.status_code, request.path, loc or "")
        return resp

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.remove()

    @app.teardown_request
    def _rollback_on_error(exception=None):
        if exception is None:
            return
        try:
            db.session.rollback()
        except Exception:
            pass

    @app.errorhandler(403)
    def _forbidden(e):
        app.logger.error("403 FORBIDDEN: %s", request.path)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            from flask import jsonify
            return jsonify({"error": "غير مصرح لك بهذا الإجراء", "message": "غير مصرح لك بهذا الإجراء"}), 403
        try:
            return render_template("errors/403.html", path=request.path), 403
        except Exception:
            return ("403 Forbidden", 403)

    @app.errorhandler(404)
    def _not_found(e):
        app.logger.error("404 NOT FOUND: %s", request.path)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {"error": "Not Found"}, 404
        try:
            return render_template("errors/404.html", path=request.path), 404
        except Exception:
            return ("404 Not Found", 404)

    @app.context_processor
    def inject_global_flags():
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            is_super = utils.is_super() if hasattr(utils, 'is_super') else False
            return {"shop_is_super_admin": is_super}
        return {"shop_is_super_admin": False}

    @app.context_processor
    def inject_shop_helpers():
        def is_customer_actor(user):
            try:
                from models import Customer
                if not getattr(user, "is_authenticated", False):
                    return False
                if isinstance(user, Customer):
                    return True
                role_slug = getattr(getattr(user, "role", None), "slug", "") or ""
                return str(role_slug).strip().lower() == "customer"
            except Exception:
                return False
        return {"is_customer_actor": is_customer_actor}


def _init_ai_systems(app):
    try:
        import sys
        skip_cmds = ("db", "seed", "shell", "migrate", "upgrade", "downgrade", "routes")
        if any(cmd in sys.argv for cmd in skip_cmds):
            app.logger.info("AI systems skipped: CLI context.")
            return
    except Exception:
        pass
    try:
        import sys
        if (os.environ.get("GUNICORN_CMD_ARGS") or "gunicorn" in " ".join(sys.argv).lower()) and os.environ.get("ENABLE_AI_SYSTEMS") != "1":
            app.logger.info("AI systems skipped: gunicorn context (set ENABLE_AI_SYSTEMS=1 to enable).")
            return
    except Exception:
        pass
    try:
        import sys
        is_uwsgi = ("uwsgi" in sys.modules) or bool(os.environ.get("UWSGI_ORIGINAL_PROC_NAME") or os.environ.get("UWSGI_FILE"))
        is_pythonanywhere = bool(os.environ.get("PYTHONANYWHERE_DOMAIN") or os.environ.get("PYTHONANYWHERE_SITE"))
        if (is_uwsgi or is_pythonanywhere) and os.environ.get("ENABLE_AI_SYSTEMS") != "1":
            app.logger.info("AI systems skipped: WSGI/uWSGI context (set ENABLE_AI_SYSTEMS=1 to enable).")
            return
    except Exception:
        pass
    if app.config.get("TESTING", False):
        app.logger.info("AI systems disabled in testing mode.")
        return
    if not app.config.get("AI_SYSTEMS_ENABLED", True):
        app.logger.info("AI systems disabled via configuration.")
        return
    state = app.extensions.setdefault("ai_systems", {})
    if state.get("initialized"):
        return
    try:
        from AI.scheduler import start_scheduler
        start_scheduler(app)
    except Exception as exc:
        app.logger.warning(f"AI Scheduler start skipped: {exc}")
    try:
        from AI.engine.ai_event_listeners import register_ai_listeners
        register_ai_listeners(app)
    except Exception as exc:
        app.logger.warning(f"AI event listeners registration skipped: {exc}")
    state["initialized"] = True


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Fix: Silence Vite client 404 errors in development environments
    @app.route("/@vite/client")
    def vite_client_shim():
        return "", 200

    _configure_app(app, config_object)
    _init_extensions_stack(app)

    # SECURITY: CSRF protection is now enabled on ledger_bp.
    # Previously exempted via csrf.exempt(ledger_bp), which left
    # financial endpoints vulnerable to cross-site request forgery.
    
    @event.listens_for(db.session.__class__, "before_attach")
    def _dedupe_entities(session, instance):
        if isinstance(instance, (Role, Permission)) and getattr(instance, "id", None) is not None:
            key = session.identity_key(instance.__class__, (instance.id,))
            existing = session.identity_map.get(key)
            if existing is not None and existing is not instance:
                session.expunge(existing)

    login_manager.login_view = "auth.login"
    login_manager.anonymous_user = MyAnonymousUser
    try:
        login_manager.session_protection = None
    except Exception:
        pass

    os.environ.setdefault("PERMISSIONS_DEBUG", "0")
    os.environ.setdefault("G_MESSAGES_DEBUG", "")
    
    try:
        import warnings
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gi")
        warnings.filterwarnings("ignore", message=".*GLib-GIO.*")
        warnings.filterwarnings("ignore", message=".*Clipchamp.*")
    except Exception:
        pass
    
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("engineio").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    
    class GLibWarningFilter(logging.Filter):
        def filter(self, record):
            msg = str(record.getMessage())
            if "GLib-GIO" in msg or "Clipchamp" in msg or "UWP app" in msg:
                return False
            return True
    
    glib_filter = GLibWarningFilter()
    logging.getLogger().addFilter(glib_filter)
    
    app.logger.setLevel(logging.INFO)

    if app.config.get("SERVER_NAME"):
        from urllib.parse import urlparse
        def _relative_url_for(self, endpoint, **values):
            rv = Flask.url_for(self, endpoint, **values)
            if not values.get("_external"):
                parsed = urlparse(rv)
                rv = parsed.path + ("?" + parsed.query if parsed.query else "")
            return rv
        app.url_for = _relative_url_for.__get__(app, Flask)

    _register_template_support(app)

    from middleware.security_middleware import init_security_middleware
    init_security_middleware(app)

    # مصدر واحد للصلاحيات: permissions_config.blueprint_guards + enums.SystemPermissions
    _blueprints_for_acl = {
        "shop_bp": shop_bp,
        "users_bp": users_bp,
        "customers_bp": customers_bp,
        "vendors_bp": vendors_bp,
        "shipments_bp": shipments_bp,
        "warehouse_bp": warehouse_bp,
        "payments_bp": payments_bp,
        "expenses_bp": expenses_bp,
        "sales_bp": sales_bp,
        "service_bp": service_bp,
        "reports_bp": reports_bp,
        "financial_reports_bp": financial_reports_bp,
        "roles_bp": roles_bp,
        "permissions_bp": permissions_bp,
        "parts_bp": parts_bp,
        "admin_reports_bp": admin_reports_bp,
        "main_bp": main_bp,
        "partner_settlements_bp": partner_settlements_bp,
        "supplier_settlements_bp": supplier_settlements_bp,
        "api_bp": api_bp,
        "notes_bp": notes_bp,
        "bp_barcode": bp_barcode,
        "ledger_bp": ledger_bp,
        "ledger_control_bp": ledger_control_bp,
        "currencies_bp": currencies_bp,
        "barcode_scanner_bp": barcode_scanner_bp,
        "checks_bp": checks_bp,
        "balances_api_bp": balances_api_bp,
    }
    for _name, _opts in get_blueprint_guard_config():
        if _name in _blueprints_for_acl:
            attach_acl(_blueprints_for_acl[_name], **_opts)
    
    _init_ai_systems(app)
    _register_blueprints(app)
    if not app.config.get("SKIP_SYSTEM_INTEGRITY"):
        _validate_system_integrity(app)
    else:
        app.logger.warning("System integrity check skipped by configuration.")
        
    # --- LOAD SETTINGS FROM DB ---
    # This ensures that settings changed in the Security Dashboard (Email, Integrations)
    # are actually used by the application (overriding env vars).
    with app.app_context():
        try:
            from models import SystemSettings
            
            # 1. Mail Settings
            mail_keys = ['MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_USE_TLS', 'MAIL_USE_SSL', 'MAIL_DEFAULT_SENDER']
            mail_updated = False
            for key in mail_keys:
                val = SystemSettings.get_setting(key)
                if val:
                    # Convert types
                    if key == 'MAIL_PORT':
                        val = int(val)
                    elif key in ('MAIL_USE_TLS', 'MAIL_USE_SSL'):
                        val = str(val).lower() in ('true', '1', 'on', 'yes')
                    
                    app.config[key] = val
                    mail_updated = True
            
            # Re-init mail if settings changed (though usually app.config update is enough if done early)
            # from extensions import mail
            # mail.init_app(app) # Careful, this might attach twice
            
            # 2. Integration Settings (Map lowercase to uppercase config keys)
            integration_map = {
                'stripe_public_key': 'STRIPE_PUBLIC_KEY',
                'stripe_secret_key': 'STRIPE_SECRET_KEY',
                'paypal_client_id': 'PAYPAL_CLIENT_ID',
                'paypal_secret': 'PAYPAL_SECRET',
                'twilio_account_sid': 'TWILIO_ACCOUNT_SID',
                'twilio_auth_token': 'TWILIO_AUTH_TOKEN',
                'twilio_whatsapp_number': 'TWILIO_WHATSAPP_NUMBER',
            }
            
            for db_key, config_key in integration_map.items():
                val = SystemSettings.get_setting(db_key)
                if val:
                    app.config[config_key] = val
                    
        except Exception as e:
            app.logger.warning(f"Failed to load settings from DB: {e}")

    _register_cors(app)
    _register_app_handlers(app)

    @app.before_request
    def _touch_last_seen():
        if getattr(current_user, "is_authenticated", False):
            try:
                now = datetime.now(timezone.utc)
                model = current_user.__class__
                ident = getattr(current_user, "id", None)
                if ident is None:
                    return
                cache_key = f"last_seen:{model.__name__}:{ident}"
                last_ts = cache.get(cache_key)
                if last_ts and (now.timestamp() - float(last_ts)) < 3600:
                    return
                
                # Use a fresh session for this update to avoid polluting the main session
                # or getting blocked by a previous failure
                try:
                    db.session.query(model).filter_by(id=ident).update({"last_seen": now}, synchronize_session=False)
                    db.session.commit()
                    cache.set(cache_key, now.timestamp(), timeout=7200)
                except Exception:
                    db.session.rollback()
            except Exception:
                pass

    @app.before_request
    def _mark_request_start():
        g.request_start = time.perf_counter()

    @app.before_request
    def _attach_request_id():
        g.request_id = _safe_request_id(request.headers.get("X-Request-Id"))

    @app.before_request
    def _serve_microcache():
        try:
            seconds = int(app.config.get("PAGE_MICROCACHE_SECONDS") or 0)
        except Exception:
            seconds = 0
        if seconds <= 0:
            return
        if request.method != "GET":
            return
        if request.path.startswith(("/static/", "/auth/", "/api/", "/socket.io")):
            return
        cc = (request.headers.get("Cache-Control") or "").lower()
        if "no-store" in cc or "no-cache" in cc:
            return
        accept = request.headers.get("Accept") or ""
        if accept and ("text/html" not in accept and "*/*" not in accept):
            return
        user_key = "anon"
        if getattr(current_user, "is_authenticated", False):
            try:
                user_key = str(current_user.get_id() or "auth")
            except Exception:
                user_key = "auth"
        key = f"microhtml:{user_key}:{request.full_path}"
        g.microcache_key = key
        cached = cache.get(key)
        if not cached:
            return
        body = cached.get("body")
        if body is None:
            return
        resp = make_response(body)
        resp.headers["Content-Type"] = cached.get("content_type") or "text/html; charset=utf-8"
        resp.headers["X-Microcache"] = "HIT"
        return resp

    @app.after_request
    def _emit_request_id(resp):
        rid = getattr(g, "request_id", None)
        if rid:
            resp.headers["X-Request-Id"] = rid
        return resp

    @app.after_request
    def _store_microcache(resp):
        key = getattr(g, "microcache_key", None)
        if not key:
            return resp
        if resp.headers.get("X-Microcache") == "HIT":
            return resp
        try:
            seconds = int(app.config.get("PAGE_MICROCACHE_SECONDS") or 0)
        except Exception:
            seconds = 0
        if seconds <= 0:
            return resp
        if request.method != "GET":
            return resp
        if resp.status_code != 200:
            return resp
        if resp.headers.get("Set-Cookie"):
            return resp
        ctype = resp.headers.get("Content-Type") or ""
        if "text/html" not in ctype.lower():
            return resp
        body = resp.get_data()
        if not body:
            return resp
        cache.set(key, {"body": body, "content_type": ctype}, timeout=seconds)
        resp.headers["X-Microcache"] = "MISS"
        return resp

    @app.after_request
    def _access_log(resp):
        try:
            path = request.path
            if path.startswith('/static/') or path == '/favicon.ico' or path.startswith('/_'):
                return resp
            start = getattr(g, "request_start", None)
            elapsed_ms = None
            if start is not None:
                elapsed_ms = round((time.perf_counter() - float(start)) * 1000, 2)
            if resp.status_code >= 400 or (elapsed_ms is not None and elapsed_ms >= 250):
                app.logger.info(
                    "access",
                    extra={
                        "event": "http.access",
                        "method": request.method,
                        "path": path,
                        "status": resp.status_code,
                        "duration_ms": elapsed_ms,
                        "remote_ip": request.remote_addr,
                    },
                )
        except Exception:
            pass
        return resp

    @app.errorhandler(400)
    def _bad_request(e):
        app.logger.warning("400 BAD REQUEST: %s - %s", request.path, str(e))
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {"error": "Bad Request", "message": "طلب غير صالح"}, 400
        try:
            return render_template("errors/400.html", path=request.path, error="طلب غير صالح"), 400
        except Exception:
            return ("400 Bad Request", 400)

    @app.errorhandler(401)
    def _unauthorized(e):
        app.logger.warning("401 UNAUTHORIZED: %s", request.path)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {"error": "Unauthorized"}, 401
        try:
            return render_template("errors/401.html", path=request.path), 401
        except Exception:
            return ("401 Unauthorized", 401)

    @app.errorhandler(429)
    def _too_many_requests(e):
        app.logger.warning("429 TOO MANY REQUESTS: %s", request.path)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {"error": "Too Many Requests"}, 429
        try:
            return render_template("errors/429.html", path=request.path), 429
        except Exception:
            return ("429 Too Many Requests", 429)

    @app.errorhandler(MemoryError)
    def _memory_error(e):
        app.logger.error("MemoryError: %s", request.path)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {"error": "Memory Error", "message": "حجم البيانات كبير جداً. الرجاء تقليل حجم الطلب أو تقسيم البيانات."}, 413
        try:
            return render_template("errors/413.html", path=request.path, error="حجم البيانات كبير جداً"), 413
        except Exception:
            return ("413 Payload Too Large - حجم البيانات كبير جداً", 413)

    @app.errorhandler(500)
    def _err_500(e):
        if isinstance(e, MemoryError):
            return _memory_error(e)
        try:
            db.session.rollback()
        except Exception:
            pass
        app.logger.exception("unhandled", extra={"event": "app.error", "path": request.path})
        is_dev = bool(app.config.get("DEBUG")) or str(app.config.get("APP_ENV", "production")).lower() in {"dev", "development", "local"}
        if is_dev:
            import traceback
            return f"500 Internal Server Error: {str(e)}\n\n{traceback.format_exc()}", 500
        request_id = getattr(g, "request_id", None)
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return {
                "error": "Internal Server Error",
                "message": "حدث خطأ داخلي في الخادم. تم تسجيل الخطأ للمراجعة.",
                "request_id": request_id,
            }, 500
        try:
            return render_template("errors/500.html", path=request.path, request_id=request_id), 500
        except Exception:
            return ("500 Internal Server Error", 500)

    @app.errorhandler(502)
    def _bad_gateway(e):
        app.logger.error("502 BAD GATEWAY: %s", request.path)
        try:
            return render_template("errors/502.html"), 502
        except Exception:
            return ("502 Bad Gateway", 502)

    @app.errorhandler(503)
    def _service_unavailable(e):
        app.logger.error("503 SERVICE UNAVAILABLE: %s", request.path)
        try:
            return render_template("errors/503.html"), 503
        except Exception:
            return ("503 Service Unavailable", 503)

    @app.before_request
    def resolve_tenant_from_path():
        from flask import session
        tenant_slug = (request.environ.get("gm.tenant_slug") or "").strip()
        if not tenant_slug:
            g.tenant_slug = None
            g.tenant_schema = None
            if request.path.startswith("/console"):
                return abort(404)
            try:
                uid = str(session.get("_user_id") or "")
                if uid.startswith("t:"):
                    logout_user()
            except Exception:
                pass
            return None
        g.tenant_slug = tenant_slug
        try:
            tenant = TenantRegistry.query.filter_by(slug=tenant_slug).first()
        except Exception:
            tenant = None
        if not tenant or not getattr(tenant, "is_active", False):
            return abort(404)
        g.tenant_schema = getattr(tenant, "schema_name", None)
        if request.path.startswith(("/security", "/advanced")):
            return abort(404)
        try:
            if current_user.is_authenticated:
                uid = str(session.get("_user_id") or "")
                if uid.startswith("t:"):
                    parts = uid.split(":", 2)
                    if len(parts) != 3 or parts[1].lower() != tenant_slug.lower():
                        logout_user()
                        return redirect(url_for("auth.login", fresh=1))
                elif uid and uid[0].isdigit():
                    logout_user()
                    return redirect(url_for("auth.login", fresh=1))
        except Exception:
            pass

    @app.before_request
    def apply_tenant_search_path():
        schema = str(getattr(g, "tenant_schema", "") or "").strip()
        if not schema or schema.lower() == "public":
            return None
        try:
            if str(getattr(getattr(db, "engine", None), "dialect", None).name or "") != "postgresql":
                return None
        except Exception:
            return None
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        if not schema or len(schema) > 63 or any(ch not in allowed for ch in schema):
            return abort(404)
        try:
            from sqlalchemy import text as sa_text
            exists = db.session.execute(
                sa_text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema},
            ).scalar()
            if not exists:
                return abort(404)
            db.session.execute(sa_text(f"SET LOCAL search_path TO {schema}, public"))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return abort(500)

    @app.before_request
    def restrict_customer_from_admin():
        if getattr(current_user, "is_authenticated", False):
            role_slug = getattr(getattr(current_user, "role", None), "slug", None)
            if role_slug == "customer":
                allowed_paths = ("/shop", "/static", "/auth/logout")
                if not any(request.path.startswith(p) for p in allowed_paths):
                    return redirect(url_for("shop.catalog"))

    critical = app.config.get(
        "CRITICAL_ENDPOINTS",
        [
            "main.dashboard",
            "warehouse_bp.list",
            "vendors_bp.suppliers_list",
            "payments.index",
            "reports_bp.index",
            "customers_bp.list_customers",
            "users_bp.list_users",
            "service.list_requests",
            "sales_bp.index",
            "permissions.list",
            "roles.list_roles",
        ],
    )
    with app.app_context():
        existing_eps = {rule.endpoint for rule in app.url_map.iter_rules()}
        missing = [ep for ep in critical if ep and ep not in existing_eps]
        if missing:
            app.logger.error("Missing endpoints at startup: %s", ", ".join(missing))

    @app.context_processor
    def inject_system_settings():
        setting_keys = {
            'system_name', 'SystemName', 'company_name', 'CompanyName',
            'login_title', 'login_subtitle', 'footer_text',
            'custom_logo', 'custom_favicon',
            'assets_version',
            'multi_tenancy_enabled',
            'primary_color', 'secondary_color', 'sidebar_bg', 'sidebar_text',
            'COMPANY_ADDRESS', 'COMPANY_PHONE', 'COMPANY_EMAIL', 'TAX_NUMBER',
            'CURRENCY_SYMBOL', 'TIMEZONE',
            'maintenance_mode',
            'MARKETING_MODULES', 'MARKETING_APIS', 'MARKETING_INDEXES',
            'MARKETING_OTHER_SYSTEMS', 'MARKETING_PRICE_FROM_USD',
        }
        lookup_keys = set(setting_keys)
        lookup_keys.update(k.upper() for k in setting_keys)
        cache_key = 'system_settings:template_settings:v1'
        raw_settings = cache.get(cache_key)
        if not isinstance(raw_settings, dict):
            try:
                rows = SystemSettings.query.filter(SystemSettings.key.in_(list(lookup_keys))).all()
                raw_settings = {row.key: row.value for row in rows}
            except Exception:
                raw_settings = {}
            else:
                try:
                    cache.set(cache_key, raw_settings, timeout=120)
                except Exception as exc:
                    current_app.logger.warning("template_settings_cache_set_failed: %s", exc)

        def _coerce(val, default=None):
            if val is None:
                return default
            s = str(val).strip()
            low = s.lower()
            if low in ['true', '1', 'yes']:
                return True
            if low in ['false', '0', 'no']:
                return False
            return s

        def _get(key, default=None):
            return _coerce(raw_settings.get(key, raw_settings.get(str(key).upper())), default)

        from utils.branding_assets import (
            normalize_rel_path,
            rel_path_platform,
            resolve_active_branding,
            ASSET_FAVICONS,
            ASSET_LOGOS,
            FAVICON_FILE,
            LOGO_PRIMARY,
        )

        system_name_val = _get('system_name') or _get('SystemName') or 'أزاد لإدارة الكراج'
        company_name_val = _get('company_name') or _get('CompanyName') or 'شركة أزاد للأنظمة الذكية'

        assets_version = _get('assets_version', '') or ''

        custom_logo = _get('custom_logo')
        favicon_val = _get('custom_favicon', '') or ''

        tenant_name = ''
        try:
            if SystemSettings.get_setting('multi_tenancy_enabled', False):
                tenant_name = (request.environ.get("gm.tenant_slug") or "").strip()
                if not tenant_name:
                    host = (request.host or '').split(':')[0].strip().lower()
                    mapping_key = 'tenant_domains:v1'
                    domains = cache.get(mapping_key)
                    if not isinstance(domains, dict):
                        try:
                            rows = SystemSettings.query.filter(SystemSettings.key.like('tenant\\_%\\_domain', escape='\\')).all()
                        except Exception:
                            rows = []
                        domains = {}
                        for row in rows:
                            dom = str(row.value or '').strip().lower()
                            if not dom:
                                continue
                            key = str(row.key or '')
                            if key.startswith('tenant_') and key.endswith('_domain'):
                                name = key[len('tenant_'):-len('_domain')]
                                if name:
                                    domains[dom] = name
                        try:
                            cache.set(mapping_key, domains, timeout=300)
                        except Exception:
                            pass
                    tenant_name = domains.get(host) or ''
                if tenant_name:
                    tcn = SystemSettings.get_setting(f'tenant_{tenant_name}_company_name', '') or ''
                    if str(tcn).strip():
                        company_name_val = str(tcn).strip()
                    tsn = SystemSettings.get_setting(f'tenant_{tenant_name}_system_name', '') or ''
                    if str(tsn).strip():
                        system_name_val = str(tsn).strip()
        except Exception:
            tenant_name = ''

        branding = resolve_active_branding(
            tenant_slug=tenant_name or None,
            raw_settings=raw_settings,
            assets_version=assets_version,
        )
        logo_url = branding.get("logo_url") or url_for(
            "static", filename=normalize_rel_path("", default=rel_path_platform(ASSET_LOGOS, LOGO_PRIMARY))
        )
        favicon_url = branding.get("favicon_url") or url_for(
            "static", filename=normalize_rel_path(favicon_val, default=rel_path_platform(ASSET_FAVICONS, FAVICON_FILE))
        )
        header_url = branding.get("header_url") or ''

        settings = {
            'system_name': system_name_val,
            'company_name': company_name_val,
            'login_title': _get('login_title', 'مرحباً بك'),
            'login_subtitle': _get('login_subtitle', 'سجل دخولك للمتابعة'),
            'footer_text': _get('footer_text', 'جميع الحقوق محفوظة'),
            'custom_logo': branding.get('logo_rel') or custom_logo or '',
            'custom_logo_url': logo_url,
            'custom_favicon': branding.get('favicon_rel') or favicon_val,
            'custom_favicon_url': favicon_url,
            'custom_header_url': header_url,
            'branding_scope': branding.get('scope') or 'platform',
            'branding_tenant_slug': branding.get('tenant_slug'),
            'assets_version': assets_version,
            'primary_color': _get('primary_color', '#007bff'),
            'secondary_color': _get('secondary_color', '#1f2937'),
            'sidebar_bg': _get('sidebar_bg', '#111827'),
            'sidebar_text': _get('sidebar_text', '#f9fafb'),
            'COMPANY_ADDRESS': _get('COMPANY_ADDRESS', ''),
            'COMPANY_PHONE': _get('COMPANY_PHONE', ''),
            'COMPANY_EMAIL': _get('COMPANY_EMAIL', app.config.get("DEV_EMAIL", "rafideen.ahmadghannam@gmail.com")),
            'TAX_NUMBER': _get('TAX_NUMBER', ''),
            'CURRENCY_SYMBOL': _get('CURRENCY_SYMBOL', '$'),
            'TIMEZONE': _get('TIMEZONE', 'UTC'),
            'maintenance_mode': _get('maintenance_mode', False),
            'marketing_modules': _get('MARKETING_MODULES', '40+'),
            'marketing_apis': _get('MARKETING_APIS', '133'),
            'marketing_indexes': _get('MARKETING_INDEXES', '89'),
            'marketing_other_systems': _get('MARKETING_OTHER_SYSTEMS', '4'),
            'marketing_price_from_usd': _get('MARKETING_PRICE_FROM_USD', '500'),
        }

        from utils.print_branding import resolve_print_settings

        print_settings = resolve_print_settings(
            tenant_slug=tenant_name or None,
            raw_settings=raw_settings,
            branding=branding,
        )
        if tenant_name:
            if print_settings.get("company_name"):
                settings["company_name"] = print_settings["company_name"]
            if print_settings.get("system_name"):
                settings["system_name"] = print_settings["system_name"]
            for ck in ("COMPANY_ADDRESS", "COMPANY_PHONE", "COMPANY_EMAIL", "TAX_NUMBER"):
                if print_settings.get(ck):
                    settings[ck] = print_settings[ck]
            if print_settings.get("footer_text"):
                settings["footer_text"] = print_settings["footer_text"]

        system_appearance = {}
        return dict(
            system_settings=settings,
            system_appearance=system_appearance,
            print_settings=print_settings,
        )

    @app.context_processor
    def inject_gm_scope():
        from flask import g as flask_g
        from utils.branding_assets import (
            is_platform_owner_user,
            is_tenant_session_user,
        )
        tenant_slug = getattr(flask_g, "tenant_slug", None)
        in_tenant = bool(tenant_slug)
        from utils.branding_scope import branding_hub_url

        return dict(
            is_tenant_scope=in_tenant,
            is_platform_scope=not in_tenant,
            is_tenant_session=is_tenant_session_user(),
            is_platform_owner=is_platform_owner_user() and not in_tenant,
            gm_tenant_slug=tenant_slug,
            branding_hub_url=branding_hub_url,
        )
    
    @app.before_request
    def check_maintenance_mode():
        """فحص وضع الصيانة - المنطق المحسّن"""
        if request.path.startswith('/static/'):
            return None
        
        if request.path.startswith('/auth/'):
            return None
        
        if not current_user.is_authenticated:
            return None
        
        try:
            val = SystemSettings.get_setting("maintenance_mode", "False")
            if str(val).strip().lower() not in ['true', '1', 'yes']:
                return None
        except Exception:
            return None
        
        try:
            if (
                (hasattr(current_user, "has_permission") and current_user.has_permission("access_owner_dashboard"))
                or (hasattr(utils, "is_super") and utils.is_super())
                or current_user.id == 1
                or (getattr(current_user, "username", "") or "").lower() in ["owner", "admin"]
            ):
                return None
        except Exception:
            pass
        
        return render_template('maintenance.html'), 503

    from cli import register_cli
    register_cli(app)

    # ========== إضافة العملات الافتراضية تلقائياً ==========
    with app.app_context():
        try:
            from models import Currency, CURRENCY_CHOICES
            
            # التحقق من وجود عملات في قاعدة البيانات
            currency_count = Currency.query.count()
            
            # إذا لم تكن هناك عملات، أضف العملات الافتراضية
            if currency_count == 0:
                symbols = {
                    'ILS': 'ILS', 'USD': 'USD', 'EUR': 'EUR', 'JOD': 'JOD',
                    'AED': 'AED', 'SAR': 'SAR', 'EGP': 'EGP', 'GBP': 'GBP'
                }
                
                for code, name in CURRENCY_CHOICES:
                    currency = Currency(
                        code=code,
                        name=name,
                        symbol=symbols.get(code, code),
                        decimals=2,
                        is_active=True
                    )
                    db.session.add(currency)
                
                db.session.commit()
        except Exception as e:
            pass
    
    # ضمان وجود الأدوار الأساسية
    with app.app_context():
        try:
            from models import Role
            from permissions_config.permissions import PermissionsRegistry
            
            for role_name in PermissionsRegistry.ROLES.keys():
                existing = Role.query.filter_by(name=role_name).first()
                if not existing:
                    role_data = PermissionsRegistry.ROLES[role_name]
                    role = Role(
                        name=role_name,
                        description=role_data.get('description', '')
                    )
                    db.session.add(role)
            
            db.session.commit()
        except Exception:
            db.session.rollback()

    try:
        import notifications as _notifications_module
        getattr(_notifications_module, "Notification", None)
    except Exception:
        pass

    @app.after_request
    def _add_static_cache_headers(response):
        """Add cache headers for static files (1 year cache)"""
        if request.path.startswith('/static/'):
            # Cache for 1 year (31536000 seconds)
            response.headers['Cache-Control'] = 'public, max-age=31536000'
            if 'Pragma' in response.headers:
                del response.headers['Pragma']
        return response

    return app


def bootstrap_database():
    """
    🔧 Bootstrap Database - تهيئة أولية آمنة (Safe Bootstrap)
    
    1. Check for critical tables (users, system_settings).
    2. If MISSING -> Run db.create_all() (Safe for new installs).
    3. If EXISTS -> Check if migrations are current (using Alembic).
    4. Validate critical columns.
    """
    from models import db, SystemSettings, NotificationLog, TaxEntry, ExpenseType
    from sqlalchemy import inspect
    from flask_migrate import upgrade
    
    try:
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        # --- PHASE 1: Schema Initialization ---
        if 'users' not in existing_tables or 'system_settings' not in existing_tables:
            current_app.logger.warning("Critical tables missing. Initializing database schema...")
            db.create_all()
            current_app.logger.info("Database schema created successfully.")
        else:
            current_app.logger.info("Critical tables exist. Checking for migrations...")
            # Optional: Attempt to run migrations if alembic is set up
            # try:
            #     upgrade()
            #     current_app.logger.info("Database migrations applied.")
            # except Exception as e:
            #     current_app.logger.warning(f"Migration warning: {e}")

        # --- PHASE 2: Data Seeding (Idempotent) ---
        
        # 2. إضافة أنواع المصاريف الأساسية (إذا لم تكن موجودة)
        expense_types = [
            ('SALARY', 'راتب', 'رواتب الموظفين'),
            ('EMPLOYEE_ADVANCE', 'سلفة', 'سلف الموظفين'),
        ]
        
        for code, name, desc in expense_types:
            existing = ExpenseType.query.filter_by(code=code).first()
            if not existing:
                new_type = ExpenseType(code=code, name=name, description=desc)
                db.session.add(new_type)
        
        # 3. زرع الإعدادات الافتراضية
        default_settings = {
            'twilio_account_sid': ('', 'Twilio Account SID', 'string'),
            'twilio_auth_token': ('', 'Twilio Auth Token', 'string'),
            'twilio_phone_number': ('', 'Twilio Phone Number', 'string'),
            'inventory_manager_email': ('', 'Inventory Manager Email', 'string'),
        }
        
        for key, (value, desc, dtype) in default_settings.items():
            existing = SystemSettings.query.filter_by(key=key).first()
            if not existing:
                SystemSettings.set_setting(key, value, desc, data_type=dtype, is_public=False)
        
        db.session.commit()
        current_app.logger.info('Bootstrap & Validation completed successfully')
        
    except Exception as e:
        current_app.logger.error(f'Bootstrap failed: {e}')
        db.session.rollback()
        # In production, we might want to exit here, but for resilience we log and continue



if __name__ == '__main__':
    import atexit
    import signal
    
    print("Initializing application...")
    app = create_app()
    print("Application created.")
    
    # Bootstrap on first run
    with app.app_context():
        print("Running bootstrap_database...")
        bootstrap_database()
        print("Bootstrap completed.")
    
    def cleanup_on_exit():
        try:
            from AI.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass
        try:
            from extensions import socketio, scheduler
            if socketio.server:
                socketio.stop()
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception:
            pass
    
    atexit.register(cleanup_on_exit)
    
    def signal_handler(signum, frame):
        print(f"Signal {signum} received. Exiting...")
        try:
            from AI.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass
        try:
            from extensions import socketio, scheduler
            if socketio.server:
                socketio.stop()
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception:
            pass
        exit(0)
    
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        host = os.environ.get("HOST") or app.config.get("HOST") or "0.0.0.0"
        port = int(os.environ.get("PORT") or app.config.get("PORT") or 5000)
        print(f"Starting server on {host}:{port}...")
        # Werkzeug 3+ blocks development server without this flag; __main__ is for local runs only.
        socketio.run(
            app,
            debug=bool(app.config.get("DEBUG", False)),
            host=host,
            port=port,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
        print("Server stopped gracefully (socketio.run returned).")
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
    except Exception as e:
        print(f"\nServer error: {e}")
    finally:
        try:
            from AI.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass
        try:
            from extensions import socketio, scheduler
            if socketio.server:
                socketio.stop()
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception:
            pass
else:
    app = create_app()
    application = app
