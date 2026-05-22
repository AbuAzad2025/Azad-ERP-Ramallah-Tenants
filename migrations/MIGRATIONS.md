# ترحيلات قاعدة البيانات (Alembic)

قاعدة واحدة (`public`) + مخططات تينانت (`t_<slug>`). **رأس التسلسل الحالي:** `i9j0k1l2m3n4`.

## تسلسل التهجيرات (مرتب زمنياً)

| # | Revision | الملف | الوصف |
|---|----------|-------|--------|
| 1 | `79cf2ae42e8e` | `79cf2ae42e8e_initial_comprehensive_schema.py` | المخطط الأولي الشامل |
| 2 | `b1a3f0c6d8a9` | `b1a3f0c6d8a9_add_composite_indexes_for_settlements.py` | فهارس مركّبة للتسويات |
| 3 | `c3a0f1b8d2e4` | `c3a0f1b8d2e4_expand_expense_payee_type_constraint.py` | توسيع قيد نوع المستفيد في المصاريف |
| 4 | `d4e5f6a7b8c9` | `d4e5f6a7b8c9_legacy_columns_and_data_backfill.py` | أعمدة legacy + تعبئة بيانات |
| 5 | `e5f6a7b8c9d0` | `e5f6a7b8c9d0_expand_accounts_code_length.py` | توسيع طول كود الحساب |
| 6 | `f6a7b8c9d0e1` | `f6a7b8c9d0e1_expand_gl_entries_ref_length.py` | توسيع مرجع قيود GL |
| 7 | `a7b8c9d0e1f2` | `a7b8c9d0e1f2_expand_gl_entries_account_length.py` | توسيع حساب قيود GL |
| 8a | `10f6c0ee04dc` | `10f6c0ee04dc_check_schema.py` | مزامنة جداول/فهارس (فرع A) |
| 9a | `94948c531c03` | `94948c531c03_add_return_date_to_sale_return.py` | `return_date` على مرتجعات البيع |
| 8b | `b2c3d4e5f6a7` | `b2c3d4e5f6a7_add_tenant_registry_table.py` | جدول `tenants` (سجل التينانت) |
| 10 | `c4d5e6f7a8b9` | `c4d5e6f7a8b9_merge_heads_949_and_tenants.py` | **دمج الرأسين** |
| 11 | `g1h2i3j4k5l6` | `g1h2i3j4k5l6_align_tenants_table_defaults.py` | قيم افتراضية لجدول `tenants` |
| 12 | `i9j0k1l2m3n4` | `i9j0k1l2m3n4_add_fiscal_period_close_tables.py` | إقفال فترات: شهر / ربع / نصف / سنة |

```text
79cf2ae42e8e
  → b1a3f0c6d8a9 → c3a0f1b8d2e4 → d4e5f6a7b8c9 → e5f6a7b8c9d0 → f6a7b8c9d0e1 → a7b8c9d0e1f2
        ├─→ 10f6c0ee04dc → 94948c531c03 ─┐
        └─→ b2c3d4e5f6a7 ────────────────┴─→ c4d5e6f7a8b9 → g1h2i3j4k5l6 → i9j0k1l2m3n4 (head)
```

## أوامر التحقق والتطبيق

```powershell
$env:FLASK_APP = "app:create_app"
.\.venv\Scripts\flask.exe db heads      # يجب: i9j0k1l2m3n4 (head) فقط
.\.venv\Scripts\flask.exe db current    # يجب أن يطابق head
.\.venv\Scripts\flask.exe db upgrade    # تطبيق المتبقي
.\.venv\Scripts\flask.exe db-verify     # فحص public + مخططات التينانت
```

أو: `.\scripts\verify_migrations.ps1`

## إنتاج

```powershell
$env:ALLOW_PRODUCTION_UPGRADE = "1"
.\.venv\Scripts\flask.exe upgrade-production
# أو
.\.venv\Scripts\flask.exe db upgrade
.\.venv\Scripts\flask.exe tenants setup-production   # تهيئة/ختم مخططات التينانت
```

## دمج يدوي (قواعد قديمة برأسين)

إذا كان `alembic_version` على `94948c531c03` أو `b2c3d4e5f6a7` فقط:

```powershell
psql -d garage_manager -f scripts/apply_tenants_migration.sql
.\.venv\Scripts\flask.exe db upgrade
```

## قواعد العمل

1. **لا** ترفع ملفات `flask db migrate` التلقائية الضخمة (فروق أسماء فهارس فقط).
2. كل تهجير جديد: `down_revision` = الرأس الحالي، وصف واضح في اسم الملف.
3. بعد `db upgrade` على `public`: ختم مخططات التينانت بـ `flask tenants setup-production` أو أمر `tenants provision`.
4. جدول `alembic_version` في كل مخطط تينانت يجب أن يساوي رأس `public`.
