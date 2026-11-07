"""تحميل وحفظ صفحة /security/system-settings — تبويبات حقيقية مربوطة بقاعدة البيانات."""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


VALID_TABS = frozenset({"general", "advanced", "company", "business", "branding"})


def normalize_tab(tab: Optional[str]) -> str:
    t = (tab or "general").strip().lower()
    return t if t in VALID_TABS else "general"


def _get(key: str, default=None):
    from models import SystemSettings

    return SystemSettings.get_setting(key, default)


def _set(key: str, value, *, data_type: str = "string", commit: bool = False):
    from models import SystemSettings

    SystemSettings.set_setting(key, value, data_type=data_type, commit=commit)


def _as_bool(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "on")


def _as_int(val, default: int) -> int:
    try:
        if val is None or str(val).strip() == "":
            return default
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _as_float(val, default: float) -> float:
    try:
        if val is None or str(val).strip() == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def invalidate_settings_cache() -> None:
    from extensions import cache

    try:
        cache.delete("system_settings:template_settings:v1")
    except Exception:
        pass
    try:
        cache.delete_memoized("routes.security.get_cached_security_stats")
    except Exception:
        pass
    try:
        from routes.security import get_cached_security_stats

        cache.delete_memoized(get_cached_security_stats)
    except Exception:
        pass
    try:
        _set("assets_version", int(time.time()), data_type="number", commit=True)
    except Exception:
        pass


def _active_company():
    from models import Company
    from utils.tenant_ui import build_tenant_context

    tctx = build_tenant_context()
    cid = tctx.get("tenant_company_id")
    if cid:
        return Company.query.get(int(cid))
    return Company.query.filter_by(is_active=True).order_by(Company.id.asc()).first()


