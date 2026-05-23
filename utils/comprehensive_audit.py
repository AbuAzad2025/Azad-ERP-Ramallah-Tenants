"""تدقيق شامل: DB ↔ models ↔ endpoints ↔ templates ↔ JS."""
from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy import inspect, text


def _model_tables(app) -> Dict[str, Any]:
    from extensions import db

    tables: Dict[str, Any] = {}
    with app.app_context():
        seen_tables: Set[str] = set()
        for mapper in db.Model.registry.mappers:
            cls = mapper.class_
            tab = getattr(mapper.local_table, "name", None) or getattr(cls, "__tablename__", None)
            if not tab or tab in seen_tables:
                continue
            seen_tables.add(tab)
            tables[tab] = cls
    return tables


def audit_models_vs_db(app) -> Dict[str, Any]:
    from extensions import db

    issues: List[Dict[str, Any]] = []
    with app.app_context():
        inspector = inspect(db.engine)
        db_tables = set(inspector.get_table_names())
        model_tables = _model_tables(app)
        model_names = set(model_tables.keys())

        for t in sorted(model_names - db_tables):
            issues.append({"level": "critical", "category": "schema", "msg": f"جدول في الموديل غير موجود في DB: {t}"})
        orm_ignore_db_only = set()  # tables now mapped via link models
        for t in sorted(db_tables - model_names):
            if t.startswith("alembic_") or t in orm_ignore_db_only:
                continue
            issues.append({"level": "warning", "category": "schema", "msg": f"جدول في DB بلا موديل ORM: {t}"})

        for table, cls in sorted(model_tables.items()):
            if table not in db_tables:
                continue
            db_cols = {c["name"] for c in inspector.get_columns(table)}
            model_cols = set()
            for col in cls.__table__.columns:
                model_cols.add(col.name)
            for c in sorted(model_cols - db_cols):
                issues.append({
                    "level": "critical",
                    "category": "schema",
                    "msg": f"{table}.{c} في الموديل فقط",
                })
            for c in sorted(db_cols - model_cols):
                if c in ("created_at", "updated_at"):
                    continue
                issues.append({
                    "level": "warning",
                    "category": "schema",
                    "msg": f"{table}.{c} في DB فقط",
                })

            db_fks = inspector.get_foreign_keys(table) or []
            for fk in db_fks:
                ref = fk.get("referred_table")
                if ref and ref not in db_tables:
                    issues.append({
                        "level": "critical",
                        "category": "fk",
                        "msg": f"FK {table} → {ref} (جدول مرجعي مفقود)",
                    })

    return {"issues": issues, "model_count": len(model_tables), "db_table_count": len(db_tables)}


def audit_orphan_fk_rows(app, *, sample_limit: int = 5) -> Dict[str, Any]:
    """عينة من صفوف تنتهك FK (إن وُجدت بيانات يتيمة)."""
    from extensions import db

    checks = [
        ("sales", "customer_id", "customers", "id"),
        ("payments", "customer_id", "customers", "id", True),
        ("invoices", "customer_id", "customers", "id", True),
        ("gl_entries", "batch_id", "gl_batches", "id"),
    ]
    issues: List[Dict[str, Any]] = []
    with app.app_context():
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        for spec in checks:
            table, col, ref_table, ref_col = spec[:4]
            nullable = len(spec) > 4 and spec[4]
            if table not in tables or ref_table not in tables:
                continue
            try:
                if nullable:
                    q = text(
                        f"SELECT COUNT(*) FROM {table} t "
                        f"LEFT JOIN {ref_table} r ON t.{col} = r.{ref_col} "
                        f"WHERE t.{col} IS NOT NULL AND r.{ref_col} IS NULL"
                    )
                else:
                    q = text(
                        f"SELECT COUNT(*) FROM {table} t "
                        f"LEFT JOIN {ref_table} r ON t.{col} = r.{ref_col} "
                        f"WHERE r.{ref_col} IS NULL"
                    )
                cnt = db.session.execute(q).scalar() or 0
                if cnt:
                    issues.append({
                        "level": "critical",
                        "category": "fk_data",
                        "msg": f"{cnt} صف يتيم في {table}.{col} → {ref_table}",
                        "count": int(cnt),
                    })
            except Exception as e:
                issues.append({
                    "level": "warning",
                    "category": "fk_data",
                    "msg": f"تعذّر فحص {table}.{col}: {e}",
                })
    return {"issues": issues}


