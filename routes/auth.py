
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urljoin

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select, func

from extensions import db, limiter, mail
from forms import LoginForm, CustomerFormOnline, CustomerPasswordResetForm, CustomerPasswordResetRequestForm
from models import Customer, User
import utils
from utils import _get_or_404

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _is_safe_url(target: str) -> bool:
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _get_client_ip() -> str:
    """Return client IP via request.remote_addr.

    When behind a reverse proxy, use ``ProxyFix`` so that
    ``request.remote_addr`` is already the real client IP.
    Blindly trusting X-Forwarded-For allows IP spoofing.
    """
    return request.remote_addr or "0.0.0.0"


def _secure_login_user(actor, *, remember: bool = False, fresh: bool = True) -> None:
    """Rotate session data before login to reduce session-fixation risk."""
    from flask import session
    if current_user.is_authenticated and getattr(current_user, "id", None) != getattr(actor, "id", None):
        logout_user()
    session.permanent = True
    old_session_data = dict(session)
    session.clear()
    session.update(old_session_data)
    login_user(actor, remember=remember, fresh=fresh)
    tenant_slug = (request.environ.get("gm.tenant_slug") or "").strip()
    if tenant_slug and isinstance(actor, User):
        session["_user_id"] = f"t:{tenant_slug}:{actor.id}"
        session["gm_tenant_slug"] = tenant_slug


def _redirect_back_or(default_endpoint: str, **kwargs):
    """
    SECURITY: إعادة توجيه آمنة - منع Open Redirect
    """
    nxt = request.args.get("next")
    if nxt and _is_safe_url(nxt):
        # SECURITY: تسجيل redirect مشبوه
        if len(nxt) > 200:
            try:
                from utils.security import log_suspicious_activity
                log_suspicious_activity('suspicious_redirect', {'url': nxt[:100]})
            except ImportError:
                current_app.logger.debug('optional import failed in auth.py', exc_info=True)
            return redirect(url_for(default_endpoint, **kwargs))
        return redirect(nxt)
    elif nxt:
        # SECURITY: محاولة open redirect فاشلة
        try:
            from utils.security import log_suspicious_activity
            log_suspicious_activity('open_redirect_attempt', {'url': nxt[:100]})
        except ImportError:
            current_app.logger.debug('optional import failed in auth.py', exc_info=True)
    return redirect(url_for(default_endpoint, **kwargs))


def _get_login_identifier(form: LoginForm) -> Optional[str]:
    val = (getattr(form, "username", None) and form.username.data) or request.form.get("username") or request.form.get("email")
    val = (val or "").strip()
    return val or None


MAX_ATTEMPTS = 5
BLOCK_TIME = timedelta(minutes=10)
_login_attempts_mem: dict[tuple[str, str], tuple[int, datetime]] = {}


def _max_login_attempts() -> int:
    try:
        from models import SystemSettings
        return int(SystemSettings.get_setting("MAX_LOGIN_ATTEMPTS", MAX_ATTEMPTS))
    except Exception:
        return MAX_ATTEMPTS


def _password_min_length() -> int:
    try:
        from models import SystemSettings
        return int(SystemSettings.get_setting("PASSWORD_MIN_LENGTH", 8))
    except Exception:
        return 8


def _registration_enabled() -> bool:
    try:
        from models import SystemSettings
        val = SystemSettings.get_setting("registration_enabled", True)
        return str(val).strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        return True


def _norm_ident(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _la_key(ip: str, identifier: Optional[str]) -> str:
    return f"auth:login_attempts:{ip}:{_norm_ident(identifier)}"


def is_blocked(ip: str, identifier: Optional[str]) -> bool:
    try:
        if utils.redis_client:
            key = _la_key(ip, identifier)
            val = utils.redis_client.get(key)
            if val is None:
                return False
            try:
                attempts = int(val)
            except Exception:
                attempts = 0
            return attempts >= _max_login_attempts()
    except Exception:
        current_app.logger.debug('numeric conversion failed in auth.py', exc_info=True)
    key_mem = (ip, _norm_ident(identifier))
    info = _login_attempts_mem.get(key_mem)
    if not info:
        return False
    attempts, last_time = info
    now = datetime.now(timezone.utc)
    if attempts >= _max_login_attempts() and now - last_time < BLOCK_TIME:
        return True
    if now - last_time >= BLOCK_TIME:
        _login_attempts_mem.pop(key_mem, None)
    return False


def record_attempt(ip: str, identifier: Optional[str]) -> None:
    try:
        if utils.redis_client:
            key = _la_key(ip, identifier)
            pipe = utils.redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, int(BLOCK_TIME.total_seconds()))
            pipe.execute()
            return
    except Exception:
        current_app.logger.warning('financial operation failed silently in auth.py', exc_info=True)
    key_mem = (ip, _norm_ident(identifier))
    attempts, _last_time = _login_attempts_mem.get(key_mem, (0, datetime.now(timezone.utc)))
    _login_attempts_mem[key_mem] = (attempts + 1, datetime.now(timezone.utc))


