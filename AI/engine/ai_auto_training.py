"""AI auto-training trigger.

Keeps automatic training safe and lightweight. It checks whether training is due,
but can be disabled in production with AI_AUTO_TRAINING_ENABLED=false.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

AUTO_TRAINING_LOG = "ai_auto_training.json"
FILES_TO_CHECK = ("models.py", "routes", "templates", "forms.py")
AUTO_TRAINING_INTERVAL_HOURS = 48


def _auto_training_enabled() -> bool:
    return os.environ.get("AI_AUTO_TRAINING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _latest_project_mtime() -> float:
    current_mtime = 0.0
    for file_path in FILES_TO_CHECK:
        path = Path(file_path)
        if not path.exists():
            continue
        if path.is_file():
            current_mtime = max(current_mtime, path.stat().st_mtime)
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.is_file() and item.suffix in {".py", ".html", ".js", ".css"}:
                    current_mtime = max(current_mtime, item.stat().st_mtime)
    return current_mtime


def should_auto_train():
    if not _auto_training_enabled():
        return False
    try:
        log = read_json(AUTO_TRAINING_LOG, None)
        if not isinstance(log, dict):
            return True

        last_training = log.get("last_training")
        if not last_training:
            return True

        last_dt = datetime.fromisoformat(str(last_training))
        hours_passed = (datetime.now() - last_dt).total_seconds() / 3600
        if hours_passed > AUTO_TRAINING_INTERVAL_HOURS:
            return True

        current_mtime = _latest_project_mtime()
        last_checked_mtime = float(log.get("last_files_mtime", 0) or 0)
        return current_mtime > last_checked_mtime
    except Exception:
        return False


def execute_silent_training():
    """Run silent training and rebuild AI maps."""
    if not _auto_training_enabled():
        return False
    try:
        from AI.engine.ai_knowledge import get_knowledge_base
        from AI.engine.ai_auto_discovery import build_system_map
        from AI.engine.ai_data_awareness import build_data_schema

        kb = get_knowledge_base()
        kb.index_all_files(force_reindex=True)
        build_system_map()
        build_data_schema()
        log_auto_training()
        sync_training_manifest(extra_files=[AUTO_TRAINING_LOG])
        return True
    except Exception:
        return False


def log_auto_training():
    try:
        old_log = read_json(AUTO_TRAINING_LOG, {})
        if not isinstance(old_log, dict):
            old_log = {}
        log_entry = {
            "last_training": datetime.now().isoformat(),
            "last_files_mtime": _latest_project_mtime(),
            "auto_trainings_count": int(old_log.get("auto_trainings_count", 0) or 0) + 1,
        }
        write_json(AUTO_TRAINING_LOG, log_entry)
        sync_training_manifest(extra_files=[AUTO_TRAINING_LOG])
    except Exception:
        pass


def init_auto_training():
    """Initialize auto-training if enabled and due."""
    try:
        if should_auto_train():
            execute_silent_training()
    except Exception:
        pass


if __name__ == "__main__":
    if should_auto_train():
        execute_silent_training()


__all__ = ["should_auto_train", "execute_silent_training", "log_auto_training", "init_auto_training"]
