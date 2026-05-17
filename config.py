import os
import logging
import secrets
from base64 import urlsafe_b64decode
from datetime import timedelta
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")
os.makedirs(instance_dir, exist_ok=True)

load_dotenv(os.path.join(basedir, ".env"), override=True)
load_dotenv(os.path.join(basedir, ".env.txt"), override=True)


def _bool(v: str | None, default: bool = False) -> bool:
    s = (v if v is not None else str(default)).strip().lower()
    return s in ("true", "1", "yes", "y")


def _int(env_name: str, default: int) -> int:
    try:
        return int(os.environ.get(env_name, str(default)))
    except Exception:
        return default


def _float(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name, str(default)))
    except Exception:
        return default


def _csv_int(env_name: str) -> list[int] | None:
    raw = os.environ.get(env_name, "")
    vals: list[int] = []
    for x in raw.split(","):
        s = x.strip()
        if not s:
            continue
        try:
            vals.append(int(s))
        except Exception:
            continue
    return vals or None


def _csv_str(env_name: str, default_list: list[str] | tuple[str, ...]) -> list[str]:
    raw = os.environ.get(env_name, "")
    vals = [x.strip() for x in raw.split(",") if x.strip()]
    return vals or list(default_list)


def _build_pg_uri_from_env() -> str | None:
    host = os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST") or os.environ.get("POSTGRESQL_HOST")
    database = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB") or os.environ.get("POSTGRESQL_DATABASE")
    username = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER") or os.environ.get("POSTGRESQL_USER")
    password = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD") or os.environ.get("POSTGRESQL_PASSWORD")
    port_raw = os.environ.get("PGPORT") or os.environ.get("POSTGRES_PORT") or os.environ.get("POSTGRESQL_PORT") or ""

    if not host or not database or not username:
        return None

    try:
        port = int(port_raw) if port_raw else 5432
    except Exception:
        port = 5432

    user_enc = quote_plus(str(username))
    if password:
        auth = f"{user_enc}:{quote_plus(str(password))}"
    else:
        auth = user_enc

    return f"postgresql://{auth}@{host}:{port}/{database}"