def load_system_settings_page_data() -> Dict[str, Any]:
    from models import SystemSettings

    co = _active_company()
    company_name_setting = _get("COMPANY_NAME") or _get("company_name") or ""
    if co and co.name and not company_name_setting:
        company_name_setting = co.name

    return {
        "general": {
            "maintenance_mode": bool(_get("maintenance_mode", False)),
            "registration_enabled": bool(_get("registration_enabled", True)),
            "api_enabled": bool(_get("api_enabled", True)),
        },
        "advanced": {
            "SESSION_TIMEOUT": _as_int(_get("SESSION_TIMEOUT", 3600), 3600),
            "MAX_LOGIN_ATTEMPTS": _as_int(_get("MAX_LOGIN_ATTEMPTS", 5), 5),
            "PASSWORD_MIN_LENGTH": _as_int(_get("PASSWORD_MIN_LENGTH", 8), 8),
            "AUTO_BACKUP_ENABLED": bool(_get("AUTO_BACKUP_ENABLED", True)),
            "BACKUP_INTERVAL_HOURS": _as_int(_get("BACKUP_INTERVAL_HOURS", 24), 24),
            "ENABLE_EMAIL_NOTIFICATIONS": bool(_get("ENABLE_EMAIL_NOTIFICATIONS", True)),
            "ENABLE_SMS_NOTIFICATIONS": bool(_get("ENABLE_SMS_NOTIFICATIONS", False)),
        },
        "company": {
            "company_id": int(co.id) if co else None,
            "company_code": (co.code if co else "") or "",
            "legal_entity_name": (co.name if co else "") or "",
            "COMPANY_NAME": company_name_setting or (co.name if co else "اسم الشركة"),
            "COMPANY_ADDRESS": _get("COMPANY_ADDRESS") or (co.address if co else "") or "",
            "COMPANY_PHONE": _get("COMPANY_PHONE") or (co.phone if co else "") or "",
            "COMPANY_EMAIL": _get("COMPANY_EMAIL") or (co.email if co else "") or "",
            "TAX_NUMBER": _get("TAX_NUMBER") or (co.tax_id if co else "") or "",
            "CURRENCY_SYMBOL": _get("CURRENCY_SYMBOL", "₪"),
            "TIMEZONE": _get("TIMEZONE", "Asia/Jerusalem"),
            "DATE_FORMAT": _get("DATE_FORMAT", "%Y-%m-%d"),
            "TIME_FORMAT": _get("TIME_FORMAT", "%H:%M:%S"),
        },
        "business": {
            "enable_tax_constants": SystemSettings.get_setting("enable_tax_constants", True),
            "enable_payroll_constants": SystemSettings.get_setting("enable_payroll_constants", True),
            "enable_asset_constants": SystemSettings.get_setting("enable_asset_constants", True),
            "enable_accounting_constants": SystemSettings.get_setting("enable_accounting_constants", True),
            "enable_notification_constants": SystemSettings.get_setting("enable_notification_constants", True),
            "enable_business_rules_constants": SystemSettings.get_setting("enable_business_rules_constants", True),
            "enable_multi_tenancy_constants": SystemSettings.get_setting("enable_multi_tenancy_constants", True),
            "default_vat_rate": SystemSettings.get_setting("default_vat_rate", 16.0),
            "vat_enabled": SystemSettings.get_setting("vat_enabled", True),
            "income_tax_rate": SystemSettings.get_setting("income_tax_rate", 15.0),
            "withholding_tax_rate": SystemSettings.get_setting("withholding_tax_rate", 5.0),
            "social_insurance_enabled": SystemSettings.get_setting("social_insurance_enabled", False),
            "social_insurance_company": SystemSettings.get_setting("social_insurance_company", 7.5),
            "social_insurance_employee": SystemSettings.get_setting("social_insurance_employee", 7.0),
            "overtime_rate_normal": SystemSettings.get_setting("overtime_rate_normal", 1.5),
            "working_hours_per_day": SystemSettings.get_setting("working_hours_per_day", 8),
            "asset_auto_depreciation": SystemSettings.get_setting("asset_auto_depreciation", True),
            "asset_threshold_amount": SystemSettings.get_setting("asset_threshold_amount", 500),
            "cost_centers_enabled": SystemSettings.get_setting("cost_centers_enabled", False),
            "budgeting_enabled": SystemSettings.get_setting("budgeting_enabled", False),
            "fiscal_year_start_month": SystemSettings.get_setting("fiscal_year_start_month", 1),
            "notify_on_service_complete": SystemSettings.get_setting("notify_on_service_complete", True),
            "notify_on_payment_due": SystemSettings.get_setting("notify_on_payment_due", True),
            "notify_on_low_stock": SystemSettings.get_setting("notify_on_low_stock", True),
            "payment_reminder_days": SystemSettings.get_setting("payment_reminder_days", 3),
            "allow_negative_stock": SystemSettings.get_setting("allow_negative_stock", False),
            "require_approval_for_sales_above": SystemSettings.get_setting("require_approval_for_sales_above", 10000),
            "discount_max_percent": SystemSettings.get_setting("discount_max_percent", 50),
            "credit_limit_check": SystemSettings.get_setting("credit_limit_check", True),
            "multi_tenancy_enabled": SystemSettings.get_setting("multi_tenancy_enabled", False),
            "trial_period_days": SystemSettings.get_setting("trial_period_days", 30),
        },
        "branding": {
            "system_name": _get("system_name", "نظام الحازم"),
            "company_name": _get("company_name", "شركة الحازم للأنظمة الذكية"),
            "login_title": _get("login_title", "مرحباً بك"),
            "login_subtitle": _get("login_subtitle", "سجل دخولك للمتابعة"),
            "footer_text": _get("footer_text", "جميع الحقوق محفوظة"),
            "primary_color": _get("primary_color", "#007bff"),
            "secondary_color": _get("secondary_color", "#1f2937"),
            "sidebar_bg": _get("sidebar_bg", "#111827"),
            "sidebar_text": _get("sidebar_text", "#f9fafb"),
            "company_logo": _get("custom_logo", "") or "",
            "tenant_logo_url": "",
        },
    }


def _save_general(form) -> None:
    _set("maintenance_mode", form.get("maintenance_mode") == "on", data_type="boolean", commit=False)
    _set("registration_enabled", form.get("registration_enabled") == "on", data_type="boolean", commit=False)
    _set("api_enabled", form.get("api_enabled") == "on", data_type="boolean", commit=False)


