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

## 2.1 تضخم بعض ملفات routes

| التصنيف | الحالة | الملفات |
|---|---|---|
| HIGH | TODO | `routes/checks.py`, وربما `routes/payments.py`, `routes/api.py` |

بعض الملفات تجمع بين routes و business logic و event listeners وعمليات محاسبية. هذا يزيد صعوبة الصيانة وخطورة أي تعديل.

### التوصية

عدم إعادة البناء الآن. فقط توثيق الدوال الحساسة، ثم إصلاحات صغيرة عند الحاجة.

## 2.2 ملفات مالية حساسة

| التصنيف | الحالة | الملفات |
|---|---|---|
| CRITICAL | IN_REVIEW | الشيكات، الدفعات، المصاريف، دفتر الأستاذ، المبيعات |

أي تعديل في هذه الملفات قد يؤثر على الأرصدة والقيود والدفعات.

### التوصية

الدراسة أولًا، ثم تعديل صغير واحد فقط في كل مرة.

## 2.3 وجود AI hooks

| التصنيف | الحالة | الملفات |
|---|---|---|
| REVIEW | TODO | `AI/__init__.py`, `AI/engine/*` |

يوجد ربط تلقائي لبعض طبقات AI عند تحميل المجلد. يجب معرفة ما الذي يعمل فعليًا وما الذي هو مراقبة فقط.

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
| `has_perm` و `has_any` في القوالب | HIGH | TODO | ممتاز للواجهة، لكن لا يغني عن حماية backend routes. يجب التأكد أن routes الحساسة عليها decorators. |

## 3.3 الأسطر 521–840

| الجزء | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| `inject_enums()` | LOW | DONE | يجعل حالات النظام متاحة للقوالب. جيد ويعتمد على اتساق enums في `models.py`. |
| `url_for_any()` | MEDIUM | TODO | مفيد لتقليل كسر القوالب، لكنه قد يخفي أخطاء routing في الإنتاج إذا لم يكن `STRICT_URLS` مفعّلًا. |
| فلاتر العملات والأرقام والتواريخ | LOW | DONE | مهمة للعرض المالي. |
| `get_setting` داخل Jinja globals | MEDIUM | TODO | يجب التأكد أن `SystemSettings.get_setting` لديه cache أو لا يسبب استعلامات كثيرة داخل القوالب. |
| `translations/accounting_ar.py` | LOW | TODO | الترجمات تُحمّل مرة عند الإعداد. جيد، لكن الملف يحتاج دراسة لاحقة. |
| `amount_in_words` | LOW | TODO | مفيد للطباعة، لكن ليس عربيًا قانونيًا مثاليًا في كل حالات التثنية والجمع. تحسين لاحق. |
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
| `_register_cors()` | HIGH | TODO | CORS مخصص لـ `/api/*` فقط. يجب التأكد من إعداد `CORS_ORIGINS` وعدم استخدام wildcard مع credentials في الإنتاج. |
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
| attach ACL على Blueprints | HIGH | TODO | مصدر مهم للصلاحيات. يجب دراسة `permissions_config.blueprint_guards.py` و `acl.py`. |
| تحميل إعدادات البريد والتكاملات من DB | MEDIUM | TODO | يسمح للوحة التحكم بتجاوز env. جيد، لكنه يعني أن أسرار integrations قد تكون في DB وتحتاج حماية. |
| `_touch_last_seen` | LOW | IN_REVIEW | يبدأ بعد هذا المقطع، ويحتاج متابعة في الجزء التالي. |

## 3.5 ملفات تابعة لـ `app.py` يجب دراستها لاحقًا

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

## قرار حالي

لا تطوير AI جديد قبل فهم النظام الأساسي.

---

# 11. الأمن والصلاحيات

## ملاحظات عامة

| المجال | التصنيف | الحالة | الملاحظة |
|---|---|---|---|
| صلاحيات routes المالية | CRITICAL | TODO | يجب مراجعة الشيكات والدفعات والمصاريف والدفتر. |
| CSRF exemptions | HIGH | TODO | يجب توثيق أي إعفاء ولماذا موجود. |
| master key | HIGH | IN_REVIEW | يبقى يعمل، مع audit وحماية جلسة. |
| حذف مالي مباشر | HIGH | TODO | الحذف في الملفات المالية يجب مراجعته، والأفضل الأرشفة أو القيود العكسية. |

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
| 1 | `app.py` | إنهاء دراسة ملف التشغيل المركزي | IN_REVIEW |
| 2 | `models.py` | خريطة الجداول والعلاقات | TODO |
| 3 | `routes/checks.py` | إكمال فهرسة الدوال وتصنيفها | IN_REVIEW |
| 4 | قوالب الشيكات | فهم الواجهة وربطها بالـ routes | TODO |
| 5 | `routes/payments.py` | دراسة منطق الدفعات | TODO |
| 6 | `routes/ledger_blueprint.py` | دراسة دفتر الأستاذ والقيود | TODO |
| 7 | `routes/expenses.py` | دراسة المصاريف | TODO |
| 8 | `routes/sales.py` | دراسة المبيعات | TODO |
| 9 | `routes/api.py` | تصنيف endpoints العامة والمحمية | TODO |
| 10 | `AI/` | دراسة hooks وملفات الذكاء | TODO |

---

# 14. ملاحظات تشغيلية

- الريبو الحالي هو الإنتاجي، لذلك أي تعديل مستقبلي يجب أن يكون محسوبًا.
- إذا أمكن لاحقًا إنشاء نسخة منفصلة أو فرع عمل مستقر، يكون أفضل.
- إلى حين ذلك، هذا الملف هو مرجع الدراسة والتخطيط.

---

آخر تحديث: 2026-05-15
