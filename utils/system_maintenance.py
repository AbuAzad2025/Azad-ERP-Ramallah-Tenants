"""
صيانة النظام — إحصائيات وتنفيذ حقيقي (بدون محاكاة).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text


def _human_size(num_bytes: int) -> str:
    n = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _dir_stats(paths: list[Path], *, min_age_days: int | None = None) -> tuple[int, int]:
    """عدد الملفات والحجم الإجمالي (اختياري: فقط الأقدم من min_age_days)."""
    count = 0
    total = 0
    cutoff = None
    if min_age_days is not None:
        cutoff = datetime.now().timestamp() - (min_age_days * 86400)
    for base in paths:
        if not base.is_dir():
            continue
        try:
            for entry in base.rglob("*"):
                if not entry.is_file():
                    continue
                try:
                    if cutoff is not None and entry.stat().st_mtime >= cutoff:
                        continue
                    count += 1
                    total += entry.stat().st_size
                except OSError:
                    continue
        except OSError:
            continue
    return count, total


def _remove_dir_files(paths: list[Path], *, min_age_days: int | None = None) -> tuple[int, int]:
    """حذف ملفات من مجلدات مؤقتة — يُرجع (عدد المحذوف، بايتات محررة)."""
    removed = 0
    freed = 0
    cutoff = None
    if min_age_days is not None:
        cutoff = datetime.now().timestamp() - (min_age_days * 86400)
    for base in paths:
        if not base.is_dir():
            continue
        try:
            for entry in base.rglob("*"):
                if not entry.is_file():
                    continue
                try:
                    st = entry.stat()
                    if cutoff is not None and st.st_mtime >= cutoff:
                        continue
                    freed += st.st_size
                    entry.unlink()
                    removed += 1
                except OSError:
                    continue
            # إزالة مجلدات فارغة
            for entry in sorted(base.rglob("*"), reverse=True):
                if entry.is_dir():
                    try:
                        entry.rmdir()
                    except OSError:
                        pass
        except OSError:
            continue
    return removed, freed


def _temp_paths(app) -> list[Path]:
    root = Path(app.root_path)
    instance = Path(app.instance_path)
    paths = [
        instance / "temp",
        instance / "cache",
        instance / "uploads" / "tmp",
        root / "static" / "uploads" / "tmp",
    ]
    return [p for p in paths if p.exists() or p.parent.exists()]


def _log_paths(app) -> list[Path]:
    root = Path(app.root_path)
    instance = Path(app.instance_path)
    candidates = [
        root / "logs",
        instance / "logs",
        root / "AI" / "data",
        root / "AI" / "data" / "daily_reports",
    ]
    return [p for p in candidates if p.is_dir()]


def _cache_item_count(cache) -> int | None:
    try:
        backend = getattr(cache, "cache", None)
        if backend is None:
            return None
        inner = getattr(backend, "_cache", None)
        if isinstance(inner, dict):
            return len(inner)
        if hasattr(inner, "__len__"):
            return len(inner)
    except Exception:
        pass
    return None


def _database_size_bytes(app) -> int | None:
    uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
    try:
        if "postgresql" in uri:
            from extensions import db

            row = db.session.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar()
            return int(row or 0)
        if "sqlite" in uri:
            from sqlalchemy.engine.url import make_url

            u = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
            db_path = u.database
            if db_path and db_path != ":memory:" and os.path.isfile(db_path):
                return os.path.getsize(db_path)
    except Exception:
        pass
    return None


def collect_maintenance_stats(app, *, cache=None) -> dict[str, Any]:
    temp_paths = _temp_paths(app)
    log_paths = _log_paths(app)
    t_count, t_bytes = _dir_stats(temp_paths)
    _, log_bytes = _dir_stats(log_paths)
    cache_n = _cache_item_count(cache) if cache is not None else None
    db_bytes = _database_size_bytes(app)

    return {
        "temp_files_count": t_count,
        "temp_files_size": _human_size(t_bytes),
        "temp_files_bytes": t_bytes,
        "logs_size": _human_size(log_bytes),
        "logs_bytes": log_bytes,
        "cache_items": cache_n if cache_n is not None else "—",
        "db_size": _human_size(db_bytes) if db_bytes is not None else "—",
        "db_bytes": db_bytes,
    }


def clear_application_cache(cache) -> dict[str, Any]:
    cache.clear()
    remaining = _cache_item_count(cache)
    return {
        "ok": True,
        "message": "تم مسح ذاكرة التخزين المؤقت.",
        "remaining": remaining if remaining is not None else 0,
    }


def cleanup_temp_files(app, *, min_age_days: int = 0) -> dict[str, Any]:
    paths = _temp_paths(app)
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
    removed, freed = _remove_dir_files(paths, min_age_days=min_age_days if min_age_days > 0 else None)
    return {
        "ok": True,
        "message": f"تم حذف {removed} ملفاً مؤقتاً ({_human_size(freed)}).",
        "removed": removed,
        "freed_bytes": freed,
    }


def purge_old_logs(app, *, days: int = 30) -> dict[str, Any]:
    from extensions import db
    from models import AuditLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    audit_deleted = 0
    files_deleted = 0
    files_freed = 0

    try:
        audit_deleted = (
            AuditLog.query.filter(AuditLog.created_at < cutoff).delete(synchronize_session=False)
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log_paths = _log_paths(app)
    file_cutoff = cutoff.timestamp()
    for base in log_paths:
        try:
            for fp in base.rglob("*"):
                if not fp.is_file():
                    continue
                if fp.suffix.lower() not in {".log", ".txt", ".jsonl"}:
                    continue
                try:
                    if fp.stat().st_mtime >= file_cutoff:
                        continue
                    sz = fp.stat().st_size
                    fp.unlink()
                    files_deleted += 1
                    files_freed += sz
                except OSError:
                    continue
        except OSError:
            continue

    return {
        "ok": True,
        "message": (
            f"تم حذف {audit_deleted} سجل تدقيق و{files_deleted} ملف سجل "
            f"أقدم من {days} يوماً ({_human_size(files_freed)} ملفات)."
        ),
        "audit_deleted": audit_deleted,
        "files_deleted": files_deleted,
        "files_freed_bytes": files_freed,
    }


def optimize_database(app) -> dict[str, Any]:
    from extensions import db, perform_vacuum_optimize

    uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
    if "postgresql" in uri:
        perform_vacuum_optimize(app)
        try:
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("ANALYZE"))
        except Exception:
            pass
        return {"ok": True, "message": "تم تنفيذ VACUUM ANALYZE على PostgreSQL."}
    if "sqlite" in uri:
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
            conn.execute(text("ANALYZE"))
        return {"ok": True, "message": "تم تنفيذ VACUUM على SQLite."}
    return {"ok": False, "message": "نوع قاعدة البيانات غير مدعوم للتحسين التلقائي."}
