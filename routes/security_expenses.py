import uuid
from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, jsonify
from sqlalchemy.orm import joinedload
from sqlalchemy.inspection import inspect
from extensions import db
from models import ExpenseType, SystemSettings, Expense, Account
from utils import permission_required


security_expenses_bp = Blueprint(
    "security_expenses",
    __name__,
    url_prefix="/security/expenses-control"
)


BASE_FIELD_LIBRARY = [
    {"key": "supplier_id", "label": "المورد", "category": "جهات", "type": "entity"},
    {"key": "partner_id", "label": "الشريك", "category": "جهات", "type": "entity"},
    {"key": "employee_id", "label": "الموظف", "category": "جهات", "type": "entity"},
    {"key": "branch_id", "label": "الفرع", "category": "أساسية", "type": "entity"},
    {"key": "site_id", "label": "الموقع", "category": "أساسية", "type": "entity"},
    {"key": "warehouse_id", "label": "المستودع", "category": "مستودعات", "type": "entity"},
    {"key": "shipment_id", "label": "الشحنة", "category": "مستودعات", "type": "entity"},
    {"key": "utility_account_id", "label": "حساب المرافق", "category": "خدمات", "type": "entity"},
    {"key": "stock_adjustment_id", "label": "تسوية المخزون", "category": "مستودعات", "type": "entity"},
    {"key": "period", "label": "الفترة المغطاة", "category": "زمنية", "type": "date_range"},
    {"key": "beneficiary_name", "label": "اسم الجهة المستفيدة", "category": "وصف", "type": "text"},
    {"key": "disbursed_by", "label": "مسلم الدفعة", "category": "وصف", "type": "text"},
    {"key": "paid_to", "label": "مدفوع إلى", "category": "وصف", "type": "text"},
    {"key": "tax_invoice_number", "label": "الفاتورة الضريبية", "category": "أرقام مرجعية", "type": "text"},
    {"key": "notes", "label": "ملاحظات عامة", "category": "وصف", "type": "long_text"},
    {"key": "description", "label": "وصف المصروف", "category": "وصف", "type": "long_text"},
    {"key": "payment_method", "label": "طريقة الدفع", "category": "دفع", "type": "choice"},
    {"key": "check_number", "label": "رقم الشيك", "category": "دفع", "type": "text"},
    {"key": "bank_transfer_ref", "label": "مرجع الحوالة", "category": "دفع", "type": "text"},
    {"key": "card_number", "label": "رقم البطاقة", "category": "دفع", "type": "text"},
    {"key": "online_gateway", "label": "بوابة الدفع", "category": "دفع", "type": "text"},
    {"key": "maintenance_provider_name", "label": "جهة الصيانة", "category": "خدمات", "type": "text"},
    {"key": "shipping_company_name", "label": "شركة الشحن", "category": "خدمات", "type": "text"},
    {"key": "travel_destination", "label": "وجهة السفر", "category": "سفر", "type": "text"},
    {"key": "insurance_company_name", "label": "شركة التأمين", "category": "تأمين", "type": "text"}
]


def _load_custom_fields():
    data = SystemSettings.get_setting("expense_custom_fields", default=[],)
    return data if isinstance(data, list) else []


def _save_custom_fields(payload):
    SystemSettings.set_setting(
        "expense_custom_fields",
        payload,
        description="لوحة تحكم المصاريف الاحترافية",
        data_type="json",
        is_public=False,
        commit=True
    )


def _build_field_library():
    library = {}
    for item in BASE_FIELD_LIBRARY:
        library[item["key"]] = item
    mapper = inspect(Expense)
    skip = {
        "id",
        "created_at",
        "updated_at",
        "is_archived",
        "archived_at",
        "archived_by",
        "archive_reason"
    }
    for column in mapper.columns:
        key = column.key
        if key in skip:
            continue
        if key not in library:
            label = key.replace("_", " ").strip().title()
            library[key] = {
                "key": key,
                "label": label,
                "category": "حقول افتراضية",
                "type": "text"
            }
    custom_items = _load_custom_fields()
    for item in custom_items:
        library[item["key"]] = item
    return list(library.values())


PAYMENT_BEHAVIORS = {"IMMEDIATE", "PARTIAL", "ON_ACCOUNT"}
TEMPLATES_SETTING_KEY = "expense_control_templates"


def _ledger_status(meta):
    ledger = (meta or {}).get("ledger") or {}
    missing = []
    if not (ledger.get("expense_account") or "").strip():
        missing.append("expense")
    if not (ledger.get("counterparty_account") or "").strip():
        missing.append("counterparty")
    if not (ledger.get("cash_account") or "").strip():
        missing.append("cash")
    return {
        "missing": missing,
        "is_complete": not missing
    }


def _load_templates():
    templates = SystemSettings.get_setting(TEMPLATES_SETTING_KEY, default=[])
    return templates if isinstance(templates, list) else []


def _save_templates(templates):
    SystemSettings.set_setting(
        TEMPLATES_SETTING_KEY,
        templates,
        description="قوالب لوحة تحكم المصاريف الاحترافية",
        data_type="json",
        is_public=False,
        commit=True
    )


