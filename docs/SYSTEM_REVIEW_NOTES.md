# ملاحظات مراجعة نظام AzadAccounting-sys

هذا الملف هو دفتر مراجعة مركزي للنظام. الهدف منه تجميع كل الملاحظات والتحسينات المطلوبة قبل أي تعديل فعلي على الكود.

## قواعد العمل

- لا يتم تعديل الملفات الكبيرة مباشرة بدون مراجعة.
- لا يتم استبدال ملف ضخم كاملًا إلا عند الضرورة القصوى وبعد فحص الفرق.
- كل ملاحظة يجب أن تكون مرتبطة بملف أو دالة أو قالب أو تكامل محدد.
- يتم تصنيف الملاحظات حسب الخطورة والأولوية.
- أي تعديل لاحق يجب أن يكون صغيرًا وقابلًا للمراجعة.
- الريبو الإنتاجي حساس، لذلك هذه الملاحظات هي مرحلة فهم وتخطيط قبل التنفيذ.

## رموز التصنيف

| التصنيف | المعنى |
|---|---|
| CRITICAL | مشكلة قد تؤثر على المال أو الصلاحيات أو سلامة البيانات |
| HIGH | مشكلة مهمة تؤثر على الأمان أو الأداء أو الاعتمادية |
| MEDIUM | تحسين مطلوب أو مشكلة متوسطة |
| LOW | تحسين تنظيمي أو تجميلي |
| REVIEW | يحتاج دراسة أو اختبار قبل الحكم |

## حالة المراجعة

| الحالة | المعنى |
|---|---|
| TODO | لم تتم معالجته |
| IN_REVIEW | قيد الدراسة |
| READY | جاهز لتعديل صغير آمن |
| BLOCKED | يحتاج أداة/اختبار/قرار قبل التنفيذ |
| DONE | تمت معالجته |
| DEFERRED | مؤجل |

---

# 1. نظرة عامة على النظام

## نوع النظام

نظام ERP / محاسبة / إدارة كراج ومخازن ومبيعات ودفعات وشيكات وصلاحيات وذكاء صناعي.

## الوحدات الظاهرة من `app.py`

- المصادقة وتسجيل الدخول: `routes/auth.py`
- اللوحة الرئيسية: `routes/main.py`
- المستخدمون والأدوار والصلاحيات: `routes/users.py`, `routes/roles.py`, `routes/permissions.py`
- العملاء: `routes/customers.py`
- المبيعات والمرتجعات: `routes/sales.py`, `routes/sale_returns.py`
- الدفعات: `routes/payments.py`
- الشيكات: `routes/checks.py`
- المصاريف: `routes/expenses.py`
- الموردون والشركاء: `routes/vendors.py`
- الشحنات والمخازن: `routes/shipments.py`, `routes/warehouses.py`
- دفتر الأستاذ والتقارير المالية: `routes/ledger_blueprint.py`, `routes/ledger_control.py`, `routes/financial_reports.py`
- العملات: `routes/currencies.py`
- التقارير: `routes/report_routes.py`, `routes/admin_reports.py`
- الذكاء الصناعي: `routes/ai_routes.py`, `routes/ai_admin.py`, مجلد `AI/`
- الأرشيف: `routes/archive.py`, `routes/archive_routes.py`
- الأداء: `routes/performance.py`, `utils/performance_monitor.py`
- الأمن والتحكم: `routes/security.py`, `routes/security_control.py`, `middleware/security_middleware.py`

---

# 2. ملاحظات عامة عالية المستوى

| التصنيف | الحالة | المجال | الملاحظة |
|---|---|---|---|
| HIGH | TODO | تضخم ملفات routes | بعض الملفات تجمع routes و business logic و event listeners وعمليات محاسبية، خصوصًا `routes/checks.py` وربما `routes/payments.py` و`routes/api.py`. |
| CRITICAL | IN_REVIEW | الملفات المالية | الشيكات، الدفعات، المصاريف، دفتر الأستاذ، المبيعات ملفات حساسة جدًا لأن أي تعديل قد يؤثر على الأرصدة والقيود والدفعات. |
| REVIEW | TODO | AI hooks | يوجد ربط تلقائي لبعض طبقات AI عند تحميل المجلد. يجب معرفة ما الذي يعمل فعليًا وما الذي هو مراقبة فقط. |

---

# 3. ملف التشغيل المركزي `app.py`

## وصف عام

`app.py` هو بوابة تشغيل النظام. يحتوي على إنشاء التطبيق، تحميل الإعدادات، تسجيل الإضافات، تسجيل القوالب، تسجيل Blueprints، تفعيل الصلاحيات، كاش الصلاحيات والوحدات، handlers عامة، CORS، AI startup، وبعض فحوصات سلامة النظام.

## تقييم أولي

| المجال | التقييم |
|---|---|
| الأهمية | عالية جدًا |
| الدور | نقطة تشغيل مركزية للنظام كله |
| سهولة الصيانة | متوسطة بسبب كثرة المسؤوليات داخل ملف واحد |
| خطر التعديل العشوائي | عالي |
| أولوية الدراسة | عالية جدًا |

## 3.1 أول 220 سطر

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| إجبار UTF-8 للـ console | LOW | DONE | مفيد لتجنب مشاكل الإيموجي في Windows، لا يحتاج تعديل. |
| Windows WMI/platform patch | LOW | REVIEW | حل عملي لمشاكل محلية على Windows، لا يخص الإنتاج غالبًا. |
| imports الواسعة | REVIEW | TODO | الملف يقوم بأدوار كثيرة، ما يزيد حجمه وترابطه. |
| `load_user(user_id)` | MEDIUM | REVIEW | يدعم `User` و`Customer` مع prefix، وفي fallback بدون prefix يبحث User أولًا ثم Customer. يحتاج توثيق لأن IDs قد تتداخل. |
| تحميل صلاحيات المستخدم بـ `joinedload` | LOW | DONE | نقطة أداء جيدة لتقليل N+1 في الصلاحيات. |
| `_configure_app` | REVIEW | IN_REVIEW | دالة مركزية تضبط إعدادات كثيرة: JSON، microcache، static version، compression، template cache، ProxyFix، logging، telemetry. |
| `STATIC_VERSION=int(time.time())` | LOW | TODO | كل restart يغير روابط static؛ جيد لتفادي cache قديم لكنه يقلل cache بعد كل restart. |

