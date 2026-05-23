#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""استبدال عميل/عملاء → زبون/زبائن في ملفات الواجهة."""
from __future__ import annotations

import os
import sys

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, basedir)
os.chdir(basedir)

from utils.arabic_ux import CUSTOMER_TERM_REPLACEMENTS  # noqa: E402

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "instance",
    "migrations",
    "static/adminlte",
    ".cursor",
}
SKIP_FILES = {"apply_zboon_terminology.py", "arabic_ux.py"}
EXTENSIONS = {".html", ".py", ".js", ".md", ".json"}

# ملفات JS التطبيق فقط (لا مكتبات)
JS_ALLOW_PREFIX = ("static/js/", "static/datatables/")


def should_process(path: str) -> bool:
    rel = path.replace("\\", "/")
    parts = rel.split("/")
    for skip in SKIP_DIRS:
        if skip in parts:
            return False
    if os.path.basename(path) in SKIP_FILES:
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTENSIONS:
        return False
    if ext == ".js" and not rel.startswith(JS_ALLOW_PREFIX):
        return False
    if ext == ".json" and "Arabic.json" not in rel:
        return False
    return True


def apply_text(text: str) -> tuple[str, int]:
    n = 0
    for old, new in CUSTOMER_TERM_REPLACEMENTS:
        if old in text:
            count = text.count(old)
            text = text.replace(old, new)
            n += count
    return text, n


def main():
    total_files = 0
    total_repl = 0
    for root, dirs, files in os.walk(basedir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, basedir)
            if not should_process(rel):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    original = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            updated, n = apply_text(original)
            if n > 0 and updated != original:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(updated)
                total_files += 1
                total_repl += n
                print(f"  {rel}: {n}")
    print(f"Done: {total_files} files, {total_repl} replacements")


if __name__ == "__main__":
    main()
