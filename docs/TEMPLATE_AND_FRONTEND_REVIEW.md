# مراجعة القوالب والفرونت اند — سجل تراكمي (لا تُعاد من الصفر)

> **ملف حيّ يُحدَّث فقط بالإضافة.** لا يُعاد كتابته ولا تُعاد مراجعة ما سُجّل ✅ إلا بطلب صريح أو تغيّر كود جوهري.

| مرجع | مسار | دور |
|------|------|-----|
| **هذا الملف** | `docs/TEMPLATE_AND_FRONTEND_REVIEW.md` | بنية منجزة + قواعد + تحقق إلزامي + **سجل زمني** |
| فهرس الروابط | `flask routes` / توثيق يدوي | عند تغيّر routes (ليس «فحص من جديد») |
| سجل قالب بقالب | `scripts/TEMPLATE_INSPECTION_LOG.md` | **يُلحق** قسم لكل قالب منتهٍ — لا يُحذف المنجز |
| طبقات CSS | `docs/UI_CSS_LAYERS.md` | يُحدَّث عند تغيير ترتيب التحميل فقط |
| تشغيل | `.\run_app.ps1` → http://127.0.0.1:5000 | |

---

## 0. سياسة التراكم — اقرأها مرة

### لا تُعاد

| النوع | معنى ✅ |
|--------|---------|
| **بنية تحتية** (§2) | مرة منجزة — لا «جولة فحص قوالب» جديدة لنفس البنية |
| **قالب في السجل** | مُوثَّق في `TEMPLATE_INSPECTION_LOG.md` كـ ✅ — لا إعادة إصلاح إلا regression |
| **قائمة التحقق §3** | تُطبَّق على **التعديل الجديد فقط**، لا إعادة اختبار كل النظام |
| **سجل زمني §0.1** | سطر جديد لكل دفعة — لا حذف التاريخ |

### متى يُعاد الفحص لقالب واحد؟

- المستخدم طلب صراحة «أعد فحص X»
- تغيّر كبير في `routes/` أو القالب أو CSS مخصّص للصفحة
- regression بعد دمج (شكوى بصرية/وظيفية)

### عند كل دفعة عمل (3 خطوات)

1. **اقرأ** §3 (تحقق) + آخر سطر في §0.1 (ماذا حدث مؤخراً).
2. **نفّذ** التعديل على القالب/الملف المطلوب فقط.
3. **ألحق** — سطر في §0.1 + قسم في `TEMPLATE_INSPECTION_LOG.md` (لا استبدال الملف).

---

## 0.1 سجل زمني للدفعات (يُلحق فقط)

