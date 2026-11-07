# سجل فحص القوالب — Template Inspection Log

> **الملخص الشامل + قائمة التحقق الإلزامية (موبايل/تابلت/تعارض CSS):**  
> **`docs/TEMPLATE_AND_FRONTEND_REVIEW.md`** ← ابدأ من هنا ولا تُعد شرح السياق في كل محادثة.

> **طبقات CSS:** `docs/UI_CSS_LAYERS.md`  
> **التطبيق:** http://127.0.0.1:5000  
> **آخر تحديث:** 2026-05-25

---

## خطة العمل

| المرحلة | الوصف | الحالة |
|---------|--------|--------|
| 0 | تشغيل التطبيق + فهرس الروابط | ✅ |
| 1 | فحص المستخدم قالباً قالباً وإرسال الملاحظات | 🔄 جاري |
| 2 | إصلاح + توثيق كل قالب في هذا الملف | 🔄 |
| 3 | **تعميم بطاقات الثيم على النظام** | ✅ 2026-05-24 |
| 4 | إعادة توليد الفهرس عند الحاجة: `python scripts/build_template_inspection_catalog.py` | — |

### تعميم البطاقات (كل النظام)

| ملف | الغرض |
|-----|--------|
| `static/css/erp-theme/kpi-cards-global.css` | KPI، small-box، info-box، summary-card، رؤوس ثيم، مخططات — **مرة واحدة آخر `<head>`** (انظر `docs/UI_CSS_LAYERS.md`) |
| `static/js/charts.js` | `ensureChartHost()` + ألوان `--erp-*` + `erp-theme-change` |

**ملاحظة:** سكربتات الترحيل/الفحص الدفعي أُزيلت من `scripts/` بعد اكتمال التعميم (2026-05-25).

**قواعد تراكمية:**
- **ألحق** أقساماً جديدة أسفل الملف — لا تحذف قوالب ✅.
- لا نُعيد فحص قالب ✅ إلا regression أو طلب صريح من المستخدم.
- البنية العامة والدفعات: `docs/TEMPLATE_AND_FRONTEND_REVIEW.md` (§0.1 سجل زمني).

---

## القوالب المُنجزة

### ✅ `templates/partials/navbar.html` — الشريط العلوي (كل صفحات `base.html`)

| البند | التفاصيل |
|-------|----------|
| **URL** | كل الصفحات الداخلية بعد تسجيل الدخول |
| **Route** | partial — `{% include 'partials/navbar.html' %}` |
| **Base** | `templates/base.html` |

**Static:** `erp-navbar.js`, `layout-app.css`, `layout-responsive.js`, `mobile.css`, `mobile-app.css`

**API:** `GET /api/exchange-rates` — USD و JOD (د.أ) → ILS؛ يدوي أولاً (`routes/api.py`)

**إصلاحات (2026-05-25):**
- زر القائمة: `data-erp-pushmenu` بدل AdminLTE `pushmenu` (تعارض كان يُلغي التبديل)
- موبايل: overlay، انزلاق RTL، قفل scroll، Escape، قائمة ℹ️ للوقت/الأسعار/الفرع
- ديسكتوب: تصغير سايدبار + أزرار إخفاء/موقع `d-lg-block` فقط
- ترتيب نافبار: تحكم → شعار → مستخدم؛ إخفاء ازدحام `<576px`
- أسعار: أونلاين أولاً (`fx_navbar_provider`) + مدى يوم/أسبوع في chip (XL+) وقائمة ℹ️
- تبديل يمين/يسار: CSS `data-sidebar-position` + `toggleSidebarPosition` على `window`

**نتيجة الفحص:** ✅ بنية | ⏳ تأكيد بصري (موقع القائمة + مصدر FX أونلاين)

---

### ✅ `templates/dashboard.html` — لوحة التحكم الرئيسية

| البند | التفاصيل |
|-------|----------|
| **URL** | http://127.0.0.1:5000/ |
| **Route** | `routes/main.py` → `main.dashboard` |
| **Endpoint** | `main.dashboard` |
| **صلاحيات** | `@login_required` + `SystemPermissions.ACCESS_DASHBOARD` |
| **Base** | `templates/base.html` |

