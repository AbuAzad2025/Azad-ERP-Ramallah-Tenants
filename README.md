# AzadAccounting-sys

نظام محاسبي وإداري مبني باستخدام Python و Flask و SQLAlchemy، ومجهز للعمل مع PostgreSQL على سيرفر إنتاج.

هذا المستودع مخصص لتركيب النظام وتشغيله فقط.

## المتطلبات

- Python 3.11 أو أحدث
- PostgreSQL
- بيئة افتراضية Python virtualenv
- ملف إعدادات محلي غير مرفوع إلى GitHub

## التركيب المختصر

من داخل مجلد المشروع على السيرفر:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
export FLASK_APP=app:create_app
flask db upgrade
flask db-verify
```

تفاصيل التهجيرات: `migrations/MIGRATIONS.md`

بعد ذلك يتم ربط التطبيق من إعدادات الاستضافة أو ملف WSGI الخاص بالسيرفر.

## ملفات مهمة

- `app.py` تشغيل التطبيق
- `config.py` إعدادات النظام
- `extensions.py` تهيئة إضافات Flask
- `models.py` نماذج قاعدة البيانات
- `forms.py` النماذج
- `cli.py` أوامر الإدارة
- `routes/` مسارات النظام
- `services/` خدمات النظام
- `migrations/` ترحيلات قاعدة البيانات
- `templates/` القوالب
- `static/` الملفات الثابتة

## تنبيهات إنتاج

- استخدم PostgreSQL في الإنتاج.
- لا تستخدم SQLite إلا للتجربة المحلية.
- لا ترفع ملف الإعدادات الحقيقي إلى GitHub.
- لا ترفع قواعد بيانات أو نسخ احتياطية أو ملفات إنتاجية.
- غيّر أي كلمات مرور افتراضية قبل الاستخدام الحقيقي.
- أبقِ وضع التصحيح مغلقًا على السيرفر.

## ملاحظات

ملف `.gitignore` يمنع رفع الملفات الحساسة مثل قواعد البيانات المحلية، النسخ الاحتياطية، ملفات البيئة، ومجلد `instance`.

جميع الحقوق محفوظة.