def audit_endpoints(app) -> Dict[str, Any]:
    rules = []
    by_endpoint: Dict[str, List[str]] = defaultdict(list)
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        rules.append({
            "rule": rule.rule,
            "endpoint": rule.endpoint,
            "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
        })
        by_endpoint[rule.endpoint].append(rule.rule)

    dup_endpoints = {k: v for k, v in by_endpoint.items() if len(set(v)) > 1}
    issues = []
    for ep, paths in sorted(dup_endpoints.items()):
        unique_paths = sorted(set(paths))
        if len(unique_paths) <= 1:
            continue
        issues.append({
            "level": "warning",
            "category": "endpoint",
            "msg": f"endpoint '{ep}' بمسارات مختلفة: {unique_paths}",
        })

    return {
        "route_count": len(rules),
        "endpoint_count": len(by_endpoint),
        "duplicate_endpoints": dup_endpoints,
        "issues": issues,
    }


def _extract_url_for_calls(content: str) -> Set[str]:
    return set(re.findall(r"url_for\(\s*['\"]([^'\"]+)['\"]", content))


def audit_templates_endpoints(app, templates_dir: str) -> Dict[str, Any]:
    """قوالب تستدعي endpoints غير مسجّلة."""
    registered = {rule.endpoint for rule in app.url_map.iter_rules()}
    broken: List[Dict[str, str]] = []
    scanned = 0
    for root, _dirs, files in os.walk(templates_dir):
        for fn in files:
            if not fn.endswith((".html", ".jinja", ".jinja2")):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    body = f.read()
            except OSError:
                continue
            scanned += 1
            for ep in _extract_url_for_calls(body):
                if ep not in registered:
                    broken.append({"file": path, "endpoint": ep})

    issues = [
        {"level": "critical" if b else "info", "category": "template", "msg": f"{b['file']}: url_for('{b['endpoint']}') غير موجود"}
        for b in broken[:80]
    ]
    if len(broken) > 80:
        issues.append({"level": "warning", "category": "template", "msg": f"... و {len(broken) - 80} مراجع أخرى"})
    return {"templates_scanned": scanned, "broken_refs": broken, "broken_count": len(broken), "issues": issues}