## 3.2 الأسطر 221–520

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| إعدادات `SUPER_USER_*` و `ADMIN_USER_*` | REVIEW | TODO | جيدة للتشغيل من البيئة، تحتاج توثيق متغيرات البيئة المهمة. |
| `AI_SYSTEMS_ENABLED=True` افتراضيًا | REVIEW | TODO | يجب توثيق أثرها؛ في بعض البيئات يتم تخطي AI لاحقًا. |
| `ENABLE_AUTOMATED_BACKUPS=True` افتراضيًا | REVIEW | TODO | يحتاج معرفة أين تعمل النسخ التلقائية فعليًا. |
| PostgreSQL `connect_timeout` و `application_name` | LOW | DONE | جيد للتشخيص والاستقرار. |
| `utils.telemetry.run_telemetry` | REVIEW | TODO | يحتاج دراسة ملف `utils/telemetry.py` لمعرفة ماذا يسجل أو يرسل. |
| `_ensure_minimum_postgres_schema` | MEDIUM | TODO | يعمل ALTER TABLE جزئيًا عند startup لجدول invoices. مفيد لكنه يفضل مستقبلًا أن يكون migration رسمي. |
| `SystemInitializer(app).ensure_integrity()` | HIGH | TODO | يضمن جاهزية العملات والأدوار والمخازن و COA، لكنه قد يزيد startup. يحتاج دراسة `services/system_initializer.py`. |
| `ensure_ghost_owner()` | HIGH | TODO | مرتبط بالمالك/الماستر كي. يحتاج دراسة `services/ghost_manager.py`. |
| `ChoiceLoader` لمساري templates | REVIEW | TODO | مفيد لكنه قد يسبب التباس إذا وُجدت قوالب مكررة بنفس الاسم. |
| `autoescape=True` | LOW | DONE | نقطة أمان جيدة. |
| كاش صلاحيات المستخدم داخل `g` | LOW | DONE | جيد جدًا لمنع إعادة حساب الصلاحيات داخل نفس الطلب. |
| كاش module flags لمدة 300 ثانية | LOW | TODO | جيد للأداء، لكن تغيير تفعيل module قد يتأخر حتى انتهاء الكاش أو مسحه. |
| `has_perm` و `has_any` في القوالب | HIGH | TODO | ممتاز للواجهة، لكن لا يغني عن حماية backend routes. يجب التأكد أن routes الحساسة عليها decorators أو محمية عبر ACL. |

## 3.3 الأسطر 521–840

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `inject_enums()` | LOW | DONE | يجعل حالات النظام متاحة للقوالب. جيد ويعتمد على اتساق enums في `models.py`. |
| `url_for_any()` | MEDIUM | TODO | مفيد لتقليل كسر القوالب، لكنه قد يخفي أخطاء routing في الإنتاج إذا لم يكن `STRICT_URLS` مفعّلًا. |
| فلاتر العملات والأرقام والتواريخ | LOW | DONE | مهمة للعرض المالي. |
| `get_setting` داخل Jinja globals | MEDIUM | TODO | يجب التأكد أن `SystemSettings.get_setting` لديه cache أو لا يسبب استعلامات كثيرة داخل القوالب. |
| `translations/accounting_ar.py` | LOW | TODO | الترجمات تُحمّل مرة عند الإعداد. جيد، لكن الملف يحتاج دراسة لاحقة. |
| `amount_in_words` | LOW | TODO | مفيد للطباعة، لكنه ليس عربيًا قانونيًا مثاليًا في كل حالات التثنية والجمع. تحسين لاحق. |
| `csrf_token()` | LOW | DONE | مهم للنماذج والقوالب. |
| `_register_blueprints()` | REVIEW | IN_REVIEW | تسجيل مركزي وواضح لكل الوحدات، لكن import failure في أي وحدة قد يمنع تشغيل التطبيق كله. |
| `_collect_model_classes()` | LOW | DONE | فحص جيد لجمع النماذج. |
| `_validate_system_integrity()` route conflicts | LOW | DONE | فحص جيد لتضارب المسارات. |
| `_validate_system_integrity()` duplicate table names | LOW | DONE | فحص جيد لتكرار أسماء الجداول. |
| `_validate_system_integrity()` forms | LOW | DONE | فحص جيد لتكرار النماذج وصحة Meta.model. |

## 3.4 الأسطر 841–1180

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| نهاية `_validate_system_integrity()` | LOW | DONE | يرفع RuntimeError إذا فشل الفحص، ويسجل نجاح الفحص بعدد routes/models/forms. جيد لكن فشله يمنع التشغيل. |
| `_register_cors()` | HIGH | DONE | تم تحسينه في فرع `review/app-safe-hardening`: إذا كانت origins تساوي `*` مع credentials يتم تعطيل credentials تلقائيًا مع تسجيل warning. |
| security headers | MEDIUM | TODO | يضيف headers جيدة، لكن CSP تسمح بـ `unsafe-inline` و `unsafe-eval` لأسباب توافق. تحتاج مراجعة مستقبلية. |
| `X-XSS-Protection` | LOW | TODO | مستخدم بقيمة قديمة `1; mode=block`. المتصفحات الحديثة لا تعتمد عليه كثيرًا. ليس أولوية. |
| no-store لـ `/auth/` و `/api/` | LOW | DONE | جيد لمنع كاش بيانات حساسة. |
| static cache سنة | LOW | DONE | جيد للأداء بشرط وجود static version. |
| `_log_status` | LOW | DONE | يسجل 302/401/403/404. مفيد للتشخيص. |
| `shutdown_session` و rollback عند الخطأ | LOW | DONE | جيد لتنظيف جلسة قاعدة البيانات. |
| error handlers 403/404 | LOW | DONE | ترجع JSON للـ API وتعرض قوالب للأخطاء. جيد. |
| `_init_ai_systems()` | REVIEW | TODO | يتخطى AI في CLI و gunicorn/uWSGI/PythonAnywhere إلا إذا `ENABLE_AI_SYSTEMS=1`. تصميم جيد لتخفيف الإنتاج، ويحتاج دراسة ملفات AI لاحقًا. |
| `csrf.exempt(ledger_bp)` | HIGH | TODO | إعفاء دفتر الأستاذ من CSRF يحتاج توثيق سبب واضح أو حماية بديلة. لا يتم تعديله الآن. |
| `login_manager.session_protection=None` | MEDIUM | TODO | تعطيل session protection يحتاج فهم السبب. قد يكون لتجنب مشاكل، لكنه ملاحظة أمنية. |
| `_dedupe_entities` before_attach | REVIEW | TODO | يعالج تكرار Role/Permission داخل session. يحتاج دراسة سبب ظهوره. |
| logging filters | LOW | DONE | تخفف ضجيج السجلات من SQLAlchemy/SocketIO/PIL/WeasyPrint وغيرها. |
| override `app.url_for` عند `SERVER_NAME` | REVIEW | TODO | يحول روابط خارجية إلى نسبية إذا ليست `_external`. يحتاج اختبار إذا تم استخدام SERVER_NAME. |
| `init_security_middleware(app)` | HIGH | TODO | يحتاج دراسة `middleware/security_middleware.py` لأن له أثرًا عامًا على الطلبات. |
| attach ACL على Blueprints | HIGH | TODO | مصدر مهم للصلاحيات. يجب دراسة `permissions_config/blueprint_guards.py` و `acl.py`. |
| تحميل إعدادات البريد والتكاملات من DB | MEDIUM | TODO | يسمح للوحة التحكم بتجاوز env. جيد، لكنه يعني أن أسرار integrations قد تكون في DB وتحتاج حماية. |
| `_touch_last_seen` | LOW | IN_REVIEW | يبدأ بعد هذا المقطع، ويحتاج متابعة في الجزء التالي. |

