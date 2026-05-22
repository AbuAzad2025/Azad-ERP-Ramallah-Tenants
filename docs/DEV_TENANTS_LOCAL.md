# تينانتات التطوير المحلي (garage_manager فقط)

## عدم التعارض مع PostgreSQL المشترك

جميع أوامر التينانت **تعمل على قاعدة `garage_manager` فقط** ولا:

- تحذف قواعد أخرى (`mavi_erp`, `naser_company`, `azad_accounting_sys_dev`, …)
- تغيّر إعدادات الكلاستر
- تستخدم `pg_terminate_backend` على مستوى السيرفر (فقط جلسات نفس القاعدة عند الاستعادة اليدوية)

المساعد/المشاريع الأخرى على نفس PostgreSQL تبقى على قواعدها المنفصلة.

## التينانتات المُعدّة

| slug | schema | الوصف |
|------|--------|--------|
| `ramallah` | `public` | البيانات الحقيقية المستعادة (legacy) |
| `nasrallah` | `t_nasrallah` | نسخة معزولة للتطوير |
| `alhazem` | `t_alhazem` | نسخة معزولة للتطوير |

## الدخول

- المنصة: `http://127.0.0.1:5000/`
- تينانت نصر الله: `http://127.0.0.1:5000/t/nasrallah/`
- تينانت الحازم: `http://127.0.0.1:5000/t/alhazem/`

**مالك التينانت (schemas المعزولة):**

- البريد: `owner@ramallah.local`
- كلمة المرور: `DevTenant2026!` (غيّرها في `.env` عبر `TENANT_OWNER_*`)

## إعادة الإعداد

```powershell
cd d:\Data\karaj\garage_manager_project\garage_manager
$env:PGPASSWORD='123'
$env:FLASK_APP='app.py'
$env:TENANT_OWNER_EMAIL='owner@ramallah.local'
$env:TENANT_OWNER_PASSWORD='DevTenant2026!'
.\.venv\Scripts\flask.exe tenants setup-production
```

## SaaS (المنصة)

خطط SaaS في `public` فقط — تُدار من `/security/saas-manager`.
