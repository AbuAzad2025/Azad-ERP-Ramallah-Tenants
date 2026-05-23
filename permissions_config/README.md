# الصلاحيات — مصدر واحد وعدم تناقض

## المصدر الوحيد لأسماء الصلاحيات

- **`enums.py`** — تعريف `SystemPermissions` و `SystemRoles`. كل اسم صلاحية (مثل `manage_customers`) موجود هنا فقط كـ `value` للـ enum.
- **لا تُكتَب أسماء الصلاحيات كـ strings مبعثرة** في الـ routes أو في `app.py`. استخدم دائماً `SystemPermissions.XXX` (وفي الـ ACL نستخدم `.value` عند الحاجة لـ string).

## أين تُستخدَم الصلاحيات

| المكان | الاستخدام |
|--------|-----------|
| **Blueprint (طبقة عامة)** | `permissions_config/blueprint_guards.py` — يحدد صلاحية القراءة/الكتابة لكل blueprint. `app.py` يستدعي `attach_acl(bp, **opts)` من خلال `get_blueprint_guard_config()` فقط. |
| **Route (دالة محددة)** | استخدم `@permission_required(SystemPermissions.XXX)` من `utils`. استورد: `from utils import permission_required` و `from permissions_config.enums import SystemPermissions`. |
| **قالب Jinja** | `current_user.has_permission(SystemPermissions.XXX)` — نفس الـ enum. |
| **ACL (acl.py)** | `attach_acl(bp, read_perm=..., write_perm=...)` — القيم تأتي من `blueprint_guards.py` وهي `SystemPermissions.XXX.value`. |

## تجنّب التناقض

1. **صلاحية واحدة لكل مجال**: مثلاً إدارة الزبائن = `MANAGE_CUSTOMERS` في كل من الـ blueprint والـ routes والـ templates. لا تستخدم `VIEW_CUSTOMERS` في route والـ blueprint يستخدم `MANAGE_CUSTOMERS` للقراءة إلا إذا كان المقصود فعلاً تخفيف الصلاحية على مستوى الـ blueprint.
2. **التوسعة (aliases)** في `utils._PERMISSION_ALIASES`: تُستخدم لربط أسماء قديمة أو مرادفات (مثل `add_customer` → `manage_customers`). لا تضف فيها صلاحيات جديدة غير موجودة في `enums.SystemPermissions`.
3. **إضافة صلاحية جديدة**: أضفها في `enums.SystemPermissions` فقط، ثم أضف التسمية العربية في `permissions_config/permissions.py` إن لزم، واستخدمها في الـ guards أو الـ routes من خلال الـ enum فقط.

4. **لا تستخدم نصوصاً حرفية للصلاحية** (مثل `'manage_system_settings'`) — لا يوجد لها تعريف في `SystemPermissions` فتنشأ تناقضات. استخدم دائماً `SystemPermissions.XXX`.

## ملخص الملفات

- `enums.py` — تعريف الصلاحيات والأدوار (المصدر الوحيد للأسماء).
- `blueprint_guards.py` — مصدر واحد لـ `attach_acl` لكل blueprint (باستخدام `SystemPermissions` فقط).
- `permissions.py` — تسميات عربية، أدوار افتراضية، وربط الصلاحيات بالأدوار (للعرض والـ bootstrap).
- الـ routes — استيراد `permission_required` من `utils` و `SystemPermissions` من `permissions_config.enums`.