**ملفات ثابتة (سلسلة التحميل):**
- CSS: `erp-theme/index.css`, `kpi-cards-global.css` (آخر head), `ui.css`, `ux-messages.css`, `mobile.css`, `mobile-app.css` (عند الموبايل)
- JS: `charts.js` (عند `show_charts=True`), `ux-messages.js`, `app.js`, `gm-scroll-filters.js`, …

**نماذج / بيانات (Python):**
- `routes/main.py` — `dashboard()`
- Models: `Product`, `StockLevel`, `ExchangeTransaction`, `Sale`, `Payment`, `Customer`, `Supplier`, `Partner`, `Check`, `ServiceRequest`, `Expense`, `Invoice`, …
- Utils: `utils`, `reports.sales_report`, `reports.ar_aging_report`, `permissions_config.enums.SystemPermissions`
- Cache keys: `dashboard_*_{scope_key}`

**أقسام الصفحة (للفحص الوظيفي):**
1. الوصول السريع (موبايل) — `gm-action-tile`
2. نظرة عامة — مخططات Chart.js
3. تنبيهات الشيكات
4. مؤشرات التشغيل — بطاقات KPI + «عرض التفاصيل»
5. الحركة المالية — KPI بدون footer
6. أرصدة — KPI
7. مخططات إضافية (أسبوع، صيانة، …)

**إصلاحات 2026-05-24:** (تفاصيل كاملة في `docs/TEMPLATE_AND_FRONTEND_REVIEW.md` §1.هـ)
- أزرار «عرض التفاصيل» + بطاقات ملوّنة + ثيم → `kpi-cards-global.css`, `dashboard.html`
- تكدس نصوص على الرسوم → `charts.js`, `erp-chart-host`
- تعميم النظام + موبايل/تابلت → `mobile-app.css`, `apply_global_card_theme.py`

**تحقق:** ديسكتوب ⏳ | موبايل ⏳ | ثيم ⏳ | تعارض CSS ✅ (طبقة واحدة)

**نتيجة الفحص:** ⏳ بانتظار تأكيد المستخدم بعد hard refresh (`Ctrl+F5`)

---

### ✅ `templates/users/*` — إدارة المستخدمين (2026-05-25)

| البند | التفاصيل |
|-------|----------|
| **URL** | `/users/`, `/users/<id>/edit`, `/users/create` |
| **Route** | `users_bp` |
| **Base** | `base.html` + `users.css` |

**إصلاحات:**
- ربط تلقائي بفرع `MAIN` / الشركة الرئيسية (`repair_missing_user_branch_links`)
- `super_admin` (Naser) → عرض «كل الشركات» بدون فرع إلزامي
- زر «ربط بالفروع» + `POST /users/repair-branch-links`
- صلاحيات إضافية: `can_edit_extra_permissions` للمستوى ≤1 (وليس owner فقط)
- Bootstrap 4 badges، `table-responsive`، عرض شركة/فرع في `detail.html`

**نتيجة الفحص:** ⏳ بعد hard refresh

---

## قائمة الانتظار (تالي القوالب المقترح)

| # | القالب / الوحدة | URL |
|---|-----------------|-----|
| 1 | `customers/list.html` | /customers/ |
| 2 | `sales/list.html` | /sales/ |
| 3 | `payments/list.html` | /payments/ |
| 4 | `security/index.html` | /security/ |
| 5 | `auth/login.html` | /login |

---

## قالب توثيق (انسخه لكل قالب جديد)

```markdown
### ✅ `templates/....html` — العنوان

| البند | التفاصيل |
|-------|----------|
| **URL** | |
| **Route** | |
| **صلاحيات** | |
| **Base** | |

**Static:** CSS … | JS …

**Python / Models:** …

**إصلاحات:** …

**نتيجة الفحص:** ✅ / ⏳ / ❌
```
