"""Local AI knowledge base.

Indexes project structure for the local assistant and keeps a compact cache in
AI/data through ai_storage. The public API is preserved.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

KNOWLEDGE_CACHE_FILE = "ai_knowledge_cache.json"
TRAINING_LOG_FILE = "ai_training_log.json"


class SystemKnowledgeBase:
    def __init__(self):
        self.base_path = Path(".")
        self.knowledge = self._empty_knowledge()
        self.load_from_cache()

    def _empty_knowledge(self) -> Dict[str, Any]:
        return {"models": {}, "enums": {}, "routes": {}, "templates": {}, "forms": {}, "functions": {}, "javascript": {}, "css": {}, "static_files": {}, "relationships": {}, "business_rules": [], "common_errors": [], "learning_quality": {}, "last_indexed": None, "index_count": 0}

    def load_from_cache(self):
        cached = read_json(KNOWLEDGE_CACHE_FILE, None)
        if isinstance(cached, dict):
            self.knowledge.update(cached)

    def save_to_cache(self):
        try:
            self.knowledge["last_indexed"] = datetime.now().isoformat()
            self.knowledge["index_count"] = int(self.knowledge.get("index_count", 0) or 0) + 1
            write_json(KNOWLEDGE_CACHE_FILE, self.knowledge)
            sync_training_manifest(extra_files=[KNOWLEDGE_CACHE_FILE, TRAINING_LOG_FILE])
        except Exception:
            pass

    def index_all_files(self, force_reindex: bool = False):
        if not force_reindex and self.knowledge.get("last_indexed"):
            return self.knowledge
        previous_index_count = int(self.knowledge.get("index_count", 0) or 0)
        self.knowledge = self._empty_knowledge()
        self.knowledge["index_count"] = previous_index_count
        self.index_models()
        self.index_forms()
        self.index_routes()
        self.index_all_functions()
        self.index_templates()
        self.index_javascript()
        self.index_css()
        self.index_static_files()
        self.analyze_relationships()
        self.extract_business_rules()
        self.extract_currency_rules()
        self.calculate_learning_quality()
        self.save_to_cache()
        return self.knowledge

    def calculate_learning_quality(self):
        try:
            data_density_score = None
            tables_with_data = 0
            total_critical_tables = 0
            try:
                from models import Customer, Expense, Invoice, Payment, Product, ServiceRequest, Supplier, Warehouse
                critical_models = [Customer, Supplier, Product, ServiceRequest, Invoice, Payment, Expense, Warehouse]
                total_critical_tables = len(critical_models)
                for model in critical_models:
                    try:
                        if model.query.count() > 0:
                            tables_with_data += 1
                    except Exception:
                        pass
                data_density_score = (tables_with_data / total_critical_tables) * 100 if total_critical_tables else None
            except Exception:
                pass
            total_indexed = len(self.knowledge.get("models", {})) + len(self.knowledge.get("routes", {})) + len(self.knowledge.get("templates", {}))
            system_health_score = min(100, total_indexed / 2) if total_indexed else 0
            avg_confidence = None
            interactions = read_json("ai_interactions.json", [])
            if isinstance(interactions, list) and interactions:
                values = []
                for item in interactions[-20:]:
                    try:
                        c = float(item.get("confidence", 0) or 0)
                        values.append(c * 100 if c <= 1 else c)
                    except Exception:
                        continue
                if values:
                    avg_confidence = sum(values) / len(values)
            components = [system_health_score]
            if data_density_score is not None:
                components.append(data_density_score)
            if avg_confidence is not None:
                components.append(avg_confidence)
            quality = sum(components) / len(components) if components else 0
            self.knowledge["learning_quality"] = {"index": round(quality, 2), "avg_confidence": round(avg_confidence, 2) if avg_confidence is not None else None, "data_density": round(data_density_score, 2) if data_density_score is not None else None, "system_health": round(system_health_score, 2), "tables_with_data": tables_with_data, "total_critical_tables": total_critical_tables, "note": "No fabricated confidence defaults are used."}
        except Exception:
            self.knowledge["learning_quality"] = {"index": 0, "error": "failed_to_calculate"}

    def extract_currency_rules(self):
        self.knowledge["business_rules"].extend([
            {"rule": "العملة الأساسية في النظام هي ILS ما لم تُضبط خلاف ذلك في الإعدادات", "source": "system_settings/models", "impact": "high"},
            {"rule": "سعر الصرف يجب أن يُقرأ من ExchangeRate أو إعداد فعلي وليس من قيمة ثابتة", "source": "exchange_rates/settings", "impact": "high"},
            {"rule": "أي عملية متعددة العملات يجب أن تحفظ fx_rate_used ومصدر السعر عند توفره", "source": "payments/invoices", "impact": "medium"},
        ])

    def index_models(self):
        models_file = self.base_path / "models.py"
        if not models_file.exists():
            return
        try:
            content = models_file.read_text(encoding="utf-8")
            for match in re.finditer(r"^class\s+(\w+)\s*\(([^)]*)\):", content, re.MULTILINE):
                class_name = match.group(1)
                inheritance = match.group(2)
                class_body = self._class_body(content, match.end())
                if "Mixin" in class_name:
                    continue
                if "Enum" in inheritance or "enum" in inheritance:
                    values = re.findall(r"(\w+)\s*=\s*[\"']([^\"']+)[\"']", class_body[:2000])
                    self.knowledge["enums"][class_name] = {"type": "enum", "values": {k: v for k, v in values}, "file": "models.py"}
                elif "db.Model" in inheritance:
                    columns = re.findall(r"(\w+)\s*=\s*db\.Column\(", class_body)
                    relationships = re.findall(r"(\w+)\s*=\s*db\.relationship\([\"'](\w+)[\"']", class_body)
                    self.knowledge["models"][class_name] = {"type": "db_model", "columns": columns[:80], "relationships": [rel[1] for rel in relationships], "file": "models.py", "has_timestamp": "TimestampMixin" in inheritance, "has_audit": "AuditMixin" in inheritance}
        except Exception:
            pass

    def _class_body(self, content: str, start: int) -> str:
        next_class = re.search(r"\nclass\s+\w+", content[start:])
        return content[start:start + next_class.start()] if next_class else content[start:]

    def index_routes(self):
        routes_dir = self.base_path / "routes"
        if not routes_dir.exists():
            return
        try:
            for route_file in routes_dir.rglob("*.py"):
                if route_file.name.startswith("__"):
                    continue
                content = route_file.read_text(encoding="utf-8")
                routes = []
                for match in re.finditer(r"@(\w+_bp)\.route\([\'\"](.+?)[\'\"](?:,\s*methods=\[(.+?)\])?", content):
                    routes.append({"blueprint": match.group(1), "path": match.group(2), "methods": match.group(3) or "GET"})
                if routes:
                    self.knowledge["routes"][route_file.stem] = {"file": str(route_file), "routes": routes}
        except Exception:
            pass

    def index_forms(self):
        try:
            files = []
            forms_py = self.base_path / "forms.py"
            if forms_py.exists():
                files.append(forms_py)
            forms_dir = self.base_path / "forms"
            if forms_dir.exists():
                files.extend([p for p in forms_dir.rglob("*.py") if p.name != "__init__.py"])
            for form_file in files:
                content = form_file.read_text(encoding="utf-8")
                for match in re.finditer(r"^class\s+(\w+Form)\s*\(", content, re.MULTILINE):
                    body = self._class_body(content, match.end())
                    fields = re.findall(r"(\w+)\s*=\s*(?:StringField|IntegerField|SelectField|TextAreaField|BooleanField|PasswordField|FileField|DateField|DecimalField)", body)
                    self.knowledge["forms"][match.group(1)] = {"fields": fields[:50], "file": str(form_file)}
        except Exception:
            pass

    def index_all_functions(self):
        try:
            for folder in ("routes", "services", "AI/engine"):
                directory = self.base_path / folder
                if directory.exists():
                    for py_file in directory.rglob("*.py"):
                        if py_file.name.startswith("__"):
                            continue
                        content = py_file.read_text(encoding="utf-8")
                        self.knowledge["functions"][str(py_file)] = {"functions": re.findall(r"^def\s+(\w+)\s*\(", content, re.MULTILINE)[:120], "classes": re.findall(r"^class\s+(\w+)\s*\(", content, re.MULTILINE)[:50]}
        except Exception:
            pass

    def index_templates(self):
        templates_dir = self.base_path / "templates"
        if not templates_dir.exists():
            return
        try:
            for template_file in templates_dir.rglob("*.html"):
                module = str(template_file.parent.relative_to(templates_dir)) if template_file.parent != templates_dir else "root"
                self.knowledge["templates"].setdefault(module, []).append(template_file.name)
        except Exception:
            pass

    def index_javascript(self):
        js_dir = self.base_path / "static" / "js"
        if not js_dir.exists():
            return
        try:
            for js_file in js_dir.rglob("*.js"):
                content = js_file.read_text(encoding="utf-8")
                functions = re.findall(r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()", content)
                self.knowledge["javascript"][str(js_file.relative_to(self.base_path))] = {"functions": [a or b for a, b in functions if a or b][:80], "events": sorted(set(re.findall(r"addEventListener\([\"'](\w+)[\"']", content)))[:30]}
        except Exception:
            pass

    def index_css(self):
        css_dir = self.base_path / "static" / "css"
        if not css_dir.exists():
            return
        try:
            for css_file in css_dir.rglob("*.css"):
                content = css_file.read_text(encoding="utf-8")
                self.knowledge["css"][str(css_file.relative_to(self.base_path))] = {"classes": sorted(set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[{,]", content)))[:150], "ids": sorted(set(re.findall(r"#([a-zA-Z][\w-]*)\s*[{,]", content)))[:80]}
        except Exception:
            pass

    def index_static_files(self):
        static_dir = self.base_path / "static"
        if not static_dir.exists():
            return
        images, fonts, data_files, other = [], [], [], []
        try:
            for path in static_dir.rglob("*"):
                if not path.is_file() or path.name.startswith("."):
                    continue
                rel, ext = str(path.relative_to(static_dir)), path.suffix.lower()
                if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}:
                    images.append(rel)
                elif ext in {".ttf", ".woff", ".woff2", ".eot"}:
                    fonts.append(rel)
                elif ext in {".json", ".xml", ".csv"}:
                    data_files.append(rel)
                elif ext not in {".js", ".css"}:
                    other.append(rel)
            self.knowledge["static_files"] = {"images": images[:80], "fonts": fonts[:80], "data": data_files[:80], "other": other[:80], "images_count": len(images), "fonts_count": len(fonts), "data_count": len(data_files)}
        except Exception:
            pass

    def analyze_relationships(self):
        self.knowledge["relationships"] = {}
        for model_name, data in self.knowledge.get("models", {}).items():
            for rel in data.get("relationships", []) or []:
                self.knowledge["relationships"][f"{model_name} → {rel}"] = {"from": model_name, "to": rel, "type": "declared_relationship"}

    def extract_business_rules(self):
        self.knowledge["business_rules"] = [
            {"rule": "AI actions must pass ai_permissions.can_ai_execute_action before execution", "source": "AI/engine/ai_permissions.py", "impact": "critical"},
            {"rule": "Generated AI runtime JSON should go through ai_storage", "source": "AI/engine/ai_storage.py", "impact": "high"},
            {"rule": "GL batches should be balanced: total debit equals total credit", "source": "accounting rules", "impact": "critical"},
            {"rule": "Database-aware answers should prefer live models/schema over hard-coded assumptions", "source": "AI/data schema", "impact": "high"},
        ]

    def get_accounting_knowledge(self):
        return {"principles": {"double_entry": "كل قيد محاسبي يجب أن يكون متوازنًا", "balance_sheet": "الأصول = الخصوم + حقوق الملكية", "income_statement": "صافي الربح = الإيرادات - المصروفات"}, "notes": ["الأرقام والحسابات النهائية يجب أن تُقرأ من قاعدة النظام الفعلية."]}


class ErrorAnalyzer:
    def analyze_traceback(self, traceback_text: str) -> Dict[str, Any]:
        text = str(traceback_text or "")
        analysis = {"error_type": "Unknown", "file": "غير معروف", "line": "غير معروف", "cause": "خطأ غير مصنف", "solution": "راجع سجل الخطأ والكود المحيط", "severity": "medium"}
        patterns = [("ImportError", "مشكلة في الاستيراد أو مكتبة غير مثبتة", "تحقق من requirements.txt والبيئة الافتراضية"), ("ModuleNotFoundError", "مكتبة أو ملف غير موجود", "ثبت المكتبة أو صحح مسار الاستيراد"), ("AttributeError", "خاصية أو دالة غير موجودة على الكائن", "تحقق من نوع الكائن واسم الخاصية"), ("KeyError", "مفتاح غير موجود في dict", "استخدم get() أو تحقق من وجود المفتاح"), ("TypeError", "نوع بيانات غير مناسب للعملية", "تحقق من التحويلات وأنواع المتغيرات"), ("ValueError", "قيمة غير صالحة", "أضف validation أو try/except"), ("IntegrityError", "مخالفة قيد في قاعدة البيانات", "تحقق من التكرار والمفاتيح الأجنبية والحقول المطلوبة"), ("OperationalError", "مشكلة اتصال أو تشغيل قاعدة البيانات", "تحقق من DATABASE_URL وحالة قاعدة البيانات")]
        for error_type, cause, solution in patterns:
            if error_type in text:
                analysis.update(error_type=error_type, cause=cause, solution=solution)
                break
        m = re.search(r'File "([^"]+)", line (\d+)', text)
        if m:
            analysis["file"], analysis["line"] = m.group(1), int(m.group(2))
        if analysis["error_type"] in {"IntegrityError", "OperationalError"}:
            analysis["severity"] = "high"
        return analysis

    @staticmethod
    def format_error_response(analysis: Dict[str, Any]) -> str:
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(analysis.get("severity"), "⚠️")
        return f"{emoji} **خطأ: {analysis.get('error_type', 'Unknown')}**\n\n📁 الملف: `{analysis.get('file', 'غير معروف')}`\n📍 السطر: `{analysis.get('line', 'غير معروف')}`\n\n💡 السبب:\n{analysis.get('cause', '')}\n\n🔧 الحل:\n{analysis.get('solution', '')}".strip()


_knowledge_base = None
_error_analyzer = ErrorAnalyzer()


def get_knowledge_base():
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = SystemKnowledgeBase()
        _knowledge_base.index_all_files()
    return _knowledge_base


def get_local_faq_responses():
    return {"من أنت": "أنا المساعد الذكي داخل نظام أزاد. أساعدك في التنقل، فهم البيانات، المحاسبة، التقارير، والأخطاء البرمجية داخل النظام.", "ما قدراتك": "أستطيع قراءة خريطة النظام، فهم الجداول والنماذج، تحليل الأخطاء، شرح القيود المحاسبية، وتوجيهك للصفحات المناسبة حسب الصلاحيات.", "كيف أضيف زبون": "افتح صفحة الزبائن ثم إضافة زبون جديد. أدخل الاسم والهاتف والبيانات المطلوبة، ثم احفظ. تحقق من الرصيد الافتتاحي قبل الحفظ."}


def get_local_quick_rules():
    return {"count_customers": {"patterns": ["كم عدد الزبائن", "عدد الزبائن", "how many customers"], "model": "Customer", "response_template": "✅ عدد الزبائن: {count} زبون"}, "count_services": {"patterns": ["كم صيانة", "عدد الصيانات", "طلبات الصيانة"], "model": "ServiceRequest", "response_template": "🔧 عدد طلبات الصيانة: {count} طلب"}, "count_expenses": {"patterns": ["كم نفقة", "عدد النفقات", "المصاريف"], "model": "Expense", "response_template": "💸 عدد النفقات: {count} نفقة"}, "count_products": {"patterns": ["كم منتج", "عدد القطع", "المنتجات"], "model": "Product", "response_template": "📦 عدد المنتجات: {count} منتج"}, "count_suppliers": {"patterns": ["كم مورد", "عدد الموردين"], "model": "Supplier", "response_template": "🏭 عدد الموردين: {count} مورد"}}


def analyze_error(traceback_text):
    return _error_analyzer.analyze_traceback(traceback_text)


def format_error_response(analysis):
    return _error_analyzer.format_error_response(analysis)


__all__ = ["SystemKnowledgeBase", "get_knowledge_base", "get_local_faq_responses", "get_local_quick_rules", "analyze_error", "format_error_response"]
