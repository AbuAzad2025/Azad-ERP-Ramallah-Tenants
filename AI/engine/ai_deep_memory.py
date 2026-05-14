"""AI Deep Memory.

Persistent bounded memory stores for facts, concepts, procedures, and episodes.
Uses ai_storage so files are written atomically and tracked in the manifest.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

LONG_TERM_FILE = "deep_memory/long_term_memory.json"
SEMANTIC_FILE = "deep_memory/semantic_memory.json"
PROCEDURAL_FILE = "deep_memory/procedural_memory.json"
EPISODIC_FILE = "deep_memory/episodic_memory.json"
DEEP_MEMORY_FILES = [LONG_TERM_FILE, SEMANTIC_FILE, PROCEDURAL_FILE, EPISODIC_FILE]
MAX_MEMORY_ITEMS = 1000


class DeepMemory:
    def __init__(self):
        self.short_term_memory = {}
        self.long_term_memory = {}
        self.semantic_memory = {}
        self.procedural_memory = {}
        self.episodic_memory = []
        self._load_all_memories()

    def _load_all_memories(self):
        self.long_term_memory = read_json(LONG_TERM_FILE, {}) or {}
        self.semantic_memory = read_json(SEMANTIC_FILE, {}) or {}
        self.procedural_memory = read_json(PROCEDURAL_FILE, {}) or {}
        episodic = read_json(EPISODIC_FILE, []) or []
        self.episodic_memory = episodic[-MAX_MEMORY_ITEMS:] if isinstance(episodic, list) else []
        if not isinstance(self.long_term_memory, dict):
            self.long_term_memory = {}
        if not isinstance(self.semantic_memory, dict):
            self.semantic_memory = {}
        if not isinstance(self.procedural_memory, dict):
            self.procedural_memory = {}

    def remember_fact(self, category: str, key: str, value: Any, importance: int = 5):
        memory_id = hashlib.md5(f"{category}_{key}".encode()).hexdigest()
        memory_entry = {
            "id": memory_id,
            "category": category,
            "key": key,
            "value": value,
            "importance": int(importance or 0),
            "created_at": datetime.now().isoformat(),
            "access_count": 0,
            "last_accessed": None,
        }
        self.short_term_memory[memory_id] = memory_entry
        if len(self.short_term_memory) > MAX_MEMORY_ITEMS:
            first_key = next(iter(self.short_term_memory))
            self.short_term_memory.pop(first_key, None)
        if memory_entry["importance"] >= 7:
            self.long_term_memory[memory_id] = memory_entry
            self._save_long_term_memory()

    def remember_concept(self, concept: str, definition: str, examples: List[str] = None, related: List[str] = None):
        concept_id = hashlib.md5(str(concept).encode()).hexdigest()
        self.semantic_memory[concept_id] = {
            "concept": concept,
            "definition": definition,
            "examples": (examples or [])[:20],
            "related_concepts": (related or [])[:20],
            "created_at": datetime.now().isoformat(),
            "mastery_level": 0,
        }
        self._trim_dict(self.semantic_memory)
        self._save_semantic_memory()

    def remember_procedure(self, name: str, steps: List[str], context: Dict = None):
        proc_id = hashlib.md5(str(name).encode()).hexdigest()
        self.procedural_memory[proc_id] = {
            "name": name,
            "steps": (steps or [])[:100],
            "context": context or {},
            "times_executed": 0,
            "success_rate": 0.0,
            "created_at": datetime.now().isoformat(),
        }
        self._trim_dict(self.procedural_memory)
        self._save_procedural_memory()

    def remember_experience(self, event: str, outcome: str, lessons_learned: List[str]):
        self.episodic_memory.append(
            {"event": event, "outcome": outcome, "lessons_learned": (lessons_learned or [])[:20], "timestamp": datetime.now().isoformat()}
        )
        self.episodic_memory = self.episodic_memory[-MAX_MEMORY_ITEMS:]
        self._save_episodic_memory()

    def recall_fact(self, key: str = None, category: str = None) -> Optional[Dict]:
        for memory in {**self.long_term_memory, **self.short_term_memory}.values():
            if key and memory.get("key") == key:
                memory["access_count"] = int(memory.get("access_count", 0) or 0) + 1
                memory["last_accessed"] = datetime.now().isoformat()
                return memory
            if category and memory.get("category") == category:
                memory["access_count"] = int(memory.get("access_count", 0) or 0) + 1
                memory["last_accessed"] = datetime.now().isoformat()
                return memory
        return None

    def recall_concept(self, concept: str) -> Optional[Dict]:
        concept_lower = str(concept or "").lower()
        for data in self.semantic_memory.values():
            if concept_lower and concept_lower in str(data.get("concept", "")).lower():
                data["mastery_level"] = int(data.get("mastery_level", 0) or 0) + 1
                self._save_semantic_memory()
                return data
        return None

    def recall_procedure(self, name: str) -> Optional[Dict]:
        name_lower = str(name or "").lower()
        for proc in self.procedural_memory.values():
            if name_lower and name_lower in str(proc.get("name", "")).lower():
                proc["times_executed"] = int(proc.get("times_executed", 0) or 0) + 1
                self._save_procedural_memory()
                return proc
        return None

    def recall_similar_experiences(self, query: str, limit: int = 5) -> List[Dict]:
        query_lower = str(query or "").lower()
        if not query_lower:
            return []
        similar = [exp for exp in self.episodic_memory if query_lower in str(exp.get("event", "")).lower() or query_lower in str(exp.get("outcome", "")).lower()]
        return similar[-max(1, int(limit or 5)):]

    def consolidate_memory(self):
        consolidated = 0
        for mem_id, memory in list(self.short_term_memory.items()):
            if int(memory.get("access_count", 0) or 0) >= 3 or int(memory.get("importance", 0) or 0) >= 7:
                self.long_term_memory[mem_id] = memory
                consolidated += 1
        if consolidated > 0:
            self._trim_dict(self.long_term_memory)
            self._save_long_term_memory()
        return consolidated

    def get_memory_stats(self) -> Dict:
        return {
            "short_term": len(self.short_term_memory),
            "long_term": len(self.long_term_memory),
            "semantic": len(self.semantic_memory),
            "procedural": len(self.procedural_memory),
            "episodic": len(self.episodic_memory),
            "total": len(self.short_term_memory) + len(self.long_term_memory) + len(self.semantic_memory) + len(self.procedural_memory) + len(self.episodic_memory),
        }

    def search_all_memories(self, query: str) -> Dict[str, List]:
        query_lower = str(query or "").lower()
        results = {"facts": [], "concepts": [], "procedures": [], "experiences": []}
        if not query_lower:
            return results
        for memory in {**self.long_term_memory, **self.short_term_memory}.values():
            if query_lower in str(memory.get("value", "")).lower() or query_lower in str(memory.get("key", "")).lower():
                results["facts"].append(memory)
        for concept in self.semantic_memory.values():
            if query_lower in str(concept.get("concept", "")).lower() or query_lower in str(concept.get("definition", "")).lower():
                results["concepts"].append(concept)
        for proc in self.procedural_memory.values():
            if query_lower in str(proc.get("name", "")).lower():
                results["procedures"].append(proc)
        for exp in self.episodic_memory:
            if query_lower in str(exp.get("event", "")).lower() or query_lower in str(exp.get("outcome", "")).lower():
                results["experiences"].append(exp)
        return {key: value[:10] for key, value in results.items()}

    def _trim_dict(self, data: Dict) -> None:
        while len(data) > MAX_MEMORY_ITEMS:
            data.pop(next(iter(data)), None)

    def _save_long_term_memory(self):
        write_json(LONG_TERM_FILE, self.long_term_memory)
        sync_training_manifest(extra_files=DEEP_MEMORY_FILES)

    def _save_semantic_memory(self):
        write_json(SEMANTIC_FILE, self.semantic_memory)
        sync_training_manifest(extra_files=DEEP_MEMORY_FILES)

    def _save_procedural_memory(self):
        write_json(PROCEDURAL_FILE, self.procedural_memory)
        sync_training_manifest(extra_files=DEEP_MEMORY_FILES)

    def _save_episodic_memory(self):
        write_json(EPISODIC_FILE, self.episodic_memory[-MAX_MEMORY_ITEMS:])
        sync_training_manifest(extra_files=DEEP_MEMORY_FILES)


_deep_memory = None


def get_deep_memory():
    global _deep_memory
    if _deep_memory is None:
        _deep_memory = DeepMemory()
    return _deep_memory


__all__ = ["DeepMemory", "get_deep_memory"]