## 3.5 الأسطر 1181–نهاية الملف

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `_touch_last_seen` | LOW | DONE | يحدث `last_seen` مرة تقريبًا كل ساعة لكل مستخدم/عميل عبر cache، وهذا جيد لتقليل ضغط الكتابة على قاعدة البيانات. |
| `_mark_request_start` | LOW | DONE | يضع وقت بداية الطلب في `g` لحساب زمن الطلب. جيد للأداء والمراقبة. |
| `_attach_request_id` و `_emit_request_id` | LOW | DONE | تم تحسين `X-Request-Id` في فرع `review/app-safe-hardening`: يتم قبول القيم النظيفة فقط بحد أقصى 64 حرفًا، وإلا يتم توليد UUID آمن. |
| `_serve_microcache` | MEDIUM | REVIEW | microcache لصفحات GET HTML حسب المستخدم والمسار. جيد للأداء، لكنه يحتاج مراقبة حتى لا يخزن صفحات فيها Set-Cookie أو محتوى ديناميكي حساس. |
| `_store_microcache` | MEDIUM | REVIEW | لا يخزن إلا status 200 وHTML وبدون Set-Cookie. تصميم جيد، لكن أي صفحة حساسة لا يجب أن تعتمد على GET فقط بدون تغيير user_key. |
| `_access_log` | LOW | DONE | يسجل الطلبات البطيئة أو ذات status >= 400، ويتجنب static. جيد للتشخيص. |
| error handlers 400/401/429/500/502/503 | MEDIUM | DONE | تم تحسين handler 500 في فرع `review/app-safe-hardening`: لا يكشف traceback في الإنتاج، ويرجع JSON/قالب عام مع `request_id`، ويبقي traceback في التطوير فقط. |
| `_memory_error` | LOW | DONE | يحول MemoryError إلى 413 مع رسالة أو قالب. جيد. |
| `restrict_customer_from_admin` | HIGH | TODO | يمنع دور customer من دخول الإدارة ويسمح فقط `/shop`, `/static`, `/auth/logout`. جيد، لكن يجب التأكد أن عملاء بدون role slug customer محميون كذلك. |
| فحص `CRITICAL_ENDPOINTS` | MEDIUM | TODO | يسجل endpoints مفقودة عند startup. مفيد، لكنه لا يفشل التشغيل. يجب مراجعة القائمة حسب أسماء endpoints الحالية. |
| `inject_system_settings` | HIGH | DONE | تم تحسينه في فرع `review/app-safe-hardening`: يقرأ مفاتيح القوالب دفعة واحدة ويخزنها في cache لمدة 120 ثانية بدل استعلام لكل مفتاح داخل كل قالب. تم إصلاح ملاحظة qodo لاحقًا بحيث فشل `cache.set()` لا يمسح نتائج قاعدة البيانات. |
| `inject_system_settings` و custom logo | MEDIUM | DONE | تم تحسين مسار الشعار في فرع `review/app-safe-hardening`: يمنع الروابط الخارجية و`..` ويعيد أي مسار غير آمن إلى `img/azad_logo.png`. |
| `check_maintenance_mode` | MEDIUM | TODO | وضع الصيانة يتخطى owner/admin بالـ id أو username. يحتاج توحيد مع صلاحيات النظام بدل hard-code فقط. |
| تسجيل `register_cli(app)` مرة ثانية | LOW | REVIEW | تم تسجيل CLI سابقًا داخل `_init_extensions_stack` ثم هنا مرة أخرى. غالبًا لا يضر، لكن يحتاج معرفة إن كان يكرر الأوامر أو لا. |
| إضافة العملات الافتراضية داخل `create_app` | MEDIUM | TODO | يضيف العملات إذا الجدول فارغ. مفيد، لكنه seed داخل startup ومكرر جزئيًا مع SystemInitializer. |
| ضمان الأدوار الأساسية داخل `create_app` | MEDIUM | TODO | ينشئ الأدوار من PermissionsRegistry، قد يتداخل مع SystemInitializer. يحتاج توحيد لاحقًا. |
| import `notifications` | LOW | REVIEW | محاولة تحميل صامتة بدون استخدام واضح. يحتاج معرفة سببها. |
| `_add_static_cache_headers` | LOW | DONE | يضيف cache سنة للـ static، وهو مكرر جزئيًا مع security_headers. لا يضر غالبًا. |
| `bootstrap_database()` | HIGH | TODO | دالة تهيئة أولية تنشئ الجداول إذا ناقصة وتزرع إعدادات وأنواع مصاريف. مهمة للتشغيل المحلي، لكن يجب عدم استخدامها عشوائيًا في إنتاج قائم. |
| `bootstrap_database()` و `upgrade` | LOW | REVIEW | يستورد `upgrade` من flask_migrate لكن لا يستخدمه فعليًا. |
| `__main__` local run | LOW | DONE | يشغل SocketIO محليًا مع cleanup للـ scheduler. لا يعمل في WSGI لأن `else: app=create_app()`. |
| `allow_unsafe_werkzeug=True` | LOW | REVIEW | مقبول في `__main__` للتشغيل المحلي فقط، ولا يستخدم في WSGI. |
| `else: app = create_app(); application = app` | LOW | DONE | مناسب لـ WSGI/PythonAnywhere. |

## 3.6 خلاصة `app.py`

