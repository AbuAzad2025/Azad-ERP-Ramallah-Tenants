"""AI Training Engine.

Scans the current system and builds a compact knowledge document for the local AI
assistant. Runtime JSON files go through ai_storage to keep training artifacts
consistent, atomic, and visible in the AI manifest.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import inspect

from extensions import db
from AI.engine.ai_storage import append_json_list, read_json, sync_training_manifest, write_json


TRAINING_STATUS_FILE = "training_status.json"
TRAINING_LOG_FILE = "training_log.json"
KNOWLEDGE_BASE_FILE = "complete_system_knowledge.json"
TRAINING_ARTIFACTS = [TRAINING_STATUS_FILE, TRAINING_LOG_FILE, KNOWLEDGE_BASE_FILE]


class AITrainingEngine:
    """Production-safe training engine for local system knowledge."""

    def __init__(self):
        self.base_path = Path(".")
        self.status = {
            "running": False,
            "progress": 0.0,
            "current_step": "",
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
        self.total_steps = 9
        self.knowledge: Dict[str, Any] = {}
        self.load_status()

    def load_status(self):
        data = read_json(TRAINING_STATUS_FILE, None)
        if isinstance(data, dict):
            self.status = data

    def save_status(self):
        try:
            write_json(TRAINING_STATUS_FILE, self.status)
            sync_training_manifest(extra_files=TRAINING_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error saving training status: {exc}")

    def log_step(self, step: str, details: Dict = None):
        try:
            append_json_list(
                TRAINING_LOG_FILE,
                {"timestamp": datetime.now().isoformat(), "step": step, "details": details or {}},
                max_items=500,
            )
            sync_training_manifest(extra_files=TRAINING_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error logging step: {exc}")

    def run_full_training(self, force: bool = False) -> Dict[str, Any]:
        try:
            from AI.engine.ai_integrated_intelligence import get_integrated_intelligence

            ai = get_integrated_intelligence()
            if not force and getattr(ai, "learning_system", None):
                stats = ai.learning_system.get_learning_stats()
                if stats.get("total_learned_queries", 0) > 100:
                    return {"success": True, "message": "Already trained", "stats": stats}
        except Exception:
            pass
        return self._run_training_process(force)

    def _run_training_process(self, force: bool = False) -> Dict[str, Any]:
        if self.status.get("running") and not force:
            return {"success": False, "error": "Training already running", "status": self.status}

        self.status = {
            "running": True,
            "progress": 0.0,
            "current_step": "Initializing...",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
        }
        self.save_status()

        try:
            self._update_progress(1, "Scanning database...")
            db_knowledge = self._scan_database_complete()
            self.knowledge["database"] = db_knowledge
            self.log_step(
                "database_scan",
                {
                    "tables_count": len(db_knowledge.get("tables", {})),
                    "total_fields": sum(len(t.get("fields", [])) for t in db_knowledge.get("tables", {}).values()),
                },
            )

            self._update_progress(2, "Scanning models...")
            models_knowledge = self._scan_models_complete()
            self.knowledge["models"] = models_knowledge
            self.log_step("models_scan", {"models_count": len(models_knowledge.get("classes", []))})

            self._update_progress(3, "Scanning routes...")
            routes_knowledge = self._scan_routes_complete()
            self.knowledge["routes"] = routes_knowledge
            self.log_step("routes_scan", {"routes_count": len(routes_knowledge.get("routes", []))})

            self._update_progress(4, "Scanning forms...")
            forms_knowledge = self._scan_forms_complete()
            self.knowledge["forms"] = forms_knowledge
            self.log_step("forms_scan", {"forms_count": len(forms_knowledge.get("forms", []))})

            self._update_progress(5, "Scanning templates...")
            templates_knowledge = self._scan_templates_complete()
            self.knowledge["templates"] = templates_knowledge
            self.log_step("templates_scan", {"templates_count": len(templates_knowledge.get("templates", []))})

            self._update_progress(6, "Analyzing relationships...")
            relationships = self._analyze_relationships()
            self.knowledge["relationships"] = relationships
            self.log_step("relationships_analysis", {"relationships_count": len(relationships)})

            self._update_progress(7, "Scanning enums...")
            enums = self._scan_enums()
            self.knowledge["enums"] = enums
            self.log_step("enums_scan", {"enums_count": len(enums)})

            self._update_progress(8, "Training specialized modules...")
            specialized_modules = self._train_specialized_modules()
            self.knowledge["specialized_modules"] = specialized_modules
            self.log_step("specialized_modules", {"modules_trained": len(specialized_modules)})

            self._update_progress(9, "Saving knowledge base...")
            self._save_knowledge_base()
            self.log_step("knowledge_saved", {"file": KNOWLEDGE_BASE_FILE})

            self.status.update(
                {
                    "running": False,
                    "progress": 100.0,
                    "current_step": "Completed",
                    "completed_at": datetime.now().isoformat(),
                    "error": None,
                }
            )
            self.save_status()

            return {
                "success": True,
                "message": "Training completed successfully",
                "status": self.status,
                "knowledge_summary": {
                    "tables": len(db_knowledge.get("tables", {})),
                    "models": len(models_knowledge.get("classes", [])),
                    "routes": len(routes_knowledge.get("routes", [])),
                    "forms": len(forms_knowledge.get("forms", [])),
                    "templates": len(templates_knowledge.get("templates", [])),
                    "relationships": len(relationships),
                    "enums": len(enums),
                },
            }
        except Exception as exc:
            self.status.update({"running": False, "error": str(exc), "completed_at": datetime.now().isoformat()})
            self.save_status()
            self.log_step("error", {"error": str(exc)})
            return {"success": False, "error": str(exc), "status": self.status}

    def _update_progress(self, step: int, message: str):
        progress = (step / self.total_steps) * 100
        self.status.update({"progress": round(progress, 2), "current_step": message})
        self.save_status()
        print(f"[TRAINING] {progress:.1f}% - {message}")

    def _scan_database_complete(self) -> Dict[str, Any]:
        try:
            from flask import has_app_context

            if not has_app_context():
                return {"error": "No application context"}

            inspector = inspect(db.engine)
            tables_info = {}
            for table_name in inspector.get_table_names():
                columns = inspector.get_columns(table_name)
                fields = []
                field_types = {}
                nullable_fields = []
                for col in columns:
                    field_name = col["name"]
                    fields.append(field_name)
                    field_types[field_name] = {
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                        "default": col.get("default"),
                        "autoincrement": col.get("autoincrement", False),
                    }
                    if col.get("nullable", True):
                        nullable_fields.append(field_name)

                tables_info[table_name] = {
                    "fields": fields,
                    "field_types": field_types,
                    "field_count": len(fields),
                    "primary_keys": inspector.get_pk_constraint(table_name).get("constrained_columns", []),
                    "foreign_keys": [
                        {
                            "columns": fk.get("constrained_columns", []),
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns", []),
                        }
                        for fk in inspector.get_foreign_keys(table_name)
                    ],
                    "indexes": [
                        {"name": idx.get("name"), "columns": idx.get("column_names", []), "unique": idx.get("unique", False)}
                        for idx in inspector.get_indexes(table_name)
                    ],
                    "nullable_fields": nullable_fields,
                }
            return {"tables": tables_info, "total_tables": len(tables_info), "scanned_at": datetime.now().isoformat()}
        except Exception as exc:
            print(f"[ERROR] Error scanning database: {exc}")
            return {"error": str(exc)}

    def _scan_models_complete(self) -> Dict[str, Any]:
        models_file = self.base_path / "models.py"
        if not models_file.exists():
            return {"error": "models.py not found"}
        try:
            content = models_file.read_text(encoding="utf-8")
            classes = []
            class_pattern = r"^class\s+(\w+)\s*\([^)]*db\.Model[^)]*\):"
            for match in re.finditer(class_pattern, content, re.MULTILINE):
                class_name = match.group(1)
                class_content = content[match.end() : self._find_class_end(content, match.end())]
                fields = re.findall(r"(\w+)\s*=\s*db\.(Column|relationship|hybrid_property)", class_content)
                classes.append({"name": class_name, "fields": [f[0] for f in fields], "field_types": [f[1] for f in fields]})
            return {"classes": classes, "total_classes": len(classes), "scanned_at": datetime.now().isoformat()}
        except Exception as exc:
            return {"error": str(exc)}

    def _find_class_end(self, content: str, start: int) -> int:
        next_match = re.search(r"\nclass\s+\w+", content[start:])
        return start + next_match.start() if next_match else len(content)

    def _scan_routes_complete(self) -> Dict[str, Any]:
        routes = []
        routes_dir = self.base_path / "routes"
        if not routes_dir.exists():
            return {"routes": []}
        route_pattern = r"@(\w+_bp)\.route\([\'\"](.+?)[\'\"]\s*(?:,\s*methods=\[(.+?)\])?\)"
        for py_file in routes_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                for match in re.finditer(route_pattern, content):
                    methods_str = match.group(3)
                    methods = [m.strip().strip("\"'") for m in methods_str.split(",")] if methods_str else ["GET"]
                    func_match = re.search(r"def\s+(\w+)\s*\(", content[match.end() : match.end() + 250])
                    routes.append(
                        {
                            "path": match.group(2),
                            "methods": methods,
                            "function": func_match.group(1) if func_match else "unknown",
                            "blueprint": match.group(1),
                            "file": str(py_file.relative_to(self.base_path)),
                        }
                    )
            except Exception as exc:
                print(f"[ERROR] Error scanning {py_file}: {exc}")
        return {"routes": routes, "total_routes": len(routes), "scanned_at": datetime.now().isoformat()}

    def _scan_forms_complete(self) -> Dict[str, Any]:
        forms_file = self.base_path / "forms.py"
        if not forms_file.exists():
            return {"forms": []}
        try:
            content = forms_file.read_text(encoding="utf-8")
            forms = []
            form_pattern = r"^class\s+(\w+Form)\s*\([^)]*FlaskForm[^)]*\):"
            field_pattern = r"(\w+)\s*=\s*(StringField|IntegerField|DecimalField|SelectField|DateField|BooleanField|TextAreaField|SubmitField)"
            for match in re.finditer(form_pattern, content, re.MULTILINE):
                form_name = match.group(1)
                form_content = content[match.end() : self._find_class_end(content, match.end())]
                fields = re.findall(field_pattern, form_content)
                forms.append({"name": form_name, "fields": [f[0] for f in fields], "field_types": [f[1] for f in fields]})
            return {"forms": forms, "total_forms": len(forms), "scanned_at": datetime.now().isoformat()}
        except Exception as exc:
            return {"error": str(exc)}

    def _scan_templates_complete(self) -> Dict[str, Any]:
        templates = []
        templates_dir = self.base_path / "templates"
        if not templates_dir.exists():
            return {"templates": []}
        for html_file in templates_dir.rglob("*.html"):
            try:
                content = html_file.read_text(encoding="utf-8")
                templates.append(
                    {
                        "path": str(html_file.relative_to(templates_dir)),
                        "extends": re.findall(r"{%\s*extends\s+[\'\"](.+?)[\'\"]\s*%}", content),
                        "includes": re.findall(r"{%\s*include\s+[\'\"](.+?)[\'\"]\s*%}", content),
                        "size": len(content),
                        "lines": content.count("\n"),
                    }
                )
            except Exception as exc:
                print(f"[ERROR] Error scanning {html_file}: {exc}")
        return {"templates": templates, "total_templates": len(templates), "scanned_at": datetime.now().isoformat()}

    def _analyze_relationships(self) -> List[Dict[str, Any]]:
        relationships = []
        try:
            from flask import has_app_context

            if not has_app_context():
                return []
            inspector = inspect(db.engine)
            for table_name in inspector.get_table_names():
                for fk in inspector.get_foreign_keys(table_name):
                    relationships.append(
                        {
                            "from_table": table_name,
                            "from_columns": fk.get("constrained_columns", []),
                            "to_table": fk.get("referred_table"),
                            "to_columns": fk.get("referred_columns", []),
                            "type": "many-to-one" if len(fk.get("constrained_columns", [])) == 1 else "composite",
                        }
                    )
        except Exception as exc:
            print(f"[ERROR] Error analyzing relationships: {exc}")
        return relationships

    def _scan_enums(self) -> List[Dict[str, Any]]:
        enums = []
        models_file = self.base_path / "models.py"
        if not models_file.exists():
            return enums
        try:
            content = models_file.read_text(encoding="utf-8")
            enum_pattern = r"(class\s+(\w+)\s*\([^)]*Enum[^)]*\):.*?)(?=\nclass\s+\w+|\Z)"
            for match in re.finditer(enum_pattern, content, re.MULTILINE | re.DOTALL):
                enum_name = match.group(2)
                values = re.findall(r"(\w+)\s*=\s*[\'\"]([^\'\"]+)[\'\"]", match.group(1))
                enums.append({"name": enum_name, "values": {k: v for k, v in values}, "file": "models.py"})
        except Exception as exc:
            print(f"[ERROR] Error scanning enums: {exc}")
        return enums

    def _train_specialized_modules(self) -> Dict[str, Any]:
        modules_data = {}
        try:
            from flask import current_app, has_app_context
            from models import Check, Partner, Product, Supplier

            if not has_app_context():
                return {"error": "No application context"}
            inspector = inspect(db.engine)

            module_specs = {
                "checks": (Check, "routes/checks.py", "نظام إدارة الشيكات الكامل مع دورة حياة الشيك"),
                "vendors_suppliers": (Supplier, "routes/vendors.py", "نظام إدارة الموردين والتسويات"),
                "partners": (Partner, "routes/partner_settlements.py", "نظام إدارة الشركاء والحصص والتسويات"),
                "products": (Product, "routes/parts.py", "نظام إدارة المنتجات الكامل مع الفئات والتقييمات"),
            }
            for key, (model, route_file, description) in module_specs.items():
                try:
                    modules_data[key] = {
                        "model": model.__name__,
                        "columns": [col.name for col in model.__table__.columns],
                        "related_tables": [t for t in inspector.get_table_names() if key.split("_")[0].rstrip("s") in t.lower()],
                        "routes_file": route_file,
                        "description": description,
                    }
                except Exception as exc:
                    modules_data[key] = {"error": str(exc)}

            owner_routes = []
            for rule in current_app.url_map.iter_rules():
                if "owner" in rule.endpoint.lower() or "advanced" in rule.endpoint.lower():
                    owner_routes.append({"path": rule.rule, "endpoint": rule.endpoint})
            modules_data["owner"] = {
                "routes": owner_routes,
                "files": ["routes/advanced_control.py", "routes/security_control.py", "routes/security.py"],
                "description": "وحدة المالك - جميع الصلاحيات والتحكم المتقدم",
            }
            modules_data["remaining_modules"] = {
                "modules": [
                    "warehouses",
                    "branches",
                    "expenses",
                    "shipments",
                    "ledger",
                    "financial_reports",
                    "accounting_docs",
                    "currencies",
                    "bank",
                    "notes",
                    "projects",
                    "assets",
                    "budgets",
                    "cost_centers",
                    "barcode",
                    "archive",
                ],
                "description": "الوحدات المتبقية في النظام",
            }
        except Exception as exc:
            print(f"[ERROR] Error training specialized modules: {exc}")
        return modules_data

    def _save_knowledge_base(self):
        try:
            knowledge_doc = {
                "version": "2.1",
                "created_at": datetime.now().isoformat(),
                "knowledge": self.knowledge,
                "summary": {
                    "tables": len(self.knowledge.get("database", {}).get("tables", {})),
                    "models": len(self.knowledge.get("models", {}).get("classes", [])),
                    "routes": len(self.knowledge.get("routes", {}).get("routes", [])),
                    "forms": len(self.knowledge.get("forms", {}).get("forms", [])),
                    "templates": len(self.knowledge.get("templates", {}).get("templates", [])),
                    "relationships": len(self.knowledge.get("relationships", [])),
                    "enums": len(self.knowledge.get("enums", [])),
                },
            }
            write_json(KNOWLEDGE_BASE_FILE, knowledge_doc)
            sync_training_manifest(extra_files=TRAINING_ARTIFACTS)
        except Exception as exc:
            print(f"[ERROR] Error saving knowledge base: {exc}")
            raise

    def get_status(self) -> Dict[str, Any]:
        self.load_status()
        return self.status

    def get_training_log(self, limit: int = 50) -> List[Dict]:
        log = read_json(TRAINING_LOG_FILE, [])
        if not isinstance(log, list):
            return []
        return log[-max(1, int(limit or 50)) :]


_training_engine = None


def get_training_engine() -> AITrainingEngine:
    global _training_engine
    if _training_engine is None:
        _training_engine = AITrainingEngine()
    return _training_engine


__all__ = ["AITrainingEngine", "get_training_engine"]
