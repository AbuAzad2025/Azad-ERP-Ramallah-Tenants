"""System deep trainer.

Builds compact deep-memory knowledge about the current application. The trainer
is intentionally dynamic: it scans the actual Flask app, SQLAlchemy registry,
routes, forms, templates, and selected Python modules instead of relying on long
hard-coded module lists. It never stores secret setting values.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


class SystemDeepTrainer:
    """Train the local deep memory on the current system structure."""

    ROUTE_FILES = ("routes", "services", "utils", "AI/engine")
    FORM_LOCATIONS = (Path("forms.py"), Path("forms"))
    TEMPLATE_DIR = Path("templates")
    STATIC_DIR = Path("static")
    MAX_EXAMPLES = 20

    def train_system_comprehensive(self) -> Dict[str, Any]:
        sections: List[Tuple[str, Any]] = [
            ("database", self._train_database_complete),
            ("models", self._train_models_relationships),
            ("routes", self._train_routes),
            ("forms", self._train_forms),
            ("templates", self._train_templates),
            ("python_modules", self._train_python_modules),
            ("business_workflows", self._train_business_workflows),
            ("accounting", self._train_accounting_knowledge),
            ("settings", self._train_settings_metadata),
            ("security_surfaces", self._train_security_surfaces),
            ("static_assets", self._train_static_assets),
            ("ai_modules", self._train_ai_modules),
        ]

        total_items = 0
        section_results: Dict[str, int] = {}
        errors: Dict[str, str] = {}

        print("[SYSTEM DEEP TRAINING - START]")
        for index, (name, func) in enumerate(sections, 1):
            print(f"\n[{index}/{len(sections)}] {name}")
            try:
                learned = int(func() or 0)
                section_results[name] = learned
                total_items += learned
                print(f"  Learned: {learned} items")
            except Exception as exc:
                errors[name] = str(exc)
                section_results[name] = 0
                print(f"  Error: {exc}")

        print("[SYSTEM DEEP TRAINING - COMPLETE]")
        print(f"Total items learned: {total_items}")
        return {"success": True, "items_learned": total_items, "modules": len(sections), "sections": section_results, "errors": errors}

    # ──────────────────────────────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────────────────────────────

    def _memory(self):
        from AI.engine.ai_deep_memory import get_deep_memory

        return get_deep_memory()

    def _has_app_context(self) -> bool:
        try:
            from flask import has_app_context

            return bool(has_app_context())
        except Exception:
            return False

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _public_functions(self, content: str) -> List[str]:
        return [name for name in re.findall(r"^def\s+(\w+)\s*\(", content, re.MULTILINE) if not name.startswith("_")]

    def _classes(self, content: str) -> List[str]:
        return re.findall(r"^class\s+(\w+)\s*(?:\(|:)", content, re.MULTILINE)

    def _remember_concept(self, title: str, definition: str, examples: Iterable[Any] = (), related: Iterable[str] = ()) -> int:
        try:
            self._memory().remember_concept(title, definition, examples=list(examples)[: self.MAX_EXAMPLES], related=list(related)[: self.MAX_EXAMPLES])
            return 1
        except Exception:
            return 0

    def _remember_fact(self, category: str, key: str, value: Any, importance: int = 6) -> int:
        try:
            self._memory().remember_fact(category, key, value, importance=importance)
            return 1
        except Exception:
            return 0

    def _remember_procedure(self, name: str, steps: Iterable[str], context: Dict[str, Any] | None = None) -> int:
        try:
            self._memory().remember_procedure(name, list(steps)[:100], context=context or {})
            return 1
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────
    # Training sections
    # ──────────────────────────────────────────────────────────────────

    def _train_database_complete(self) -> int:
        if not self._has_app_context():
            print("  Warning: No app context, skipping database scan")
            return 0
        items = 0
        try:
            from extensions import db
            from sqlalchemy import inspect

            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            for table in tables:
                columns = inspector.get_columns(table)
                fks = inspector.get_foreign_keys(table)
                pk = inspector.get_pk_constraint(table)
                column_names = [col["name"] for col in columns]
                items += self._remember_concept(
                    f"جدول: {table}",
                    f"جدول في قاعدة البيانات يحتوي على {len(columns)} عمود و {len(fks)} علاقة خارجية",
                    examples=column_names,
                    related=["database", "schema"],
                )
                items += self._remember_fact(
                    "db_table",
                    table,
                    {"columns": column_names, "column_count": len(columns), "has_pk": bool(pk and pk.get("constrained_columns")), "fk_count": len(fks)},
                    importance=7,
                )
                for fk in fks:
                    items += self._remember_fact(
                        "db_relationship",
                        f"{table} -> {fk.get('referred_table')}",
                        {"from_table": table, "to_table": fk.get("referred_table"), "columns": fk.get("constrained_columns", []), "referred_columns": fk.get("referred_columns", [])},
                        importance=8,
                    )
            print(f"  Tables analyzed: {len(tables)}")
        except Exception as exc:
            print(f"  Error: {exc}")
        return items

    def _train_models_relationships(self) -> int:
        items = 0
        try:
            import models as _models  # noqa: F401
            from extensions import db

            mappers = list(db.Model.registry.mappers)
            for mapper in mappers:
                model_class = mapper.class_
                model_name = model_class.__name__
                columns = [col.name for col in mapper.columns]
                relationships = {rel.key: {"target": rel.mapper.class_.__name__, "uselist": rel.uselist} for rel in mapper.relationships}
                items += self._remember_concept(f"Model: {model_name}", f"نموذج SQLAlchemy مرتبط بجدول {getattr(model_class, '__tablename__', 'unknown')}", examples=columns, related=["models", "database"])
                if relationships:
                    items += self._remember_fact("model_relationships", model_name, relationships, importance=8)
            print(f"  Models analyzed: {len(mappers)}")
        except Exception as exc:
            print(f"  Error: {exc}")
        return items

    def _train_routes(self) -> int:
        if not self._has_app_context():
            print("  Warning: No app context, skipping routes scan")
            return 0
        items = 0
        try:
            from flask import current_app

            routes_by_module: Dict[str, List[Dict[str, Any]]] = {}
            for rule in current_app.url_map.iter_rules():
                if rule.endpoint == "static":
                    continue
                module = rule.endpoint.split(".")[0] if "." in rule.endpoint else "main"
                methods = sorted(list(rule.methods - {"HEAD", "OPTIONS"}))
                route = {"path": str(rule.rule), "endpoint": rule.endpoint, "methods": methods}
                routes_by_module.setdefault(module, []).append(route)
                items += self._remember_procedure(f"Route: {rule.endpoint}", [f"المسار: {rule.rule}", f"الوحدة: {module}", f"الطرق: {', '.join(methods)}"], context={"module": module, "path": str(rule.rule)})
            for module, routes in routes_by_module.items():
                items += self._remember_concept(f"Module: {module}", f"وحدة Flask تحتوي على {len(routes)} مسار", examples=[r["path"] for r in routes], related=["routes", "system_modules"])
            print(f"  Routes analyzed: {sum(len(v) for v in routes_by_module.values())}")
        except Exception as exc:
            print(f"  Error: {exc}")
        return items

    def _train_forms(self) -> int:
        items = 0
        form_files: List[Path] = []
        for location in self.FORM_LOCATIONS:
            if location.is_file():
                form_files.append(location)
            elif location.is_dir():
                form_files.extend([p for p in location.rglob("*.py") if p.name != "__init__.py"])
        for form_file in form_files:
            content = self._safe_read(form_file)
            classes = re.findall(r"^class\s+(\w+Form)\s*\(", content, re.MULTILINE)
            fields = re.findall(r"(\w+)\s*=\s*(?:StringField|IntegerField|DecimalField|SelectField|DateField|BooleanField|TextAreaField|SubmitField|PasswordField|FileField)", content)
            for form_class in classes:
                items += self._remember_concept(f"Form: {form_class}", f"نموذج إدخال في {form_file}", examples=fields, related=["forms", "validation"])
        print(f"  Form files analyzed: {len(form_files)}")
        return items

    def _train_templates(self) -> int:
        items = 0
        if not self.TEMPLATE_DIR.exists():
            return 0
        templates = list(self.TEMPLATE_DIR.rglob("*.html"))
        modules: Dict[str, List[str]] = {}
        for template in templates:
            try:
                rel = template.relative_to(self.TEMPLATE_DIR)
                module = str(rel.parent) if str(rel.parent) != "." else "root"
                modules.setdefault(module, []).append(rel.name)
                items += self._remember_fact("template", str(rel), {"path": str(rel), "module": module}, importance=5)
            except Exception:
                continue
        for module, names in modules.items():
            items += self._remember_concept(f"Template Module: {module}", f"قوالب واجهة لوحدة {module}", examples=names, related=["templates", module])
        print(f"  Templates analyzed: {len(templates)}")
        return items

    def _train_python_modules(self) -> int:
        items = 0
        files: List[Path] = []
        for folder in self.ROUTE_FILES:
            path = Path(folder)
            if path.exists():
                files.extend([p for p in path.rglob("*.py") if p.name != "__init__.py"])
        for py_file in files:
            content = self._safe_read(py_file)
            functions = self._public_functions(content)
            classes = self._classes(content)
            if functions or classes:
                items += self._remember_concept(f"Python Module: {py_file}", f"ملف Python يحتوي على {len(functions)} دالة عامة و {len(classes)} كلاس", examples=functions[:10] + classes[:10], related=["python", py_file.parent.name])
        print(f"  Python files analyzed: {len(files)}")
        return items

    def _train_business_workflows(self) -> int:
        workflows = {
            "عملية البيع": ["اختيار الزبون", "اختيار المستودع", "إضافة المنتجات والكميات", "مراجعة الخصم والضريبة من إعدادات النظام", "حفظ/تأكيد البيع", "تحديث المخزون والقيود حسب إعدادات النظام"],
            "تسجيل دفعة": ["اختيار الجهة", "تحديد IN/OUT", "إدخال المبلغ والطريقة", "الحفظ", "تحديث الرصيد والقيود حسب الإعدادات"],
            "الصيانة": ["إنشاء طلب", "تحديد العطل", "إضافة قطع/مهام", "إكمال العمل", "الفوترة عند الحاجة"],
            "المخزون": ["استلام", "بيع", "تحويل", "جرد", "تسوية عند وجود فرق"],
        }
        items = 0
        for name, steps in workflows.items():
            items += self._remember_procedure(name, steps, context={"category": "business_workflow"})
        return items

    def _train_accounting_knowledge(self) -> int:
        concepts = {
            "القيد المزدوج": "كل قيد يجب أن يكون متوازنًا: المدين يساوي الدائن.",
            "دفتر الأستاذ": "تجميع القيود حسب الحساب لتحليل الحركة والرصيد.",
            "ميزان المراجعة": "فحص توازن الحسابات في فترة معينة.",
            "قائمة الدخل": "الإيرادات ناقص المصروفات خلال فترة.",
            "الميزانية": "الأصول تساوي الخصوم زائد حقوق الملكية.",
            "الضريبة": "نسب وقواعد الضريبة يجب أن تأتي من الإعدادات أو مصدر رسمي حديث.",
        }
        items = 0
        for concept, definition in concepts.items():
            items += self._remember_concept(concept, definition, related=["accounting", "GL"])
        return items

    def _train_settings_metadata(self) -> int:
        if not self._has_app_context():
            return 0
        items = 0
        sensitive_patterns = ("key", "secret", "token", "password", "api", "auth", "credential")
        try:
            from models import SystemSettings

            settings = SystemSettings.query.limit(200).all()
            for setting in settings:
                key = str(getattr(setting, "key", ""))
                dtype = getattr(setting, "data_type", None) or getattr(setting, "type", None) or "unknown"
                is_sensitive = any(pattern in key.lower() for pattern in sensitive_patterns)
                value_preview = "[REDACTED]" if is_sensitive else str(getattr(setting, "value", ""))[:80]
                items += self._remember_fact("system_setting", key, {"key": key, "data_type": dtype, "value_preview": value_preview, "sensitive": is_sensitive}, importance=6)
            print(f"  Settings scanned: {len(settings)}")
        except Exception as exc:
            print(f"  Error: {exc}")
        return items

    def _train_security_surfaces(self) -> int:
        items = 0
        security_notes = {
            "AI destructive actions": "AI لا ينفذ الحذف أو عكس القيود أو hard delete تلقائيًا.",
            "Owner routes": "مسارات المالك والتحكم المتقدم تحتاج صلاحيات عالية.",
            "Sensitive settings": "القيم الحساسة مثل API keys لا تُخزن في الذاكرة العميقة كنص صريح.",
            "Book reader": "قراءة الكتب مقيدة داخل AI/data/books فقط.",
        }
        for name, note in security_notes.items():
            items += self._remember_concept(name, note, related=["security", "ai_safety"])
        return items

    def _train_static_assets(self) -> int:
        if not self.STATIC_DIR.exists():
            return 0
        counts = {"images": 0, "scripts": 0, "styles": 0, "other": 0}
        for path in self.STATIC_DIR.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}:
                counts["images"] += 1
            elif ext == ".js":
                counts["scripts"] += 1
            elif ext == ".css":
                counts["styles"] += 1
            else:
                counts["other"] += 1
        return self._remember_fact("static_assets", "static_summary", counts, importance=4)

    def _train_ai_modules(self) -> int:
        items = 0
        ai_dir = Path("AI/engine")
        if not ai_dir.exists():
            return 0
        for ai_file in ai_dir.glob("*.py"):
            if ai_file.name == "__init__.py":
                continue
            content = self._safe_read(ai_file)
            functions = self._public_functions(content)
            classes = self._classes(content)
            items += self._remember_concept(f"AI Engine: {ai_file.stem}", f"محرك AI يحتوي على {len(functions)} دالة عامة و {len(classes)} كلاس", examples=functions[:10] + classes[:10], related=["ai", "engine"])
        return items


_system_deep_trainer = None


def get_system_deep_trainer() -> SystemDeepTrainer:
    global _system_deep_trainer
    if _system_deep_trainer is None:
        _system_deep_trainer = SystemDeepTrainer()
    return _system_deep_trainer


__all__ = ["SystemDeepTrainer", "get_system_deep_trainer"]
