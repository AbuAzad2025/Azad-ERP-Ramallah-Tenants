# نظام الثيم — Arabic ERP Theme System

## المصدر الوحيد للألوان

- **JSON:** `docs/arabic_erp_theme_system.json`
- **Tokens + مكوّنات:** `static/css/erp-theme/index.css`
- **بطاقات KPI (طبقة واحدة):** `static/css/erp-theme/kpi-cards-global.css`
- **JS:** `static/js/erp-theme.js`

---

## ترتيب التحميل (بدون تكدس)

### صفحات التطبيق (`base.html`)

| # | ملف | دور |
|---|-----|-----|
| 1 | AdminLTE + Bootstrap + Select2 | هيكل فقط |
| 2 | `ui.css` | تخطيط sidebar، `card-header-blue` (يُلغى لاحقاً بثيم) |
| 3 | `mobile.css`, `mobile-app.css`, `gm-*` | جداول/موبايل فقط |
| 4 | `numbers-fix`, `bs5-utils`, `tenant-scope`, `ux-messages` | مساعدات |
| 5 | **`erp-theme/index.css`** | tokens, components, layouts, pages-financial, pages-dashboard |
| 6 | `{% block styles %}` / `{% block extra_head %}` | **CSS صفحة** مثل `service.css`, `sales.css`, `reporting.css` |
| 7 | **`kpi-cards-global.css`** (آخر `<head>`) | **يفرض ألوان البطاقات من الثيم** — يتجاوز تعارض (6) |

> القاعدة: لا تضع ألوان `!important` لـ `.small-box` / `.erp-kpi-card` / `.summary-card` في CSS الصفحة. استخدم الثيم أو عدّل `kpi-cards-global.css` فقط.

### صفحات عامة (`erp_public.html`)

نفس (1–5) عبر `erp_head_assets`، ثم `{% block head %}`، ثم **`kpi-cards-global.css`** مرة واحدة.

---

## ملفات **لا** تُحمَّل (تجنّب إعادة إضافتها)

`style.css`, `enhancements.css`, `ux-unified.css`, `ux-contrast.css`, **`erp-arabic-ui.css`**, `erp-forms-spacing.css`, `erp-conflict-fixes.css`, `erp-content-migrated.css`

> `erp-arabic-ui.css` ما زال على القرص لكنه **غير مربوط** — قواعد KPI فيه legacy ومكررة.

---

## من يملك ماذا؟ (لا تكرار)

| المكوّن | الملف الوحيد |
|---------|----------------|
| `--erp-primary`, variants | `tokens.css` |
| `.card`, `.form-control`, أزرار | `components.css` |
| جداول مالية، `erp-kpi-row` | `pages-financial.css` |
| تنبيهات الداشبورد | `pages-dashboard.css` |
| `erp-kpi-card`, `small-box`, `summary-card`, `info-box`, رؤوس ثيم، `erp-chart-host` | **`kpi-cards-global.css`** |

---

## تعارضات معروفة ومُعالجة

| ملف صفحة | الخطر | الحل |
|----------|--------|-----|
| `service.css` | ألوان `small-box` ثابتة | عُدّلت لـ `var(--erp-*)` + الطبقة الأخيرة تفوز |
| `ui.css` | `card-header-blue` hex | `kpi-cards-global` + `!important` على `body.erp-app` |
| `reporting.css` | hover على summary فقط | لا تعارض لون |
| AdminLTE | `small-box` افتراضي | مُغطى بـ `body.erp-app .small-box.bg-*` |

---

## عند إضافة CSS جديد

1. **لا** تكرار قواعد KPI في ملف صفحة — عدّل `kpi-cards-global.css`.
2. **لا** `!important` على `.card` عامة بعد الطبقة (7).
3. صفحات خاصة: تخطيط فقط (مسافات، جداول)، ليس ألوان البطاقات.
4. دفعات قوالب: تعديل القوالب مباشرة أو عبر `kpi-cards-global.css` — لا سكربت دفعي في `scripts/`.

---

## موبايل / تابلت (`data-ui-mode`)

| ملف | متى يُحمَّل | دور |
|-----|-------------|-----|
| `mobile.css` | عرض ≤991px أو وضع mobile/tablet | شريط، سايدبار، جداول، `gm-action-tile` |
| `mobile-app.css` | نفس الشرط + `body.gm-compact-app` | بطاقات قوائم، فلاتر — **لا يُسطّح** `erp-kpi-card` بعد التحديث |
| `kpi-cards-global.css` | آخر `<head>` | قواعد `html[data-ui-mode="mobile\|tablet"]` بأولوية أعلى |
| `layout-app.css` (ضمن erp-theme) | مع الحزمة | نافبار، سايدبار RTL، overlay موبايل (`sidebar-open`, `#gm-sidebar-backdrop`) |
| `erp-navbar.js` | بعد `layout-responsive.js` | زر القائمة `data-erp-pushmenu`، أسعار `/api/exchange-rates` — **ليس** `data-widget="pushmenu"` |

- `mobile-app.js` يضيف `gm-compact-app` على `<body>` تلقائياً.
- متغيرات `--gm-app-*` مربوطة بـ `--erp-*` (نفس الثيم).
- `charts.js`: ارتفاع أصغر + وسيلة إيضاح أسفل على الموبايل (`isCompact`).

---

## JavaScript

- `charts.js` — ألوان من `--erp-*`، `ensureChartHost()`، `erp-theme-change`
- `erp-navbar.js` — `data-erp-pushmenu`، drawer موبايل، `/api/exchange-rates` (بعد `layout-responsive.js`)
- `safe-enhancements.js` — لا يغيّر ألوان البطاقات
- `mobile-app.js` — `gm-compact-app` + بطاقات جداول فقط
