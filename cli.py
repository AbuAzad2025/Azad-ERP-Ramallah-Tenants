# cli.py - Command Line Interface
# Location: /garage_manager/cli.py
# Description: Command line tools and utilities

from __future__ import annotations

import json, os, re, uuid, traceback, sqlite3, hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import click
from flask.cli import with_appcontext
from sqlalchemy import func, or_, select, text as sa_text, delete as sa_delete, bindparam, inspect, MetaData, Table
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from extensions import db
from utils import clear_role_permission_cache, clear_users_cache_by_role, get_entity_balance_in_ils, validate_currency_consistency
from utils.balance_calculator import build_customer_balance_view
from utils.customer_balance_updater import update_customer_balance_components
from utils.supplier_balance_updater import update_supplier_balance_components, build_supplier_balance_view
from utils.partner_balance_updater import update_partner_balance_components, build_partner_balance_view
from permissions_config.permissions import PermissionsRegistry
from models import (
    Account, AuditLog, Branch, Site, Check, CheckStatus, Customer, Employee, ExchangeTransaction, Expense, ExpenseType, GLBatch,
    GLEntry, GL_ACCOUNTS, Invoice, Note, OnlineCart, OnlineCartItem, OnlinePayment, OnlinePreOrder, OnlinePreOrderItem,
    Partner, PartnerSettlement, Payment, PaymentDirection, PaymentEntityType, PaymentMethod, PaymentStatus, Permission,
    PreOrder, Product, ProductCategory, Role, Sale, SaleLine, ServicePart, ServiceRequest, ServiceStatus, ServiceTask,
    Shipment, ShipmentItem, ShipmentStatus, StockAdjustment, StockAdjustmentItem, StockLevel, Supplier,
    SupplierSettlement, Transfer, TransferDirection, Warehouse, _ensure_customer_for_counterparty, _gl_upsert_batch_and_entries,
    build_partner_settlement_draft, build_supplier_settlement_draft, convert_amount, User,
    TenantRegistry,
    role_permissions,
)

RESERVED_CODES = PermissionsRegistry.get_all_permission_codes()

def _get_perm_name_ar(code: str) -> str:
    perm_info = PermissionsRegistry.get_permission_info(code)
    return perm_info.get('name_ar', code) if perm_info else code

def _parse_dt(val: str | None, end: bool = False):
    """تحويل التاريخ من نص إلى datetime"""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.strip())
        if end:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except Exception:
        return None

_SKIP_SEED_ROLE_SYNC = frozenset({"owner", "developer", "super_admin", "super"})


def _standard_role_permission_codes() -> dict[str, set[str]]:
    """أدوار المنصة القياسية — من السجل فقط (بدون تكرار يدوي)."""
    return {
        role_name: PermissionsRegistry.get_role_permissions(role_name)
        for role_name in PermissionsRegistry.ROLES.keys()
        if role_name not in _SKIP_SEED_ROLE_SYNC
    }


ROLE_PERMISSIONS = _standard_role_permission_codes()

OWNER_USERNAME = os.getenv("OWNER_USERNAME", "owner").strip()
OWNER_EMAIL = (os.getenv("OWNER_EMAIL", "owner@example.com") or "").strip().lower()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "OWNER123")

DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "developer").strip()
DEVELOPER_EMAIL = (os.getenv("DEVELOPER_EMAIL", "developer@example.com") or "").strip().lower()
DEVELOPER_PASSWORD = os.getenv("DEVELOPER_PASSWORD", "DEV123")

SUPER_USERNAME = os.getenv("SUPER_ADMIN_USERNAME","azad").strip()
SUPER_EMAIL = (os.getenv("SUPER_ADMIN_EMAIL","rafideen.ahmadghannam@gmail.com") or "").strip().lower()
SUPER_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD","AZ123456")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME","admin").strip()
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL","admin@example.com") or "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD","ADMIN123")

MANAGER_USERNAME = os.getenv("MANAGER_USERNAME","manager").strip()
MANAGER_EMAIL = (os.getenv("MANAGER_EMAIL","manager@example.com") or "").strip().lower()
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD","MANAGER123")
STAFF_USERNAME = os.getenv("STAFF_USERNAME","staff").strip()
STAFF_EMAIL = (os.getenv("STAFF_EMAIL","staff@example.com") or "").strip().lower()
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD","STAFF123")
MECH_USERNAME = os.getenv("MECHANIC_USERNAME","mechanic").strip()
MECH_EMAIL = (os.getenv("MECHANIC_EMAIL","mechanic@example.com") or "").strip().lower()
MECH_PASSWORD = os.getenv("MECHANIC_PASSWORD","MECH123")
RC_USERNAME = os.getenv("REGISTERED_CUSTOMER_USERNAME","customer").strip()
RC_EMAIL = (os.getenv("REGISTERED_CUSTOMER_EMAIL","customer@example.com") or "").strip().lower()
RC_PASSWORD = os.getenv("REGISTERED_CUSTOMER_PASSWORD","CUST123")

def _normalize_code(s: str | None) -> str | None:
    if not s: return None
    s = re.sub(r"_+","_",re.sub(r"[^a-z0-9_]+","",re.sub(r"[\s\-]+","_",s.strip().lower()))).strip("_")
    return s or None

def _D(x):
    try: return Decimal(str(x))
    except Exception: return Decimal("0")
def _Q2(x): return _D(x).quantize(Decimal("0.01"), ROUND_HALF_UP)

def _clean_role_perms(role: Role) -> None:
    if getattr(role, "permissions", None) is None:
        role.permissions = []
        return
    perms = [p for p in role.permissions if isinstance(p, Permission)]
    seen: set[int] = set()
    unique: list[Permission] = []
    for p in perms:
        pid = getattr(p, "id", None)
        if not pid:
            unique.append(p)
            continue
        if pid in seen:
            continue
        seen.add(pid)
        unique.append(p)
    role.permissions[:] = unique

def _dedupe_role_permissions_in_place(role: Role) -> None:
    if getattr(role, "permissions", None) is None:
        role.permissions = []
        return
    perms = [p for p in role.permissions if isinstance(p, Permission)]
    seen: set[int] = set()
    unique: list[Permission] = []
    for p in perms:
        pid = getattr(p, "id", None)
        if not pid:
            unique.append(p)
            continue
        if pid in seen:
            continue
        seen.add(pid)
        unique.append(p)
    role.permissions[:] = unique


@click.command("import-sqlite-appdb")
@click.option("--sqlite-path", default=os.path.join("instance", "app.db"), show_default=True)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@with_appcontext
def import_sqlite_appdb(sqlite_path: str, dry_run: bool, force: bool):
    allow = os.getenv("ALLOW_SQLITE_IMPORT", "").strip() == "1"
    if not (force or allow):
        raise click.ClickException("ارفع ALLOW_SQLITE_IMPORT=1 أو استخدم --force")

    abs_path = sqlite_path
    if not os.path.isabs(abs_path):
        abs_path = os.path.abspath(abs_path)
    if not os.path.exists(abs_path):
        raise click.ClickException(f"ملف SQLite غير موجود: {abs_path}")

    con = sqlite3.connect(abs_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    sqlite_tables = {r[0] for r in cur.fetchall()}
    required = {"branches", "sites", "expense_types", "employees", "expenses"}
    missing = sorted(required - sqlite_tables)
    if missing:
        raise click.ClickException(f"جداول ناقصة في SQLite: {', '.join(missing)}")

    existing_user_ids = {row[0] for row in db.session.execute(sa_text("select id from users")).fetchall()}

    def _parse_dt2(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v))
        s = str(v).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    def _parse_date2(v):
        dt = _parse_dt2(v)
        return dt.date() if dt else None

    def _coerce_value(col, v):
        if v is None:
            return None
        col_type = col.type.__class__.__name__.lower()
        if "datetime" in col_type:
            return _parse_dt2(v)
        if col_type == "date":
            return _parse_date2(v)
        if "boolean" in col_type:
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "y", "t")
            return bool(int(v)) if isinstance(v, (int, float)) else bool(v)
        if "numeric" in col_type or "decimal" in col_type:
            try:
                return Decimal(str(v))
            except Exception:
                return None
        return v

    def _row_dict(row: sqlite3.Row):
        return {k: row[k] for k in row.keys()}

    def _get_sqlite_rows(table: str):
        cur.execute(f"SELECT * FROM {table}")
        return list(cur.fetchall())

    def _upsert_by_unique(model, unique_field: str, rows):
        inserted = 0
        updated = 0
        mapping = {}
        cols = {c.name: c for c in model.__table__.columns}
        for row in rows:
            data = _row_dict(row)
            unique_val = (data.get(unique_field) or "").strip() if isinstance(data.get(unique_field), str) else data.get(unique_field)
            if not unique_val:
                continue
            existing = db.session.execute(
                select(model).where(getattr(model, unique_field) == unique_val)
            ).scalar_one_or_none()
            if existing:
                target = existing
                updated += 1
            else:
                target = model()
                inserted += 1
            for k, v in data.items():
                if k not in cols:
                    continue
                if k in ("id",):
                    continue
                setattr(target, k, _coerce_value(cols[k], v))
            db.session.add(target)
            db.session.flush()
            mapping[data.get("id")] = target.id
        return inserted, updated, mapping

    def _upsert_by_pk(model, rows, id_map=None, fk_maps=None, value_transform=None):
        inserted = 0
        updated = 0
        cols = {c.name: c for c in model.__table__.columns}
        for row in rows:
            data = _row_dict(row)
            src_id = data.get("id")
            if src_id is None:
                continue
            dst_id = id_map.get(src_id, src_id) if id_map else src_id
            existing = db.session.get(model, dst_id)
            if existing:
                obj = existing
                updated += 1
            else:
                obj = model()
                obj.id = dst_id
                inserted += 1
            for k, v in data.items():
                if k not in cols:
                    continue
                if k == "id":
                    continue
                if fk_maps and k in fk_maps:
                    v = fk_maps[k].get(v) if v is not None else None
                if value_transform:
                    v = value_transform(k, v)
                if k in ("created_by", "updated_by", "archived_by") and v is not None and v not in existing_user_ids:
                    v = None
                setattr(obj, k, _coerce_value(cols[k], v))
            db.session.add(obj)
        return inserted, updated

    def _set_seq(table_name: str, pk_col: str = "id"):
        seq = f"{table_name}_{pk_col}_seq"
        db.session.execute(sa_text(
            f"select setval('{seq}', (select coalesce(max({pk_col}), 1) from {table_name}), true)"
        ))

    branches_rows = _get_sqlite_rows("branches")
    sites_rows = _get_sqlite_rows("sites")
    types_rows = _get_sqlite_rows("expense_types")
    employees_rows = _get_sqlite_rows("employees")
    expenses_rows = _get_sqlite_rows("expenses")

    click.echo(f"SQLite: branches={len(branches_rows)} sites={len(sites_rows)} expense_types={len(types_rows)} employees={len(employees_rows)} expenses={len(expenses_rows)}")
    if dry_run:
        click.echo("Dry-run: لم يتم إدخال أي بيانات.")
        return

    try:
        b_ins, b_upd, branch_map = _upsert_by_unique(Branch, "code", branches_rows)
        db.session.flush()

        default_branch = Branch.query.filter(func.lower(Branch.code) == "main").first() or Branch.query.order_by(Branch.id.asc()).first()
        if not default_branch:
            raise click.ClickException("لا يوجد أي فرع في قاعدة البيانات الهدف")
        default_branch_id = default_branch.id

        site_fk_maps = {"branch_id": branch_map}
        s_ins, s_upd = _upsert_by_pk(Site, sites_rows, fk_maps=site_fk_maps)
        db.session.flush()
        existing_site_ids = {r[0] for r in db.session.execute(sa_text("select id from sites")).fetchall()}

        t_ins, t_upd, type_map = _upsert_by_unique(ExpenseType, "name", types_rows)
        db.session.flush()

        fallback_type = ExpenseType.query.filter(func.lower(ExpenseType.name) == "imported").first()
        if not fallback_type:
            fallback_type = ExpenseType(name="Imported", description="Imported from legacy SQLite")
            db.session.add(fallback_type)
            db.session.flush()
        fallback_type_id = fallback_type.id

        emp_fk_maps = {"branch_id": branch_map}
        def _employee_value_transform(k: str, v):
            if k == "branch_id":
                return v or default_branch_id
            if k == "site_id":
                if v in (None, 0):
                    return None
                return v if v in existing_site_ids else None
            return v
        e_ins, e_upd = _upsert_by_pk(Employee, employees_rows, fk_maps=emp_fk_maps, value_transform=_employee_value_transform)
        db.session.flush()

        existing_customer_ids = {r[0] for r in db.session.execute(sa_text("select id from customers")).fetchall()}
        existing_supplier_ids = {r[0] for r in db.session.execute(sa_text("select id from suppliers")).fetchall()}
        existing_partner_ids = {r[0] for r in db.session.execute(sa_text("select id from partners")).fetchall()}
        existing_warehouse_ids = {r[0] for r in db.session.execute(sa_text("select id from warehouses")).fetchall()}
        existing_shipment_ids = {r[0] for r in db.session.execute(sa_text("select id from shipments")).fetchall()}
        existing_utility_account_ids = {r[0] for r in db.session.execute(sa_text("select id from utility_accounts")).fetchall()}
        existing_stock_adjustment_ids = {r[0] for r in db.session.execute(sa_text("select id from stock_adjustments")).fetchall()}
        existing_site_ids = {r[0] for r in db.session.execute(sa_text("select id from sites")).fetchall()}
        existing_employee_ids = {r[0] for r in db.session.execute(sa_text("select id from employees")).fetchall()}

        def _expense_value_transform(k: str, v):
            if k == "branch_id":
                if v is None:
                    return default_branch_id
                return branch_map.get(v) or default_branch_id
            if k == "type_id":
                if v is None:
                    return fallback_type_id
                return type_map.get(v) or fallback_type_id
            if k == "site_id":
                return v if v in existing_site_ids else None
            if k == "employee_id":
                return v if v in existing_employee_ids else None
            if k == "customer_id":
                return v if v in existing_customer_ids else None
            if k == "supplier_id":
                return v if v in existing_supplier_ids else None
            if k == "partner_id":
                return v if v in existing_partner_ids else None
            if k == "warehouse_id":
                return v if v in existing_warehouse_ids else None
            if k == "shipment_id":
                return v if v in existing_shipment_ids else None
            if k == "utility_account_id":
                return v if v in existing_utility_account_ids else None
            if k == "stock_adjustment_id":
                return v if v in existing_stock_adjustment_ids else None
            return v

        exp_fk_maps = {"branch_id": branch_map, "type_id": type_map}
        x_ins, x_upd = _upsert_by_pk(Expense, expenses_rows, fk_maps=exp_fk_maps, value_transform=_expense_value_transform)
        db.session.flush()

        _set_seq("branches")
        _set_seq("sites")
        _set_seq("expense_types")
        _set_seq("employees")
        _set_seq("expenses")

        db.session.commit()
        click.echo(
            "✅ تم الاستيراد: "
            f"branches +{b_ins}/~{b_upd}, sites +{s_ins}/~{s_upd}, "
            f"types +{t_ins}/~{t_upd}, employees +{e_ins}/~{e_upd}, expenses +{x_ins}/~{x_upd}"
        )
    except Exception as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))


@click.command("compare-sqlite-appdb")
@click.option("--sqlite-path", default=os.path.join("instance", "app.db"), show_default=True)
@click.option("--limit", default=25, show_default=True, type=int)
@click.option("--fail", is_flag=True, default=False)
@with_appcontext
def compare_sqlite_appdb(sqlite_path: str, limit: int, fail: bool):
    abs_path = sqlite_path
    if not os.path.isabs(abs_path):
        abs_path = os.path.abspath(abs_path)
    if not os.path.exists(abs_path):
        raise click.ClickException(f"ملف SQLite غير موجود: {abs_path}")

    con = sqlite3.connect(abs_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def _fetch_all(table: str):
        cur.execute(f"SELECT * FROM {table}")
        return list(cur.fetchall())

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    sqlite_tables = {r[0] for r in cur.fetchall()}
    required = {"branches", "sites", "expense_types", "employees", "expenses"}
    missing = sorted(required - sqlite_tables)
    if missing:
        raise click.ClickException(f"جداول ناقصة في SQLite: {', '.join(missing)}")

    sqlite_branches = {r["id"]: r for r in _fetch_all("branches")}
    sqlite_sites = {r["id"]: r for r in _fetch_all("sites")}
    sqlite_types = {r["id"]: r for r in _fetch_all("expense_types")}
    sqlite_emps = {r["id"]: r for r in _fetch_all("employees")}
    sqlite_exps = {r["id"]: r for r in _fetch_all("expenses")}

    con.close()

    def _s(v):
        if v is None:
            return ""
        return str(v).strip()

    def _money(v):
        try:
            return Decimal(str(v)).quantize(Decimal("0.01"))
        except Exception:
            return Decimal("0.00")

    def _bool(v):
        if v is None:
            return False
        if isinstance(v, (int, float)):
            return int(v) == 1
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "y", "t")

    def _date(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.date()
        s = str(v).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except Exception:
            return None

    def _sqlite_field(row, key: str):
        if row is None:
            return None
        try:
            return row[key]
        except Exception:
            return None

    default_branch = Branch.query.filter(func.lower(Branch.code) == "main").first() or Branch.query.order_by(Branch.id.asc()).first()
    default_branch_code = default_branch.code if default_branch else ""

    emp_ids = sorted(int(x) for x in sqlite_emps.keys())
    exp_ids = sorted(int(x) for x in sqlite_exps.keys())

    pg_emps = {e.id: e for e in Employee.query.filter(Employee.id.in_(emp_ids)).all()} if emp_ids else {}
    pg_exps = {e.id: e for e in Expense.query.filter(Expense.id.in_(exp_ids)).all()} if exp_ids else {}

    emp_missing = [eid for eid in emp_ids if eid not in pg_emps]
    exp_missing = [eid for eid in exp_ids if eid not in pg_exps]

    emp_mismatches = []
    for eid in emp_ids:
        if eid not in pg_emps:
            continue
        srow = sqlite_emps[eid]
        prow = pg_emps[eid]

        sqlite_branch_id = srow["branch_id"]
        sqlite_branch_row = sqlite_branches.get(sqlite_branch_id)
        sqlite_branch_code = _s(_sqlite_field(sqlite_branch_row, "code")) if sqlite_branch_id else ""
        expected_branch_code = sqlite_branch_code or default_branch_code
        pg_branch_code = _s(prow.branch.code) if getattr(prow, "branch", None) else ""

        sqlite_site_id = srow["site_id"]
        sqlite_site_row = sqlite_sites.get(sqlite_site_id)
        sqlite_site_code = _s(_sqlite_field(sqlite_site_row, "code")) if sqlite_site_id else ""
        pg_site_code = _s(prow.site.code) if getattr(prow, "site", None) else ""
        expected_site_code = "" if sqlite_site_id in (None, 0) else sqlite_site_code

        diffs = {}
        if _s(srow["name"]) != _s(prow.name):
            diffs["name"] = (_s(srow["name"]), _s(prow.name))
        if _s(srow["position"]) != _s(prow.position):
            diffs["position"] = (_s(srow["position"]), _s(prow.position))
        if _money(srow["salary"]) != _money(prow.salary):
            diffs["salary"] = (str(_money(srow["salary"])), str(_money(prow.salary)))
        if _s(srow["phone"]) != _s(prow.phone):
            diffs["phone"] = (_s(srow["phone"]), _s(prow.phone))
        if _s(srow["email"]).lower() != _s(prow.email).lower():
            diffs["email"] = (_s(srow["email"]), _s(prow.email))
        if _date(srow["hire_date"]) != _date(prow.hire_date):
            diffs["hire_date"] = (str(_date(srow["hire_date"])), str(_date(prow.hire_date)))
        if _s(srow["currency"]).upper() != _s(prow.currency).upper():
            diffs["currency"] = (_s(srow["currency"]), _s(prow.currency))
        if expected_branch_code.lower() != pg_branch_code.lower():
            diffs["branch_code"] = (expected_branch_code, pg_branch_code)
        if expected_site_code.lower() != pg_site_code.lower():
            diffs["site_code"] = (expected_site_code, pg_site_code)

        if diffs:
            emp_mismatches.append((eid, diffs))

    exp_mismatches = []
    for xid in exp_ids:
        if xid not in pg_exps:
            continue
        srow = sqlite_exps[xid]
        prow = pg_exps[xid]

        sqlite_branch_id = srow["branch_id"]
        sqlite_branch_row = sqlite_branches.get(sqlite_branch_id)
        sqlite_branch_code = _s(_sqlite_field(sqlite_branch_row, "code")) if sqlite_branch_id else ""
        expected_branch_code = sqlite_branch_code or default_branch_code
        pg_branch_code = _s(prow.branch.code) if getattr(prow, "branch", None) else ""

        sqlite_type_id = srow["type_id"]
        sqlite_type_row = sqlite_types.get(sqlite_type_id)
        sqlite_type_name = _s(_sqlite_field(sqlite_type_row, "name")) if sqlite_type_id else ""
        pg_type_name = _s(prow.type.name) if getattr(prow, "type", None) else ""

        diffs = {}
        if _date(srow["date"]) != _date(prow.date):
            diffs["date"] = (str(_date(srow["date"])), str(_date(prow.date)))
        if _money(srow["amount"]) != _money(prow.amount):
            diffs["amount"] = (str(_money(srow["amount"])), str(_money(prow.amount)))
        if _s(srow["currency"]).upper() != _s(prow.currency).upper():
            diffs["currency"] = (_s(srow["currency"]), _s(prow.currency))
        if _bool(srow["is_archived"]) != bool(prow.is_archived):
            diffs["is_archived"] = (str(_bool(srow["is_archived"])), str(bool(prow.is_archived)))
        if _s(srow["payment_method"]).lower() != _s(prow.payment_method).lower():
            diffs["payment_method"] = (_s(srow["payment_method"]), _s(prow.payment_method))
        if _s(srow["payee_type"]).upper() != _s(prow.payee_type).upper():
            diffs["payee_type"] = (_s(srow["payee_type"]), _s(prow.payee_type))
        if sqlite_type_name.strip().lower() != pg_type_name.strip().lower():
            diffs["type_name"] = (sqlite_type_name, pg_type_name)
        if expected_branch_code.lower() != pg_branch_code.lower():
            diffs["branch_code"] = (expected_branch_code, pg_branch_code)

        sqlite_text_fields = ("payee_name", "paid_to", "beneficiary_name", "description", "notes", "tax_invoice_number")
        for f in sqlite_text_fields:
            if f in srow.keys() and hasattr(prow, f):
                if _s(srow[f]) != _s(getattr(prow, f)):
                    diffs[f] = (_s(srow[f]), _s(getattr(prow, f)))

        if diffs:
            exp_mismatches.append((xid, diffs))

    click.echo("📌 مقارنة SQLite (قديم) مع Postgres (حالي)")
    click.echo(f"- employees: sqlite={len(emp_ids)} postgres_matched={len(pg_emps)} missing={len(emp_missing)} mismatched={len(emp_mismatches)}")
    click.echo(f"- expenses:  sqlite={len(exp_ids)} postgres_matched={len(pg_exps)} missing={len(exp_missing)} mismatched={len(exp_mismatches)}")

    shown = 0
    if emp_missing:
        click.echo("\n❌ موظفين مفقودين (أول 20): " + ", ".join(str(x) for x in emp_missing[:20]))
    if exp_missing:
        click.echo("\n❌ نفقات مفقودة (أول 20): " + ", ".join(str(x) for x in exp_missing[:20]))

    if emp_mismatches:
        click.echo("\n⚠️ اختلافات الموظفين (أول العناصر):")
        for eid, diffs in emp_mismatches[: max(0, limit)]:
            shown += 1
            click.echo(f"- Employee #{eid}: {json.dumps(diffs, ensure_ascii=False)}")
            if shown >= limit:
                break

    if exp_mismatches and shown < limit:
        click.echo("\n⚠️ اختلافات النفقات (أول العناصر):")
        for xid, diffs in exp_mismatches[: max(0, limit - shown)]:
            click.echo(f"- Expense #{xid}: {json.dumps(diffs, ensure_ascii=False)}")

    total_problems = len(emp_missing) + len(exp_missing) + len(emp_mismatches) + len(exp_mismatches)
    if total_problems == 0:
        click.echo("\n✅ البيانات متطابقة (حسب الحقول الأساسية).")
        return
    click.echo(f"\n❗ يوجد اختلافات: {total_problems}")
    if fail:
        raise click.ClickException("التحقق فشل: توجد اختلافات")


@click.command("compare-sqlite-full")
@click.option("--sqlite-path", default=os.path.join("instance", "app.db"), show_default=True)
@click.option("--tables", default="*", show_default=True)
@click.option("--schema-only", is_flag=True, default=False)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--chunk-size", default=500, show_default=True, type=int)
@click.option("--fail", is_flag=True, default=False)
@with_appcontext
def compare_sqlite_full(sqlite_path: str, tables: str, schema_only: bool, limit: int, chunk_size: int, fail: bool):
    abs_path = sqlite_path
    if not os.path.isabs(abs_path):
        abs_path = os.path.abspath(abs_path)
    if not os.path.exists(abs_path):
        raise click.ClickException(f"ملف SQLite غير موجود: {abs_path}")

    con = sqlite3.connect(abs_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    sqlite_tables = sorted(
        t[0]
        for t in cur.fetchall()
        if t and t[0] and not str(t[0]).startswith("sqlite_")
    )

    if tables.strip() == "*":
        target_tables = sqlite_tables
    else:
        wanted = [t.strip() for t in tables.split(",") if t.strip()]
        missing = [t for t in wanted if t not in sqlite_tables]
        if missing:
            raise click.ClickException("جداول غير موجودة في SQLite: " + ", ".join(missing))
        target_tables = wanted

    def _fetch_all(table: str):
        cur.execute(f"SELECT * FROM {table}")
        return list(cur.fetchall())

    sqlite_branch_id_to_code = {}
    sqlite_type_id_to_name = {}
    if "branches" in sqlite_tables:
        for r in _fetch_all("branches"):
            try:
                sqlite_branch_id_to_code[int(r["id"])] = str(r["code"] or "").strip()
            except Exception:
                continue
    if "expense_types" in sqlite_tables:
        for r in _fetch_all("expense_types"):
            try:
                sqlite_type_id_to_name[int(r["id"])] = str(r["name"] or "").strip()
            except Exception:
                continue

    pg_branch_code_to_id = {str(b.code or "").strip().lower(): b.id for b in Branch.query.all()}
    pg_type_name_to_id = {str(t.name or "").strip().lower(): t.id for t in ExpenseType.query.all()}

    default_branch = Branch.query.filter(func.lower(Branch.code) == "main").first() or Branch.query.order_by(Branch.id.asc()).first()
    default_branch_id = default_branch.id if default_branch else None
    fallback_type = ExpenseType.query.filter(func.lower(ExpenseType.name) == "imported").first()
    fallback_type_id = fallback_type.id if fallback_type else None

    insp = inspect(db.engine)
    pg_tables = set(insp.get_table_names(schema="public"))

    click.echo("📌 مقارنة شاملة SQLite (قديم) مع Postgres (حالي)")
    click.echo(f"- جداول SQLite: {len(sqlite_tables)} | جداول مستهدفة: {len(target_tables)} | جداول Postgres: {len(pg_tables)}")

    def _sqlite_cols(table: str):
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall()
        cols = []
        pk_cols = []
        for r in rows:
            name = r[1]
            decl = r[2] or ""
            pk = int(r[5] or 0)
            cols.append((name, decl))
            if pk:
                pk_cols.append((pk, name))
        pk_cols = [n for _, n in sorted(pk_cols)]
        return cols, pk_cols

    def _sqlite_count(table: str):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])

    def _sqlite_pk_chunk(table: str, pk: str, offset: int, size: int):
        cur.execute(f"SELECT {pk} FROM {table} ORDER BY {pk} LIMIT ? OFFSET ?", (size, offset))
        return [r[0] for r in cur.fetchall()]

    def _normalize(v):
        if v is None:
            return None
        if isinstance(v, (bytes, bytearray, memoryview)):
            return bytes(v).hex()
        if isinstance(v, bool):
            return bool(v)
        if isinstance(v, (int,)):
            return int(v)
        if isinstance(v, (float,)):
            return Decimal(str(v))
        if isinstance(v, Decimal):
            return v
        if isinstance(v, datetime):
            return v.replace(tzinfo=None)
        try:
            return str(v)
        except Exception:
            return repr(v)

    def _coerce_like_pg(pg_val, sqlite_val):
        if pg_val is None:
            return _normalize(sqlite_val)
        if isinstance(pg_val, bool):
            s = str(sqlite_val).strip().lower()
            if s in ("1", "true", "yes", "y", "t"):
                return True
            if s in ("0", "false", "no", "n", "f"):
                return False
            try:
                return bool(int(sqlite_val))
            except Exception:
                return bool(sqlite_val)
        if isinstance(pg_val, Decimal):
            try:
                return Decimal(str(sqlite_val))
            except Exception:
                return Decimal("0")
        if isinstance(pg_val, int):
            try:
                return int(sqlite_val)
            except Exception:
                return sqlite_val
        if isinstance(pg_val, datetime):
            s = str(sqlite_val).strip()
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return sqlite_val
        return _normalize(sqlite_val)

    def _map_sqlite_fk(table: str, col: str, sqlite_val):
        if col == "branch_id":
            if sqlite_val in (None, 0, "0"):
                return default_branch_id
            try:
                sid = int(sqlite_val)
                code = (sqlite_branch_id_to_code.get(sid) or "").strip().lower()
                if code and code in pg_branch_code_to_id:
                    return pg_branch_code_to_id[code]
            except Exception:
                pass
            return default_branch_id

        if col == "type_id" and table == "expenses":
            if sqlite_val in (None, 0, "0"):
                return fallback_type_id
            try:
                sid = int(sqlite_val)
                name = (sqlite_type_id_to_name.get(sid) or "").strip().lower()
                if name and name in pg_type_name_to_id:
                    return pg_type_name_to_id[name]
            except Exception:
                pass
            return fallback_type_id

        if sqlite_val in (None, ""):
            return None
        try:
            if isinstance(sqlite_val, str) and sqlite_val.strip() == "":
                return None
        except Exception:
            pass

        if col.endswith("_id"):
            if sqlite_val in (0, "0"):
                return None
            try:
                if isinstance(sqlite_val, str) and sqlite_val.strip() == "0":
                    return None
            except Exception:
                pass

        return sqlite_val

    problems = 0
    shown = 0
    for table in target_tables:
        if table not in pg_tables:
            problems += 1
            click.echo(f"\n❌ جدول مفقود في Postgres: {table}")
            continue

        sqlite_cols, sqlite_pk = _sqlite_cols(table)
        sqlite_col_names = [c[0] for c in sqlite_cols]
        pg_cols = insp.get_columns(table, schema="public")
        pg_col_names = [c["name"] for c in pg_cols]

        missing_cols = [c for c in sqlite_col_names if c not in pg_col_names]
        extra_cols = [c for c in pg_col_names if c not in sqlite_col_names]

        sqlite_count = _sqlite_count(table)
        pg_count = db.session.execute(sa_text(f"select count(*) from {table}")).scalar()
        pg_count = int(pg_count or 0)

        if missing_cols or sqlite_count != pg_count:
            problems += 1
        click.echo(f"\n🧾 {table}: rows sqlite={sqlite_count} postgres={pg_count} | cols sqlite={len(sqlite_col_names)} postgres={len(pg_col_names)}")
        if missing_cols:
            click.echo("  ❌ أعمدة SQLite غير موجودة في Postgres: " + ", ".join(missing_cols[:50]) + (" ..." if len(missing_cols) > 50 else ""))
        if extra_cols:
            click.echo("  ℹ️ أعمدة موجودة في Postgres فقط: " + ", ".join(extra_cols[:50]) + (" ..." if len(extra_cols) > 50 else ""))

        if schema_only:
            continue

        pg_pk = insp.get_pk_constraint(table, schema="public").get("constrained_columns") or []
        common_cols = [c for c in sqlite_col_names if c in pg_col_names]

        if not common_cols:
            continue

        if len(sqlite_pk) == 1 and len(pg_pk) == 1 and sqlite_pk[0] == pg_pk[0] and sqlite_pk[0] in common_cols:
            pk = sqlite_pk[0]
            offset = 0
            meta = MetaData()
            pg_table = Table(table, meta, autoload_with=db.engine, schema="public")
            cols_sel = [pg_table.c[c] for c in common_cols if c in pg_table.c]
            stmt = select(*cols_sel).where(pg_table.c[pk].in_(bindparam("pks", expanding=True)))

            while True:
                ids = _sqlite_pk_chunk(table, pk, offset, chunk_size)
                if not ids:
                    break
                offset += len(ids)

                cur.execute(
                    f"SELECT {', '.join(common_cols)} FROM {table} WHERE {pk} IN ({','.join(['?'] * len(ids))})",
                    ids,
                )
                sqlite_rows = {r[common_cols.index(pk)]: r for r in cur.fetchall()}

                pg_rows = {}
                for r in db.session.execute(stmt, {"pks": ids}).all():
                    d = dict(zip(common_cols, r))
                    pg_rows[d[pk]] = d

                for rid in ids:
                    srow = sqlite_rows.get(rid)
                    prow = pg_rows.get(rid)
                    if prow is None or srow is None:
                        problems += 1
                        if shown < limit:
                            click.echo(f"  ❌ صف مفقود في أحد الطرفين: {pk}={rid}")
                            shown += 1
                        continue

                    diffs = {}
                    for i, col in enumerate(common_cols):
                        pg_val = prow.get(col)
                        s_val_raw = srow[i]
                        s_val_raw = _map_sqlite_fk(table, col, s_val_raw)
                        s_val = _coerce_like_pg(pg_val, s_val_raw)
                        if _normalize(pg_val) != _normalize(s_val):
                            diffs[col] = (str(pg_val), str(s_val_raw))
                    if diffs:
                        problems += 1
                        if shown < limit:
                            click.echo(f"  ⚠️ اختلاف صف {pk}={rid}: {json.dumps(diffs, ensure_ascii=False)}")
                            shown += 1
                if shown >= limit:
                    break
        else:
            problems += 1
            click.echo("  ⚠️ تخطي مقارنة الصفوف: لا يوجد PK متوافق (أو PK مركب).")

    if problems == 0:
        click.echo("\n✅ مطابق بالكامل: كل جداول SQLite وأعمدتها وصفوفها متطابقة في Postgres.")
        return
    click.echo(f"\n❗ فشل التطابق الكامل: تم العثور على {problems} مشكلة.")
    if fail:
        raise click.ClickException("التحقق فشل: توجد اختلافات")

