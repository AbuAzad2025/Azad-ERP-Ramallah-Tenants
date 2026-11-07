"""Expand mobile.css selectors to include tablet ui mode."""
import re
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "static" / "css" / "mobile.css"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out = []
changed = 0

for line in lines:
    if 'html[data-ui-mode="mobile"]' not in line or 'html[data-ui-mode="tablet"]' in line:
        out.append(line)
        continue

    stripped = line.rstrip("\n")
    m = re.match(r"^(\s*)(.+?)\s*\{(.*)$", stripped)
    if not m:
        out.append(line)
        continue

    indent, sel, tail = m.groups()
    sel = sel.strip()
    if sel == 'html[data-ui-mode="mobile"]':
        new = f'{indent}html[data-ui-mode="mobile"], html[data-ui-mode="tablet"] {{{tail}\n'
    elif sel.startswith('html[data-ui-mode="mobile"]'):
        suffix = sel[len('html[data-ui-mode="mobile"]'):]
        new = (
            f'{indent}html[data-ui-mode="mobile"]{suffix}, '
            f'html[data-ui-mode="tablet"]{suffix} {{{tail}\n'
        )
    else:
        out.append(line)
        continue

    if new != line:
        changed += 1
    out.append(new)

path.write_text("".join(out), encoding="utf-8", newline="")
print(f"expanded {changed} selectors in {path}")
