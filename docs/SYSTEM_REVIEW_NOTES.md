# ملاحظات ومتابعة مراجعة نظام AzadAccounting-sys

هذا الملف هو المرجع المركزي لما تم إنجازه، وما بقي، وما يجب الرجوع إليه لاحقًا. لا يتم الاعتماد على الذاكرة أو الكلام في المحادثة فقط؛ أي قرار أو ملاحظة مهمة يجب أن تظهر هنا.

## قواعد العمل الثابتة

- لا يتم تعديل ملفات ضخمة أو مالية دفعة واحدة.
- لا يتم إنشاء ملفات جديدة إلا للضرورة.
- لا يتم استبدال ملف كامل إذا أمكن تعديل موضعي صغير.
- لا يتم لمس GL أو المخزون أو الشيكات أو الدفعات أو الماستر كي إلا بعد مراجعة دقيقة واختبار.
- أي تعديل يجب أن يكون على فرع منفصل أو PR واضح قبل الدمج.
- الريبو الإنتاجي حساس، لذلك الأولوية للتغييرات الصغيرة القابلة للفحص.

## رموز الحالة

| الحالة | المعنى |
|---|---|
| DONE | تم إنجازه ودمجه أو توثيقه نهائيًا |
| IN_PROGRESS | قيد التنفيذ على فرع/PR |
| READY | جاهز كتعديل صغير آمن نسبيًا |
| TODO | لم يبدأ بعد |
| DEFERRED | مؤجل عمدًا لأنه يحتاج اختبار أو مراجعة ملف تابع |
| BLOCKED | متعطل بسبب أداة/صلاحية/مخاطرة تقنية |

---

# 1. المنجز حتى الآن

## 1.1 `app.py`

| البند | الحالة | التفاصيل |
|---|---|---|
| مراجعة `app.py` من البداية للنهاية | DONE | تمت دراسة ملف التشغيل المركزي وتوثيق علاقته بالـ blueprints، الصلاحيات، CORS، الكاش، الإعدادات، وAI startup. |
| PR #1 `Safe app.py hardening batch` | DONE | تم دمجه إلى `main`. |
| منع كشف traceback في الإنتاج | DONE | خطأ 500 صار يرجع رسالة عامة و`request_id`، مع بقاء التفاصيل في logs والتطوير. |
| حماية CORS مع credentials | DONE | تم منع الحالة غير الآمنة عند `CORS_ORIGINS=*` مع credentials. |
| تنظيف `X-Request-Id` | DONE | منع القيم الطويلة أو غير النظيفة في headers/logs. |
| تحسين `inject_system_settings` | DONE | قراءة إعدادات القوالب دفعة واحدة بدل استعلام لكل مفتاح. |
| تنظيف `custom_logo` | DONE | منع روابط خارجية ومسارات `..` والرجوع إلى شعار افتراضي آمن. |
| إصلاح ملاحظة qodo | DONE | فشل `cache.set()` لم يعد يلغي القيم المقروءة من قاعدة البيانات. |

## 1.2 `models.py`

| البند | الحالة | التفاصيل |
|---|---|---|
| مراجعة `models.py` من البداية للنهاية | DONE | تمت مراجعة الملف كاملًا تقريبًا من السطر 1 حتى نهاية الملف على 7 جولات. |
| توثيق الجولات | DONE | تم توثيق المجالات: SystemSettings، FX، Auth/User/Customer، Supplier/Partner، Product/Stock، Sale/Invoice، Payment/Split، Shipment/Service، Expense/GL/Audit/Check، SaaS/Budget/Assets/Projects/Workflow/Balance queues. |
| تحديد التصحيحات الآمنة | DONE | تم استخراج قائمة أولية لتغييرات صغيرة لا تمس GL أو المخزون. |
| تحديد التصحيحات الخطرة | DONE | تم فصل البنود التي تحتاج اختبار مالي/مخزون قبل أي تعديل. |

## 1.3 PR #2 الحالي

| البند | الحالة | التفاصيل |
|---|---|---|
| الفرع `review/safe-models-fixes` | IN_PROGRESS | فرع مخصص للتصحيحات الآمنة التالية. |
| PR #2 `Safe system hardening batch 1` | IN_PROGRESS | مفتوح كـ Draft ولم يتم دمجه بعد. |
| حماية `/health/metrics` | IN_PROGRESS | تم تعديل `routes/health.py` على الفرع فقط، وليس على `main` بعد. |
| تنظيف `/health/ready` | IN_PROGRESS | لم يعد يرجع نص الاستثناء الخام للعامة على الفرع. |
| تنظيف أخطاء فحص health | IN_PROGRESS | disk/memory/socket/system أصبحت ترجع رموز خطأ عامة بدل تفاصيل داخلية. |
| حجم تغيير PR #2 الحالي | IN_PROGRESS | ملف واحد فقط: `routes/health.py`، فرق تقريبي `+18 / -8`. |

