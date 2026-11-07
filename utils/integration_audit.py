"""تدقيق تكامل سريع — يُستدعى من CLI."""
from __future__ import annotations

from typing import Any, Dict, List


def run_integration_audit(app) -> Dict[str, Any]:
    """فحوصات تكامل دون تعديل البيانات."""
    from extensions import db
    from models import Company, Branch, PurchaseOrder, PaymentAllocation, GLBatch

    issues: List[Dict[str, str]] = []
    with app.app_context():
        try:
            Company.query.limit(1).all()
        except Exception as e:
            issues.append({"level": "critical", "msg": f"جدول companies: {e}"})
        try:
            PaymentAllocation.query.limit(1).all()
        except Exception as e:
            issues.append({"level": "critical", "msg": f"جدول payment_allocations: {e}"})
        orphan_branches = Branch.query.filter(Branch.company_id.is_(None)).count()
        if orphan_branches:
            issues.append({
                "level": "warning",
                "msg": f"{orphan_branches} فرع بلا company_id",
            })
        po_gl = GLBatch.query.filter_by(source_type="PURCHASE_ORDER").count()
        if po_gl == 0:
            issues.append({
                "level": "info",
                "msg": "لا قيود GL لأوامر شراء بعد — طبيعي حتى أول استلام RECEIVED",
            })
        from utils.payment_allocation_policy import payment_auto_allocate_enabled
        if payment_auto_allocate_enabled():
            issues.append({
                "level": "info",
                "msg": "التوزيع التلقائي مفعّل (auto_allocate أو PAYMENT_ALLOCATION_ENABLED)",
            })
        else:
            issues.append({
                "level": "info",
                "msg": "التوزيع التلقائي معطّل — دفعة على حساب الزبون (الافتراضي)",
            })

    return {
        "ok": not any(i["level"] == "critical" for i in issues),
        "issues": issues,
        "issue_count": len(issues),
    }
