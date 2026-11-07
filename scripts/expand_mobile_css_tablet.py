"""Expand all mobile.css selectors to include tablet ui mode."""
import re
from pathlib import Path

MOBILE = 'html[data-ui-mode="mobile"]'
TABLET = 'html[data-ui-mode="tablet"]'


def expand_block(sel: str) -> str:
    sel = sel.strip()
    if MOBILE not in sel or TABLET in sel:
        return sel
    parts = re.split(r",\s*", sel)
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith(MOBILE):
            suffix = part[len(MOBILE):]
            out.append(f"{MOBILE}{suffix}")
            out.append(f"{TABLET}{suffix}")
        else:
            out.append(part)
    return ", ".join(out)


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "static" / "css" / "mobile.css"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    buf: list[str] = []
    changed = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("@") or MOBILE not in line or TABLET in line:
            if buf:
                out.extend(buf)
                buf = []
            out.append(line)
            continue

        buf.append(line)
        if "{" not in line:
            continue

        combined = "".join(buf)
        sel, brace, tail = combined.partition("{")
        expanded = expand_block(sel)
        new_line = expanded + "{" + tail
        if new_line != combined:
            changed += 1
        out.append(new_line)
        buf = []

    if buf:
        out.extend(buf)

    path.write_text("".join(out), encoding="utf-8", newline="")
    print(f"expanded {changed} selector blocks in {path}")


if __name__ == "__main__":
    main()
