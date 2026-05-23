#!/usr/bin/env python3
"""تقييد قواعد CSS القديمة حتى لا تتعارض مع body.gm-pro-ui"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_security_dark_mode():
    p = ROOT / "static/css/security_dark_mode.css"
    text = p.read_text(encoding="utf-8")
    if ":not(.gm-pro-ui)" in text and "body.dark-mode:not(.gm-pro-ui)" in text:
        print("security_dark_mode: already scoped")
        return
    text = text.replace("body.dark-mode", "body.dark-mode:not(.gm-pro-ui)")
    header = (
        "/* Scoped: لا يُطبَّق على gm-pro-ui — الثيم من gm-design-system */\n"
    )
    if not text.startswith("/* Scoped"):
        text = header + text
    p.write_text(text, encoding="utf-8")
    print("security_dark_mode: scoped")


def patch_ux_unified():
    p = ROOT / "static/css/ux-unified.css"
    text = p.read_text(encoding="utf-8")
    if "body:not(.gm-pro-ui)" in text:
        print("ux-unified: already scoped")
        return
    prefixes = (
        ".form-control",
        ".custom-select",
        "select.form-control",
        ".form-label",
        "label.col-form-label",
        ".form-text",
        "small.text-muted",
        ".btn",
        ".btn-group",
        ".input-group",
        ".btn-primary",
        ".btn-secondary",
        ".btn-outline-secondary",
        ".btn-sm",
        ".select2-container",
        ".table thead",
        ".table td",
        ".card-header .btn",
        ".page-actions",
        ".filter-toolbar",
    )

    lines = text.splitlines()
    out = []
    in_media = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("@media"):
            in_media = True
            out.append(line)
            continue
        if in_media and stripped == "}" and not stripped.startswith("."):
            in_media = False
        if (
            not stripped
            or stripped.startswith("/*")
            or stripped.startswith(":root")
            or stripped.startswith("@")
            or in_media
            or "body:not(.gm-pro-ui)" in line
        ):
            out.append(line)
            continue
        new_line = line
        for pref in prefixes:
            if stripped.startswith(pref) or stripped.startswith(pref + ":"):
                indent = line[: len(line) - len(line.lstrip())]
                rest = line.lstrip()
                if not rest.startswith("body:not(.gm-pro-ui)"):
                    new_line = f"{indent}body:not(.gm-pro-ui) {rest}"
                break
        out.append(new_line)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("ux-unified: scoped")


def patch_enhancements():
    p = ROOT / "static/css/enhancements.css"
    text = p.read_text(encoding="utf-8")
    replacements = [
        ("body:not(.dark-mode) {", "body:not(.gm-pro-ui):not(.dark-mode) {"),
        ("body:not(.dark-mode) .", "body:not(.gm-pro-ui):not(.dark-mode) ."),
        ("body.dark-mode {", "body.dark-mode:not(.gm-pro-ui) {"),
        ("body.dark-mode .", "body.dark-mode:not(.gm-pro-ui) ."),
        (".btn-primary { background:", "body:not(.gm-pro-ui) .btn-primary { background:"),
        (".btn-success { background:", "body:not(.gm-pro-ui) .btn-success { background:"),
        (".btn-danger  { background:", "body:not(.gm-pro-ui) .btn-danger  { background:"),
        (".btn-warning { background:", "body:not(.gm-pro-ui) .btn-warning { background:"),
        (".btn-info    { background:", "body:not(.gm-pro-ui) .btn-info    { background:"),
    ]
    for old, new in replacements:
        if old in text and new not in text:
            text = text.replace(old, new)
    if "body:not(.gm-pro-ui) .form-control {" not in text:
        text = text.replace(
            "/* ═══ 8. Inputs & Forms (General) ═══ */\n.form-control {",
            "/* ═══ 8. Inputs & Forms (General) — legacy pages only ═══ */\n"
            "body:not(.gm-pro-ui) .form-control {",
        )
    note = "/* gm-pro-ui pages use gm-design-system + gm-spacing-dropdowns */\n"
    if note not in text:
        text = note + text
    p.write_text(text, encoding="utf-8")
    print("enhancements: scoped")


if __name__ == "__main__":
    patch_security_dark_mode()
    patch_ux_unified()
    patch_enhancements()