class Config:
    FLASK_APP = os.environ.get("FLASK_APP", "app:create_app")

    APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "production"))
    DEBUG = _bool(os.environ.get("DEBUG"), False)
    
    AI_SYSTEMS_ENABLED = _bool(os.environ.get("AI_SYSTEMS_ENABLED"), True)
    ENABLE_AUTOMATED_BACKUPS = _bool(os.environ.get("ENABLE_AUTOMATED_BACKUPS"), True)
    SYSTEM_COMPONENT_MAP = {
        "accounting": [
            "sales",
            "payments",
            "checks",
            "expenses",
            "ledger",
            "reports",
            "currencies",
            "budgets",
            "assets",
            "bank",
            "cost_centers",
            "cost_centers_advanced",
        ],
        "inventory": [
            "warehouses",
            "shipments",
            "vendors",
            "partners",
            "parts",
            "shop",
            "barcode",
            "barcode_scanner",
        ],
        "security": [
            "auth",
            "users",
            "roles",
            "permissions",
            "security",
            "security_control",
            "security_expenses",
        ],
        "ai": [
            "ai",
            "ai_admin",
            "ai_scheduler",
            "ai_event_listeners",
            "ai_systems",
        ],
    }
    AUTO_CREATE_PERFORMANCE_INDEXES = _bool(os.environ.get("AUTO_CREATE_PERFORMANCE_INDEXES"), True)
    _APP_ENV_LOWER = str(APP_ENV).lower()
    _IS_DEV = DEBUG or (_APP_ENV_LOWER in {"dev", "development", "local"})

    PERF_MONITOR_ENABLED = _bool(os.environ.get("PERF_MONITOR_ENABLED"), _IS_DEV)
    PERF_MONITOR_PERSIST_PATH = os.environ.get("PERF_MONITOR_PERSIST_PATH", "")

    # SECURITY: SECRET_KEY يجب أن يكون قوي في الإنتاج
    _secret_env = os.environ.get("SECRET_KEY")
    if _secret_env:
        SECRET_KEY = _secret_env
    else:
        _secret_path = os.path.join(instance_dir, "secret_key")
        _persisted = None
        try:
            if os.path.exists(_secret_path):
                with open(_secret_path, "r", encoding="utf-8") as f:
                    _persisted = (f.read() or "").strip()
        except Exception:
            _persisted = None
        if _persisted:
            SECRET_KEY = _persisted
        else:
            SECRET_KEY = secrets.token_hex(32)
            try:
                with open(_secret_path, "w", encoding="utf-8") as f:
                    f.write(SECRET_KEY)
            except Exception:
                pass

    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = _int("PORT", 5000)

    _db_uri = os.environ.get("DATABASE_URL") or _build_pg_uri_from_env()

    # Fallback to SQLite if no DB configured (Useful for simple deployments/testing)
    if not _db_uri:
        # Default to SQLite in instance folder
        sqlite_db_path = os.path.join(instance_dir, "garage.db")
        _db_uri = f"sqlite:///{sqlite_db_path}"
        # print(f"WARNING: No DATABASE_URL found. Using SQLite: {_db_uri}")

    if _db_uri.startswith("postgres://"):
        _db_uri = _db_uri.replace("postgres://", "postgresql://", 1)

    if _db_uri.startswith("sqlite:///"):
        sqlite_path = _db_uri[len("sqlite:///"):]
        if sqlite_path and sqlite_path != ":memory:":
            if not os.path.isabs(sqlite_path):
                sqlite_path = os.path.abspath(os.path.join(basedir, sqlite_path))
            sqlite_path = sqlite_path.replace("\\", "/")
            _db_uri = f"sqlite:///{sqlite_path}"
            sqlite_parent = os.path.dirname(sqlite_path)
            if sqlite_parent:
                os.makedirs(sqlite_parent, exist_ok=True)
    
    # Allow PostgreSQL, MySQL, and SQLite
    if not _db_uri.startswith(("postgresql://", "mysql://", "mysql+pymysql://", "sqlite://")):
        # If it doesn't match known schemes, we warn but allow it (could be other drivers)
        pass 

    if _db_uri.startswith("postgresql://") and _bool(os.environ.get("DB_SSLMODE_REQUIRE"), False):
        _db_uri += ("&" if "?" in _db_uri else "?") + "sslmode=require"
        
    SQLALCHEMY_DATABASE_URI = _db_uri

    SQLALCHEMY_TRACK_MODIFICATIONS = _bool(os.environ.get("SQLALCHEMY_TRACK_MODIFICATIONS"), False)
    
    _default_pool_size = 100
    _default_max_overflow = 200

    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {},
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_size": _int("SQLALCHEMY_POOL_SIZE", _default_pool_size),
        "max_overflow": _int("SQLALCHEMY_MAX_OVERFLOW", _default_max_overflow),
        "pool_timeout": _int("SQLALCHEMY_POOL_TIMEOUT", 30),
        "echo": False,
        "echo_pool": False,
    }

    if _db_uri.startswith(("postgresql://", "postgres://")):
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"].update({
            "connect_timeout": 10,
            "application_name": "garage_manager",
            # Performance & Stability Tuning
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        })
    elif _db_uri.startswith("sqlite://"):
        # SQLite يستخدم StaticPool عادةً، وخيارات مثل pool_size غير مدعومة
        SQLALCHEMY_ENGINE_OPTIONS.update({
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        })
        for k in ("pool_size", "max_overflow", "pool_timeout"):
            SQLALCHEMY_ENGINE_OPTIONS.pop(k, None)
    
    SQLALCHEMY_ECHO = False
    
    # Template auto-reload (will be set based on DEBUG in app.py)
    TEMPLATES_AUTO_RELOAD = _bool(os.environ.get("TEMPLATES_AUTO_RELOAD"), True)

    JSON_AS_ASCII = False
    JSON_SORT_KEYS = False

    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = False if _IS_DEV else _bool(os.environ.get("SESSION_COOKIE_SECURE"), not DEBUG)
    REMEMBER_COOKIE_DURATION = timedelta(days=_int("REMEMBER_DAYS", 14))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=_int("SESSION_HOURS", 12))
    SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "gm_session")

    # SECURITY: حد أقصى لحجم الملفات المرفوعة (8 MB)
    MAX_CONTENT_LENGTH = _int("MAX_CONTENT_LENGTH_MB", 8) * 1024 * 1024
    
    # SECURITY: أنواع الملفات المسموح برفعها
    ALLOWED_UPLOAD_EXTENSIONS = {
        'images': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'},
        'documents': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt'},
        'all': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt'}
    }
    
    # SECURITY: الحد الأقصى لمحاولات تسجيل الدخول الفاشلة
    MAX_LOGIN_ATTEMPTS = _int("MAX_LOGIN_ATTEMPTS", 5)
    LOGIN_BLOCK_DURATION = _int("LOGIN_BLOCK_DURATION_MINUTES", 15) * 60  # بالثواني
    
    # SECURITY: حماية متقدمة
    ENABLE_TIMING_ATTACK_PROTECTION = _bool(os.environ.get("ENABLE_TIMING_ATTACK_PROTECTION"), True)
    ENABLE_RACE_CONDITION_PROTECTION = _bool(os.environ.get("ENABLE_RACE_CONDITION_PROTECTION"), True)
    MAX_AMOUNT_CHANGE_PERCENT = _float("MAX_AMOUNT_CHANGE_PERCENT", 50.0)  # أقصى تغيير مسموح في المبالغ
    SUSPICIOUS_ACTIVITY_LOG_ENABLED = _bool(os.environ.get("SUSPICIOUS_ACTIVITY_LOG_ENABLED"), True)

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = _int("MAIL_PORT", 587)
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USE_SSL = _bool(os.environ.get("MAIL_USE_SSL"), False)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "noreply@azad.local")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "dummy_password")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "MyApp <noreply@example.com>")

    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)

    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")
    SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE")
    # SECURITY: تقييد SocketIO CORS للأمان - لا تستخدم "*" في الإنتاج
    _sock_cors_raw = os.environ.get("SOCKETIO_CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000")
    SOCKETIO_CORS_ORIGINS = [x.strip() for x in _sock_cors_raw.split(",")] if "," in _sock_cors_raw else _sock_cors_raw
    SOCKETIO_PING_TIMEOUT = _int("SOCKETIO_PING_TIMEOUT", 20)
    SOCKETIO_PING_INTERVAL = _int("SOCKETIO_PING_INTERVAL", 25)
    SOCKETIO_MAX_HTTP_BUFFER_SIZE = _int("SOCKETIO_MAX_HTTP_BUFFER_SIZE", 100_000_000)

    WTF_CSRF_ENABLED = _bool(os.environ.get("WTF_CSRF_ENABLED"), True)
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_CHECK_DEFAULT = True
    WTF_CSRF_SSL_STRICT = False if _IS_DEV else _bool(os.environ.get("WTF_CSRF_SSL_STRICT"), True)

    if str(APP_ENV).lower() == 'local':
            WTF_CSRF_SKIP_REFERER_VERIFICATION = True
            WTF_CSRF_ENABLED = False # Disable CSRF for local testing to avoid 400 Bad Request
            WTF_CSRF_CHECK_DEFAULT = False # Explicitly disable default check

    # استثناء blueprint المخازن من CSRF إذا لزم
    # csrf.exempt(warehouse_bp)

    # SECURITY: تقييد CORS للأمان - لا تستخدم "*" في الإنتاج
    _cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000")
    CORS_ORIGINS = [x.strip() for x in _cors_raw.split(",")] if "," in _cors_raw else _cors_raw
    CORS_SUPPORTS_CREDENTIALS = _bool(os.environ.get("CORS_SUPPORTS_CREDENTIALS"), True)

    # SECURITY: Rate Limiting محسّن للحماية من Brute Force
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "100 per day;20 per hour;5 per minute")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = _bool(os.environ.get("RATELIMIT_HEADERS_ENABLED"), True)
    # حدود خاصة لصفحة تسجيل الدخول
    RATELIMIT_LOGIN = "10 per hour;3 per minute"
    RATELIMIT_API = "60 per hour;1 per second"
    
    # Cache - تحسين التخزين المؤقت
    CACHE_TYPE = os.environ.get("CACHE_TYPE", "flask_caching.backends.simplecache.SimpleCache")
    CACHE_REDIS_URL = os.environ.get("CACHE_REDIS_URL", REDIS_URL)
    CACHE_DEFAULT_TIMEOUT = _int("CACHE_DEFAULT_TIMEOUT", 1800)
    CACHE_KEY_PREFIX = os.environ.get("CACHE_KEY_PREFIX", "garage_manager")
    CACHE_THRESHOLD = _int("CACHE_THRESHOLD", 500)

    ITEMS_PER_PAGE = _int("ITEMS_PER_PAGE", 200)
    MAX_ITEMS_PER_PAGE = _int("MAX_ITEMS_PER_PAGE", 500)
    SHOP_PREPAID_RATE = _float("SHOP_PREPAID_RATE", 0.20)
    SHOP_WAREHOUSE_IDS = _csv_int("SHOP_WAREHOUSE_IDS")
    SHOP_WAREHOUSE_TYPES = _csv_str("SHOP_WAREHOUSE_TYPES", ["MAIN", "INVENTORY"])

    USE_PROXYFIX = _bool(os.environ.get("USE_PROXYFIX"), False)
    PREFERRED_URL_SCHEME = "https" if not DEBUG else "http"

    DEV_EMAIL = os.environ.get("DEV_EMAIL", "rafideen.ahmadghannam@gmail.com")
    PASSWORD_HASH_METHOD = os.environ.get("PASSWORD_HASH_METHOD", "scrypt")
    CARD_ENC_KEY = os.environ.get("CARD_ENC_KEY", "")
    REVEAL_PAN_ENABLED = _bool(os.environ.get("REVEAL_PAN_ENABLED"), False)

    DEFAULT_PRODUCT_IMAGE = os.environ.get("DEFAULT_PRODUCT_IMAGE", "products/default.png")

    SUPER_USER_EMAILS = os.environ.get("SUPER_USER_EMAILS", "")
    SUPER_USER_IDS = os.environ.get("SUPER_USER_IDS", "")
    ADMIN_USER_EMAILS = os.environ.get("ADMIN_USER_EMAILS", "")
    ADMIN_USER_IDS = os.environ.get("ADMIN_USER_IDS", "")
    PERMISSIONS_REQUIRE_ALL = _bool(os.environ.get("PERMISSIONS_REQUIRE_ALL"), False)

    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(instance_dir, "backups"))
    BACKUP_DB_DIR = BACKUP_DIR
    BACKUP_SQL_DIR = os.environ.get("BACKUP_SQL_DIR", os.path.join(BACKUP_DIR, "sql"))
    os.makedirs(BACKUP_DB_DIR, exist_ok=True)
    os.makedirs(BACKUP_SQL_DIR, exist_ok=True)
    BACKUP_KEEP_LAST = _int("BACKUP_KEEP_LAST", 5)
    BACKUP_DB_INTERVAL = timedelta(hours=1)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    JSON_LOGS = _bool(os.environ.get("JSON_LOGS"), False)

    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    SENTRY_PROFILES_SAMPLE_RATE = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.0"))

    APP_VERSION = os.environ.get("APP_VERSION", None)

    IMPORT_TMP_DIR = os.environ.get("IMPORT_TMP_DIR") or os.path.join(instance_dir, "imports")
    IMPORT_REPORT_DIR = os.environ.get("IMPORT_REPORT_DIR") or os.path.join(instance_dir, "imports", "reports")
    os.makedirs(IMPORT_TMP_DIR, exist_ok=True)
    os.makedirs(IMPORT_REPORT_DIR, exist_ok=True)

    ONLINE_GATEWAY_DEFAULT = (os.environ.get("ONLINE_GATEWAY_DEFAULT") or "blooprint").lower()
    BLOOPRINT_WEBHOOK_SECRET = os.environ.get("BLOOPRINT_WEBHOOK_SECRET", "")

    DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "ILS")
    GL_AUTO_POST_ON_EXCHANGE = _bool(os.environ.get("GL_AUTO_POST_ON_EXCHANGE"), False)
    GL_EXCHANGE_INV_ACCOUNT = os.environ.get("GL_EXCHANGE_INV_ACCOUNT", "1205_INV_EXCHANGE")
    GL_EXCHANGE_COGS_ACCOUNT = os.environ.get("GL_EXCHANGE_COGS_ACCOUNT", "5105_COGS_EXCHANGE")
    GL_EXCHANGE_AP_ACCOUNT = os.environ.get("GL_EXCHANGE_AP_ACCOUNT", "2000_AP")


