from __future__ import annotations

import json
import logging
import os
import sys
import glob
from datetime import datetime, timezone

from flask import g, has_request_context
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_caching import Cache
try:
    from flask_compress import Compress
except ImportError:
    class Compress:
        def __init__(self, *args, **kwargs):
            pass
        def init_app(self, app):
            pass
from sqlalchemy import event, func
from sqlalchemy.engine import Engine

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except Exception:
    pdfmetrics = None
    TTFont = None

try:
    from colorama import init as colorama_init, Fore, Style
    # colorama_init(autoreset=True) # DISABLED to prevent UnicodeEncodeError on Windows
except Exception:
    class _Fore:
        BLUE = ""; GREEN = ""; YELLOW = ""; RED = ""
    class _Style:
        BRIGHT = ""; RESET_ALL = ""
    Fore, Style = _Fore(), _Style()
    def colorama_init(*args, **kwargs):
        return

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
except Exception:
    sentry_sdk = None


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
        else:
            record.request_id = "-"
        return True


class GLibWarningFilter(logging.Filter):
    def filter(self, record):
        msg = str(record.getMessage())
        if any(keyword in msg for keyword in ["GLib-GIO", "Clipchamp", "UWP app", "GIO-WARNING"]):
            return False
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for k, v in record.__dict__.items():
            if k.startswith("_"):
                continue
            if k in (
                "name","msg","args","levelname","levelno","pathname","filename",
                "module","exc_info","exc_text","stack_info","lineno","funcName",
                "created","msecs","relativeCreated","thread","threadName",
                "processName","process","request_id"
            ):
                continue
            try:
                json.dumps({k: v})
                base[k] = v
            except Exception:
                base[k] = str(v)
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG":   Fore.BLUE,
        "INFO":    Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR":   Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = Style.RESET_ALL
        req_id = getattr(record, "request_id", "-")
        base = f"[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}] {color}{record.levelname}{reset} {req_id} {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(app):
    level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    out_handler = logging.StreamHandler(sys.stdout)
    out_handler.setLevel(level)
    out_handler.addFilter(RequestIdFilter())
    out_handler.addFilter(GLibWarningFilter())
    out_handler.setFormatter(JSONFormatter() if app.config.get("JSON_LOGS") else ColorFormatter())

    err_handler = logging.StreamHandler(sys.stderr)
    err_handler.setLevel(logging.ERROR)
    err_handler.addFilter(RequestIdFilter())
    err_handler.addFilter(GLibWarningFilter())
    err_handler.setFormatter(JSONFormatter() if app.config.get("JSON_LOGS") else ColorFormatter())

    for lg in (app.logger, logging.getLogger(), logging.getLogger("sqlalchemy.engine")):
        lg.handlers.clear()
        lg.setLevel(level)
        lg.addHandler(out_handler)
        lg.addHandler(err_handler)
        lg.propagate = False

    if not app.config.get("SQLALCHEMY_ECHO", False):
        for name in (
            "sqlalchemy.engine",
            "sqlalchemy.engine.Engine",
            "sqlalchemy.orm",
            "sqlalchemy.pool",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("werkzeug", "engineio", "socketio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_sentry(app):
    dsn = (app.config.get("SENTRY_DSN") or "").strip()
    if not dsn or not sentry_sdk:
        app.logger.info("Sentry disabled (no DSN configured).")
        return
    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.0),
            profiles_sample_rate=app.config.get("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
            environment=app.config.get("APP_ENV", "production"),
            release=app.config.get("APP_VERSION") or None,
            send_default_pii=False,
            max_breadcrumbs=100,
        )
        app.logger.info("Sentry initialized.")
    except Exception as e:
        app.logger.warning("Sentry setup failed: %s", e)


db = SQLAlchemy(session_options={"expire_on_commit": False})

migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
compress = Compress()
socketio = SocketIO(cors_allowed_origins="*", logger=False, engineio_logger=False)

# نظام الإشعارات الفورية
def send_notification(user_id: int, notification_type: str, title: str, message: str, data: dict = None):
    """
    إرسال إشعار فوري للمستخدم
    
    ⚠️ معطّل: كان يسبب تعليق في النظام
    """
    # ❌ معطّل مؤقتاً - كان يسبب مشاكل أداء
    return
    
    # الكود القديم (معطّل):
    # try:
    #     notification = {
    #         "type": notification_type,
    #         "title": title,
    #         "message": message,
    #         "timestamp": datetime.now(timezone.utc).isoformat(),
    #         "data": data or {}
    #     }
    #     socketio.emit('notification', notification, room=f'user_{user_id}')
    # except Exception as e:
    #     logging.getLogger(__name__).error(f"Failed to send notification: {e}")

def send_broadcast_notification(notification_type: str, title: str, message: str, data: dict = None):
    """
    إرسال إشعار عام لجميع المستخدمين
    
    ⚠️ معطّل: كان يسبب تعليق في النظام
    """
    # ❌ معطّل مؤقتاً - كان يسبب مشاكل أداء
    return
    
    # الكود القديم (معطّل):
    # try:
    #     notification = {
    #         "type": notification_type,
    #         "title": title,
    #         "message": message,
    #         "timestamp": datetime.now(timezone.utc).isoformat(),
    #         "data": data or {}
    #     }
    #     socketio.emit('broadcast_notification', notification)
    # except Exception as e:
    #     logging.getLogger(__name__).error(f"Failed to send broadcast notification: {e}")

def send_system_alert(alert_type: str, message: str, severity: str = "warning"):
    """
    إرسال تنبيه نظام
    
    ⚠️ معطّل: كان يسبب تعليق في النظام
    """
    # ❌ معطّل مؤقتاً - كان يسبب مشاكل أداء
    return
    
    # الكود القديم (معطّل):
    # try:
    #     alert = {
    #         "type": "system_alert",
    #         "alert_type": alert_type,
    #         "message": message,
    #         "severity": severity,
    #         "timestamp": datetime.now(timezone.utc).isoformat()
    #     }
    #     socketio.emit('system_alert', alert)
    # except Exception as e:
    #     logging.getLogger(__name__).error(f"Failed to send system alert: {e}")
cache = Cache()


def _rate_limit_key():
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return f"user:{current_user.get_id()}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(key_func=_rate_limit_key, default_limits=[])
scheduler = BackgroundScheduler()


def _record_scheduler_failure(app, payload):
    state = app.extensions.setdefault("scheduler_failures", {"items": []})
    items = state.get("items")
    if not isinstance(items, list):
        items = []
        state["items"] = items
    items.append(payload)
    limit = int(app.config.get("SCHEDULER_FAILURES_LIMIT", 200) or 200)
    if len(items) > limit:
        del items[:-limit]


def init_scheduler_monitor(app):
    state = app.extensions.setdefault("scheduler_monitor", {})
    if state.get("initialized"):
        return

    def _listener(event):
        try:
            payload = {
                "job_id": getattr(event, "job_id", None),
                "event_code": getattr(event, "code", None),
                "scheduled_run_time": getattr(event, "scheduled_run_time", None),
                "exception": str(getattr(event, "exception", "") or ""),
                "traceback": str(getattr(event, "traceback", "") or ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _record_scheduler_failure(app, payload)
            if getattr(event, "exception", None):
                app.logger.warning("Scheduler job failed: %s", payload["job_id"])
            else:
                app.logger.warning("Scheduler job missed: %s", payload["job_id"])
        except Exception:
            pass

    try:
        scheduler.add_listener(_listener, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        state["initialized"] = True
    except Exception:
        pass


def register_scheduler_job(app, job_id, func, trigger, **kwargs):
    try:
        scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
    except Exception as e:
        try:
            app.logger.warning("Scheduler job registration failed: %s", e)
        except Exception:
            pass
        try:
            payload = {
                "job_id": job_id,
                "event_code": None,
                "scheduled_run_time": None,
                "exception": str(e),
                "traceback": "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _record_scheduler_failure(app, payload)
        except Exception:
            pass

def _get_pg_bin(bin_name: str) -> str:
    import shutil

    path = shutil.which(bin_name)
    if path:
        return path

    if os.name == "nt":
        common_versions = ["18", "17", "16", "15", "14", "13", "12"]
        for ver in common_versions:
            candidate = os.path.join(r"C:\Program Files\PostgreSQL", ver, "bin", f"{bin_name}.exe")
            if os.path.exists(candidate):
                return candidate
            candidate_x86 = os.path.join(r"C:\Program Files (x86)\PostgreSQL", ver, "bin", f"{bin_name}.exe")
            if os.path.exists(candidate_x86):
                return candidate_x86

    return bin_name


def perform_vacuum_optimize(app):
    """تنفيذ VACUUM دوري لتنظيف وتحسين قاعدة البيانات"""
    try:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        
        with app.app_context():
            try:
                if "postgresql" in uri:
                    conn = db.engine.raw_connection()
                    try:
                        conn.set_isolation_level(0)
                        cursor = conn.cursor()
                        cursor.execute("VACUUM ANALYZE")
                        cursor.close()
                    finally:
                        conn.close()
                
                app.logger.debug("✅ Database optimization completed")
            except Exception as e:
                # db.session.rollback() # Not needed for raw connection or if commit failed
                app.logger.warning(f"⚠️ Database optimization failed: {e}")
    except Exception as e:
        app.logger.warning(f"⚠️ Database optimization error: {e}")


def perform_backup_db(app=None):
    """نسخ احتياطي ذكي لقاعدة البيانات"""
    try:
        # إذا تم استدعاء الدالة بدون app (مثلاً من قبل المستخدم)
        if app is None:
            from flask import current_app
            app = current_app
        
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        backup_dir = app.config.get("BACKUP_DB_DIR") or os.path.join(app.instance_path, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        if "postgresql" in uri:
            backup_path = os.path.join(backup_dir, f"backup_{ts}.dump")
            try:
                import subprocess
                from sqlalchemy.engine.url import make_url
                pg_dump_bin = _get_pg_bin("pg_dump")
                
                u = make_url(uri)
                env = os.environ.copy()
                if u.password:
                    env["PGPASSWORD"] = u.password
                
                # Construct command: pg_dump -h host -p port -U user -d dbname -Fc -b -f file
                # -Fc means Custom format (compressed, suitable for pg_restore)
                cmd = [pg_dump_bin, "-h", u.host or "localhost", "-p", str(u.port or 5432), "-U", u.username or "postgres", "-d", u.database, "-Fc", "-b", "-f", backup_path]
                
                app.logger.info(f"Starting PostgreSQL backup to {backup_path}")
                process = subprocess.run(cmd, env=env, capture_output=True, text=True)
                
                if process.returncode == 0:
                    backup_info = {
                        "timestamp": ts,
                        "type": "postgresql",
                        "format": "custom",
                        "size": os.path.getsize(backup_path),
                        "version": app.config.get("APP_VERSION", "unknown")
                    }
                    info_path = os.path.join(backup_dir, f"backup_{ts}.info")
                    with open(info_path, "w") as f:
                        import json
                        json.dump(backup_info, f, indent=2)
                    keep_last = app.config.get("BACKUP_KEEP_LAST", 5)
                    backups = sorted(glob.glob(os.path.join(backup_dir, "backup_*.*")))
                    backup_files = sorted([f for f in backups if f.endswith((".dump", ".info"))])
                    dump_files = [f for f in backup_files if f.endswith(".dump")]
                    if len(dump_files) > keep_last:
                        for old in dump_files[:-keep_last]:
                            try:
                                os.remove(old)
                                info_file = os.path.splitext(old)[0] + ".info"
                                if os.path.exists(info_file):
                                    os.remove(info_file)
                            except Exception as e:
                                app.logger.warning(f"Failed to remove old backup {old}: {e}")
                    app.logger.info(f"PostgreSQL backup completed successfully")
                    return True, "تم النسخ الاحتياطي بنجاح", backup_path
                else:
                    app.logger.error(f"PostgreSQL backup failed: {process.stderr}")
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    return False, f"فشل النسخ الاحتياطي: {process.stderr}", None
            except Exception as e:
                app.logger.error(f"PostgreSQL backup exception: {e}")
                return False, f"خطأ في النسخ الاحتياطي: {str(e)}", None
        
        else:
            app.logger.warning("Backup skipped: Database type not supported for auto-backup")
            return False, "نوع قاعدة البيانات غير مدعوم للنسخ التلقائي", None
                    
    except Exception as e:
        app.logger.error(f"Backup process failed: {e}")
        return False, f"خطأ غير متوقع: {str(e)}", None


def process_asset_depreciation(app):
    try:
        with app.app_context():
            from models import SystemSettings, FixedAsset, FixedAssetCategory, AssetDepreciation, db
            from datetime import date
            from decimal import Decimal
            
            enable_auto = SystemSettings.get_setting('enable_auto_depreciation', False)
            if not enable_auto:
                return
            
            today = date.today()
            current_year = today.year
            current_month = today.month
            
            day_of_month = int(SystemSettings.get_setting('depreciation_day_of_month', 1))
            if today.day != day_of_month:
                return
            
            assets = FixedAsset.query.filter_by(status='ACTIVE').all()
            
            for asset in assets:
                existing = AssetDepreciation.query.filter_by(
                    asset_id=asset.id,
                    fiscal_year=current_year,
                    fiscal_month=current_month
                ).first()
                
                if existing:
                    continue
                
                category = asset.category
                if not category:
                    continue
                
                years_owned = (today - asset.purchase_date).days / 365.25
                if years_owned >= category.useful_life_years:
                    continue
                
                if category.depreciation_method == 'STRAIGHT_LINE':
                    annual_depreciation = float(asset.purchase_price) / category.useful_life_years
                    monthly_depreciation = annual_depreciation / 12
                else:
                    rate = float(category.depreciation_rate or 0) / 100
                    current_value = asset.get_current_book_value(today)
                    annual_depreciation = current_value * rate
                    monthly_depreciation = annual_depreciation / 12
                
                total_previous = db.session.query(func.sum(AssetDepreciation.depreciation_amount)).filter(
                    AssetDepreciation.asset_id == asset.id
                ).scalar() or 0
                
                accumulated = float(total_previous) + monthly_depreciation
                book_value = float(asset.purchase_price) - accumulated
                
                if book_value < 0:
                    book_value = 0
                    monthly_depreciation = float(asset.purchase_price) - float(total_previous)
                
                depreciation = AssetDepreciation(
                    asset_id=asset.id,
                    fiscal_year=current_year,
                    fiscal_month=current_month,
                    depreciation_date=today,
                    depreciation_amount=Decimal(str(round(monthly_depreciation, 2))),
                    accumulated_depreciation=Decimal(str(round(accumulated, 2))),
                    book_value=Decimal(str(round(book_value, 2)))
                )
                db.session.add(depreciation)
                
                from models import _gl_upsert_batch_and_entries, GL_ACCOUNTS
                
                entries = [
                    (GL_ACCOUNTS.get("DEPRECIATION_EXP", "6800_DEPRECIATION"), monthly_depreciation, 0),
                    (category.depreciation_account_code, 0, monthly_depreciation),
                ]
                
                try:
                    batch_id = _gl_upsert_batch_and_entries(
                        db.session.connection(),
                        source_type="DEPRECIATION",
                        source_id=asset.id,
                        purpose="DEPRECIATION",
                        currency="ILS",
                        memo=f"استهلاك {asset.name} - {current_year}/{current_month}",
                        entries=entries,
                        ref=f"DEP-{asset.asset_number}-{current_year}{current_month:02d}",
                        entity_type=None,
                        entity_id=None
                    )
                    depreciation.gl_batch_id = batch_id
                except Exception as e:
                    app.logger.warning(f"Failed to create GL for depreciation: {e}")
            
            db.session.commit()
            app.logger.info(f"[Depreciation] Processed {len(assets)} assets")
            
    except Exception as e:
        app.logger.error(f"[Depreciation] Job failed: {e}")


def update_exchange_rates_job(app):
    try:
        with app.app_context():
            from models import auto_update_missing_rates
            
            result = auto_update_missing_rates()
            
            if result.get('success'):
                updated = result.get('updated_rates', 0)
                app.logger.info(f"[FX Update] Updated {updated} exchange rates")
            else:
                app.logger.warning(f"[FX Update] Failed: {result.get('message', 'Unknown error')}")
                
    except Exception as e:
        app.logger.error(f"[FX Update] Job failed: {e}")


def process_recurring_invoices(app):
    try:
        with app.app_context():
            from models import RecurringInvoiceTemplate, RecurringInvoiceSchedule, db
            from datetime import date
            from routes.recurring_invoices import _generate_recurring_invoice
            
            today = date.today()
            
            templates = RecurringInvoiceTemplate.query.filter(
                RecurringInvoiceTemplate.is_active == True,
                RecurringInvoiceTemplate.next_invoice_date <= today,
                db.or_(
                    RecurringInvoiceTemplate.end_date.is_(None),
                    RecurringInvoiceTemplate.end_date >= today
                )
            ).all()
            
            generated_count = 0
            error_count = 0
            
            for template in templates:
                try:
                    scheduled_date = template.next_invoice_date
                    
                    if scheduled_date > today:
                        continue
                    
                    existing = RecurringInvoiceSchedule.query.filter_by(
                        template_id=template.id,
                        scheduled_date=scheduled_date,
                        status='GENERATED'
                    ).first()
                    
                    if existing:
                        continue
                    
                    _generate_recurring_invoice(template, scheduled_date)
                    db.session.commit()
                    generated_count += 1
                    
                except Exception as e:
                    error_count += 1
                    db.session.rollback()
                    
                    try:
                        schedule = RecurringInvoiceSchedule(
                            template_id=template.id,
                            scheduled_date=scheduled_date,
                            status='FAILED',
                            error_message=str(e)[:500]
                        )
                        db.session.add(schedule)
                        db.session.commit()
                    except Exception:
                        pass
                    
                    app.logger.error(f"[Recurring Invoices] Failed to generate invoice for template {template.id}: {e}")
            
            if generated_count > 0 or error_count > 0:
                app.logger.info(f"[Recurring Invoices] Generated {generated_count} invoices, {error_count} errors")
                
    except Exception as e:
        app.logger.error(f"[Recurring Invoices] Job failed: {e}")


def process_payment_reminders(app):
    try:
        with app.app_context():
            from utils import notify_payment_reminder
            
            result = notify_payment_reminder()
            
            if result.get('success'):
                sent = result.get('sent', 0)
                if sent > 0:
                    app.logger.info(f"[Payment Reminders] Sent {sent} reminders")
            else:
                app.logger.warning(f"[Payment Reminders] Failed: {result.get('error', 'Unknown')}")
                
    except Exception as e:
        app.logger.error(f"[Payment Reminders] Job failed: {e}")


def process_low_stock_alerts(app):
    try:
        with app.app_context():
            from models import Product, StockLevel, db
            from sqlalchemy import func
            from notifications import notify_low_stock
            
            products = db.session.query(
                Product,
                func.coalesce(func.sum(StockLevel.quantity), 0).label('total_stock')
            ).outerjoin(
                StockLevel, StockLevel.product_id == Product.id
            ).group_by(Product.id).having(
                func.coalesce(func.sum(StockLevel.quantity), 0) <= Product.min_qty
            ).all()
            
            alerted_count = 0
            
            for product, stock in products:
                if product.min_qty and stock <= product.min_qty:
                    try:
                        notify_low_stock(
                            product_id=product.id,
                            product_name=product.name,
                            current_stock=int(stock),
                            min_stock=int(product.min_qty or 0)
                        )
                        alerted_count += 1
                    except Exception as e:
                        app.logger.error(f"[Low Stock] Failed to notify for product {product.id}: {e}")
            
            if alerted_count > 0:
                app.logger.info(f"[Low Stock Alerts] Sent {alerted_count} alerts")
                
    except Exception as e:
        app.logger.error(f"[Low Stock Alerts] Job failed: {e}")


def process_check_reminders(app):
    try:
        with app.app_context():
            from models import Check, CheckStatus, db
            from datetime import datetime, timedelta, timezone
            from notifications import notify_system_alert, NotificationPriority
            
            today = datetime.now(timezone.utc).date()
            reminder_days = 3
            target_date = today + timedelta(days=reminder_days)
            
            upcoming_checks = Check.query.filter(
                Check.status == CheckStatus.PENDING.value,
                Check.check_due_date >= today,
                Check.check_due_date <= target_date
            ).all()
            
            overdue_checks = Check.query.filter(
                Check.status == CheckStatus.PENDING.value,
                Check.check_due_date < today
            ).all()
            
            if upcoming_checks:
                notify_system_alert(
                    title=f"تذكير: {len(upcoming_checks)} شيك مستحق خلال {reminder_days} أيام",
                    message=f"يوجد {len(upcoming_checks)} شيك يستحق التحصيل قريباً",
                    priority=NotificationPriority.MEDIUM
                )
                app.logger.info(f"[Check Reminders] {len(upcoming_checks)} upcoming checks")
            
            if overdue_checks:
                notify_system_alert(
                    title=f"تنبيه: {len(overdue_checks)} شيك متأخر!",
                    message=f"يوجد {len(overdue_checks)} شيك متأخر عن موعد الاستحقاق",
                    priority=NotificationPriority.HIGH
                )
                app.logger.warning(f"[Check Reminders] {len(overdue_checks)} overdue checks")
                
    except Exception as e:
        app.logger.error(f"[Check Reminders] Job failed: {e}")


def perform_backup_sql(app):
    """نسخ احتياطي SQL محسن"""
    try:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        backup_dir = (
            app.config.get("BACKUP_SQL_DIR")
            or os.path.join(app.config.get("BACKUP_DB_DIR") or os.path.join(app.instance_path, "backups"), "sql")
        )
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if uri.startswith("postgresql"):
            backup_path = os.path.join(backup_dir, f"backup_pg_{ts}.sql")
            
            # Extract connection details
            from urllib.parse import urlparse
            import subprocess
            
            parsed = urlparse(uri)
            db_name = parsed.path[1:]
            user = parsed.username
            password = parsed.password
            host = parsed.hostname
            port = parsed.port or 5432
            
            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password
            
            cmd = [
                "pg_dump",
                "-h", host,
                "-p", str(port),
                "-U", user,
                "-F", "p",
                "-f", backup_path,
                db_name
            ]
            
            try:
                subprocess.run(cmd, env=env, check=True)
                app.logger.info(f"PostgreSQL backup completed: {backup_path}")
            except subprocess.CalledProcessError as e:
                app.logger.error(f"PostgreSQL backup failed: {e}")
            except FileNotFoundError:
                app.logger.error("pg_dump not found. Please install PostgreSQL client tools.")
        
        else:
            app.logger.warning("SQL backup skipped: Unsupported database type")

        # تنظيف النسخ القديمة
        keep_last = app.config.get("BACKUP_KEEP_LAST", 5)
        backups = sorted(glob.glob(os.path.join(backup_dir, "backup_*.sql")))
        if len(backups) > keep_last:
            for old in backups[:-keep_last]:
                try:
                    os.remove(old)
                except Exception as e:
                    app.logger.warning(f"Failed to remove old SQL backup {old}: {e}")

    except Exception as e:
        app.logger.error(f"Backup process failed: {e}")


def restore_database(app, backup_path):
    """استعادة قاعدة البيانات من نسخة احتياطية"""
    try:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        
        # PostgreSQL Restore
        if "postgresql" in uri:
            try:
                import subprocess
                from sqlalchemy.engine.url import make_url
                from sqlalchemy import text
                
                u = make_url(uri)
                env = os.environ.copy()
                if u.password:
                    env["PGPASSWORD"] = u.password

                try:
                    if os.environ.get("PG_RESTORE_JOBS") is None:
                        restore_jobs = int(min(max(os.cpu_count() or 4, 2), 8))
                    else:
                        restore_jobs = int(os.environ.get("PG_RESTORE_JOBS") or 4)
                except Exception:
                    restore_jobs = 4
                restore_jobs = max(1, min(restore_jobs, 16))

                raw_fast_restore = str(os.environ.get("FAST_RESTORE", "") or "").strip().lower()
                if raw_fast_restore in {"0", "false", "no", "n", "off"}:
                    fast_restore = False
                elif raw_fast_restore in {"1", "true", "yes", "y", "on"}:
                    fast_restore = True
                else:
                    fast_restore = True

                raw_disable_triggers = str(os.environ.get("PG_RESTORE_DISABLE_TRIGGERS", "") or "").strip().lower()
                disable_triggers = raw_disable_triggers in {"1", "true", "yes", "y", "on"}

                raw_terminate = str(os.environ.get("PG_RESTORE_TERMINATE_CONNECTIONS", "") or "").strip().lower()
                if raw_terminate in {"0", "false", "no", "n", "off"}:
                    terminate_connections = False
                elif raw_terminate in {"1", "true", "yes", "y", "on"}:
                    terminate_connections = True
                else:
                    terminate_connections = True

                try:
                    db.session.remove()
                except Exception:
                    pass
                try:
                    db.engine.dispose()
                except Exception:
                    pass

                if terminate_connections:
                    try:
                        db.session.execute(
                            text(
                                "SELECT pg_terminate_backend(pid) "
                                "FROM pg_stat_activity "
                                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                            )
                        )
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        app.logger.warning(f"Terminate connections skipped: {e}")
                
                pg_restore_bin = _get_pg_bin("pg_restore")
                psql_bin = _get_pg_bin("psql")

                if fast_restore:
                    reset_sql = (
                        "DO $$ DECLARE r record; BEGIN "
                        "FOR r IN (SELECT nspname FROM pg_namespace "
                        "WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema') LOOP "
                        "EXECUTE 'DROP SCHEMA IF EXISTS ' || quote_ident(r.nspname) || ' CASCADE'; "
                        "END LOOP; "
                        "EXECUTE 'CREATE SCHEMA IF NOT EXISTS public'; "
                        "EXECUTE 'GRANT ALL ON SCHEMA public TO ' || quote_ident(current_user); "
                        "EXECUTE 'GRANT USAGE ON SCHEMA public TO public'; "
                        "END $$;"
                    )
                    reset_cmd = [
                        psql_bin,
                        "-h", u.host or "localhost",
                        "-p", str(u.port or 5432),
                        "-U", u.username or "postgres",
                        "-d", u.database,
                        "-v", "ON_ERROR_STOP=1",
                        "-c", reset_sql,
                    ]
                    reset_proc = subprocess.run(reset_cmd, env=env, capture_output=True, text=True)
                    if reset_proc.returncode != 0:
                        app.logger.warning(f"Fast restore schema reset failed: {reset_proc.stderr}")
                        fast_restore = False

                cmd = [
                    pg_restore_bin,
                    "-h", u.host or "localhost", 
                    "-p", str(u.port or 5432), 
                    "-U", u.username or "postgres", 
                    "-d", u.database, 
                    "--no-owner",  # Skip ownership restoration
                    "--no-privileges",  # Skip privilege restoration
                    "--exit-on-error",
                ]

                if not fast_restore:
                    cmd.extend(["--clean", "--if-exists"])
                if disable_triggers:
                    cmd.append("--disable-triggers")
                if restore_jobs > 1:
                    cmd.extend(["-j", str(restore_jobs)])
                cmd.append(backup_path)
                
                app.logger.info(f"Starting PostgreSQL restore from {backup_path}")
                process = subprocess.run(cmd, env=env, capture_output=True, text=True)

                try:
                    db.session.remove()
                except Exception:
                    pass
                try:
                    db.engine.dispose()
                except Exception:
                    pass
                
                if process.returncode == 0:
                    app.logger.info(f"PostgreSQL restore completed successfully")
                    return True, "تمت استعادة قاعدة البيانات بنجاح"
                else:
                    # pg_restore might return non-zero even on success with warnings
                    # Check if the error is fatal or just warnings
                    if "fatal" in process.stderr.lower() or "error" in process.stderr.lower():
                         app.logger.error(f"PostgreSQL restore failed: {process.stderr}")
                         return False, f"فشل الاستعادة: {process.stderr}"
                    else:
                        app.logger.warning(f"PostgreSQL restore finished with warnings: {process.stderr}")
                        return True, "تمت الاستعادة (مع بعض التحذيرات)"
                        
            except Exception as e:
                app.logger.error(f"PostgreSQL restore exception: {e}")
                return False, f"خطأ في الاستعادة: {str(e)}"
        
        else:
            return False, "نوع قاعدة البيانات غير مدعوم للاستعادة التلقائية"
            
    except Exception as e:
        app.logger.error(f"Restore process failed: {e}")
        return False, f"خطأ غير متوقع: {str(e)}"


def register_fonts(app=None):
    try:
        if not pdfmetrics or not TTFont:
            return
        base_path = os.path.join(app.root_path if app else os.getcwd(), "static", "fonts")
        fonts = {
            "Amiri": "Amiri-Regular.ttf",
            "Amiri-Bold": "Amiri-Bold.ttf",
            "Amiri-Italic": "Amiri-Italic.ttf",
            "Amiri-BoldItalic": "Amiri-BoldItalic.ttf",
        }
        for name, file in fonts.items():
            path = os.path.join(base_path, file)
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
    except Exception as e:
        logging.error("Font registration failed: %s", e)


def _safe_start_scheduler(app):
    skip_cmds = ("db", "seed", "shell", "migrate", "upgrade", "downgrade", "init")
    if any(cmd in sys.argv for cmd in skip_cmds):
        app.logger.info("Scheduler skipped: CLI context.")
        return
    try:
        if (os.environ.get("GUNICORN_CMD_ARGS") or "gunicorn" in " ".join(sys.argv).lower()) and os.environ.get("ENABLE_SCHEDULER") != "1":
            app.logger.info("Scheduler skipped: gunicorn context (set ENABLE_SCHEDULER=1 to enable).")
            return
    except Exception:
        pass
    try:
        is_uwsgi = ("uwsgi" in sys.modules) or bool(os.environ.get("UWSGI_ORIGINAL_PROC_NAME") or os.environ.get("UWSGI_FILE"))
        is_pythonanywhere = bool(os.environ.get("PYTHONANYWHERE_DOMAIN") or os.environ.get("PYTHONANYWHERE_SITE"))
        if (is_uwsgi or is_pythonanywhere) and os.environ.get("ENABLE_SCHEDULER") != "1":
            app.logger.info("Scheduler skipped: WSGI/uWSGI context (set ENABLE_SCHEDULER=1 to enable).")
            return
    except Exception:
        pass
    if os.environ.get("DISABLE_SCHEDULER"):
        app.logger.info("Scheduler disabled by environment variable.")
        return
    try:
        if not scheduler.running:
            scheduler.start()
            app.logger.info("APScheduler started.")
        else:
            app.logger.info("APScheduler already running; skip start.")
    except Exception as e:
        app.logger.warning(f"Scheduler start skipped: {e}")


def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = app.config.get("LOGIN_VIEW", "auth.login")
    login_manager.login_message_category = app.config.get("LOGIN_MESSAGE_CATEGORY", "warning")

    csrf.init_app(app)
    mail.init_app(app)
    
    compress.init_app(app)
    app.config.setdefault('COMPRESS_MIMETYPES', [
        'text/html', 'text/css', 'text/xml', 'text/javascript',
        'application/json', 'application/javascript'
    ])
    app.config.setdefault('COMPRESS_LEVEL', 9)
    app.config.setdefault('COMPRESS_MIN_SIZE', 100)

    # تعطيل SocketIO في Development mode لتجنب أخطاء WebSocket
    # يمكن تفعيله في Production مع gunicorn + gevent
    if not app.config.get('SOCKETIO_ENABLED', False):
        # تهيئة بدون websocket transport (polling only)
        socketio.init_app(
            app,
            async_mode='threading',  # استخدام threading بدل eventlet/gevent
            cors_allowed_origins=app.config.get("SOCKETIO_CORS_ORIGINS", []),
            logger=False,
            engineio_logger=False,
            ping_timeout=20,
            ping_interval=25,
            transports=['polling']  # فقط polling، بدون websocket
        )
    else:
        # في Production mode
        socketio.init_app(
            app,
            async_mode=app.config.get("SOCKETIO_ASYNC_MODE"),
            message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
            cors_allowed_origins=app.config.get("SOCKETIO_CORS_ORIGINS", []),
            logger=app.config.get("SOCKETIO_LOGGER", False),
            engineio_logger=app.config.get("SOCKETIO_ENGINEIO_LOGGER", False),
            ping_timeout=app.config.get("SOCKETIO_PING_TIMEOUT", 20),
            ping_interval=app.config.get("SOCKETIO_PING_INTERVAL", 25),
            max_http_buffer_size=app.config.get("SOCKETIO_MAX_HTTP_BUFFER_SIZE", 100_000_000),
        )

    app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    app.config.setdefault("RATELIMIT_EXEMPT_SUPER", True)

    limiter.init_app(app)
    cache.init_app(app)

    default_limit = app.config.get("RATELIMIT_DEFAULT")
    if default_limit:
        if isinstance(default_limit, (list, tuple)):
            limiter.default_limits = [str(x).strip() for x in default_limit if str(x).strip()]
        else:
            parts = [p.strip() for p in str(default_limit).split(";") if p.strip()]
            limiter.default_limits = parts

    if app.config.get("RATELIMIT_EXEMPT_SUPER", True):
        @limiter.request_filter
        def _exempt_super_admin():
            try:
                import utils
                return utils.is_super()
            except Exception:
                return False

    def _entity_balance_audit_job():
        try:
            from datetime import datetime, timezone
            import json
            from sqlalchemy import func, or_
            from models import (
                AuditLog,
                Customer,
                Supplier,
                Partner,
                GLBatch,
                GLEntry,
                GL_ACCOUNTS,
            )

            with app.app_context():
                tol = float(app.config.get("ENTITY_BALANCE_AUDIT_TOLERANCE", 0.01) or 0.01)
                as_of_dt = datetime.now(timezone.utc)
                auto_fix = bool(app.config.get("ENTITY_BALANCE_AUDIT_AUTO_FIX", True))

                ar_account = (GL_ACCOUNTS.get("AR") or "1100_AR").upper()
                ap_account = (GL_ACCOUNTS.get("AP") or "2000_AP").upper()

                def _compute_snapshot():
                    customer_gl_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "CUSTOMER",
                            GLEntry.account == ar_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )

                    supplier_gl_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "SUPPLIER",
                            GLEntry.account == ap_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )

                    partner_ap_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "PARTNER",
                            GLEntry.account == ap_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )
                    partner_ar_sq = (
                        db.session.query(
                            Partner.id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
                        )
                        .join(GLBatch, GLBatch.entity_id == Partner.customer_id)
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "CUSTOMER",
                            GLEntry.account == ar_account,
                            Partner.customer_id.isnot(None),
                        )
                        .group_by(Partner.id)
                        .subquery()
                    )
                    partner_gl_sq = (
                        db.session.query(
                            Partner.id.label("entity_id"),
                            (
                                func.coalesce(partner_ap_sq.c.gl_balance, 0)
                                - func.coalesce(partner_ar_sq.c.gl_balance, 0)
                            ).label("gl_balance"),
                        )
                        .outerjoin(partner_ap_sq, partner_ap_sq.c.entity_id == Partner.id)
                        .outerjoin(partner_ar_sq, partner_ar_sq.c.entity_id == Partner.id)
                        .subquery()
                    )

                    partner_gl_present = (
                        db.session.query(func.count(GLBatch.id))
                        .filter(GLBatch.status == "POSTED", GLBatch.entity_type == "PARTNER", GLBatch.posted_at <= as_of_dt)
                        .scalar()
                        or 0
                    )

                    cust_stored = func.coalesce(Customer.current_balance, 0)
                    cust_gl = func.coalesce(customer_gl_sq.c.gl_balance, 0)
                    cust_diff = cust_gl - (-cust_stored)
                    customers_q = db.session.query(Customer.id).outerjoin(customer_gl_sq, customer_gl_sq.c.entity_id == Customer.id)
                    customers_mismatch_count = customers_q.with_entities(func.count()).filter(func.abs(cust_diff) > tol).scalar() or 0
                    customers_mismatch_total_abs = (
                        customers_q.with_entities(func.coalesce(func.sum(func.abs(cust_diff)), 0)).filter(func.abs(cust_diff) > tol).scalar()
                        or 0
                    )

                    supp_stored = func.coalesce(Supplier.current_balance, 0)
                    supp_gl = func.coalesce(supplier_gl_sq.c.gl_balance, 0)
                    supp_diff = supp_gl - supp_stored
                    suppliers_q = db.session.query(Supplier.id).outerjoin(supplier_gl_sq, supplier_gl_sq.c.entity_id == Supplier.id)
                    suppliers_mismatch_count = suppliers_q.with_entities(func.count()).filter(func.abs(supp_diff) > tol).scalar() or 0
                    suppliers_mismatch_total_abs = (
                        suppliers_q.with_entities(func.coalesce(func.sum(func.abs(supp_diff)), 0)).filter(func.abs(supp_diff) > tol).scalar()
                        or 0
                    )

                    part_stored = func.coalesce(Partner.current_balance, 0)
                    part_gl = func.coalesce(partner_gl_sq.c.gl_balance, 0)
                    part_diff = part_gl - part_stored
                    partners_q = db.session.query(Partner.id).outerjoin(partner_gl_sq, partner_gl_sq.c.entity_id == Partner.id)
                    partners_mismatch_count = partners_q.with_entities(func.count()).filter(func.abs(part_diff) > tol).scalar() or 0
                    partners_mismatch_total_abs = (
                        partners_q.with_entities(func.coalesce(func.sum(func.abs(part_diff)), 0)).filter(func.abs(part_diff) > tol).scalar()
                        or 0
                    )

                    posted_batches_missing_entity = (
                        db.session.query(func.count(GLBatch.id))
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            or_(GLBatch.entity_type.is_(None), GLBatch.entity_id.is_(None)),
                        )
                        .scalar()
                        or 0
                    )

                    ar_unassigned = (
                        db.session.query(func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0))
                        .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLEntry.account == ar_account,
                            or_(
                                GLBatch.entity_type.is_(None),
                                GLBatch.entity_id.is_(None),
                                GLBatch.entity_type != "CUSTOMER",
                            ),
                        )
                        .scalar()
                        or 0
                    )

                    ap_unassigned = (
                        db.session.query(func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0))
                        .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLEntry.account == ap_account,
                            or_(
                                GLBatch.entity_type.is_(None),
                                GLBatch.entity_id.is_(None),
                            ),
                        )
                        .scalar()
                        or 0
                    )

                    return {
                        "customers_mismatch_count": int(customers_mismatch_count),
                        "customers_mismatch_total_abs": float(customers_mismatch_total_abs),
                        "suppliers_mismatch_count": int(suppliers_mismatch_count),
                        "suppliers_mismatch_total_abs": float(suppliers_mismatch_total_abs),
                        "partners_mismatch_count": int(partners_mismatch_count),
                        "partners_mismatch_total_abs": float(partners_mismatch_total_abs),
                        "partner_gl_present": bool(partner_gl_present),
                        "posted_batches_missing_entity": int(posted_batches_missing_entity),
                        "ar_unassigned_balance": float(ar_unassigned),
                        "ap_unassigned_balance": float(ap_unassigned),
                    }

                def _find_target_ids():
                    customer_gl_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "CUSTOMER",
                            GLEntry.account == ar_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )
                    supplier_gl_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "SUPPLIER",
                            GLEntry.account == ap_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )
                    partner_ap_sq = (
                        db.session.query(
                            GLBatch.entity_id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
                        )
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "PARTNER",
                            GLEntry.account == ap_account,
                        )
                        .group_by(GLBatch.entity_id)
                        .subquery()
                    )
                    partner_ar_sq = (
                        db.session.query(
                            Partner.id.label("entity_id"),
                            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
                        )
                        .join(GLBatch, GLBatch.entity_id == Partner.customer_id)
                        .join(GLEntry, GLEntry.batch_id == GLBatch.id)
                        .filter(
                            GLBatch.status == "POSTED",
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == "CUSTOMER",
                            GLEntry.account == ar_account,
                            Partner.customer_id.isnot(None),
                        )
                        .group_by(Partner.id)
                        .subquery()
                    )
                    partner_gl_sq = (
                        db.session.query(
                            Partner.id.label("entity_id"),
                            (
                                func.coalesce(partner_ap_sq.c.gl_balance, 0)
                                - func.coalesce(partner_ar_sq.c.gl_balance, 0)
                            ).label("gl_balance"),
                        )
                        .outerjoin(partner_ap_sq, partner_ap_sq.c.entity_id == Partner.id)
                        .outerjoin(partner_ar_sq, partner_ar_sq.c.entity_id == Partner.id)
                        .subquery()
                    )

                    max_customers = int(app.config.get("ENTITY_BALANCE_AUTO_FIX_MAX_CUSTOMERS", 300) or 300)
                    max_suppliers = int(app.config.get("ENTITY_BALANCE_AUTO_FIX_MAX_SUPPLIERS", 300) or 300)
                    max_partners = int(app.config.get("ENTITY_BALANCE_AUTO_FIX_MAX_PARTNERS", 300) or 300)

                    cust_stored = func.coalesce(Customer.current_balance, 0)
                    cust_gl = func.coalesce(customer_gl_sq.c.gl_balance, 0)
                    cust_diff = cust_gl - (-cust_stored)
                    customers_q = db.session.query(Customer.id).outerjoin(customer_gl_sq, customer_gl_sq.c.entity_id == Customer.id)
                    customer_ids = [int(r.id) for r in customers_q.filter(func.abs(cust_diff) > tol).order_by(func.abs(cust_diff).desc()).limit(max_customers).all()]

                    supp_stored = func.coalesce(Supplier.current_balance, 0)
                    supp_gl = func.coalesce(supplier_gl_sq.c.gl_balance, 0)
                    supp_diff = supp_gl - supp_stored
                    suppliers_q = db.session.query(Supplier.id).outerjoin(supplier_gl_sq, supplier_gl_sq.c.entity_id == Supplier.id)
                    supplier_ids = [int(r.id) for r in suppliers_q.filter(func.abs(supp_diff) > tol).order_by(func.abs(supp_diff).desc()).limit(max_suppliers).all()]

                    part_stored = func.coalesce(Partner.current_balance, 0)
                    part_gl = func.coalesce(partner_gl_sq.c.gl_balance, 0)
                    part_diff = part_gl - part_stored
                    partners_q = db.session.query(Partner.id).outerjoin(partner_gl_sq, partner_gl_sq.c.entity_id == Partner.id)
                    partner_ids = [int(r.id) for r in partners_q.filter(func.abs(part_diff) > tol).order_by(func.abs(part_diff).desc()).limit(max_partners).all()]

                    return {"customers": customer_ids, "suppliers": supplier_ids, "partners": partner_ids}

                before = _compute_snapshot()
                fix_stats = None

                if auto_fix and (
                    before.get("customers_mismatch_count")
                    or before.get("suppliers_mismatch_count")
                    or before.get("partners_mismatch_count")
                    or before.get("posted_batches_missing_entity")
                ):
                    fix_stats = {
                        "gl_batches": {"found": 0, "updated": 0, "skipped": 0},
                        "recalculated": {"customers": 0, "suppliers": 0, "partners": 0},
                    }

                    try:
                        from services.ledger_service import SmartEntityExtractor

                        supported_source_types = {
                            "PAYMENT",
                            "PAYMENT_SPLIT",
                            "SALE",
                            "INVOICE",
                            "EXPENSE",
                            "SERVICE",
                            "PREORDER",
                            "SHIPMENT",
                        }
                        max_batches = int(app.config.get("ENTITY_BALANCE_AUTO_FIX_MAX_BATCHES", 2000) or 2000)
                        q = (
                            db.session.query(GLBatch)
                            .filter(GLBatch.status == "POSTED", GLBatch.posted_at <= as_of_dt)
                            .filter(or_(GLBatch.entity_type.is_(None), GLBatch.entity_id.is_(None)))
                            .filter(GLBatch.source_type.isnot(None), GLBatch.source_id.isnot(None))
                            .filter(func.upper(GLBatch.source_type).in_(supported_source_types))
                            .order_by(GLBatch.id.desc())
                            .limit(max_batches)
                        )
                        batches = q.all()
                        fix_stats["gl_batches"]["found"] = len(batches)
                        for b in batches:
                            try:
                                _, _, entity_id, entity_type = SmartEntityExtractor.extract_from_batch(b)
                                if not entity_type or not entity_id:
                                    fix_stats["gl_batches"]["skipped"] += 1
                                    continue
                                entity_type_u = str(entity_type).upper()
                                if entity_type_u not in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"}:
                                    fix_stats["gl_batches"]["skipped"] += 1
                                    continue
                                b.entity_type = entity_type_u
                                b.entity_id = int(entity_id)
                                fix_stats["gl_batches"]["updated"] += 1
                            except Exception:
                                fix_stats["gl_batches"]["skipped"] += 1
                        if fix_stats["gl_batches"]["updated"]:
                            db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass

                    try:
                        targets = _find_target_ids()
                    except Exception:
                        targets = {"customers": [], "suppliers": [], "partners": []}

                    try:
                        from utils.customer_balance_updater import update_customer_balance_components
                    except Exception:
                        update_customer_balance_components = None
                    try:
                        from utils.supplier_balance_updater import update_supplier_balance_components
                    except Exception:
                        update_supplier_balance_components = None
                    try:
                        from models import update_partner_balance
                    except Exception:
                        update_partner_balance = None

                    for cid in targets.get("customers", []):
                        if not update_customer_balance_components:
                            break
                        try:
                            update_customer_balance_components(int(cid), db.session)
                            fix_stats["recalculated"]["customers"] += 1
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass

                    for sid in targets.get("suppliers", []):
                        if not update_supplier_balance_components:
                            break
                        try:
                            update_supplier_balance_components(int(sid), db.session)
                            fix_stats["recalculated"]["suppliers"] += 1
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass

                    for pid in targets.get("partners", []):
                        if not update_partner_balance:
                            break
                        try:
                            update_partner_balance(int(pid), db.session)
                            fix_stats["recalculated"]["partners"] += 1
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass

                after = _compute_snapshot()

                summary = {
                    "as_of": as_of_dt.isoformat(),
                    "tolerance": tol,
                    "accounts": {"ar": ar_account, "ap": ap_account},
                    "auto_fix": bool(auto_fix),
                    "before": before,
                    "after": after,
                    "fix_stats": fix_stats,
                }

                try:
                    db.session.add(
                        AuditLog(
                            model_name="Ledger",
                            record_id=None,
                            user_id=None,
                            action="ENTITY_BALANCE_AUDIT",
                            old_data=None,
                            new_data=json.dumps(summary, ensure_ascii=False, default=str),
                        )
                    )
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        except Exception:
            try:
                app.logger.warning("entity_balance_audit_job_failed")
            except Exception:
                pass

    try:
        init_scheduler_monitor(app)
        backup_db_interval = app.config.get("BACKUP_DB_INTERVAL")
        if backup_db_interval and hasattr(backup_db_interval, 'total_seconds'):
            register_scheduler_job(
                app,
                "db_backup",
                lambda: perform_backup_db(app),
                "interval",
                seconds=backup_db_interval.total_seconds(),
            )
        
        # Check if perform_backup_sql exists before adding job
        if 'perform_backup_sql' in globals():
            backup_sql_interval = app.config.get("BACKUP_SQL_INTERVAL")
            if backup_sql_interval and hasattr(backup_sql_interval, 'total_seconds'):
                register_scheduler_job(
                    app,
                    "sql_backup",
                    lambda: perform_backup_sql(app),
                    "interval",
                    seconds=backup_sql_interval.total_seconds(),
                )
        
        register_scheduler_job(
            app,
            "update_fx_rates",
            lambda: update_exchange_rates_job(app),
            "interval",
            hours=1,
        )
        
        register_scheduler_job(
            app,
            "asset_depreciation",
            lambda: process_asset_depreciation(app),
            "cron",
            day=1,
            hour=2,
            minute=0,
        )
        
        register_scheduler_job(
            app,
            "recurring_invoices",
            lambda: process_recurring_invoices(app),
            "cron",
            hour=0,
            minute=5,
        )
        
        register_scheduler_job(
            app,
            "payment_reminders",
            lambda: process_payment_reminders(app),
            "cron",
            hour=9,
            minute=0,
        )
        
        register_scheduler_job(
            app,
            "low_stock_alerts",
            lambda: process_low_stock_alerts(app),
            "cron",
            hour=8,
            minute=0,
        )
        
        register_scheduler_job(
            app,
            "check_reminders",
            lambda: process_check_reminders(app),
            "cron",
            hour=7,
            minute=30,
        )
        
        register_scheduler_job(
            app,
            "db_vacuum",
            lambda: perform_vacuum_optimize(app),
            "interval",
            hours=1,
        )
        
        if app.config.get("ENABLE_AUTOMATED_BACKUPS", True):
            try:
                from services.backup_service import schedule_automated_backups
                state = app.extensions.setdefault("auto_backup_scheduler", {})
                if not state.get("scheduled"):
                    schedule_automated_backups(app, scheduler)
                    state["scheduled"] = True
            except Exception as e:
                app.logger.warning(f"Automated backup scheduling failed: {e}")

        if app.config.get("ENABLE_ENTITY_BALANCE_AUDIT_JOB", True):
            register_scheduler_job(
                app,
                "entity_balance_audit",
                _entity_balance_audit_job,
                "cron",
                hour=int(app.config.get("ENTITY_BALANCE_AUDIT_HOUR", 4) or 4),
                minute=int(app.config.get("ENTITY_BALANCE_AUDIT_MINUTE", 10) or 10),
            )
    except Exception as e:
        app.logger.warning(f"Scheduler job registration failed: {e}")

    try:
        state = app.extensions.setdefault("allocation_listeners", {})
        if not state.get("registered"):
            from utils.allocation_listeners import register_allocation_listeners

            register_allocation_listeners()
            state["registered"] = True
    except Exception as e:
        try:
            app.logger.warning(f"Allocation listeners registration failed: {e}")
        except Exception:
            pass

    _safe_start_scheduler(app)
    register_fonts(app)
    
    try:
        skip_cmds = ("db", "seed", "shell", "migrate", "upgrade", "downgrade", "init")
        if not any(cmd in sys.argv for cmd in skip_cmds):
            if os.environ.get("DISABLE_PERFORMANCE_INDEXES"):
                return
            if not app.config.get("AUTO_CREATE_PERFORMANCE_INDEXES", True):
                return
            ensure_performance_indexes(app)
    except Exception:
        pass