| التاريخ | الدفعة | ملخص | ملفات رئيسية |
|---------|--------|------|----------------|
| 2026-05 (سابق) | مراجعة قوالب جماعية | ~323 قالب responsive/theme | سكربتات دفعية (أُزيلت من `scripts/` بعد التنفيذ) |
| 2026-05 (سابق) | JS | ربط يتيم + BS bridge | `safe-enhancements.js`, `bs5-utils.css` |
| 2026-05-24 | UX رسائل | رسائل موحّدة، لا أخطاء صامتة | `ux_messages.py`, `ux-messages.js`, `app.py`, `api.py` |
| 2026-05-24 | داشبورد | KPI، مخططات، ثيم | `dashboard.html`, `charts.js` |
| 2026-05-24 | تعميم بطاقات | كل النظام + موبايل/تابلت | `kpi-cards-global.css`, `mobile-app.css` |
| 2026-05-25 | تنظيف scripts | حذف سكربتات ترحيل/فحص لمرة واحدة | — |
| 2026-05-24 | توثيق تراكمي | هذا الملف + سياسة عدم إعادة العمل | `TEMPLATE_AND_FRONTEND_REVIEW.md` |
| 2026-05-25 | نافبار + سايدبار + FX | زر القائمة موحّد، أسعار USD/د.أ، ترتيب شريط علوي، موبايل overlay | `erp-navbar.js`, `navbar.html`, `layout-app.css`, `routes/api.py`, `base.html` |
| 2026-05-25 | FX أونلاين + موقع القائمة | أولوية Investing→سيرفرات→يدوي؛ مدى يوم/أسبوع؛ `data-sidebar-position` يمين/يسار | `services/fx_navbar_provider.py`, `layout-app.css`, `base.html` |
| 2026-05-25 | FX موحّد للحسابات | يدوي عند تعذّر الأونلاين؛ سعر بتاريخ الحركة؛ `fx_rate_used` ثابت | `services/fx_resolution.py`, `models.py`, `routes/payments.py` |
| 2026-05-25 | عرض المحتوى + نافبار FX | `calc(100%-sidebar)`؛ إصلاح `ensure_currency` في نافبار | `layout-app.css`, `fx_resolution.py`, `erp-navbar.js` |
| 2026-05-25 | قوالب العملات BS4 | توحيد Bootstrap 4.6؛ إعدادات بدون تكرار `content-header` | `templates/currencies/*`, `settings.html` |
| 2026-05-25 | مستخدمون — ربط فروع | ربط تلقائي بفرع MAIN؛ super_admin = كل الشركات؛ صلاحيات إضافية للمستوى ≤1 | `user_branch_service.py`, `users/*`, `routes/users.py` |

<!-- عند دفعة جديدة: أضف صفاً في الجدول أعلاه — لا تحذف الصفوف القديمة -->

---

## 1. بنية تحتية منجزة (مرجع ثابت — لا تُعاد عملها)

### أ. بنية الفحص والتشغيل

| الإنجاز | التفاصيل |
|---------|----------|
| تشغيل التطبيق | `app.py` / `run_app.ps1` — المنفذ 5000 |
| فهرس القوالب | ~407 ملف، ~329 صفحة برابط، ~56 partial |

### ب. مراجعة القوالب (جولة سابقة)

| الإنجاز | التفاصيل |
|---------|----------|
| مراجعة شاملة | ~323 قالب مُعدّل (responsive / theme / BS bridge) — السكربتات أُزيلت بعد التنفيذ |

### ج. JavaScript

| الإنجاز | الملفات |
|---------|---------|
| إزالة تكرار سكربتات | `security_mega_enhancements`, `fx_utils`, `dom-safe` في بعض القوالب |
| ربط سكربتات يتيمة | `auth.js`, `barcode.js`, `export-helpers`, `reporting.js`, `security-tour-guide.js`, … |
| جسر BS4/BS5 | `safe-enhancements.js`, `bs5-utils.css` |
| تقرير JS | مُدمج في الكود — لا ملف تقرير في `scripts/` |

### د. رسائل المستخدم (UX)

| الإنجاز | الملفات |
|---------|---------|
| رسائل موحّدة عربية | `utils/ux_messages.py`, `flash_msg`, `json_error`, `api_payload` |
| واجهة | `static/js/ux-messages.js`, `static/css/ux-messages.css`, `partials/ux_flash_messages.html` |
| معالجة AJAX/JS | `fetch` (401/403/5xx), jQuery `ajaxError`, `unhandledrejection` |
| منع تكرار toast | نافذة 5 ثوانٍ لنفس الرسالة |
| API/Flask | `app.py` معالجات أخطاء، `routes/api.py` |

### هـ. الداشبورد وتحسينات بصرية (جلسة المراجعة الحالية)

| المشكلة | الحل |
|---------|------|
| أزرار «عرض التفاصيل» أبيض على فاتح | `erp-kpi-card__footer` + ألوان accent |
| بطاقات بيضاء لا تتبع الثيم | `kpi-cards-global.css` + tokens |
| تكدس نصوص على الرسوم | `charts.js`: إيقاف datalabels على الداشبورد، وسيلة إيضاح أسفل، `erp-chart-host` |
| تعميم على كل النظام | `kpi-cards-global.css` آخر `<head>` + `apply_global_card_theme.py` (~180 قالب) |
| موبايل/تابلت يُسطّح البطاقات | استثناءات في `mobile-app.css` + قواعد `data-ui-mode` في `kpi-cards-global.css` |
| تعارض `service.css` | `--box-color` → `var(--erp-*)` |