def _normalize_meta(meta):
    m = meta
    if m in (None, "", "None"):
        snapshot = {}
    elif isinstance(m, dict):
        snapshot = dict(m)
    elif isinstance(m, str):
        try:
            import json
            snapshot = dict(json.loads(m))
        except Exception:
            snapshot = {}
    elif isinstance(m, (list, tuple)):
        snapshot = {}
        for item in m:
            if isinstance(item, dict):
                snapshot.update(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                k, v = item
                snapshot[str(k)] = v
            else:
                snapshot[str(item)] = None
    else:
        snapshot = {}
    required = snapshot.get("required") or []
    optional = snapshot.get("optional") or []
    snapshot["required"] = sorted(set(required))
    snapshot["optional"] = sorted(set(optional))
    ledger = snapshot.get("ledger") or {}
    snapshot["ledger"] = {
        "expense_account": (ledger.get("expense_account") or "").strip().upper() or None,
        "counterparty_account": (ledger.get("counterparty_account") or "").strip().upper() or None,
        "cash_account": (ledger.get("cash_account") or "").strip().upper() or None,
    }
    behavior = (snapshot.get("payment_behavior") or "IMMEDIATE").strip().upper()
    if behavior not in PAYMENT_BEHAVIORS:
        behavior = "IMMEDIATE"
    snapshot["payment_behavior"] = behavior
    return snapshot


def _update_type_meta(expense_type, meta):
    expense_type.fields_meta = meta
    db.session.add(expense_type)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        utils.flash_error(utils.MSG_SAVE_FAILED)
    return _normalize_meta(expense_type.fields_meta)


@security_expenses_bp.route("/", methods=["GET"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def control_panel():
    expense_types = (
        ExpenseType.query.options(joinedload(ExpenseType.expenses))
        .order_by(ExpenseType.name.asc())
        .all()
    )
    data = []
    account_rows = Account.query.order_by(Account.code.asc()).all()
    accounts = [
        {"code": acc.code, "name": acc.name, "type": getattr(acc, "type", None)}
        for acc in account_rows
    ]
    for etype in expense_types:
        meta = _normalize_meta(etype.fields_meta)
        ledger_status = _ledger_status(meta.get("ledger"))
        data.append(
            {
                "id": etype.id,
                "name": etype.name,
                "code": etype.code,
                "is_active": etype.is_active,
                "required": meta["required"],
                "optional": meta["optional"],
                "ledger": meta.get("ledger", {}),
                "payment_behavior": meta.get("payment_behavior"),
                "ledger_missing": ledger_status["missing"],
                "ledger_complete": ledger_status["is_complete"],
            }
        )
    field_library = _build_field_library()
    stats = {
        "types_count": len(expense_types),
        "active_types": len([t for t in expense_types if t.is_active]),
        "library_fields": len(field_library),
        "custom_fields": len(_load_custom_fields())
    }
    return render_template(
        "security/expenses_control/index.html",
        expense_types=data,
        field_library=field_library,
        stats=stats,
        accounts=accounts,
        payment_behaviors=sorted(PAYMENT_BEHAVIORS),
        templates=_load_templates()
    )


@security_expenses_bp.route("/library", methods=["GET"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_field_library():
    return jsonify({"success": True, "items": _build_field_library()})


@security_expenses_bp.route("/library/custom", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_add_custom_field():
    payload = request.get_json() or {}
    key = (payload.get("key") or "").strip()
    label = (payload.get("label") or "").strip()
    category = (payload.get("category") or "مخصصة").strip()
    input_type = (payload.get("type") or "text").strip()
    if not key or not label:
        return jsonify({"success": False, "error": "الحقل والمسمى مطلوبان"}), 400
    library = {item["key"]: item for item in _build_field_library()}
    if key in library:
        return jsonify({"success": False, "error": "المفتاح مستخدم بالفعل"}), 400
    custom_fields = _load_custom_fields()
    custom_fields.append(
        {"key": key, "label": label, "category": category, "type": input_type}
    )
    _save_custom_fields(custom_fields)
    return jsonify({"success": True, "items": _build_field_library()})


@security_expenses_bp.route("/types/<int:type_id>/fields", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_update_field_status(type_id):
    payload = request.get_json() or {}
    field_key = (payload.get("field_key") or "").strip()
    mode = (payload.get("mode") or "").strip().lower()
    if not field_key or mode not in {"required", "optional", "hidden"}:
        return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400
    field_library = {item["key"]: item for item in _build_field_library()}
    if field_key not in field_library:
        return jsonify({"success": False, "error": "حقل غير معروف"}), 404
    expense_type = db.get_or_404(ExpenseType, type_id)
    meta = _normalize_meta(expense_type.fields_meta)
    if mode == "required":
        meta["required"].append(field_key)
        meta["optional"] = [f for f in meta["optional"] if f != field_key]
    elif mode == "optional":
        meta["optional"].append(field_key)
        meta["required"] = [f for f in meta["required"] if f != field_key]
    else:
        meta["required"] = [f for f in meta["required"] if f != field_key]
        meta["optional"] = [f for f in meta["optional"] if f != field_key]
    meta["required"] = sorted(set(meta["required"]))
    meta["optional"] = sorted(set(meta["optional"]))
    updated_meta = _update_type_meta(expense_type, meta)
    return jsonify({"success": True, "meta": updated_meta})


@security_expenses_bp.route("/types/<int:type_id>/bulk", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_bulk_update(type_id):
    payload = request.get_json() or {}
    required = payload.get("required") or []
    optional = payload.get("optional") or []
    field_library = {item["key"]: item for item in _build_field_library()}
    for key in required + optional:
        if key not in field_library:
            return jsonify({"success": False, "error": f"الحقل {key} غير معروف"}), 400
    overlap = set(required) & set(optional)
    if overlap:
        return jsonify({"success": False, "error": "الحقل لا يمكن أن يكون الزامي واختياري"},), 400
    expense_type = db.get_or_404(ExpenseType, type_id)
    existing_meta = _normalize_meta(expense_type.fields_meta)
    existing_meta["required"] = sorted(set(required))
    existing_meta["optional"] = sorted(set(optional))
    updated_meta = _update_type_meta(expense_type, existing_meta)
    return jsonify({"success": True, "meta": updated_meta})


@security_expenses_bp.route("/types/<int:type_id>/ledger", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_update_ledger(type_id):
    expense_type = db.get_or_404(ExpenseType, type_id)
    payload = request.get_json() or {}
    meta = _normalize_meta(expense_type.fields_meta)
    ledger = meta.get("ledger", {})
    ledger["expense_account"] = (payload.get("expense_account") or "").strip().upper() or None
    ledger["counterparty_account"] = (payload.get("counterparty_account") or "").strip().upper() or None
    ledger["cash_account"] = (payload.get("cash_account") or "").strip().upper() or None
    meta["ledger"] = ledger
    behavior = (payload.get("payment_behavior") or meta.get("payment_behavior") or "IMMEDIATE").strip().upper()
    if behavior not in PAYMENT_BEHAVIORS:
        behavior = "IMMEDIATE"
    meta["payment_behavior"] = behavior
    updated_meta = _update_type_meta(expense_type, meta)
    return jsonify({"success": True, "meta": updated_meta})


@security_expenses_bp.route("/templates", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_create_template():
    payload = request.get_json() or {}
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    source_type_id = payload.get("source_type_id")
    if not name or not source_type_id:
        return jsonify({"success": False, "error": "بيانات القالب غير مكتملة"}), 400
    expense_type = db.get_or_404(ExpenseType, int(source_type_id))
    meta = _normalize_meta(expense_type.fields_meta)
    template = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "required": meta.get("required") or [],
        "optional": meta.get("optional") or [],
        "ledger": meta.get("ledger") or {},
        "payment_behavior": meta.get("payment_behavior") or "IMMEDIATE",
        "source_type_id": expense_type.id,
        "source_type_name": expense_type.name,
    }
    templates = _load_templates()
    templates.append(template)
    _save_templates(templates)
    return jsonify({"success": True, "template": template, "templates": templates})


@security_expenses_bp.route("/templates/<string:template_id>/apply", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_apply_template(template_id):
    payload = request.get_json() or {}
    type_ids = payload.get("type_ids") or []
    if not isinstance(type_ids, list) or not type_ids:
        return jsonify({"success": False, "error": "اختر الأنواع المستهدفة"}), 400
    templates = _load_templates()
    template = next((tpl for tpl in templates if tpl.get("id") == template_id), None)
    if not template:
        return jsonify({"success": False, "error": "القالب غير موجود"}), 404
    updated = []
    for tid in type_ids:
        try:
            type_id = int(tid)
        except (TypeError, ValueError):
            continue
        expense_type = db.session.get(ExpenseType, type_id)
        if not expense_type:
            continue
        meta = _normalize_meta(expense_type.fields_meta)
        meta["required"] = sorted(set(template.get("required") or []))
        meta["optional"] = sorted(set(template.get("optional") or []))
        meta["ledger"] = template.get("ledger") or {}
        meta["payment_behavior"] = template.get("payment_behavior") or "IMMEDIATE"
        updated_meta = _update_type_meta(expense_type, meta)
        updated.append({"type_id": expense_type.id, "meta": updated_meta})
    return jsonify({"success": True, "updated": updated})


@security_expenses_bp.route("/templates/<string:template_id>", methods=["DELETE"])
@permission_required(SystemPermissions.MANAGE_EXPENSES)
def api_delete_template(template_id):
    templates = _load_templates()
    new_templates = [tpl for tpl in templates if tpl.get("id") != template_id]
    if len(new_templates) == len(templates):
        return jsonify({"success": False, "error": "القالب غير موجود"}), 404
    _save_templates(new_templates)
    return jsonify({"success": True, "templates": new_templates})


