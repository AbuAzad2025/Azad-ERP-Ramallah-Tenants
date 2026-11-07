# أصول الهوية البصرية

## الهيكل

```
branding/
  platform/              ← شركة أزاد (المنصة)
    logos/               primary.png, emblem.png, white.png
    favicons/            favicon.png
    headers/             letterhead.png
    auth/                login_bg.webp
  tenants/
    {code}/              ← مجلد لكل شركة (رمز الشركة lowercase)
      logos/             primary.png, emblem.png, white.png
      favicons/          favicon.png
      headers/           letterhead.png, banner.png
  _samples/
    alhazem/             ← نموذج مرجعي (اختياري)
```

## الشركات الحالية

| الرمز | المجلد | الشركة |
|-------|--------|--------|
| PHE | `tenants/phe/` | المهندس الفلسطيني للمعدات الثقيلة |
| NASR | `tenants/nasr/` | شركة نصر للاستيراد والتصدير |

عند **إنشاء شركة جديدة** يُنشأ مجلد `tenants/{code}/` تلقائياً مع المجلدات الفرعية.

## ماذا يُولَّد من `logos/primary.png`؟

| الملف | الاستخدام |
|--------|-----------|
| `favicons/favicon.png` | أيقونة المتصفح |
| `logos/emblem.png` | الشريط الجانبي المضغوط |
| `headers/letterhead.png` | ترويسة الفواتير والطباعة |
| `headers/banner.png` | بانر اختياري |
| `logos/white.png` | المنصة فقط — للخلفيات الداكنة |

## أوامر

```powershell
flask branding generate-missing
flask branding generate-missing --force
flask branding sync-files
```

## أين تظهر

| المكان | المنصة | التينانت |
|--------|--------|----------|
| `/auth/login` | شعار أزاد + خلفية | — |
| الشريط الجانبي | — | شعار الشركة |
| الشريط العلوي | شعار أزاد | اسم الشركة |
| الطباعة | letterhead المنصة | letterhead الشركة |

ضع **صورة واحدة** في `logos/primary.png` — النظام يبني الباقي.
