"""AI data awareness.

Builds and loads a schema map from SQLAlchemy models. Functional mappings are
filtered against actually discovered models so the assistant does not learn
phantom table/model names.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import class_mapper

from extensions import db
from AI.engine.ai_storage import append_json_list, read_json, sync_training_manifest, write_json

DATA_SCHEMA_FILE = "ai_data_schema.json"
LEARNING_LOG_FILE = "ai_learning_log.json"
SCHEMA_MAX_AGE_DAYS = 7

MODEL_SYNONYMS = {
    "زبون": ["customer", "client"], "زبائن": ["customer", "client"], "مورد": ["supplier", "vendor", "partner"], "منتج": ["product", "part"], "صيانة": ["service", "servicerequest", "repair"], "فاتورة": ["invoice", "sale"], "دفعة": ["payment"], "دفع": ["payment"], "مخزن": ["warehouse", "stock", "inventory"], "مستخدم": ["user"], "دور": ["role"], "صلاحية": ["permission"], "نفقة": ["expense"], "مصروف": ["expense"], "شيك": ["check"], "ملاحظة": ["note"], "شحنة": ["shipment"], "عملة": ["currency", "exchange", "exchangerate"], "حساب": ["account", "ledger", "gl"],
}


def discover_all_models() -> List[type]:
    models: List[type] = []
    try:
        import models as _models  # noqa: F401
        for mapper in db.Model.registry.mappers:
            cls = mapper.class_
            if getattr(cls, "__tablename__", None):
                models.append(cls)
    except Exception:
        return []
    return sorted(set(models), key=lambda model: model.__name__)


def analyze_model_structure(model: type) -> Dict[str, Any]:
    try:
        mapper = class_mapper(model)
        columns = [{"name": column.name, "type": str(column.type), "nullable": column.nullable, "primary_key": column.primary_key, "foreign_key": bool(column.foreign_keys)} for column in mapper.columns]
        relationships = [{"name": rel.key, "target": rel.mapper.class_.__name__, "uselist": rel.uselist, "type": "one-to-many" if rel.uselist else "many-to-one"} for rel in mapper.relationships]
        return {"table_name": mapper.local_table.name, "class_name": model.__name__, "columns_count": len(columns), "columns": columns, "relationships_count": len(relationships), "relationships": relationships}
    except Exception as exc:
        return {"table_name": "unknown", "class_name": getattr(model, "__name__", "unknown"), "error": str(exc)}


def _existing_model_names() -> set[str]:
    try:
        return {model.__name__ for model in discover_all_models()}
    except Exception:
        return set()


def _filter_models(candidates: List[str], existing: set[str]) -> List[str]:
    return [name for name in candidates if name in existing]


def _primary_table_for(model_name: str, models_by_name: Dict[str, type]) -> Optional[str]:
    model = models_by_name.get(model_name)
    return getattr(model, "__tablename__", None) if model else None


def build_functional_mapping() -> Dict[str, Dict[str, Any]]:
    models = discover_all_models()
    existing = {m.__name__ for m in models}
    by_name = {m.__name__: m for m in models}
    raw = {
        "الصيانة": {"models": ["ServiceRequest", "ServicePart", "ServiceTask"], "purpose": "إدارة طلبات الصيانة وقطع الغيار والمهام", "keywords": ["صيانة", "إصلاح", "عطل", "تشخيص", "workshop", "service"]},
        "النفقات": {"models": ["Expense", "ExpenseType"], "purpose": "تتبع المصاريف والنفقات", "keywords": ["نفقة", "مصروف", "مصاريف", "expense"]},
        "المحاسبة": {"models": ["Account", "GLBatch", "GLEntry"], "purpose": "إدارة دفتر الأستاذ والحسابات", "keywords": ["دفتر", "حساب", "محاسبة", "ledger", "accounting", "gl"]},
        "المتجر": {"models": ["Product", "OnlineCart", "PreOrder", "ProductRating"], "purpose": "المبيعات والمتجر الإلكتروني", "keywords": ["متجر", "منتج", "طلب", "سلة", "shop", "store", "product"]},
        "المبيعات": {"models": ["Sale", "SaleLine", "Invoice", "Payment"], "purpose": "إدارة المبيعات والفواتير والمدفوعات", "keywords": ["فاتورة", "دفع", "مبيعات", "invoice", "payment", "sales"]},
        "الزبائن": {"models": ["Customer"], "purpose": "إدارة بيانات الزبائن", "keywords": ["زبون", "زبون", "customer", "client"]},
        "الموردين": {"models": ["Supplier", "SupplierSettlement"], "purpose": "إدارة الموردين والمشتريات", "keywords": ["مورد", "شراء", "supplier", "vendor"]},
        "المخازن": {"models": ["Warehouse", "StockLevel", "Shipment"], "purpose": "إدارة المخزون والشحنات", "keywords": ["مخزن", "مخزون", "شحنة", "warehouse", "stock", "inventory"]},
        "الشركاء": {"models": ["Partner", "PartnerSettlement"], "purpose": "إدارة الشراكات والتسويات", "keywords": ["شريك", "شراكة", "تسوية", "partner", "settlement"]},
        "الضرائب والعملات": {"models": ["ExchangeRate", "ExchangeTransaction", "Currency", "CurrencyRate", "SystemSettings"], "purpose": "إدارة أسعار الصرف والضرائب حسب الموديلات والإعدادات الفعلية", "keywords": ["ضريبة", "صرف", "عملة", "دولار", "tax", "exchange", "currency"]},
        "المستخدمين والأمان": {"models": ["User", "Role", "Permission", "AuditLog"], "purpose": "إدارة المستخدمين والصلاحيات", "keywords": ["مستخدم", "صلاحية", "دور", "user", "role", "permission", "audit"]},
        "الملاحظات": {"models": ["Note"], "purpose": "إدارة الملاحظات والمذكرات", "keywords": ["ملاحظة", "مذكرة", "note"]},
    }
    mapping: Dict[str, Dict[str, Any]] = {}
    for module, data in raw.items():
        found = _filter_models(data["models"], existing)
        if not found:
            continue
        mapping[module] = {"models": found, "primary_table": _primary_table_for(found[0], by_name), "purpose": data["purpose"], "keywords": data["keywords"]}
    return mapping


def build_language_mapping() -> Dict[str, List[str]]:
    return {"مبيعات": ["sales", "sale", "invoice", "payment"], "دفتر": ["ledger", "account", "gl"], "نفقات": ["expense", "expenses"], "ضرائب": ["tax", "vat", "systemsettings"], "سعر الدولار": ["exchange", "exchangerate", "usd", "ils"], "زبائن": ["customer", "client"], "موردين": ["supplier", "vendor"], "متجر": ["shop", "store", "product"], "صيانة": ["service", "workshop", "repair"], "مخازن": ["warehouse", "inventory", "stock"], "شركاء": ["partner", "partnership"]}


def build_data_schema() -> Dict[str, Any]:
    models = discover_all_models()
    schema: Dict[str, Any] = {"generated_at": datetime.now().isoformat(), "models_count": len(models), "models": {}, "functional_mapping": {}, "language_mapping": build_language_mapping(), "statistics": {"total_tables": 0, "total_columns": 0, "total_relationships": 0}}
    for model in models:
        analysis = analyze_model_structure(model)
        if "error" not in analysis:
            schema["models"][model.__name__] = analysis
            schema["statistics"]["total_columns"] += analysis.get("columns_count", 0)
            schema["statistics"]["total_relationships"] += analysis.get("relationships_count", 0)
    schema["functional_mapping"] = build_functional_mapping()
    schema["statistics"]["total_tables"] = len(schema["models"])
    save_data_schema(schema)
    log_learning_event("schema_built", {"models_discovered": len(models), "models_saved": len(schema["models"])})
    sync_training_manifest()
    return schema


def save_data_schema(schema: Dict[str, Any]) -> None:
    try:
        write_json(DATA_SCHEMA_FILE, schema)
    except Exception:
        pass


def load_data_schema() -> Optional[Dict[str, Any]]:
    data = read_json(DATA_SCHEMA_FILE, None)
    return data if isinstance(data, dict) else None


def log_learning_event(event_type: str, details: Any) -> None:
    try:
        append_json_list(LEARNING_LOG_FILE, {"timestamp": datetime.now().isoformat(), "event": event_type, "details": details}, max_items=100)
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
            best_match = {"name": model_name, "table_name": model_data.get("table_name"), "description": f"نموذج {model_name} - يحتوي على {len(model_data.get('columns', []))} حقل", "columns": model_data.get("columns", []), "relationships": [rel.get("name", "") for rel in model_data.get("relationships", [])], "score": score}
    for module_name, module_data in schema.get("functional_mapping", {}).items():
        keywords = [str(k).lower() for k in module_data.get("keywords", [])]
        if any(term.lower() in keywords or any(term.lower() in kw for kw in keywords) for term in terms):
            if not best_match or highest_score < 5:
                best_match = {"module": module_name, "models": module_data.get("models", []), "purpose": module_data.get("purpose", ""), "description": f"وحدة {module_name}"}
                highest_score = 5
    return {"model": best_match, "keyword": keyword} if best_match else None


def auto_build_if_needed() -> Optional[Dict[str, Any]]:
    path = os.path.join("AI/data", DATA_SCHEMA_FILE)
    if not os.path.exists(path):
        return build_data_schema()
    try:
        age_days = (datetime.now().timestamp() - os.path.getmtime(path)) / (3600 * 24)
        if age_days > SCHEMA_MAX_AGE_DAYS:
            return build_data_schema()
    except Exception:
        pass
    return load_data_schema()


__all__ = ["DATA_SCHEMA_FILE", "LEARNING_LOG_FILE", "discover_all_models", "analyze_model_structure", "build_functional_mapping", "build_language_mapping", "build_data_schema", "save_data_schema", "load_data_schema", "log_learning_event", "find_model_by_keyword", "auto_build_if_needed"]