### و. فحص قالب بقالب (تراكمي — ليس من الصفر)

| المصدر | العدد / الحالة |
|--------|----------------|
| قوالب في الفهرس | ~407 |
| مراجعة جماعية سابقة | ~323 مُعدّل (لا تُعاد) |
| **موثّق يدوياً قالباً قالباً** | انظر **`scripts/TEMPLATE_INSPECTION_LOG.md`** فقط |
| آخر قالب مُشتغل عليه | `dashboard.html` — ⏳ تأكيد نهائي |

> **لا تُعدّ «مراجعة كل القوالب».** تُضاف فقط قوالب جديدة إلى السجل عندما يرسل المستخدم ملاحظاته.

---

## 2. ملفات البنية الثابتة (مرجع — تُحدَّث عند إضافة ملف جديد فقط)

### CSS (الطبقة النشطة فقط)

```
static/css/erp-theme/
  tokens.css              ← ألوان الثيم (palestinian/gulf × light/dark)
  index.css               ← يستورد المكوّنات (بدون kpi مكرر داخل الحزمة)
  components.css          ← بطاقات عامة، نماذج، أزرار
  kpi-cards-global.css    ← ★ بطاقات KPI / small-box / summary / charts / موبايل
  pages-dashboard.css     ← تنبيهات الداشبورد فقط
  pages-financial.css     ← تقارير مالية
  responsive.css
  …

templates/base.html       ← kpi-cards-global.css بعد {% block styles %}
templates/partials/erp_head_assets.html
templates/layouts/erp_public.html  ← kpi-cards-global بعد block head
```

### CSS لا يُحمَّل (لا تعيد ربطه)

`erp-arabic-ui.css`, `erp-conflict-fixes.css`, `enhancements.css`, `style.css`, `ux-unified.css`, `ux-contrast.css`, `erp-content-migrated.css`

### JS أساسي للواجهة

`erp-theme.js`, `ux-messages.js`, `charts.js`, `layout-responsive.js`, **`erp-navbar.js`** (قائمة جانبية + أسعار شريط علوي), `mobile-app.js`, `safe-enhancements.js`, `gm-scroll-filters.js`

### و. نافبار وسايدبار (2026-05-25)

| المشكلة | الحل |
|---------|------|
| زر ☰ لا يبدّل القائمة (تعارض AdminLTE) | `data-erp-pushmenu` + `erp-navbar.js` — `stopImmediatePropagation` |
| أسعار USD/د.أ خاطئة أو افتراضية دائماً | `/api/exchange-rates`: يدوي/محلي أولاً ثم أونلاين (`routes/api.py`) |
| نافبار مزدحم على الموبايل | أيقونات الثيم/الوضع `d-none d-sm-block`؛ سياق الشركة/الفرع في قائمة ℹ️ فقط |
| سايدبار موبايل | overlay + `translateX` + قفل scroll + Escape + `#gm-sidebar-backdrop` |
| FX أونلاين | `services/fx_navbar_provider.py`: Investing (إن توفّر) → exchangerate-api/host → يدوي DB |
| مدى يوم/أسبوع | Frankfurter (USD) + سجل `exchange_rates`؛ عرض مدمج في chip + قائمة ℹ️ موبايل |
| موقع القائمة | `data-sidebar-position=left\|right` + CSS ديسكتوب/موبايل؛ افتراض RTL = `right` |
| FX موحّد | `fx_resolution.py`: نافبار ≠ تاريخ الحركة؛ معاملات قديمة = `fx_rate_used` فقط |
| صفحة أسعار الصرف مزدحمة/أخطاء جلب | `/currencies/exchange-rates`: `resolve_fx_rate_for_date` بدل `_fetch_external_fx_rate`؛ إخفاء عمود الأونلاين عند التعطيل؛ JS اختبار/تحديث (`routes/currencies.py`, `templates/currencies/exchange_rates.html`) |