def _save_advanced(form) -> None:
    _set("SESSION_TIMEOUT", _as_int(form.get("session_timeout"), 3600), data_type="number", commit=False)
    _set("MAX_LOGIN_ATTEMPTS", _as_int(form.get("max_login_attempts"), 5), data_type="number", commit=False)
    _set("PASSWORD_MIN_LENGTH", _as_int(form.get("password_min_length"), 8), data_type="number", commit=False)
    _set("AUTO_BACKUP_ENABLED", form.get("auto_backup_enabled") == "on", data_type="boolean", commit=False)
    _set("BACKUP_INTERVAL_HOURS", _as_int(form.get("backup_interval_hours"), 24), data_type="number", commit=False)
    _set("ENABLE_EMAIL_NOTIFICATIONS", form.get("enable_email_notifications") == "on", data_type="boolean", commit=False)
    _set("ENABLE_SMS_NOTIFICATIONS", form.get("enable_sms_notifications") == "on", data_type="boolean", commit=False)


def _save_company(form) -> None:
    from extensions import db
    from models import Company

    legal_name = (form.get("legal_entity_name") or "").strip()
    display_name = (form.get("company_name") or "").strip()
    address = (form.get("company_address") or "").strip()
    phone = (form.get("company_phone") or "").strip()
    email = (form.get("company_email") or "").strip()
    tax_number = (form.get("tax_number") or "").strip()

    company_id = form.get("company_id")
    co = None
    if company_id:
        try:
            co = db.session.get(Company, int(company_id))
        except (TypeError, ValueError):
            co = None
    if co is None:
        co = _active_company()

    if co:
        if legal_name:
            co.name = legal_name
        if address:
            co.address = address
        if phone:
            co.phone = phone
        if email:
            co.email = email
        if tax_number:
            co.tax_id = tax_number

    name_for_reports = display_name or legal_name or (co.name if co else "")
    _set("COMPANY_NAME", name_for_reports, commit=False)
    _set("company_name", name_for_reports, commit=False)
    _set("COMPANY_ADDRESS", address, commit=False)
    _set("COMPANY_PHONE", phone, commit=False)
    _set("COMPANY_EMAIL", email, commit=False)
    _set("TAX_NUMBER", tax_number, commit=False)
    _set("CURRENCY_SYMBOL", (form.get("currency_symbol") or "₪").strip(), commit=False)
    _set("TIMEZONE", (form.get("timezone") or "Asia/Jerusalem").strip(), commit=False)
    _set("DATE_FORMAT", (form.get("date_format") or "%Y-%m-%d").strip(), commit=False)
    _set("TIME_FORMAT", (form.get("time_format") or "%H:%M:%S").strip(), commit=False)


def _save_business(form) -> None:
    group_flags = {
        "tax": form.get("enable_tax_constants") == "on",
        "payroll": form.get("enable_payroll_constants") == "on",
        "assets": form.get("enable_asset_constants") == "on",
        "accounting": form.get("enable_accounting_constants") == "on",
        "notifications": form.get("enable_notification_constants") == "on",
        "business_rules": form.get("enable_business_rules_constants") == "on",
        "multi_tenancy": form.get("enable_multi_tenancy_constants") == "on",
    }
    descriptions = {
        "tax": "تفعيل ثوابت الضرائب",
        "payroll": "تفعيل ثوابت الرواتب",
        "assets": "تفعيل ثوابت الأصول الثابتة",
        "accounting": "تفعيل ثوابت المحاسبة",
        "notifications": "تفعيل ثوابت الإشعارات",
        "business_rules": "تفعيل ثوابت قواعد العمل",
        "multi_tenancy": "تفعيل ثوابت التعددية",
    }
    for group, enabled in group_flags.items():
        _set(f"enable_{group}_constants", enabled, data_type="boolean", commit=False)

    _set("default_vat_rate", _as_float(form.get("default_vat_rate"), 16.0), data_type="number", commit=False)
    _set("vat_enabled", form.get("vat_enabled") == "on", data_type="boolean", commit=False)
    _set("income_tax_rate", _as_float(form.get("income_tax_rate"), 15.0), data_type="number", commit=False)
    _set("withholding_tax_rate", _as_float(form.get("withholding_tax_rate"), 5.0), data_type="number", commit=False)
    _set("social_insurance_enabled", form.get("social_insurance_enabled") == "on", data_type="boolean", commit=False)
    _set("social_insurance_company", _as_float(form.get("social_insurance_company"), 7.5), data_type="number", commit=False)
    _set("social_insurance_employee", _as_float(form.get("social_insurance_employee"), 7.0), data_type="number", commit=False)
    _set("overtime_rate_normal", _as_float(form.get("overtime_rate_normal"), 1.5), data_type="number", commit=False)
    _set("working_hours_per_day", _as_int(form.get("working_hours_per_day"), 8), data_type="number", commit=False)
    _set("asset_auto_depreciation", form.get("asset_auto_depreciation") == "on", data_type="boolean", commit=False)
    _set("asset_threshold_amount", _as_float(form.get("asset_threshold_amount"), 500), data_type="number", commit=False)
    _set("cost_centers_enabled", form.get("cost_centers_enabled") == "on", data_type="boolean", commit=False)
    _set("budgeting_enabled", form.get("budgeting_enabled") == "on", data_type="boolean", commit=False)
    _set("fiscal_year_start_month", _as_int(form.get("fiscal_year_start_month"), 1), data_type="number", commit=False)
    _set("notify_on_service_complete", form.get("notify_on_service_complete") == "on", data_type="boolean", commit=False)
    _set("notify_on_payment_due", form.get("notify_on_payment_due") == "on", data_type="boolean", commit=False)
    _set("notify_on_low_stock", form.get("notify_on_low_stock") == "on", data_type="boolean", commit=False)
    _set("payment_reminder_days", _as_int(form.get("payment_reminder_days"), 3), data_type="number", commit=False)
    _set("allow_negative_stock", form.get("allow_negative_stock") == "on", data_type="boolean", commit=False)
    _set(
        "require_approval_for_sales_above",
        _as_float(form.get("require_approval_for_sales_above"), 10000),
        data_type="number",
        commit=False,
    )
    _set("discount_max_percent", _as_float(form.get("discount_max_percent"), 50), data_type="number", commit=False)
    _set("credit_limit_check", form.get("credit_limit_check") == "on", data_type="boolean", commit=False)
    _set("multi_tenancy_enabled", form.get("multi_tenancy_enabled") == "on", data_type="boolean", commit=False)
    _set("trial_period_days", _as_int(form.get("trial_period_days"), 30), data_type="number", commit=False)


