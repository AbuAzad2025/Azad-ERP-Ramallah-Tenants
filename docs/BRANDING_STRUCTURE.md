# هيكل الأصول والهوية البصرية

## مبدأان أساسيان

1. **مسارات نسبية** داخل `static/` — تُخزَّن في DB كـ `branding/platform/...` وليس URL كامل.
2. **فصل المنصة عن التينانت** — ملفات ومستخدمون ولوحات تحكم منفصلة.

## شجرة المجلدات (النهائية)

```
static/
├── branding/
│   ├── platform/                 ← شركة أزاد (مالك النظام / SaaS)
│   │   ├── logos/                primary.png, emblem.png, white.png
│   │   ├── favicons/             favicon.png
│   │   ├── headers/              ترويسات المنصة (اختياري)
│   │   └── auth/                 login_bg.webp, favicon_alt.png
│   └── tenants/
│       ├── nasrallah/            شعار المهندس الفلسطيني
│       ├── alhazem/              شعارات الحازم + ترويسات
│       └── ramallah/             يستخدم هوية المنصة في الإعدادات
├── img/
│   ├── banners/                  بانرات تسويقية عامة (SVG)
│   ├── uploads/                  رفع تشغيلي (منتجات، …) — ليس شعارات ثابتة
│   └── _deprecated/logos/        نسخ قديمة مكررة — لا تستخدم
├── favicon.ico                   مرآة من platform/favicons/favicon.png
└── adminlte/ …                   مكتبات واجهة — لا تعدّل
```

## من يستخدم ماذا؟

| الجهة | المجلد | المستخدم | اللوحة |
|--------|--------|----------|--------|
| **منصة أزاد** | `branding/platform/` | `owner` / `admin` — جلسة عادية (`_user_id` رقمي) | `/security/*` لوحة المالك، SaaS |
| **تينانت** | `branding/tenants/<slug>/` | `owner@tenant` — جلسة `t:<slug>:<id>` | `/t/<slug>/` + `/console` |
| **لا تخلط** | — | مالك التينانت لا يرى `/security` داخل `/t/...` | — |

## مفاتيح `system_settings`

| المفتاح | مثال |
|---------|------|
| `custom_logo` | `branding/platform/logos/primary.png` |
| `tenant_nasrallah_logo` | `branding/tenants/nasrallah/logos/primary.png` |
| `tenant_alhazem_header` | `branding/tenants/alhazem/headers/letterhead.png` |
| `multi_tenancy_enabled` | `true` |

## القوالب (الربط الصحيح)

```jinja
{{ system_settings.custom_logo_url }}
{{ system_settings.custom_header_url }}
{{ branding_url('tenant', 'alhazem', 'logos', 'primary.png') }}
```

متغيرات السياق:

- `is_tenant_scope` — داخل `/t/<slug>/`
- `is_platform_owner` — مالك أزاد فقط (خارج التينانت)
- `is_tenant_session` — جلسة `t:slug:id`

## ما يُؤرشف / لا يلزم

| العنصر | القرار |
|--------|--------|
| `static/img/logo_main.png` ونظائرها | **مكرر** → `_deprecated/logos` |
| `static/img/logo.png` (نصر الله) | **نُقل** → `tenants/nasrallah` |
| `static/img/azad_login_bg.webp` | **نُسخ** → `branding/platform/auth/` |
| `/static/img/logo.png` في JS قديم | **أُزيل** — يعتمد على `meta gm-logo-url` |
| روابط `http://...` في DB | **مرفوض** — `normalize_rel_path` |

## أوامر الصيانة

```powershell
flask branding audit          # تقرير JSON
flask branding reorganize     # تنظيم + تطبيع DB + أرشفة مكررات
flask branding bootstrap      # تهيئة كاملة للتطوير
```

## الإنتاج

- انسخ مجلد `static/branding/` كاملاً مع التطبيق.
- لا تغيّر المسارات في DB عند تغيير النطاق — `url_for('static')` يبني الرابط تلقائياً.
- `assets_version` يكسر كاش المتصفح بعد رفع شعار جديد.
