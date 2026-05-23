#!/usr/bin/env python3
"""استبدال رسائل flash المتكررة بـ utils.flash_* في routes/."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "routes"

EMOJI_DANGER = re.compile(
    r"""flash\(\s*["']❌\s*([^"']+)["']\s*,\s*["'](?:danger|warning)["']\s*\)"""
)
EMOJI_SUCCESS = re.compile(
    r"""flash\(\s*["']✅\s*([^"']+)["']\s*,\s*["'](?:success|info)["']\s*\)"""
)
EMOJI_WARN = re.compile(
    r"""flash\(\s*["']⚠️\s*([^"']+)["']\s*,\s*["'](?:warning|info)["']\s*\)"""
)

# f-strings وبادئات إيموجي متنوعة
_PREFIX_REPLACEMENTS = [
    ("flash(f'✅ ", "utils.flash_success(f'"),
    ('flash(f"✅ ', 'utils.flash_success(f"'),
    ("flash(f'❌ ", "utils.flash_error(f'"),
    ('flash(f"❌ ', 'utils.flash_error(f"'),
    ("flash(f'⚠️ ", "utils.flash_warning(f'"),
    ("flash('✅ ", "utils.flash_success('"),
    ('flash("✅ ', 'utils.flash_success("'),
    ("flash('❌ ", "utils.flash_error('"),
    ('flash("❌ ', 'utils.flash_error("'),
    ("flash('⚠️ ", "utils.flash_warning('"),
    ("flash('⛔ ", "utils.flash_error('"),
    ('flash("⛔ ', 'utils.flash_error("'),
    ("flash(f'⚠️ ", "utils.flash_warning(f'"),
    ("flash('ℹ️ ", "utils.flash_info('"),
]

JSON_ERROR_OLD = "حدث خطأ داخلي"
JSON_ERROR_NEW = "تعذر تنفيذ العملية. حاول مرة أخرى."

REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"""flash\(\s*["']❌\s*حدث خطأ داخلي["']\s*,\s*["']danger["']\s*\)"""), "utils.flash_error()"),
    (re.compile(r"""flash\(\s*["']حدث خطأ داخلي["']\s*,\s*["'](?:danger|error)["']\s*\)"""), "utils.flash_error()"),
    (re.compile(r"""flash\(\s*["']حدث خطأ أثناء الحفظ\.?["']\s*,\s*["']danger["']\s*\)"""), "utils.flash_error(utils.MSG_SAVE_FAILED)"),
    (re.compile(r"""flash\(\s*["']حدث خطأ أثناء الحفظ["']\s*,\s*["']danger["']\s*\)"""), "utils.flash_error(utils.MSG_SAVE_FAILED)"),
    (re.compile(r"""flash\(\s*["']❌\s*حدث خطأ أثناء التنظيف["']\s*,\s*["']danger["']\s*\)"""), 'utils.flash_error("تعذر التنظيف. راجع السجل.")'),
    (re.compile(r"""flash\(\s*["']✅\s*تم تسجيل الدفعة["']\s*,\s*["']success["']\s*\)"""), 'utils.flash_success("تم تسجيل الدفعة.")'),
    (re.compile(r"""flash\(\s*["']✅\s*تم تسجيل دفع المصروف بنجاح["']\s*,\s*["']success["']\s*\)"""), 'utils.flash_success("تم تسجيل دفع المصروف.")'),
]

ERROR_CATEGORY = re.compile(
    r"""flash\(([^,]+),\s*["']error["']\)""",
)

IMPORT_UTILS = "import utils"


def _ensure_utils_import(text: str) -> str:
    if "import utils" in text or "from utils import" in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            insert_at = i + 1
    lines.insert(insert_at, IMPORT_UTILS)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def migrate_file(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    text = original
    count = 0

    for pat, repl in REPLACEMENTS:
        text, n = pat.subn(repl, text)
        count += n

    def _error_repl(m: re.Match) -> str:
        msg = m.group(1).strip()
        if msg in ('"حدث خطأ داخلي"', "'حدث خطأ داخلي'"):
            return "utils.flash_error()"
        return f"utils.flash_error({msg})"

    text, n2 = ERROR_CATEGORY.subn(_error_repl, text)
    count += n2

    def _ed(m: re.Match) -> str:
        return f'utils.flash_error("{m.group(1).strip()}")'

    def _es(m: re.Match) -> str:
        return f'utils.flash_success("{m.group(1).strip()}")'

    def _ew(m: re.Match) -> str:
        return f'utils.flash_warning("{m.group(1).strip()}")'

    text, n3 = EMOJI_DANGER.subn(_ed, text)
    count += n3
    text, n4 = EMOJI_SUCCESS.subn(_es, text)
    count += n4
    text, n5 = EMOJI_WARN.subn(_ew, text)
    count += n5

    for old, new in _PREFIX_REPLACEMENTS:
        c = text.count(old)
        if c:
            text = text.replace(old, new)
            count += c

    if JSON_ERROR_OLD in text:
        c = text.count(JSON_ERROR_OLD)
        text = text.replace(JSON_ERROR_OLD, JSON_ERROR_NEW)
        count += c

    if text != original:
        text = _ensure_utils_import(text)
        path.write_text(text, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    for path in sorted(ROUTES.glob("*.py")):
        n = migrate_file(path)
        if n:
            print(f"  {path.name}: {n}")
            total += n
    print(f"Done — {total} replacement(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
