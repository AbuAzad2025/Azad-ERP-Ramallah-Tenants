# أصول الهوية البصرية

التوثيق الكامل: `docs/BRANDING_STRUCTURE.md`

## هيكل المجلدات

```
static/branding/
  platform/                 ← شركة أزاد (المنصة) — لا تخلط مع التينانت
    logos/
      primary.png           الشعار الرئيسي
      emblem.png            أيقونة الشريط الجانبي
      white.png             نسخة فاتحة
    favicons/
      favicon.png
    headers/                ترويسات المنصة (اختياري)
  tenants/
    alhazem/                تينانت الحازم
      logos/
      favicons/
      headers/
    nasrallah/              ← المهندس الفلسطيني (من static/img/logo.png)
      logos/primary.png
    ramallah/
```

## قاعدة البيانات (`system_settings`)

| المفتاح | المسار النموذجي |
|---------|----------------|
| `custom_logo` | `branding/platform/logos/primary.png` |
| `tenant_alhazem_logo` | `branding/tenants/alhazem/logos/primary.png` |
| `tenant_alhazem_header` | `branding/tenants/alhazem/headers/letterhead.png` |

## القوالب

- استخدم `{{ system_settings.custom_logo_url }}` و `{{ system_settings.custom_header_url }}`
- أو `{{ branding_url('tenant', 'alhazem', 'logos', 'primary.png') }}`

## أوامر

```powershell
flask branding bootstrap
flask branding bootstrap --alhazem-source "C:\Users\azad1\OneDrive\Desktop\انس"
```