| التصنيف | الحالة | الملاحظة |
|---|---|---|
| REVIEW | DONE | `app.py` مدروس من أوله لآخره على مراحل. |
| HIGH | DONE | تم إنجاز تحسينات آمنة في فرع `review/app-safe-hardening`: handler 500، CORS wildcard/credentials، X-Request-Id، cache لإعدادات القوالب، وتنظيف custom logo. |
| HIGH | DONE | تم إصلاح ملاحظة qodo على `inject_system_settings`: فشل كتابة الكاش لم يعد يلغي القيم المقروءة من قاعدة البيانات. |
| HIGH | TODO | نقاط أمنية متبقية تحتاج دراسة ملفات تابعة قبل تعديلها: CSRF exemption للـ ledger، session_protection، وأسرار integrations من DB. |
| MEDIUM | TODO | أكثر نقطة تنظيمية: وجود seed/init logic في أكثر من مكان: `SystemInitializer`, إضافة العملات, إضافة الأدوار, `bootstrap_database`. |
| LOW | DONE | توجد نقاط أداء جيدة: microcache، request id، access log، static cache، كاش last_seen، وكاش module flags. |

## 3.7 ملفات تابعة لـ `app.py` يجب دراستها لاحقًا

| الملف | السبب | الحالة |
|---|---|---|
| `extensions.py` | يربط db/cache/csrf/limiter/socketio/logging | TODO |
| `utils/telemetry.py` | معرفة ماذا يسجل أو يرسل | TODO |
| `services/system_initializer.py` | معرفة كلفة وآثار ensure_integrity | TODO |
| `services/ghost_manager.py` | مرتبط بالمالك والماستر كي | TODO |
| `middleware/security_middleware.py` | حماية عامة على كل الطلبات | TODO |
| `permissions_config/blueprint_guards.py` | خريطة صلاحيات Blueprints | TODO |
| `acl.py` | آلية فرض الصلاحيات | TODO |
| `models.py` / `SystemSettings.get_setting` | التأكد من كاش الإعدادات | TODO |

---

# 4. ملف الشيكات `routes/checks.py`

## وصف عام

ملف الشيكات يحتوي على منطق واسع جدًا، ليس فقط صفحات الشيكات. يشمل:

- إنشاء شيكات يدوية.
- تعديل وحذف شيكات.
- تغيير حالة الشيك.
- مزامنة حالة الدفعات مع الشيكات.
- إنشاء دفعات تلقائية عند إنشاء شيك يدوي.
- قيود دفتر الأستاذ GL للشيكات.
- قيود عكسية عند حذف الشيك.
- تنبيهات وتقارير.
- endpoints للواجهة.
- event listeners على SQLAlchemy.

## تقييم أولي

| المجال | التقييم |
|---|---|
| الأهمية | عالية جدًا |
| الحساسية المالية | عالية جدًا |
| سهولة الصيانة | متوسطة إلى ضعيفة بسبب التضخم |
| خطر التعديل العشوائي | عالي |
| أولوية الدراسة | عالية جدًا |

## 4.1 دوال تحتاج مراجعة صلاحيات

| الدالة | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `update_check_status(check_id)` | CRITICAL | READY | تغيّر حالة الشيك وتستدعي منطق مالي، تحتاج صلاحية إدارة دفعات/شيكات. |
| `add_check()` | HIGH | READY | تضيف شيك يدوي، تحتاج صلاحية إدارة. |
| `edit_check(check_id)` | HIGH | READY | تعدل بيانات شيك، تحتاج صلاحية إدارة. |
| `check_detail(check_id)` | MEDIUM | READY | تعرض تفاصيل شيك، تحتاج صلاحية عرض مالية. |
| `reports()` | MEDIUM | READY | تعرض تقارير شيكات، تحتاج صلاحية عرض مالية. |
| `get_first_incomplete_check()` | MEDIUM | READY | endpoint يكشف أول شيك ناقص، يحتاج صلاحية عرض مالية. |
| `get_check_lifecycle(check_id, check_type)` | HIGH | READY | يعرض دورة حياة شيك/دفعة/مصروف، يحتاج تسجيل دخول وصلاحية عرض. |

### توصية أولية

إضافة صلاحيات فقط، دون تغيير أي منطق محاسبي.

## 4.2 دوال منطق الحالة والمحاسبة

| الدالة/الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `PaymentStatusSyncService` | HIGH | IN_REVIEW | يربط حالة الشيك بحالة الدفعة، يعتمد على split و notes. يحتاج توثيق دقيق. |
| `CheckActionService.run` | CRITICAL | IN_REVIEW | القلب الحقيقي لتغيير حالة الشيك. لا يلمس قبل اختبار. |
| `create_gl_entry_for_check` | CRITICAL | IN_REVIEW | ينشئ قيود GL للشيكات. يجب التأكد من عدم الفشل الصامت. |
| `_process_check_gl_queue` / `_create_check_gl_after_commit` | HIGH | IN_REVIEW | إنشاء GL بعد commit يحتاج اختبار فعلي. |
| `_check_create_payment_auto` | CRITICAL | IN_REVIEW | ينشئ دفعة تلقائيًا عند إنشاء شيك يدوي. حساس جدًا. |
| `_check_gl_batch_reverse` | CRITICAL | IN_REVIEW | ينشئ قيد عكسي عند حذف شيك. حساس. |
| `_payment_check_before_delete` | HIGH | IN_REVIEW | يحذف/يتعامل مع قيود مرتبطة بدفعة شيك قبل الحذف. |
| `_glbatch_before_delete` | HIGH | IN_REVIEW | حذف قيد GL قد يغير حالة شيك/دفعة. يحتاج دراسة. |

## 4.3 دوال أداء محتملة الثقل

| الدالة | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `get_checks()` | HIGH | TODO | تجمع مصادر كثيرة وتستخدم تحميل واسع للبيانات. تحتاج pagination لاحقًا. |
| `get_statistics()` | MEDIUM | TODO | تعتمد على `get_checks()` بدل استعلامات مختصرة. |
| `reports()` | MEDIUM | TODO | تستخدم `get_checks()` و `Check.query.limit(10000).all()`. |
| `get_alerts()` | MEDIUM | TODO | قد تسبب N+1 بسبب العلاقات. |

## 4.4 ملاحظات validation

| الدالة | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `add_check()` | HIGH | TODO | يحتاج تحقق أقوى: المبلغ > 0، الاتجاه IN/OUT، تاريخ الاستحقاق منطقي، رقم وبنك الشيك. |
| `edit_check()` | HIGH | TODO | يحتاج نفس validation قبل الحفظ. |
| `_update_check_details()` | MEDIUM | TODO | فيه validation جيد للمبلغ والجهة، لكن يحتاج دراسة سياسة تفريغ البنك. |

## 4.5 أشياء لا يجب لمسها الآن

- GL entries.
- Event listeners.
- إنشاء الدفعات التلقائي.
- القيود العكسية.
- auto refund.
- منطق split payments.

