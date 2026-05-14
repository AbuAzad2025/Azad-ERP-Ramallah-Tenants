"""Shared storage helpers for AI runtime data.

All generated AI JSON/JSONL files should go through this module. It gives the
AI layer one consistent place for paths, atomic JSON writes, bounded logs, and a
small manifest that describes the state of training/discovery files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

AI_DATA_DIR = os.environ.get("AI_DATA_DIR", "AI/data")
TRAINING_MANIFEST_FILE = "ai_training_manifest.json"

KNOWN_AI_DATA_FILES = (
    "api_keys.enc.json",
    "training_jobs.json",
    "model_training_status.json",
    "ai_training_manifest.json",
    "ai_training_policy.json",
    "ai_self_audit.json",
    "ai_interactions.json",
    "conversations.json",
    "ai_learning_log.json",
    "ai_discovery_log.json",
    "ai_data_schema.json",
    "ai_system_map.json",
    "ai_knowledge_cache.json",
    "ai_local_mode_log.json",
    "ai_security_events.jsonl",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_data_dir() -> Path:
    path = Path(AI_DATA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_path(filename: str | Path) -> Path:
    raw = Path(filename)
    if raw.is_absolute():
        return raw
    normalized = str(raw).replace("\\", "/")
    default_prefix = "AI/data/"
    configured_prefix = str(Path(AI_DATA_DIR)).replace("\\", "/").rstrip("/") + "/"
    if normalized.startswith(default_prefix) or normalized.startswith(configured_prefix):
        return raw
    return ensure_data_dir() / raw


def read_json(filename: str | Path, default: Any = None) -> Any:
    path = data_path(filename)
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(filename: str | Path, data: Any) -> None:
    path = data_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def append_json_list(filename: str | Path, item: Any, max_items: int = 200) -> List[Any]:
    items = read_json(filename, [])
    if not isinstance(items, list):
        items = []
    items.append(item)
    if max_items and len(items) > max_items:
        items = items[-max_items:]
    write_json(filename, items)
    return items


def append_jsonl(filename: str | Path, item: Any) -> None:
    path = data_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def file_metadata(filename: str | Path) -> Dict[str, Any]:
    path = data_path(filename)
    if not path.exists():
        return {"file": path.name, "exists": False}
    stat = path.stat()
    return {
        "file": path.name,
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def build_training_manifest(extra_files: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    files = list(KNOWN_AI_DATA_FILES)
    if extra_files:
        for filename in extra_files:
            if filename not in files:
                files.append(filename)

    manifest = {
        "generated_at": utc_now(),
        "data_dir": str(ensure_data_dir()),
        "files": {name: file_metadata(name) for name in files},
        "summary": {
            "known_files": len(files),
            "existing_files": 0,
            "missing_files": 0,
            "total_size_bytes": 0,
        },
    }
    existing = [meta for meta in manifest["files"].values() if meta.get("exists")]
    manifest["summary"]["existing_files"] = len(existing)
    manifest["summary"]["missing_files"] = len(files) - len(existing)
    manifest["summary"]["total_size_bytes"] = sum(int(meta.get("size_bytes", 0) or 0) for meta in existing)
    return manifest


def sync_training_manifest(extra_files: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    manifest = build_training_manifest(extra_files=extra_files)
    write_json(TRAINING_MANIFEST_FILE, manifest)
    return manifest


__all__ = [
    "AI_DATA_DIR",
    "TRAINING_MANIFEST_FILE",
    "KNOWN_AI_DATA_FILES",
    "utc_now",
    "ensure_data_dir",
    "data_path",
    "read_json",
    "write_json",
    "append_json_list",
    "append_jsonl",
    "file_metadata",
    "build_training_manifest",
    "sync_training_manifest",
]