def ensure_runtime_dirs(cfg) -> None:
    paths = [
        getattr(cfg, "BACKUP_DIR", None),
        getattr(cfg, "BACKUP_DB_DIR", None),
        getattr(cfg, "BACKUP_SQL_DIR", None),
        getattr(cfg, "IMPORT_TMP_DIR", None),
        getattr(cfg, "IMPORT_REPORT_DIR", None),
        instance_dir,
    ]
    for p in paths:
        if p:
            try:
                os.makedirs(p, exist_ok=True)
            except Exception as e:
                logging.warning("cannot create directory %s: %s", p, e)


def assert_production_sanity(cfg) -> None:
    debug = getattr(cfg, "DEBUG", False)
    app_env = str(getattr(cfg, "APP_ENV", "production")).lower()
    is_prod = (not debug) and (app_env not in {"dev", "development", "local"})
    sk = getattr(cfg, "SECRET_KEY", None)
    if is_prod and sk in {"production-secret-key-2024", "change-me", "secret", "dev-secret-key"}:
        raise RuntimeError("SECRET_KEY is a well-known default — change it immediately")
    if is_prod and (not sk or len(sk or "") < 16):
        raise RuntimeError("SECRET_KEY is missing or too weak for production (min 16 chars)")
    db_uri = getattr(cfg, "SQLALCHEMY_DATABASE_URI", "")
    if is_prod and not db_uri:
        raise RuntimeError("DATABASE_URL/SQLALCHEMY_DATABASE_URI missing")
    if is_prod and getattr(cfg, "MAIL_SERVER", "") and (not getattr(cfg, "MAIL_USERNAME", "") or not getattr(cfg, "MAIL_PASSWORD", "")):
        logging.warning("CONFIG WARNING: mail credentials missing")
    if getattr(cfg, "RATELIMIT_HEADERS_ENABLED", True) and not getattr(cfg, "RATELIMIT_STORAGE_URI", ""):
        logging.warning("CONFIG WARNING: ratelimit storage not set")
    key = getattr(cfg, "CARD_ENC_KEY", "") or ""
    if is_prod and key:
        try:
            b = urlsafe_b64decode(key)
            if len(b) != 32:
                raise RuntimeError("CARD_ENC_KEY invalid length")
        except Exception:
            raise RuntimeError("CARD_ENC_KEY invalid base64")
    if is_prod and not getattr(cfg, "SESSION_COOKIE_SECURE", True):
        logging.warning("CONFIG WARNING: SESSION_COOKIE_SECURE disabled in production")


logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
