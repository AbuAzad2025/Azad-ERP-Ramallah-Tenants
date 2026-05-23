# ترتيب CSS/JS للواجهة — منع التعارض

## ترتيب تحميل CSS (`templates/base.html`)

| الطبقة | الملف | الدور |
|--------|------|--------|
| 1 | AdminLTE + FontAwesome + Select2 | إطار Bootstrap/AdminLTE |
| 2 | `ui.css`, `style.css` | تخطيط RTL، شريط جانبي |
| 3 | `mobile*.css`, `tenant-scope`, `gm-financial-*` | متجاوب / نطاق تينانت |
| 4 | `numbers-fix`, `bs5-utils` | أرقام ومساعدات BS |
| 5 | `ux-unified`, `ux-contrast` | **قديم** — مُقيَّد بـ `:not(.gm-pro-ui)` |
| 6 | `enhancements.css` | **قديم** — تدرجات أزرار — مُقيَّد |
| 7 | `security_dark_mode.css` | **قديم** — ليلي — `body.dark-mode:not(.gm-pro-ui)` |
| 8 | `gm-theme-tokens.css` | **Tokens** — فلسطيني/خليجي × فاتح/ليلي |
| 9 | `gm-design-system.css` | مكوّنات ERP (بدون ألوان مكررة) |
| 10 | `gm-spacing-dropdowns.css` | تباعد، قوائم، جداول |
| 11 | `gm-security-console.css` | لوحة `/security/` |
| 12 | `gm-theme-components.css` | محاذاة مركزية، فوتر، أنماط |
| 13 | `gm-conflict-guard.css` | **الأخير** — يلغي بقايا التعارض |
| 12 | `print.css` | طباعة فقط |

`{% block styles %}` في القوالب الفرعية يأتي **بعد** الطبقة 12 تقريبًا (قبل `enhancements` القديم الذي أُزيل من أسفل الرأس).

## صنف الجسم

- `body.gm-pro-ui` — كل الصفحات من `base.html`
- `body.security-console.sidebar-hidden` — كونسول المالك `/security/`

## JavaScript للثيم

- **`gm-theme.js`** — `toggleDarkMode()` + `gmToggleVariant()` (فلسطيني ↔ خليجي)
- `localStorage.gmTheme` = `light` | `dark`
- `localStorage.gmVariant` = `palestinian` | `gulf`
- المواصفة الكاملة: `docs/arabic_erp_theme_system.json`
- **`security_dark_mode.js`** — لا يعمل إن وُجد `__GM_THEME_INIT__` (لا يُحمَّل حاليًا من base)

## قواعد للمطورين

1. لا تضف `!important` في قوالب inline إلا للضرورة.
2. تنسيق جديد → `gm-design-system.css` أو `gm-spacing-dropdowns.css`، وليس `enhancements.css`.
3. صفحة فرعية خاصة → ملف `static/css/module.css` + ربط في `{% block styles %}` فقط.
4. بعد تعديل CSS قديم شغّل: `python scripts/scope_legacy_css_for_gm.py`

## مراجع المواصفات

- `docs/arabic_erp_ui_spacing_dropdowns_spec.json`
- `docs/arabic_erp_ui_assistant_spec.json` (إن وُجد)