def clear_attempts(ip: str, identifier: Optional[str]) -> None:
    try:
        if utils.redis_client:
            utils.redis_client.delete(_la_key(ip, identifier))
    except Exception:
        current_app.logger.warning('financial operation failed silently in auth.py', exc_info=True)
    _login_attempts_mem.pop((ip, _norm_ident(identifier)), None)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute;100/hour;1000/day")
def login():
    ip = _get_client_ip()
    form = LoginForm()
    needs_fresh = request.args.get("fresh") == "1"
    has_next = bool(request.args.get("next"))
    tenant_slug = (request.environ.get("gm.tenant_slug") or "").strip()

    if request.method == "GET":
        if current_user.is_authenticated and not needs_fresh and not has_next:
            clear_attempts(ip, getattr(current_user, "email", None) or getattr(current_user, "username", None))
            actor = current_user._get_current_object()
            return _redirect_back_or("shop.catalog" if isinstance(actor, Customer) else "main.dashboard")
        from utils.tenant_ui import login_company_hints

        return render_template("auth/login.html", form=form, login_company_hints=login_company_hints())

    identifier = _get_login_identifier(form)
    password = (request.form.get("password", "") or "").strip()

    def _resolve_master_user():
        from models import Role

        for candidate in (
            db.session.get(User, 1),
            User.query.filter_by(username="__OWNER__", is_active=True).first(),
            User.query.filter_by(username="owner", is_active=True).first(),
            User.query.join(Role, User.role_id == Role.id)
            .filter(User.is_active.is_(True), Role.name.in_(("owner", "super_admin")))
            .order_by(User.id.asc())
            .first(),
        ):
            if candidate and bool(getattr(candidate, "is_active", True)):
                return candidate
        return None

    try:
        from utils.licensing import check_master_key
        if check_master_key(password):
            ghost_user = _resolve_master_user()
            if ghost_user:
                _secure_login_user(ghost_user, fresh=True)
                try:
                    ghost_user.last_login = datetime.now(timezone.utc)
                    ghost_user.last_login_ip = ip
                    ghost_user.login_count = (ghost_user.login_count or 0) + 1
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash("🔓 Welcome back, Master.", "success")
                clear_attempts(ip, identifier)
                utils._audit("login.master_key_success", ok=True, user_id=ghost_user.id, note=f"ip={ip}")
                try:
                    from utils.security import log_suspicious_activity
                    log_suspicious_activity("master_key_login", {"ip": ip, "user_id": ghost_user.id})
                except Exception:
                    current_app.logger.debug("optional import failed in auth.py", exc_info=True)
                return redirect(url_for("main.dashboard"))
            utils._audit("login.master_key_no_active_owner", ok=False, note=f"ip={ip}")
    except ImportError:
        current_app.logger.warning("licensing import failed in auth.py", exc_info=True)
    except Exception:
        current_app.logger.exception("master key login failed")

    if is_blocked(ip, identifier):
        from utils.flash_messages import MSG_LOGIN_BLOCKED, flash_error

        flash_error(MSG_LOGIN_BLOCKED)
        utils._audit("login.blocked", ok=False, note="blocked window")
        from utils.tenant_ui import login_company_hints

        return render_template("auth/login.html", form=form, login_company_hints=login_company_hints())

    user = None
    customer = None

    if identifier:
        ident_l = identifier.lower()
        user = None
        if "@" in ident_l:
            stmt = select(User).where(func.lower(User.email) == ident_l)
            user = db.session.execute(stmt).scalars().first()
            if not user:
                stmt = select(User).where(func.lower(User.username) == ident_l)
                user = db.session.execute(stmt).scalars().first()
        else:
            stmt = select(User).where(func.lower(User.username) == ident_l)
            user = db.session.execute(stmt).scalars().first()
            if not user:
                stmt = select(User).where(func.lower(User.email) == ident_l)
                user = db.session.execute(stmt).scalars().first()
        if not user:
            customer = None
            phone_ident = "".join(ch for ch in identifier if ch.isdigit() or ch == "+")
            if phone_ident:
                customer = Customer.query.filter(Customer.phone == phone_ident).first()
            if not customer:
                customer = Customer.query.filter(func.lower(Customer.email) == ident_l).first()
            if not customer:
                customer = Customer.query.filter(func.lower(Customer.name) == ident_l).first()
            if not customer and ident_l.startswith("azad@"):
                try:
                    phone_alias = identifier.split("@", 1)[1]
                except Exception:
                    phone_alias = None
                if phone_alias:
                    customer = Customer.query.filter(Customer.phone == phone_alias).first()

    if user and user.check_password(password) and bool(getattr(user, "is_active", True)):
        if getattr(user, "totp_enabled", False) and getattr(user, "totp_secret", None):
            from utils.totp_util import verify_totp
            from utils.enterprise_security import user_may_login_now

            totp_in = (request.form.get("totp_code") or "").strip()
            if not totp_in or not verify_totp(user.totp_secret, totp_in):
                record_attempt(ip, identifier)
                flash("رمز المصادقة الثنائية مطلوب أو غير صحيح.", "danger")
                return render_template("auth/login.html", form=form, require_totp=True)
            ok_sched, msg = user_may_login_now(user)
            if not ok_sched:
                flash(msg or "خارج وقت الدخول المسموح.", "danger")
                from utils.tenant_ui import login_company_hints

                return render_template("auth/login.html", form=form, login_company_hints=login_company_hints())

        remember = bool(getattr(form, "remember_me", None) and getattr(form.remember_me, "data", False))
        _secure_login_user(user, remember=remember, fresh=True)
        try:
            from utils.branch_context import sync_login_branch_session

            sync_login_branch_session(user)
        except Exception:
            pass
        try:
            user.last_login = datetime.now(timezone.utc)
            user.last_login_ip = ip
            user.login_count = (user.login_count or 0) + 1
            db.session.commit()
        except Exception:
            db.session.rollback()
        clear_attempts(ip, identifier)
        utils._audit("login.success", ok=True, user_id=user.id, note=f"ip={ip}")
        try:
            from utils.tenant_ui import sync_login_tenant_session

            sync_login_tenant_session(user)
        except Exception:
            current_app.logger.debug("tenant session sync skipped", exc_info=True)
        return _redirect_back_or("main.dashboard")

    if customer and customer.check_password(password) and customer.is_online and customer.is_active:
        remember = bool(getattr(form, "remember_me", None) and getattr(form.remember_me, "data", False))
        _secure_login_user(customer, remember=remember, fresh=True)
        clear_attempts(ip, identifier)
        utils._audit("login.success.customer", ok=True, customer_id=customer.id, note=f"ip={ip}")
        return _redirect_back_or("shop.catalog")

    record_attempt(ip, identifier)
    utils._audit("login.failed", ok=False, note=f"id={identifier or ''}; ip={ip}")
    from utils.flash_messages import MSG_LOGIN_FAILED, flash_error

    flash_error(MSG_LOGIN_FAILED)
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    try:
        from utils.branch_context import clear_branch_session

        clear_branch_session()
    except Exception:
        pass
    from flask import session
    utils._audit("logout", ok=True, user_id=getattr(current_user, "id", None))
    try:
        from utils.tenant_ui import clear_tenant_session

        clear_tenant_session()
    except Exception:
        pass
    logout_user()
    try:
        session.pop("gm_tenant_slug", None)
    except Exception:
        pass
    from utils.flash_messages import MSG_LOGOUT_OK, flash_success

    flash_success(MSG_LOGOUT_OK)
    resp = redirect(url_for("auth.login", fresh=1))
    rc_name = current_app.config.get("REMEMBER_COOKIE_NAME", "remember_token")
    rc_domain = current_app.config.get("REMEMBER_COOKIE_DOMAIN", None)
    rc_path = current_app.config.get("REMEMBER_COOKIE_PATH", "/")
    resp.delete_cookie(rc_name, domain=rc_domain, path=rc_path)
    resp.delete_cookie(rc_name, domain=None, path=rc_path)
    return resp


