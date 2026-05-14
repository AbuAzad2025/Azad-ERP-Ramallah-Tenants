"""AI Book Reader.

Reads markdown/PDF files from AI/data/books only, indexes compact metadata, and
keeps full text in a local content file. Paths are constrained to avoid arbitrary
file reads.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from AI.engine.ai_storage import data_path, read_json, sync_training_manifest, write_json

BOOKS_DIR = data_path("books")
BOOK_INDEX_FILE = "books/book_index.json"
MAX_FULL_TEXT_CHARS = 2_000_000


class BookReader:
    def __init__(self):
        self.books_dir = BOOKS_DIR
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.memorized_books = {}
        self.book_index = {}
        self._load_index()

    def _safe_book_path(self, file_path: str) -> Optional[Path]:
        try:
            candidate = Path(file_path)
            if not candidate.is_absolute():
                candidate = self.books_dir / candidate
            resolved = candidate.resolve()
            base = self.books_dir.resolve()
            if base not in resolved.parents and resolved != base:
                return None
            return resolved
        except Exception:
            return None

    def _load_index(self):
        data = read_json(BOOK_INDEX_FILE, {})
        self.book_index = data if isinstance(data, dict) else {}

    def _save_index(self):
        write_json(BOOK_INDEX_FILE, self.book_index)
        sync_training_manifest(extra_files=[BOOK_INDEX_FILE])

    def read_markdown_book(self, file_path: str) -> Dict[str, Any]:
        path = self._safe_book_path(file_path)
        if not path or not path.exists() or path.suffix.lower() not in {".md", ".markdown", ".txt"}:
            return {"success": False, "error": "File not found or not allowed"}

        try:
            content = path.read_text(encoding="utf-8")[:MAX_FULL_TEXT_CHARS]
            book_data = {
                "title": path.stem,
                "file": str(path.relative_to(self.books_dir)),
                "format": "markdown",
                "read_date": datetime.now().isoformat(),
                "size": len(content),
                "chapters": [],
                "sections": [],
                "headings": [],
                "content_full": content,
                "key_concepts": [],
            }

            current_chapter = None
            current_section = None
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    current_chapter = {"level": 1, "title": title, "content": []}
                    book_data["chapters"].append(current_chapter)
                    book_data["headings"].append({"level": 1, "text": title})
                elif line.startswith("## "):
                    title = line[3:].strip()
                    current_section = {"level": 2, "title": title, "content": []}
                    book_data["sections"].append(current_section)
                    book_data["headings"].append({"level": 2, "text": title})
                    if current_chapter:
                        current_chapter["content"].append(current_section)
                elif line.startswith("### "):
                    book_data["headings"].append({"level": 3, "text": line[4:].strip()})
                elif current_section:
                    current_section["content"].append(line)
                elif current_chapter:
                    current_chapter["content"].append(line)

            book_data["code_examples_count"] = len(re.findall(r"```[\s\S]*?```", content))
            for pattern in (r"\*\*(.+?)\*\*", r"__(.+?)__", r"> (.+)", r"- (.+)"):
                book_data["key_concepts"].extend(re.findall(pattern, content)[:50])
            book_data["key_concepts"] = book_data["key_concepts"][:150]

            return self._store_book(book_data)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def read_pdf_book(self, file_path: str) -> Dict[str, Any]:
        path = self._safe_book_path(file_path)
        if not path or not path.exists() or path.suffix.lower() != ".pdf":
            return {"success": False, "error": "File not found or not allowed"}

        try:
            try:
                import PyPDF2
            except ImportError:
                return {"success": False, "error": "PyPDF2 not installed. Install with: pip install PyPDF2"}

            book_data = {
                "title": path.stem,
                "file": str(path.relative_to(self.books_dir)),
                "format": "pdf",
                "read_date": datetime.now().isoformat(),
                "pages": [],
                "total_pages": 0,
                "content_full": "",
                "key_terms": [],
            }

            with path.open("rb") as f:
                pdf_reader = PyPDF2.PdfReader(f)
                book_data["total_pages"] = len(pdf_reader.pages)
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = (page.extract_text() or "")[:100_000]
                    book_data["pages"].append({"page_number": page_num, "content": text, "word_count": len(text.split())})
                    if len(book_data["content_full"]) < MAX_FULL_TEXT_CHARS:
                        book_data["content_full"] += text + "\n"

            word_freq = {}
            for word in book_data["content_full"].split():
                clean_word = re.sub(r"[^\w\u0600-\u06FF]", "", word).lower()
                if len(clean_word) > 3:
                    word_freq[clean_word] = word_freq.get(clean_word, 0) + 1
            book_data["key_terms"] = [word for word, _ in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:100]]

            return self._store_book(book_data)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _store_book(self, book_data: Dict[str, Any]) -> Dict[str, Any]:
        book_id = f"book_{re.sub(r'[^a-zA-Z0-9_\u0600-\u06FF-]', '_', book_data['title'])}"
        self.memorized_books[book_id] = book_data
        self.book_index[book_id] = {
            "title": book_data["title"],
            "file": book_data["file"],
            "format": book_data["format"],
            "chapters_count": len(book_data.get("chapters", [])),
            "sections_count": len(book_data.get("sections", [])),
            "pages": book_data.get("total_pages", 0),
            "size": book_data.get("size", len(book_data.get("content_full", ""))),
            "read_date": book_data["read_date"],
        }
        self._save_index()
        self._save_book_memory(book_id, book_data)
        return {
            "success": True,
            "book_id": book_id,
            "title": book_data["title"],
            "chapters": len(book_data.get("chapters", [])),
            "sections": len(book_data.get("sections", [])),
            "pages": book_data.get("total_pages", 0),
            "key_concepts": len(book_data.get("key_concepts", [])),
            "key_terms": len(book_data.get("key_terms", [])),
        }

    def _save_book_memory(self, book_id: str, book_data: Dict):
        memory_data = {k: v for k, v in book_data.items() if k != "content_full"}
        write_json(f"books/{book_id}_memory.json", memory_data)
        content_file = self.books_dir / f"{book_id}_content.txt"
        content_file.write_text(book_data.get("content_full", ""), encoding="utf-8")
        sync_training_manifest(extra_files=[f"books/{book_id}_memory.json", f"books/{book_id}_content.txt"])

    def search_in_books(self, query: str) -> List[Dict]:
        results = []
        query_lower = str(query or "").lower().strip()
        if not query_lower:
            return results

        for book_id, book_info in self.book_index.items():
            content_file = self.books_dir / f"{book_id}_content.txt"
            if content_file.exists():
                try:
                    content = content_file.read_text(encoding="utf-8")
                    if query_lower in content.lower():
                        matching_lines = [line for line in content.split("\n") if query_lower in line.lower()][:10]
                        results.append({"book_id": book_id, "book_title": book_info.get("title", book_id), "matches_count": len(matching_lines), "sample_matches": matching_lines[:5]})
                except Exception:
                    pass
        return results

    def answer_from_books(self, question: str) -> Optional[str]:
        search_results = self.search_in_books(question)
        if not search_results:
            return None
        answer_parts = [f"من الكتب المحفوظة ({len(search_results)} مصدر):\n"]
        for result in search_results[:3]:
            answer_parts.append(f"\n📖 {result['book_title']}:")
            for match in result["sample_matches"][:3]:
                clean_match = match.strip()
                if clean_match:
                    answer_parts.append(f"  - {clean_match}")
        return "\n".join(answer_parts)

    def get_books_summary(self) -> Dict:
        return {
            "total_books": len(self.book_index),
            "formats": {
                "markdown": sum(1 for b in self.book_index.values() if b.get("format") == "markdown"),
                "pdf": sum(1 for b in self.book_index.values() if b.get("format") == "pdf"),
            },
            "books": list(self.book_index.values()),
        }


_book_reader = None


def get_book_reader():
    global _book_reader
    if _book_reader is None:
        _book_reader = BookReader()
    return _book_reader


__all__ = ["BookReader", "get_book_reader"]
