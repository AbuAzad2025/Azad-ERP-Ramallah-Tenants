# أصول الهوية البصرية

## الهيكل

```
branding/
  platform/          ← شركة أزاد للأنظمة الذكية (المنصة)
    logos/           primary.png, emblem.png, white.png
    favicons/        favicon.png
    headers/         letterhead.png (طباعة المنصة)
    auth/            login_bg.webp
  tenants/
    alhazem/         ← شركة الحازم
    nasrallah/       ← شركة المهندس الفلسطيني للمعدات الثقيلة
```

## ماذا يُولَّد تلقائياً من `primary.png`؟

| الملف | الاستخدام |
|--------|-----------|
| `favicons/favicon.png` | أيقونة المتصفح |
| `logos/emblem.png` | شريط جانبي / أيقونة مضغوطة |
| `headers/letterhead.png` | ترويسة الفواتير والطباعة |
| `logos/white.png` | المنصة فقط — شعار فاتح للخلفيات الداكنة |
| `auth/login_bg.webp` | المنصة فقط — خلفية تسجيل الدخول |

## أوامر

```powershell
# بعد وضع صورك في المجلدات أعلاه
flask branding generate-missing      # يولّد الناقص فقط
flask branding generate-missing --force   # إعادة توليد الكل
flask branding sync-files            # ربط DB + توحيد الأسماء
flask branding cleanup               # حذف المكررات وكاش التطوير
```

## أين تظهر في الواجهة

| المكان | المنصة | التينانت |
|--------|--------|----------|
| `/auth/login` | شعار أزاد + فوتر | شعار التينانت |
| فوتر التطبيق | أزاد | التينانت |
| الشريط الجانبي | — | شعار واحد |
| الشريط العلوي | شعار أزاد | نص فقط (بدون تكرار) |
| الطباعة | letterhead المنصة | letterhead التينانت |

ضع **صورة واحدة رئيسية** في `logos/primary.png` لكل جهة — النظام يبني الباقي.