def audit_javascript(project_root: str) -> Dict[str, Any]:
    """فحص JS: ملفات static + كتل script في القوالب."""
    issues: List[Dict[str, Any]] = []
    scanned = 0
    paths: List[str] = []
    static_js = os.path.join(project_root, "static")
    if os.path.isdir(static_js):
        for root, _d, files in os.walk(static_js):
            for fn in files:
                if fn.endswith(".js"):
                    paths.append(os.path.join(root, fn))
    templates = os.path.join(project_root, "templates")
    if os.path.isdir(templates):
        for root, _d, files in os.walk(templates):
            for fn in files:
                if not fn.endswith(".html"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        html = f.read()
                except OSError:
                    continue
                for m in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", html, re.I):
                    code = m.group(1).strip()
                    if not code or "src=" in (m.group(0)[:80]):
                        continue
                    scanned += 1
                    _lint_js_snippet(code, f"{fp}:inline", issues)

    for fp in paths:
        scanned += 1
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                code = f.read()
        except OSError as e:
            issues.append({"level": "warning", "category": "js", "msg": f"لا يمكن قراءة {fp}: {e}"})
            continue
        _lint_js_snippet(code, fp, issues)

    return {"js_files_scanned": scanned, "issues": issues}


def _lint_js_snippet(code: str, label: str, issues: List[Dict[str, Any]]) -> None:
    if "{{" in code and "}}" in code:
        return
    risky = [
        (r"eval\s*\(", "استخدام eval"),
        (r"document\.write\s*\(", "document.write"),
        (r"innerHTML\s*=\s*[^'\"]", "innerHTML ديناميكي"),
    ]
    for pat, desc in risky:
        if re.search(pat, code):
            issues.append({"level": "warning", "category": "js", "msg": f"{label}: {desc}"})
    norm = label.replace("\\", "/")
    if "/static/adminlte/" in norm or "/plugins/" in norm or norm.endswith("/static/js/dom-safe.js"):
        return
    if "AzadDom.setHtmlTrusted" in code or "AzadDom.escapeHtml" in code:
        return
    open_count = code.count("{") - code.count("}")
    if abs(open_count) > 2:
        issues.append({"level": "info", "category": "js", "msg": f"{label}: عدم توازن أقواس {{}} محتمل"})


def audit_blueprint_registration(app) -> Dict[str, Any]:
    """مسارات مكررة بنفس rule+method."""
    seen: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    issues = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (rule.rule, method)
            seen[key].append(rule.endpoint)
    for key, eps in seen.items():
        if len(eps) > 1:
            issues.append({
                "level": "critical",
                "category": "route_collision",
                "msg": f"{key[1]} {key[0]} → {eps}",
            })
    return {"collisions": len(issues), "issues": issues}


def run_comprehensive_audit(app, *, project_root: str | None = None) -> Dict[str, Any]:
    root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(root, "templates")

    sections = {
        "models_db": audit_models_vs_db(app),
        "orphan_fk": audit_orphan_fk_rows(app),
        "endpoints": audit_endpoints(app),
        "route_collisions": audit_blueprint_registration(app),
        "templates": audit_templates_endpoints(app, templates_dir),
        "javascript": audit_javascript(root),
    }

    from utils.integration_audit import run_integration_audit

    sections["integration"] = run_integration_audit(app)

    all_issues: List[Dict[str, Any]] = []
    for name, data in sections.items():
        if isinstance(data, dict):
            for iss in data.get("issues", []):
                iss = dict(iss)
                iss["section"] = name
                all_issues.append(iss)

    critical = [i for i in all_issues if i.get("level") == "critical"]
    warning = [i for i in all_issues if i.get("level") == "warning"]

    return {
        "ok": len(critical) == 0,
        "summary": {
            "critical": len(critical),
            "warning": len(warning),
            "total_issues": len(all_issues),
            "routes": sections["endpoints"].get("route_count"),
            "models": sections["models_db"].get("model_count"),
            "template_broken_url_for": sections["templates"].get("broken_count"),
            "route_collisions": sections["route_collisions"].get("collisions"),
        },
        "sections": sections,
        "issues": all_issues,
    }


def format_audit_report_text(report: Dict[str, Any]) -> str:
    lines = [
        "=== تدقيق شامل Garage Manager ===",
        f"الحالة: {'OK' if report.get('ok') else 'ISSUES FOUND'}",
        f"حرج: {report['summary']['critical']} | تحذير: {report['summary']['warning']}",
        f"مسارات: {report['summary']['routes']} | موديلات: {report['summary']['models']}",
        f"url_for مكسور: {report['summary']['template_broken_url_for']} | تصادم مسارات: {report['summary']['route_collisions']}",
        "",
    ]
    by_level = {"critical": [], "warning": [], "info": []}
    for i in report.get("issues", []):
        by_level.get(i.get("level", "info"), []).append(i)
    for lvl in ("critical", "warning", "info"):
        items = by_level.get(lvl) or []
        if not items:
            continue
        lines.append(f"--- {lvl.upper()} ({len(items)}) ---")
        for i in items[:50]:
            lines.append(f"  [{i.get('section', '?')}] {i.get('msg', '')}")
        if len(items) > 50:
            lines.append(f"  ... +{len(items) - 50} أخرى")
        lines.append("")
    return "\n".join(lines)
