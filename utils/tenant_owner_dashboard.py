"""
مؤشرات ولوحة مالك التينانت — داخل schema الشركة (search_path الحالي).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from extensions import cache, db
from sqlalchemy import func


def _today_bounds():
    today = date.today()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today + timedelta(days=1), time.min)
    return start, end


def _to_ils(amount, currency, fx_used, at_dt) -> Decimal:
    from models import convert_amount, fx_rate

    value = Decimal(str(amount or 0))
    code = (currency or "ILS").upper()
    if code == "ILS":
        return value
    if fx_used:
        try:
            return value * Decimal(str(fx_used))
        except Exception:
            pass
    try:
        rate = fx_rate(code, "ILS", at_dt, raise_on_missing=False)
        if rate and rate > 0:
            return value * Decimal(str(rate))
    except Exception:
        pass
    try:
        return convert_amount(value, code, "ILS", at_dt)
    except Exception:
        return value


@cache.memoize(timeout=180)
def get_tenant_owner_stats(tenant_slug: str) -> dict[str, Any]:
    """إحصائيات تشغيلية ومالية للتينانت (مُخزّنة 3 دقائق)."""
    from models import (
        Customer,
        FiscalPeriod,
        Payment,
        PaymentDirection,
        PaymentStatus,
        PreOrder,
        Product,
        Sale,
        SaleStatus,
        ServiceRequest,
        ServiceStatus,
        StockLevel,
        User,
    )

    slug = (tenant_slug or "").strip()
    day_start, day_end = _today_bounds()
    stats: dict[str, Any] = {
        "tenant_slug": slug,
        "total_users": 0,
        "active_users": 0,
        "online_users": 0,
        "today_sales_ils": 0.0,
        "today_payments_in_ils": 0.0,
        "today_sales_count": 0,
        "today_payments_count": 0,
        "pending_services": 0,
        "open_preorders": 0,
        "customers_total": 0,
        "customers_with_balance": 0,
        "receivables_ils": 0.0,
        "low_stock_count": 0,
        "inventory_units": 0,
        "open_fiscal_label": None,
        "open_fiscal_status": None,
        "week_sales_ils": 0.0,
    }

    try:
        stats["total_users"] = int(User.query.count())
        stats["active_users"] = int(User.query.filter_by(is_active=True).count())
        threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
        stats["online_users"] = int(
            User.query.filter(User.last_seen >= threshold).count()
        )
    except Exception:
        db.session.rollback()

    try:
        rows = (
            db.session.query(
                Sale.total_amount,
                Sale.currency,
                Sale.fx_rate_used,
                Sale.sale_date,
            )
            .filter(
                Sale.status == SaleStatus.CONFIRMED.value,
                Sale.sale_date >= day_start,
                Sale.sale_date < day_end,
            )
            .all()
        )
        total = Decimal("0")
        for amt, cur, fx, dt in rows:
            total += _to_ils(amt, cur, fx, dt)
        stats["today_sales_ils"] = float(total)
        stats["today_sales_count"] = len(rows)
    except Exception:
        db.session.rollback()

    try:
        week_start = datetime.combine(date.today() - timedelta(days=6), time.min)
        week_rows = (
            db.session.query(
                Sale.total_amount,
                Sale.currency,
                Sale.fx_rate_used,
                Sale.sale_date,
            )
            .filter(
                Sale.status == SaleStatus.CONFIRMED.value,
                Sale.sale_date >= week_start,
                Sale.sale_date < day_end,
            )
            .all()
        )
        week_total = Decimal("0")
        for amt, cur, fx, dt in week_rows:
            week_total += _to_ils(amt, cur, fx, dt)
        stats["week_sales_ils"] = float(week_total)
    except Exception:
        db.session.rollback()

    try:
        pay_rows = (
            db.session.query(
                Payment.total_amount,
                Payment.currency,
                Payment.fx_rate_used,
                Payment.payment_date,
            )
            .filter(
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.direction == PaymentDirection.IN.value,
                Payment.payment_date >= day_start,
                Payment.payment_date < day_end,
            )
            .all()
        )
        pay_total = Decimal("0")
        for amt, cur, fx, dt in pay_rows:
            pay_total += _to_ils(amt, cur, fx, dt)
        stats["today_payments_in_ils"] = float(pay_total)
        stats["today_payments_count"] = len(pay_rows)
    except Exception:
        db.session.rollback()

    try:
        stats["pending_services"] = int(
            ServiceRequest.query.filter(
                ServiceRequest.status.in_(
                    [
                        ServiceStatus.PENDING.value,
                        ServiceStatus.DIAGNOSIS.value,
                        ServiceStatus.IN_PROGRESS.value,
                        ServiceStatus.ON_HOLD.value,
                    ]
                )
            ).count()
        )
    except Exception:
        db.session.rollback()

    try:
        stats["open_preorders"] = int(
            PreOrder.query.filter(
                PreOrder.status.notin_(["FULFILLED", "CANCELLED"])
            ).count()
        )
    except Exception:
        db.session.rollback()

    try:
        stats["customers_total"] = int(Customer.query.count())
        stats["customers_with_balance"] = int(
            Customer.query.filter(Customer.current_balance > 0.01).count()
        )
        stats["receivables_ils"] = float(
            db.session.query(func.coalesce(func.sum(Customer.current_balance), 0)).scalar()
            or 0
        )
    except Exception:
        db.session.rollback()

    try:
        subq = (
            db.session.query(
                Product.id.label("pid"),
                func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"),
                func.coalesce(Product.min_qty, 0).label("min_qty"),
            )
            .outerjoin(StockLevel, StockLevel.product_id == Product.id)
            .filter(Product.is_active.is_(True))
            .group_by(Product.id, Product.min_qty)
            .subquery()
        )
        stats["inventory_units"] = int(
            db.session.query(func.coalesce(func.sum(subq.c.qty), 0)).scalar() or 0
        )
        stats["low_stock_count"] = int(
            db.session.query(func.count())
            .select_from(subq)
            .filter(subq.c.qty <= subq.c.min_qty)
            .scalar()
            or 0
        )
    except Exception:
        db.session.rollback()

    try:
        fp = (
            FiscalPeriod.query.filter_by(status="OPEN")
            .order_by(FiscalPeriod.end_date.desc())
            .first()
        )
        if fp:
            stats["open_fiscal_label"] = getattr(fp, "period_key", None) or str(
                getattr(fp, "fiscal_year", "")
            )
            stats["open_fiscal_status"] = getattr(fp, "status", "OPEN")
    except Exception:
        db.session.rollback()

    return stats


def get_tenant_registry_meta(slug: str) -> dict[str, Any]:
    """بيانات التينانت من جدول المنصة (public)."""
    from models import TenantRegistry

    slug = (slug or "").strip()
    row = TenantRegistry.query.filter_by(slug=slug).first()
    if not row:
        return {"slug": slug, "display_name": slug, "is_active": True, "schema_name": None}
    return {
        "slug": row.slug,
        "display_name": (row.display_name or row.slug or "").strip(),
        "schema_name": row.schema_name,
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
    }


def build_tenant_alerts(stats: dict[str, Any]) -> list[dict[str, str]]:
    """تنبيهات تشغيلية للمالك."""
    alerts: list[dict[str, str]] = []
    if not stats.get("is_active", True):
        alerts.append(
            {
                "level": "danger",
                "icon": "fa-ban",
                "message": "حساب التينانت غير مفعّل على المنصة — تواصل مع دعم أزاد.",
            }
        )
    low = int(stats.get("low_stock_count") or 0)
    if low > 0:
        alerts.append(
            {
                "level": "warning",
                "icon": "fa-boxes",
                "message": f"{low} منتج تحت حد إعادة الطلب أو نفد المخزون.",
            }
        )
    pending = int(stats.get("pending_services") or 0)
    if pending > 0:
        alerts.append(
            {
                "level": "info",
                "icon": "fa-wrench",
                "message": f"{pending} طلب صيانة قيد التنفيذ أو الانتظار.",
            }
        )
    recv = float(stats.get("receivables_ils") or 0)
    if recv > 1000:
        alerts.append(
            {
                "level": "warning",
                "icon": "fa-hand-holding-usd",
                "message": f"ذمم زبائن مجمّعة: {recv:,.2f} ₪ — راجع التحصيل.",
            }
        )
    if stats.get("open_fiscal_label") is None:
        alerts.append(
            {
                "level": "secondary",
                "icon": "fa-calendar",
                "message": "لا توجد فترة مالية مفتوحة — راجع إقفال الفترات.",
            }
        )
    return alerts


def get_tenant_recent_audit(limit: int = 12) -> list:
    from models import AuditLog, User
    from sqlalchemy.orm import joinedload

    try:
        return (
            AuditLog.query.options(joinedload(AuditLog.user))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        db.session.rollback()
        return []


def build_tenant_quick_actions(user) -> list[dict[str, str]]:
    """اختصارات حسب صلاحيات المستخدم."""
    from utils.tenant_permissions import user_can_access_hub_endpoint

    candidates = (
        ("main.dashboard", "لوحة التشغيل", "fa-tachometer-alt", "primary"),
        ("sales_bp.list_sales", "المبيعات", "fa-shopping-cart", "success"),
        ("payments.index", "الدفعات", "fa-money-bill-wave", "success"),
        ("customers_bp.list_customers", "الزبائن", "fa-user-friends", "info"),
        ("service.list_requests", "الصيانة", "fa-wrench", "info"),
        ("ledger_control.index", "دفتر الأستاذ", "fa-book", "primary"),
        ("tenant_fiscal_bp.index", "إقفال الفترات", "fa-calendar-check", "dark"),
        ("financial_reports.index", "التقارير المالية", "fa-file-invoice-dollar", "secondary"),
        ("tenant_console.branding", "الهوية", "fa-palette", "warning"),
        ("users_bp.list_users", "المستخدمون", "fa-users", "success"),
        ("tenant_console.activity", "سجل النشاط", "fa-history", "dark"),
    )
    out = []
    for endpoint, label, icon, color in candidates:
        if user_can_access_hub_endpoint(user, endpoint):
            out.append(
                {
                    "endpoint": endpoint,
                    "label": label,
                    "icon": icon,
                    "color": color,
                }
            )
    return out


@cache.memoize(timeout=300)
def get_platform_saas_snapshot() -> dict[str, Any]:
    """ملخص التينانتات لمالك المنصة."""
    from models import TenantRegistry

    try:
        total = int(TenantRegistry.query.count())
        active = int(TenantRegistry.query.filter_by(is_active=True).count())
        return {
            "tenants_total": total,
            "tenants_active": active,
            "tenants_inactive": max(0, total - active),
        }
    except Exception:
        db.session.rollback()
        return {"tenants_total": 0, "tenants_active": 0, "tenants_inactive": 0}