def ensure_performance_indexes(app):
    """إنشاء فهارس الأداء على قاعدة البيانات (PostgreSQL أو SQLite) لتسريع الاستعلامات."""
    try:
        from sqlalchemy import text, inspect
        with app.app_context():
            uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            is_pg = "postgresql" in uri
            is_sqlite = "sqlite" in uri
            if not is_pg and not is_sqlite:
                return
            base_stmts = [
                "CREATE INDEX IF NOT EXISTS ix_users_is_active ON users (is_active)",
                "CREATE INDEX IF NOT EXISTS ix_users_lower_username ON users (lower(username))",
                "CREATE INDEX IF NOT EXISTS ix_users_lower_email ON users (lower(email))",
                "CREATE INDEX IF NOT EXISTS ix_users_last_login ON users (last_login)",
                "CREATE INDEX IF NOT EXISTS ix_users_last_seen ON users (last_seen)",
                "CREATE INDEX IF NOT EXISTS ix_products_name ON products (name)",
                "CREATE INDEX IF NOT EXISTS ix_products_part_number ON products (part_number)",
                "CREATE INDEX IF NOT EXISTS ix_products_brand ON products (brand)",
                "CREATE INDEX IF NOT EXISTS ix_stock_levels_wh ON stock_levels (warehouse_id)",
                "CREATE INDEX IF NOT EXISTS ix_stock_levels_prod ON stock_levels (product_id)",
                "CREATE INDEX IF NOT EXISTS ix_stock_levels_wh_prod ON stock_levels (warehouse_id, product_id)",
                "CREATE INDEX IF NOT EXISTS ix_sales_date ON sales (sale_date)",
                "CREATE INDEX IF NOT EXISTS ix_sales_customer_id ON sales (customer_id)",
                "CREATE INDEX IF NOT EXISTS ix_sales_customer_date ON sales (customer_id, sale_date)",
                "CREATE INDEX IF NOT EXISTS ix_sales_status ON sales (status)",
                "CREATE INDEX IF NOT EXISTS ix_payments_date ON payments (payment_date)",
                "CREATE INDEX IF NOT EXISTS ix_payments_is_archived ON payments (is_archived)",
                "CREATE INDEX IF NOT EXISTS ix_customers_created_at ON customers (created_at)",
                "CREATE INDEX IF NOT EXISTS ix_customers_name ON customers (name)",
                "CREATE INDEX IF NOT EXISTS ix_customers_phone ON customers (phone)",
                "CREATE INDEX IF NOT EXISTS ix_customers_lower_email ON customers (lower(email))",
                "CREATE INDEX IF NOT EXISTS ix_customers_category ON customers (category)",
                "CREATE INDEX IF NOT EXISTS ix_customers_current_balance ON customers (current_balance)",
                "CREATE INDEX IF NOT EXISTS ix_customers_is_active ON customers (is_active)",
                "CREATE INDEX IF NOT EXISTS ix_customers_is_online ON customers (is_online)",
                "CREATE INDEX IF NOT EXISTS ix_customers_is_archived ON customers (is_archived)",
                "CREATE INDEX IF NOT EXISTS ix_payments_status ON payments (status)",
                "CREATE INDEX IF NOT EXISTS ix_payments_direction ON payments (direction)",
                "CREATE INDEX IF NOT EXISTS ix_payments_entity_type ON payments (entity_type)",
                "CREATE INDEX IF NOT EXISTS ix_payments_method ON payments (method)",
                "CREATE INDEX IF NOT EXISTS ix_payments_currency ON payments (currency)",
                "CREATE INDEX IF NOT EXISTS ix_payments_customer_id ON payments (customer_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_supplier_id ON payments (supplier_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_partner_id ON payments (partner_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_invoice_id ON payments (invoice_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_sale_id ON payments (sale_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_service_id ON payments (service_id)",
                "CREATE INDEX IF NOT EXISTS ix_payments_customer_date ON payments (customer_id, payment_date)",
                "CREATE INDEX IF NOT EXISTS ix_payments_supplier_date ON payments (supplier_id, payment_date)",
                "CREATE INDEX IF NOT EXISTS ix_payments_partner_date ON payments (partner_id, payment_date)",
                "CREATE INDEX IF NOT EXISTS ix_payments_payment_number ON payments (payment_number)",
                "CREATE INDEX IF NOT EXISTS ix_payments_receipt_number ON payments (receipt_number)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_invoice_number ON invoices (invoice_number)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_invoice_date ON invoices (invoice_date)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices (status)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_customer_id ON invoices (customer_id)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_customer_date ON invoices (customer_id, invoice_date)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_customer_id ON service_requests (customer_id)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_mechanic_id ON service_requests (mechanic_id)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_status ON service_requests (status)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_priority ON service_requests (priority)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_received_at ON service_requests (received_at)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_customer_status_date ON service_requests (customer_id, status, received_at)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_customer_date ON service_requests (customer_id, received_at)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_status_created_at ON service_requests (status, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_mechanic_status ON service_requests (mechanic_id, status)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_status_priority ON service_requests (status, priority)",
                "CREATE INDEX IF NOT EXISTS ix_service_requests_received_status ON service_requests (received_at, status)",
                "CREATE INDEX IF NOT EXISTS ix_checks_status_due_date_direction ON checks (status, check_due_date, direction)",
                "CREATE INDEX IF NOT EXISTS ix_checks_customer_id_date ON checks (customer_id, check_date)",
                "CREATE INDEX IF NOT EXISTS ix_checks_supplier_id_date ON checks (supplier_id, check_date)",
                "CREATE INDEX IF NOT EXISTS ix_checks_partner_id_date ON checks (partner_id, check_date)",
                "CREATE INDEX IF NOT EXISTS ix_checks_payment_id_status ON checks (payment_id, status)",
                "CREATE INDEX IF NOT EXISTS ix_checks_is_archived_status ON checks (is_archived, status)",
                "CREATE INDEX IF NOT EXISTS ix_checks_check_date_status ON checks (check_date, status)",
                "CREATE INDEX IF NOT EXISTS ix_checks_payment_id ON checks (payment_id)",
                "CREATE INDEX IF NOT EXISTS ix_checks_check_date ON checks (check_date)",
                "CREATE INDEX IF NOT EXISTS ix_checks_direction ON checks (direction)",
                "CREATE INDEX IF NOT EXISTS ix_checks_status ON checks (status)",
                "CREATE INDEX IF NOT EXISTS ix_partners_is_archived_balance ON partners (is_archived, current_balance)",
                "CREATE INDEX IF NOT EXISTS ix_partners_name_phone ON partners (name, phone_number)",
                "CREATE INDEX IF NOT EXISTS ix_partners_customer_id ON partners (customer_id)",
                "CREATE INDEX IF NOT EXISTS ix_partners_currency_balance ON partners (currency, current_balance)",
                "CREATE INDEX IF NOT EXISTS ix_partners_share_percentage ON partners (share_percentage)",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_name ON suppliers (name)",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_phone ON suppliers (phone_number)",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_lower_email ON suppliers (lower(email))",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_is_archived ON suppliers (is_archived)",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_currency ON suppliers (currency)",
                "CREATE INDEX IF NOT EXISTS ix_suppliers_current_balance ON suppliers (current_balance)",
                "CREATE INDEX IF NOT EXISTS ix_gl_batches_posted_at ON gl_batches (posted_at)",
                "CREATE INDEX IF NOT EXISTS ix_gl_batches_status ON gl_batches (status)"
            ]
            pg_trgm_stmts = [
                "CREATE INDEX IF NOT EXISTS gin_customers_name_trgm ON customers USING gin (name gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS gin_suppliers_name_trgm ON suppliers USING gin (name gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS gin_partners_name_trgm ON partners USING gin (name gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS gin_payments_reference_trgm ON payments USING gin (reference gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS gin_payments_notes_trgm ON payments USING gin (notes gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS gin_checks_check_number_trgm ON checks USING gin (check_number gin_trgm_ops)",
            ]
            pg_partial_stmts = [
                "CREATE INDEX IF NOT EXISTS ix_payments_date_active ON payments (payment_date) WHERE is_archived = false",
                "CREATE INDEX IF NOT EXISTS ix_payments_customer_date_completed ON payments (customer_id, payment_date) WHERE is_archived = false AND status = 'COMPLETED'",
                "CREATE INDEX IF NOT EXISTS ix_checks_date_pending ON checks (check_date) WHERE status = 'PENDING'",
                "CREATE INDEX IF NOT EXISTS ix_service_received_active ON service_requests (received_at) WHERE status IN ('PENDING','IN_PROGRESS','DIAGNOSIS')",
            ]
            with db.engine.connect() as conn:
                if is_pg:
                    ac = conn.execution_options(isolation_level="AUTOCOMMIT")
                    def _run(s: str) -> bool:
                        try:
                            ac.execute(text(s))
                            return True
                        except Exception:
                            return False
                    for sql in base_stmts:
                        _run(sql)
                    pg_trgm_ready = _run("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                    if not pg_trgm_ready:
                        try:
                            pg_trgm_ready = bool(
                                ac.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm' LIMIT 1")).scalar()
                            )
                        except Exception:
                            pg_trgm_ready = False
                    if pg_trgm_ready:
                        for sql in pg_trgm_stmts:
                            _run(sql)
                    for sql in pg_partial_stmts:
                        _run(sql)
                else:
                    # SQLite: فهارس بسيطة فقط (بدون GIN/جزئية)
                    def _run(s: str) -> bool:
                        try:
                            conn.execute(text(s))
                            conn.commit()
                            return True
                        except Exception:
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                            return False
                    for sql in base_stmts:
                        _run(sql)

                # تغطية شاملة لكل أعمدة FK بفهرس بسيط (جدول × عمود)
                try:
                    inspector = inspect(db.engine)
                    all_tables = inspector.get_table_names()
                    for table in all_tables:
                        fks = inspector.get_foreign_keys(table) or []
                        for fk in fks:
                            for col in fk.get("constrained_columns") or []:
                                if not col:
                                    continue
                                idx_name = f"ix_{table}_{col}_fk_auto"
                                fk_sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})"
                                _run(fk_sql)
                except Exception:
                    # في أسوأ الأحوال، إذا فشل فهرسة FK لا نعطّل التطبيق
                    pass
    except Exception:
        pass