---

# 2. ما بقي من `app.py`

هذه البنود متبقية لكنها لا تعدل من `app.py` مباشرة قبل دراسة الملفات التابعة:

| الأولوية | الحالة | البند | سبب التأجيل | أين نعود له |
|---|---|---|---|---|
| HIGH | TODO | `csrf.exempt(ledger_bp)` | مرتبط بدفتر الأستاذ وقد يكسر عمليات مالية إذا أزيل عشوائيًا. | بعد دراسة `routes/ledger_blueprint.py`. |
| MEDIUM | TODO | `login_manager.session_protection = None` | قد يكون مرتبطًا ببيئة PythonAnywhere/proxy أو جلسات الزبائن. | بعد دراسة `routes/auth.py` والجلسات. |
| HIGH | TODO | أسرار التكاملات من DB | يجب معرفة من يستطيع رؤيتها وتعديلها وهل تعرض في الواجهة. | `SystemSettings` + شاشات security/settings. |
| MEDIUM | TODO | تكرار seed/init logic | يوجد `SystemInitializer`, إضافة العملات، إضافة الأدوار، و`bootstrap_database`. | بعد دراسة `services/system_initializer.py`. |
| HIGH | TODO | ACL والصلاحيات المركزية | حماية routes لا تفهم من `app.py` وحده. | `acl.py` و`permissions_config/blueprint_guards.py`. |
| HIGH | TODO | middleware الأمن العام | يؤثر على كل الطلبات. | `middleware/security_middleware.py`. |

---

# 3. التصحيحات الآمنة الجاهزة بعد PR #2 أو ضمنه

هذه تغييرات صغيرة نسبيًا، ولا تلمس GL أو المخزون أو الدفعات:

| الأولوية | الحالة | الملف | التصحيح المقترح | ملاحظات |
|---|---|---|---|---|
| HIGH | READY | `models.py` | تحديث `SystemSettings.set_setting()` لمسح كاشات `system_settings:template_settings:v1` و`system_settings:module_flags:v1`. | مهم حتى تظهر تغييرات الإعدادات فورًا بدل انتظار انتهاء الكاش. |
| MEDIUM | READY | `models.py` أو helper صغير | توحيد fallback لاسم الشركة بين `COMPANY_NAME`, `company_name`, `CompanyName`. | مهم لأن الشيكات وبعض القوالب قد تستخدم مفاتيح مختلفة. |
| MEDIUM | READY | `config.py` | تخفيف defaults لـ SQLAlchemy pool وpagination بتعديل موضعي صغير فقط. | محاولة استبدال الملف كاملًا رفضتها الأداة بسبب وجود إعدادات حساسة؛ المطلوب patch صغير لا استبدال كامل. |
| HIGH | READY | `routes/api.py` | جعل `/api/health` عامًا وبسيطًا بدون counts تجارية، أو نقل counts إلى endpoint محمي. | يحسن الخصوصية والأداء. |
| MEDIUM | READY | `models.py` | إزالة/تعليق كود ميت واضح مثل الجزء بعد `return` في `_gl_on_service_complete` بعد تأكيده. | تنظيف فقط إن ثبت أنه غير مستخدم. |
| LOW | READY | التوثيق/تعليقات داخلية | توثيق معنى حقول أسعار المنتج: `purchase_price`, `selling_price`, `price`, `online_price`, وغيرها. | لا نغير الحسابات الآن. |

---

# 4. الشيكات — ما بقي

تمت ملاحظات أولية فقط، ولم يتم تعديل منطق الشيكات.

| الأولوية | الحالة | البند | ملاحظات |
|---|---|---|---|
| CRITICAL | DEFERRED | `CheckActionService.run` | قلب تغيير حالة الشيك. لا يلمس قبل اختبار. |
| CRITICAL | DEFERRED | GL الشيكات | `create_gl_entry_for_check`, `_process_check_gl_queue`, `_create_check_gl_after_commit`, `_check_gl_batch_reverse`. |
| CRITICAL | DEFERRED | إنشاء الدفعة التلقائي | `_check_create_payment_auto` حساس لأنه ينشئ دفعة عند إنشاء شيك يدوي. |
| HIGH | READY | صلاحيات routes الشيكات | `update_check_status`, `add_check`, `edit_check`, `check_detail`, `reports`, `get_first_incomplete_check`, `get_check_lifecycle`. |
| HIGH | READY | validation إضافة/تعديل الشيك | المبلغ، الاتجاه، البنك، الرقم، التاريخ، والجهة. بدون لمس GL. |
| HIGH | TODO | أداء قوائم الشيكات | `get_checks()`, `reports()`, `get_statistics()` تحتاج pagination واستعلامات أخف. |