def _sync_role_permissions(role_id: int, desired_permission_ids: set[int], *, reset: bool = False, add_only: bool = False) -> None:
    if not role_id:
        return
    desired = {int(x) for x in (desired_permission_ids or set()) if x}
    existing = {
        int(r[0])
        for r in db.session.execute(
            select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role_id)
        ).all()
        if r and r[0]
    }

    if reset:
        if existing:
            db.session.execute(sa_delete(role_permissions).where(role_permissions.c.role_id == role_id))
        existing = set()
    elif not add_only:
        to_remove = existing - desired
        if to_remove:
            db.session.execute(
                sa_delete(role_permissions).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id.in_(sorted(to_remove)),
                )
            )
            existing -= to_remove

    to_add = desired - existing
    if to_add:
        rows = [{"role_id": role_id, "permission_id": pid} for pid in sorted(to_add)]
        stmt = pg_insert(role_permissions).values(rows).on_conflict_do_nothing(
            index_elements=["role_id", "permission_id"]
        )
        db.session.execute(stmt)
def _get_or_create_role(name: str) -> Role:
    r = Role.query.filter(func.lower(Role.name) == name.lower()).first()
    if not r:
        r = Role(name=name)
        db.session.add(r)
        db.session.flush()
    return r

def _ensure_permission(code: str) -> Permission:
    code_n = _normalize_code(code)
    if not code_n:
        raise click.ClickException(f"Invalid permission code: {code!r}")
    p = Permission.query.filter(func.lower(Permission.code) == code_n).first()
    if p:
        p.name = p.name or code_n
        perm_info = PermissionsRegistry.get_permission_info(code_n)
        if perm_info:
            p.name_ar = p.name_ar or perm_info.get('name_ar')
            p.module = p.module or perm_info.get('module')
            p.description = p.description or perm_info.get('description')
            p.is_protected = perm_info.get('is_protected', False)
        return p
    try:
        perm_info = PermissionsRegistry.get_permission_info(code_n)
        p = Permission(
            code=code_n,
            name=code_n,
            name_ar=perm_info.get('name_ar') if perm_info else None,
            module=perm_info.get('module') if perm_info else None,
            description=perm_info.get('description') if perm_info else None,
            is_protected=perm_info.get('is_protected', False) if perm_info else False
        )
        db.session.add(p)
        db.session.flush()
        return p
    except IntegrityError:
        db.session.rollback()
        p = Permission.query.filter(func.lower(Permission.code) == code_n).first()
        if not p:
            raise
        return p

def _assign_role_perms(role: Role, desired_codes: set[str], *, reset: bool = False) -> None:
    if not isinstance(role, Role):
        return
    desired = {(_normalize_code(c) or "").lower() for c in (desired_codes or set())}
    desired.discard("")
    desired_ids: set[int] = set()
    for code in sorted(desired):
        perm = _ensure_permission(code)
        if isinstance(perm, Permission) and getattr(perm, "id", None):
            desired_ids.add(int(perm.id))
    _sync_role_permissions(int(role.id), desired_ids, reset=reset, add_only=not reset)

def _norm_email(s: str) -> str:
    return (s or "").strip().lower()

def _norm_user(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())

def _get_or_create_user(username: str, email: str, password: str, role: Role) -> User:
    uname, mail = _norm_user(username), _norm_email(email)
    if not uname or not mail:
        raise click.ClickException("username/email required")
    u = User.query.filter(or_(func.lower(User.email) == mail, func.lower(User.username) == uname)).first()
    if u:
        u.is_active = True if u.is_active is not True else u.is_active
        u.username = u.username or uname
        u.email = u.email or mail
        if not u.password_hash and password:
            u.set_password(password)
        u.role = role
        return u
    try:
        u = User(username=uname, email=mail, is_active=True, role=role)
        if password:
            u.set_password(password)
        db.session.add(u)
        db.session.flush()
        return u
    except IntegrityError:
        db.session.rollback()
        u = User.query.filter(or_(func.lower(User.email) == mail, func.lower(User.username) == uname)).first()
        if not u:
            raise
        if not u.role:
            u.role = role
        return u

def _is_production() -> bool:
    fe = os.getenv("FLASK_ENV","").lower(); env = os.getenv("ENVIRONMENT","").lower(); debug = os.getenv("DEBUG","").lower()
    return (fe=="production") or (env=="production") or (debug not in ("1","true","yes"))

def _ensure_schema_ready(): db.session.execute(select(1))

def _begin():
    try: db.session.rollback()
    except Exception: pass
    return db.session.begin()

@click.command("create-system-admin")
@click.option("--username", required=True)
@click.option("--password", required=True)
@click.option("--email", default=None)
@with_appcontext
def create_system_admin(username, password, email):
    s = db.session
    if not email:
        email = f"{username}@local"
    r = Role.query.filter_by(name="super_admin").one_or_none()
    if not r:
        r = Role(name="super_admin")
        s.add(r)
        s.flush()
    u = User.query.filter((User.username==username)|(User.email==email)).one_or_none()
    if not u:
        u = User(username=username, email=email)
        u.set_password(password)
        u.role = r
        s.add(u)
        s.flush()
    else:
        u.username = username
        u.email = email
        u.role = r
        u.set_password(password)
    s.commit()
    click.echo(f"✅ system admin '{username}' created or updated.")

