# نظام إدارة المحاسبة والصيانة المتكامل

<div align="center">

![Logo](https://img.shields.io/badge/Azad%20Accounting-System-blue?style=for-the-badge)

**نظام متكامل لإدارة المحاسبة والمخزون والصيانة والمبيعات**

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.3-green.svg)](https://flask.palletsprojects.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://postgresql.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 📋 نظرة عامة

نظام **Azad Accounting** هو حل متكامل لإدارة العمليات المحاسبية والتجارية للشركات الصغيرة والمتوسطة. يوفر النظام إدارة شاملة للمخزون والمبيعات والصيانة والعملاء والموردين مع تقارير مالية دقيقة وتحكم كامل في الصلاحيات.

### ✨ المميزات الرئيسية

- 📊 **إدارة المحاسبة**: قيود يومية، ميزان مراجعة، قوائم مالية
- 📦 **إدارة المخزون**: تتبع المنتجات، حركات المخزون، التحويلات بين المستودعات
- 🔧 **إدارة الصيانة**: طلبات صيانة، قطع غيار، متابعة الحالة
- 💰 **إدارة المبيعات**: فواتير، مرتجعات، عروض أسعار
- 👥 **إدارة العملاء والموردين**: أرصدة، دفعات، تقارير
- 📱 **واجهة مستخدم سهلة**: تصميم عصري، دعم كامل للعربية
- 🔒 **نظام صلاحيات متقدم**: تحكم دقيق في الوصول

---

## 🏗️ الهيكل التقني

### المتطلبات

```
Python 3.11+
PostgreSQL 15+
Redis (اختياري للـ caching)
```

### التقنيات المستخدمة

| التقنية | الاستخدام |
|---------|----------|
| **Flask** | إطار العمل الرئيسي |
| **SQLAlchemy** | ORM لإدارة قاعدة البيانات |
| **Alembic** | ترحيلات قاعدة البيانات |
| **Jinja2** | قوالب HTML |
| **Bootstrap 5** | تصميم الواجهة |
| **Chart.js** | الرسوم البيانية |
| **DataTables** | جداول متقدمة |

---

## 🚀 التثبيت والتشغيل

### 1. استنساخ المشروع

```bash
git clone https://github.com/AbuAzad2025/AzadAccounting-sys.git
cd AzadAccounting-sys
```

### 2. إنشاء البيئة الافتراضية

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. تثبيت المتطلبات

```bash
pip install -r requirements.txt
```

### 4. إعداد قاعدة البيانات

```bash
# تعديل config.py بإعدادات قاعدة البيانات
# ثم تشغيل الترحيلات
flask db upgrade
```

### 5. تشغيل التطبيق

```bash
python app.py
```

الوصول عبر: `http://localhost:5000`

---

## 📁 هيكل المشروع

```
AzadAccounting-sys/
├── app.py                 # نقطة الدخول الرئيسية
├── config.py              # الإعدادات
├── models.py              # نماذج قاعدة البيانات
├── utils.py               # دوال مساعدة
├── extensions.py          # الإضافات
├── stock_audit_system.py  # نظام توثيق المخزون
├── requirements.txt       # المتطلبات
├── routes/                # المسارات
│   ├── auth.py           # المصادقة
│   ├── sales.py          # المبيعات
│   ├── service.py        # الصيانة ⭐
│   ├── inventory.py      # المخزون
│   ├── customers.py      # العملاء
│   ├── payments.py       # الدفعات
│   └── ...
├── templates/            # القوالب
│   ├── base.html
│   ├── sales/
│   ├── service/
│   └── ...
├── static/               # الملفات الثابتة
│   ├── css/
│   ├── js/
│   └── img/
└── migrations/           # ترحيلات قاعدة البيانات
```

---

## 🔧 نظام الصيانة المتكامل

### العلاقات الرئيسية

```
ServiceRequest (طلب الصيانة)
    ├── Customer (العميل) ⭐
    ├── Mechanic (الميكانيكي)
    ├── ServicePart (قطع الغيار) ← Warehouse (المستودع)
    └── ServiceTask (المهام)
```

### عمليات المخزون

| العملية | الوصف |
|---------|-------|
| **إضافة قطعة** | خصم تلقائي من المخزون |
| **تعديل قطعة** | إرجاع القديم + خصم الجديد |
| **حذف قطعة** | إرجاع المخزون |
| **إكمال الصيانة** | خصم نهائي |
| **إعادة الفتح** | إرجاع كامل المخزون |

### التوثيق

كل عملية مخزون يتم توثيقها في `AuditLog` مع:
- نوع العملية (SERVICE_CONSUME, SERVICE_RELEASE, ...)
- المنتج والمستودع
- الكمية والرصيد بعد العملية
- المستخدم والوقت
- سبب العملية

---

## 💻 واجهة المستخدم

### لوحة التحكم الرئيسية

- إحصائيات سريعة
- الرسوم البيانية
- التنبيهات والإشعارات
- الوصول السريع

### الشاشات الرئيسية

| الشاشة | الوصف |
|--------|-------|
| 🏠 **الرئيسية** | لوحة التحكم والإحصائيات |
| 📦 **المخزون** | إدارة المنتجات والمستودعات |
| 🔧 **الصيانة** | طلبات الصيانة والمتابعة |
| 💰 **المبيعات** | الفواتير والمرتجعات |
| 👥 **العملاء** | بيانات العملاء والأرصدة |
| 📊 **التقارير** | التقارير المالية والإحصائية |

---

## 🔒 الأمان والصلاحيات

### نموذج الصلاحيات

```python
# أمثلة على الصلاحيات
PERMISSIONS = [
    'view_sales',
    'create_sales',
    'edit_sales',
    'delete_sales',
    'view_inventory',
    'manage_inventory',
    'view_service',
    'manage_service',
    'view_reports',
    'admin_access',
]
```

### الأدوار الافتراضية

| الدور | الصلاحيات |
|-------|----------|
| **مدير** | جميع الصلاحيات |
| **محاسب** | المبيعات، الدفعات، التقارير |
| **مستودع** | إدارة المخزون |
| **فني صيانة** | إدارة طلبات الصيانة |
| **مستخدم** | عرض فقط |

---

## 📊 التقارير

### التقارير المتاحة

- 📈 **التقارير المالية**: ميزان المراجعة، قائمة الدخل، الميزانية
- 📦 **تقارير المخزون**: حركات المخزون، جرد المستودعات
- 👥 **تقارير العملاء**: أرصدة العملاء، كشف حساب
- 🔧 **تقارير الصيانة**: إحصائيات الصيانة، أداء الفنيين
- 💰 **تقارير المبيعات**: مبيعات حسب الفترة، المنتجات الأكثر مبيعاً

---

## 🛠️ التطوير

### إضافة ميزة جديدة

```bash
# إنشاء فرع جديد
git checkout -b feature/new-feature

# تطوير الميزة
# ...

# اختبار الميزة
python -m pytest tests/

# دمج الميزة
git checkout main
git merge feature/new-feature
```

### الاختبارات

```bash
# تشغيل جميع الاختبارات
python -m pytest

# تشغيل اختبار محدد
python -m pytest tests/test_service.py
```

---

## 📝 المساهمة

نرحب بالمساهمات! يرجى اتباع الخطوات التالية:

1. 🍴 Fork المشروع
2. 🌿 إنشاء فرع للميزة (`git checkout -b feature/amazing-feature`)
3. 💾 Commit التغييرات (`git commit -m 'Add amazing feature'`)
4. 📤 Push للفرع (`git push origin feature/amazing-feature`)
5. 🔃 فتح Pull Request

---

## 📄 الترخيص

هذا المشروع مرخص بموجب [MIT License](LICENSE)

---

## 👨‍💻 المطور

**Azad Accounting Team**

📧 للتواصل: [your-email@example.com](mailto:your-email@example.com)

🌐 الموقع: [https://github.com/AbuAzad2025](https://github.com/AbuAzad2025)

---

<div align="center">

**⭐ لا تنسَ إعطاء النجمة إذا أعجبك المشروع! ⭐**

</div>