---

# 5. `models.py` — أهم ما بقي حسب الخطورة

## 5.1 إعدادات وكاش

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | READY | `SystemSettings.set_setting()` لا يمسح كاشات `app.py` الجديدة. |
| MEDIUM | READY | عدم اتساق مفاتيح اسم الشركة بين `COMPANY_NAME`, `company_name`, `CompanyName`. |
| HIGH | TODO | أسرار integrations داخل DB تحتاج فحص عرض/تعديل/إخفاء. |

## 5.2 FX والعملات

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | TODO | منطق FX داخل `models.py` يجري اتصالات خارجية ويحتوي placeholders وخدمات بعضها عبر HTTP. |
| MEDIUM | TODO | `_get_rate_cached` قد يعطي سعرًا قديمًا بعد إدخال سعر يدوي. |
| MEDIUM | TODO | `auto_update_missing_rates()` يقارن DateTime بتاريخ فقط وقد يفشل في التقاط سعر اليوم. |

## 5.3 المستخدمون والأمان

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | TODO | `User.has_permission()` يعطي صلاحيات كاملة لـ `is_system`, owner, developer, super roles؛ يجب مطابقته مع auth وutils. |
| HIGH | TODO | `AuthAudit` داخل نفس transaction وقد يختفي مع rollback. |
| MEDIUM | TODO | `Customer.password` قد يقبل قيمة فارغة حسب مسار الاستدعاء. |
| HIGH | IN_REVIEW | الماستر كي يبقى يعمل، لكن يحتاج audit وحماية من كشف السر. |

## 5.4 الزبائن والموردون والشركاء

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | TODO | أعمدة الأرصدة المخزنة في Customer/Supplier/Partner تحتاج مطابقة مع دوال إعادة الحساب. |
| HIGH | TODO | properties مثل `total_paid`, `total_invoiced`, employee totals قد تسبب N+1. |
| HIGH | DEFERRED | opening balance GL للزبون/المورد/الشريك يكتب قيود GL من داخل model events. |
| HIGH | TODO | الربط التلقائي Supplier/Partner مع Customer قد يخلط الكيانات إن لم يظهر بوضوح. |
| HIGH | DEFERRED | اعتماد PartnerSettlement يغير `opening_balance` للشريك مباشرة. |

## 5.5 المخزون والمنتجات

| الأولوية | الحالة | البند |
|---|---|---|
| MEDIUM | READY | توثيق وتوحيد معنى حقول الأسعار العديدة داخل Product. |
| HIGH | DEFERRED | reservation policy غير موحدة: بعض checks معلقة لكن `available_quantity` ما زال يطرح المحجوز. |
| HIGH | DEFERRED | Stock events وTransfer events تعدل المخزون مباشرة وتحتاج اختبار. |
| HIGH | DEFERRED | `_apply_stock_delta` قد يغير المخزون حتى لو فشل تسجيل StockMovement لأن الخطأ يبتلع. |

## 5.6 المبيعات والمرتجعات والفواتير

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | DEFERRED | `SaleReturnLine.after_update` قد يضيف كامل الكمية للمخزون بدل الفرق فقط. |
| HIGH | DEFERRED | منطق damaged return يستخدم `Product.cost_price` مع احتمال عدم وجود الحقل. |
| HIGH | DEFERRED | خطر تضارب أو ازدواج GL في SaleReturn. |
| HIGH | DEFERRED | Sale GL وحساب VAT/COGS/partner shares حساس. |
| HIGH | DEFERRED | علاقة Invoice payments فيها `cascade=all, delete-orphan` وقد تحذف دفعات عند حذف فاتورة. |

