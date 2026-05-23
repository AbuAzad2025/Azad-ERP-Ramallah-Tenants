"""AI Database Expert.

Schema and SQL expert for the assistant. It does not execute arbitrary user SQL;
it explains tables, relationships, safe filters, and workflow-aware data access
from the actual SQLAlchemy/DB schema.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect

from extensions import db

BUSINESS_DOMAINS = {
    "customers": {"keywords": ["زبون", "زبائن", "زبون", "customer", "client", "رصيد زبون", "كشف زبون"], "models": ["Customer", "Invoice", "Sale", "Payment", "ServiceRequest"], "expert_focus": ["الاسم والهاتف لتجنب التكرار", "الرصيد لا يفسر دون سياسة النظام", "كشف الزبون يجمع الفواتير والدفعات والصيانة"]},
    "suppliers": {"keywords": ["مورد", "موردين", "supplier", "vendor", "كشف مورد"], "models": ["Supplier", "Payment", "SupplierSettlement", "Product"], "expert_focus": ["مراجعة المستحقات والتسويات", "تمييز المورد عن الزبون", "ربط المورد بالمشتريات أو المنتجات عند توفر العلاقة"]},
    "sales": {"keywords": ["بيع", "مبيعات", "sale", "sales", "فاتورة", "invoice"], "models": ["Sale", "SaleLine", "Invoice", "Payment", "Customer", "StockLevel"], "expert_focus": ["الزبون والمستودع والكمية قبل الحفظ", "VAT من الإعدادات فقط", "راجع أثر البيع على المخزون والذمة"]},
    "payments": {"keywords": ["دفعة", "دفعات", "payment", "قبض", "صرف", "تحصيل"], "models": ["Payment", "Customer", "Supplier", "Invoice", "Sale"], "expert_focus": ["اتجاه الدفعة IN/OUT", "ربط الدفعة بالجهة والفاتورة", "المرجع وطريقة الدفع مهمان للتدقيق"]},
    "inventory": {"keywords": ["مخزون", "مخزن", "warehouse", "stock", "inventory", "منتج", "product"], "models": ["Product", "Warehouse", "StockLevel", "Shipment", "ServicePart", "SaleLine"], "expert_focus": ["كل كمية يجب أن تكون مرتبطة بمنتج ومستودع", "تجنب تعديل الكمية بلا حركة", "راقب المنتجات تحت الحد الأدنى"]},
    "services": {"keywords": ["صيانة", "service", "ورشة", "عطل", "مركبة"], "models": ["ServiceRequest", "ServicePart", "ServiceTask", "Customer", "Product", "Payment"], "expert_focus": ["فصل وصف العطل عن التشخيص", "قطع الصيانة تؤثر على المخزون", "راجع التكلفة والدفعة قبل الإغلاق"]},
    "finance": {"keywords": ["محاسب", "قيد", "دفتر", "ledger", "gl", "مصروف", "expense", "ضريبة", "vat"], "models": ["Account", "GLBatch", "GLEntry", "Expense", "Payment", "Invoice", "ExchangeRate", "SystemSettings"], "expert_focus": ["كل قيد يجب أن يتوازن", "الضرائب وأسعار الصرف من الإعدادات/ExchangeRate", "التقارير تعتمد على التاريخ والعملة"]},
}


class DatabaseExpert:
    def __init__(self):
        self.common_patterns = self._load_common_patterns()

    def analyze_query(self, query: str) -> Dict[str, Any]:
        query = str(query or "")
        analysis = {"query": query, "issues": [], "performance_score": 100, "suggestions": [], "optimized_query": None, "estimated_complexity": "unknown"}
        upper = query.upper()

        if "SELECT *" in upper:
            analysis["issues"].append({"type": "bad_practice", "severity": "medium", "message": "استخدام SELECT * - حدد الأعمدة المطلوبة فقط", "fix": "استبدل * بأسماء الأعمدة المحددة"})
            analysis["performance_score"] -= 10
        if "WHERE" not in upper and "SELECT" in upper:
            analysis["issues"].append({"type": "missing_where", "severity": "high", "message": "لا يوجد WHERE clause - قد يعيد جميع السجلات", "fix": "أضف WHERE لتحديد السجلات المطلوبة"})
            analysis["performance_score"] -= 20
            analysis["estimated_complexity"] = "likely full table scan"
        if "LIMIT" not in upper and "SELECT" in upper:
            analysis["suggestions"].append("أضف LIMIT للحد من عدد النتائج المعادة عند الاستعراض")
        join_count = upper.count("JOIN")
        if join_count > 3:
            analysis["issues"].append({"type": "many_joins", "severity": "medium", "message": f"عدد كبير من JOINs ({join_count}) - قد يؤثر على الأداء", "fix": "راجع خطة التنفيذ أو فكر في indexes مناسبة"})
            analysis["performance_score"] -= (join_count - 3) * 5
        if re.search(r"LIKE\s+['\"]%.*%['\"]", query, re.IGNORECASE):
            analysis["issues"].append({"type": "slow_like", "severity": "high", "message": "LIKE %...% بطيء غالباً ولا يستفيد من index عادي", "fix": "استخدم Full-Text Search أو نمط يبدأ بحرف ثابت إذا أمكن"})
            analysis["performance_score"] -= 25
        or_count = len(re.findall(r"\bOR\b", query, re.IGNORECASE))
        if or_count > 2:
            analysis["suggestions"].append(f"عدد كبير من OR ({or_count}) - فكر في استخدام IN إذا كانت المقارنة على نفس العمود")
        if "SELECT" in query[10:].upper():
            analysis["suggestions"].append("يوجد subquery - راجع إن كان JOIN أو EXISTS أفضل حسب خطة التنفيذ")
        analysis["performance_score"] = max(0, min(100, analysis["performance_score"]))
        return analysis

    def describe_business_question(self, question: str) -> Dict[str, Any]:
        """Map a user/business question to likely schema areas and expert checks."""
        q = str(question or "").lower()
        matches = []
        for domain, data in BUSINESS_DOMAINS.items():
            score = sum(1 for kw in data["keywords"] if kw.lower() in q)
            if score:
                matches.append({"domain": domain, "score": score, "models": self._existing_models(data["models"]), "expert_focus": data["expert_focus"], "safe_filters": self._safe_filters_for_domain(domain)})
        matches.sort(key=lambda item: item["score"], reverse=True)
        return {"question": question, "matches": matches, "best_match": matches[0] if matches else None, "note": "Use these models as candidates; confirm live columns before querying."}

    def summarize_model(self, model_name: str) -> Dict[str, Any]:
        """Return a practical summary of a SQLAlchemy model/table if it exists."""
        try:
            model = self._get_model(model_name)
            if model is None:
                return {"error": f"Model not found: {model_name}"}
            mapper = inspect(model)
            columns = []
            for col in mapper.columns:
                columns.append({"name": col.name, "type": str(col.type), "primary_key": bool(col.primary_key), "nullable": bool(col.nullable), "foreign_key": bool(col.foreign_keys), "expert_role": self._column_role(col.name)})
            relationships = [{"name": rel.key, "target": rel.mapper.class_.__name__, "uselist": bool(rel.uselist)} for rel in mapper.relationships]
            important = [c for c in columns if c["primary_key"] or c["foreign_key"] or c["expert_role"] != "general"]
            return {"model": model.__name__, "table": getattr(model, "__tablename__", None), "columns_count": len(columns), "relationships_count": len(relationships), "important_columns": important[:25], "relationships": relationships[:25], "expert_usage": self._model_usage_hint(model.__name__)}
        except Exception as exc:
            return {"error": str(exc)}

    def expert_data_path(self, domain: str) -> Dict[str, Any]:
        domain = str(domain or "").lower().strip()
        if domain not in BUSINESS_DOMAINS:
            return {"error": "unknown domain", "known_domains": sorted(BUSINESS_DOMAINS.keys())}
        data = BUSINESS_DOMAINS[domain]
        models = self._existing_models(data["models"])
        return {"domain": domain, "models": models, "workflow": self._workflow_for_domain(domain), "expert_focus": data["expert_focus"], "safe_filters": self._safe_filters_for_domain(domain), "common_data_mistakes": self._mistakes_for_domain(domain)}

    def suggest_index(self, table_name: str, query_pattern: str) -> List[Dict]:
        table_name = str(table_name or "").strip()
        query_pattern = str(query_pattern or "")
        suggestions = []
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
            return suggestions
        where_match = re.search(r"WHERE\s+(\w+)", query_pattern, re.IGNORECASE)
        if where_match:
            column = where_match.group(1)
            suggestions.append({"type": "single_column_index", "table": table_name, "columns": [column], "sql": f"CREATE INDEX idx_{table_name}_{column} ON {table_name}({column});", "reason": f"لتسريع WHERE {column}"})
        join_matches = re.findall(r"JOIN\s+\w+\s+ON\s+\w+\.(\w+)", query_pattern, re.IGNORECASE)
        for column in join_matches:
            suggestions.append({"type": "foreign_key_index", "table": table_name, "columns": [column], "sql": f"CREATE INDEX idx_{table_name}_{column}_fk ON {table_name}({column});", "reason": f"لتسريع JOIN على {column}"})
        return suggestions

    def detect_n_plus_one(self, code_context: str) -> Optional[Dict]:
        pattern = r"for\s+\w+\s+in\s+.*:\s*\n.*\.query\."
        if re.search(pattern, str(code_context or ""), re.MULTILINE):
            return {"detected": True, "issue": "N+1 Query Problem", "explanation": "يتم تنفيذ query منفصل لكل عنصر داخل loop. استخدم eager loading مثل joinedload أو subqueryload عند الحاجة.", "solution": "استخدم eager loading: joinedload() أو subqueryload()"}
        return None

    def analyze_schema(self, table_name: str) -> Dict[str, Any]:
        try:
            table_name = str(table_name or "").strip()
            inspector = inspect(db.engine)
            if table_name not in inspector.get_table_names():
                return {"error": f"Table not found: {table_name}"}
            columns = inspector.get_columns(table_name)
            fks = inspector.get_foreign_keys(table_name)
            indexes = inspector.get_indexes(table_name)
            analysis = {"table_name": table_name, "total_columns": len(columns), "total_fks": len(fks), "total_indexes": len(indexes), "issues": [], "recommendations": [], "expert_columns": [{"name": col.get("name"), "type": str(col.get("type")), "role": self._column_role(col.get("name"))} for col in columns]}
            pk = inspector.get_pk_constraint(table_name)
            if not pk.get("constrained_columns"):
                analysis["issues"].append({"type": "no_primary_key", "severity": "critical", "message": "الجدول لا يحتوي على Primary Key"})
            fk_columns = {col for fk in fks for col in fk.get("constrained_columns", [])}
            indexed_columns = {col for idx in indexes for col in idx.get("column_names", [])}
            unindexed_fks = fk_columns - indexed_columns
            if unindexed_fks:
                analysis["recommendations"].append({"type": "add_fk_indexes", "message": f"أضف indexes على FK: {', '.join(sorted(unindexed_fks))}"})
            if len(columns) > 30:
                analysis["recommendations"].append({"type": "review_table_width", "message": f"الجدول يحتوي على {len(columns)} عمود - راجع إن كان التقسيم مناسباً"})
            nullable_count = sum(1 for col in columns if col.get("nullable", True))
            if columns and nullable_count > len(columns) * 0.7:
                analysis["recommendations"].append({"type": "review_nullables", "message": f"{nullable_count} عمود nullable - راجع القيم الافتراضية والتحقق"})
            return analysis
        except Exception as exc:
            return {"error": str(exc)}

    def suggest_query_optimization(self, slow_query: str) -> Dict[str, Any]:
        slow_query = str(slow_query or "")
        optimizations = []
        upper = slow_query.upper()
        if "SELECT *" in upper:
            optimizations.append({"type": "specific_columns", "before": "SELECT *", "after": "SELECT column1, column2, ...", "benefit": "تقليل البيانات المنقولة"})
        if "LIMIT" not in upper and "SELECT" in upper:
            optimizations.append({"type": "add_limit", "before": slow_query, "after": slow_query + " LIMIT 100", "benefit": "تحديد عدد النتائج عند الاستعراض"})
        if "COUNT(*)" in upper and "WHERE" in upper:
            optimizations.append({"type": "use_exists", "before": "SELECT COUNT(*) FROM table WHERE condition", "after": "SELECT EXISTS(SELECT 1 FROM table WHERE condition LIMIT 1)", "benefit": "EXISTS قد يكون أسرع للتحقق من الوجود"})
        if len(re.findall(r"\bOR\b", slow_query, re.IGNORECASE)) > 2:
            optimizations.append({"type": "use_in", "before": "WHERE col = 1 OR col = 2 OR col = 3", "after": "WHERE col IN (1, 2, 3)", "benefit": "IN أوضح وقد يساعد المحسن حسب الحالة"})
        return {"original_query": slow_query, "optimizations": optimizations, "estimated_improvement": "requires EXPLAIN/ANALYZE"}

    def _get_model(self, model_name: str):
        try:
            import models
            return getattr(models, str(model_name or ""), None)
        except Exception:
            return None

    def _existing_models(self, model_names: List[str]) -> List[str]:
        return [name for name in model_names if self._get_model(name) is not None]

    def _column_role(self, name: str) -> str:
        name = str(name or "").lower()
        if name == "id" or name.endswith("_id"):
            return "identity_or_relation"
        if any(part in name for part in ["date", "created", "updated", "valid_from", "valid_until"]):
            return "time_filter"
        if any(part in name for part in ["amount", "total", "price", "cost", "balance", "rate", "tax", "discount"]):
            return "financial_value"
        if any(part in name for part in ["status", "state", "direction", "method", "type"]):
            return "workflow_state"
        if any(part in name for part in ["name", "phone", "email", "sku", "barcode", "reference"]):
            return "lookup_key"
        if any(part in name for part in ["notes", "description", "problem"]):
            return "human_context"
        return "general"

    def _model_usage_hint(self, model_name: str) -> List[str]:
        hints = []
        for domain, data in BUSINESS_DOMAINS.items():
            if model_name in data["models"]:
                hints.append(f"يستخدم في {domain}: {', '.join(data['expert_focus'][:2])}")
        return hints or ["استخدمه حسب علاقاته وحقوله الفعلية فقط."]

    def _safe_filters_for_domain(self, domain: str) -> List[str]:
        mapping = {
            "customers": ["name/phone", "is_active", "created_at", "balance only with policy note"],
            "suppliers": ["name/phone", "created_at", "balance with policy note"],
            "sales": ["customer_id", "sale_date/invoice_date", "status", "warehouse_id", "currency"],
            "payments": ["direction", "entity/customer/supplier", "payment_date", "method", "reference"],
            "inventory": ["product_id", "warehouse_id", "quantity", "min_qty", "sku/barcode"],
            "services": ["customer_id", "status", "vehicle_vrn", "mechanic_id", "created_at"],
            "finance": ["date", "account_code", "batch_id", "currency", "source", "status"],
        }
        return mapping.get(domain, [])

    def _workflow_for_domain(self, domain: str) -> List[str]:
        mapping = {
            "customers": ["ابحث عن الزبون", "راجع كشفه", "راجع آخر فاتورة/دفعة", "ثم أجب أو وجّه المستخدم"],
            "suppliers": ["ابحث عن المورد", "راجع التسويات/الدفعات", "راجع العملة والرصيد", "ثم أجب"],
            "sales": ["حدد الفترة والزبون", "اجمع الفواتير/المبيعات", "راجع الحالة والضريبة", "اربط الدفعات إن لزم"],
            "payments": ["حدد الاتجاه IN/OUT", "حدد الجهة", "راجع التاريخ والمرجع", "اربط الفاتورة إن وجدت"],
            "inventory": ["حدد المنتج", "حدد المستودع", "راجع الكمية والحد الأدنى", "راجع الحركات المؤثرة"],
            "services": ["حدد الزبون/المركبة", "راجع حالة الطلب", "راجع القطع والتكلفة", "راجع الدفعات قبل الإغلاق"],
            "finance": ["حدد الفترة", "حدد الحساب/المصدر", "راجع التوازن", "لا تستخدم نسب ضريبية غير مهيأة"],
        }
        return mapping.get(domain, [])

    def _mistakes_for_domain(self, domain: str) -> List[str]:
        mapping = {
            "customers": ["تكرار الزبون", "تفسير الرصيد عكس السياسة", "إهمال الهاتف في البحث"],
            "suppliers": ["خلط المورد مع الزبون", "تجاهل التسوية", "عكس الرصيد"],
            "sales": ["إهمال status", "احتساب VAT ثابت", "نسيان أثر المخزون"],
            "payments": ["عكس IN/OUT", "عدم ربط الجهة", "تكرار المرجع"],
            "inventory": ["تعديل كمية بلا حركة", "اختيار مستودع خاطئ", "تجاهل المنتجات تحت الحد"],
            "services": ["إغلاق الطلب قبل التحصيل", "عدم خصم القطع", "خلط التشخيص بوصف الزبون"],
            "finance": ["قيد غير متوازن", "حساب ثابت غير موجود", "استخدام تاريخ خاطئ للتقرير"],
        }
        return mapping.get(domain, [])

    def _load_common_patterns(self) -> Dict:
        return {"slow_patterns": [r"SELECT \* FROM", r"LIKE [\"']%.*%[\"']", r"OR.*OR.*OR"], "good_patterns": [r"SELECT \w+, \w+ FROM", r"WHERE.*LIMIT", r".*INDEX"]}


_db_expert = None


def get_database_expert() -> DatabaseExpert:
    global _db_expert
    if _db_expert is None:
        _db_expert = DatabaseExpert()
    return _db_expert


__all__ = ["DatabaseExpert", "get_database_expert"]
