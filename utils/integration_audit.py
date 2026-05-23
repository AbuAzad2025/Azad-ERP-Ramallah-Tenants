"""تدقيق تكامل سريع — متوافق مع SaaS (schema التينانت الحالي)."""
from __future__ import annotations

from typing import Any, Dict, List


def run_integration_audit(app) -> Dict[str, Any]:
    """فحوصات تكامل دون تعديل البيانات."""
    from extensions import db

    issues: List[Dict[str, str]] = []
    with app.app_context():
        try:
            from models import Branch, FiscalPeriod

            Branch.query.limit(1).all()
            FiscalPeriod.query.limit(1).all()
        except Exception as e:
            issues.append({"level": "critical", "msg": f"فروع/فترات محاسبية: {e}"})

        try:
            from utils.tenant_fiscal_schema import FISCAL_TABLES
            from sqlalchemy import inspect

            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            missing = [t for t in FISCAL_TABLES if t not in tables]
            if missing:
                issues.append({
                    "level": "warning",
                    "msg": f"جداول إقفال ناقصة في schema الحالي: {', '.join(missing)} — شغّل tenants-ensure-fiscal-tables",
                })
        except Exception as e:
            issues.append({"level": "warning", "msg": f"فحص fiscal tables: {e}"})

        try:
            from models import TenantRegistry

            TenantRegistry.query.limit(1).all()
        except Exception as e:
            issues.append({"level": "info", "msg": f"TenantRegistry (public): {e}"})

        try:
            from utils.payment_allocation_policy import payment_auto_allocate_enabled

            if payment_auto_allocate_enabled():
                issues.append({
                    "level": "info",
                    "msg": "التوزيع التلقائي مفعّل — الافتراضي الآمن: دفعة على حساب الزبون فقط",
                })
            else:
                issues.append({
                    "level": "info",
                    "msg": "التوزيع التلقائي معطّل — دفعة على حساب الزبون (الافتراضي)",
                })
        except Exception as e:
            issues.append({"level": "warning", "msg": f"سياسة التوزيع: {e}"})

    return {
        "ok": not any(i["level"] == "critical" for i in issues),
        "issues": issues,
        "issue_count": len(issues),
    }