هذه تحتاج اختبار عملي قبل أي تعديل.

---

# 5. ملف المصادقة `routes/auth.py`

## ملاحظات عامة

| التصنيف | الحالة | الملاحظة |
|---|---|---|
| HIGH | IN_REVIEW | الماستر كي يجب أن يبقى يعمل حسب قرار المالك. |
| HIGH | IN_REVIEW | يجب عدم تسجيل كلمة الماستر كي أو كشفها. |
| MEDIUM | IN_REVIEW | تسجيل دخول الماستر يجب أن يكون مراقبًا audit. |
| HIGH | TODO | منع كلمات المرور الافتراضية في تسجيل العملاء مهم. |

## قرارات ثابتة

- لا يتم تعطيل الماستر كي.
- أي تحسين يجب أن يكون حول الجلسة والتدقيق وعدم كشف السر.

---

# 6. ملف API `routes/api.py`

## ملاحظات أولية

| الدالة/المسار | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `/api/health` | HIGH | TODO | يعرض counts لجداول تجارية. من ناحية أمان وكفاءة، الأفضل health بسيط بدون إحصائيات للعامة. |
| endpoints العامة | REVIEW | TODO | يجب تصنيف ما هو public وما هو login_required وما يحتاج permission. |

## توصية

لا يتم تعديل `routes/api.py` مباشرة قبل توثيق endpoints، لأنه ملف كبير.

---

# 7. ملف الإعدادات `config.py`

## ملاحظات أولية

| العنصر | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| SQLAlchemy pool defaults | MEDIUM | TODO | القيم الافتراضية الكبيرة غير مناسبة لـ PythonAnywhere. الأفضل ضبطها بالبيئة بدل تعديل الملف. |
| SQLite fallback | MEDIUM | REVIEW | مناسب للتجربة، غير مناسب للإنتاج. |
| `ITEMS_PER_PAGE=200` | MEDIUM | TODO | قد يكون كبيرًا للواجهات الثقيلة. |
| `MAX_ITEMS_PER_PAGE=500` | MEDIUM | TODO | يحتاج مراجعة حسب أداء الصفحات. |

## قرار حالي

تخفيف pool من متغيرات البيئة على PythonAnywhere بدل تعديل `config.py`.

---

# 8. الأداء

## نقاط قوة

- يوجد microcache للصفحات.
- يوجد template cache في الإنتاج.
- يوجد static cache.
- يوجد performance monitor.
- يوجد تقليل لتحديث `last_seen` المتكرر.
- يوجد request id وaccess log للطلبات البطيئة أو ذات الأخطاء.
- تم تقليل استعلامات إعدادات القوالب في `app.py` على فرع `review/app-safe-hardening`.

## نقاط تحتاج متابعة

| العنصر | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `/system/performance` | REVIEW | TODO | يجب استخدامه لتحديد أبطأ endpoints بدل التخمين. |
| query counts | MEDIUM | TODO | مراقبة N+1 في صفحات الشيكات والدفعات والمخزون. |
| صفحات القوائم | MEDIUM | TODO | مراجعة pagination وحجم الجلب. |

---

# 9. القوالب Templates

## ملاحظات عامة

| القالب | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `templates/base.html` | REVIEW | IN_REVIEW | قالب مركزي وحساس. لا يتم استبداله كاملًا. |
| قوالب الشيكات | REVIEW | TODO | تحتاج دراسة بعد ملف `routes/checks.py`. |
| قوالب الدفعات | REVIEW | TODO | تحتاج دراسة بعد ملف الدفعات. |

## قاعدة العمل مع القوالب

لا تعديل مباشر على `base.html` إلا بتغيير صغير جدًا وقابل للمراجعة.

---

# 10. الذكاء الصناعي AI

## ملاحظات عامة

| الملف/الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `AI/__init__.py` | REVIEW | TODO | يربط عدة hooks تلقائيًا. يحتاج توثيق ما الذي يعمل فعليًا. |
| `ai_erp_transaction_guard.py` | MEDIUM | REVIEW | يضيف listener قبل flush. افتراضيًا مراقبة، لكن قد يضيف حملًا. |
| ملفات security bind | REVIEW | TODO | تحتاج دراسة لتحديد أثرها على النظام. |
| `_init_ai_systems` من `app.py` | LOW | DONE | لا يشغل scheduler/listeners في PythonAnywhere/uWSGI/gunicorn إلا عند `ENABLE_AI_SYSTEMS=1`. |

## قرار حالي

لا تطوير AI جديد قبل فهم النظام الأساسي.

---

# 11. الأمن والصلاحيات

## ملاحظات عامة

| المجال | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| صلاحيات routes المالية | CRITICAL | TODO | يجب مراجعة الشيكات والدفعات والمصاريف والدفتر. |
| CSRF exemptions | HIGH | TODO | يجب توثيق أي إعفاء ولماذا موجود، خصوصًا `ledger_bp`. |
| master key | HIGH | IN_REVIEW | يبقى يعمل، مع audit وحماية جلسة. |
| حذف مالي مباشر | HIGH | TODO | الحذف في الملفات المالية يجب مراجعته، والأفضل الأرشفة أو القيود العكسية. |
| handler 500 | HIGH | DONE | تم منع كشف traceback كامل للمستخدم في الإنتاج، مع إرجاع رسالة عامة و`request_id`، وبقاء التفاصيل في logs وفي التطوير فقط. |
| أسرار integrations في DB | HIGH | TODO | يجب معرفة من يستطيع رؤيتها وهل تُخفى أو تُشفر. |
| CORS مع credentials | HIGH | DONE | تم منع الجمع غير الآمن بين `CORS_ORIGINS=*` و credentials على `/api/*`. |
| X-Request-Id | MEDIUM | DONE | تم تنظيف قيمة `X-Request-Id` لمنع قيم طويلة أو غير نظيفة داخل logs/headers. |
| custom logo path | MEDIUM | DONE | تم منع روابط خارجية أو مسارات تحتوي `..` في شعار النظام، مع fallback آمن. |
| template settings cache fallback | MEDIUM | DONE | تم إصلاح فشل `cache.set()` بحيث لا يمسح نتائج قاعدة البيانات ولا يعيد القوالب لقيم افتراضية غير لازمة. |

---

# 12. سجل الملاحظات حسب الملف

## قالب إدخال ملاحظة جديدة

```md
## الملف: path/to/file.py

### الدالة/القسم: function_name

- التصنيف: HIGH
- الحالة: TODO
- النوع: صلاحيات / أداء / منطق / أمان / قالب / تكامل / محاسبة
- الوصف:
- السبب:
- الأثر المحتمل:
- الاقتراح:
- هل يحتاج اختبار قبل التعديل: نعم/لا
- هل يمكن تعديله بأمان كتغيير صغير: نعم/لا
```