def _save_branding(form, logo_file: Optional[FileStorage]) -> Optional[str]:
    """Returns error message or None on success."""
    for key in ("system_name", "company_name", "login_title", "login_subtitle", "footer_text"):
        val = (form.get(key) or "").strip()
        if val:
            _set(key, val, commit=False)

    for key in ("primary_color", "secondary_color", "sidebar_bg", "sidebar_text"):
        val = (form.get(key) or "").strip()
        if val:
            _set(key, val, commit=False)

    if logo_file and logo_file.filename:
        from utils.branding_assets import save_tenant_logo_upload

        filename = secure_filename(logo_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return "نوع ملف الشعار غير مدعوم (png, jpg, jpeg, gif, webp)"

        co = _active_company()
        company_code = (co.code if co and co.code else "MAIN").strip().upper()

        import tempfile

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                logo_file.save(tmp.name)
                tmp_path = tmp.name
            result = save_tenant_logo_upload(
                current_app.root_path,
                company_code,
                "main",
                tmp_path,
            )
            os.unlink(tmp_path)
            if not result:
                return "تعذّر حفظ الشعار — تحقق من رمز الشركة"
            rel_path, _setting_key = result
            from utils.branding_assets import default_company_code, persist_tenant_logo_settings

            persist_tenant_logo_settings(
                company_code,
                rel_path,
                "logo",
                set_setting=_set,
                default_code=default_company_code(),
            )
        except Exception:
            current_app.logger.exception("system_settings branding logo upload failed")
            return "حدث خطأ أثناء رفع الشعار"
    return None


def save_system_settings_tab(tab: str, form, files) -> Tuple[bool, Optional[str]]:
    """Save one tab. Returns (ok, error_message)."""
    from extensions import db

    tab = normalize_tab(tab)
    try:
        if tab == "general":
            _save_general(form)
        elif tab == "advanced":
            _save_advanced(form)
        elif tab == "company":
            _save_company(form)
        elif tab == "business":
            _save_business(form)
        elif tab == "branding":
            err = _save_branding(form, files.get("custom_logo") if files else None)
            if err:
                return False, err
        db.session.commit()
        invalidate_settings_cache()
        return True, None
    except Exception:
        db.session.rollback()
        current_app.logger.exception("save_system_settings_tab failed tab=%s", tab)
        return False, "حدث خطأ أثناء الحفظ"
