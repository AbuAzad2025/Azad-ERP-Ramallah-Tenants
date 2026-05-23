# دليل واجهة ERP العربية

المرجع الكامل: [`arabic_erp_ui_assistant_spec.json`](arabic_erp_ui_assistant_spec.json)

## التطبيق في الكود

| الملف | الدور |
|--------|--------|
| `static/css/gm-design-system.css` | ثيم فاتح/ليلي، شريط جانبي، جداول، أزرار، فوتر |
| `static/js/gm-theme.js` | تبديل الوضع الليلي (`localStorage.gmTheme`) |
| `templates/base.html` | class `gm-pro-ui` + تحميل الملفات |

## الثيمات (من المواصفة)

- **افتراضي:** `light_teal_saas` — خلفية `#F7F9FC`، شريط جانبي `#0f2744`، لون أساسي تركوازي
- **ليلي:** `dark_navy_gold_executive` — خلفية `#0f172a`، لمسة ذهبية للعنصر النشط في القائمة

لون الشركة من الإعدادات يُطبَّق عبر `--theme-primary` في `base.html`.

## قائمة التحقق

- [x] RTL وقائمة يمين
- [x] أزرار عربية بدون تحويل أحرف كبيرة إجباري
- [x] كروت بظل خفيف وحدود 16px
- [x] قوائم فرعية بمسافة بادئة وحد يميني
- [x] فوتر بدون عبارات تسويقية
- [ ] لوحة تحكم KPI/Charts — تُحسَّن تدريجياً في `dashboard.html`
