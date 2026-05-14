"""AI data awareness.

Builds and loads a schema map from SQLAlchemy models. This replaces fragile
hard-coded model lists with registry-based discovery while keeping public
function names stable for existing AI modules.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import class_mapper

from extensions import db

DATA_SCHEMA_FILE = "AI/data/ai_data_schema.json"
LEARNING_LOG_FILE = "AI/data/ai_learning_log.json"
SCHEMA_MAX_AGE_DAYS = 7

MODEL_SYNONYMS = {
    "عميل": ["customer", "client"],
    "عملاء": ["customer", "client"],
    "مورد": ["supplier", "vendor", "partner"],
    "منتج": ["product", "part"],
    "صيانة": ["service", "servicerequest", "repair"],
    "فاتورة": ["invoice", "sale"],
    "دفعة": ["payment"],
    "دفع": ["payment"],
    "مخزن": ["warehouse", "stock", "inventory"],
    "مستخدم": ["user"],
    "دور": ["role"],
    "صلاحية": ["permission"],
    "نفقة": ["expense"],
    "مصروف": ["expense"],
    "شيك": ["check"],
    "ملاحظة": ["note"],
    "شحنة": ["shipment"],
    "عملة": ["currency", "exchange"],
    "حساب": ["account", "ledger", "gl"],
}


def _ensure_data_dir() -> None:
    os.makedirs("AI/data", exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data: Any) -> None:
    _ensure_data_dir()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def discover_all_models() -> List[type]:
    """Discover SQLAlchemy model classes from the app registry."""
    models: List[type] = []
    try:
        # Importing models registers mapped classes in db.Model.registry.
        import models as _models  # noqa: F401

        for mapper in db.Model.registry.mappers:
            cls = mapper.class_
            if getattr(cls, "__tablename__", None):
                models.append(cls)
    except Exception:
        return []
    return sorted(set(models), key=lambda model: model.__name__)


def analyze_model_structure(model: type) -> Dict[str, Any]:
    """Analyze one SQLAlchemy model."""
    try:
        mapper = class_mapper(model)
        columns = [
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": column.nullable,
                "primary_key": column.primary_key,
                "foreign_key": bool(column.foreign_keys),
            }
            for column in mapper.columns
        ]
        relationships = [
            {
                "name": rel.key,
                "target": rel.mapper.class_.__name__,
                "uselist": rel.uselist,
                "type": "one-to-many" if rel.uselist else "many-to-one",
            }
            for rel in mapper.relationships
        ]
        return {
            "table_name": mapper.local_table.name,
            "class_name": model.__name__,
            "columns_count": len(columns),
            "columns": columns,
            "relationships_count": len(relationships),
            "relationships": relationships,
        }
    except Exception as exc:
        return {"table_name": "unknown", "class_name": getattr(model, "__name__", "unknown"), "error": str(exc)}


def build_functional_mapping() -> Dict[str, Dict[str, Any]]:
    return {
        "الصيانة": {"models": ["ServiceRequest", "ServicePart", "ServiceTask"], "primary_table": "service_requests", "purpose": "إدارة طلبات الصيانة وقطع الغيار والمهام", "keywords": ["صيانة", "إصلاح", "عطل", "تشخيص", "workshop", "service"]},
        "النفقات": {"models": ["Expense", "ExpenseType"], "primary_table": "expenses", "purpose": "تتبع المصاريف والنفقات", "keywords": ["نفقة", "مصروف", "مصاريف", "expense"]},
        "المحاسبة": {"models": ["Account", "ExchangeTransaction"], "primary_table": "accounts", "purpose": "إدارة دفتر الأستاذ والحسابات", "keywords": ["دفتر", "حساب", "محاسبة", "ledger", "accounting"]},
        "المتجر": {"models": ["Product", "OnlineCart", "PreOrder", "ProductRating"], "primary_table": "products", "purpose": "المبيعات والمتجر الإلكتروني", "keywords": ["متجر", "منتج", "طلب", "سلة", "shop", "store", "product"]},
        "المبيعات": {"models": ["Invoice", "Payment"], "primary_table": "invoices", "purpose": "إدارة الفواتير والمدفوعات", "keywords": ["فاتورة", "دفع", "مبيعات", "invoice", "payment", "sales"]},
        "العملاء": {"models": ["Customer"], "primary_table": "customers", "purpose": "إدارة بيانات العملاء", "keywords": ["عميل", "زبون", "customer", "client"]},
        "الموردين": {"models": ["Supplier", "SupplierSettlement"], "primary_table": "suppliers", "purpose": "إدارة الموردين والمشتريات", "keywords": ["مورد", "شراء", "supplier", "vendor"]},
        "المخازن": {"models": ["Warehouse", "StockLevel", "Shipment"], "primary_table": "warehouses", "purpose": "إدارة المخزون والشحنات", "keywords": ["مخزن", "مخزون", "شحنة", "warehouse", "stock", "inventory"]},
        "الشركاء": {"models": ["Partner", "PartnerSettlement"], "primary_table": "partners", "purpose": "إدارة الشراكات والتسويات", "keywords": ["شريك", "شراكة", "تسوية", "partner", "settlement"]},
        "الضرائب والعملات": {"models": ["ExchangeTransaction", "Currency"], "primary_table": "exchange_transactions", "purpose": "إدارة أسعار الصرف والضرائب", "keywords": ["ضريبة", "صرف", "عملة", "دولار", "tax", "exchange", "currency"]},
        "المستخدمين والأمان": {"models": ["User", "Role", "Permission", "AuditLog"], "primary_table": "users", "purpose": "إدارة المستخدمين والصلاحيات", "keywords": ["مستخدم", "صلاحية", "دور", "user", "role", "permission", "audit"]},
        "الملاحظات": {"models": ["Note"], "primary_table": "notes", "purpose": "إدارة الملاحظات والمذكرات", "keywords": ["ملاحظة", "مذكرة", "note"]},
    }


def build_language_mapping() -> Dict[str, List[str]]:
    return {
        "مبيعات": ["sales", "invoice", "payment"],
        "دفتر": ["ledger", "account"],
        "نفقات": ["expense", "expenses"],
        "ضرائب": ["tax", "vat"],
        "سعر الدولار": ["exchange", "usd", "ils"],
        "عملاء": ["customer", "client"],
        "موردين": ["supplier", "vendor"],
        "متجر": ["shop", "store", "product"],
        "صيانة": ["service", "workshop", "repair"],
        "مخازن": ["warehouse", "inventory", "stock"],
        "شركاء": ["partner", "partnership"],
    }


def build_data_schema() -> Dict[str, Any]:
    models = discover_all_models()
    schema: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "models_count": len(models),
        "models": {},
        "functional_mapping": build_functional_mapping(),
        "language_mapping": build_language_mapping(),
        "statistics": {"total_tables": 0, "total_columns": 0, "total_relationships": 0},
    }

    for model in models:
        analysis = analyze_model_structure(model)
        if "error" not in analysis:
            schema["models"][model.__name__] = analysis
            schema["statistics"]["total_columns"] += analysis.get("columns_count", 0)
            schema["statistics"]["total_relationships"] += analysis.get("relationships_count", 0)

    schema["statistics"]["total_tables"] = len(schema["models"])
    save_data_schema(schema)
    log_learning_event("schema_built", {"models_discovered": len(models), "models_saved": len(schema["models"])})
    return schema


def save_data_schema(schema: Dict[str, Any]) -> None:
    try:
        _write_json(DATA_SCHEMA_FILE, schema)
    except Exception:
        pass


def load_data_schema() -> Optional[Dict[str, Any]]:
    data = _read_json(DATA_SCHEMA_FILE, None)
    return data if isinstance(data, dict) else None


def log_learning_event(event_type: str, details: Any) -> None:
    try:
        logs = _read_json(LEARNING_LOG_FILE, [])
        if not isinstance(logs, list):
            logs = []
        logs.append({"timestamp": datetime.now().isoformat(), "event": event_type, "details": details})
        _write_json(LEARNING_LOG_FILE, logs[-100:])
    except Exception:
        pass


def _search_terms(keyword: str) -> List[str]:
    text = str(keyword or "").lower()
    terms = {text}
    for ar_word, synonyms in MODEL_SYNONYMS.items():
        if ar_word in text:
            terms.update(synonyms)
        if any(syn in text for syn in synonyms):
            terms.add(ar_word)
            terms.update(synonyms)
    return [term for term in terms if term]


def find_model_by_keyword(keyword: str) -> Optional[Dict[str, Any]]:
    schema = load_data_schema()
    if not schema or not schema.get("models"):
        return None

    terms = _search_terms(keyword)
    best_match = None
    highest_score = 0

    for model_name, model_data in schema.get("models", {}).items():
        score = 0
        table = str(model_data.get("table_name") or "").lower()
        model_lower = model_name.lower()
        for term in terms:
            term_lower = term.lower()
            if term_lower in model_lower:
                score += 15
            if term_lower in table:
                score += 10
            for col in model_data.get("columns", []):
                if term_lower in str(col.get("name") or "").lower():
                    score += 2
        if score > highest_score:
            highest_score = score
            best_match = {
                "name": model_name,
                "table_name": model_data.get("table_name"),
                "description": f"نموذج {model_name} - يحتوي على {len(model_data.get('columns', []))} حقل",
                "columns": model_data.get("columns", []),
                "relationships": [rel.get("name", "") for rel in model_data.get("relationships", [])],
                "score": score,
            }

    for module_name, module_data in schema.get("functional_mapping", {}).items():
        keywords = [str(k).lower() for k in module_data.get("keywords", [])]
        if any(term.lower() in keywords or any(term.lower() in kw for kw in keywords) for term in terms):
            if not best_match or highest_score < 5:
                best_match = {"module": module_name, "models": module_data.get("models", []), "purpose": module_data.get("purpose", ""), "description": f"وحدة {module_name}"}
                highest_score = 5

    return {"model": best_match, "keyword": keyword} if best_match else None


def auto_build_if_needed() -> Optional[Dict[str, Any]]:
    if not os.path.exists(DATA_SCHEMA_FILE):
        return build_data_schema()
    try:
        age_days = (datetime.now().timestamp() - os.path.getmtime(DATA_SCHEMA_FILE)) / (3600 * 24)
        if age_days > SCHEMA_MAX_AGE_DAYS:
            return build_data_schema()
    except Exception:
        pass
    return load_data_schema()


__all__ = [
    "DATA_SCHEMA_FILE",
    "LEARNING_LOG_FILE",
    "discover_all_models",
    "analyze_model_structure",
    "build_functional_mapping",
    "build_language_mapping",
    "build_data_schema",
    "save_data_schema",
    "load_data_schema",
    "log_learning_event",
    "find_model_by_keyword",
    "auto_build_if_needed",
]
