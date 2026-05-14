"""AI Continuous Learner.

Studies database schema, routes, models, forms, and business logic snapshots.
Uses ai_storage for consistent, atomic persistence and bounded session history.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

CL_DIR = "continuous_learning"
KNOWLEDGE_FILE = f"{CL_DIR}/knowledge_base.json"
SNAPSHOT_FILE = f"{CL_DIR}/last_snapshot.json"
SESSIONS_FILE = f"{CL_DIR}/sessions.json"
MAX_SESSIONS = 50


class ContinuousLearner:
    def __init__(self):
        self.knowledge_base: Dict[str, Any] = {}
        self.system_snapshot = {}
        self.changes_detected: List[Dict[str, Any]] = []
        self.learning_sessions: List[Dict[str, Any]] = []
        self.last_scan_time = None
        self._load_existing_knowledge()

    def _load_existing_knowledge(self):
        kb = read_json(KNOWLEDGE_FILE, {})
        self.knowledge_base = kb if isinstance(kb, dict) else {}
        sessions = read_json(SESSIONS_FILE, [])
        self.learning_sessions = sessions[-MAX_SESSIONS:] if isinstance(sessions, list) else []

    def start_learning_session(self) -> Dict[str, Any]:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        session = {
            "id": session_id,
            "start_time": datetime.now().isoformat(),
            "phases": [],
            "discoveries": [],
            "total_items_learned": 0,
            "status": "running",
        }

        for phase_func in (
            self._study_database_schema,
            self._study_routes_and_endpoints,
            self._study_models_and_relationships,
            self._study_forms_and_validations,
            self._study_business_logic,
            self._detect_changes_from_last_session,
        ):
            phase = phase_func()
            session["phases"].append(phase)
            session["total_items_learned"] += int(phase.get("items_learned", 0) or 0)
            session["discoveries"].extend(phase.get("discoveries", []) or [])

        session["end_time"] = datetime.now().isoformat()
        session["status"] = "completed"
        self.learning_sessions.append(session)
        self.learning_sessions = self.learning_sessions[-MAX_SESSIONS:]
        self._save_session(session)
        self._update_knowledge_base()
        return session

    def _study_database_schema(self) -> Dict:
        phase = {"name": "Database Schema Study", "items_learned": 0, "discoveries": [], "tables_analyzed": []}
        try:
            from extensions import db
            from sqlalchemy import inspect

            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            for table_name in tables:
                table_info = {"name": table_name, "columns": [], "indexes": [], "foreign_keys": [], "primary_keys": []}
                for col in inspector.get_columns(table_name):
                    table_info["columns"].append(
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                            "default": str(col.get("default")) if col.get("default") else None,
                        }
                    )
                for idx in inspector.get_indexes(table_name):
                    table_info["indexes"].append({"name": idx.get("name"), "columns": idx.get("column_names", []), "unique": idx.get("unique", False)})
                for fk in inspector.get_foreign_keys(table_name):
                    table_info["foreign_keys"].append(
                        {
                            "constrained_columns": fk.get("constrained_columns", []),
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns", []),
                        }
                    )
                pk = inspector.get_pk_constraint(table_name)
                if pk and pk.get("constrained_columns"):
                    table_info["primary_keys"] = pk["constrained_columns"]
                self.knowledge_base[f"table_{table_name}"] = table_info
                phase["tables_analyzed"].append(table_name)
                phase["items_learned"] += 1
            phase["discoveries"].append(f"Analyzed {len(tables)} database tables")
        except Exception as exc:
            phase["error"] = str(exc)
        return phase

    def _study_routes_and_endpoints(self) -> Dict:
        phase = {"name": "Routes and Endpoints Study", "items_learned": 0, "discoveries": [], "routes_analyzed": []}
        try:
            from flask import current_app, has_app_context

            if not has_app_context():
                raise RuntimeError("No app context")
            routes_info = {}
            for rule in current_app.url_map.iter_rules():
                if rule.endpoint != "static":
                    route_key = f"route_{rule.endpoint}"
                    routes_info[route_key] = {
                        "endpoint": rule.endpoint,
                        "path": str(rule.rule),
                        "methods": sorted(list(rule.methods - {"HEAD", "OPTIONS"})),
                        "blueprint": rule.endpoint.split(".")[0] if "." in rule.endpoint else None,
                    }
                    phase["routes_analyzed"].append(rule.endpoint)
                    phase["items_learned"] += 1
            self.knowledge_base.update(routes_info)
            phase["discoveries"].append(f"Memorized {len(routes_info)} routes")
        except Exception as exc:
            phase["error"] = str(exc)
        return phase

    def _study_models_and_relationships(self) -> Dict:
        phase = {"name": "Models and Relationships Study", "items_learned": 0, "discoveries": [], "models_analyzed": []}
        try:
            from extensions import db

            models_info = {}
            for mapper in db.Model.registry.mappers:
                model_class = mapper.class_
                model_name = model_class.__name__
                model_info = {"name": model_name, "table": getattr(model_class, "__tablename__", None), "columns": [], "relationships": []}
                for column in mapper.columns:
                    model_info["columns"].append(
                        {
                            "name": column.name,
                            "type": str(column.type),
                            "primary_key": column.primary_key,
                            "nullable": column.nullable,
                            "unique": column.unique,
                        }
                    )
                for rel_name, relationship in mapper.relationships.items():
                    model_info["relationships"].append(
                        {"name": rel_name, "target": relationship.entity.class_.__name__, "direction": relationship.direction.name, "uselist": relationship.uselist}
                    )
                models_info[f"model_{model_name}"] = model_info
                phase["models_analyzed"].append(model_name)
                phase["items_learned"] += 1
            self.knowledge_base.update(models_info)
            phase["discoveries"].append(f"Studied {len(models_info)} models with relationships")
        except Exception as exc:
            phase["error"] = str(exc)
        return phase

    def _study_forms_and_validations(self) -> Dict:
        phase = {"name": "Forms and Validations Study", "items_learned": 0, "discoveries": [], "forms_found": []}
        try:
            files = []
            forms_py = Path("forms.py")
            if forms_py.exists():
                files.append(forms_py)
            forms_dir = Path("forms")
            if forms_dir.exists():
                files.extend([p for p in forms_dir.rglob("*.py") if p.name != "__init__.py"])
            for form_file in files:
                content = form_file.read_text(encoding="utf-8")
                form_name = form_file.stem
                self.knowledge_base[f"form_{form_name}"] = {
                    "file": str(form_file),
                    "content_hash": hashlib.md5(content.encode()).hexdigest(),
                    "size": len(content),
                    "last_modified": datetime.fromtimestamp(form_file.stat().st_mtime).isoformat(),
                }
                phase["forms_found"].append(form_name)
                phase["items_learned"] += 1
            phase["discoveries"].append(f"Analyzed {len(phase['forms_found'])} forms")
        except Exception as exc:
            phase["error"] = str(exc)
        return phase

    def _study_business_logic(self) -> Dict:
        phase = {"name": "Business Logic Study", "items_learned": 0, "discoveries": [], "routes_scanned": []}
        try:
            routes_dir = Path("routes")
            if routes_dir.exists():
                for route_file in routes_dir.rglob("*.py"):
                    if route_file.name == "__init__.py":
                        continue
                    content = route_file.read_text(encoding="utf-8")
                    route_name = route_file.stem
                    self.knowledge_base[f"business_logic_{route_name}"] = {
                        "file": str(route_file),
                        "content_hash": hashlib.md5(content.encode()).hexdigest(),
                        "size": len(content),
                        "functions_count": content.count("def "),
                        "routes_count": content.count("@"),
                        "last_modified": datetime.fromtimestamp(route_file.stat().st_mtime).isoformat(),
                    }
                    phase["routes_scanned"].append(route_name)
                    phase["items_learned"] += 1
                phase["discoveries"].append(f"Studied business logic in {len(phase['routes_scanned'])} route files")
        except Exception as exc:
            phase["error"] = str(exc)
        return phase

    def _detect_changes_from_last_session(self) -> Dict:
        phase = {"name": "Change Detection", "items_learned": 0, "discoveries": [], "changes_found": []}
        old_snapshot = read_json(SNAPSHOT_FILE, {})
        if isinstance(old_snapshot, dict) and old_snapshot:
            for key, new_value in self.knowledge_base.items():
                if key not in old_snapshot:
                    phase["changes_found"].append({"type": "NEW", "key": key, "description": f"New item added: {key}"})
                    phase["items_learned"] += 1
                elif isinstance(new_value, dict) and isinstance(old_snapshot.get(key), dict) and new_value.get("content_hash") != old_snapshot[key].get("content_hash"):
                    phase["changes_found"].append({"type": "MODIFIED", "key": key, "description": f"Item modified: {key}"})
                    phase["items_learned"] += 1
            for key in old_snapshot:
                if key not in self.knowledge_base:
                    phase["changes_found"].append({"type": "DELETED", "key": key, "description": f"Item removed: {key}"})
            if phase["changes_found"]:
                phase["discoveries"].append(f"Detected {len(phase['changes_found'])} changes since last session")
            else:
                phase["discoveries"].append("No changes detected - system is stable")
        else:
            phase["discoveries"].append("First learning session - building initial knowledge base")
        write_json(SNAPSHOT_FILE, self.knowledge_base)
        sync_training_manifest(extra_files=[SNAPSHOT_FILE])
        self.changes_detected = phase["changes_found"]
        return phase

    def _save_session(self, session: Dict):
        write_json(f"{CL_DIR}/session_{session['id']}.json", session)
        write_json(SESSIONS_FILE, self.learning_sessions[-MAX_SESSIONS:])
        sync_training_manifest(extra_files=[SESSIONS_FILE, f"{CL_DIR}/session_{session['id']}.json"])

    def _update_knowledge_base(self):
        write_json(KNOWLEDGE_FILE, self.knowledge_base)
        sync_training_manifest(extra_files=[KNOWLEDGE_FILE])

    def get_learning_stats(self) -> Dict:
        return {
            "total_knowledge_items": len(self.knowledge_base),
            "total_sessions": len(self.learning_sessions),
            "last_session": self.learning_sessions[-1] if self.learning_sessions else None,
            "recent_changes": self.changes_detected[-20:] if self.changes_detected else [],
        }

    def search_knowledge(self, query: str) -> List[Dict]:
        results = []
        query_lower = str(query or "").lower()
        if not query_lower:
            return results
        for key, value in self.knowledge_base.items():
            if query_lower in key.lower():
                results.append({"key": key, "value": value, "match_type": "key"})
            elif isinstance(value, dict) and any(query_lower in str(v).lower() for v in value.values()):
                results.append({"key": key, "value": value, "match_type": "value"})
        return results[:50]


_continuous_learner = None


def get_continuous_learner():
    global _continuous_learner
    if _continuous_learner is None:
        _continuous_learner = ContinuousLearner()
    return _continuous_learner


__all__ = ["ContinuousLearner", "get_continuous_learner"]