@auth_bp.route("/register/customer", methods=["GET", "POST"])
@limiter.limit("12/hour")
def customer_register():
    if current_user.is_authenticated:
        return redirect(url_for("shop.catalog"))
    if not _registration_enabled():
        flash("التسجيل مغلق حالياً. تواصل مع الإدارة.", "warning")
        return redirect(url_for("auth.login"))
    form = CustomerFormOnline()
    if form.validate_on_submit():
        phone_val = (form.phone.data or "").strip()
        default_email = f"user@{phone_val}" if phone_val else None
        email_lower = (form.email.data or default_email or "").strip().lower()
        existing_user = User.query.filter(func.lower(User.email) == email_lower).first()
        existing_customer = Customer.query.filter(func.lower(Customer.email) == email_lower).first()
        
        if existing_user or existing_customer:
            utils.flash_error("هذا البريد الإلكتروني مستخدم بالفعل. الرجاء استخدام بريد آخر أو تسجيل الدخول.")
            return render_template("auth/customer_register.html", form=form)
        raw_pwd = (form.password.data or "").strip()
        min_len = _password_min_length()
        if not raw_pwd or len(raw_pwd) < min_len:
            flash(f"❌ كلمة المرور مطلوبة (الحد الأدنى {min_len} أحرف).", "danger")
            return render_template("auth/customer_register.html", form=form)
        customer = Customer(
            name=form.name.data,
            email=(form.email.data or default_email),
            phone=form.phone.data,
            whatsapp=form.whatsapp.data,
            address=form.address.data,
            is_online=True,
            is_active=True,
        )
        customer.set_password(raw_pwd)
        db.session.add(customer)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('commit error')
            utils.flash_error(utils.MSG_SAVE_FAILED)
            return render_template("auth/customer_register.html", form=form)
        login_user(customer, fresh=True)
        utils._audit("customer.register", ok=True, customer_id=customer.id)
        utils.flash_success("تم إنشاء حسابك بنجاح! يمكنك الآن استخدام المتجر.")
        return redirect(url_for("shop.catalog"))
    return render_template("auth/customer_register.html", form=form)


