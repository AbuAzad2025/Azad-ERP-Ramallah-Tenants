# مراجعة شاملة للصلاحيات — تطابق المسميات وإزالة التكرار

## 1. المصدر الوحيد للمسميات

| الملف | الدور |
|-------|--------|
| **`enums.py`** | المصدر الوحيد لأسماء الصلاحيات (`SystemPermissions`) والأدوار (`SystemRoles`). كل قيمة مثل `manage_customers` مُعرّفة مرة واحدة فقط. |
| **`permissions.py`** | تسميات عربية (`PERMISSIONS_AR_MAP`)، وصف الصلاحيات (`PERMISSIONS`)، وأدوار افتراضية (`ROLES`). **لا يُعاد فيه تعريف أسماء الإنكليزية** — يُستخدم الـ enum ك مفتاح. |
| **`utils._PERMISSION_ALIASES`** | توسعة فقط: ربط أسماء قديمة/مرادفة في DB بأسماء الـ enum. المفاتيح مطابقة لـ `SystemPermissions`؛ القيم الإضافية في كل set لأكواد قديمة (توافق رجعي). |
| **`blueprint_guards.py`** | لا يُعرّف أسماء جديدة — يستخدم فقط `SystemPermissions.XXX.value` لـ `attach_acl`. |

---

## 2. التعديلات المنفذة في هذه المراجعة

### إزالة التكرار
- **`permissions_config/permissions.py`**: حذف تكرار المفتاح `MANAGE_BRANCHES` في `PERMISSIONS_AR_MAP` (كان مذكوراً مرتين: مع النظام ومع Branches). بقي تعريف واحد فقط.

### تطابق المسميات
- **`routes/permissions.py` — `permissions_matrix()`**: مقارنة الصلاحيات مع الأدوار كانت بين نوع enum ومجموعة نصوص. تم توحيد المقارنة باستخدام `.value` عند الحاجة (`rp_code = rp.value if hasattr(rp, "value") else rp` وما شابه) لضمان مقارنة نصوص بنصوص.

### القوالب (Templates)
- **`create_sale`** غير موجود في `SystemPermissions`. تم استبداله في القوالب بـ **`manage_sales`** (الصلاحية المناسبة لإنشاء بيع من طلب مسبق):
  - `templates/parts/preorder_detail.html`
  - `templates/parts/preorders_list.html`
- باقي استدعاءات `has_permission` في القوالب تستخدم نصوصاً مطابقة لقيم الـ enum (مثل `manage_service`, `manage_expenses`, `delete_preorder`, `manage_advanced_accounting`) — لا تغيير.

### توثيق الـ Aliases
- **`utils.py`**: إضافة تعليق فوق `_PERMISSION_ALIASES` يوضح أن المفاتيح والأسماء الأساسية من `SystemPermissions`، وأن القيم الإضافية في كل set لأسماء قديمة/مرادفة في DB (توافق رجعي).

---

## 3. قواعد لتجنب التكرار والتناقض

1. **إضافة صلاحية جديدة**: فقط في `enums.SystemPermissions`. ثم (إن لزم) التسمية العربية في `permissions_config/permissions.py` وربطها بالأدوار.
2. **في الـ Routes**: استخدم دائماً `@permission_required(SystemPermissions.XXX)` أو `@utils.permission_required(SystemPermissions.XXX)` — لا نصوص حرفية.
3. **في الـ Blueprints (ACL)**: القيم تأتي من `get_blueprint_guard_config()` في `blueprint_guards.py` فقط، وكلها `SystemPermissions.XXX.value`.
4. **في القوالب**: `current_user.has_permission('...')` — النص يجب أن يساوي بالضبط `SystemPermissions.XXX.value` (مثل `manage_sales` وليس `create_sale`).
5. **في `_PERMISSION_ALIASES`**: المفتاح يجب أن يكون اسم صلاحية من الـ enum؛ القيم الإضافية في الـ set مسموحة لأكواد قديمة في DB فقط.

---

## 4. ملخص الملفات المراجعة

| الملف | التعديل |
|-------|---------|
| `permissions_config/permissions.py` | إزالة تكرار مفتاح `MANAGE_BRANCHES` في `PERMISSIONS_AR_MAP`. |
| `permissions_config/endpoint_access.py` | **مصدر واحد** لـ endpoint → صلاحية (تينانت + منصة). |
| `utils/tenant_permissions.py` | `HUB_*` مرادفات لـ `endpoint_access` — لا تعريف مكرر. |
| `utils/dashboard_routing.py` | يستورد `permission_for_endpoint` فقط. |
| `permissions_config/role_policy.py` | أدوار، مرادف `super`، تدقيق تغطية اللوحات. |
| `scripts/audit_permission_maps.py` | `python scripts/audit_permission_maps.py` — فحص تلقائي. |
| `permissions_config/enums.py` | بدون تغيير — مرجع للمراجعة. |
| `permissions_config/blueprint_guards.py` | بدون تغيير — يستخدم الـ enum فقط. |
| `utils.py` | تعليق توضيحي لـ `_PERMISSION_ALIASES`. |
| `routes/permissions.py` | توحيد مقارنة الصلاحيات في `permissions_matrix()` باستخدام `.value`. |
| `templates/parts/preorder_detail.html` | `create_sale` → `manage_sales`. |
| `templates/parts/preorders_list.html` | `create_sale` → `manage_sales`. |

---

## 5. مرجع سريع: صلاحية واحدة لكل مجال

| المجال | صلاحية القراءة (عرض) | صلاحية الكتابة (تعديل/حذف/إضافة) |
|--------|------------------------|-------------------------------------|
| الزبائن | `MANAGE_CUSTOMERS` | `MANAGE_CUSTOMERS` |
| الموردون/الشركاء | `MANAGE_VENDORS` | `MANAGE_VENDORS` |
| المستودعات | `VIEW_WAREHOUSES` | `MANAGE_WAREHOUSES` |
| الجرد/القطع | `VIEW_PARTS` / `VIEW_INVENTORY` | `MANAGE_INVENTORY` |
| المبيعات | `MANAGE_SALES` | `MANAGE_SALES` |
| الصيانة | `VIEW_SERVICE` | `MANAGE_SERVICE` |
| المدفوعات | `MANAGE_PAYMENTS` | `MANAGE_PAYMENTS` |
| المصاريف | `MANAGE_EXPENSES` | `MANAGE_EXPENSES` |
| التقارير | `VIEW_REPORTS` | `MANAGE_REPORTS` |
| الدفتر/المحاسبة | `MANAGE_LEDGER` | `MANAGE_LEDGER` |
| المستخدمون/الأدوار/الصلاحيات | `MANAGE_USERS` / `MANAGE_ROLES` / `MANAGE_PERMISSIONS` | نفس الصلاحية للكتابة |

لا تُستخدم في نفس المجال صلاحيات مختلفة لنفس الفعل (مثل استخدام `create_sale` بدل `manage_sales`) إلا إذا كان التصميم يفرق صراحة بين عرض وتعديل.