## 5.7 الدفعات وPaymentSplit

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | DEFERRED | `Payment.entity` قد يرمي ValueError إذا الرابط ناقص. |
| HIGH | DEFERRED | Payment transitions مثل COMPLETED → FAILED/CANCELLED حساسة جدًا. |
| HIGH | DEFERRED | Payment GL يتخطى manual checks وsplits ويجب توثيق مصدر GL النهائي. |
| HIGH | DEFERRED | إنشاء Check تلقائيًا من cheque payment يبتلع الأخطاء. |
| HIGH | DEFERRED | PaymentSplit GL وحالة FAILED تحتاج اختبار حتى لا تبقى قيود قديمة. |
| HIGH | DEFERRED | `_update_sale_payment_totals` قد يتجاهل splits والعملات والشيكات الراجعة. |

## 5.8 الصيانة والخدمات

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | DEFERRED | `ServiceRequest.total_paid` قد يحتسب دفعات PENDING/FAILED إذا لم يفلتر status. |
| HIGH | DEFERRED | اختلاف معنى `total`, `total_amount`, والضريبة في الصيانة. |
| LOW | READY | كود ميت واضح بعد `return` في `_gl_on_service_complete` بعد تأكيده. |
| MEDIUM | TODO | transitions الصيانة لا تغطي كل الحالات الظاهرة في النظام. |

## 5.9 الأونلاين والبطاقات

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | DEFERRED | `OnlinePayment` قد يخزن رقم البطاقة كاملًا مشفرًا ويحتوي `decrypt_card_number`; هذا موضوع PCI حساس. |
| HIGH | DEFERRED | fingerprint للبطاقة SHA256 مباشر للـ PAN بدون HMAC/salt. |
| HIGH | DEFERRED | OnlinePreOrder GL يستخدم كامل total_amount وليس المدفوع الفعلي دائمًا. |

## 5.10 المشاريع والهندسة

| الأولوية | الحالة | البند |
|---|---|---|
| HIGH | DEFERRED | `ProjectCost.after_update` و`ProjectRevenue.after_update` قد يضيفان كامل المبلغ مرة أخرى بدل delta. |
| HIGH | DEFERRED | `ProjectRevenue` قد يحدث `project_phases.actual_cost` بدل revenue. |
| HIGH | DEFERRED | `ResourceTimeLog.after_update` و`ChangeOrder.after_update` قد يسببان double counting. |
| MEDIUM | TODO | TimeLog ينشئ ProjectCost عند approval لكنه لا يحدثه إذا تغيرت التكلفة لاحقًا. |

---

# 6. ما لا نلمسه الآن

هذه البنود مؤجلة عمدًا لأنها قد تخرب الحسابات أو المخزون إن عُدلت بدون سيناريوهات اختبار:

- GL الشيكات والدفعات.
- PaymentSplit GL.
- Sale/SaleReturn GL.
- Stock reservation وTransfer stock deltas.
- SaleReturn stock update.
- Project double counting.
- OnlinePayment card storage.
- تغيير `csrf.exempt(ledger_bp)`.
- تعطيل أو تعديل الماستر كي.
- posted GL immutability.

---

# 7. ترتيب العمل القادم المقترح

| الترتيب | الحالة | المهمة | السبب |
|---|---|---|---|
| 1 | IN_PROGRESS | إكمال PR #2 وفحصه | يحتوي تصحيح health آمن ومحدود. |
| 2 | READY | إضافة تصحيح `SystemSettings.set_setting()` لمسح كاشات app.py | أثره واضح وآمن ولا يمس المال. |
| 3 | READY | حماية/تبسيط `/api/health` | يمنع كشف counts تجارية للعامة. |
| 4 | READY | تصحيح config defaults بتعديل صغير فقط | مناسب لـ PythonAnywhere ومستخدمين أقل من 100، لكن لا يتم استبدال الملف كاملًا. |
| 5 | READY | صلاحيات وvalidation الشيكات بدون GL | يحسن الحماية دون لمس المنطق المحاسبي. |
| 6 | TODO | دراسة `routes/payments.py` | لفهم Payment/Split قبل أي تعديل مالي. |
| 7 | TODO | دراسة `routes/sales.py` و`routes/sale_returns.py` | قبل إصلاح المخزون وSaleReturn. |
| 8 | TODO | دراسة `routes/ledger_blueprint.py` | لحسم CSRF exemption. |

---

# 8. روابط وفروع مهمة

| العنصر | الحالة | الرابط/الاسم |
|---|---|---|
| PR #1 | DONE/MERGED | `Safe app.py hardening batch` |
| PR #2 | IN_PROGRESS/DRAFT | `Safe system hardening batch 1` |
| فرع PR #2 | IN_PROGRESS | `review/safe-models-fixes` |
| الفرع الرئيسي | ACTIVE | `main` |

---

آخر تحديث: 2026-05-16