@click.command("seed-roles")
@click.option("--force", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--reset", "reset_roles", is_flag=True)
@click.option("--allow-default-passwords", is_flag=True)
@with_appcontext
def seed_roles(force: bool, dry_run: bool, reset_roles: bool, allow_default_passwords: bool) -> None:
    if not force and os.getenv("ALLOW_SEED_ROLES") != "1":
        raise click.ClickException("seed-roles disabled. Set ALLOW_SEED_ROLES=1 or use --force.")
    if _is_production() and not force:
        if not click.confirm("Production environment detected. Continue?", default=False):
            click.echo("Canceled.")
            return
    if _is_production() and not allow_default_passwords:
        weak = {"AZ123456", "ADMIN123", "STAFF123", "MECH123", "CUST123", "OWNER123", "DEV123", "MANAGER123"}
        if any(p in weak for p in (
            SUPER_PASSWORD, ADMIN_PASSWORD, STAFF_PASSWORD, MECH_PASSWORD, RC_PASSWORD,
            OWNER_PASSWORD, DEVELOPER_PASSWORD, MANAGER_PASSWORD
        )):
            raise click.ClickException("Refusing to seed weak default passwords in production. Use --allow-default-passwords to override.")

    try:
        _ensure_schema_ready()
    except click.ClickException:
        raise
    except Exception:
        pass

    if dry_run:
        click.echo(f"- Ensure {len(RESERVED_CODES)} permissions exist")
        click.echo("- Ensure roles: super_admin, admin, staff, registered_customer, mechanic")
        click.echo(f"- Assign role permissions (reset={reset_roles})")
        click.echo("- Ensure users:")
        click.echo(f"  super_admin: {SUPER_USERNAME} <{SUPER_EMAIL}>")
        click.echo(f"  admin      : {ADMIN_USERNAME} <{ADMIN_EMAIL}>")
        click.echo(f"  staff      : {STAFF_USERNAME} <{STAFF_EMAIL}>")
        click.echo(f"  mechanic   : {MECH_USERNAME} <{MECH_EMAIL}>")
        click.echo(f"  reg_cust   : {RC_USERNAME} <{RC_EMAIL}>")
        return

    affected_roles: set[int] = set()
    try:
        with _begin():
            for code in sorted(RESERVED_CODES):
                _ensure_permission(code)

            owner_role = _get_or_create_role("owner")
            developer_role = _get_or_create_role("developer")
            super_admin = _get_or_create_role("super_admin")
            admin = _get_or_create_role("admin")
            manager = _get_or_create_role("manager")
            staff = _get_or_create_role("staff")
            mechanic = _get_or_create_role("mechanic")
            registered_customer = _get_or_create_role("registered_customer")
            guest_role = _get_or_create_role("guest")

            all_perms = [p for p in Permission.query.all() if isinstance(p, Permission)]
            
            for super_role_obj in [owner_role, developer_role, super_admin]:
                role_key = (super_role_obj.name or "").strip().lower()
                role_info = PermissionsRegistry.ROLES.get(role_key, {})
                exclude_list = set(role_info.get("exclude", []))
                
                desired_ids: set[int] = set()
                for p in all_perms:
                    p_code = (getattr(p, "code", None) or "").strip().lower()
                    if not p_code or p_code in exclude_list:
                        continue
                    pid = getattr(p, "id", None)
                    if pid:
                        desired_ids.add(int(pid))

                _sync_role_permissions(int(super_role_obj.id), desired_ids, reset=False, add_only=False)
                if super_role_obj.id is not None:
                    affected_roles.add(super_role_obj.id)

            if 'admin' in ROLE_PERMISSIONS:
                _assign_role_perms(admin, ROLE_PERMISSIONS['admin'], reset=reset_roles)
                if admin.id is not None:
                    affected_roles.add(admin.id)
            
            if 'manager' in ROLE_PERMISSIONS:
                _assign_role_perms(manager, ROLE_PERMISSIONS['manager'], reset=reset_roles)
                if manager.id is not None:
                    affected_roles.add(manager.id)
            
            if 'staff' in ROLE_PERMISSIONS:
                _assign_role_perms(staff, ROLE_PERMISSIONS['staff'], reset=reset_roles)
                if staff.id is not None:
                    affected_roles.add(staff.id)
            
            if 'mechanic' in ROLE_PERMISSIONS:
                _assign_role_perms(mechanic, ROLE_PERMISSIONS['mechanic'], reset=reset_roles)
                if mechanic.id is not None:
                    affected_roles.add(mechanic.id)
            
            if 'registered_customer' in ROLE_PERMISSIONS:
                _assign_role_perms(registered_customer, ROLE_PERMISSIONS['registered_customer'], reset=reset_roles)
                if registered_customer.id is not None:
                    affected_roles.add(registered_customer.id)
            
            if 'guest' in ROLE_PERMISSIONS:
                _assign_role_perms(guest_role, ROLE_PERMISSIONS['guest'], reset=reset_roles)
                if guest_role.id is not None:
                    affected_roles.add(guest_role.id)

            owner_user = _get_or_create_user(OWNER_USERNAME, OWNER_EMAIL, OWNER_PASSWORD, owner_role)
            developer_user = _get_or_create_user(DEVELOPER_USERNAME, DEVELOPER_EMAIL, DEVELOPER_PASSWORD, developer_role)
            owner_user.is_system_account = True
            developer_user.is_system_account = True

            _get_or_create_user(SUPER_USERNAME, SUPER_EMAIL, SUPER_PASSWORD, super_admin)
            _get_or_create_user(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, admin)
            _get_or_create_user(MANAGER_USERNAME, MANAGER_EMAIL, MANAGER_PASSWORD, manager)
            _get_or_create_user(STAFF_USERNAME, STAFF_EMAIL, STAFF_PASSWORD, staff)
            _get_or_create_user(MECH_USERNAME, MECH_EMAIL, MECH_PASSWORD, mechanic)
            _get_or_create_user(RC_USERNAME, RC_EMAIL, RC_PASSWORD, registered_customer)

        from utils.role_sync import consolidate_super_roles

        merge_stats = consolidate_super_roles(db.session)
        if merge_stats.get("migrated_users"):
            click.echo(f"• Merged super→super_admin users: {merge_stats['migrated_users']}")
        if merge_stats.get("removed_role"):
            click.echo("• Removed deprecated role: super")

        for rid in affected_roles:
            try:
                clear_role_permission_cache(rid)
            except Exception:
                pass
            try:
                clear_users_cache_by_role(rid)
            except Exception:
                pass

        click.echo("OK: roles, permissions, and users synced.")
    except IntegrityError as e:
        db.session.rollback()
        raise click.ClickException(f"Constraint/unique violation: {getattr(e, 'orig', e)}") from e
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(f"DB error: {e.__class__.__name__}: {e}") from e

@click.command("sync-permissions")
@click.option("--dry-run", is_flag=True)
@with_appcontext
def sync_permissions(dry_run: bool) -> None:
    desired=set(RESERVED_CODES)
    if dry_run: click.echo(f"Would ensure {len(desired)} permissions exist"); return
    try:
        with _begin():
            for code in sorted(desired): _ensure_permission(code)
        click.echo("OK: permissions synced.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("list-permissions")
@click.option("--q", default="")
@with_appcontext
def list_permissions(q: str) -> None:
    s=(q or "").strip().lower()
    qy=Permission.query
    if s: qy=qy.filter(or_(func.lower(Permission.code).contains(s), func.lower(Permission.name_ar).contains(s)))
    for p in qy.order_by(Permission.code).all(): click.echo(f"{p.id:>3}  {p.code:<30}  {p.name_ar or ''}")

@click.command("list-roles")
@with_appcontext
def list_roles() -> None:
    for r in Role.query.order_by(Role.name).all():
        cnt=len(r.permissions or [])
        click.echo(f"{r.id:>3}  {r.name:<25} perms={cnt}")

@click.command("role-add-perms")
@click.argument("role_name", nargs=1)
@click.argument("codes", nargs=-1)
@click.option("--reset", is_flag=True)
@with_appcontext
def role_add_perms(role_name: str, codes: tuple[str, ...], reset: bool) -> None:
    if not role_name:
        raise click.ClickException("role_name is required")
    if not codes and not reset:
        raise click.ClickException("provide at least one permission code or use --reset")
    try:
        with _begin():
            r = _get_or_create_role(role_name)
            _assign_role_perms(r, set(codes), reset=reset)
        clear_role_permission_cache(r.id)
        clear_users_cache_by_role(r.id)
        click.echo(f"OK: role {role_name} updated.")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(f"Commit failed: {e}") from e

@click.command("create-role")
@click.option("--codes", default="")
@click.argument("name", nargs=1)
@with_appcontext
def create_role(name: str, codes: str) -> None:
    desired={c.strip() for c in (codes or "").split(",") if c.strip()}
    try:
        with _begin():
            r=_get_or_create_role(name)
            if desired: _assign_role_perms(r, desired, reset=False)
        clear_role_permission_cache(r.id); click.echo(f"OK: role {name} created/updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("export-rbac")
@with_appcontext
def export_rbac() -> None:
    data=[]
    for r in Role.query.order_by(Role.name).all():
        perms=sorted([(p.code or "") for p in r.permissions or []])
        data.append({"role":r.name,"permissions":perms})
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))

@click.command("create-user")
@click.argument("username")
@click.argument("email")
@click.argument("password")
@click.option("--role", "role_name", default="staff")
@with_appcontext
def create_user(username: str, email: str, password: str, role_name: str) -> None:
    try:
        with _begin():
            r=_get_or_create_role(role_name); _get_or_create_user(username,email,password,r)
        click.echo("OK: user created/updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("user-set-password")
@click.argument("identifier")
@click.argument("password")
@with_appcontext
def user_set_password(identifier: str, password: str) -> None:
    u=User.query.filter(or_(func.lower(User.email)==identifier.lower(), func.lower(User.username)==identifier.lower())).first()
    if not u: raise click.ClickException("User not found")
    try:
        with _begin(): u.set_password(password)
        click.echo("OK: password updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("user-activate")
@click.argument("identifier")
@click.option("--active/--inactive", default=True)
@with_appcontext
def user_activate(identifier: str, active: bool) -> None:
    u=User.query.filter(or_(func.lower(User.email)==identifier.lower(), func.lower(User.username)==identifier.lower())).first()
    if not u: raise click.ClickException("User not found")
    try:
        with _begin(): u.is_active=bool(active)
        click.echo(f"OK: user {'activated' if active else 'deactivated'}.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("user-assign-role")
@click.argument("identifier")
@click.argument("role_name")
@with_appcontext
def user_assign_role(identifier: str, role_name: str) -> None:
    u=User.query.filter(or_(func.lower(User.email)==identifier.lower(), func.lower(User.username)==identifier.lower())).first()
    if not u: raise click.ClickException("User not found")
    try:
        with _begin():
            r=_get_or_create_role(role_name); u.role=r
        clear_users_cache_by_role(r.id); click.echo("OK: user role updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("list-users")
@click.option("--q", default="")
@click.option("--role", "role_name", default="")
@click.option("--show-system", is_flag=True, help="Show hidden system accounts")
@with_appcontext
def list_users(q: str, role_name: str, show_system: bool) -> None:
    s=(q or "").strip().lower(); qy=User.query
    if not show_system:
        qy = qy.filter(User.is_system_account == False)
    if s: qy=qy.filter(or_(func.lower(User.username).contains(s), func.lower(User.email).contains(s)))
    if role_name.strip(): qy=qy.join(Role).filter(func.lower(Role.name)==role_name.strip().lower())
    for u in qy.order_by(User.id).all():
        rn=u.role.name if u.role else "-"
        is_sys = " [SYS]" if getattr(u, "is_system_account", False) else ""
        click.echo(f"{u.id:>3}  {u.username:<20}  {u.email:<30}  role={rn:<18}  active={bool(u.is_active)}{is_sys}")

@click.command("list-customers")
@click.option("--q", default="")
@click.option("--limit", type=int, default=100)
@with_appcontext
def list_customers(q: str, limit: int):
    s=(q or "").strip().lower(); qy=Customer.query
    if s:
        like=f"%{s}%"
        qy=qy.filter(or_(func.lower(Customer.name).like(like), func.lower(Customer.phone).like(like), func.lower(Customer.email).like(like), func.lower(Customer.whatsapp).like(like)))
    rows=qy.order_by(Customer.id.asc()).limit(limit).all()
    for c in rows: click.echo(f"{c.id:>3}  {c.name:<25}  phone={c.phone or '-':<15}  email={c.email or '-':<28}  balance={getattr(c,'balance',0)}")

@click.command("seed-expense-types")
@click.option("--force", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--deactivate-missing", is_flag=True)
@with_appcontext
def seed_expense_types(force: bool, dry_run: bool, deactivate_missing: bool) -> None:
    if not force and os.getenv("ALLOW_SEED_EXPENSE_TYPES")!="1": raise click.ClickException("seed-expense-types disabled. Set ALLOW_SEED_EXPENSE_TYPES=1 or use --force.")
    if _is_production() and not force:
        if not click.confirm("Production environment detected. Continue?", default=False): click.echo("Canceled."); return
    base_types=[("رواتب","مصروف رواتب وأجور",True),("كهرباء","فواتير كهرباء",True),("مياه","فواتير مياه",True),("جمارك","رسوم جمركية",True),("تالف","توالف/هدر مخزون",True),("استخدام داخلي","استهلاك داخلي للمخزون",True),("متفرقات","مصروفات أخرى",True)]
    if dry_run:
        click.echo("Would ensure these expense types exist/active:");
        for n,d,a in base_types: click.echo(f"- {n} ({'active' if a else 'inactive'})")
        if deactivate_missing: click.echo("Would deactivate missing types not in the list."); return
    try:
        with _begin():
            wanted_names=set()
            for name,desc,active in base_types:
                wanted_names.add(name.lower())
                ex=ExpenseType.query.filter(func.lower(ExpenseType.name)==name.lower()).first()
                if not ex: ex=ExpenseType(name=name, description=desc, is_active=bool(active)); db.session.add(ex)
                else:
                    if desc: ex.description=desc
                    ex.is_active=bool(active)
            if deactivate_missing:
                others=ExpenseType.query.filter(func.lower(ExpenseType.name).notin_(wanted_names)).all()
                for ex in others:
                    if ex.is_active: ex.is_active=False
        click.echo("OK: expense types seeded.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("seed-employees")
@click.option("--force", is_flag=True)
@with_appcontext
def seed_employees(force: bool) -> None:
    if _is_production() and not force:
        if not click.confirm("Production environment detected. Continue?", default=False):
            click.echo("Canceled.")
            return
    default_branch = Branch.query.filter(Branch.is_active.is_(True)).order_by(Branch.id.asc()).first() or Branch.query.order_by(Branch.id.asc()).first()
    if not default_branch:
        raise click.ClickException("لا يوجد فرع لإنشاء الموظفين")
    default_site = (
        Site.query.filter(Site.branch_id == default_branch.id, Site.is_active.is_(True)).order_by(Site.id.asc()).first()
        or Site.query.filter(Site.branch_id == default_branch.id).order_by(Site.id.asc()).first()
    )
    base = [
        ("أحمد", "محاسب", 3500),
        ("ليلى", "أمينة مستودع", 3200),
        ("خالد", "مندوب مبيعات", 3000),
        ("سوسن", "موارد بشرية", 2800),
    ]
    try:
        with _begin():
            if not default_site:
                default_site = Site(code="MAIN", name="الموقع الرئيسي", branch_id=default_branch.id, is_active=True)
                db.session.add(default_site)
                db.session.flush()
            for name, position, salary in base:
                row = Employee.query.filter(func.lower(Employee.name) == name.lower()).first()
                if not row:
                    db.session.add(Employee(
                        name=name,
                        position=position,
                        salary=_Q2(salary),
                        currency="ILS",
                        branch_id=default_branch.id,
                        site_id=default_site.id,
                    ))
                else:
                    if not row.position:
                        row.position = position
                    if not row.salary:
                        row.salary = _Q2(salary)
                    if not getattr(row, "branch_id", None):
                        row.branch_id = default_branch.id
                    if not getattr(row, "site_id", None):
                        row.site_id = default_site.id
        click.echo("OK: employees seeded.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

def _get_expense_type_id(name: str) -> int:
    ex = ExpenseType.query.filter(func.lower(ExpenseType.name) == name.strip().lower()).first()
    if not ex:
        ex = ExpenseType(name=name.strip(), description=name.strip(), is_active=True)
        db.session.add(ex)
        db.session.flush()
    return int(ex.id)

@click.command("seed-salaries")
@click.option("--months", type=int, default=6)
@click.option("--start", type=str, default="")
@with_appcontext
def seed_salaries(months: int, start: str) -> None:
    from datetime import date, timedelta
    # تحديد أول يوم من الشهر لبداية الفترة
    today = date.today()
    if start:
        try:
            y, m = [int(x) for x in start.split("-")[:2]]
            start_date = date(y, m, 1)
        except Exception:
            start_date = date(today.year, today.month, 1)
    else:
        start_date = date(today.year, today.month, 1)
    salary_type_id = _get_expense_type_id("رواتب")
    emps = Employee.query.order_by(Employee.id).all()
    if not emps:
        click.echo("No employees. Run: flask seed-employees")
        return
    default_branch = Branch.query.filter(Branch.is_active.is_(True)).order_by(Branch.id.asc()).first() or Branch.query.order_by(Branch.id.asc()).first()
    default_site = None
    if default_branch:
        default_site = (
            Site.query.filter(Site.branch_id == default_branch.id, Site.is_active.is_(True)).order_by(Site.id.asc()).first()
            or Site.query.filter(Site.branch_id == default_branch.id).order_by(Site.id.asc()).first()
        )
    try:
        with _begin():
            if default_branch and not default_site:
                default_site = Site(code="MAIN", name="الموقع الرئيسي", branch_id=default_branch.id, is_active=True)
                db.session.add(default_site)
                db.session.flush()
            for i in range(months):
                # حساب تاريخ هذا الشهر بالإزاحة العكسية i
                year = start_date.year
                month = start_date.month - i
                while month <= 0:
                    month += 12
                    year -= 1
                payday = date(year, month, 25)
                for emp in emps:
                    amt = _Q2(emp.salary or 0)
                    branch_id = getattr(emp, "branch_id", None) or (default_branch.id if default_branch else None)
                    site_id = getattr(emp, "site_id", None) or (default_site.id if default_site else None)
                    if not branch_id:
                        raise click.ClickException("لا يوجد branch_id صالح لإنشاء الرواتب")
                    ex = Expense(
                        date=payday,
                        amount=amt,
                        currency="ILS",
                        type_id=salary_type_id,
                        employee_id=emp.id,
                        branch_id=branch_id,
                        site_id=site_id,
                        payee_type="EMPLOYEE",
                        payee_entity_id=emp.id,
                        payee_name=emp.name,
                        payment_method="cash",
                        description=f"راتب شهر {month:02d}-{year} للموظف {emp.name}",
                        notes=None,
                    )
                    db.session.add(ex)
        click.echo(f"OK: salaries seeded for {len(emps)} employees x {months} months.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("seed-expenses-demo")
@with_appcontext
def seed_expenses_demo() -> None:
    from datetime import datetime, timedelta
    et_electric = _get_expense_type_id("كهرباء")
    et_water = _get_expense_type_id("مياه")
    et_misc = _get_expense_type_id("متفرقات")
    default_branch = Branch.query.filter(Branch.is_active.is_(True)).order_by(Branch.id.asc()).first() or Branch.query.order_by(Branch.id.asc()).first()
    if not default_branch:
        raise click.ClickException("لا يوجد فرع لإنشاء مصاريف تجريبية")
    default_site = (
        Site.query.filter(Site.branch_id == default_branch.id, Site.is_active.is_(True)).order_by(Site.id.asc()).first()
        or Site.query.filter(Site.branch_id == default_branch.id).order_by(Site.id.asc()).first()
    )
    base = [
        (et_electric, 1200.00, "فاتورة كهرباء شهرية"),
        (et_water, 450.00, "فاتورة مياه شهرية"),
        (et_misc, 300.00, "قرطاسية ومستلزمات"),
    ]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with _begin():
            if not default_site:
                default_site = Site(code="MAIN", name="الموقع الرئيسي", branch_id=default_branch.id, is_active=True)
                db.session.add(default_site)
                db.session.flush()
            for idx, (tid, amount, desc) in enumerate(base):
                ex = Expense(
                    date=now - timedelta(days=idx * 7),
                    amount=_Q2(amount),
                    currency="ILS",
                    type_id=tid,
                    branch_id=default_branch.id,
                    site_id=default_site.id,
                    payee_type="OTHER",
                    payment_method="cash",
                    description=desc,
                )
                db.session.add(ex)
        click.echo("OK: demo expenses seeded.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("seed-customer-statement-demo")
@click.option("--customer-id", type=int, default=3)
@click.option("--warehouse-id", type=int, default=3)
@click.option("--branch-id", type=int, default=0)
@click.option("--days-ago", type=int, default=0)
@click.option("--tag", type=str, default="")
@with_appcontext
def seed_customer_statement_demo(customer_id: int, warehouse_id: int, branch_id: int, days_ago: int, tag: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=int(days_ago or 0))
    seed_tag = (tag or "").strip() or uuid.uuid4().hex[:8].upper()

    customer = db.session.get(Customer, int(customer_id))
    if not customer:
        raise click.ClickException("Customer not found")

    warehouse = db.session.get(Warehouse, int(warehouse_id))
    if not warehouse:
        warehouse = Warehouse.query.order_by(Warehouse.id.asc()).first()
    if not warehouse:
        raise click.ClickException("No warehouse found")

    branch = None
    if int(branch_id or 0) > 0:
        branch = db.session.get(Branch, int(branch_id))
    if not branch:
        branch = Branch.query.filter(Branch.is_active.is_(True)).order_by(Branch.id.asc()).first() or Branch.query.order_by(Branch.id.asc()).first()
    if not branch:
        raise click.ClickException("No branch found")

    user = User.query.filter(User.is_active.is_(True)).order_by(User.id.asc()).first() or User.query.order_by(User.id.asc()).first()
    if not user:
        raise click.ClickException("No user found")

    expense_type_id = _get_expense_type_id("أخرى")

    try:
        with _begin():
            product = Product(
                name=f"TraeSeed Product {seed_tag}",
                price=_Q2("150"),
                selling_price=_Q2("150"),
                tax_rate=_Q2("0"),
            )
            db.session.add(product)
            db.session.flush()

            sale = Sale(
                customer_id=customer.id,
                seller_id=user.id,
                sale_date=now,
                status="CONFIRMED",
                currency="ILS",
                tax_rate=_Q2("0"),
                discount_total=_Q2("0"),
                shipping_cost=_Q2("0"),
                total_amount=_Q2("150"),
                balance_due=_Q2("150"),
                notes=f"TraeSeed sale {seed_tag}",
            )
            db.session.add(sale)
            db.session.flush()

            line = SaleLine(
                sale_id=sale.id,
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=1,
                unit_price=_Q2("150"),
                discount_rate=_Q2("0"),
                tax_rate=_Q2("0"),
            )
            db.session.add(line)

            pay_sale = Payment(
                payment_date=now,
                total_amount=_Q2("100"),
                currency="ILS",
                method=PaymentMethod.CASH.value,
                status=PaymentStatus.COMPLETED.value,
                direction=PaymentDirection.IN.value,
                entity_type=PaymentEntityType.SALE.value,
                sale_id=sale.id,
                reference=f"TraeSeed payment {seed_tag}",
                deliverer_name=f"TraePay {seed_tag}",
                receiver_name=str(user.username or f"User {user.id}"),
                created_by=user.id,
            )
            db.session.add(pay_sale)

            preorder = PreOrder(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=1,
                customer_id=customer.id,
                prepaid_amount=_Q2("0"),
                tax_rate=_Q2("0"),
                payment_method=PaymentMethod.CASH.value,
                notes=f"TraeSeed preorder {seed_tag}",
                preorder_date=now,
            )
            db.session.add(preorder)

            service = ServiceRequest(
                customer_id=customer.id,
                tax_rate=_Q2("0"),
                discount_total=_Q2("0"),
                currency="ILS",
                status=ServiceStatus.COMPLETED.value,
                notes=f"TraeSeed service {seed_tag}",
                description=f"TraeSeed service {seed_tag}",
                completed_at=now,
            )
            db.session.add(service)
            db.session.flush()

            db.session.add(ServicePart(
                service_id=service.id,
                part_id=product.id,
                warehouse_id=warehouse.id,
                quantity=1,
                unit_price=_Q2("120"),
                discount=_Q2("0"),
                tax_rate=_Q2("0"),
            ))
            db.session.add(ServiceTask(
                service_id=service.id,
                description=f"TraeSeed labor {seed_tag}",
                quantity=1,
                unit_price=_Q2("30"),
                discount=_Q2("0"),
                tax_rate=_Q2("0"),
            ))

            expense = Expense(
                date=now,
                amount=_Q2("75"),
                currency="ILS",
                type_id=int(expense_type_id),
                branch_id=branch.id,
                customer_id=customer.id,
                payee_type="OTHER",
                payee_entity_id=customer.id,
                payee_name=customer.name,
                payment_method="cash",
                description=f"TraeSeed expense {seed_tag}",
                notes=f"TraeSeed expense {seed_tag}",
            )
            db.session.add(expense)

            check = Check(
                amount=_Q2("60"),
                currency="ILS",
                check_number=f"{seed_tag}01",
                check_bank="Trae Bank",
                check_date=now,
                check_due_date=now + timedelta(days=7),
                status=CheckStatus.PENDING.value,
                direction=PaymentDirection.IN.value,
                customer_id=customer.id,
                reference_number=f"TraeSeed check {seed_tag}",
                notes=f"TraeSeed check {seed_tag}",
                created_by_id=user.id,
            )
            db.session.add(check)

        update_customer_balance_components(customer.id)
        db.session.commit()

        click.echo(json.dumps({
            "seed_tag": seed_tag,
            "customer_id": customer.id,
            "warehouse_id": warehouse.id,
            "branch_id": branch.id,
            "sale_id": sale.id,
            "payment_id": pay_sale.id,
            "service_id": service.id,
            "expense_id": expense.id,
            "check_id": check.id,
        }, ensure_ascii=False))
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(f"Commit failed: {e}") from e

@click.command("seed-branches")
@click.option("--force", is_flag=True)
@with_appcontext
def seed_branches(force: bool) -> None:
    """إنشاء الفرع الرئيسي الافتراضي"""
    from models import Branch
    if _is_production() and not force:
        if not click.confirm("Production environment detected. Continue?", default=False):
            click.echo("Canceled.")
            return
    try:
        with _begin():
            # التحقق من وجود الفرع الرئيسي
            main_branch = Branch.query.filter(func.lower(Branch.code) == 'main').first()
            if not main_branch:
                main_branch = Branch(
                    code='MAIN',
                    name='الفرع الرئيسي',
                    is_active=True,
                    currency='ILS',
                    timezone='Asia/Jerusalem'
                )
                db.session.add(main_branch)
                click.echo("✅ Created main branch")
            else:
                click.echo("ℹ️  Main branch already exists")
        click.echo("OK: branches seeded.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("expense-type")
@click.option("--name", required=True)
@click.option("--desc", default="")
@click.option("--active/--inactive", default=True)
@with_appcontext
def expense_type_cmd(name: str, desc: str, active: bool) -> None:
    try:
        with _begin():
            ex=ExpenseType.query.filter(func.lower(ExpenseType.name)==name.strip().lower()).first()
            if not ex: ex=ExpenseType(name=name.strip(), description=(desc or "").strip(), is_active=bool(active)); db.session.add(ex)
            else:
                ex.description=(desc or ex.description or "").strip(); ex.is_active=bool(active)
        click.echo("OK: expense type created/updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(f"Commit failed: {e}") from e

@click.command("seed-palestine")
@click.option("--reset", is_flag=True)
@with_appcontext
def seed_palestine_cmd(reset: bool):
    try:
        from seed_palestine import seed_palestine as _seed_cmd
    except Exception as e:
        raise click.ClickException(f"تعذّر استيراد seed_palestine.py: {e}")
    cb=getattr(_seed_cmd,"callback",None)
    if callable(cb): return cb(reset=reset)
    return _seed_cmd(reset=reset)

@click.command("seed-all")
@click.option("--force", is_flag=True)
@click.option("--reset-roles", is_flag=True)
@click.option("--deactivate-missing-expense-types", is_flag=True)
@click.option("--allow-default-passwords", is_flag=True)
@with_appcontext
def seed_all(force: bool, reset_roles: bool, deactivate_missing_expense_types: bool, allow_default_passwords: bool) -> None:
    if _is_production() and not force:
        if not click.confirm("Production environment detected. Continue?", default=False):
            click.echo("Canceled.")
            return
    if _is_production() and not allow_default_passwords:
        weak = {"AZ123456", "ADMIN123", "STAFF123", "MECH123", "CUST123", "OWNER123", "DEV123", "MANAGER123"}
        if any(p in weak for p in (
            SUPER_PASSWORD, ADMIN_PASSWORD, STAFF_PASSWORD, MECH_PASSWORD, RC_PASSWORD,
            OWNER_PASSWORD, DEVELOPER_PASSWORD, MANAGER_PASSWORD
        )):
            raise click.ClickException("Refusing to seed weak default passwords in production. Use --allow-default-passwords to override.")
    try:
        try:
            _ensure_schema_ready()
        except Exception:
            pass
        with _begin():
            click.echo("• Ensuring permissions...")
            for code in sorted(RESERVED_CODES):
                _ensure_permission(code)

            click.echo("• Ensuring roles...")
            owner_role = _get_or_create_role("owner")
            developer_role = _get_or_create_role("developer")
            super_admin = _get_or_create_role("super_admin")
            admin = _get_or_create_role("admin")
            manager = _get_or_create_role("manager")
            staff = _get_or_create_role("staff")
            mechanic = _get_or_create_role("mechanic")
            registered_customer = _get_or_create_role("registered_customer")
            guest_role = _get_or_create_role("guest")

            click.echo("• Assigning full permissions to privileged roles...")
            all_perms = [p for p in Permission.query.all() if isinstance(p, Permission)]
            for super_role_obj in [owner_role, developer_role, super_admin]:
                if getattr(super_role_obj, "permissions", None) is None:
                    super_role_obj.permissions = []
                else:
                    super_role_obj.permissions[:] = [p for p in super_role_obj.permissions if isinstance(p, Permission)]
                curr = {(p.code or "").lower() for p in super_role_obj.permissions}
                for p in all_perms:
                    if (p.code or "").lower() not in curr:
                        super_role_obj.permissions.append(p)
                db.session.flush()

            click.echo("• Assigning module permissions to standard roles...")
            if 'admin' in ROLE_PERMISSIONS:
                _assign_role_perms(admin, ROLE_PERMISSIONS['admin'], reset=reset_roles)
            if 'manager' in ROLE_PERMISSIONS:
                _assign_role_perms(manager, ROLE_PERMISSIONS['manager'], reset=reset_roles)
            if 'staff' in ROLE_PERMISSIONS:
                _assign_role_perms(staff, ROLE_PERMISSIONS['staff'], reset=reset_roles)
            if 'mechanic' in ROLE_PERMISSIONS:
                _assign_role_perms(mechanic, ROLE_PERMISSIONS['mechanic'], reset=reset_roles)
            if 'registered_customer' in ROLE_PERMISSIONS:
                _assign_role_perms(registered_customer, ROLE_PERMISSIONS['registered_customer'], reset=reset_roles)
            if 'guest' in ROLE_PERMISSIONS:
                _assign_role_perms(guest_role, ROLE_PERMISSIONS['guest'], reset=reset_roles)

            click.echo("• Ensuring users...")
            owner_user = _get_or_create_user(OWNER_USERNAME, OWNER_EMAIL, OWNER_PASSWORD, owner_role)
            developer_user = _get_or_create_user(DEVELOPER_USERNAME, DEVELOPER_EMAIL, DEVELOPER_PASSWORD, developer_role)
            owner_user.is_system_account = True
            developer_user.is_system_account = True

            _get_or_create_user(SUPER_USERNAME, SUPER_EMAIL, SUPER_PASSWORD, super_admin)
            _get_or_create_user(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, admin)
            _get_or_create_user(MANAGER_USERNAME, MANAGER_EMAIL, MANAGER_PASSWORD, manager)
            _get_or_create_user(STAFF_USERNAME, STAFF_EMAIL, STAFF_PASSWORD, staff)
            _get_or_create_user(MECH_USERNAME, MECH_EMAIL, MECH_PASSWORD, mechanic)
            _get_or_create_user(RC_USERNAME, RC_EMAIL, RC_PASSWORD, registered_customer)

            click.echo("• Clearing RBAC caches...")
            for r in Role.query.all():
                try:
                    clear_role_permission_cache(r.id)
                    clear_users_cache_by_role(r.id)
                except Exception:
                    pass

            click.echo("• Seeding base expense types...")
            base_types = [
                ("رواتب", "مصروف رواتب وأجور", True),
                ("كهرباء", "فواتير كهرباء", True),
                ("مياه", "فواتير مياه", True),
                ("جمارك", "رسوم جمركية", True),
                ("تالف", "توالف/هدر مخزون", True),
                ("استخدام داخلي", "استهلاك داخلي للمخزون", True),
                ("متفرقات", "مصروفات أخرى", True),
            ]
            wanted_names = set()
            for name, desc, active in base_types:
                wanted_names.add(name.lower())
                ex = ExpenseType.query.filter(func.lower(ExpenseType.name) == name.lower()).first()
                if not ex:
                    db.session.add(ExpenseType(name=name, description=desc, is_active=bool(active)))
                else:
                    ex.description = desc
                    ex.is_active = bool(active)
            if deactivate_missing_expense_types:
                others = ExpenseType.query.filter(func.lower(ExpenseType.name).notin_(wanted_names)).all()
                for ex in others:
                    ex.is_active = False

        click.echo("✔ OK: seed-all completed.")
    except SQLAlchemyError as e:
        db.session.rollback()
        traceback.print_exc()
        raise click.ClickException(f"Commit failed: {e}") from e

@click.command("clear-rbac-caches")
@with_appcontext
def clear_rbac_caches() -> None:
    for r in Role.query.all():
        try: clear_role_permission_cache(r.id); clear_users_cache_by_role(r.id)
        except Exception: pass
    click.echo("OK: RBAC caches cleared.")

@click.command("wh-create")
@click.option("--name", required=True)
@click.option("--type", "wtype", default="MAIN")
@click.option("--location", default="")
@click.option("--supplier-id", type=int)
@click.option("--partner-id", type=int)
@click.option("--share-percent", type=float, default=0.0)
@click.option("--online-slug", default="")
@click.option("--online-default/--no-online-default", default=False)
@with_appcontext
def wh_create(name, wtype, location, supplier_id, partner_id, share_percent, online_slug, online_default):
    try:
        with _begin():
            w=Warehouse(name=name.strip(), warehouse_type=wtype.strip().upper(), location=location or None, supplier_id=supplier_id, partner_id=partner_id, share_percent=share_percent or 0, online_slug=(online_slug or None), online_is_default=bool(online_default))
            db.session.add(w)
        click.echo(f"OK: warehouse {w.id} created.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("wh-list")
@click.option("--active", type=bool)
@click.option("--type", "wtype", default="")
@with_appcontext
def wh_list(active, wtype):
    q=Warehouse.query
    if active is not None: q=q.filter(Warehouse.is_active==bool(active))
    if wtype: q=q.filter(Warehouse.warehouse_type==wtype.strip().upper())
    for w in q.order_by(Warehouse.id).all():
        click.echo(f"{w.id:>3}  {w.name:<25} type={getattr(w.warehouse_type,'value',w.warehouse_type)} active={w.is_active} partner={w.partner_id or '-'} supplier={w.supplier_id or '-'}")

@click.command("wh-stock")
@click.option("--warehouse-id", type=int, required=True)
@click.option("--q", default="")
@with_appcontext
def wh_stock(warehouse_id: int, q: str):
    qry = (
        db.session.query(StockLevel, Product)
        .join(Product, Product.id == StockLevel.product_id)
        .filter(StockLevel.warehouse_id == warehouse_id)
    )
    s = (q or "").strip()
    if s:
        ss = f"%{s.lower()}%"
        qry = qry.filter(
            or_(
                func.lower(Product.name).like(ss),
                func.lower(Product.sku).like(ss),
                func.lower(Product.part_number).like(ss),
                func.lower(Product.brand).like(ss),
            )
        )
    for lvl, prod in qry.order_by(Product.name).all():
        click.echo(
            f"P{prod.id:<5} {prod.name[:40]:<40} "
            f"qty={lvl.quantity:<6} reserved={lvl.reserved_quantity:<6} "
            f"avail={lvl.available_quantity:<6} status={lvl.status}"
        )

@click.command("product-create")
@click.option("--name", required=True)
@click.option("--price", type=float, default=0)
@click.option("--brand", default="")
@click.option("--part-number", default="")
@click.option("--sku", default="")
@click.option("--barcode", default="")
@click.option("--tax-rate", type=float, default=0)
@with_appcontext
def product_create(name, price, brand, part_number, sku, barcode, tax_rate):
    try:
        with _begin():
            p=Product(name=name.strip(), price=_Q2(price), selling_price=_Q2(price), brand=brand or None, part_number=part_number or None, sku=sku or None, barcode=barcode or None, tax_rate=_Q2(tax_rate))
            db.session.add(p)
        click.echo(f"OK: product {p.id} created.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("product-find")
@click.option("--q", default="")
@click.option("--barcode", default="")
@click.option("--limit", type=int, default=50)
@with_appcontext
def product_find(q: str, barcode: str, limit: int):
    qry = Product.query
    if barcode.strip():
        qry = qry.filter(Product.barcode == barcode.strip())
    else:
        s = (q or "").strip().lower()
        if s:
            ss = f"%{s}%"
            qry = qry.filter(
                or_(
                    func.lower(Product.name).like(ss),
                    func.lower(Product.brand).like(ss),
                    func.lower(Product.part_number).like(ss),
                    func.lower(Product.sku).like(ss),
                )
            )
    rows = qry.order_by(Product.id.desc()).limit(limit).all()
    for p in rows:
        click.echo(
            f"{p.id:>4}  {p.name[:50]:<50} price={float(p.price or 0):.2f} "
            f"brand={p.brand or '-'} part={p.part_number or '-'} sku={p.sku or '-'}"
        )

@click.command("product-stock")
@click.option("--product-id", type=int, required=True)
@with_appcontext
def product_stock(product_id: int):
    lvls=StockLevel.query.filter(StockLevel.product_id==product_id).all()
    if not lvls: click.echo("No stock rows."); return
    for lvl in lvls:
        w=db.session.get(Warehouse, lvl.warehouse_id)
        click.echo(f"WH{lvl.warehouse_id:<4} {w.name if w else '-':<25} qty={lvl.quantity:<6} reserved={lvl.reserved_quantity:<6} avail={lvl.available_quantity:<6}")

@click.command("product-set-price")
@click.option("--product-id", type=int, required=True)
@click.option("--price", type=float, required=True)
@with_appcontext
def product_set_price(product_id: int, price: float):
    p=db.session.get(Product, product_id)
    if not p: raise click.ClickException("Product not found")
    try:
        with _begin(): p.price=_Q2(price); p.selling_price=_Q2(price)
        click.echo("OK: price updated.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-transfer")
@click.option("--product-id", type=int, required=True)
@click.option("--source-id", type=int, required=True)
@click.option("--destination-id", type=int, required=True)
@click.option("--qty", type=int, required=True)
@click.option("--ref", default="")
@click.option("--notes", default="")
@with_appcontext
def stock_transfer(product_id, source_id, destination_id, qty, ref, notes):
    try:
        with _begin():
            t=Transfer(reference=ref or None, product_id=product_id, source_id=source_id, destination_id=destination_id, quantity=int(qty), direction=TransferDirection.OUTGOING.value, notes=notes or None)
            db.session.add(t)
        click.echo(f"OK: transfer {t.reference} saved.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-exchange")
@click.option("--product-id", type=int, required=True)
@click.option("--warehouse-id", type=int, required=True)
@click.option("--direction", type=click.Choice(["IN","OUT","ADJUSTMENT"], case_sensitive=False), required=True)
@click.option("--qty", type=int, required=True)
@click.option("--unit-cost", type=float, default=0.0)
@click.option("--notes", default="")
@with_appcontext
def stock_exchange(product_id, warehouse_id, direction, qty, unit_cost, notes):
    try:
        with _begin():
            tx=ExchangeTransaction(product_id=product_id, warehouse_id=warehouse_id, direction=direction.upper(), quantity=int(qty), unit_cost=_Q2(unit_cost) if unit_cost else None, notes=notes or None)
            db.session.add(tx)
        click.echo(f"OK: exchange tx #{tx.id} saved.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-reserve")
@click.option("--product-id", type=int, required=True)
@click.option("--warehouse-id", type=int, required=True)
@click.option("--qty", type=int, required=True)
@with_appcontext
def stock_reserve(product_id, warehouse_id, qty):
    row=db.session.execute(select(StockLevel).where(StockLevel.product_id==product_id, StockLevel.warehouse_id==warehouse_id)).scalar_one_or_none()
    if not row: raise click.ClickException("Stock row not found")
    if row.available_quantity < qty: raise click.ClickException("Insufficient available quantity")
    try:
        with _begin(): row.reserved_quantity=int(row.reserved_quantity or 0)+int(qty)
        click.echo("OK: reserved.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-unreserve")
@click.option("--product-id", type=int, required=True)
@click.option("--warehouse-id", type=int, required=True)
@click.option("--qty", type=int, required=True)
@with_appcontext
def stock_unreserve(product_id, warehouse_id, qty):
    row=db.session.execute(select(StockLevel).where(StockLevel.product_id==product_id, StockLevel.warehouse_id==warehouse_id)).scalar_one_or_none()
    if not row: raise click.ClickException("Stock row not found")
    newv=int(row.reserved_quantity or 0)-int(qty)
    if newv < 0: newv=0
    try:
        with _begin(): row.reserved_quantity=newv
        click.echo("OK: unreserved.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("shipment-create")
@click.option("--destination-id", type=int, required=True)
@click.option("--currency", default="USD")
@click.option("--date", "sdate", default="")
@click.option("--items-json", "items_json", required=True)
@click.option("--status", default=ShipmentStatus.DRAFT.value)
@with_appcontext
def shipment_create(destination_id, currency, sdate, items_json, status):
    try_load=items_json.strip()
    if os.path.exists(try_load):
        with open(try_load,"r",encoding="utf-8") as f: items=json.load(f)
    else:
        items=json.loads(try_load)
    try:
        with _begin():
            sh=Shipment(destination_id=destination_id, currency=currency.upper(), date=_parse_dt(sdate) if sdate else datetime.now(timezone.utc).replace(tzinfo=None), status=status.strip().upper())
            db.session.add(sh); db.session.flush()
            for it in items:
                db.session.add(ShipmentItem(shipment_id=sh.id, product_id=int(it["product_id"]), warehouse_id=int(it.get("warehouse_id") or destination_id), quantity=int(it["quantity"]), unit_cost=_Q2(it.get("unit_cost",0)), notes=it.get("notes")))
        click.echo(f"OK: shipment {sh.shipment_number or sh.number} created.")
    except Exception as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("shipment-status")
@click.option("--shipment-id", type=int, required=True)
@click.option("--status", type=click.Choice([s.value for s in ShipmentStatus], case_sensitive=False), required=True)
@with_appcontext
def shipment_status(shipment_id: int, status: str):
    sh=db.session.get(Shipment, shipment_id)
    if not sh: raise click.ClickException("Shipment not found")
    try:
        with _begin(): sh.update_status(status.upper())
        click.echo(f"OK: shipment {shipment_id} -> {status.upper()}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("supplier-settlement-draft")
@click.option("--supplier-id", type=int, required=True)
@click.option("--from", "date_from", required=True)
@click.option("--to", "date_to", required=True)
@click.option("--currency", default="ILS")
@click.option("--mode", type=click.Choice(["ON_RECEIPT","ON_CONSUME"], case_sensitive=False))
@with_appcontext
def supplier_settlement_draft(supplier_id, date_from, date_to, currency, mode):
    df=_parse_dt(date_from); dt=_parse_dt(date_to)
    ss=build_supplier_settlement_draft(supplier_id, df, dt, currency=currency, mode=mode)
    try:
        with _begin(): db.session.add(ss)
        click.echo(f"OK: supplier settlement {ss.code} draft with {len(ss.lines or [])} lines, due={float(ss.total_due or 0):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("supplier-settlement-confirm")
@click.option("--id", "settlement_id", type=int, required=True)
@with_appcontext
def supplier_settlement_confirm(settlement_id: int):
    ss=db.session.get(SupplierSettlement, settlement_id)
    if not ss: raise click.ClickException("Settlement not found")
    try:
        with _begin(): ss.mark_confirmed()
        click.echo(f"OK: supplier settlement {ss.code} confirmed.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("partner-settlement-draft")
@click.option("--partner-id", type=int, required=True)
@click.option("--from", "date_from", required=True)
@click.option("--to", "date_to", required=True)
@click.option("--currency", default="ILS")
@with_appcontext
def partner_settlement_draft(partner_id, date_from, date_to, currency):
    df=_parse_dt(date_from); dt=_parse_dt(date_to)
    ps=build_partner_settlement_draft(partner_id, df, dt, currency=currency)
    try:
        with _begin(): db.session.add(ps)
        click.echo(f"OK: partner settlement {ps.code} draft with {len(ps.lines or [])} lines, due={float(ps.total_due or 0):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("partner-settlement-confirm")
@click.option("--id", "settlement_id", type=int, required=True)
@with_appcontext
def partner_settlement_confirm(settlement_id: int):
    ps=db.session.get(PartnerSettlement, settlement_id)
    if not ps: raise click.ClickException("Settlement not found")
    try:
        with _begin(): ps.mark_confirmed()
        click.echo(f"OK: partner settlement {ps.code} confirmed.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

def _method_enum(v: str): return getattr(PaymentMethod, v.upper()).value if v else PaymentMethod.CASH.value
def _status_enum(v: str): return getattr(PaymentStatus, v.upper()).value if v else PaymentStatus.PENDING.value
def _direction_enum(v: str): return getattr(PaymentDirection, v.upper()).value if v else PaymentDirection.IN.value
def _entity_enum(v: str): return getattr(PaymentEntityType, v.upper()).value if v else PaymentEntityType.CUSTOMER.value

@click.command("payment-create")
@click.option("--direction", default="IN", type=click.Choice(["IN", "OUT"], case_sensitive=False))
@click.option("--entity-type", "entity_type", required=True, type=click.Choice([e.value for e in PaymentEntityType], case_sensitive=False))
@click.option("--target-id", type=int, required=True)
@click.option("--amount", type=float, required=True)
@click.option("--method", default=PaymentMethod.CASH.value, type=click.Choice([e.value for e in PaymentMethod], case_sensitive=False))
@click.option("--status", default=PaymentStatus.COMPLETED.value, type=click.Choice([e.value for e in PaymentStatus], case_sensitive=False))
@click.option("--currency", default="ILS")
@click.option("--reference", default="")
@click.option("--notes", default="")
@with_appcontext
def payment_create(direction, entity_type, target_id, amount, method, status, currency, reference, notes):
    fields = {
        PaymentEntityType.CUSTOMER.value: "customer_id",
        PaymentEntityType.SUPPLIER.value: "supplier_id",
        PaymentEntityType.PARTNER.value: "partner_id",
        PaymentEntityType.SHIPMENT.value: "shipment_id",
        PaymentEntityType.EXPENSE.value: "expense_id",
        PaymentEntityType.LOAN.value: "loan_settlement_id",
        PaymentEntityType.SALE.value: "sale_id",
        PaymentEntityType.INVOICE.value: "invoice_id",
        PaymentEntityType.PREORDER.value: "preorder_id",
        PaymentEntityType.SERVICE.value: "service_id",
    }
    fk = fields.get(entity_type)
    if not fk:
        raise click.ClickException(f"Unsupported entity-type: {entity_type}")
    try:
        with _begin():
            entity_kwargs = {fk: int(target_id)}
            
            p = Payment(
                total_amount=_Q2(amount),
                method=_method_enum(method),
                status=_status_enum(status),
                direction=_direction_enum(direction),
                entity_type=_entity_enum(entity_type),
                currency=currency.upper(),
                reference=reference or None,
                notes=notes or None,
                **entity_kwargs,
            )
            db.session.add(p)
        click.echo(f"OK: payment {p.payment_number} created for {entity_type}={target_id} amount={float(p.total_amount):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e

@click.command("payment-list")
@click.option("--status", default="")
@click.option("--direction", default="")
@click.option("--entity-type", default="")
@click.option("--limit", type=int, default=100)
@with_appcontext
def payment_list(status, direction, entity_type, limit):
    q=Payment.query
    if status.strip(): q=q.filter(Payment.status==status.strip().upper())
    if direction.strip(): q=q.filter(Payment.direction==direction.strip().upper())
    if entity_type.strip(): q=q.filter(Payment.entity_type==entity_type.strip().upper())
    for p in q.order_by(Payment.id.desc()).limit(limit).all():
        click.echo(f"{p.id:>5} {p.payment_number:<16} {p.payment_date} {getattr(p,'entity_type',''):<10} amt={float(p.total_amount):.2f} {getattr(p,'status','')} {getattr(p,'direction','')} -> {p.entity_label()}")

@click.command("invoice-list")
@click.option("--status", default="")
@click.option("--customer-id", type=int)
@click.option("--limit", type=int, default=100)
@with_appcontext
def invoice_list(status, customer_id, limit):
    q=Invoice.query
    if status.strip(): q=q.filter(Invoice.status==status.strip().upper())
    if customer_id: q=q.filter(Invoice.customer_id==int(customer_id))
    for inv in q.order_by(Invoice.id.desc()).limit(limit).all():
        click.echo(f"{inv.id:>5} {inv.invoice_number or '-':<14} cust={inv.customer_id or '-':<5} total={float(inv.total_amount or 0):.2f} paid={float(inv.total_paid):.2f} due={float(inv.balance_due):.2f} status={inv.status}")

@click.command("invoice-update-status")
@click.option("--id", "invoice_id", type=int, required=True)
@with_appcontext
def invoice_update_status(invoice_id: int):
    inv=db.session.get(Invoice, invoice_id)
    if not inv: raise click.ClickException("Invoice not found")
    try:
        with _begin():
            db.session.flush()
        click.echo(f"OK: invoice {invoice_id} status -> {inv.status}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("preorder-create")
@click.option("--product-id", type=int, required=True)
@click.option("--warehouse-id", type=int, required=True)
@click.option("--quantity", type=int, required=True)
@click.option("--customer-id", type=int)
@click.option("--supplier-id", type=int)
@click.option("--partner-id", type=int)
@click.option("--prepaid", type=float, default=0.0)
@click.option("--tax-rate", type=float, default=0.0)
@click.option("--method", default="CASH", type=click.Choice([e.value for e in PaymentMethod], case_sensitive=False))
@with_appcontext
def preorder_create(product_id, warehouse_id, quantity, customer_id, supplier_id, partner_id, prepaid, tax_rate, method):
    if not any([customer_id, supplier_id, partner_id]):
        raise click.ClickException("One of customer-id/supplier-id/partner-id is required")
    try:
        with _begin():
            po = PreOrder(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=int(quantity),
                customer_id=customer_id,
                supplier_id=supplier_id,
                partner_id=partner_id,
                prepaid_amount=_Q2(prepaid),
                tax_rate=_Q2(tax_rate),
                payment_method=getattr(PaymentMethod, method.upper()).value,
            )
            db.session.add(po)
            db.session.flush()
            if _Q2(prepaid) > 0:
                p = Payment(
                    total_amount=_Q2(prepaid),
                    method=getattr(PaymentMethod, method.upper()).value,
                    status=PaymentStatus.COMPLETED.value,
                    direction=PaymentDirection.IN.value,
                    entity_type=PaymentEntityType.PREORDER.value,
                    preorder_id=po.id,
                    currency="ILS",
                    reference=f"PreOrder:{po.reference}",
                )
                db.session.add(p)
        click.echo(f"OK: preorder {po.reference} created.")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e
@click.command("sr-create")
@click.option("--customer-id", type=int, required=True)
@click.option("--tax-rate", type=float, default=0.0)
@click.option("--discount-total", type=float, default=0.0)
@click.option("--currency", type=str, default="ILS")
@click.option("--status", type=click.Choice([e.value for e in ServiceStatus]), default=ServiceStatus.PENDING.value)
@click.option("--notes", type=str, default=None)
@with_appcontext
def sr_create(customer_id, tax_rate, discount_total, currency, status, notes):
    sr=ServiceRequest(customer_id=customer_id, tax_rate=_Q2(tax_rate), discount_total=_Q2(discount_total), currency=(currency or "ILS").upper(), status=status, notes=notes)
    try:
        with _begin(): db.session.add(sr)
        click.echo(f"OK: service {sr.service_number} created.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("sr-add-part")
@click.option("--service-id", type=int, required=True)
@click.option("--product-id", type=int, required=True)
@click.option("--warehouse-id", type=int, required=True)
@click.option("--quantity", type=int, required=True)
@click.option("--unit-price", type=str, required=True)
@click.option("--discount", type=str, default="0")
@click.option("--tax-rate", type=str, default="0")
@click.option("--partner-id", type=int, default=None)
@click.option("--share-percentage", type=str, default="0")
@click.option("--note", type=str, default=None)
@click.option("--notes", type=str, default=None)
@with_appcontext
def sr_add_part(service_id, product_id, warehouse_id, quantity, unit_price, discount, tax_rate, partner_id, share_percentage, note, notes):
    sr=db.session.get(ServiceRequest, service_id)
    if not sr: raise click.ClickException("ServiceRequest not found")
    part=ServicePart(service_id=sr.id, part_id=product_id, warehouse_id=warehouse_id, quantity=int(quantity), unit_price=_Q2(unit_price), discount=_Q2(discount), tax_rate=_Q2(tax_rate), partner_id=partner_id, share_percentage=_Q2(share_percentage), note=note, notes=notes)
    try:
        with _begin(): db.session.add(part)
        click.echo(f"OK: part {part.id} added to service {sr.service_number or sr.id}.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("sr-add-task")
@click.option("--service-id", type=int, required=True)
@click.option("--description", type=str, required=True)
@click.option("--quantity", type=int, default=1)
@click.option("--unit-price", type=str, required=True)
@click.option("--discount", type=str, default="0")
@click.option("--tax-rate", type=str, default="0")
@click.option("--partner-id", type=int, default=None)
@click.option("--share-percentage", type=str, default="0")
@click.option("--note", type=str, default=None)
@with_appcontext
def sr_add_task(service_id, description, quantity, unit_price, discount, tax_rate, partner_id, share_percentage, note):
    sr=db.session.get(ServiceRequest, service_id)
    if not sr: raise click.ClickException("ServiceRequest not found")
    task=ServiceTask(service_id=sr.id, description=description, quantity=int(quantity), unit_price=_Q2(unit_price), discount=_Q2(discount), tax_rate=_Q2(tax_rate), partner_id=partner_id, share_percentage=_Q2(share_percentage), note=note)
    try:
        with _begin(): db.session.add(task)
        click.echo(f"OK: task {task.id} added to service {sr.service_number or sr.id}.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("sr-recalc")
@click.option("--service-id", type=int, required=True)
@with_appcontext
def sr_recalc(service_id):
    sr = db.session.get(ServiceRequest, service_id)
    if not sr:
        raise click.ClickException("ServiceRequest not found")
    try:
        with _begin():
            sr.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            sr.recalc_totals()
        click.echo(f"OK: recalc -> total={float(sr.total_amount or 0):.2f} parts={float(sr.parts_total or 0):.2f} labor={float(sr.labor_total or 0):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e

@click.command("sr-set-status")
@click.option("--service-id", type=int, required=True)
@click.option("--status", type=click.Choice([e.value for e in ServiceStatus]), required=True)
@click.option("--post-gl/--no-post-gl", default=False)
@with_appcontext
def sr_set_status(service_id, status, post_gl):
    sr = db.session.get(ServiceRequest, service_id)
    if not sr:
        raise click.ClickException("ServiceRequest not found")
    prev = sr.status
    try:
        with _begin():
            sr.status = status
        if post_gl and status == ServiceStatus.COMPLETED.value:
            parts = _D(getattr(sr, "parts_total", 0) or 0)
            labor = _D(getattr(sr, "labor_total", 0) or 0)
            discount = _D(getattr(sr, "discount_total", 0) or 0)
            tax_rate = _D(getattr(sr, "tax_rate", 0) or 0)
            base = parts + labor - discount
            if base < 0:
                base = Decimal("0.00")
            tax = base * (tax_rate / Decimal("100"))
            total = base + tax
            entries = []
            if "AR" in GL_ACCOUNTS:
                entries.append((GL_ACCOUNTS["AR"], float(_Q2(total)), 0.0))
            if "VAT" in GL_ACCOUNTS:
                entries.append((GL_ACCOUNTS["VAT"], 0.0, float(_Q2(tax))))
            if "REV" in GL_ACCOUNTS:
                entries.append((GL_ACCOUNTS["REV"], 0.0, float(_Q2(total - tax))))
            if entries:
                _gl_upsert_batch_and_entries(
                    db.session.connection(),
                    source_type="SERVICE",
                    source_id=sr.id,
                    purpose="SERVICE_COMPLETE",
                    currency=(sr.currency or "ILS").upper(),
                    memo=f"Service {sr.service_number or sr.id} completed",
                    entries=entries,
                    ref=str(sr.service_number or sr.id),
                    entity_type="CUSTOMER",
                    entity_id=sr.customer_id,
                )
        click.echo(f"OK: service {service_id} {prev} -> {status}")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e

@click.command("sr-show")
@click.option("--service-id", type=int, required=True)
@with_appcontext
def sr_show(service_id):
    sr=db.session.get(ServiceRequest, service_id)
    if not sr: raise click.ClickException("ServiceRequest not found")
    data={"id":sr.id,"service_number":sr.service_number,"customer_id":sr.customer_id,"status":getattr(sr.status,"value",sr.status),"parts_total":float(sr.parts_total or 0),"labor_total":float(sr.labor_total or 0),"discount_total":float(sr.discount_total or 0),"tax_rate":float(sr.tax_rate or 0),"total_amount":float(sr.total_amount or 0),"currency":sr.currency,"completed_at":sr.completed_at.isoformat() if getattr(sr,"completed_at",None) else None,"parts":[p.to_dict() for p in (sr.parts or [])],"tasks":[t.to_dict() for t in (sr.tasks or [])]}
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))

@click.command("cart-create")
@click.option("--customer-id", type=int, default=None)
@click.option("--session-id", type=str, default=None)
@with_appcontext
def cart_create(customer_id, session_id):
    cart=OnlineCart(customer_id=customer_id, session_id=session_id)
    try:
        with _begin(): db.session.add(cart)
        click.echo(f"OK: cart {cart.cart_id} created.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("cart-add-item")
@click.option("--cart-id", type=int, required=True)
@click.option("--product-id", type=int, required=True)
@click.option("--quantity", type=int, default=1)
@click.option("--price", type=str, required=True)
@with_appcontext
def cart_add_item(cart_id, product_id, quantity, price):
    cart=db.session.get(OnlineCart, cart_id)
    if not cart: raise click.ClickException("Cart not found")
    item=OnlineCartItem(cart_id=cart.id, product_id=product_id, quantity=int(quantity), price=_Q2(price))
    try:
        with _begin(): db.session.add(item)
        click.echo(f"OK: item {item.id} added. subtotal={cart.subtotal} count={cart.item_count}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("order-from-cart")
@click.option("--cart-id", type=int, required=True)
@click.option("--customer-id", type=int, required=True)
@click.option("--warehouse-id", type=int, default=None)
@with_appcontext
def order_from_cart(cart_id, customer_id, warehouse_id):
    cart=db.session.get(OnlineCart, cart_id)
    if not cart: raise click.ClickException("Cart not found")
    order=OnlinePreOrder(customer_id=customer_id, cart_id=cart.id, warehouse_id=warehouse_id)
    try:
        with _begin():
            db.session.add(order); db.session.flush()
            for it in (cart.items or []):
                db.session.add(OnlinePreOrderItem(order_id=order.id, product_id=it.product_id, quantity=it.quantity, price=it.price))
            order.update_totals_and_status()
        click.echo(f"OK: order {order.order_number} total={float(order.total_amount or 0):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("order-set-status")
@click.option("--order-id", type=int, required=True)
@click.option("--status", type=click.Choice(["PENDING","CONFIRMED","FULFILLED","CANCELLED"]), required=True)
@with_appcontext
def order_set_status(order_id, status):
    order=db.session.get(OnlinePreOrder, order_id)
    if not order: raise click.ClickException("Order not found")
    prev=order.status
    try:
        with _begin(): order.status=status
        click.echo(f"OK: order {order_id} {prev} -> {status} total={float(order.total_amount or 0):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("order-add-item")
@click.option("--order-id", type=int, required=True)
@click.option("--product-id", type=int, required=True)
@click.option("--quantity", type=int, default=1)
@click.option("--price", type=str, required=True)
@with_appcontext
def order_add_item(order_id, product_id, quantity, price):
    order=db.session.get(OnlinePreOrder, order_id)
    if not order: raise click.ClickException("Order not found")
    it=OnlinePreOrderItem(order_id=order.id, product_id=product_id, quantity=int(quantity), price=_Q2(price))
    try:
        with _begin(): db.session.add(it); order.update_totals_and_status()
        click.echo(f"OK: item {it.id} added. order_total={float(order.total_amount or 0):.2f} payment_status={order.payment_status}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("onlinepay-create")
@click.option("--order-id", type=int, required=True)
@click.option("--amount", type=str, required=True)
@click.option("--currency", type=str, default="ILS")
@click.option("--method", type=str, default=None)
@click.option("--gateway", type=str, default=None)
@click.option("--status", type=click.Choice(["PENDING","SUCCESS","FAILED","REFUNDED"]), default="PENDING")
@click.option("--card-pan", type=str, default=None)
@click.option("--card-holder", type=str, default=None)
@click.option("--card-expiry", type=str, default=None)
@with_appcontext
def onlinepay_create(order_id, amount, currency, method, gateway, status, card_pan, card_holder, card_expiry):
    order=db.session.get(OnlinePreOrder, order_id)
    if not order: raise click.ClickException("Order not found")
    p=OnlinePayment(order_id=order.id, amount=_Q2(amount), currency=(currency or "ILS").upper(), method=method, gateway=gateway, status=status)
    if card_pan or card_holder or card_expiry: p.set_card_details(card_pan, card_holder, card_expiry, validate=True)
    p.payment_ref=f"OP-{uuid.uuid4().hex[:10].upper()}"
    try:
        with _begin(): db.session.add(p); db.session.flush(); order.update_totals_and_status()
        click.echo(f"OK: payment {p.payment_ref} status={p.status} balance_due={order.balance_due}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("onlinepay-decrypt-card")
@click.option("--payment-id", type=int, required=True)
@with_appcontext
def onlinepay_decrypt_card(payment_id):
    p=db.session.get(OnlinePayment, payment_id)
    if not p: raise click.ClickException("Payment not found")
    num=p.decrypt_card_number(); click.echo(num or "")

@click.command("expense-create")
@click.option("--amount", type=str, required=True)
@click.option("--type-id", type=int, required=True)
@click.option("--branch-id", type=int, default=None)
@click.option("--currency", type=str, default="ILS")
@click.option("--payee-type", type=click.Choice(["EMPLOYEE","SUPPLIER","CUSTOMER","PARTNER","WAREHOUSE","SHIPMENT","UTILITY","OTHER"]), default="OTHER")
@click.option("--payee-entity-id", type=int, default=None)
@click.option("--payee-name", type=str, default=None)
@click.option("--payment-method", type=click.Choice(["cash","cheque","bank","card","online","other"]), default="cash")
@click.option("--description", type=str, default=None)
@click.option("--notes", type=str, default=None)
@with_appcontext
def expense_create(amount, type_id, branch_id, currency, payee_type, payee_entity_id, payee_name, payment_method, description, notes):
    resolved_branch_id = branch_id
    if not resolved_branch_id:
        b = (
            Branch.query.filter(Branch.is_active.is_(True))
            .order_by(Branch.id.asc())
            .first()
        ) or Branch.query.order_by(Branch.id.asc()).first()
        resolved_branch_id = b.id if b else None
    if not resolved_branch_id:
        raise click.ClickException("No branch found. Create/activate a branch first or pass --branch-id.")
    resolved_payee_type = (payee_type or "OTHER").upper()
    entity_id = int(payee_entity_id) if payee_entity_id else None
    link_kwargs = {}
    if entity_id:
        if resolved_payee_type == "CUSTOMER":
            link_kwargs["customer_id"] = entity_id
        elif resolved_payee_type == "SUPPLIER":
            link_kwargs["supplier_id"] = entity_id
        elif resolved_payee_type == "PARTNER":
            link_kwargs["partner_id"] = entity_id
        elif resolved_payee_type == "WAREHOUSE":
            link_kwargs["warehouse_id"] = entity_id
        elif resolved_payee_type == "SHIPMENT":
            link_kwargs["shipment_id"] = entity_id
        elif resolved_payee_type == "EMPLOYEE":
            link_kwargs["employee_id"] = entity_id
        elif resolved_payee_type == "UTILITY":
            link_kwargs["utility_account_id"] = entity_id

    resolved_payee_name = (payee_name or "").strip() or None
    if not resolved_payee_name and entity_id:
        obj = None
        if resolved_payee_type == "CUSTOMER":
            obj = db.session.get(Customer, entity_id)
        elif resolved_payee_type == "SUPPLIER":
            obj = db.session.get(Supplier, entity_id)
        elif resolved_payee_type == "PARTNER":
            obj = db.session.get(Partner, entity_id)
        elif resolved_payee_type == "WAREHOUSE":
            obj = db.session.get(Warehouse, entity_id)
        resolved_payee_name = getattr(obj, "name", None) if obj else None

    ex=Expense(amount=_Q2(amount), type_id=type_id, branch_id=int(resolved_branch_id), currency=(currency or "ILS").upper(), payee_type=resolved_payee_type, payee_entity_id=entity_id, payee_name=resolved_payee_name, payment_method=payment_method, description=description, notes=notes, date=datetime.now(timezone.utc).replace(tzinfo=None), **link_kwargs)
    try:
        with _begin(): db.session.add(ex)
        click.echo(f"OK: expense {ex.id} amount={float(ex.amount):.2f} balance={ex.balance:.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("expense-pay")
@click.option("--expense-id", type=int, required=True)
@click.option("--amount", type=str, required=True)
@click.option("--method", type=click.Choice(["cash","cheque","bank","card","online","other"]), default="cash")
@click.option("--currency", type=str, default="ILS")
@with_appcontext
def expense_pay(expense_id, amount, method, currency):
    ex=db.session.get(Expense, expense_id)
    if not ex: raise click.ClickException("Expense not found")
    amt=_Q2(amount)
    p=Payment(direction=PaymentDirection.OUT.value, entity_type=PaymentEntityType.EXPENSE.value, expense_id=ex.id, total_amount=amt, currency=(currency or "ILS").upper(), method=method.lower(), status=PaymentStatus.COMPLETED.value, reference=f"EXP-{ex.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    try:
        with _begin(): db.session.add(p)
        click.echo(f"OK: expense paid. payment_id={p.id} balance={ex.balance:.2f} is_paid={ex.is_paid}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("expense-link-known-entities")
@with_appcontext
def expense_link_known_entities():
    updated = {"naser": 0, "mahal": 0, "baraa": 0}
    naser_name = "نصر  خالد"
    naser = db.session.query(Employee).filter(Employee.name == naser_name).one_or_none()
    if naser:
        q = db.session.query(Expense).filter(
            Expense.employee_id.is_(None),
            Expense.supplier_id.is_(None),
            Expense.partner_id.is_(None),
            Expense.customer_id.is_(None),
            (Expense.payee_name.contains("نصر")) | (Expense.payee_name.contains("[افتراضي] نصر"))
        )
        for e in q.yield_per(100):
            e.employee_id = naser.id
            e.payee_type = "EMPLOYEE"
            e.payee_entity_id = naser.id
            e.payee_name = naser_name
            updated["naser"] += 1
    q = db.session.query(Expense).filter(Expense.payee_name == "المحل")
    for e in q.yield_per(100):
        e.payee_name = "المركز الرئيسي"
        updated["mahal"] += 1
    baraa_name = "براء – خدمات تنظيف"
    supplier = db.session.query(Supplier).filter(Supplier.name == baraa_name).one_or_none()
    if not supplier:
        supplier = Supplier(name=baraa_name, is_local=True)
        db.session.add(supplier)
        db.session.flush()
    q = db.session.query(Expense).filter(
        Expense.supplier_id.is_(None),
        Expense.partner_id.is_(None),
        Expense.customer_id.is_(None),
        Expense.employee_id.is_(None),
        Expense.payee_name == "براء"
    )
    for e in q.yield_per(100):
        e.supplier_id = supplier.id
        e.payee_type = "SUPPLIER"
        e.payee_entity_id = supplier.id
        e.payee_name = baraa_name
        updated["baraa"] += 1
    try:
        with _begin():
            db.session.flush()
        click.echo(json.dumps(updated, ensure_ascii=False))
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e

@click.command("expenses-payoff-all")
@click.option("--method", type=click.Choice(["cash","cheque","bank","card","online","other"]), default="cash")
@click.option("--dry-run/--commit", default=True)
@with_appcontext
def expenses_payoff_all(method, dry_run):
    created = 0
    skipped = 0
    q = db.session.query(Expense).order_by(Expense.id.asc())
    for e in q.yield_per(200):
        bal = float(e.balance or 0)
        if bal <= 0.01:
            skipped += 1
            continue
        p = Payment(
            payment_date=datetime.now(timezone.utc).replace(tzinfo=None),
            total_amount=_Q2(bal),
            currency=(e.currency or "ILS").upper(),
            method=PaymentMethod(method),
            status=PaymentStatus.COMPLETED.value,
            direction=PaymentDirection.OUT.value,
            entity_type=PaymentEntityType.EXPENSE.value,
            expense_id=e.id,
            reference=f"AUTO-EXP-{e.id}",
        )
        db.session.add(p)
        created += 1
    try:
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        click.echo(json.dumps({"created": created, "skipped": skipped, "committed": (not dry_run)}, ensure_ascii=False))
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e

@click.command("stock-adjustment-create")
@click.option("--warehouse-id", type=int, required=True)
@click.option("--reason", type=click.Choice(["DAMAGED","STORE_USE"]), required=True)
@click.option("--notes", type=str, default=None)
@with_appcontext
def stock_adjustment_create(warehouse_id, reason, notes):
    adj=StockAdjustment(warehouse_id=warehouse_id, reason=reason, notes=notes)
    try:
        with _begin(): db.session.add(adj)
        click.echo(f"OK: adjustment {adj.id} created.")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-adjustment-add-item")
@click.option("--adjustment-id", type=int, required=True)
@click.option("--product-id", type=int, required=True)
@click.option("--quantity", type=int, required=True)
@click.option("--unit-cost", type=str, required=True)
@with_appcontext
def stock_adjustment_add_item(adjustment_id, product_id, quantity, unit_cost):
    adj=db.session.get(StockAdjustment, adjustment_id)
    if not adj: raise click.ClickException("Adjustment not found")
    it=StockAdjustmentItem(adjustment_id=adj.id, product_id=product_id, quantity=int(quantity), unit_cost=_Q2(unit_cost))
    try:
        with _begin():
            db.session.add(it); db.session.flush()
            total=Decimal("0")
            for x in (adj.items or []): total += _D(x.quantity or 0)*_D(x.unit_cost or 0)
            adj.total_cost=_Q2(total)
        click.echo(f"OK: item {it.id} added. total_cost={float(adj.total_cost):.2f}")
    except SQLAlchemyError as e:
        db.session.rollback(); raise click.ClickException(str(e)) from e

@click.command("stock-adjustment-finalize")
@click.option("--adjustment-id", type=int, required=True)
@click.option("--expense-type-id", type=int, required=True)
@with_appcontext
def stock_adjustment_finalize(adjustment_id, expense_type_id):
    adj = db.session.get(StockAdjustment, adjustment_id)
    if not adj:
        raise click.ClickException("Adjustment not found")
    if float(adj.total_cost or 0) <= 0:
        raise click.ClickException("No total_cost to finalize")
    ex = Expense(
        amount=_Q2(adj.total_cost or 0),
        type_id=expense_type_id,
        currency="ILS",
        stock_adjustment_id=adj.id,
        description=f"Stock Adjustment {adj.reason} #{adj.id}",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        payment_method="other",
    )
    try:
        with _begin():
            db.session.add(ex)
        click.echo(f"OK: expense {ex.id} created for adjustment.")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e


@click.command("gl-seed-accounts")
@with_appcontext
def gl_seed_accounts():
    created, updated = [], []
    mapping = [
        ("1100_AR", "Accounts Receivable"),
        ("4000_SALES", "Sales Revenue"),
        ("4100_SERVICE_REVENUE", "Service Revenue"),
        ("1500_INVENTORY", "Inventory"),
        ("5000_COGS", "Cost of Goods Sold"),
        ("2100_VAT_PAYABLE", "VAT Payable"),
        ("1000_CASH", "Cash on Hand"),
        ("1010_BANK", "Bank"),
        ("1020_CARD_CLEARING", "Card Clearing"),
        ("1150_CHQ_REC", "Cheques Receivable"),
        ("2000_AP", "Accounts Payable"),
        ("2150_CHQ_PAY", "Cheques Payable"),
        ("5000_EXPENSES", "Expenses"),
        ("5200_PART_EXP", "Partner Expenses"),
        ("1205_INV_EXCHANGE", "Inventory Exchange"),
        ("5105_COGS_EXCHANGE", "COGS Exchange"),
        ("2300_ADV_PAY", "Advance Payments"),
        ("2150_EMP_ADV", "Employee Advances"),
        ("2150_PAY_CLR", "Payroll Clearing"),
        ("2200_PAR_CLR", "Partner Clearing"),
        ("3100_OWNER_CURRENT", "Owner Current Account"),
    ]
    with _begin():
        for code, name in mapping:
            acc = db.session.query(Account).filter_by(code=code).one_or_none()
            if acc:
                if (acc.is_active is not True) or (acc.name != name):
                    acc.name = name
                    acc.is_active = True
                    updated.append(code)
            else:
                inferred_type = "ASSET"
                if code.startswith("2"):
                    inferred_type = "LIABILITY"
                elif code.startswith("3"):
                    inferred_type = "EQUITY"
                elif code.startswith("4"):
                    inferred_type = "REVENUE"
                elif not code.startswith(("1","2","3","4")):
                    inferred_type = "EXPENSE"
                acc = Account(code=code, name=name, type=inferred_type, is_active=True)
                db.session.add(acc)
                created.append(code)
    click.echo(json.dumps({"created": created, "updated": updated}, ensure_ascii=False))


@click.command("gl-batches")
@click.option("--limit", type=int, default=20)
@with_appcontext
def gl_list_batches(limit):
    rows = db.session.query(GLBatch).order_by(GLBatch.created_at.desc()).limit(limit).all()
    out = [
        {
            "id": r.id,
            "code": r.code,
            "status": getattr(r.status, "value", r.status),
            "source": f"{r.source_type}:{r.source_id}",
            "purpose": r.purpose,
            "currency": r.currency,
            "posted_at": r.posted_at,
        }
        for r in rows
    ]
    click.echo(json.dumps(out, default=str, ensure_ascii=False))


@click.command("gl-entries")
@click.option("--batch-id", type=int, required=True)
@with_appcontext
def gl_list_entries(batch_id):
    rows = (
        db.session.query(GLEntry)
        .filter(GLEntry.batch_id == batch_id)
        .order_by(GLEntry.id.asc())
        .all()
    )
    out = [
        {
            "id": e.id,
            "account": e.account,
            "debit": float(e.debit or 0),
            "credit": float(e.credit or 0),
            "currency": e.currency,
            "ref": e.ref,
        }
        for e in rows
    ]
    click.echo(json.dumps(out, ensure_ascii=False))


@click.command("note-add")
@click.option("--entity-type", type=str, required=True)
@click.option("--entity-id", type=str, required=True)
@click.option("--content", type=str, required=True)
@click.option("--priority", type=click.Choice(["LOW", "MEDIUM", "HIGH", "URGENT"]), default="MEDIUM")
@click.option("--pin/--no-pin", default=False)
@with_appcontext
def note_add(entity_type, entity_id, content, priority, pin):
    n = Note(
        entity_type=entity_type.strip().upper(),
        entity_id=str(entity_id),
        content=content.strip(),
        priority=priority,
        is_pinned=bool(pin),
    )
    try:
        with _begin():
            db.session.add(n)
        click.echo(f"OK: note {n.id} added.")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(str(e)) from e


@click.command("note-list")
@click.option("--entity-type", type=str, required=True)
@click.option("--entity-id", type=str, required=True)
@with_appcontext
def note_list(entity_type, entity_id):
    rows = (
        db.session.query(Note)
        .filter(
            Note.entity_type == entity_type.strip().upper(),
            Note.entity_id == str(entity_id),
        )
        .order_by(Note.is_pinned.desc(), Note.created_at.desc())
        .all()
    )
    out = [r.to_dict() for r in rows]
    click.echo(json.dumps(out, ensure_ascii=False, default=str))


@click.command("audit-tail")
@click.option("--limit", type=int, default=50)
@with_appcontext
def audit_tail(limit):
    rows = db.session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    out = [
        {
            "id": r.id,
            "time": r.created_at.isoformat() if r.created_at else None,
            "model": r.model_name,
            "record_id": r.record_id,
            "action": r.action,
            "user_id": r.user_id,
            "customer_id": r.customer_id,
            "ip": r.ip_address,
        }
        for r in rows
    ]
    click.echo(json.dumps(out, ensure_ascii=False))


@click.command("currency-balance")
@click.option("--entity-type", type=str, required=True, help="نوع الكيان (CUSTOMER, SUPPLIER, PARTNER)")
@click.option("--entity-id", type=int, required=True, help="معرف الكيان")
@with_appcontext
def currency_balance(entity_type, entity_id):
    """حساب رصيد الكيان بالشيكل"""
    try:
        balance = get_entity_balance_in_ils(entity_type.upper(), entity_id)
        click.echo(f"الرصيد بالشيكل: {balance:,.2f} شيكل")
    except Exception as e:
        click.echo(f"خطأ: {e}")

@click.command("currency-validate")
@click.option("--entity-type", type=str, required=True, help="نوع الكيان (CUSTOMER, SUPPLIER, PARTNER)")
@click.option("--entity-id", type=int, required=True, help="معرف الكيان")
@with_appcontext
def currency_validate(entity_type, entity_id):
    """التحقق من اتساق العملات"""
    try:
        result = validate_currency_consistency(entity_type.upper(), entity_id)
        if result["is_consistent"]:
            click.echo("✅ الحسابات متسقة")
        else:
            click.echo("❌ الحسابات غير متسقة")
            click.echo(f"الرصيد الجديد: {result['new_balance']:,.2f}")
            click.echo(f"الرصيد القديم: {result['old_balance']:,.2f}")
            click.echo(f"الفرق: {result['difference']:,.2f}")
    except Exception as e:
        click.echo(f"خطأ: {e}")


@click.command("currency-report")
@click.option("--entity-type", type=str, required=True, help="نوع الكيان (CUSTOMER, SUPPLIER, PARTNER)")
@with_appcontext
def currency_report(entity_type):
    """تقرير الأرصدة بالشيكل"""
    try:
        from reports import customer_balance_report_ils, supplier_balance_report_ils, partner_balance_report_ils

        if entity_type.upper() == "CUSTOMER":
            report = customer_balance_report_ils()
        elif entity_type.upper() == "SUPPLIER":
            report = supplier_balance_report_ils()
        elif entity_type.upper() == "PARTNER":
            report = partner_balance_report_ils()
        else:
            click.echo("نوع الكيان غير مدعوم")
            return

        if "error" in report:
            click.echo(f"خطأ: {report['error']}")
            return

        click.echo(f"إجمالي الأرصدة: {report['formatted_total']}")

        # تحديد نوع الكيان والبيانات المناسبة
        if entity_type.upper() == "CUSTOMER":
            count_key = "total_customers"
            entities_key = "customers"
            name_key = "customer_name"
        elif entity_type.upper() == "SUPPLIER":
            count_key = "total_suppliers"
            entities_key = "suppliers"
            name_key = "supplier_name"
        else:  # PARTNER
            count_key = "total_partners"
            entities_key = "partners"
            name_key = "partner_name"

        click.echo(f"عدد الكيانات: {report[count_key]}")

        # عرض تفاصيل أول 10 كيانات
        entities = report[entities_key]
        for entity in entities[:10]:
            name = entity[name_key]
            balance = entity['formatted_balance']
            click.echo(f"- {name}: {balance}")

        if len(entities) > 10:
            click.echo(f"... و {len(entities) - 10} كيان آخر")

    except Exception as e:
        click.echo(f"خطأ: {e}")

@click.command("currency-health")
@with_appcontext
def currency_health():
    """فحص صحة نظام العملات مع السيرفرات العالمية"""
    try:
        from models import Currency, ExchangeRate, convert_amount, get_fx_rate_with_fallback

        click.echo("=== فحص صحة نظام العملات ===")
        click.echo()

        # فحص العملات النشطة
        active_currencies = Currency.query.filter_by(is_active=True).count()
        click.echo(f"✅ العملات النشطة: {active_currencies}")

        # فحص أسعار الصرف
        total_rates = ExchangeRate.query.filter_by(is_active=True).count()
        click.echo(f"✅ أسعار الصرف: {total_rates}")

        # فحص سعر صرف تجريبي مع معلومات المصدر
        try:
            rate_info = get_fx_rate_with_fallback("USD", "ILS")
            if rate_info["success"]:
                source_text = "محلي" if rate_info["source"] == "local" else "عالمي"
                click.echo(f"✅ سعر USD/ILS: {rate_info['rate']} (مصدر: {source_text})")
            else:
                click.echo(f"❌ خطأ في سعر USD/ILS: {rate_info.get('error', 'غير معروف')}")
        except Exception as e:
            click.echo(f"❌ خطأ في سعر USD/ILS: {e}")

        # فحص تحويل تجريبي
        try:
            converted = convert_amount(100, "USD", "ILS")
            click.echo(f"✅ تحويل 100 USD إلى ILS: {converted}")
        except Exception as e:
            click.echo(f"❌ خطأ في التحويل: {e}")

        click.echo()
        click.echo("🎉 فحص النظام مكتمل!")

    except Exception as e:
        click.echo(f"خطأ: {e}")


@click.command("currency-update")
@with_appcontext
def currency_update():
    """تحديث أسعار الصرف من السيرفرات العالمية"""
    try:
        from models import auto_update_missing_rates

        click.echo("=== تحديث أسعار الصرف ===")
        click.echo()

        result = auto_update_missing_rates()

        if result["success"]:
            click.echo(f"✅ {result['message']}")
            click.echo(f"📊 تم تحديث {result['updated_rates']} سعر صرف")
        else:
            click.echo(f"❌ {result['message']}")
            if "error" in result:
                click.echo(f"🔍 تفاصيل الخطأ: {result['error']}")

    except Exception as e:
        click.echo(f"خطأ: {e}")


@click.command("currency-test")
@click.option("--base", type=str, default="USD", help="العملة الأساسية")
@click.option("--quote", type=str, default="ILS", help="العملة المقابلة")
@with_appcontext
def currency_test(base, quote):
    """اختبار سعر الصرف مع معلومات المصدر"""
    try:
        from models import get_fx_rate_with_fallback, convert_amount

        click.echo(f"=== اختبار سعر الصرف {base}/{quote} ===")
        click.echo()

        # اختبار الحصول على السعر
        rate_info = get_fx_rate_with_fallback(base, quote)

        if rate_info["success"]:
            source_text = "محلي (مدخل من الادمن)" if rate_info["source"] == "local" else "عالمي (من السيرفرات)"
            click.echo(f"✅ السعر: {rate_info['rate']}")
            click.echo(f"📡 المصدر: {source_text}")
            click.echo(f"⏰ الوقت: {rate_info['timestamp']}")

            # اختبار التحويل
            try:
                converted = convert_amount(100, base, quote)
                click.echo(f"💰 تحويل 100 {base} = {converted} {quote}")
            except Exception as e:
                click.echo(f"❌ خطأ في التحويل: {e}")
        else:
            click.echo(f"❌ فشل في الحصول على السعر: {rate_info.get('error', 'غير معروف')}")

    except Exception as e:
        click.echo(f"خطأ: {e}")


@click.command('create-system-admin-interactive', help="إنشاء مستخدم مدير نظام")
@with_appcontext
def create_system_admin_interactive():
    """إنشاء مستخدم مدير نظام بصلاحيات كاملة"""
    from werkzeug.security import generate_password_hash

    email = click.prompt("البريد الإلكتروني", type=str)
    username = click.prompt("اسم المستخدم", type=str)
    password = click.prompt("كلمة المرور", type=str, hide_input=True)
    password_confirm = click.prompt("تأكيد كلمة المرور", type=str, hide_input=True)

    if password != password_confirm:
        click.echo(click.style("كلمة المرور غير متطابقة", fg="red"))
        return

    # التحقق من وجود المستخدم
    if User.query.filter_by(email=email).first():
        click.echo(click.style(f"المستخدم {email} موجود بالفعل", fg="yellow"))
        return

    # البحث عن دور مدير النظام أو إنشاؤه
    super_role = Role.query.filter_by(slug="super_admin").first()
    if not super_role:
        super_role = Role(
            name="System Admin",
            slug="super_admin",
            description="صلاحيات كاملة للنظام"
        )
        db.session.add(super_role)
        db.session.flush()

    # إنشاء المستخدم
    user = User(
        email=email,
        username=username,
        password_hash=generate_password_hash(password),
        role_id=super_role.id,
        is_active=True,
        email_confirmed=True
    )

    try:
        db.session.add(user)
        db.session.commit()
        click.echo(click.style(f"✅ تم إنشاء مستخدم مدير نظام: {email}", fg="green"))
    except Exception as e:
        db.session.rollback()
        click.echo(click.style(f"❌ خطأ: {str(e)}", fg="red"))


@click.command('optimize-db', help="تحسين أداء قاعدة البيانات")
@click.option("--dry-run", is_flag=True, help="عرض أوامر إنشاء الفهارس بدون تنفيذ")
@with_appcontext
def optimize_db(dry_run: bool):
    """تحسين أداء قاعدة البيانات بإنشاء الفهارس وتحليل الجداول"""
    try:
        from sqlalchemy import text

        # قائمة الفهارس الموصى بها
        recommended_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id)",
            "CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku)",
            "CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)",
            "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)",
            "CREATE INDEX IF NOT EXISTS idx_products_active_name ON products(is_active, name)",
            "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date)",
            "CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id)",
            "CREATE INDEX IF NOT EXISTS idx_sales_status_date ON sales(status, sale_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_entity_type ON payments(entity_type)",
            "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
            "CREATE INDEX IF NOT EXISTS idx_payments_direction ON payments(direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_currency ON payments(currency)",
            "CREATE INDEX IF NOT EXISTS idx_payments_status_date ON payments(status, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_dir_status_date ON payments(direction, status, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_dir_status_entity_type ON payments(direction, status, entity_type)",
            "CREATE INDEX IF NOT EXISTS idx_payments_method_date ON payments(method, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_created_by ON payments(created_by)",
            "CREATE INDEX IF NOT EXISTS idx_payments_total_amount ON payments(total_amount)",
            "CREATE INDEX IF NOT EXISTS idx_payments_customer_date ON payments(customer_id, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_supplier_date ON payments(supplier_id, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_partner_date ON payments(partner_id, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_customer_status_dir ON payments(customer_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_supplier_status_dir ON payments(supplier_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_partner_status_dir ON payments(partner_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_sale_status_dir ON payments(sale_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_invoice_status_dir ON payments(invoice_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_service_status_dir ON payments(service_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_shipment_status_dir ON payments(shipment_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_expense_status_dir ON payments(expense_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_preorder_status_dir ON payments(preorder_id, status, direction)",
            "CREATE INDEX IF NOT EXISTS idx_payments_refund_of ON payments(refund_of_id)",
            "CREATE INDEX IF NOT EXISTS idx_payments_customer_dir_status_date ON payments(customer_id, direction, status, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_supplier_dir_status_date ON payments(supplier_id, direction, status, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_partner_dir_status_date ON payments(partner_id, direction, status, payment_date)",
            "CREATE INDEX IF NOT EXISTS idx_service_customer ON service_requests(customer_id)",
            "CREATE INDEX IF NOT EXISTS idx_service_status ON service_requests(status)",
            "CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)",
            "CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email)",
            "CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name)",
            "CREATE INDEX IF NOT EXISTS idx_customers_archived ON customers(is_archived)",
            "CREATE INDEX IF NOT EXISTS idx_customers_balance ON customers(current_balance)",
            "CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name)",
            "CREATE INDEX IF NOT EXISTS idx_partners_name ON partners(name)",
            "CREATE INDEX IF NOT EXISTS idx_partners_archived ON partners(is_archived)",
            "CREATE INDEX IF NOT EXISTS idx_partners_balance ON partners(current_balance)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_expected_arrival ON shipments(expected_arrival)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_destination_id ON shipments(destination_id)",
            "CREATE INDEX IF NOT EXISTS idx_shipments_archived ON shipments(is_archived)",
            "CREATE INDEX IF NOT EXISTS idx_transfers_transfer_date ON transfers(transfer_date)",
            "CREATE INDEX IF NOT EXISTS idx_transfers_product_date ON transfers(product_id, transfer_date)",
            "CREATE INDEX IF NOT EXISTS idx_transfers_source_date ON transfers(source_id, transfer_date)",
            "CREATE INDEX IF NOT EXISTS idx_transfers_destination_date ON transfers(destination_id, transfer_date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_type_date ON expenses(type_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_partner_date ON expenses(partner_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_supplier_date ON expenses(supplier_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_shipment_date ON expenses(shipment_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_customer_date ON expenses(customer_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_payee_entity_date ON expenses(payee_type, payee_entity_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_branch_date ON expenses(branch_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_site_date ON expenses(site_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_employee_date ON expenses(employee_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_utility_date ON expenses(utility_account_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_stock_adjustment_date ON expenses(stock_adjustment_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_payee_type_date ON expenses(payee_type, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_archived_date ON expenses(is_archived, date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_period_start ON expenses(period_start)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_period_end ON expenses(period_end)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_amount ON expenses(amount)",
            "CREATE INDEX IF NOT EXISTS idx_stocklevels_product_wh ON stock_levels(product_id, warehouse_id)",
            "CREATE INDEX IF NOT EXISTS idx_online_preorders_customer_created ON online_preorders(customer_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_online_preorders_status_created ON online_preorders(status, created_at)",
        ]

        created = 0
        for idx_sql in recommended_indexes:
            try:
                if dry_run:
                    click.echo(idx_sql)
                else:
                    db.session.execute(text(idx_sql))
                    created += 1
            except Exception:
                pass

        if not dry_run:
            db.session.commit()

        # تحليل قاعدة البيانات
        try:
            if not dry_run:
                db.session.execute(text("ANALYZE"))
                db.session.commit()
        except Exception:
            pass

        if dry_run:
            click.echo(click.style("OK: dry-run (لم يتم تنفيذ أي تغيير).", fg="yellow"))
        else:
            click.echo(click.style(f"✅ اكتمل تحسين قاعدة البيانات: تم إنشاء {created} فهرس", fg="green"))
    except Exception as e:
        click.echo(click.style(f"❌ خطأ: {str(e)}", fg="red"))


@click.command("recompute-sale-returns", help="إعادة احتساب مبالغ المرتجعات المرتبطة ببيع")
@click.option("--limit", type=int, default=0)
@click.option("--return-id", type=int, default=0)
@click.option("--dry-run", is_flag=True)
@with_appcontext
def recompute_sale_returns(limit: int, return_id: int, dry_run: bool):
    from decimal import Decimal
    from sqlalchemy.orm import selectinload
    from models import Sale, SaleReturn

    def _d(v):
        return Decimal(str(v or 0))

    q = (
        SaleReturn.query.filter(SaleReturn.sale_id.isnot(None), SaleReturn.status == "CONFIRMED")
        .options(
            selectinload(SaleReturn.lines),
            selectinload(SaleReturn.sale).selectinload(Sale.lines),
        )
        .order_by(SaleReturn.id.desc())
    )
    if return_id and int(return_id) > 0:
        q = q.filter(SaleReturn.id == int(return_id))
    if limit and int(limit) > 0:
        q = q.limit(int(limit))
    rows = q.all()

    changed = 0
    affected_customers = set()
    for sr in rows:
        sale = sr.sale
        if not sale:
            continue
        if sr.customer_id:
            try:
                affected_customers.add(int(sr.customer_id))
            except Exception:
                pass
        sale_subtotal = Decimal("0")
        sale_map = {}
        for ln in (sale.lines or []):
            try:
                sale_map[(int(ln.product_id), int(ln.warehouse_id))] = ln
            except Exception:
                continue
            base = _d(getattr(ln, "unit_price", 0))
            qty = _d(getattr(ln, "quantity", 0))
            dr = _d(getattr(ln, "discount_rate", 0))
            sale_subtotal += (base * qty) * (Decimal("1") - (dr / Decimal("100")))

        items_total = Decimal("0")
        for rl in (sr.lines or []):
            sl = None
            try:
                sl = sale_map.get((int(rl.product_id), int(rl.warehouse_id)))
            except Exception:
                sl = None
            if sl is not None:
                base = _d(getattr(sl, "unit_price", 0))
                dr = _d(getattr(sl, "discount_rate", 0))
                eff = base * (Decimal("1") - (dr / Decimal("100")))
                rl.unit_price = eff
                unit = eff
            else:
                unit = _d(getattr(rl, "unit_price", 0))
            items_total += unit * _d(getattr(rl, "quantity", 0))

        if sale_subtotal > Decimal("0"):
            ratio = items_total / sale_subtotal
        else:
            ratio = Decimal("1") if items_total > Decimal("0") else Decimal("0")
        if ratio < Decimal("0"):
            ratio = Decimal("0")
        if ratio > Decimal("1"):
            ratio = Decimal("1")

        disc_share = _d(getattr(sale, "discount_total", 0)) * ratio
        ship_share = _d(getattr(sale, "shipping_cost", 0)) * ratio
        base = items_total - disc_share
        if base < Decimal("0"):
            base = Decimal("0")
        base = base + ship_share
        tr = _d(getattr(sale, "tax_rate", 0))
        tax_amount = (base * tr / Decimal("100")) if tr > 0 else Decimal("0")
        total_amount = base + tax_amount

        old_total = _d(getattr(sr, "total_amount", 0))
        if old_total != total_amount or _d(getattr(sr, "tax_amount", 0)) != tax_amount:
            changed += 1
            click.echo(
                f"SaleReturn#{sr.id} sale#{sr.sale_id}: total {old_total:.2f} -> {total_amount:.2f} (tax {tax_amount:.2f})"
            )
        sr.total_amount = total_amount
        sr.tax_rate = tr
        sr.tax_amount = tax_amount

    if dry_run:
        click.echo(click.style(f"OK: dry-run. would change {changed}.", fg="yellow"))
        db.session.rollback()
        return
    db.session.commit()
    if affected_customers:
        for cid in sorted(affected_customers):
            try:
                from utils.customer_balance_updater import update_customer_balance_components
                update_customer_balance_components(cid, db.session)
            except Exception:
                pass
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    click.echo(click.style(f"✅ تم تحديث {changed} مرتجع.", fg="green"))


@click.command("perf-snapshot", help="إنشاء Snapshot من ملف perf JSONL إن وجد")
@click.option("--path", "path", default=None)
@click.option("--window", "window", type=int, default=2000)
@click.option("--by", "by", type=click.Choice(["endpoint", "path"], case_sensitive=False), default="endpoint")
@click.option("--out", "out_path", default="")
@with_appcontext
def perf_snapshot(path: str | None, window: int, by: str, out_path: str):
    import json
    import os
    from flask import current_app

    by = (by or "endpoint").lower()
    window = min(20000, max(100, int(window or 2000)))
    default_path = current_app.config.get("PERF_MONITOR_PERSIST_PATH") or os.path.join(current_app.instance_path, "perf_log.jsonl")
    p = (path or default_path or "").strip()
    if not p or not os.path.exists(p):
        raise click.ClickException(f"perf log not found: {p}")

    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except Exception:
                continue
    rows = rows[-window:]

    def _f(x):
        try:
            return float(x or 0)
        except Exception:
            return 0.0

    def _pct(vals, p):
        if not vals:
            return 0.0
        vs = sorted(vals)
        k = (len(vs) - 1) * (p / 100.0)
        f0 = int(k)
        c0 = min(f0 + 1, len(vs) - 1)
        if f0 == c0:
            return float(vs[f0])
        return float(vs[f0] * (c0 - k) + vs[c0] * (k - f0))

    key_field = "endpoint" if by == "endpoint" else "path"
    groups = {}
    for r in rows:
        k = str((r.get(key_field) or "")).strip() or "(unknown)"
        groups.setdefault(k, []).append(r)

    aggs = []
    for k, items in groups.items():
        totals = [_f(x.get("total_ms")) for x in items]
        sqls = [_f(x.get("sql_ms")) for x in items]
        tpls = [_f(x.get("template_ms")) for x in items]
        qcnt = [_f(x.get("sql_count")) for x in items]
        n = len(items)
        aggs.append(
            {
                "key": k,
                "count": n,
                "avg_total_ms": round(sum(totals) / n, 2) if n else 0.0,
                "p95_total_ms": round(_pct(totals, 95), 2),
                "avg_sql_ms": round(sum(sqls) / n, 2) if n else 0.0,
                "p95_sql_ms": round(_pct(sqls, 95), 2),
                "avg_sql_count": round(sum(qcnt) / n, 2) if n else 0.0,
                "p95_sql_count": round(_pct(qcnt, 95), 2),
                "avg_template_ms": round(sum(tpls) / n, 2) if n else 0.0,
                "p95_template_ms": round(_pct(tpls, 95), 2),
            }
        )
    aggs.sort(key=lambda r: float(r.get("p95_total_ms") or 0), reverse=True)

    top = aggs[:25]
    for r in top:
        click.echo(
            f"{r['p95_total_ms']:>8.2f}ms  avg={r['avg_total_ms']:>7.2f}ms  "
            f"sql={r['avg_sql_ms']:>7.2f}ms  q={r['avg_sql_count']:>6.1f}  "
            f"tpl={r['avg_template_ms']:>7.2f}ms  n={r['count']:>4d}  {r['key']}"
        )

    if out_path:
        out_path = out_path.strip()
        os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"by": by, "window": window, "top": top}, ensure_ascii=False, indent=2))
        click.echo(click.style(f"OK: snapshot written: {out_path}", fg="green"))

@click.command("link-missing-counterparties")
@with_appcontext
def link_missing_counterparties():
    connection = db.session.connection()
    suppliers = Supplier.query.filter(Supplier.customer_id.is_(None)).all()
    partners = Partner.query.filter(Partner.customer_id.is_(None)).all()
    sup_total = len(suppliers)
    part_total = len(partners)
    sup_linked = 0
    part_linked = 0
    failures = []
    for supplier in suppliers:
        try:
            cid = _ensure_customer_for_counterparty(
                connection,
                name=supplier.name,
                phone=supplier.phone,
                whatsapp=supplier.phone,
                email=supplier.email,
                address=supplier.address,
                currency=supplier.currency,
                source_label="SUPPLIER",
                source_id=supplier.id,
            )
            if cid:
                supplier.customer_id = cid
                sup_linked += 1
            else:
                failures.append(f"Supplier#{supplier.id}")
        except Exception as exc:
            failures.append(f"Supplier#{supplier.id}: {exc}")
    for partner in partners:
        try:
            cid = _ensure_customer_for_counterparty(
                connection,
                name=partner.name,
                phone=partner.phone_number,
                whatsapp=partner.phone_number,
                email=partner.email,
                address=partner.address,
                currency=partner.currency,
                source_label="PARTNER",
                source_id=partner.id,
            )
            if cid:
                partner.customer_id = cid
                part_linked += 1
            else:
                failures.append(f"Partner#{partner.id}")
        except Exception as exc:
            failures.append(f"Partner#{partner.id}: {exc}")
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    click.echo(click.style(f"الموردون المستهدفون: {sup_total} | تم الربط: {sup_linked}", fg="green"))
    click.echo(click.style(f"الشركاء المستهدفون: {part_total} | تم الربط: {part_linked}", fg="green"))
    if failures:
        click.echo(click.style("سجلات لم تنجح:", fg="yellow"))
        for item in failures:
            click.echo(f"- {item}")

@click.command("workflow-check-timeouts")
@with_appcontext
def workflow_check_timeouts():
    """فحص حالات الـ Workflows المتأخرة وتنفيذ التصعيد وفق القواعد المعرفة."""
    try:
        from services.workflow_engine import WorkflowEngine
        WorkflowEngine.check_timeouts()
        click.echo("✅ تم فحص الـ Workflows المتأخرة وتنفيذ التصعيد (إن وجد)")
    except Exception as e:
        click.echo(click.style(f"❌ خطأ أثناء فحص الـ Workflows: {str(e)}", fg="red"))

@click.command("gl-recreate-payments")
@click.option("--dry-run", is_flag=True, help="عرض ما سيتم عمله دون تنفيذ")
@click.option("--payment-id", type=int, help="إعادة إنشاء قيد لدفعة محددة فقط")
@click.option("--from-date", help="تاريخ البداية (YYYY-MM-DD)")
@click.option("--to-date", help="تاريخ النهاية (YYYY-MM-DD)")
@click.option("--force", is_flag=True, help="إعادة إنشاء القيود حتى لو كانت موجودة")
@click.option("--list-only", is_flag=True, help="عرض قائمة الدفعات فقط")
@click.option("--show-details", is_flag=True, help="عرض تفاصيل القيود الموجودة")
@with_appcontext
def gl_recreate_payments(dry_run, payment_id, from_date, to_date, force, list_only, show_details):
    """إعادة إنشاء قيود دفتر الأستاذ للدفعات المفقودة"""
    from models import (
        GLBatch,
        GL_ACCOUNTS,
        Payment,
        PaymentDirection,
        PaymentEntityType,
        PaymentMethod,
        PaymentStatus,
        fx_rate,
        _payment_entity_id_for,
        _payment_expense_ledger,
    )
    from datetime import datetime
    
    try:
        query = Payment.query.filter(
            Payment.status.in_(
                [PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value]
            )
        )
        
        if payment_id:
            query = query.filter(Payment.id == payment_id)
        
        if from_date:
            try:
                fd = datetime.strptime(from_date, '%Y-%m-%d')
                query = query.filter(Payment.payment_date >= fd)
            except ValueError:
                click.echo(f"❌ تاريخ غير صحيح: {from_date}")
                return
        
        if to_date:
            try:
                td = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                query = query.filter(Payment.payment_date <= td)
            except ValueError:
                click.echo(f"❌ تاريخ غير صحيح: {to_date}")
                return
        
        payments = query.all()
        click.echo(f"📋 تم العثور على {len(payments)} دفعة")
        
        created = 0
        skipped = 0
        errors = 0
        
        for payment in payments:
            try:
                existing = GLBatch.query.filter(
                    GLBatch.source_type == 'PAYMENT',
                    GLBatch.source_id == payment.id,
                    GLBatch.purpose == 'PAYMENT'
                ).first()
                
                if existing and not force:
                    if list_only or show_details:
                        entries = GLEntry.query.filter(GLEntry.batch_id == existing.id).all()
                        if show_details:
                            click.echo(f"\n✅ الدفعة #{payment.id} - القيد: {existing.code}")
                            click.echo(f"   التاريخ: {existing.posted_at}")
                            click.echo(f"   المذكرة: {existing.memo}")
                            click.echo("   الحسابات:")
                            for entry in entries:
                                click.echo(f"     - {entry.account}: مدين {entry.debit:.2f} | دائن {entry.credit:.2f}")
                        elif list_only:
                            click.echo(f"✅ الدفعة #{payment.id} - القيد موجود: {existing.code}")
                    elif not dry_run:
                        click.echo(f"⏭️  تخطي الدفعة #{payment.id} - القيد موجود بالفعل")
                    skipped += 1
                    continue
                
                if list_only:
                    if existing:
                        click.echo(f"✅ الدفعة #{payment.id} - {payment.payment_date} - {payment.total_amount} {payment.currency} - القيد موجود: {existing.code}")
                    else:
                        click.echo(f"❌ الدفعة #{payment.id} - {payment.payment_date} - {payment.total_amount} {payment.currency} - بدون قيد")
                    continue
                
                if "[SETTLED=true]" in (payment.notes or ""):
                    if not dry_run:
                        click.echo(f"⏭️  تخطي الدفعة #{payment.id} - مستوطنة")
                    skipped += 1
                    continue
                
                if "[FROM_MANUAL_CHECK=true]" in (payment.notes or ""):
                    if not dry_run:
                        click.echo(f"⏭️  تخطي الدفعة #{payment.id} - من شيك يدوي")
                    skipped += 1
                    continue

                amount = float(payment.total_amount or 0)
                if amount <= 0:
                    if not dry_run:
                        click.echo(f"⏭️  تخطي الدفعة #{payment.id} - مبلغ صفر")
                    skipped += 1
                    continue
                
                amount_ils = amount
                if payment.currency and payment.currency != "ILS":
                    try:
                        rate = fx_rate(
                            payment.currency,
                            "ILS",
                            payment.payment_date or datetime.now(timezone.utc).replace(tzinfo=None),
                            raise_on_missing=False,
                        )
                        if rate and rate > 0:
                            amount_ils = float(amount * float(rate))
                    except Exception:
                        pass
                
                is_pending_check = (
                    payment.status == PaymentStatus.PENDING.value
                    and payment.method == PaymentMethod.CHEQUE.value
                )
                
                if is_pending_check:
                    if payment.direction == PaymentDirection.IN.value:
                        cash_account = "1150_CHQ_REC"
                    else:
                        cash_account = "2150_CHQ_PAY"
                else:
                    method_val = getattr(payment, "method", "CASH")
                    if hasattr(method_val, "value"):
                        method_val = method_val.value
                    payment_method = str(method_val or "CASH").upper()
                    
                    if payment_method == PaymentMethod.BANK.value:
                        cash_account = GL_ACCOUNTS.get("BANK", "1010_BANK")
                    elif payment_method == PaymentMethod.CARD.value:
                        cash_account = GL_ACCOUNTS.get("CARD", "1020_CARD_CLEARING")
                    else:
                        cash_account = GL_ACCOUNTS.get("CASH", "1000_CASH")
                expense_ledger_ctx = _payment_expense_ledger(db.session, payment) if payment.expense_id else None
                
                entity_account = GL_ACCOUNTS.get("AR", "1100_AR")
                entity_name = "عميل"
                
                if payment.entity_type == PaymentEntityType.SUPPLIER.value or payment.supplier_id:
                    entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                    entity_name = "مورد"
                elif payment.entity_type == PaymentEntityType.PARTNER.value or payment.partner_id:
                    entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                    entity_name = "شريك"
                elif payment.entity_type == PaymentEntityType.EXPENSE.value or payment.expense_id:
                    entity_account = GL_ACCOUNTS.get("AP", "2000_AP")
                    entity_name = "مصروف"
                
                if expense_ledger_ctx:
                    if expense_ledger_ctx.get("counterparty_account"):
                        entity_account = expense_ledger_ctx["counterparty_account"]
                    elif expense_ledger_ctx.get("behavior") == "IMMEDIATE" and expense_ledger_ctx.get("cash_account"):
                        entity_account = expense_ledger_ctx["cash_account"]
                    if not is_pending_check and expense_ledger_ctx.get("cash_account"):
                        cash_account = expense_ledger_ctx["cash_account"]
                
                if payment.direction == PaymentDirection.IN.value:
                    entries = [
                        (cash_account, amount_ils, 0),
                        (entity_account, 0, amount_ils),
                    ]
                    if is_pending_check:
                        memo = f"شيك معلق من {entity_name} - {payment.check_number or payment.payment_number or payment.id}"
                    else:
                        memo = f"قبض من {entity_name} - {payment.payment_number or payment.id}"
                else:
                    entries = [
                        (entity_account, amount_ils, 0),
                        (cash_account, 0, amount_ils),
                    ]
                    if is_pending_check:
                        memo = f"شيك صادر لـ {entity_name} - {payment.check_number or payment.payment_number or payment.id}"
                    else:
                        memo = f"سداد لـ {entity_name} - {payment.payment_number or payment.id}"
                
                if dry_run:
                    click.echo(f"🔍 سينشئ قيد للدفعة #{payment.id}: {memo} - {amount_ils:.2f} ILS")
                else:
                    _gl_upsert_batch_and_entries(
                        db.session,
                        source_type="PAYMENT",
                        source_id=payment.id,
                        purpose="PAYMENT",
                        currency="ILS",
                        memo=memo,
                        entries=entries,
                        ref=payment.payment_number or f"PMT-{payment.id}",
                        entity_type=payment.entity_type,
                        entity_id=_payment_entity_id_for(payment),
                    )
                    db.session.commit()
                    click.echo(f"✅ تم إنشاء قيد للدفعة #{payment.id}: {memo}")
                    created += 1
                    
            except Exception as e:
                errors += 1
                click.echo(f"❌ خطأ في الدفعة #{payment.id}: {str(e)}")
                if not dry_run:
                    db.session.rollback()
        
        click.echo("\n📊 النتيجة:")
        click.echo(f"  ✅ تم إنشاء: {created}")
        click.echo(f"  ⏭️  تم التخطي: {skipped}")
        click.echo(f"  ❌ أخطاء: {errors}")
        
    except Exception as e:
        click.echo(f"❌ خطأ عام: {str(e)}")
        if not dry_run:
            db.session.rollback()


@click.command("sync-balances")
@click.option(
    "--entity",
    type=click.Choice(["customers", "suppliers", "partners", "all"], case_sensitive=False),
    default="all",
    help="حدد نوع الكيانات التي ترغب في مزامنة أرصدتها أو ALL للجميع.",
)
@click.option("--limit", type=int, default=None, help="حد أقصى لعدد السجلات لكل نوع.")
@click.option("--dry-run", is_flag=True, help="عرض الفروقات فقط دون تعديل البيانات.")
@click.option("--include-archived", is_flag=True, help="تضمين السجلات المؤرشفة.")
@click.option("--batch-size", type=int, default=200, show_default=True, help="عدد التصحيحات قبل تنفيذ COMMIT.")
@with_appcontext
def sync_balances(entity, limit, dry_run, include_archived, batch_size):
    """مزامنة جميع الأرصدة مع منطق الحقوق والالتزامات."""
    entity = (entity or "all").lower()
    tolerance = Decimal("0.01")
    summary_rows = []

    groups = [
        ("customers", Customer, build_customer_balance_view, update_customer_balance_components),
        ("suppliers", Supplier, build_supplier_balance_view, update_supplier_balance_components),
        ("partners", Partner, build_partner_balance_view, update_partner_balance_components),
    ]

    def _should_process(label: str) -> bool:
        return entity in ("all", label.lower())

    for label, model_cls, breakdown_fn, updater_fn in groups:
        if not _should_process(label):
            continue

        query = model_cls.query
        if hasattr(model_cls, "is_archived") and not include_archived:
            query = query.filter(model_cls.is_archived == False)  # noqa: E712
        query = query.order_by(model_cls.id.asc())
        if limit:
            query = query.limit(limit)

        total = mismatches = fixed = errors = 0
        pending_commits = 0

        click.echo(f"\n🔄 مراجعة {label} ...")
        for obj in query:
            total += 1
            try:
                breakdown = breakdown_fn(obj.id, db.session)
            except Exception as exc:
                errors += 1
                db.session.rollback()
                click.echo(f"  ⚠️ {label[:-1]} #{obj.id}: تعذر حساب الرصيد ({exc})")
                continue

            if not breakdown or not breakdown.get("success"):
                errors += 1
                click.echo(f"  ⚠️ {label[:-1]} #{obj.id}: نتيجة غير صالحة من الحاسبة")
                continue

            expected = Decimal(str(breakdown.get("balance", {}).get("amount", 0)))
            stored = Decimal(str(getattr(obj, "current_balance", 0) or 0))
            diff = (expected - stored).copy_abs()

            if diff <= tolerance:
                continue

            mismatches += 1
            click.echo(
                f"  • {label[:-1].capitalize()} #{obj.id}: متوقع {expected:.2f} مقابل المخزن {stored:.2f} (فرق {diff:.2f})"
            )

            if dry_run:
                continue

            try:
                updater_fn(obj.id, db.session)
                pending_commits += 1
                fixed += 1
                if pending_commits >= batch_size:
                    db.session.commit()
                    pending_commits = 0
            except Exception as exc:
                db.session.rollback()
                errors += 1
                click.echo(f"    ❌ تعذر تصحيح السجل #{obj.id}: {exc}")

        if not dry_run and pending_commits:
            db.session.commit()

        summary_rows.append(
            {
                "label": label,
                "total": total,
                "mismatches": mismatches,
                "fixed": fixed,
                "errors": errors,
            }
        )

    click.echo("\n📊 الملخص:")
    if not summary_rows:
        click.echo("لا توجد كيانات مطابقة للمعايير المحددة.")
        return
    for row in summary_rows:
        click.echo(
            f"- {row['label'].capitalize():<10}: إجمالي={row['total']}, فروقات={row['mismatches']}, "
            f"تم تصحيحها={row['fixed']}, أخطاء={row['errors']}"
        )
    if dry_run:
        click.echo("\nوضع Dry-Run مفعّل: لم يتم تعديل أي بيانات.")
    else:
        click.echo("\n✅ تمت مزامنة الأرصدة بنجاح.")


@click.command("backfill-sale-invoices")
@click.option("--limit", type=int, default=0, show_default=True, help="0 = كل المبيعات المؤكدة")
@click.option("--dry-run", is_flag=True)
@with_appcontext
def backfill_sale_invoices(limit, dry_run):
    """إنشاء/تحديث سجلات Invoice للمبيعات المؤكدة التي لا تملك فاتورة."""
    from models import Sale, SaleStatus
    from utils.sale_billing import ensure_invoice_for_sale, refresh_customer_balance_for_sale

    q = (
        Sale.query.filter(
            Sale.customer_id.isnot(None),
            Sale.status == SaleStatus.CONFIRMED.value,
            Sale.is_archived.is_(False),
        )
        .order_by(Sale.id.asc())
    )
    if limit and limit > 0:
        q = q.limit(int(limit))
    sales = q.all()
    created = updated = 0
    for sale in sales:
        from models import Invoice

        had = Invoice.query.filter_by(sale_id=sale.id).first() is not None
        if dry_run:
            if not had:
                created += 1
            else:
                updated += 1
            continue
        inv = ensure_invoice_for_sale(sale)
        if inv:
            if had:
                updated += 1
            else:
                created += 1
    if not dry_run:
        from extensions import db

        db.session.commit()
        touched_customers = {int(s.customer_id) for s in sales if s.customer_id}
        for cid in touched_customers:
            try:
                from utils.customer_balance_updater import update_customer_balance_components

                update_customer_balance_components(cid, db.session)
            except Exception:
                pass
        db.session.commit()
    click.echo(
        f"مبيعات: {len(sales)} | جديد: {created} | محدّث: {updated}"
        + (" (dry-run)" if dry_run else "")
    )


@click.command("fiscal-periods-sync")
@click.option("--from-year", type=int, default=None)
@click.option("--to-year", type=int, default=None)
@click.option("--no-monthly", is_flag=True)
@click.option("--no-quarterly", is_flag=True)
@click.option("--no-half", is_flag=True)
@click.option("--no-year", is_flag=True)
@click.option(
    "--all-tenants",
    is_flag=True,
    help="مزامنة فترات كل تينانت في schema الخاص (وليس public فقط)",
)
@with_appcontext
def fiscal_periods_sync(from_year, to_year, no_monthly, no_quarterly, no_half, no_year, all_tenants):
    """توليد الفترات المحاسبية (شهر / ربع / نصف / سنة)."""
    kwargs = dict(
        from_year=from_year,
        to_year=to_year,
        include_monthly=not no_monthly,
        include_quarterly=not no_quarterly,
        include_half=not no_half,
        include_year=not no_year,
    )
    if all_tenants:
        from utils.tenant_fiscal_schema import sync_fiscal_periods_all_tenants

        for stats in sync_fiscal_periods_all_tenants(**kwargs):
            click.echo(
                f"  {stats.get('slug')}/{stats.get('schema')}: "
                f"created={stats.get('created')} updated={stats.get('updated')}"
            )
        return

    from utils.period_close_service import sync_fiscal_periods

    stats = sync_fiscal_periods(**kwargs)
    click.echo(f"OK: created={stats['created']} updated={stats['updated']}")


@click.command("tenants-ensure-fiscal-tables")
@with_appcontext
def tenants_ensure_fiscal_tables():
    """إنشاء جداول إقفال الفترات في مخططات التينانت إن لم تكن موجودة."""
    from utils.tenant_fiscal_schema import ensure_all_tenant_fiscal_tables, iter_tenant_schemas, set_local_search_path

    for row in ensure_all_tenant_fiscal_tables(db.session):
        click.echo(
            f"  {row.get('slug')}/{row.get('schema')}: "
            f"created={row.get('created', [])} skipped={row.get('skipped', row.get('note', ''))}"
        )


@click.command("tenants-ensure-org-structure")
@click.option("--slug", default=None, help="تينانت واحد فقط (افتراضي: الكل)")
@with_appcontext
def tenants_ensure_org_structure(slug: str | None):
    """فرع MAIN + مواقع + مستودعات بكل الأنواع + ربط مالك التينانت."""
    from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path
    from utils.tenant_org_structure import audit_tenant_org_structure, ensure_tenant_org_structure
    from models import TenantRegistry, User

    targets = []
    if slug:
        row = TenantRegistry.query.filter_by(slug=slug.strip().lower()).first()
        if not row:
            raise click.ClickException(f"تينانت غير موجود: {slug}")
        targets.append((row.slug, row.schema_name))
    else:
        for s, sch in iter_tenant_schemas(db.session):
            targets.append((s, sch))

    for tslug, schema in targets:
        if schema.lower() == "public":
            click.echo(f"  {tslug}/public: skipped")
            continue
        db.session.rollback()
        set_local_search_path(db.session, schema)
        reg = TenantRegistry.query.filter_by(slug=tslug).first()
        owner = User.query.filter_by(username="owner").first()
        display = (reg.display_name if reg else None) or tslug
        try:
            stats = ensure_tenant_org_structure(
                db.session,
                company_name=display,
                tenant_slug=tslug,
                owner_user_id=getattr(owner, "id", None),
            )
            db.session.commit()
            after = audit_tenant_org_structure(db.session)
            click.echo(
                f"  {tslug}/{schema}: branch={stats.get('branch_id')} "
                f"wh_created={stats.get('warehouses_created')} "
                f"linked={stats.get('warehouses_linked')} "
                f"orphans={after.get('warehouses_without_branch')} "
                f"types={after.get('warehouse_types')}"
            )
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(f"{tslug}/{schema}: {exc}") from exc
    click.echo("OK")


@click.command("tenants-sync-permissions")
@with_appcontext
def tenants_sync_permissions():
    """مزامنة صلاحيات كل الأدوار القياسية في كل تينانت (owner + admin + mechanic + …)."""
    from utils.tenant_fiscal_schema import iter_tenant_schemas, set_local_search_path
    from utils.tenant_permissions import permission_codes_for_tenant_owner
    from utils.role_sync import sync_all_tenant_standard_roles
    from models import Permission

    codes = permission_codes_for_tenant_owner()
    for slug, schema in iter_tenant_schemas(db.session):
        if schema.lower() == "public":
            click.echo(f"  {slug}/public: skipped (منصة رام الله)")
            continue
        set_local_search_path(db.session, schema)
        existing = {str(p.code or "").strip().lower(): p for p in Permission.query.all()}
        for code in codes:
            if code not in existing:
                db.session.add(Permission(code=code, name=code))
        db.session.flush()
        role_stats = sync_all_tenant_standard_roles(db.session)
        parts = [f"{s.get('role')}={s.get('permissions', s.get('skipped', '?'))}" for s in role_stats]
        click.echo(f"  {slug}/{schema}: " + ", ".join(parts))
    db.session.commit()
    click.echo("OK")


@click.command("sync-system-roles")
@click.option("--force", is_flag=True, help="مطلوب على الإنتاج")
@with_appcontext
def sync_system_roles(force: bool) -> None:
    """مزامنة أدوار المنصة من السجل + دمج super في super_admin (بدون إنشاء مستخدمين)."""
    if not force and os.getenv("ALLOW_SEED_ROLES") != "1":
        raise click.ClickException("sync-system-roles disabled. Use --force or ALLOW_SEED_ROLES=1.")
    from utils.role_sync import (
        consolidate_super_roles,
        sync_platform_standard_roles,
        sync_privileged_platform_roles,
    )

    try:
        with _begin():
            for code in sorted(RESERVED_CODES):
                _ensure_permission(code)
            priv_stats = sync_privileged_platform_roles(db.session)
            platform_stats = sync_platform_standard_roles(db.session)
            merge_stats = consolidate_super_roles(db.session)
        for r in Role.query.all():
            try:
                clear_role_permission_cache(r.id)
            except Exception:
                pass
        click.echo(f"OK: platform roles synced ({len(platform_stats)}), super merge={merge_stats}")
    except SQLAlchemyError as e:
        db.session.rollback()
        raise click.ClickException(f"DB error: {e}") from e


@click.command("fiscal-period-close")
@click.argument("period_key")
@click.option("--scope", type=click.Choice(["GL_ONLY", "FULL"]), default="FULL")
@click.option("--no-gl", is_flag=True, help="بدون قيود إقفال GL")
@click.option("--no-carry", is_flag=True, help="بدون ترحيل سنوي")
@click.option("--no-lock", is_flag=True, help="إقفال بدون LOCKED")
@with_appcontext
def fiscal_period_close(period_key, scope, no_gl, no_carry, no_lock):
    """إقفال فترة محاسبية بالمفتاح (مثل 2025-FY أو 2025-Q1)."""
    from utils.period_close_service import close_fiscal_period, get_period_by_key

    period = get_period_by_key(period_key)
    if not period:
        raise click.ClickException(f"الفترة غير موجودة: {period_key}")
    result = close_fiscal_period(
        period.id,
        close_scope=scope,
        post_gl=not no_gl,
        carry_forward=not no_carry,
        lock_period=not no_lock,
    )
    click.echo(
        f"OK: {result['period_key']} -> {result['status']} "
        f"snapshots={result.get('entity_snapshots')}"
    )


@click.command("accounting-audit")
@click.option("--limit", type=int, default=0, show_default=True, help="0 = كل الجهات")
@click.option("--fix", is_flag=True, help="إعادة حساب الأرصدة المخزّنة عند الفروقات")
@click.option("--fix-policy", is_flag=True, help="فك ربط الدفعات القديمة من المبيعات وربطها بالعميل فقط")
@click.option("--include-archived", is_flag=True)
@with_appcontext
def accounting_audit(limit, fix, fix_policy, include_archived):
    """تدقيق محاسبي صارم: حقوق / التزامات / رصيد للعميل والمورد والشريك."""
    from utils.accounting_audit import audit_entity_balances, format_audit_report_text

    report = audit_entity_balances(
        limit=int(limit or 0),
        include_archived=include_archived,
        fix=fix,
        fix_policy=fix_policy,
    )
    click.echo(format_audit_report_text(report))
    s = report.get("summary", {})
    if any(s.get(k, 0) for k in s):
        raise SystemExit(1)


@click.command("audit-integrity")
@click.option(
    "--scope",
    type=click.Choice(["balances", "statements", "payments", "checks", "all", "customers", "suppliers", "partners"], case_sensitive=False),
    default="all",
)
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--fix", is_flag=True)
@click.option("--include-archived", is_flag=True)
@with_appcontext
def audit_integrity(scope, limit, fix, include_archived):
    scope = (scope or "all").lower()
    limit = int(limit or 0)
    tolerance = Decimal("0.01")
    balance_scope = scope if scope in {"customers", "suppliers", "partners"} else None

    def _want(key: str) -> bool:
        return scope in ("all", key)

    results = {
        "scope": scope,
        "limit": limit,
        "fix": bool(fix),
        "include_archived": bool(include_archived),
        "balances": {"checked": 0, "mismatches": 0, "fixed": 0, "errors": 0},
        "statements": {"checked": 0, "errors": 0, "failures": []},
        "payments": {"checked": 0, "issues": 0, "fixed": 0, "samples": []},
        "checks": {"checked": 0, "issues": 0, "fixed": 0, "samples": []},
    }

    if _want("balances") or balance_scope:
        groups = [
            ("customer", Customer, build_customer_balance_view, update_customer_balance_components),
            ("supplier", Supplier, build_supplier_balance_view, update_supplier_balance_components),
            ("partner", Partner, build_partner_balance_view, update_partner_balance_components),
        ]
        if balance_scope == "customers":
            groups = [groups[0]]
        elif balance_scope == "suppliers":
            groups = [groups[1]]
        elif balance_scope == "partners":
            groups = [groups[2]]
        for label, model_cls, breakdown_fn, updater_fn in groups:
            q = model_cls.query.order_by(model_cls.id.asc())
            if hasattr(model_cls, "is_archived") and not include_archived:
                q = q.filter(model_cls.is_archived == False)  # noqa: E712
            if limit:
                q = q.limit(limit)
            for obj in q:
                results["balances"]["checked"] += 1
                try:
                    breakdown = breakdown_fn(obj.id, db.session)
                except Exception:
                    results["balances"]["errors"] += 1
                    db.session.rollback()
                    continue
                if not breakdown or not breakdown.get("success"):
                    results["balances"]["errors"] += 1
                    continue
                expected = Decimal(str(breakdown.get("balance", {}).get("amount", 0) or 0))
                stored = Decimal(str(getattr(obj, "current_balance", 0) or 0))
                diff = (expected - stored).copy_abs()
                if diff <= tolerance:
                    continue
                results["balances"]["mismatches"] += 1
                if fix:
                    try:
                        updater_fn(obj.id, db.session)
                        db.session.commit()
                        results["balances"]["fixed"] += 1
                    except Exception:
                        db.session.rollback()
                        results["balances"]["errors"] += 1

    if _want("statements"):
        user = User.query.filter(User.is_active.is_(True)).order_by(User.id.asc()).first() or User.query.order_by(User.id.asc()).first()
        if user:
            from app import create_app
            app = create_app()
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["_user_id"] = str(user.id)
                    sess["_fresh"] = True

                for model_cls, url_fn in [
                    (Customer, lambda oid: f"/customers/{oid}/account_statement?start_date=2024-01-01&end_date=2026-12-31"),
                    (Supplier, lambda oid: f"/vendors/suppliers/{oid}/statement?from=2024-01-01&to=2026-12-31"),
                    (Partner, lambda oid: f"/vendors/partners/{oid}/statement?from=2024-01-01&to=2026-12-31"),
                ]:
                    q = model_cls.query.order_by(model_cls.id.asc())
                    if hasattr(model_cls, "is_archived") and not include_archived:
                        q = q.filter(model_cls.is_archived == False)  # noqa: E712
                    if limit:
                        q = q.limit(limit)
                    for obj in q:
                        results["statements"]["checked"] += 1
                        try:
                            resp = client.get(url_fn(obj.id))
                            if resp.status_code != 200:
                                results["statements"]["errors"] += 1
                                if len(results["statements"]["failures"]) < 50:
                                    results["statements"]["failures"].append({"path": url_fn(obj.id), "status": resp.status_code})
                        except Exception as exc:
                            results["statements"]["errors"] += 1
                            if len(results["statements"]["failures"]) < 50:
                                results["statements"]["failures"].append({"path": url_fn(obj.id), "error": str(exc)})

    if _want("payments"):
        from models import Payment
        fk_to_type = [
            ("shipment_id", PaymentEntityType.SHIPMENT.value),
            ("expense_id", PaymentEntityType.EXPENSE.value),
            ("loan_settlement_id", PaymentEntityType.LOAN.value),
            ("sale_id", PaymentEntityType.SALE.value),
            ("invoice_id", PaymentEntityType.INVOICE.value),
            ("preorder_id", PaymentEntityType.PREORDER.value),
            ("service_id", PaymentEntityType.SERVICE.value),
            ("customer_id", PaymentEntityType.CUSTOMER.value),
            ("supplier_id", PaymentEntityType.SUPPLIER.value),
            ("partner_id", PaymentEntityType.PARTNER.value),
        ]

        q = Payment.query.order_by(Payment.id.asc())
        if not include_archived:
            q = q.filter(Payment.is_archived == False)  # noqa: E712
        if limit:
            q = q.limit(limit)
        for p in q:
            results["payments"]["checked"] += 1
            core_targets = [fk for fk in ("shipment_id", "expense_id", "loan_settlement_id", "sale_id", "invoice_id", "preorder_id", "service_id") if getattr(p, fk, None)]
            if len(core_targets) > 1:
                results["payments"]["issues"] += 1
                if len(results["payments"]["samples"]) < 50:
                    results["payments"]["samples"].append({"payment_id": p.id, "issue": "multiple_targets", "targets": core_targets})
                continue

            targets = [fk for fk, _ in fk_to_type if getattr(p, fk, None)]
            expected_type = None
            if targets:
                fk = targets[0]
                expected_type = dict(fk_to_type).get(fk)
            if not targets and (p.entity_type not in (PaymentEntityType.MISCELLANEOUS.value, PaymentEntityType.OTHER.value)):
                results["payments"]["issues"] += 1
                if len(results["payments"]["samples"]) < 50:
                    results["payments"]["samples"].append({"payment_id": p.id, "issue": "no_target", "entity_type": p.entity_type})
                continue
            if expected_type and p.entity_type != expected_type:
                results["payments"]["issues"] += 1
                if fix:
                    try:
                        p.entity_type = expected_type
                        db.session.commit()
                        results["payments"]["fixed"] += 1
                    except Exception:
                        db.session.rollback()
                if len(results["payments"]["samples"]) < 50:
                    results["payments"]["samples"].append({"payment_id": p.id, "issue": "entity_type_mismatch", "expected": expected_type, "actual": p.entity_type})

            if core_targets:
                fk = core_targets[0]
                expected_type2 = dict(fk_to_type).get(fk)
                if expected_type2 and p.entity_type != expected_type2:
                    results["payments"]["issues"] += 1
                    if len(results["payments"]["samples"]) < 50:
                        results["payments"]["samples"].append({"payment_id": p.id, "issue": "core_entity_type_mismatch", "expected": expected_type2, "actual": p.entity_type})

    if _want("checks"):
        from models import Check
        q = Check.query.order_by(Check.id.asc())
        if not include_archived:
            q = q.filter(Check.is_archived == False)  # noqa: E712
        if limit:
            q = q.limit(limit)
        for ch in q:
            results["checks"]["checked"] += 1
            if not ch.payment_id or not ch.payment:
                continue
            p = ch.payment
            expected = {"customer_id": p.customer_id, "supplier_id": p.supplier_id, "partner_id": p.partner_id}
            issue = False
            for k, v in expected.items():
                if v and getattr(ch, k) not in (None, v):
                    issue = True
            if issue:
                results["checks"]["issues"] += 1
                if fix:
                    try:
                        if expected["customer_id"] and ch.customer_id is None:
                            ch.customer_id = expected["customer_id"]
                        if expected["supplier_id"] and ch.supplier_id is None:
                            ch.supplier_id = expected["supplier_id"]
                        if expected["partner_id"] and ch.partner_id is None:
                            ch.partner_id = expected["partner_id"]
                        db.session.commit()
                        results["checks"]["fixed"] += 1
                    except Exception:
                        db.session.rollback()
                if len(results["checks"]["samples"]) < 50:
                    results["checks"]["samples"].append(
                        {"check_id": ch.id, "payment_id": ch.payment_id, "customer_id": ch.customer_id, "supplier_id": ch.supplier_id, "partner_id": ch.partner_id}
                    )

    click.echo(json.dumps(results, ensure_ascii=False, indent=2))


@click.command("checks-sync-due")
@click.option(
    "--target-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="تاريخ المعالجة (افتراضي اليوم). سيتم اعتبار أي شيك يستحق في هذا التاريخ أو قبله كمسحوب."
)
@click.option(
    "--direction",
    type=click.Choice(["all", "in", "out"], case_sensitive=False),
    default="all",
    show_default=True,
    help="تصفية حسب اتجاه الشيك (وارد/صادر)."
)
@click.option("--limit", type=int, help="حد أقصى لعدد الشيكات التي سيتم معالجتها.")
@click.option("--dry-run", is_flag=True, help="عرض ما سيتم تنفيذه دون تعديل فعلي.")
@click.option("--note", type=str, default="", help="نص مخصص يضاف في مذكرة تحديث الحالة.")
@with_appcontext
def checks_sync_due(target_date, direction, limit, dry_run, note):
    """تسوية حالات الشيكات بناءً على تاريخ الاستحقاق (معلق قبل الاستحقاق، مسحوب بعده)."""
    from routes.checks import CheckActionService

    target_day = target_date.date() if target_date else datetime.now(timezone.utc).date()
    cutoff_dt = datetime.combine(target_day, datetime.max.time())
    pending_like = [
        CheckStatus.PENDING.value,
        CheckStatus.RESUBMITTED.value,
        CheckStatus.OVERDUE.value,
    ]

    query = (
        Check.query
        .filter(Check.check_due_date.isnot(None))
        .filter(Check.status.in_(pending_like))
        .filter(Check.check_due_date <= cutoff_dt)
        .order_by(Check.check_due_date.asc(), Check.id.asc())
    )

    direction_key = (direction or "all").lower()
    if direction_key in ("in", "out"):
        dir_value = PaymentDirection.IN.value if direction_key == "in" else PaymentDirection.OUT.value
        query = query.filter(Check.direction == dir_value)

    if limit:
        query = query.limit(limit)

    candidates = query.all()
    if not candidates:
        click.echo("لا توجد شيكات بحاجة إلى تحديث بناءً على المعايير الحالية.")
        return

    def _due_as_date(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        return value

    def _direction_code(value):
        raw = getattr(value, "value", value)
        return "IN" if str(raw or "").upper() == PaymentDirection.IN.value else "OUT"

    def _resolve_token(check_obj: Check):
        if check_obj.payment_id:
            return f"payment-{check_obj.payment_id}"
        reference = (check_obj.reference_number or "").strip()
        if reference:
            upper_ref = reference.upper()
            if upper_ref.startswith("PMT-SPLIT-"):
                try:
                    split_id = int(upper_ref.split("PMT-SPLIT-")[-1].split("-")[0])
                    return f"split-{split_id}"
                except ValueError:
                    pass
            if upper_ref.startswith("EXPENSE-"):
                try:
                    exp_id = int(upper_ref.split("EXPENSE-")[-1].split("-")[0])
                    return f"expense-{exp_id}"
                except ValueError:
                    pass
            if upper_ref.startswith("EXP-") and check_obj.expense_id:
                return f"expense-{check_obj.expense_id}"
        if check_obj.expense_id:
            return f"expense-{check_obj.expense_id}"
        return f"check-{check_obj.id}"

    def _amount_in_ils(check_obj: Check) -> Decimal:
        amt = Decimal(str(check_obj.amount or 0))
        if amt <= 0:
            return Decimal("0")
        currency = (check_obj.currency or "ILS").upper()
        if currency == "ILS":
            return amt
        ref_dt = check_obj.check_due_date if isinstance(check_obj.check_due_date, datetime) else None
        if not ref_dt:
            ref_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            return convert_amount(amt, currency, "ILS", ref_dt)
        except Exception:
            return Decimal("0")

    actor = SimpleNamespace(username="AUTO_CHECK_SYNC", id=0, is_system_account=True)
    service = CheckActionService(actor)

    processed_tokens = set()
    stats = {
        "total": len(candidates),
        "updated": 0,
        "errors": 0,
        "skipped": 0,
        "direction": {
            "IN": {"count": 0, "amount_ils": Decimal("0")},
            "OUT": {"count": 0, "amount_ils": Decimal("0")},
        },
    }
    rows = []

    for check_obj in candidates:
        token = _resolve_token(check_obj)
        if not token or token in processed_tokens:
            stats["skipped"] += 1
            continue
        processed_tokens.add(token)

        due_date = _due_as_date(check_obj.check_due_date)
        if not due_date:
            stats["skipped"] += 1
            continue

        current_status = check_obj.status.value if isinstance(check_obj.status, CheckStatus) else str(check_obj.status or "").upper()
        if current_status == "CASHED":
            stats["skipped"] += 1
            continue

        note_parts = [
            f"تسوية آلية لتاريخ استحقاق {due_date.isoformat()}",
            f"تشغيل {target_day.isoformat()}",
        ]
        if note:
            note_parts.append(note.strip())
        note_text = " - ".join(part for part in note_parts if part)

        amount_ils = _amount_in_ils(check_obj)
        entry = {
            "token": token,
            "check_id": check_obj.id,
            "target_status": "CASHED",
            "current_status": current_status,
            "due_date": due_date.isoformat(),
            "direction": _direction_code(check_obj.direction),
            "amount": float(check_obj.amount or 0),
            "amount_ils": float(amount_ils),
            "currency": check_obj.currency or "ILS",
            "entity_type": check_obj.entity_type or "",
            "entity_id": check_obj.entity_id,
            "reference": check_obj.reference_number,
        }

        if dry_run:
            stats["updated"] += 1
            stats["direction"][entry["direction"]]["count"] += 1
            stats["direction"][entry["direction"]]["amount_ils"] += amount_ils
            rows.append(entry)
            continue

        try:
            result = service.run(token, "CASHED", note_text)
            db.session.commit()
            balance_after = result.get("balance")
            if balance_after is not None:
                entry["balance_after"] = balance_after
            stats["updated"] += 1
            stats["direction"][entry["direction"]]["count"] += 1
            stats["direction"][entry["direction"]]["amount_ils"] += amount_ils
            rows.append(entry)
        except Exception as exc:
            stats["errors"] += 1
            db.session.rollback()
            click.echo(f"❌ فشل في تحديث الشيك #{check_obj.id} ({token}): {exc}")

    click.echo(f"\n📊 النتائج حتى {target_day.isoformat()}:")
    click.echo(f"- إجمالي المرشحين: {stats['total']}")
    click.echo(f"- تم تحديثه: {stats['updated']}")
    click.echo(f"- تم تخطيه: {stats['skipped']}")
    click.echo(f"- أخطاء: {stats['errors']}")

    for dir_key in ("IN", "OUT"):
        dir_stats = stats["direction"][dir_key]
        click.echo(
            f"  • {('الواردة' if dir_key == 'IN' else 'الصادرة')}: "
            f"{dir_stats['count']} شيكات | {dir_stats['amount_ils']:.2f} ILS"
        )

    if rows:
        click.echo("\nتفاصيل الشيكات التي تمت معالجتها:")
        for row in rows:
            click.echo(
                f"- #{row['check_id']} ({row['token']}) | استحقاق {row['due_date']} | "
                f"{row['direction']} | {row['amount']:.2f} {row['currency']} -> CASHED"
            )

    if dry_run:
        click.echo("\nوضع Dry-Run مفعّل: لم يتم تعديل أي بيانات.")
        return

    if stats["updated"]:
        audit_payload = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "target_date": target_day.isoformat(),
            "updated": stats["updated"],
            "direction": {
                k: {
                    "count": v["count"],
                    "amount_ils": float(v["amount_ils"]),
                }
                for k, v in stats["direction"].items()
            },
        }
        db.session.add(AuditLog(
            model_name="Check",
            action="CHECK_AUTO_CLASSIFY",
            new_data=json.dumps(audit_payload, ensure_ascii=False)
        ))
        db.session.commit()
        click.echo("\n📝 تم تسجيل العملية في سجل التدقيق.")


# قائمة فئات المنتجات الافتراضية (الاسم الخاطئ "lkj[hj 2" مُصحّح إلى "قطع غيار")
PRODUCT_CATEGORIES_DEFAULT = [
    "محركات", "قطع غيار", "GEARBOX", "HYD PUMP", "HYD PARTS", "كوبلنات", "فلاتر", "بخاخات",
    "محركات ديزل", "جلود اهتزاز", "زيوت وشحمة", "الكترونيات", "كسكيتات", "مراوح تبريد",
    "برابيش هواء وماء ماتور", "رديترات", "قطع محركات جديدة", "متفرقات", "قطع محركات مستعملة",
    "معدات", "خدمات", "مولدات وماكنات", "شحن وجمرك",
]

@click.command("seed-product-categories")
@with_appcontext
def seed_product_categories() -> None:
    """زرع فئات المنتجات الافتراضية (23 فئة). يضيف فقط الأسماء غير الموجودة."""
    existing = {(c.name or "").strip().lower(): c for c in ProductCategory.query.all()}
    added = 0
    for name in PRODUCT_CATEGORIES_DEFAULT:
        name = (name or "").strip()
        if not name or name.lower() in existing:
            continue
        c = ProductCategory(name=name)
        db.session.add(c)
        existing[name.lower()] = c
        added += 1
        click.echo(f"  + {name}")
    try:
        db.session.commit()
        click.echo(f"✅ تمت إضافة {added} فئة. (الإجمالي: {len(existing)})")
    except Exception as e:
        db.session.rollback()
        raise click.ClickException(str(e))


@click.command("restore-product-categories")
@click.option("--backup-path", type=click.Path(exists=True), required=True, help="مسار ملف النسخة الاحتياطية .sql (مثال: instance/backups/backup_20260207_230002.sql)")
@with_appcontext
def restore_product_categories(backup_path: str) -> None:
    """استعادة فئات المنتجات من ملف نسخة احتياطية SQL. يضيف فقط الأسماء غير الموجودة."""
    with open(backup_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    start_marker = "COPY public.product_categories ("
    if start_marker not in content:
        raise click.ClickException("لم يُعثر على جدول product_categories في الملف.")
    start = content.index(start_marker)
    end = content.find("\n\\.\n", start)
    if end == -1:
        end = content.find("\n\\.", start)
    if end == -1:
        raise click.ClickException("لم يُعثر على نهاية بيانات product_categories.")
    block = content[start:end]
    lines = [ln for ln in block.split("\n") if ln.strip() and not ln.strip().startswith("COPY ")]
    existing = {(c.name or "").strip().lower(): c for c in ProductCategory.query.all()}
    added = 0
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = (parts[1] or "").strip()
        if not name or name.lower() in existing:
            continue
        c = ProductCategory(name=name)
        db.session.add(c)
        existing[name.lower()] = c
        added += 1
        click.echo(f"  + {name}")
    try:
        db.session.commit()
        click.echo(f"تمت إضافة {added} فئة.")
    except Exception as e:
        db.session.rollback()
        raise click.ClickException(str(e))


@click.command("restore-upgrade-production")
@click.option("--backup-path", default=os.path.join("instance", "backup_20260207_000139.dump"), show_default=True)
@click.option("--force", is_flag=True, default=False)
@click.option("--confirm-restore", is_flag=True, default=False)
@click.option("--skip-upgrade", is_flag=True, default=False)
@click.option("--skip-fix", is_flag=True, default=False)
@click.option("--dry-run-fix", is_flag=True, default=False)
@with_appcontext
def restore_upgrade_production(backup_path: str, force: bool, confirm_restore: bool, skip_upgrade: bool, skip_fix: bool, dry_run_fix: bool) -> None:
    allow = os.getenv("ALLOW_PRODUCTION_RESTORE_UPGRADE", "").strip() == "1"
    if not (force or allow):
        raise click.ClickException("ارفع ALLOW_PRODUCTION_RESTORE_UPGRADE=1 أو استخدم --force")
    if not confirm_restore:
        raise click.ClickException("لتأكيد الاستعادة اكتب: --confirm-restore")

    abs_path = backup_path
    if not os.path.isabs(abs_path):
        abs_path = os.path.abspath(abs_path)
    if not os.path.exists(abs_path):
        raise click.ClickException(f"ملف النسخة غير موجود: {abs_path}")

    from flask import current_app
    from extensions import restore_database

    ok, msg = restore_database(current_app, abs_path)
    if not ok:
        raise click.ClickException(msg)
    click.echo(f"✅ {msg}")

    try:
        db.session.remove()
    except Exception:
        pass
    try:
        db.engine.dispose()
    except Exception:
        pass

    if not skip_upgrade:
        from flask_migrate import upgrade as migrate_upgrade
        migrate_upgrade()
        click.echo("✅ تم تطبيق التهجير الموجود في الكود.")

    if not skip_fix:
        from سكريبتات.fix_production_data import fix_production_data
        fix_production_data(app=current_app._get_current_object(), dry_run=dry_run_fix)
        click.echo("✅ تم تشغيل إصلاح البيانات.")


@click.command("db-verify")
@click.option("--fix-stamp", is_flag=True, help="ختم مخططات التينانت برأس public إن اختلفت")
@click.option(
    "--ensure-fiscal",
    is_flag=True,
    help="إنشاء جداول fiscal_periods/period_closes/entity_period_balances في مخططات التينانت",
)
@with_appcontext
def db_verify(fix_stamp: bool, ensure_fiscal: bool) -> None:
    """التحقق من رأس Alembic وتطابق ختم مخططات التينانت."""
    from flask import current_app
    from sqlalchemy import text as sa_text

    try:
        from alembic.script import ScriptDirectory
    except Exception as exc:
        raise click.ClickException(f"تعذّر تحميل Alembic: {exc}") from exc

    migrate_ext = current_app.extensions.get("migrate")
    if not migrate_ext or not getattr(migrate_ext, "migrate", None):
        raise click.ClickException("Flask-Migrate غير مهيأ")
    cfg = migrate_ext.migrate.get_config(directory=migrate_ext.directory)
    script = ScriptDirectory.from_config(cfg)
    head_revs = [str(h) for h in script.get_heads()]
    if len(head_revs) != 1:
        raise click.ClickException(f"أكثر من رأس Alembic: {head_revs}")
    head = head_revs[0]
    click.echo(f"alembic head (code): {head}")

    db_rev = db.session.execute(sa_text("SELECT version_num FROM public.alembic_version")).scalar()
    click.echo(f"alembic_version (public): {db_rev or '—'}")
    if str(db_rev or "") != head:
        raise click.ClickException(f"public غير محدّث: DB={db_rev} code={head}")

    tenants = db.session.execute(
        sa_text("SELECT slug, schema_name, is_active FROM public.tenants ORDER BY id")
    ).fetchall()
    if not tenants:
        click.echo("تحذير: لا يوجد سجل في public.tenants")
    for slug, schema_name, is_active in tenants:
        schema_name = _validate_pg_identifier(str(schema_name))
        exists = db.session.execute(
            sa_text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
            ),
            {"s": schema_name},
        ).scalar()
        if not exists:
            raise click.ClickException(f"مخطط مفقود: {schema_name} (tenant {slug})")
        t_rev = db.session.execute(
            sa_text(f"SELECT version_num FROM {schema_name}.alembic_version")
        ).scalar()
        status = "OK" if str(t_rev or "") == head else "MISMATCH"
        click.echo(
            f"  tenant {slug}: schema={schema_name} active={is_active} "
            f"alembic={t_rev or '—'} [{status}]"
        )
        if status != "OK":
            if fix_stamp:
                from utils.tenant_prod_seed import _stamp_tenant_alembic_head

                _stamp_tenant_alembic_head(db.session, schema_name)
                db.session.commit()
                click.echo(f"  → خُتم {schema_name} بـ {head}")
            else:
                raise click.ClickException(
                    f"مخطط {schema_name}: {t_rev} ≠ head {head} — "
                    f"نفّذ: flask db-verify --fix-stamp أو flask tenants setup-production"
                )
        if schema_name.lower() != "public":
            from utils.tenant_fiscal_schema import FISCAL_TABLES, ensure_fiscal_tables_in_schema

            missing = []
            for tbl in FISCAL_TABLES:
                has_tbl = db.session.execute(
                    sa_text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = :s AND table_name = :t
                        """
                    ),
                    {"s": schema_name, "t": tbl},
                ).scalar()
                if not has_tbl:
                    missing.append(tbl)
            if missing:
                if ensure_fiscal:
                    ensure_fiscal_tables_in_schema(db.session, schema_name)
                    click.echo(f"  → أُنشئت جداول الإقفال في {schema_name}: {missing}")
                else:
                    raise click.ClickException(
                        f"مخطط {schema_name}: جداول إقفال ناقصة {missing} — "
                        f"نفّذ: flask tenants-ensure-fiscal-tables أو db-verify --ensure-fiscal"
                    )

    click.echo("✅ التهجيرات مكتملة ومتسقة.")


@click.command("upgrade-production")
@click.option("--force", is_flag=True, default=False)
@click.option("--skip-fix", is_flag=True, default=False)
@click.option("--revision", default="head", show_default=True)
@click.option("--dry-run-fix", is_flag=True, default=False)
@with_appcontext
def upgrade_production(force: bool, skip_fix: bool, revision: str, dry_run_fix: bool) -> None:
    allow = os.getenv("ALLOW_PRODUCTION_UPGRADE", "").strip() == "1"
    if not (force or allow):
        raise click.ClickException("ارفع ALLOW_PRODUCTION_UPGRADE=1 أو استخدم --force")

    from flask import current_app
    from flask_migrate import upgrade as migrate_upgrade

    migrate_upgrade(revision=revision)
    click.echo("✅ تم تطبيق التهجيرات على قاعدة البيانات الحالية.")

    if not skip_fix:
        from fix_production_data import fix_production_data
        fix_production_data(app=current_app._get_current_object(), dry_run=dry_run_fix)
        click.echo("✅ تم تشغيل إصلاح البيانات.")


def _validate_pg_identifier(value: str) -> str:
    s = (value or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if not s or len(s) > 63 or any(ch not in allowed for ch in s):
        raise click.ClickException("قيمة غير صالحة (مسموح فقط: a-z A-Z 0-9 _)")
    return s


def _tenant_schema_from_slug(slug: str) -> str:
    base = (slug or "").strip().lower().replace("-", "_")
    base = "".join(ch for ch in base if (ch.isalnum() or ch == "_"))
    if not base:
        raise click.ClickException("slug غير صالح")
    if base[0].isdigit():
        base = f"t{base}"
    return _validate_pg_identifier(f"t_{base}")


def _ensure_tenant_registry(slug: str, schema_name: str, display_name: str | None, *, is_active: bool = True) -> TenantRegistry:
    row = TenantRegistry.query.filter_by(slug=slug).first()
    if not row:
        row = TenantRegistry(slug=slug)
        db.session.add(row)
    row.schema_name = schema_name
    row.display_name = (display_name or slug).strip()
    row.is_active = bool(is_active)
    db.session.flush()
    return row


def _seed_tenant_owner(*, owner_username: str, owner_email: str, owner_password: str) -> None:
    from permissions_config.permissions import PermissionsRegistry
    all_codes = PermissionsRegistry.get_all_permission_codes()
    existing = {str(p.code or "").strip().lower(): p for p in Permission.query.all()}
    for code in sorted(all_codes):
        c = str(code or "").strip().lower()
        if not c:
            continue
        if c in existing:
            continue
        db.session.add(Permission(code=c, name=c))
    db.session.flush()

    perms = [p for p in Permission.query.all() if getattr(p, "id", None)]
    role = Role.query.filter_by(name="owner").one_or_none()
    if not role:
        role = Role(name="owner")
        db.session.add(role)
        db.session.flush()
    role.permissions = perms

    email_norm = (owner_email or "").strip().lower()
    uname = (owner_username or "owner").strip() or "owner"
    user = User.query.filter((User.username == uname) | (func.lower(User.email) == email_norm)).one_or_none()
    if not user:
        user = User(username=uname, email=email_norm)
        db.session.add(user)
        db.session.flush()
    user.username = uname
    user.email = email_norm
    user.role = role
    user.set_password(owner_password)
    user.is_active = True
    db.session.flush()


@click.group("tenants")
@with_appcontext
def tenants_group():
    pass


@tenants_group.command("provision")
@click.option("--slug", required=True)
@click.option("--display-name", default=None)
@click.option("--schema", "schema_name", default=None)
@click.option("--owner-username", default="owner")
@click.option("--owner-email", default=None)
@click.option("--owner-password", default=None)
@click.option("--skip-migrate", is_flag=True, default=False)
@click.option("--inactive", is_flag=True, default=False)
def tenants_provision(slug: str, display_name: str | None, schema_name: str | None, owner_username: str, owner_email: str | None, owner_password: str | None, skip_migrate: bool, inactive: bool):
    dialect = str(getattr(getattr(db.engine, "dialect", None), "name", "") or "")
    if dialect != "postgresql":
        raise click.ClickException("هذا الأمر يتطلب PostgreSQL")

    slug = (slug or "").strip()
    if not slug:
        raise click.ClickException("slug مطلوب")

    if schema_name is None:
        schema_name = _tenant_schema_from_slug(slug)
    schema_name = (schema_name or "").strip()
    if schema_name.lower() != "public":
        schema_name = _validate_pg_identifier(schema_name)

    if schema_name.lower() == "public":
        _ensure_tenant_registry(slug=slug, schema_name=schema_name, display_name=display_name, is_active=not inactive)
        db.session.commit()
        click.echo(f"OK: tenant '{slug}' schema='{schema_name}' active={not inactive}")
        return

    owner_email = (owner_email or os.getenv("TENANT_OWNER_EMAIL") or "").strip()
    owner_password = (owner_password or os.getenv("TENANT_OWNER_PASSWORD") or "").strip()
    if not owner_email or not owner_password:
        raise click.ClickException("owner_email/owner_password مطلوبة (أو عبر TENANT_OWNER_EMAIL/TENANT_OWNER_PASSWORD)")

    from utils.tenant_prod_seed import provision_new_tenant, ensure_tenant_registry_row, _seed_tenant_owner

    if skip_migrate:
        _ensure_tenant_registry(slug=slug, schema_name=schema_name, display_name=display_name, is_active=not inactive)
        db.session.commit()
        db.session.execute(sa_text(f"SET search_path TO {schema_name}, public"))
        _seed_tenant_owner(owner_username=owner_username, owner_email=owner_email, owner_password=owner_password)
        db.session.commit()
        db.session.execute(sa_text("SET search_path TO public"))
        db.session.commit()
        click.echo(f"OK: tenant '{slug}' schema='{schema_name}' (skip-migrate) active={not inactive}")
        return

    prov = provision_new_tenant(
        db.session,
        slug=slug,
        display_name=display_name,
        owner_username=owner_username,
        owner_email=owner_email,
        owner_password=owner_password,
        copy_data=False,
    )
    if inactive:
        row = TenantRegistry.query.filter_by(slug=slug).first()
        if row:
            row.is_active = False
        db.session.commit()
    click.echo(f"OK: {prov.get('path')} schema={schema_name} owner={owner_username} active={not inactive}")


@click.group("branding")
@with_appcontext
def branding_group():
    """أصول الهوية: منصة أزاد مقابل تينانت."""
    pass


@branding_group.command("bootstrap")
@click.option("--alhazem-source", default=None, help="مجلد شعارات الحازم (افتراضي: سطح المكتب/انس)")
@with_appcontext
def branding_bootstrap(alhazem_source):
    """تهيئة مجلدات branding وربط الإعدادات — garage_manager فقط."""
    from utils.branding_assets import assert_garage_manager_only, bootstrap_dev_branding

    assert_garage_manager_only()
    report = bootstrap_dev_branding(db.session, alhazem_source=alhazem_source)
    db.session.commit()
    click.echo(report)


@branding_group.command("reorganize")
@click.option("--no-archive", is_flag=True, help="لا تنقل المكررات إلى _deprecated")
@with_appcontext
def branding_reorganize(no_archive):
    """تنظيم المجلدات، تطبيع مسارات DB، أرشفة مكررات static/img."""
    from utils.branding_assets import assert_garage_manager_only, reorganize_and_wire

    assert_garage_manager_only()
    report = reorganize_and_wire(db.session, archive_dupes=not no_archive)
    db.session.commit()
    click.echo(f"normalized_settings={report.get('settings_normalized')}")
    click.echo(f"archived={report.get('archived_duplicates')}")
    click.echo(report.get("audit"))


@branding_group.command("audit")
@with_appcontext
def branding_audit():
    """تقرير أصول branding وملفات img المتبقية."""
    from utils.branding_assets import assert_garage_manager_only, audit_branding_tree

    assert_garage_manager_only()
    import json
    click.echo(json.dumps(audit_branding_tree(), ensure_ascii=False, indent=2))


@tenants_group.command("setup-production")
@click.option("--owner-email", envvar="TENANT_OWNER_EMAIL", required=True)
@click.option("--owner-password", envvar="TENANT_OWNER_PASSWORD", required=True)
@click.option("--slug", multiple=True, help="تينانتات إضافية (افتراضي: nasrallah alhazem)")
@click.option("--no-copy", is_flag=True, default=False, help="لا تنسخ بيانات public إلى schemas الجديدة")
@with_appcontext
def tenants_setup_production(owner_email, owner_password, slug, no_copy):
    """
    إعداد إنتاجي محلي للتينانتات — قاعدة garage_manager فقط.
    لا يمس قواعد PostgreSQL الأخرى (mavi_erp, naser_company, ...).
    """
    from utils.tenant_prod_seed import assert_garage_manager_only, setup_production_dev_tenants

    assert_garage_manager_only()
    slugs = tuple(slug) if slug else ("nasrallah", "alhazem")
    report = setup_production_dev_tenants(
        owner_email=owner_email,
        owner_password=owner_password,
        provision_schemas=slugs,
        copy_data=not no_copy,
    )
    for t in report.get("tenants", []):
        click.echo(f"OK tenant: {t}")
    for err in report.get("errors", []):
        click.echo(f"ERR: {err}", err=True)
    if report.get("errors"):
        raise SystemExit(1)


def _guard_production_dangerous_cli(cmd):
    if not getattr(cmd, "callback", None):
        return cmd
    name = str(getattr(cmd, "name", "") or "")
    original_callback = cmd.callback

    def wrapped_callback(*args, **kwargs):
        if _is_production():
            allow = os.getenv("ALLOW_PRODUCTION_DANGEROUS_CLI", "").strip() == "1"
            if not allow:
                raise click.ClickException(f"هذا الأمر معطّل على الإنتاج: {name}. ارفع ALLOW_PRODUCTION_DANGEROUS_CLI=1 للتنفيذ.")
        return original_callback(*args, **kwargs)
    cmd.callback = wrapped_callback
    return cmd


def register_cli(app) -> None:
    commands = [
        import_sqlite_appdb,
        compare_sqlite_appdb,
        compare_sqlite_full,
        branding_group,
        tenants_group,
        seed_roles, sync_system_roles, sync_permissions, list_permissions, list_roles, role_add_perms, create_role, export_rbac,
        create_user, user_set_password, user_activate, user_assign_role, list_users, list_customers,
        seed_expense_types, expense_type_cmd, seed_palestine_cmd, seed_all, clear_rbac_caches,
        wh_create, wh_list, wh_stock, product_create, product_find, product_stock, product_set_price,
        stock_transfer, stock_exchange, stock_reserve, stock_unreserve, shipment_create, shipment_status,
        supplier_settlement_draft, supplier_settlement_confirm, partner_settlement_draft, partner_settlement_confirm,
        payment_create, payment_list, invoice_list, invoice_update_status, preorder_create,
        sr_create, sr_add_part, sr_add_task, sr_recalc, sr_set_status, sr_show, 
        cart_create, cart_add_item, order_from_cart, order_set_status, order_add_item,
        onlinepay_create, onlinepay_decrypt_card, expense_create, expense_pay, expense_link_known_entities, expenses_payoff_all,
        stock_adjustment_create, stock_adjustment_add_item, stock_adjustment_finalize,
        gl_seed_accounts, gl_list_batches, gl_list_entries,
        note_add, note_list, audit_tail,
        currency_balance, currency_validate, currency_report, currency_health, currency_update, currency_test,
        create_system_admin, create_system_admin_interactive,
        optimize_db, perf_snapshot, recompute_sale_returns, link_missing_counterparties,
        seed_employees, seed_salaries, seed_expenses_demo, seed_customer_statement_demo, seed_branches,
        workflow_check_timeouts, gl_recreate_payments, sync_balances, backfill_sale_invoices,
        fiscal_periods_sync, fiscal_period_close, tenants_ensure_fiscal_tables,
        tenants_ensure_org_structure, tenants_sync_permissions,
        accounting_audit, audit_integrity, checks_sync_due,
        seed_product_categories, restore_product_categories,
        restore_upgrade_production,
        upgrade_production,
        db_verify,
    ]
    for cmd in commands:
        name = str(getattr(cmd, "name", "") or "")
        if name.startswith("seed-") or name in ("import-sqlite-appdb", "compare-sqlite-appdb", "compare-sqlite-full", "restore-upgrade-production"):
            cmd = _guard_production_dangerous_cli(cmd)
        app.cli.add_command(cmd)