---

# 13. قائمة العمل القادمة للدراسة فقط

| الترتيب | الملف/الوحدة | الهدف | الحالة |
|---|---|---|---|
| 1 | `app.py` | إنهاء دراسة ملف التشغيل المركزي وتحسيناته الآمنة | DONE |
| 2 | `models.py` | خريطة الجداول والعلاقات | IN_REVIEW |
| 3 | `extensions.py` | فهم db/cache/csrf/limiter/socketio/logging | TODO |
| 4 | `middleware/security_middleware.py` | فهم الحماية العامة | TODO |
| 5 | `permissions_config/blueprint_guards.py` و `acl.py` | فهم الصلاحيات المركزية | TODO |
| 6 | `routes/checks.py` | إكمال فهرسة الدوال وتصنيفها | IN_REVIEW |
| 7 | قوالب الشيكات | فهم الواجهة وربطها بالـ routes | TODO |
| 8 | `routes/payments.py` | دراسة منطق الدفعات | TODO |
| 9 | `routes/ledger_blueprint.py` | دراسة دفتر الأستاذ والقيود | TODO |
| 10 | `routes/expenses.py` | دراسة المصاريف | TODO |
| 11 | `routes/sales.py` | دراسة المبيعات | TODO |
| 12 | `routes/api.py` | تصنيف endpoints العامة والمحمية | TODO |
| 13 | `AI/` | دراسة hooks وملفات الذكاء | TODO |

---

# 14. ملاحظات تشغيلية

- الريبو الحالي هو الإنتاجي، لذلك أي تعديل مستقبلي يجب أن يكون محسوبًا.
- إذا أمكن لاحقًا إنشاء نسخة منفصلة أو فرع عمل مستقر، يكون أفضل.
- إلى حين ذلك، هذا الملف هو مرجع الدراسة والتخطيط.

---

# 15. سجل الإنجاز والعودة لاحقًا

## 15.1 ما تم إنجازه ودمجه

| التاريخ | الملف | الإنجاز | الحالة |
|---|---|---|---|
| 2026-05-15 | `app.py` | دراسة الملف من البداية إلى النهاية على مراحل وتوثيق الملاحظات. | DONE |
| 2026-05-15 | `app.py` | دمج PR #1: تحسين handler 500، CORS، Request ID، إعدادات القوالب، ومسار الشعار. | DONE |
| 2026-05-15 | `app.py` | إصلاح ملاحظة `qodo-code-review[bot]`: فشل `cache.set()` في `inject_system_settings` لا يلغي نتائج قاعدة البيانات. | DONE |
| 2026-05-15 | `docs/SYSTEM_REVIEW_NOTES.md` | تحديث التقرير التراكمي بما تم وما بقي وما سنعود له. | DONE |

## 15.2 ما بقي مؤجلًا من `app.py`

هذه البنود لا يتم تعديلها مباشرة من `app.py` قبل دراسة ملفاتها التابعة:

| البند | السبب | الملف المطلوب دراسته أولًا | الحالة |
|---|---|---|---|
| `csrf.exempt(ledger_bp)` | مرتبط بدفتر الأستاذ وقد يكسر عمليات مالية إذا عُدّل عشوائيًا. | `routes/ledger_blueprint.py` | TODO |
| `login_manager.session_protection = None` | قد يكون بسبب proxy/PythonAnywhere أو جلسات العملاء. | `routes/auth.py`, إعدادات الجلسات, بيئة التشغيل | TODO |
| أسرار التكاملات المحملة من DB | يجب معرفة من يستطيع رؤيتها وتعديلها وهل تُخفى أو تُشفّر. | شاشات الإعدادات/الأمن، `SystemSettings` | TODO |
| تكرار seed/init logic | يوجد أكثر من مصدر تهيئة وقد يؤدي التوحيد العشوائي لكسر أول تشغيل. | `services/system_initializer.py`, `bootstrap_database`, الأدوار والعملات | TODO |
| ACL والصلاحيات المركزية | حماية routes لا تُفهم من `app.py` فقط. | `acl.py`, `permissions_config/blueprint_guards.py` | TODO |
| middleware الأمن العام | يؤثر على كل الطلبات. | `middleware/security_middleware.py` | TODO |

## 15.3 ما سنعود له لاحقًا

بعد دراسة `models.py` والملفات التابعة، نعود إلى:

1. فحص CSRF للـ ledger وإما توثيق سبب الإعفاء أو استبداله بحماية بديلة.
2. فحص session protection وربطه ببيئة التشغيل والصلاحيات.
3. فحص إدارة أسرار integrations في DB وعرضها في الواجهة.
4. توحيد أو ترتيب seed/init بدون كسر التشغيل الأولي.
5. مراجعة ACL والصلاحيات المالية على routes الحساسة.
6. فحص أداء القوالب والصفحات الثقيلة بعد فهم العلاقات في `models.py`.

## 15.4 الخطوة التالية المباشرة

الخطوة التالية هي دراسة:

```text
models.py
```

والهدف منها:

- رسم خريطة الجداول والعلاقات.
- معرفة النماذج المالية الحساسة.
- تحديد أماكن الأرصدة والقيود والدفعات والشيكات.
- معرفة كيف تُخزن إعدادات النظام والأسرار.
- تجهيز دراسة routes المالية لاحقًا بدون تخمين.

---

# 16. مراجعة `models.py`

## 16.1 نطاق المراجعة المنجز حتى الآن

| الجولة | نطاق الأسطر | الحالة | ملاحظات |
|---|---:|---|---|
| 1 | 1–1580 تقريبًا | IN_REVIEW | بداية الملف، event listeners، Archive، الجداول الوسيطة للصلاحيات، enums، SystemSettings، العملات وأسعار الصرف. |
| 2 | 1581–2700 تقريبًا | IN_REVIEW | سياسات الدفعات، Audit/Auth، User/Role/Permission، Customer، GL للرصيد الافتتاحي، بداية Supplier. |
| 3 | 2701–4500 تقريبًا | IN_REVIEW | Supplier، تسويات الموردين، Partner، تسويات الشركاء، بداية Employee، بداية Product. |

## 16.2 ملاحظات الجولة الأولى