### Python / قوالب

`utils/ux_messages.py`, `routes/main.py` (dashboard), `kpi-cards-global.css`

---

## 3. قائمة التحقق الإلزامية — قبل دمج أي تحسين فرونت اند

> **يُطبَّق على كل PR / كل قالب / كل ملف CSS أو JS جديد.**  
> الهدف: عدم نسيان التكامل مع الموبايل، التابلت، طبقات CSS، والثيم.

### أ. فهم السياق (5 دقائق)

- [ ] أي **قالب** يتأثر؟ (`extends base` أم `erp_public` أم `base_security`؟)
- [ ] أي **route** وصلاحيات؟ (`flask routes` أو توثيق الصفحة)
- [ ] هل الصفحة تحمّل **CSS/JS إضافي** في `{% block styles %}` أو `head_extra`؟ (مثل `service.css`, `sales.css`)

### ب. طبقات CSS (لا تكدس)

- [ ] قراءة `docs/UI_CSS_LAYERS.md` — ترتيب التحميل
- [ ] **لا** قواعد ألوان KPI في CSS صفحة — فقط `kpi-cards-global.css`
- [ ] **لا** إعادة ربط ملفات legacy الموقوفة
- [ ] ألوان من **`var(--erp-*)`** وليس hex ثابت (إلا نادراً مع تعليق)
- [ ] إن وُجد `!important` على `.card` — تحقق أنه لا يكسر `erp-kpi-card` / `summary-card`
- [ ] **`kpi-cards-global.css` يبقى آخر طبقة** — لا تضع CSS بعده في `base` دون مراجعة

### ج. موبايل وتابلت (إلزامي)

- [ ] اختبار ضيق النافذة أو `data-ui-mode="mobile"` / `"tablet"`
- [ ] `mobile-app.css`: هل قاعدة `.card { background:#fff }` تُسطّح بطاقاتك؟ → استثنِ أو عزّز في `kpi-cards-global`
- [ ] `gm-stat-row` / `gm-mobile-grid-*` — هل التخطيط عمودان؟
- [ ] جداول: هل تحتاج `table-mobile-cards`؟
- [ ] أزرار/حقول: `font-size: 16px` على iOS للمدخلات (موجود في `responsive.css`)
- [ ] مخططات: `charts.js` + `erp-chart-host` على ارتفاع أصغر

### د. الثيم

- [ ] تبديل **فلسطيني ↔ خليجي** و **فاتح ↔ داكن**
- [ ] `erp-theme-change` — هل الرسوم تُحدَّث؟ (`charts.js` يعيد الرسم)
- [ ] لون الشركة `primary_color` في الإعدادات إن وُجد

### هـ. رسائل وتفاعل

- [ ] أخطاء API تستخدم `json_error` / `api_payload` أو `AzadUX.notify`
- [ ] لا `alert()` جديد — `AzadUX.notify` أو `showToast`
- [ ] لا رسائل مكررة (flash + toast لنفس الحدث)
- [ ] `fetch` مع معالجة يدوية: `uxFeedback: false` لتجنب تكرار

### و. Bootstrap / AdminLTE

- [ ] المشروع **BS 4.6 + AdminLTE** — ليس BS5 كامل؛ استخدم `data-dismiss` أو الجسر في `safe-enhancements`
- [ ] `small-box` / `info-box` — ألوان عبر `kpi-cards-global` لا Bootstrap الافتراضي فقط

### ز. بعد الدمج

- [ ] Ctrl+F5 — ديسكتوب + موبايل
- [ ] تحديث `scripts/TEMPLATE_INSPECTION_LOG.md` إن انتهى قالب
- [ ] Hard refresh بعد تغيير CSS في `static/` (كاش `static_version`)

