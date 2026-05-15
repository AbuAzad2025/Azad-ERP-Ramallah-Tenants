"""ERP policy advisor for the AI assistant."""

from __future__ import annotations

from typing import Dict, List

POLICIES = {
    "segregation_of_duties": {
        "title": "فصل الصلاحيات",
        "level": "critical",
        "rule": "لا يكون نفس المستخدم مسؤولاً عن الإنشاء والاعتماد والحذف للحركات المالية الحساسة.",
        "recommendation": "افصل صلاحيات البيع والدفع والحذف والإدارة بين أكثر من دور.",
    },
    "large_payment_reference": {
        "title": "مرجع إلزامي للحركات الكبيرة",
        "level": "high",
        "rule": "أي دفعة أو مصروف كبير يجب أن يحتوي مرجعاً أو مرفقاً واضحاً.",
        "recommendation": "اجعل المرجع والمرفق إلزاميين فوق حد مالي تحدده الإدارة.",
    },
    "second_approval": {
        "title": "موافقة ثانية",
        "level": "high",
        "rule": "الحذف والإلغاء والخصم الكبير وتعديل المخزون تحتاج موافقة ثانية.",
        "recommendation": "أضف سير اعتماد للحركات الحساسة قبل تنفيذها أو اعتمادها النهائي.",
    },
    "negative_stock": {
        "title": "منع المخزون السالب",
        "level": "critical",
        "rule": "لا يسمح بوصول المخزون إلى كمية سالبة إلا بصلاحية استثنائية وسبب موثق.",
        "recommendation": "فعّل منع المخزون السالب أو اطلب موافقة مدير مع سبب.",
    },
    "audit_trail": {
        "title": "أثر تدقيق غير قابل للمحو",
        "level": "critical",
        "rule": "كل حذف أو تعديل حساس يجب أن يحفظ قبل/بعد ومن نفذه ومتى ولماذا.",
        "recommendation": "استخدم الأرشفة مع سبب بدل الحذف المباشر للحركات المالية.",
    },
    "ai_scope": {
        "title": "نطاق المساعد الذكي",
        "level": "critical",
        "rule": "المساعد لا يعرض إلا ما تسمح به صلاحيات المستخدم ولا ينفذ حركات مدمرة من المحادثة.",
        "recommendation": "أبقِ تنفيذ الحركات الحساسة خارج المحادثة أو خلف موافقة صريحة وصلاحية قوية.",
    },
}


def get_policy_catalog() -> Dict:
    return POLICIES


def evaluate_policy_gaps(active_features: Dict = None) -> Dict:
    active_features = active_features or {}
    gaps: List[Dict] = []
    for key, policy in POLICIES.items():
        enabled = bool(active_features.get(key, False))
        if not enabled:
            gaps.append({"policy": key, "title": policy["title"], "level": policy["level"], "recommendation": policy["recommendation"]})
    critical = sum(1 for item in gaps if item["level"] == "critical")
    high = sum(1 for item in gaps if item["level"] == "high")
    return {"total_policies": len(POLICIES), "gaps": gaps, "critical_gaps": critical, "high_gaps": high, "status": "excellent" if not gaps else "needs_policy_activation"}


__all__ = ["get_policy_catalog", "evaluate_policy_gaps"]