| التصنيف | الحالة | المجال | الملاحظة |
|---|---|---|---|
| REVIEW | TODO | SQLAlchemy listeners | يوجد استبدال عام لـ `event.listen` بهدف تتبع وتغليف listeners. مفيد للتشخيص لكنه حساس لأنه يؤثر على كل listeners في الشيكات والدفعات ودفتر الأستاذ. |
| HIGH | TODO | Archive | `Archive.archive_record()` قد يفشل خارج سياق مستخدم إذا لم يتم تمرير `user_id` لأن `archived_by` غير قابل لـ NULL. |
| HIGH | READY | SystemSettings | `set_setting()` يمسح `system_setting_{key}` و`system_settings:bundle:v2` فقط، ولا يمسح كاشات `app.py` الجديدة: `system_settings:template_settings:v1` و`system_settings:module_flags:v1`. |
| MEDIUM | TODO | PaymentMethod | يحتوي قيم lowercase وuppercase للتوافق، ويحتاج تدقيق استعماله في `payments/checks/expenses` لتجنب تضارب `cheque/CHEQUE`. |
| HIGH | TODO | FX | منطق أسعار الصرف داخل `models.py` يجري اتصالات خارجية ويحتوي API key placeholders وخدمات بعضها عبر HTTP. يحتاج فصل أو ضبط واضح قبل الإنتاج. |
| MEDIUM | TODO | FX cache | `_get_rate_cached` يستخدم `lru_cache` يومي، وقد يعطي سعرًا قديمًا بعد إدخال سعر يدوي جديد ما لم يوجد تفريغ للكاش. |
| MEDIUM | TODO | FX auto update | `auto_update_missing_rates()` يقارن `valid_from == today` مع أن `valid_from` DateTime؛ قد لا يكتشف أسعار اليوم بشكل صحيح. |

## 16.3 ملاحظات الجولة الثانية

| التصنيف | الحالة | المجال | الملاحظة |
|---|---|---|---|
| HIGH | TODO | سياسات الدفعات | `validate_payment_policies()` يتحقق من المبلغ ومنع دخل EXPENSE فقط، ثم يترك باقي القيود مفتوحة. هذا يعطي مرونة لكنه يحتاج توافق مع الشيكات والدفعات حتى لا تمر حركات غير منطقية. |
| MEDIUM | TODO | Refund/Receivable | `refundable_amount_for()` و`receivable_amount_for()` يعتمدان على `Payment.total_amount` وحالة الدفعة واتجاهها. يجب تدقيقها مع split payments والشيكات المؤجلة/الراجعة. |
| REVIEW | TODO | AuditMixin | `AuditMixin` يلتقط الحالة السابقة قبل التعديل ويضعها في `_previous_state`. يحتاج تتبع أين تُستخدم هذه القيمة فعليًا وهل تغطي الحقول الحساسة ماليًا. |
| HIGH | TODO | AuthAudit | `_auth_log()` يضيف سجل audit للجلسة لكنه لا يعمل commit بنفسه، وهذا جيد داخل transactions لكنه قد لا يُحفظ إذا فشل الطلب لاحقًا أو حصل rollback. يحتاج قرار: هل audit الأمني يجب أن يلتزم بالمعاملة أم يُحفظ مستقلًا. |
| HIGH | TODO | User / master access | `User.has_permission()` يعطي صلاحيات كاملة لـ `is_system`, super roles, owner, developer. هذا مرتبط مباشرة بالماستر/المالك ويجب مطابقته مع `routes/auth.py`, `utils.is_super`, و`permissions_config`. |
| MEDIUM | TODO | Customer login | `Customer.get_id()` يرجع `c:{id}` وهذا متوافق مع `load_user()` في `app.py`. جيد ويجب الحفاظ عليه عند أي تعديل. |
| MEDIUM | TODO | Customer password | `Customer.password` setter يقبل أي قيمة ويولد hash حتى لو فارغة. يجب تدقيق مسار إنشاء العملاء لمنع كلمات مرور فارغة/افتراضية. |
| HIGH | TODO | Customer balances | `Customer` يحتوي أعمدة أرصدة كثيرة محفوظة مثل `current_balance`, `sales_balance`, `payments_in_balance`, `checks_in_balance`. هذه تحتاج مطابقة مع دوال إعادة الحساب حتى لا تصبح الأرصدة المخزنة مختلفة عن الواقع. |
| HIGH | TODO | Customer hybrid totals | `total_invoiced` و`total_paid` تنفذ استعلامات وتحويل عملة داخل properties، وقد تكون ثقيلة في القوائم وتسبب N+1. |
| HIGH | TODO | Customer opening balance GL | listener `_customer_opening_balance_gl` ينشئ/يحذف قيود GL للرصيد الافتتاحي عند insert/update. حساس جدًا لأنه يلمس دفتر الأستاذ من داخل model event. لا يُعدل قبل فحص GL helpers. |
| MEDIUM | TODO | Customer normalize | يوجد validation للهاتف ويوجد listener normalize أيضًا. يجب التأكد من عدم تضارب السلوكين، خصوصًا أن validation قد يرفض أرقامًا بينما listener ينظفها. |
| REVIEW | TODO | Auto customer for counterparty | `_ensure_customer_for_counterparty()` ينشئ عميلًا تلقائيًا للجهات المقابلة ويستخدم fallback phone من timestamp عند غياب الهاتف. عملي، لكنه قد ينشئ بيانات غير حقيقية تحتاج تمييز واضح في الواجهة. |
| HIGH | TODO | Supplier link to customer | بداية `Supplier` تحتوي `customer_id` لربط تلقائي مع العملاء. يحتاج فهم كامل لأنه قد يؤثر على الأرصدة المشتركة بين supplier/customer. |

## 16.4 ملاحظات الجولة الثالثة