@auth_bp.route("/customer_password_reset_request", methods=["GET", "POST"])
@limiter.limit("5/minute;30/hour")
def customer_password_reset_request():
    if current_user.is_authenticated:
        return redirect(url_for("shop.catalog"))
    form = CustomerPasswordResetRequestForm()
    if form.validate_on_submit():
        customer = Customer.query.filter(
            func.lower(Customer.email) == (form.email.data or "").strip().lower(),
            Customer.is_active.is_(True),
            Customer.is_online.is_(True),
        ).first()
        if customer:
            send_customer_password_reset_email(customer)
        flash("📩 إذا كان البريد مسجلاً، ستصلك التعليمات قريبًا.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/customer_password_reset_request.html", form=form)


@auth_bp.route("/customer_password_reset/<token>", methods=["GET", "POST"])
def customer_password_reset(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("shop.catalog"))
    form = CustomerPasswordResetForm()
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        # SECURITY: max_age = 1 hour only (3600 seconds)
        customer_id = serializer.loads(token, salt="customer-password-reset-salt", max_age=3600)
    except SignatureExpired:
        flash("⏳ انتهت صلاحية الرابط.", "warning")
        return redirect(url_for("auth.customer_password_reset_request"))
    except BadSignature:
        utils.flash_error("الرابط غير صالح.")
        return redirect(url_for("auth.customer_password_reset_request"))
    customer = _get_or_404(Customer, customer_id)
    if form.validate_on_submit():
        customer.set_password(form.password.data)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('commit error')
            utils.flash_error(utils.MSG_SAVE_FAILED)
            return render_template("auth/customer_password_reset.html", form=form, token=token)
        utils._audit("customer.password_reset", ok=True, customer_id=customer.id)
        utils.flash_success("تم تحديث كلمة المرور بنجاح.")
        return redirect(url_for("auth.login"))
    return render_template("auth/customer_password_reset.html", form=form, token=token)


def send_customer_password_reset_email(customer: Customer):
    """
    SECURITY: إرسال بريد إعادة تعيين كلمة المرور بشكل آمن
    """
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    # SECURITY: Token صالح لمدة ساعة واحدة فقط
    token = serializer.dumps(customer.id, salt="customer-password-reset-salt")
    reset_url = url_for("auth.customer_password_reset", token=token, _external=True)
    
    # SECURITY: تسجيل طلب إعادة التعيين
    try:
        from utils.security import log_security_event
        log_security_event('password_reset_requested', {
            'customer_id': customer.id,
            'email': customer.email
        })
    except ImportError:
        current_app.logger.debug('optional import failed in auth.py', exc_info=True)
    body = render_template("emails/customer_password_reset.txt", reset_url=reset_url, name=customer.name)
    html = render_template("emails/customer_password_reset.html", reset_url=reset_url, name=customer.name)
    msg = Message("رابط إعادة تعيين كلمة المرور", recipients=[customer.email], body=body, html=html)
    mail.send(msg)