---

## 4. سير عمل مراجعة قالب واحد (للمستخدم وللمطور)

```
1. افتح الرابط من توثيق الصفحة أو `flask routes`
2. سجّل الملاحظات (بصري / وظيفي / موبايل)
3. نفّذ الإصلاح مع قائمة التحقق أعلاه
4. انسخ قسم التوثيق إلى TEMPLATE_INSPECTION_LOG.md
5. علّم الحالة: ✅ مكتمل | ⏳ بانتظار تأكيد | ❌ يحتاج بيانات/صلاحية
```

---

## 5. دروس من الجلسة — لماذا حدث «نسيان التكامل»

| ما حدث | الدرس المُطبَّق الآن |
|--------|---------------------|
| تحسين الداشبورد في `erp-arabic-ui.css` غير المحمّل | مصدر واحد: `erp-theme/` + تحقق من `erp_head_assets` |
| ألوان ثابتة لا تتبع الثيم | tokens + `kpi-cards-global` فقط |
| `service.css` بعد الثيم يطغى | `kpi-cards-global` **آخر** `<head>` + لا ألوان KPI في CSS صفحة |
| موبايل يُبيضّض كل `.card` | استثناءات في `mobile-app.css` + قواعد `[data-ui-mode]` |
| تكرار طلب «موبايل؟ تعارض؟» | **هذا الملف** + قائمة التحقق إلزامية |

**التزام العمل القادم:** أي تحسين فرونت اند يبدأ بقراءة §3 في هذا الملف، وليس بإصلاح القالب فقط.

---

## 6. أوامر مفيدة

```powershell
# تشغيل
.\run_app.ps1
# أو
venv\Scripts\python.exe app.py

# فهرس routes (بدل سكربت الفهرس المحذوف)
venv\Scripts\flask.exe routes
```

---

## 7. قائمة الانتظار الحالية (تتقلص — لا تُعاد البنية)

| البند | الحالة | ملاحظة |
|-------|--------|--------|
| تأكيد نهائي `dashboard.html` | ⏳ | يُغلق في السجل عند موافقتك → ✅ |
| قالب تالي من اختيارك | — | يُلحق في `TEMPLATE_INSPECTION_LOG.md` |
| `alert()` في JS قديم | تدريجي | يُسجّل في §0.1 عند كل دفعة |
| دفع Git / PA | عند الطلب | — |

---

## 8. قالب إلحاق قالب (انسخ إلى **أسفل** `TEMPLATE_INSPECTION_LOG.md`)

```markdown
### ✅ `templates/....html` — العنوان

| البند | التفاصيل |
|-------|----------|
| **URL** | |
| **Route** | |
| **صلاحيات** | |
| **Base** | |

**Static:** …

**Python / Models:** …

**تحقق:** ديسكتوب ✅ | موبايل ✅ | تابلت ✅ | ثيم فلسطيني/خليجي ✅ | تعارض CSS لا ✅

**إصلاحات:** …

**نتيجة:** ✅ / ⏳ / ❌
```

---

## 9. تعليمات للمساعد / المطور (Cursor)

```
قبل تحسين فرونت اند:
1. افتح docs/TEMPLATE_AND_FRONTEND_REVIEW.md — §0 و §3
2. افتح scripts/TEMPLATE_INSPECTION_LOG.md — هل القالب منجز ✅؟
3. إن ✅ ولا regression — لا تعيد العمل

بعد التعديل:
1. ألحق صفاً في §0.1 (جدول السجل الزمني)
2. ألحق قسم قالب في TEMPLATE_INSPECTION_LOG.md
3. لا تحذف ولا تعيد كتابة الأقسام §1–§2 إلا إضافة سطر لملف جديد
```

---

*سجل تراكمي — آخر تعديل على الملف: 2026-05-24. الدفعة التالية: ألحق فقط، لا تستبدل.*