| التصنيف | الحالة | المجال | الملاحظة |
|---|---|---|---|
| HIGH | TODO | Supplier totals | `Supplier.total_paid` يجمع دفعات مباشرة، دفعات loan settlements، ومصاريف المورد. هذا مهم ماليًا وقد يكون ثقيلًا في القوائم، كما يجب مطابقته مع أعمدة الأرصدة المخزنة في `Supplier`. |
| HIGH | TODO | Supplier auto customer | عند إضافة مورد يتم ربط/إنشاء Customer تلقائيًا عبر `supplier_after_insert_create_customer`. هذا يربط كيان مورد بكيان عميل وقد يسبب لبسًا في الأرصدة أو البحث إذا لم تعرض الواجهة مصدر الربط بوضوح. |
| HIGH | TODO | Supplier opening balance GL | `_supplier_opening_balance_gl` ينشئ/يحذف قيود GL للرصيد الافتتاحي للمورد من داخل model event. نفس حساسية Customer GL ويحتاج فحص `_gl_upsert_batch_and_entries`. |
| MEDIUM | TODO | SupplierSettlement code | `SupplierSettlement.ensure_code()` يعتمد على COUNT للأكواد المتطابقة، وقد ينتج تصادم عند عمليات متزامنة إذا لم يُحمَ بقيد unique ومحاولة retry. يوجد unique على `code`، لكن تجربة الخطأ تحتاج معالجة في routes/services. |
| HIGH | TODO | SupplierSettlement confirmation | `before_update` يمنع تأكيد التسوية إذا فيها بنود تحتاج تسعير أو مصادر مستخدمة سابقًا. جيد، لكنه يعتمد على مقارنة `source_type/source_id` عبر استعلامات subquery ويحتاج اختبار فعلي مع NULL source_id. |
| MEDIUM | TODO | SupplierSettlement payments | `SupplierSettlement.total_paid` يعتمد على `Payment.reference == SupplierSettle:{code}`. الاعتماد على نص reference حساس؛ الأفضل لاحقًا وجود FK أو حقل ربط صريح إن أمكن. |
| HIGH | TODO | SupplierLoanSettlement | بعد إدخال تسوية قرض مورد يتم تحديث `ProductSupplierLoan` مباشرة إلى `is_settled=True`. هذا جيد لكنه model event مالي ويحتاج فحص مسارات حذف/تعديل التسوية وهل تعكس حالة القرض. |
| REVIEW | TODO | API helpers in models | توجد دوال `_ok`, `_created`, `_err` داخل `models.py` وتستخدم `jsonify`. هذا خلط طبقات؛ مكانها الطبيعي routes/utils وليس models. لا يعدل الآن لكن يوثق للتنظيم. |
| HIGH | TODO | Partner balances | `Partner` يحتوي أعمدة أرصدة كثيرة مثل `inventory_balance`, `sales_share_balance`, `payments_in/out`, `returned_checks`. تحتاج مطابقة مع محدثات `utils.partner_balance_updater`. |
| HIGH | TODO | Partner auto customer | عند إضافة شريك يتم إنشاء/ربط Customer تلقائيًا كما يحدث مع Supplier. نفس خطر خلط كيان شريك/عميل إذا لم يتم تمييزه بوضوح. |
| HIGH | TODO | Partner opening balance GL | `_partner_opening_balance_gl` يستخدم حساب AP مثل الموردين. يجب التأكد محاسبيًا أن الشريك دائمًا يعامل كالتزام وليس ذمة مختلفة حسب طبيعة الرصيد. |
| MEDIUM | TODO | update_partner_balance | إذا أُمرر connection غير Session، يفتح `db.session.begin()` ويتجاهل connection الفعلي. قد يسبب فصلًا بين transaction الحالية وتحديث الرصيد. |
| HIGH | TODO | PartnerSettlement approval | `PartnerSettlement.after_update` عند `is_approved` يحدّث `partners.opening_balance` إلى `closing_balance` مباشرة. هذا سلوك مالي قوي جدًا ويجب التأكد أنه مقصود ولا يعيد فتح GL opening balance بطريقة غير متوقعة. |
| HIGH | TODO | Partner settlement draft | `build_partner_settlement_draft` يضيف `INVENTORY_SHARE` إلى `total_due` حسب تعليق داخل الكود نفسه. هذا قرار محاسبي حساس: هل يدفع للشريك مقابل المخزون الحالي أم يعرض فقط كمعلومة؟ يحتاج قرار واضح. |
| MEDIUM | TODO | Partner settlement returns | مرتجعات المبيعات تستخدم `Product.selling_price` كقيمة تقريبية عند غياب سعر الإرجاع. قد يعطي تسويات غير دقيقة إذا تغير السعر. |
| HIGH | TODO | Employee totals | خصائص `Employee.total_expenses`, `total_paid`, `total_advances`, `total_deductions` تستخدم استعلامات داخل properties وقد تكون ثقيلة وتسبب N+1 في قوائم الموظفين. |
| REVIEW | TODO | Employee tax logic | `income_tax_amount` يحتوي منطق ضريبة تقريبي وثابت داخل model. يحتاج نقله لإعدادات/خدمة أو توثيق أنه تقديري وليس مرجعًا قانونيًا. |
| MEDIUM | TODO | Employee advance tables | جداول السلف والأقساط موجودة لكن تحتاج فحص routes/services للتأكد من تحديث `installments_paid`, `fully_paid`, و`paid` بشكل متسق. |
| HIGH | TODO | Product unique indexes | `Product` يستخدم unique indexes مشروطة لـ name+warehouse وname global وsku/barcode/serial. جيد في PostgreSQL، لكن يجب التأكد من توافق SQLite/local إن كان يستخدم للتجربة. |
| MEDIUM | TODO | Product pricing fields | توجد حقول أسعار كثيرة: `purchase_price`, `selling_price`, `cost_before_shipping`, `cost_after_shipping`, `unit_price_before_tax`, `price`, `online_price`. تحتاج توحيد معنى كل حقل في routes والقوالب حتى لا يحصل خلط سعر البيع/التكلفة. |

## 16.5 تحسينات مرشحة بعد إكمال `models.py`

لا يتم تنفيذها الآن قبل إنهاء الملف:

1. مسح كاشات `system_settings:template_settings:v1` و`system_settings:module_flags:v1` داخل `SystemSettings.set_setting()`.
2. مراجعة وحصر منطق FX الخارجي وإخراج API placeholders من الكود التشغيلي أو ربطها بإعدادات آمنة.
3. إضافة آلية تفريغ `_get_rate_cached` عند إدخال أو تعديل سعر يدوي.
4. مراجعة سياسات `validate_payment_policies()` مقابل الشيكات والدفعات والمصاريف.
5. فحص listeners التي تكتب GL من داخل models قبل أي تعديل.
6. مراجعة أداء properties الثقيلة في Customer/Supplier/Partner/Employee قبل القوائم والتقارير.
7. فحص سجل AuthAudit وهل يجب أن يحفظ مستقلًا عن معاملات الطلب.
8. مراجعة ربط supplier/customer وpartner/customer التلقائي والبيانات الافتراضية الناتجة عنه.
9. مراجعة تسويات الموردين والشركاء التي تعتمد على `Payment.reference` النصي، والبحث عن ربط أقوى لاحقًا.
10. اتخاذ قرار محاسبي واضح حول إدخال حصة المخزون الحالية في `PartnerSettlement.total_due`.
11. مراجعة منطق تحديث opening_balance للشريك عند اعتماد التسوية.
12. توثيق حقول أسعار المنتج وتوحيد استخدامها في routes والقوالب.

---

آخر تحديث: 2026-05-15
