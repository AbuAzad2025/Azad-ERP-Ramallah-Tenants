#!/usr/bin/env python3
"""إصلاح مسارات مطلقة شائعة في قوالب التينانت (سكربتات inline)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

SKIP_DIRS = {
    "templates/security",
    "templates/advanced",
    "templates/ai",
    "templates/ai_admin",
}

GM_WRAP = '(window.gmPath||window.gmU||function(p){return p;})'

REPLACEMENTS = [
    # window.location.href = `/path` or '/path'
    (
        re.compile(
            r"window\.location\.href\s*=\s*`(/(?!static)[^`]+)`",
            re.I,
        ),
        lambda m: f"window.location.href = {GM_WRAP}(`{m.group(1)}`)",
    ),
    (
        re.compile(
            r"""window\.location\.href\s*=\s*'(/(?!static)[^']+)'""",
            re.I,
        ),
        lambda m: f"window.location.href = {GM_WRAP}('{m.group(1)}')",
    ),
    (
        re.compile(
            r'window\.location\.href\s*=\s*"(/(?!static)[^"]+)"',
            re.I,
        ),
        lambda m: f'window.location.href = {GM_WRAP}("{m.group(1)}")',
    ),
    # var url = '/path'
    (
        re.compile(
            r"""var\s+url\s*=\s*'(/(?!static)[^']+)'(\s*\+)""",
            re.I,
        ),
        lambda m: f"var url = {GM_WRAP}('{m.group(1)}'){m.group(2)}",
    ),
    (
        re.compile(
            r"""var\s+url\s*=\s*`(/(?!static)[^`]+)`""",
            re.I,
        ),
        lambda m: f"var url = {GM_WRAP}(`{m.group(1)}`)",
    ),
    # .action = `/path`
    (
        re.compile(
            r"""\.action\s*=\s*`(/(?!static)[^`]+)`""",
            re.I,
        ),
        lambda m: f".action = {GM_WRAP}(`{m.group(1)}`)",
    ),
    # url: '/path' in ajax objects (not url_for)
    (
        re.compile(
            r"""url:\s*'(/(?!static)[^']+)'""",
            re.I,
        ),
        lambda m: f"url: {GM_WRAP}('{m.group(1)}')",
    ),
    (
        re.compile(
            r"""url:\s*`(/(?!static)[^`]+)`""",
            re.I,
        ),
        lambda m: f"url: {GM_WRAP}(`{m.group(1)}`)",
    ),
]


def should_skip(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(s.startswith(str(ROOT / d).replace("\\", "/")) for d in SKIP_DIRS)


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    orig = text
    if "gmPath(" in text and "GM_WRAP" in text:
        return False
    for rx, repl in REPLACEMENTS:
        text = rx.sub(repl, text)
    if text == orig:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    changed = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        if should_skip(path):
            continue
        if fix_file(path):
            changed.append(path.relative_to(ROOT))
    print(f"Fixed {len(changed)} template files")
    for p in changed[:60]:
        print(f"  {p}")
    if len(changed) > 60:
        print(f"  ... +{len(changed) - 60} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
