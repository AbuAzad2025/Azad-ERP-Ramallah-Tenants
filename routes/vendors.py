
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from permissions_config.enums import SystemPermissions
from flask import abort, Blueprint, current_app, flash, jsonify, redirect, render_template, render_template_string, request, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import generate_csrf
from sqlalchemy import func, or_, and_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import joinedload
from extensions import db
from forms import PartnerForm, SupplierForm, CURRENCY_CHOICES
import utils
from utils import D, q2, _get_or_404, archive_record, restore_record, permission_required, classify_entity_balance
from models import (
    ExchangeTransaction,
    Partner,
    Payment,
    PaymentDirection,
    PaymentStatus,
    Product,
    StockLevel,
    Supplier,
    SupplierLoanSettlement,
    Warehouse,
    WarehouseType,
    Expense,
    Sale,
    SaleLine,
    SaleStatus,
    ServicePart,
    ServiceRequest,
    ServiceStatus,
    _find_partner_share_percentage,
    Branch,
)

class CSRFProtectForm(FlaskForm):
    pass

vendors_bp = Blueprint("vendors_bp", __name__, url_prefix="/vendors")


@vendors_bp.route("/suppliers", methods=["GET"], endpoint="suppliers_list")
@login_required
def suppliers_list():
    form = CSRFProtectForm()
    search_term = (request.args.get("q") or request.args.get("search") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    q = Supplier.query.filter(Supplier.is_archived == False)
    if search_term:
        term = f"%{search_term}%"
        q = q.filter(or_(Supplier.name.ilike(term), Supplier.phone.ilike(term), Supplier.identity_number.ilike(term)))
    pagination = q.order_by(Supplier.name.asc(), Supplier.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    suppliers = list(pagination.items or [])

    from sqlalchemy import case
    bal = func.coalesce(Supplier.current_balance, 0)
    totals_row = (
        q.order_by(None)
        .with_entities(
            func.count(Supplier.id).label("total_suppliers"),
            func.coalesce(func.sum(bal), 0).label("total_balance"),
            func.coalesce(func.sum(case((bal > 0, bal), else_=0)), 0).label("total_debit"),
            func.coalesce(func.sum(case((bal < 0, -bal), else_=0)), 0).label("total_credit"),
            func.coalesce(func.sum(case((bal > 0, 1), else_=0)), 0).label("suppliers_with_debt"),
            func.coalesce(func.sum(case((bal < 0, 1), else_=0)), 0).label("suppliers_with_credit"),
        )
        .first()
    )
    total_suppliers = int(getattr(totals_row, "total_suppliers", 0) or 0)
    total_balance = float(getattr(totals_row, "total_balance", 0) or 0)
    total_debit = float(getattr(totals_row, "total_debit", 0) or 0)
    total_credit = float(getattr(totals_row, "total_credit", 0) or 0)
    suppliers_with_debt = int(getattr(totals_row, "suppliers_with_debt", 0) or 0)
    suppliers_with_credit = int(getattr(totals_row, "suppliers_with_credit", 0) or 0)
    summary = {
        "total_suppliers": total_suppliers,
        "total_balance": total_balance,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "suppliers_with_debt": suppliers_with_debt,
        "suppliers_with_credit": suppliers_with_credit,
        "average_balance": (total_balance / total_suppliers) if total_suppliers else 0,
    }
    
    default_branch = (
        Branch.query.filter(Branch.is_active.is_(True))
        .order_by(Branch.id.asc())
        .first()
    )
    quick_service = {
        "branch_id": default_branch.id if default_branch else None,
        "currency_choices": [{"code": code, "label": label} for code, label in CURRENCY_CHOICES],
        "default_currency": "ILS",
        "today": _utcnow_naive().strftime("%Y-%m-%d"),
    }
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1"
    if is_ajax:
        csrf_value = generate_csrf()
        table_html = render_template_string(
            """
<table class="table table-striped table-hover mb-0 align-middle" id="suppliersTable">
  <thead class="table-dark">
    <tr>
      <th style="width:70px">#</th>
      <th>الاسم</th>
      <th>الهاتف</th>
      <th>الرصيد</th>
      <th style="min-width: 440px;" data-sortable="false">عمليات</th>
    </tr>
  </thead>
  <tbody>
    {% for s in suppliers %}
    <tr>
      <td>{{ loop.index }}</td>
      <td class="supplier-name">{{ s.name }}</td>
      <td class="supplier-phone">{{ s.phone or '—' }}</td>
      <td data-sort-value="{{ s.current_balance or 0 }}">
        <span class="badge {% if (s.current_balance or 0) > 0 %}bg-success{% elif (s.current_balance or 0) == 0 %}bg-secondary{% else %}bg-danger{% endif %}" data-balance-supplier="{{ s.id }}">
          {{ '%.2f'|format(s.current_balance or 0) }} ₪
        </span>
      </td>
      <td>
        <div class="supplier-actions d-flex flex-wrap gap-2">
          <a href="{{ url_for('supplier_settlements_bp.supplier_settlement', supplier_id=s.id) }}"
             class="btn btn-sm btn-success d-flex align-items-center"
             title="التسوية الذكية الشاملة - قطع، مبيعات، صيانة، دفعات">
            <i class="fas fa-calculator"></i>
            <span class="d-none d-lg-inline ms-1">تسوية ذكية</span>
          </a>
          <a href="{{ url_for('expenses_bp.create_expense', supplier_id=s.id, mode='supplier_service') }}"
             class="btn btn-sm btn-info d-flex align-items-center js-supplier-service"
             data-supplier-id="{{ s.id }}"
             data-supplier-name="{{ s.name }}"
             title="توريد خدمات للمورد">
            <i class="fas fa-file-signature"></i>
            <span class="d-none d-lg-inline ms-1">توريد خدمات</span>
          </a>
          <a href="{{ url_for('payments.create_payment') }}?entity_type=SUPPLIER&entity_id={{ s.id }}&entity_name={{ s.name|urlencode }}"
             class="btn btn-sm btn-primary d-flex align-items-center" title="إضافة دفعة">
            <i class="fas fa-money-bill-wave"></i>
            <span class="d-none d-lg-inline ms-1">دفع</span>
          </a>
          <a href="{{ url_for('vendors_bp.suppliers_statement', supplier_id=s.id) }}"
             class="btn btn-sm btn-warning d-flex align-items-center" title="كشف حساب مبسط">
            <i class="fas fa-file-invoice"></i>
            <span class="d-none d-lg-inline ms-1">كشف حساب</span>
          </a>
          {% if current_user.has_permission(SystemPermissions.MANAGE_VENDORS) %}
            <a href="{{ url_for('vendors_bp.suppliers_edit', id=s.id) }}"
               class="btn btn-sm btn-outline-secondary d-flex align-items-center" title="تعديل">
              <i class="fas fa-edit"></i>
              <span class="d-none d-lg-inline ms-1">تعديل</span>
            </a>
            {% if s.is_archived %}
            <button type="button" class="btn btn-sm btn-success d-flex align-items-center" title="استعادة" onclick="restoreSupplier({{ s.id }})">
                <i class="fas fa-undo"></i>
                <span class="d-none d-lg-inline ms-1">استعادة</span>
            </button>
            {% else %}
            <button type="button" class="btn btn-sm btn-warning d-flex align-items-center" title="أرشفة" onclick="archiveSupplier({{ s.id }})">
                <i class="fas fa-archive"></i>
                <span class="d-none d-lg-inline ms-1">أرشفة</span>
            </button>
            {% endif %}
            <form method="post" action="{{ url_for('vendors_bp.suppliers_delete', id=s.id) }}" class="d-inline-block">
              <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
              <button type="submit"
                      class="btn btn-sm btn-danger d-flex align-items-center"
                      title="حذف عادي"
                      onclick="return confirm('حذف المورد؟');">
                <i class="fas fa-trash"></i>
                <span class="d-none d-lg-inline ms-1">حذف</span>
              </button>
            </form>
            
          {% endif %}
        </div>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5" class="text-center py-4">لا توجد بيانات</td></tr>
    {% endfor %}
    {% if suppliers %}
    <tr class="table-info fw-bold">
      <td colspan="3" class="text-end">الإجمالي:</td>
      <td class="{% if summary.total_balance > 0 %}text-success{% elif summary.total_balance < 0 %}text-danger{% else %}text-secondary{% endif %}">
        <span class="badge {% if summary.total_balance > 0 %}bg-success{% elif summary.total_balance < 0 %}bg-danger{% else %}bg-secondary{% endif %} fs-6">
          {{ '%.2f'|format(summary.total_balance) }} ₪
        </span>
      </td>
      <td></td>
    </tr>
    {% endif %}
  </tbody>
</table>
            """,
            suppliers=suppliers,
            csrf_token=csrf_value,
            summary=summary,
        )
        return jsonify(
            {
                "table_html": table_html,
                "total_suppliers": summary["total_suppliers"],
                "total_balance": summary["total_balance"],
                "average_balance": summary["average_balance"],
                "suppliers_with_debt": summary["suppliers_with_debt"],
                "suppliers_with_credit": summary["suppliers_with_credit"],
                "total_filtered": int(pagination.total or 0),
                "page": int(pagination.page or 1),
                "pages": int(pagination.pages or 1),
                "per_page": int(per_page),
            }
        )

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)
    return render_template(
        "vendors/suppliers/list.html",
        suppliers=suppliers,
        search=search_term,
        form=form,
        pay_url=url_for("payments.create_payment"),
        summary=summary,
        quick_service=quick_service,
        csrf_token_value=generate_csrf(),
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
    )


@vendors_bp.post("/suppliers/balances/recalculate", endpoint="suppliers_recalculate_balances")
@login_required
@permission_required(SystemPermissions.MANAGE_VENDORS)
def suppliers_recalculate_balances():
    payload = request.get_json(silent=True) or {}
    ids_raw = (
        request.form.get("supplier_ids")
        or request.form.get("ids")
        or payload.get("supplier_ids")
        or payload.get("ids")
        or ""
    )
    if isinstance(ids_raw, list):
        raw_list = ids_raw
    else:
        raw_list = [s.strip() for s in str(ids_raw).replace(";", ",").split(",") if s.strip()]
    supplier_ids = []
    for x in raw_list:
        try:
            supplier_ids.append(int(x))
        except Exception:
            continue
    supplier_ids = [sid for sid in supplier_ids if sid > 0]
    supplier_ids = list(dict.fromkeys(supplier_ids))
    if not supplier_ids:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"success": False, "message": "no_supplier_ids"}), 400
        flash("أدخل أرقام الموردين لتحديث الأرصدة.", "warning")
        return redirect(url_for("vendors_bp.suppliers_list"))

    try:
        from utils.supplier_balance_updater import update_supplier_balance_components
        from sqlalchemy.orm import sessionmaker
        SessionFactory = sessionmaker(bind=db.engine)
        session = SessionFactory()
        updated = 0
        try:
            for sid in supplier_ids:
                try:
                    update_supplier_balance_components(sid, session)
                    updated += 1
                except Exception:
                    continue
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"success": True, "updated": updated})
        flash(f"تم تحديث أرصدة {updated} مورد.", "success")
        return redirect(url_for("vendors_bp.suppliers_list"))
    except Exception as e:
        if request.accept_mimetypes.best == "application/json":
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
        flash("حدث خطأ أثناء تحديث أرصدة الموردين.", "danger")
        return redirect(url_for("vendors_bp.suppliers_list"))

@vendors_bp.route("/suppliers/new", methods=["GET", "POST"], endpoint="suppliers_create")
@login_required
def suppliers_create():
    form = SupplierForm()
    if form.validate_on_submit():
        supplier = Supplier()
        form.apply_to(supplier)
        db.session.add(supplier)
        try:
            db.session.commit()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
                return jsonify({"success": True, "id": supplier.id, "name": supplier.name})
            flash("✅ تم إضافة المورد بنجاح", "success")
            return redirect(url_for("vendors_bp.suppliers_list"))
        except SQLAlchemyError as e:
            db.session.rollback()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
                current_app.logger.exception('API error')
                return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
            flash(f"❌ خطأ أثناء إضافة المورد: {e}", "danger")
    else:
        if request.method == "POST":
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"خطأ في {field}: {error}", "danger")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
        html = render_template("vendors/suppliers/form.html", form=form, supplier=None)
        return jsonify({"success": True, "html": html})
    return render_template("vendors/suppliers/form.html", form=form, supplier=None)

@vendors_bp.route("/suppliers/<int:id>/edit", methods=["GET", "POST"], endpoint="suppliers_edit")
@login_required
def suppliers_edit(id):
    supplier = _get_or_404(Supplier, id)
    db.session.refresh(supplier)
    form = SupplierForm(obj=supplier)
    form.obj_id = supplier.id
    if form.validate_on_submit():
        form.apply_to(supplier)
        try:
            db.session.commit()
            flash("✅ تم تحديث المورد بنجاح", "success")
            return redirect(url_for("vendors_bp.suppliers_list"))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f"❌ خطأ أثناء تحديث المورد: {e}", "danger")
    return render_template("vendors/suppliers/form.html", form=form, supplier=supplier)


@vendors_bp.route("/suppliers/<int:id>/delete", methods=["POST"], endpoint="suppliers_delete")
@login_required
def suppliers_delete(id):
    supplier = _get_or_404(Supplier, id)

    w_count = db.session.query(Warehouse.id).filter(Warehouse.supplier_id == id).count()
    pay_count = db.session.query(Payment.id).filter(Payment.supplier_id == id).count()
    stl_count = db.session.query(SupplierLoanSettlement.id).filter(SupplierLoanSettlement.supplier_id == id).count()

    if any([w_count, pay_count, stl_count]):
        parts = []
        if w_count: parts.append(f"مستودعات مرتبطة: {w_count}")
        if pay_count: parts.append(f"دفعات مرتبطة: {pay_count}")
        if stl_count: parts.append(f"تسويات قروض: {stl_count}")
        flash("لا يمكن حذف المورد لوجود مراجع مرتبطة — " + "، ".join(parts), "danger")
        return redirect(url_for("vendors_bp.suppliers_list"))

    try:
        db.session.delete(supplier)
        db.session.commit()
        flash("تم حذف المورد بنجاح", "success")
    except IntegrityError:
        db.session.rollback()
        flash("لا يمكن حذف المورد لوجود بيانات مرتبطة به. الرجاء فك الارتباط أولًا.", "danger")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("تعذّر تنفيذ العملية. الرجاء المحاولة لاحقًا.", "danger")
    return redirect(url_for("vendors_bp.suppliers_list"))

# ⚠️ قبل التعديل: اقرأ ACCOUNTING_RULES.md - قواعد المحاسبة الأساسية
@vendors_bp.get("/suppliers/<int:supplier_id>/statement", endpoint="suppliers_statement")
@login_required
def suppliers_statement(supplier_id: int):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1"
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        if is_ajax:
            return jsonify({"success": False, "message": "not_found"}), 404
        abort(404)
    db.session.refresh(supplier)

    date_from_s = (request.args.get("from") or "").strip()
    date_to_s = (request.args.get("to") or "").strip()
    try:
        df = datetime.strptime(date_from_s, "%Y-%m-%d") if date_from_s else None
        dt = datetime.strptime(date_to_s, "%Y-%m-%d") if date_to_s else None
    except Exception:
        df, dt = None, None
    if dt:
        dt = dt + timedelta(days=1)

    tx_query = (
        db.session.query(ExchangeTransaction)
        .options(joinedload(ExchangeTransaction.product))
        .filter(
            ExchangeTransaction.supplier_id == supplier.id,
        )
    )
    if df:
        tx_query = tx_query.filter(ExchangeTransaction.created_at >= df)
    if dt:
        tx_query = tx_query.filter(ExchangeTransaction.created_at < dt)
    txs = tx_query.all()

    entries = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    per_product = {}
    returns_supply_total = Decimal("0.00")
    returns_supply_last_date = None

    def _pp(pid):
        if pid not in per_product:
            per_product[pid] = {
                "product": None,
                "qty_in": 0,
                "qty_out": 0,
                "qty_paid": 0,
                "qty_unpaid": 0,
                "val_in": Decimal("0.00"),
                "val_out": Decimal("0.00"),
                "val_paid": Decimal("0.00"),
                "val_unpaid": Decimal("0.00"),
                "notes": set(),
            }
        return per_product[pid]

    for tx in txs:
        p = tx.product
        pid = getattr(p, "id", None)
        row = _pp(pid)
        if row["product"] is None:
            row["product"] = p

        qty = int(tx.quantity or 0)
        unit_cost = D(getattr(tx, "unit_cost", 0))
        used_fallback = False
        if unit_cost <= 0:
            pc = getattr(p, "purchase_price", None)
            if pc and D(pc) > 0:
                unit_cost = D(pc)
                used_fallback = True
            else:
                unit_cost = Decimal("0")

        amount = q2(unit_cost) * q2(qty)
        
        tx_currency = getattr(tx, "currency", None) or getattr(p, "currency", None) or "ILS"
        if tx_currency and tx_currency != "ILS" and amount > 0:
            try:
                from models import convert_amount
                convert_date = getattr(tx, "created_at", None) or (df if df else supplier.created_at)
                amount = convert_amount(amount, tx_currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting exchange transaction #{tx.id} amount: {e}")
                except Exception:
                    pass
        
        if used_fallback:
            row["notes"].add("تم التسعير من سعر شراء المنتج")
        if unit_cost == 0:
            row["notes"].add("سعر غير متوفر – راجع التسعير")

        d = getattr(tx, "created_at", None)
        dirv = (getattr(tx, "direction", "") or "").upper()
        prod_name = getattr(p, 'name', 'منتج') if p else 'منتج'

        item_detail = {
            "product": prod_name,
            "qty": qty,
            "unit_cost": float(unit_cost),
            "total": float(amount),
            "direction": dirv,
            "tx_id": tx.id
        }
        
        if dirv in {"IN", "PURCHASE", "CONSIGN_IN"}:
            # توريد = حقوق المورد = دائن (credit) لأن الرصيد يصبح أكثر سالبية
            statement = f"توريد {prod_name} - كمية: {qty}"
            entries.append({
                "id": tx.id,
                "model": "exchange_transaction",
                "date": d, 
                "type": "PURCHASE", 
                "ref": f"توريد قطع #{tx.id}", 
                "statement": statement, 
                "debit": Decimal("0.00"), 
                "credit": amount,
                "details": [item_detail],
                "has_details": True
            })
            total_credit += amount
            row["qty_in"] += qty
            row["val_in"] += amount
        elif dirv in {"OUT", "RETURN", "CONSIGN_OUT"}:
            # مرتجع = يقلل حقوق المورد = مدين (debit) لأن الرصيد يصبح أقل سالبية
            statement = f"مرتجع {prod_name} - كمية: {qty}"
            entries.append({
                "id": tx.id,
                "model": "exchange_transaction",
                "date": d, 
                "type": "RETURN", 
                "ref": f"مرتجع قطع #{tx.id}", 
                "statement": statement, 
                "debit": amount, 
                "credit": Decimal("0.00"),
                "details": [item_detail],
                "has_details": True
            })
            total_debit += amount
            returns_supply_total += amount
            if d and (returns_supply_last_date is None or d > returns_supply_last_date):
                returns_supply_last_date = d
            row["qty_out"] += qty
            row["val_out"] += amount
        elif dirv in {"SETTLEMENT", "ADJUST"}:
            statement = f"تسوية مخزون {prod_name} - كمية: {qty}"
            entries.append({
                "id": tx.id,
                "model": "exchange_transaction",
                "date": d, 
                "type": "SETTLEMENT", 
                "ref": f"تسوية مخزون #{tx.id}", 
                "statement": statement, 
                "debit": Decimal("0.00"), 
                "credit": amount,
                "details": [item_detail],
                "has_details": True
            })
            total_credit += amount

    if returns_supply_total > 0:
        entries.append({
            "model": "return_supply_adjustment",
            "date": returns_supply_last_date,
            "type": "RETURN",
            "ref": "مرتجعات توريد (تسوية)",
            "statement": "تسوية مالية لمرتجعات التوريد",
            "debit": returns_supply_total,
            "credit": Decimal("0.00"),
        })
        total_debit += returns_supply_total

    # المبيعات للمورد (كعميل) — تُسجّل دائن (تُخفّض ما ندين به)
    sales_data = []
    if supplier.customer_id:
        from models import Sale, SaleStatus, SaleLine, Product
        sale_q = (
            db.session.query(Sale)
            .options(joinedload(Sale.lines).joinedload(SaleLine.product))
            .filter(
                Sale.customer_id == supplier.customer_id,
                Sale.status == SaleStatus.CONFIRMED.value,
            )
        )
        if df:
            sale_q = sale_q.filter(Sale.sale_date >= df)
        if dt:
            sale_q = sale_q.filter(Sale.sale_date < dt)
        
        for sale in sale_q.all():
            d = sale.sale_date
            amt = q2(sale.total_amount or 0)
            if sale.currency and sale.currency != "ILS" and amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else supplier.created_at)
                    amt = convert_amount(amt, sale.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting sale #{sale.id} amount: {e}")
                    except Exception:
                        pass
            ref = sale.sale_number or f"فاتورة #{sale.id}"
            
            # جمع بنود الفاتورة
            items = []
            for line in (sale.lines or []):
                prod_name = line.product.name if line.product else "منتج"
                items.append({
                    "product": prod_name,
                    "qty": line.quantity,
                    "price": float(line.unit_price or 0),
                    "total": float(q2(line.quantity * line.unit_price))
                })
            
            statement = f"مبيعات للمورد - {ref}"
            entries.append({
                "id": sale.id,
                "model": "sale",
                "date": d, 
                "type": "SALE", 
                "ref": ref, 
                "statement": statement, 
                "debit": amt, 
                "credit": Decimal("0.00"),
                "details": items,
                "has_details": len(items) > 0
            })
            total_debit += amt
            sales_data.append({"ref": ref, "date": d, "amount": amt, "items": items})
    
    # الصيانة للمورد (كعميل) — تُسجّل مدين
    services_data = []
    if supplier.customer_id:
        from models import ServiceRequest, ServicePart, ServiceTask
        service_q = (
            db.session.query(ServiceRequest)
            .options(joinedload(ServiceRequest.parts), joinedload(ServiceRequest.tasks))
            .filter(
                ServiceRequest.customer_id == supplier.customer_id,
                ServiceRequest.status == ServiceStatus.COMPLETED.value,
            )
        )
        if df:
            service_q = service_q.filter(ServiceRequest.received_at >= df)
        if dt:
            service_q = service_q.filter(ServiceRequest.received_at < dt)
        
        for service in service_q.all():
            d = service.received_at
            amt = q2(service.total_amount or 0)
            if service.currency and service.currency != "ILS" and amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else supplier.created_at)
                    amt = convert_amount(amt, service.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting service #{service.id} amount: {e}")
                    except Exception:
                        pass
            ref = service.service_number or f"صيانة #{service.id}"
            
            # جمع قطع الغيار والخدمات
            items = []
            for part in (service.parts or []):
                items.append({
                    "type": "قطعة",
                    "name": part.part.name if part.part else "قطعة غيار",
                    "qty": part.quantity,
                    "price": float(part.unit_price or 0),
                    "total": float(q2(part.quantity * part.unit_price))
                })
            for task in (service.tasks or []):
                items.append({
                    "type": "خدمة",
                    "name": task.description or "خدمة",
                    "qty": task.quantity or 1,
                    "price": float(task.unit_price or 0),
                    "total": float(q2((task.quantity or 1) * task.unit_price))
                })
            
            statement = f"صيانة للمورد - {ref}"
            entries.append({
                "id": service.id,
                "model": "service",
                "date": d, 
                "type": "SERVICE",  
                "ref": ref, 
                "statement": statement, 
                "debit": amt, 
                "credit": Decimal("0.00"),
                "details": items,
                "has_details": len(items) > 0
            })
            total_debit += amt
            services_data.append({"ref": ref, "date": d, "amount": amt, "items": items})
    
    preorders_data = []
    if supplier.customer_id:
        from models import PreOrder
        preorder_q = (
            db.session.query(PreOrder)
            .options(joinedload(PreOrder.product))
            .filter(
                PreOrder.customer_id == supplier.customer_id,
                PreOrder.status.in_(['CONFIRMED', 'COMPLETED']),
            )
        )
        if df:
            preorder_q = preorder_q.filter(PreOrder.preorder_date >= df)
        if dt:
            preorder_q = preorder_q.filter(PreOrder.preorder_date < dt)
        
        for preorder in preorder_q.all():
            d = preorder.preorder_date
            amt = q2(preorder.total_amount or 0)
            if preorder.currency and preorder.currency != "ILS" and amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else supplier.created_at)
                    amt = convert_amount(amt, preorder.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting preorder #{preorder.id} amount: {e}")
                    except Exception:
                        pass
            ref = f"حجز #{preorder.id}"
            prod_name = preorder.product.name if preorder.product else "منتج"
            
            items = [{
                "product": prod_name,
                "qty": preorder.quantity,
                "price": float(preorder.unit_price or 0),
                "total": float(amt)
            }]
            
            statement = f"حجز مسبق للمورد - {ref}"
            entries.append({
                "id": preorder.id,
                "model": "preorder",
                "date": d, 
                "type": "PREORDER", 
                "ref": ref, 
                "statement": statement, 
                "debit": amt, 
                "credit": Decimal("0.00"),
                "details": items,
                "has_details": True
            })
            total_debit += amt
            preorders_data.append({"ref": ref, "date": d, "amount": amt, "items": items})
        
        prepaid_preorders = db.session.query(PreOrder).filter(
            PreOrder.customer_id == supplier.customer_id,
            PreOrder.prepaid_amount > 0,
            PreOrder.status != 'FULFILLED',
        )
        if df:
            prepaid_preorders = prepaid_preorders.filter(PreOrder.preorder_date >= df)
        if dt:
            prepaid_preorders = prepaid_preorders.filter(PreOrder.preorder_date < dt)
        
        for preorder in prepaid_preorders.all():
            d = preorder.preorder_date
            prepaid_amt = q2(preorder.prepaid_amount or 0)
            if preorder.currency and preorder.currency != "ILS" and prepaid_amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else supplier.created_at)
                    prepaid_amt = convert_amount(prepaid_amt, preorder.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting preorder prepaid #{preorder.id} amount: {e}")
                    except Exception:
                        pass
            ref_prepaid = f"عربون حجز #{preorder.id}"
            prod_name = preorder.product.name if preorder.product else "منتج"
            
            items_prepaid = [{
                "product": prod_name,
                "qty": preorder.quantity,
                "prepaid": float(prepaid_amt),
                "total": float(prepaid_amt)
            }]
            
            statement_prepaid = f"عربون حجز مسبق - {ref_prepaid}"
            entries.append({
                "id": preorder.id,
                "model": "preorder",
                "date": d, 
                "type": "PREPAID", 
                "ref": ref_prepaid, 
                "statement": statement_prepaid, 
                "debit": Decimal("0.00"), 
                "credit": prepaid_amt,
                "details": items_prepaid,
                "has_details": True
            })
            total_credit += prepaid_amt
        
        from models import SaleReturn, SaleReturnLine, SaleStatus
        sale_returns_q = db.session.query(SaleReturn).filter(
            SaleReturn.customer_id == supplier.customer_id,
            SaleReturn.status == SaleStatus.CONFIRMED.value,
        )
        if df:
            sale_returns_q = sale_returns_q.filter(SaleReturn.created_at >= df)
        if dt:
            sale_returns_q = sale_returns_q.filter(SaleReturn.created_at < dt)
        
        for sale_return in sale_returns_q.all():
            d = sale_return.created_at
            amt = q2(sale_return.total_amount or 0)
            if sale_return.currency and sale_return.currency != "ILS" and amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else supplier.created_at)
                    amt = convert_amount(amt, sale_return.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting sale return #{sale_return.id} amount: {e}")
                    except Exception:
                        pass
            
            items_return = []
            for return_line in (sale_return.lines or []):
                prod_name = return_line.product.name if return_line.product else "منتج"
                items_return.append({
                    "product": prod_name,
                    "qty": return_line.quantity,
                    "price": float(return_line.unit_price or 0),
                    "total": float(q2(return_line.quantity * return_line.unit_price)),
                    "condition": return_line.condition
                })
            
            ref_return = f"مرتجع #{sale_return.id}"
            statement_return = f"مرتجع مبيعات للمورد - {ref_return}"
            entries.append({
                "id": sale_return.id,
                "model": "sale_return",
                "date": d, 
                "type": "SALE_RETURN", 
                "ref": ref_return, 
                "statement": statement_return, 
                "debit": Decimal("0.00"), 
                "credit": amt,
                "details": items_return,
                "has_details": len(items_return) > 0,
                "notes": sale_return.reason or sale_return.notes or ''
            })
            total_credit += amt

    from models import Check, CheckStatus
    pay_q = (
        db.session.query(Payment)
        .options(joinedload(Payment.related_check), joinedload(Payment.splits))
        .filter(
            Payment.supplier_id == supplier.id,
            Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value, PaymentStatus.REFUNDED.value]),
        )
    )
    if df:
        pay_q = pay_q.filter(Payment.payment_date >= df)
    if dt:
        pay_q = pay_q.filter(Payment.payment_date < dt        )
    direct_payments = pay_q.all()
    
    expense_pay_q = (
        db.session.query(Payment)
        .options(joinedload(Payment.related_check), joinedload(Payment.splits))
        .join(Expense, Payment.expense_id == Expense.id)
        .filter(
            or_(
                Expense.supplier_id == supplier.id,
                and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier.id)
            ),
            Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value, PaymentStatus.REFUNDED.value]),
        )
    )
    if df:
        expense_pay_q = expense_pay_q.filter(Payment.payment_date >= df)
    if dt:
        expense_pay_q = expense_pay_q.filter(Payment.payment_date < dt)
    expense_payments = expense_pay_q.all()
    
    customer_payments = []
    if supplier.customer_id:
        from models import Sale, Invoice, ServiceRequest, PreOrder
        customer_pay_q = (
            db.session.query(Payment)
            .outerjoin(Sale, Payment.sale_id == Sale.id)
            .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
            .outerjoin(ServiceRequest, Payment.service_id == ServiceRequest.id)
            .outerjoin(PreOrder, Payment.preorder_id == PreOrder.id)
            .outerjoin(Expense, Payment.expense_id == Expense.id)
            .options(joinedload(Payment.related_check), joinedload(Payment.splits))
            .filter(
                Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value, PaymentStatus.REFUNDED.value]),
                or_(
                    Payment.customer_id == supplier.customer_id,
                    Sale.customer_id == supplier.customer_id,
                    Invoice.customer_id == supplier.customer_id,
                    ServiceRequest.customer_id == supplier.customer_id,
                    PreOrder.customer_id == supplier.customer_id,
                    Expense.customer_id == supplier.customer_id,
                ),
                or_(
                    Payment.preorder_id.is_(None),
                    Payment.sale_id.isnot(None),
                    PreOrder.status == 'FULFILLED',
                ),
            )
        )
        if df:
            customer_pay_q = customer_pay_q.filter(Payment.payment_date >= df)
        if dt:
            customer_pay_q = customer_pay_q.filter(Payment.payment_date < dt)
        customer_payments = customer_pay_q.distinct().all()
    
    payment_ids = set()
    all_payments = []
    for p in direct_payments + expense_payments + customer_payments:
        if p.id not in payment_ids:
            payment_ids.add(p.id)
            all_payments.append(p)
    
    for pmt in all_payments:
        d = pmt.payment_date
        amt = q2(pmt.total_amount)
        if pmt.currency and pmt.currency != "ILS" and amt > 0:
            try:
                from models import convert_amount
                convert_date = d if d else (df if df else supplier.created_at)
                amt = convert_amount(amt, pmt.currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting payment #{pmt.id} amount: {e}")
                except Exception:
                    pass
        ref = pmt.reference or f"دفعة #{pmt.id}"
        
        payment_status_val = getattr(pmt, 'status', 'COMPLETED')
        if hasattr(payment_status_val, 'value'):
            payment_status_val = payment_status_val.value
        payment_status = str(payment_status_val or 'COMPLETED').upper()
        is_bounced = payment_status in ['BOUNCED', 'FAILED', 'REJECTED', 'RETURNED']
        is_pending = payment_status == 'PENDING'
        is_cancelled = payment_status == 'CANCELLED'
        is_refunded = payment_status == 'REFUNDED'
        
        related_check = getattr(pmt, 'related_check', None)
        check_status = None
        check_notes = ''
        is_check_settled = False
        is_check_legal = False
        is_check_resubmitted = False
        is_check_archived = False
        
        if related_check:
            check_status = getattr(related_check, 'status', None)
            check_notes = getattr(related_check, 'notes', '') or ''
            internal_notes = getattr(related_check, 'internal_notes', '') or ''
            all_check_notes = (check_notes + ' ' + internal_notes).lower()
            
            is_check_settled = '[SETTLED=true]' in all_check_notes or 'مسوى' in all_check_notes or 'تم التسوية' in all_check_notes
            is_check_legal = 'دائرة قانونية' in all_check_notes or 'محول للدوائر القانونية' in all_check_notes or 'قانوني' in all_check_notes
            is_check_resubmitted = check_status == CheckStatus.RESUBMITTED.value or 'أعيد للبنك' in all_check_notes or 'معاد للبنك' in all_check_notes
            is_check_archived = check_status == CheckStatus.ARCHIVED.value or 'مؤرشف' in all_check_notes
        
        payment_notes_lower = (getattr(pmt, 'notes', '') or '').lower()
        if not is_check_settled:
            is_check_settled = '[SETTLED=true]' in payment_notes_lower or 'مسوى' in payment_notes_lower
        if not is_check_legal:
            is_check_legal = 'دائرة قانونية' in payment_notes_lower or 'محول للدوائر القانونية' in payment_notes_lower
        
        method_map = {
            'cash': 'نقداً',
            'card': 'بطاقة',
            'cheque': 'شيك',
            'bank': 'تحويل بنكي',
            'online': 'إلكتروني',
        }
        method_value = getattr(pmt, 'method', 'cash')
        if hasattr(method_value, 'value'):
            method_value = method_value.value
        method_raw = str(method_value).lower()
        
        split_details = []
        splits = list(getattr(pmt, 'splits', []) or [])
        if splits:
            unique_methods = set()
            for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                split_method_val = getattr(split, "method", None)
                if hasattr(split_method_val, "value"):
                    split_method_val = split_method_val.value
                split_method_raw = str(split_method_val or "").lower()
                if not split_method_raw:
                    split_method_raw = method_raw or "cash"
                unique_methods.add(split_method_raw)
                split_currency = (getattr(split, "currency", None) or getattr(pmt, "currency", "ILS") or "ILS").upper()
                converted_currency = (getattr(split, "converted_currency", None) or getattr(pmt, "currency", "ILS") or "ILS").upper()
                split_details.append({
                    "method": method_map.get(split_method_raw, split_method_raw),
                    "method_raw": split_method_raw,
                    "amount": D(getattr(split, "amount", 0) or 0),
                    "currency": split_currency,
                    "fx_rate": getattr(split, "fx_rate_used", None),
                    "fx_rate_source": getattr(split, "fx_rate_source", None),
                    "converted_amount": D(getattr(split, "converted_amount", 0) or 0),
                    "converted_currency": converted_currency,
                })
            if unique_methods:
                if len(unique_methods) == 1:
                    method_raw = next(iter(unique_methods))
                else:
                    method_raw = "mixed"
        
        method_arabic = method_map.get(method_raw, "طرق متعددة" if method_raw == "mixed" else method_raw)
        method_display = "طرق متعددة" if method_raw == "mixed" else method_arabic
        
        check_number = getattr(pmt, 'check_number', None)
        check_bank = getattr(pmt, 'check_bank', None)
        check_due_date = getattr(pmt, 'check_due_date', None)
        
        if related_check and method_raw == 'cheque':
            if not check_number:
                check_number = getattr(related_check, 'check_number', None)
            if not check_bank:
                check_bank = getattr(related_check, 'check_bank', None)
            if not check_due_date:
                check_due_date = getattr(related_check, 'check_due_date', None)
        
        payment_details = {
            'method': method_display,
            'method_raw': method_raw,
            'check_number': check_number if method_raw == 'cheque' else None,
            'check_bank': check_bank,
            'check_due_date': check_due_date if method_raw == 'cheque' else None,
            'check_status': check_status,
            'check_notes': check_notes,
            'is_check_settled': is_check_settled,
            'is_check_legal': is_check_legal,
            'is_check_resubmitted': is_check_resubmitted,
            'is_check_archived': is_check_archived,
            'deliverer_name': getattr(pmt, 'deliverer_name', None) or '',
            'receiver_name': getattr(pmt, 'receiver_name', None) or '',
            'status': payment_status,
            'is_bounced': is_bounced,
            'is_pending': is_pending,
            'is_cancelled': is_cancelled,
            'is_refunded': is_refunded,
            'splits': split_details,
        }
        
        notes = getattr(pmt, 'notes', '') or ''
        direction_value = pmt.direction.value if hasattr(pmt.direction, 'value') else str(pmt.direction)
        is_out = direction_value == 'OUT'
        
        if method_raw == 'cheque':
            if is_check_legal:
                if is_out:
                    statement = f"⚖️ شيك محول للدوائر القانونية - {method_arabic} للمورد"
                else:
                    statement = f"⚖️ شيك محول للدوائر القانونية - {method_arabic} من المورد"
            elif is_check_settled:
                if is_out:
                    statement = f"✅ شيك مسوى - {method_arabic} للمورد"
                else:
                    statement = f"✅ شيك مسوى - {method_arabic} من المورد"
            elif is_check_resubmitted:
                if is_out:
                    statement = f"🔄 شيك معاد للبنك - {method_arabic} للمورد"
                else:
                    statement = f"🔄 شيك معاد للبنك - {method_arabic} من المورد"
            elif is_check_archived:
                if is_out:
                    statement = f"📦 شيك مؤرشف - {method_arabic} للمورد"
                else:
                    statement = f"📦 شيك مؤرشف - {method_arabic} من المورد"
            elif is_bounced:
                if payment_status == 'RETURNED':
                    statement = f"↩️ شيك مرتجع - {method_arabic} {'للمورد' if is_out else 'من المورد'}"
                else:
                    statement = f"❌ شيك مرفوض - {method_arabic} {'للمورد' if is_out else 'من المورد'}"
            elif is_pending:
                statement = f"⏳ شيك معلق - {method_arabic} {'للمورد' if is_out else 'من المورد'}"
            elif check_status == CheckStatus.CASHED.value:
                if is_out:
                    statement = f"✅ شيك تم صرفه - {method_arabic} للمورد"
                else:
                    statement = f"✅ شيك تم صرفه - {method_arabic} من المورد"
            elif is_cancelled:
                if is_out:
                    statement = f"🚫 شيك ملغي - {method_arabic} للمورد"
                else:
                    statement = f"🚫 شيك ملغي - {method_arabic} من المورد"
            else:
                if is_out:
                    statement = f"سداد {method_arabic} للمورد"
                else:
                    statement = f"قبض {method_arabic} من المورد"
        else:
            if is_out:
                if is_bounced:
                    if payment_status == 'RETURNED':
                        statement = f"↩️ شيك مرتجع - {method_arabic} للمورد"
                    else:
                        statement = f"❌ شيك مرفوض - {method_arabic} للمورد"
                elif is_pending:
                    statement = f"⏳ شيك معلق - {method_arabic} للمورد"
                else:
                    statement = f"سداد {method_arabic} للمورد"
            else:
                if is_bounced:
                    if payment_status == 'RETURNED':
                        statement = f"↩️ شيك مرتجع - {method_arabic} من المورد"
                    else:
                        statement = f"❌ شيك مرفوض - {method_arabic} من المورد"
                elif is_pending:
                    statement = f"⏳ شيك معلق - {method_arabic} من المورد"
                else:
                    statement = f"قبض {method_arabic} من المورد"
        
        if notes:
            statement += f" - {notes[:30]}"
        
        if method_raw == 'cheque':
            if is_check_legal:
                entry_type = "CHECK_LEGAL"
            elif is_check_settled:
                entry_type = "CHECK_SETTLED"
            elif is_check_resubmitted:
                entry_type = "CHECK_RESUBMITTED"
            elif is_check_archived:
                entry_type = "CHECK_ARCHIVED"
            elif is_bounced:
                entry_type = "CHECK_BOUNCED"
            elif is_pending:
                entry_type = "CHECK_PENDING"
            elif check_status == CheckStatus.CASHED.value:
                entry_type = "CHECK_CASHED"
            elif is_cancelled:
                entry_type = "CHECK_CANCELLED"
            else:
                entry_type = "PAYMENT"
        else:
            entry_type = "CHECK_BOUNCED" if is_bounced else ("CHECK_PENDING" if is_pending and method_raw == 'cheque' else "PAYMENT")
        
        # ✅ إذا كانت الدفعة لديها splits، نعرض كل split كدفعة منفصلة
        if splits and len(splits) > 0:
            # عرض كل split كدفعة منفصلة
            for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                split_method_val = getattr(split, "method", None)
                if hasattr(split_method_val, "value"):
                    split_method_val = split_method_val.value
                split_method_raw = str(split_method_val or "").lower()
                if not split_method_raw:
                    split_method_raw = method_raw or "cash"
                
                split_currency = (getattr(split, "currency", None) or getattr(pmt, "currency", "ILS") or "ILS").upper()
                converted_currency = (getattr(split, "converted_currency", None) or getattr(pmt, "currency", "ILS") or "ILS").upper()
                
                # حساب المبلغ بالـ ILS
                split_amount = D(getattr(split, "amount", 0) or 0)
                split_converted_amount = D(getattr(split, "converted_amount", 0) or 0)
                
                # استخدام المبلغ المحول إذا كان موجوداً
                if split_converted_amount > 0 and converted_currency == "ILS":
                    split_amount_ils = split_converted_amount
                else:
                    split_amount_ils = split_amount
                    if split_currency != "ILS":
                        try:
                            from models import convert_amount
                            split_amount_ils = convert_amount(split_amount, split_currency, "ILS", pmt.payment_date or df)
                        except:
                            pass
                
                # تحديد طريقة الدفع للـ split
                split_method_arabic = method_map.get(split_method_raw, split_method_raw)
                
                # فحص إذا كان Split لديها شيك مرتبط
                split_check = None
                if 'check' in split_method_raw or 'cheque' in split_method_raw:
                    from models import Check
                    split_checks = Check.query.filter(
                        or_(
                            Check.reference_number == f"PMT-SPLIT-{split.id}",
                            Check.reference_number.like(f"PMT-SPLIT-{split.id}-%")
                        )
                    ).all()
                    if split_checks:
                        split_check = split_checks[0]
                
                # تحديد حالة Split
                split_is_bounced = False
                split_is_pending = False
                split_has_cashed = False
                split_has_returned = False
                split_check_status = None
                
                if split_check:
                    split_check_status = str(getattr(split_check, 'status', 'PENDING') or 'PENDING').upper()
                    split_is_bounced = split_check_status in ['RETURNED', 'BOUNCED']
                    split_is_pending = split_check_status == 'PENDING' and not split_is_bounced
                    split_has_cashed = split_check_status == 'CASHED'
                    split_has_returned = split_check_status in ['RETURNED', 'BOUNCED']
                
                # إنشاء البيان للـ split
                if split_has_returned:
                    split_statement = f"إرجاع شيك"
                    if split_check and split_check.check_number:
                        split_statement += f" #{split_check.check_number}"
                    if split_check and split_check.check_bank:
                        split_statement += f" - {split_check.check_bank}"
                    split_entry_type = "CHECK_RETURNED"
                elif split_is_pending and ('check' in split_method_raw or 'cheque' in split_method_raw):
                    split_statement = f"⏳ شيك معلق - {split_method_arabic} {'للمورد' if is_out else 'من المورد'}"
                    if split_check and split_check.check_number:
                        split_statement += f" #{split_check.check_number}"
                    split_entry_type = "CHECK_PENDING"
                elif split_has_cashed:
                    split_statement = f"✅ شيك مسحوب - {split_method_arabic} {'للمورد' if is_out else 'من المورد'}"
                    if split_check and split_check.check_number:
                        split_statement += f" #{split_check.check_number}"
                    split_entry_type = "CHECK_CASHED"
                else:
                    split_statement = f"{'سداد' if is_out else 'قبض'} {split_method_arabic} {'للمورد' if is_out else 'من المورد'}"
                    split_entry_type = "PAYMENT"
                
                if notes:
                    split_statement += f" - {notes[:30]}"
                
                split_is_in = not is_out
                if is_cancelled or is_refunded:
                    split_debit = D(0)
                    split_credit = D(0)
                elif split_has_returned:
                    split_debit = split_amount_ils if not is_out else D(0)
                    split_credit = split_amount_ils if is_out else D(0)
                else:
                    split_debit = split_amount_ils if is_out else D(0)
                    split_credit = split_amount_ils if split_is_in else D(0)
                
                # إنشاء payment_details للـ split
                split_payment_details = {
                    'method': split_method_arabic,
                    'method_raw': split_method_raw,
                    'check_number': split_check.check_number if split_check else None,
                    'check_bank': split_check.check_bank if split_check else None,
                    'check_due_date': split_check.check_due_date if split_check else None,
                    'deliverer_name': getattr(pmt, 'deliverer_name', None) or '',
                    'receiver_name': getattr(pmt, 'receiver_name', None) or '',
                    'status': split_check_status if split_check_status else payment_status,
                    'is_bounced': split_is_bounced,
                    'is_pending': split_is_pending,
                    'is_cashed': split_has_cashed,
                    'is_returned': split_has_returned,
                    'is_refunded': is_refunded,
                    'splits': [],
                    'all_checks': [{
                        'check_number': split_check.check_number,
                        'check_bank': split_check.check_bank,
                        'check_due_date': split_check.check_due_date,
                        'status': split_check_status,
                        'amount': float(split_check.amount or 0),
                        'currency': split_check.currency or 'ILS',
                    }] if split_check else [],
                }
                
                # إضافة الـ split كدفعة منفصلة
                entries.append({
                    "id": pmt.id,
                    "model": "payment",
                    "date": d,
                    "type": split_entry_type,
                    "ref": f"SPLIT-{split.id}-PMT-{pmt.id}",
                    "statement": split_statement,
                    "debit": split_debit,
                    "credit": split_credit,
                    "payment_details": split_payment_details,
                    "notes": notes
                })
                
                total_debit += split_debit
                total_credit += split_credit
                
                if split_has_returned and split_check:
                    returned_statement = f"إرجاع شيك"
                    if split_check.check_number:
                        returned_statement += f" #{split_check.check_number}"
                    if split_check.check_bank:
                        returned_statement += f" - {split_check.check_bank}"
                    
                    returned_check_amt = D(0)
                    
                    if is_out:
                        returned_debit = D(0)
                        returned_credit = returned_check_amt
                    else:
                        returned_debit = returned_check_amt
                        returned_credit = D(0)
                    
                    entries.append({
                        "id": getattr(split_check, 'id', None) if split_check else None,
                        "model": "check",
                        "date": (split_check.check_date if split_check else None) or d,
                        "type": "CHECK_RETURNED",
                        "ref": f"SPLIT-RETURN-{split.id}-CHK-{getattr(split_check, 'id', 'NA')}",
                        "statement": returned_statement,
                        "debit": returned_debit,
                        "credit": returned_credit,
                        "payment_details": {
                            'method': 'شيك',
                            'method_raw': 'cheque',
                            'check_number': split_check.check_number,
                            'check_bank': split_check.check_bank,
                            'check_due_date': split_check.check_due_date,
                            'status': str(getattr(split_check, 'status', 'RETURNED')),
                            'is_bounced': True,
                            'is_returned': True,
                        },
                        "notes": notes,
                    })
                    
                    total_debit += returned_debit
                    total_credit += returned_credit
        else:
            if is_cancelled or is_refunded:
                debit_val = Decimal("0.00")
                credit_val = Decimal("0.00")
            elif is_bounced:
                debit_val = amt if not is_out else Decimal("0.00")
                credit_val = amt if is_out else Decimal("0.00")
            else:
                debit_val = amt if is_out else Decimal("0.00")
                credit_val = Decimal("0.00") if is_out else amt
            
            entries.append({
                "id": pmt.id,
                "model": "payment",
                "date": d,
                "type": entry_type,
                "ref": ref,
                "statement": statement,
                "debit": debit_val,
                "credit": credit_val,
                "payment_details": payment_details,
                "notes": notes
            })
            
            total_debit += debit_val
            total_credit += credit_val
            
            if is_bounced:
                returned_checks = Check.query.filter(
                    Check.payment_id == pmt.id,
                    Check.status.in_(['RETURNED', 'BOUNCED'])
                ).all()
                
                for check in returned_checks:
                    check_amt = D(check.amount or 0)
                    if check.currency and check.currency != "ILS":
                        try:
                            from models import convert_amount
                            check_amt = convert_amount(check_amt, check.currency, "ILS", check.check_date or d)
                        except:
                            pass
                    
                    returned_statement = f"إرجاع شيك"
                    if check.check_number:
                        returned_statement += f" #{check.check_number}"
                    if check.check_bank:
                        returned_statement += f" - {check.check_bank}"
                    
                    returned_debit = D(0)
                    returned_credit = D(0)
                    
                    entries.append({
                        "id": check.id,
                        "model": "check",
                        "date": check.check_date or d,
                        "type": "CHECK_RETURNED",
                        "ref": f"CHK-{check.id}",
                        "statement": returned_statement,
                        "debit": returned_debit,
                        "credit": returned_credit,
                        "payment_details": {
                            'method': 'شيك',
                            'method_raw': 'cheque',
                            'check_number': check.check_number,
                            'check_bank': check.check_bank,
                            'check_due_date': check.check_due_date,
                            'status': str(getattr(check, 'status', 'RETURNED')),
                            'is_bounced': True,
                            'is_returned': True,
                        },
                        "notes": check.notes or notes or '',
                    })
                    
                    total_debit += returned_debit
                    total_credit += returned_credit

    stl_q = (
        db.session.query(SupplierLoanSettlement)
        .options(joinedload(SupplierLoanSettlement.loan))
        .filter(SupplierLoanSettlement.supplier_id == supplier.id)
    )
    if df:
        stl_q = stl_q.filter(SupplierLoanSettlement.settlement_date >= df)
    if dt:
        stl_q = stl_q.filter(SupplierLoanSettlement.settlement_date < dt)

    for s in stl_q.all():
        d = s.settlement_date
        amt = q2(s.settled_price)
        
        settlement_currency = getattr(s, "currency", None) or getattr(supplier, "currency", None) or "ILS"
        if settlement_currency and settlement_currency != "ILS" and amt > 0:
            try:
                from models import convert_amount
                convert_date = d if d else (df if df else supplier.created_at)
                amt = convert_amount(amt, settlement_currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting loan settlement #{s.id} amount: {e}")
                except Exception:
                    pass
        
        ref = f"تسوية قرض #{s.loan_id or s.id}"
        loan = getattr(s, "loan", None)
        statement = "تسوية قرض مع المورد"
        if loan:
            product = getattr(loan, "product", None)
            if product:
                statement = f"تسوية قرض - {product.name}"
        entries.append({
            "id": s.id,
            "model": "supplier_loan_settlement",
            "date": d, 
            "type": "SETTLEMENT", 
            "ref": ref, 
            "statement": statement, 
            "debit": Decimal("0.00"), 
            "credit": amt
        })
        total_credit += amt
        pid = getattr(getattr(s, "loan", None), "product_id", None)
        if pid in per_product:
            per_product[pid]["qty_paid"] += 1
            per_product[pid]["val_paid"] += amt

    expense_q = Expense.query.filter(
        or_(
            Expense.supplier_id == supplier.id,
            and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier.id)
        )
    )
    if df:
        expense_q = expense_q.filter(Expense.date >= df)
    if dt:
        expense_q = expense_q.filter(Expense.date < dt)
    
    for exp in expense_q.all():
        d = exp.date
        amt = q2(exp.amount or 0)
        
        if exp.currency and exp.currency != "ILS" and amt > 0:
            try:
                from models import convert_amount
                convert_date = d if d else (df if df else supplier.created_at)
                amt = convert_amount(amt, exp.currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting expense #{exp.id} amount: {e}")
                except Exception:
                    pass
        
        exp_type_code = ""
        if exp.type_id:
            from models import ExpenseType
            exp_type = db.session.get(ExpenseType, exp.type_id)
            if exp_type:
                exp_type_code = (exp_type.code or "").upper()
        
        is_supplier_service = exp_type_code in ["PARTNER_EXPENSE", "SUPPLIER_EXPENSE"]
        
        exp_type_name = getattr(getattr(exp, 'type', None), 'name', 'مصروف')
        ref = f"مصروف #{exp.id}"
        statement = f"{'توريد خدمة' if is_supplier_service else 'مصروف'}: {exp_type_name}"
        if exp.description:
            statement += f" - {exp.description}"
        
        if is_supplier_service:
            # توريد خدمة = حقوق المورد = دائن (credit) لأن الرصيد يصبح أكثر سالبية
            entries.append({
                "id": exp.id,
                "model": "expense",
                "date": d,
                "type": "EXPENSE",
                "ref": ref,
                "statement": statement,
                "debit": Decimal("0.00"),
                "credit": amt
            })
            total_credit += amt
        else:
            # مصروف عادي = دفعنا له = مدين (debit) لأن الرصيد يصبح أقل سالبية
            entries.append({
                "id": exp.id,
                "model": "expense",
                "date": d,
                "type": "EXPENSE",
                "ref": ref,
                "statement": statement,
                "debit": amt,
                "credit": Decimal("0.00")
            })
            total_debit += amt

    manual_checks = db.session.query(Check).filter(
        Check.payment_id.is_(None),
        Check.supplier_id == supplier.id,
        ~Check.status.in_([CheckStatus.CANCELLED.value, CheckStatus.ARCHIVED.value])
    )
    if df:
        manual_checks = manual_checks.filter(Check.check_date >= df)
    if dt:
        manual_checks = manual_checks.filter(Check.check_date < dt)
    
    for check in manual_checks.all():
        d = check.check_date
        amt = q2(check.amount or 0)
        if check.currency and check.currency != "ILS" and amt > 0:
            try:
                from models import convert_amount
                convert_date = d if d else (df if df else supplier.created_at)
                amt = convert_amount(amt, check.currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting check #{check.id} amount: {e}")
                except Exception:
                    pass
        
        direction_value = check.direction.value if hasattr(check.direction, 'value') else str(check.direction)
        is_out = direction_value == 'OUT'
        check_status = check.status.value if hasattr(check.status, 'value') else str(check.status)
        
        ref = f"شيك #{check.check_number}"
        check_bank = check.check_bank or ''
        check_due_date = check.check_due_date.strftime('%Y-%m-%d') if check.check_due_date else ''
        
        if check_status == CheckStatus.RETURNED.value or check_status == CheckStatus.BOUNCED.value:
            if is_out:
                statement = f"↩️ شيك مرتجع - {check_bank} - {ref}"
                entry_type = "CHECK_BOUNCED"
            else:
                statement = f"↩️ شيك مرتجع - {check_bank} - {ref}"
                entry_type = "CHECK_BOUNCED"
        elif check_status == CheckStatus.PENDING.value:
            statement = f"⏳ شيك معلق - {check_bank} - {ref}"
            entry_type = "CHECK_PENDING"
        elif check_status == CheckStatus.CASHED.value:
            if is_out:
                statement = f"✅ شيك تم صرفه - {check_bank} - {ref}"
            else:
                statement = f"✅ شيك تم صرفه - {check_bank} - {ref}"
            entry_type = "CHECK_CASHED"
        elif check_status == CheckStatus.RESUBMITTED.value:
            statement = f"🔄 شيك معاد للبنك - {check_bank} - {ref}"
            entry_type = "CHECK_RESUBMITTED"
        elif check_status == CheckStatus.ARCHIVED.value:
            statement = f"📦 شيك مؤرشف - {check_bank} - {ref}"
            entry_type = "CHECK_ARCHIVED"
        else:
            if is_out:
                statement = f"شيك صادر - {check_bank} - {ref}"
            else:
                statement = f"شيك وارد - {check_bank} - {ref}"
            entry_type = "CHECK_PENDING" if check_status == CheckStatus.PENDING.value else "PAYMENT"
        
        payment_details = {
            'method': 'شيك',
            'method_raw': 'cheque',
            'check_number': check.check_number,
            'check_bank': check_bank,
            'check_due_date': check_due_date,
            'check_status': check_status,
            'is_check_settled': False,
            'is_check_legal': False,
            'is_check_resubmitted': check_status == CheckStatus.RESUBMITTED.value,
            'is_check_archived': check_status == CheckStatus.ARCHIVED.value,
            'check_notes': check.notes or ''
        }
        
        if is_out:
            entries.append({
                "date": d,
                "type": entry_type,
                "ref": ref,
                "statement": statement,
                "debit": amt,
                "credit": Decimal("0.00"),
                "payment_details": payment_details,
                "notes": check.notes or ''
            })
            total_debit += amt
        else:
            entries.append({
                "date": d,
                "type": entry_type,
                "ref": ref,
                "statement": statement,
                "debit": Decimal("0.00"),
                "credit": amt,
                "payment_details": payment_details,
                "notes": check.notes or ''
            })
            total_credit += amt

    opening_balance = Decimal(getattr(supplier, 'opening_balance', 0) or 0)
    if opening_balance != 0 and supplier.currency and supplier.currency != "ILS":
        try:
            from models import convert_amount
            convert_date = df if df else supplier.created_at
            opening_balance = convert_amount(opening_balance, supplier.currency, "ILS", convert_date)
        except Exception as e:
            try:
                from flask import current_app
                current_app.logger.error(f"Error converting supplier #{supplier.id} opening balance: {e}")
            except Exception:
                pass
    
    opening_balance_for_period = Decimal("0.00")
    if df:
        base_date = datetime(2024, 1, 1)
        if df <= base_date:
            opening_balance_for_period = opening_balance
        else:
            from routes.supplier_settlements import _calculate_smart_supplier_balance
            balance_before_period = _calculate_smart_supplier_balance(
                supplier_id,
                base_date,
                df - timedelta(days=1)
            )
            if balance_before_period.get('success'):
                opening_balance_for_period = Decimal(str(balance_before_period.get('balance', {}).get('amount', 0)))
            else:
                opening_balance_for_period = Decimal(str(supplier.opening_balance or 0))
                if supplier.currency and supplier.currency != "ILS":
                    try:
                        from models import convert_amount
                        convert_date = df if df else supplier.created_at
                        opening_balance_for_period = convert_amount(opening_balance_for_period, supplier.currency, "ILS", convert_date)
                    except Exception:
                        pass
    else:
        opening_balance_for_period = Decimal(str(supplier.opening_balance or 0))
        if supplier.currency and supplier.currency != "ILS":
            try:
                from models import convert_amount
                opening_balance_for_period = convert_amount(opening_balance_for_period, supplier.currency, "ILS", supplier.created_at)
            except Exception:
                pass
    
    balance_to_use = opening_balance_for_period if df else opening_balance
    
    opening_entry = None
    if balance_to_use != 0:
        opening_date = supplier.created_at
        if entries:
            valid_dates = [e["date"] for e in entries if e.get("date")]
            if valid_dates:
                first_entry_date = min(valid_dates)
            if first_entry_date and first_entry_date < supplier.created_at:
                    opening_date = first_entry_date - timedelta(days=1)
        
        opening_entry = {
            "model": "opening_balance",
            "date": opening_date,
            "type": "OPENING_BALANCE",
            "ref": "OB-SUP-000",
            "statement": "الرصيد الافتتاحي",
            "debit": abs(balance_to_use) if balance_to_use < 0 else Decimal("0.00"),
            "credit": abs(balance_to_use) if balance_to_use > 0 else Decimal("0.00"),
        }
        if balance_to_use > 0:
            total_credit += abs(balance_to_use)
        else:
            total_debit += abs(balance_to_use)

    def _sort_key(e):
        entry_date = e.get("date")
        if entry_date is not None and not isinstance(entry_date, datetime):
            try:
                entry_date = datetime.combine(entry_date, datetime.min.time())
            except Exception:
                entry_date = None
        if isinstance(entry_date, datetime) and entry_date.tzinfo is not None:
            entry_date = entry_date.replace(tzinfo=None)
        if entry_date is None:
            return (datetime.max, 999, e.get("ref", ""))
        entry_type = e.get("type", "")
        type_priority = {
            "OPENING_BALANCE": 0,
            "PURCHASE": 1,
            "RETURN": 2,
            "EXPENSE": 3,
            "PAYMENT": 4,
            "CHECK_PENDING": 5,
            "CHECK_BOUNCED": 6,
            "CHECK_RESUBMITTED": 7,
            "CHECK_SETTLED": 8,
            "CHECK_LEGAL": 9,
            "CHECK_ARCHIVED": 10,
            "CHECK_CASHED": 11,
            "CHECK_CANCELLED": 12,
            "SALE": 13,
            "SALE_RETURN": 14,
            "SERVICE": 15,
            "PREORDER": 16,
            "PREPAID": 17,
            "EXPENSE": 18,
            "SETTLEMENT": 19,
        }
        type_order = type_priority.get(entry_type, 99)
        ref = e.get("ref", "")
        return (entry_date, type_order, ref)

    entries.sort(key=_sort_key)
    
    if opening_entry:
        entries.insert(0, opening_entry)

    balance = D(0)
    out = []
    for e in entries:
        # الرصيد التراكمي = دائن - مدين (ما له - ما عليه)
        # credit (دائن = ما له) يزيد الرصيد، debit (مدين = ما عليه) يقلل الرصيد
        d = q2(e.get("debit", 0))
        c = q2(e.get("credit", 0))
        balance = balance + c - d
        out.append({**e, "debit": d, "credit": c, "balance": balance})
    
    final_balance_from_ledger = balance
    balance = total_credit - total_debit

    ex_ids = [
        wid
        for (wid,) in db.session.query(Warehouse.id)
        .filter(Warehouse.supplier_id == supplier.id, Warehouse.warehouse_type == WarehouseType.EXCHANGE.value)
        .all()
    ]
    consignment_value = Decimal("0.00")
    if ex_ids:
        rows = (
            db.session.query(
                Product.id.label("pid"),
                Product.name,
                func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"),
                func.coalesce(Product.purchase_price, 0.0).label("unit_cost"),
            )
            .join(Product, Product.id == StockLevel.product_id)
            .filter(StockLevel.warehouse_id.in_(ex_ids), StockLevel.quantity > 0)
            .group_by(Product.id, Product.name, Product.purchase_price)
            .order_by(Product.name.asc())
            .all()
        )
        for pid, name, qty, unit_cost in rows:
            qty_i = int(qty or 0)
            unit_cost_d = q2(unit_cost)
            value = unit_cost_d * q2(qty_i)
            consignment_value += value
            r = _pp(pid)
            if r["product"] is None:
                r["product"] = {"name": name}
            r["qty_unpaid"] = qty_i
            r["val_unpaid"] = value
    
    for pid, row in per_product.items():
        val_paid_from_calc = max(Decimal("0.00"), row["val_in"] - row["val_out"] - row["val_unpaid"])
        row["val_paid"] = row["val_paid"] + val_paid_from_calc
        qty_paid_from_calc = max(0, row["qty_in"] - row["qty_out"] - row["qty_unpaid"])
        row["qty_paid"] = row["qty_paid"] + qty_paid_from_calc

    db.session.refresh(supplier)
    
    current_balance = float(supplier.current_balance or 0)
    
    diff_val = abs(float(final_balance_from_ledger - Decimal(str(current_balance))))
    if diff_val > 0.01:
        try:
            from utils.supplier_balance_updater import update_supplier_balance_components
            from sqlalchemy.orm import sessionmaker
            SessionFactory = sessionmaker(bind=db.engine)
            session = SessionFactory()
            try:
                update_supplier_balance_components(supplier_id, session)
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            pass

        db.session.refresh(supplier)
        current_balance = float(supplier.current_balance or 0)
        diff_val2 = abs(float(final_balance_from_ledger - Decimal(str(current_balance))))
        if diff_val2 > 0.01:
            from flask import current_app
            current_app.logger.warning(
                f"⚠️ عدم تطابق الرصيد في كشف حساب المورد {supplier_id}: "
                f"current_balance={current_balance}, calculated_balance={float(final_balance_from_ledger)}, "
                f"difference={diff_val2}"
            )
    
    from routes.supplier_settlements import _calculate_smart_supplier_balance
    balance_data = _calculate_smart_supplier_balance(
        supplier_id,
        df if df else datetime(2024, 1, 1),
        (dt - timedelta(days=1)) if dt else _utcnow_naive()
    )
    
    balance_unified = balance_data.get('balance', {}).get('amount', 0) if balance_data.get('success') else current_balance
    
    balance_breakdown = None
    balance_breakdown_rights = []
    balance_breakdown_obligations = []
    display_rights_rows = []
    display_obligations_rows = []
    rights_total_display = 0.0
    obligations_total_display = 0.0
    
    if balance_data and balance_data.get("success"):
        rights_info = balance_data.get("rights") or {}
        obligations_info = balance_data.get("obligations") or {}
        rights_total_display = float(rights_info.get("total") or 0.0)
        obligations_total_display = float(obligations_info.get("total") or 0.0)
    
        exchange_total = float((rights_info.get("exchange_items") or {}).get("total_value_ils") or 0.0)
        if exchange_total:
            display_rights_rows.append({"label": "توريدات قطع", "amount": exchange_total})
        services_total = float((rights_info.get("services") or {}).get("total_ils") or 0.0)
        if services_total:
            display_rights_rows.append({"label": "توريد خدمات", "amount": services_total})
    
        sales_total = float((obligations_info.get("sales_to_supplier") or {}).get("total_ils") or 0.0)
        if sales_total:
            display_obligations_rows.append({"label": "مبيعات له", "amount": sales_total})
        services_to_supplier_total = float((obligations_info.get("services_to_supplier") or {}).get("total_ils") or 0.0)
        if services_to_supplier_total:
            display_obligations_rows.append({"label": "صيانة له", "amount": services_to_supplier_total})
        preorders_total = float((obligations_info.get("preorders_to_supplier") or {}).get("total_ils") or 0.0)
        if preorders_total:
            display_obligations_rows.append({"label": "حجوزات له", "amount": preorders_total})
    
        balance_breakdown = {
            **balance_data,
            "rights": {**rights_info, "items": display_rights_rows},
            "obligations": {**obligations_info, "items": display_obligations_rows},
        }
    else:
        try:
            from utils.supplier_balance_updater import build_supplier_balance_view
            balance_breakdown = build_supplier_balance_view(supplier_id, db.session)
        except Exception as exc:
            current_app.logger.warning("supplier_balance_breakdown_statement_failed: %s", exc)
        if balance_breakdown and balance_breakdown.get("success"):
            rights_total_display = float((balance_breakdown.get("rights") or {}).get("total") or 0.0)
            obligations_total_display = float((balance_breakdown.get("obligations") or {}).get("total") or 0.0)
            balance_breakdown_rights = (balance_breakdown.get("rights") or {}).get("items") or []
            balance_breakdown_obligations = (balance_breakdown.get("obligations") or {}).get("items") or []
            if not display_rights_rows:
                display_rights_rows = balance_breakdown_rights
            if not display_obligations_rows:
                display_obligations_rows = balance_breakdown_obligations
    
    if not balance_breakdown_rights:
        balance_breakdown_rights = display_rights_rows
    if not balance_breakdown_obligations:
        balance_breakdown_obligations = display_obligations_rows

    def _direction_meta(amount, positive_text, negative_text, positive_class, negative_class):
        if amount > 0:
            return positive_text, positive_class
        if amount < 0:
            return negative_text, negative_class
        return "متوازن", "text-secondary"

    rights_total_direction_text, rights_total_direction_class = _direction_meta(
        rights_total_display,
        "له رصيد عندنا",
        "عليه تسوية لصالحنا",
        "text-success",
        "text-danger"
    )

    obligations_total_direction_text, obligations_total_direction_class = _direction_meta(
        obligations_total_display,
        "عليه يدفع لنا",
        "له تسوية لدينا",
        "text-danger",
        "text-success"
    )

    balance_display_amount = 0.0
    balance_display_action = ""
    if balance_data and balance_data.get("success"):
        balance_info = balance_data.get("balance") or {}
        balance_display_amount = float(balance_info.get("amount") or 0.0)
        balance_display_action = balance_info.get("action") or ""
    elif balance_breakdown and balance_breakdown.get("success"):
        balance_info = balance_breakdown.get("balance") or {}
        balance_display_amount = float(balance_info.get("amount") or 0.0)
        balance_display_action = balance_info.get("action") or ""

    balance_display_direction_text, balance_display_direction_class = _direction_meta(
        balance_display_amount,
        "له رصيد عندنا",
        "عليه يدفع لنا",
        "text-success",
        "text-danger"
    )
    
    supplier_items = []
    if ex_ids:
        items_query = (
            db.session.query(
                Product.id,
                Product.name,
                Product.sku,
                func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"),
                func.coalesce(Product.purchase_price, 0.0).label("unit_cost"),
                Product.currency,
            )
            .join(Product, Product.id == StockLevel.product_id)
            .filter(StockLevel.warehouse_id.in_(ex_ids), StockLevel.quantity > 0)
            .group_by(Product.id, Product.name, Product.sku, Product.purchase_price, Product.currency)
            .order_by(Product.name.asc())
        )
        
        sold_quantities = (
            db.session.query(
                SaleLine.product_id,
                func.sum(SaleLine.quantity).label("sold_qty")
            )
            .join(Sale, SaleLine.sale_id == Sale.id)
            .filter(
                Sale.status == 'CONFIRMED',
                SaleLine.warehouse_id.in_(ex_ids)
            )
            .group_by(SaleLine.product_id)
        ).subquery()
        
        items_with_sold = (
            items_query
            .outerjoin(sold_quantities, Product.id == sold_quantities.c.product_id)
            .add_columns(func.coalesce(sold_quantities.c.sold_qty, 0).label("sold_qty"))
        ).all()
        
        for item in items_with_sold:
            pid, name, sku, qty, unit_cost, currency, sold_qty = item
            qty_i = int(qty or 0)
            sold_qty_i = int(sold_qty or 0)
            unit_cost_d = q2(unit_cost)
            value = unit_cost_d * q2(qty_i)
            
            supplier_items.append({
                "product_id": pid,
                "name": name,
                "sku": sku or "",
                "quantity": qty_i,
                "sold_quantity": sold_qty_i,
                "available_quantity": qty_i - sold_qty_i,
                "unit_cost": float(unit_cost_d),
                "total_value": float(value),
                "currency": currency or "ILS",
                "is_sold": sold_qty_i > 0,
                "is_available": (qty_i - sold_qty_i) > 0
            })
    
    if is_ajax:
        entries_json = []
        for e in out[:50]:
            d = e.get("date")
            ds = d.strftime("%Y-%m-%d") if isinstance(d, datetime) else (d or "")
            entries_json.append({
                "date": ds,
                "type": e.get("type"),
                "ref": e.get("ref"),
                "debit": float(e.get("debit", 0)),
                "credit": float(e.get("credit", 0)),
                "balance": float(e.get("balance", 0)),
            })
        return jsonify({
            "success": True,
            "entries": entries_json,
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "balance": float(balance_unified),
            "date_from": (df.strftime("%Y-%m-%d") if df else None),
            "date_to": ((dt - timedelta(days=1)).strftime("%Y-%m-%d") if dt else None),
        })
    return render_template(
        "vendors/suppliers/statement.html",
        supplier=supplier,
        ledger_entries=out,
        total_debit=total_debit,
        total_credit=total_credit,
        balance=float(balance_unified),
        balance_ledger=float(final_balance_from_ledger),
        balance_unified=balance_unified,
        balance_data=balance_data,
        balance_breakdown=balance_breakdown,
        balance_breakdown_rights=balance_breakdown_rights,
        balance_breakdown_obligations=balance_breakdown_obligations,
        rights_display_rows=display_rights_rows,
        obligations_display_rows=display_obligations_rows,
        rights_display_total=rights_total_display,
        obligations_display_total=obligations_total_display,
        rights_total_direction_text=rights_total_direction_text,
        rights_total_direction_class=rights_total_direction_class,
        obligations_total_direction_text=obligations_total_direction_text,
        obligations_total_direction_class=obligations_total_direction_class,
        balance_display_amount=balance_display_amount,
        balance_display_action=balance_display_action,
        balance_display_direction_text=balance_display_direction_text,
        balance_display_direction_class=balance_display_direction_class,
        consignment_value=consignment_value,
        per_product=per_product,
        date_from=df if df else None,
        date_to=(dt - timedelta(days=1)) if dt else None,
        supplier_items=supplier_items,
        opening_balance_for_period=float(opening_balance_for_period),
    )

@vendors_bp.route("/partners", methods=["GET"], endpoint="partners_list")
@login_required
def partners_list():
    form = CSRFProtectForm()
    search_term = (request.args.get("q") or request.args.get("search") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(200, max(10, per_page))
    q = Partner.query.filter(Partner.is_archived == False)
    if search_term:
        term = f"%{search_term}%"
        q = q.filter(or_(Partner.name.ilike(term), Partner.phone_number.ilike(term), Partner.identity_number.ilike(term)))
    pagination = q.order_by(Partner.name.asc(), Partner.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    partners = list(pagination.items or [])

    from sqlalchemy import case
    bal = func.coalesce(Partner.current_balance, 0)
    totals_row = (
        q.order_by(None)
        .with_entities(
            func.count(Partner.id).label("total_partners"),
            func.coalesce(func.sum(bal), 0).label("total_balance"),
            func.coalesce(func.sum(case((bal > 0, bal), else_=0)), 0).label("total_debit"),
            func.coalesce(func.sum(case((bal < 0, -bal), else_=0)), 0).label("total_credit"),
            func.coalesce(func.sum(case((bal > 0, 1), else_=0)), 0).label("partners_with_debt"),
            func.coalesce(func.sum(case((bal < 0, 1), else_=0)), 0).label("partners_with_credit"),
        )
        .first()
    )
    total_partners = int(getattr(totals_row, "total_partners", 0) or 0)
    total_balance = float(getattr(totals_row, "total_balance", 0) or 0)
    total_debit = float(getattr(totals_row, "total_debit", 0) or 0)
    total_credit = float(getattr(totals_row, "total_credit", 0) or 0)
    partners_with_debt = int(getattr(totals_row, "partners_with_debt", 0) or 0)
    partners_with_credit = int(getattr(totals_row, "partners_with_credit", 0) or 0)
    
    default_branch = (
        Branch.query.filter(Branch.is_active.is_(True))
        .order_by(Branch.id.asc())
        .first()
    )
    partner_quick_service = {
        "branch_id": default_branch.id if default_branch else None,
        "currency_choices": [{"code": code, "label": label} for code, label in CURRENCY_CHOICES],
        "default_currency": "ILS",
        "today": _utcnow_naive().strftime("%Y-%m-%d"),
    }
    
    summary = {
        "total_partners": total_partners,
        "total_balance": total_balance,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "partners_with_debt": partners_with_debt,
        "partners_with_credit": partners_with_credit,
        "average_balance": (total_balance / total_partners) if total_partners else 0,
    }
    
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1"
    if is_ajax:
        csrf_value = generate_csrf()
        table_html = render_template_string(
            """
<table class="table table-striped table-hover mb-0" id="partnersTable">
  <thead class="table-dark">
    <tr>
      <th style="width:70px">#</th>
      <th>الاسم</th>
      <th>الهاتف</th>
      <th>الرصيد</th>
      <th style="width:520px" data-sortable="false">عمليات</th>
    </tr>
  </thead>
  <tbody>
    {% for p in partners %}
    {% set balance = (p.current_balance if p is not none and p.current_balance is defined and p.current_balance is not none else (p.balance_in_ils or 0)) %}
    <tr>
      <td>{{ loop.index }}</td>
      <td class="partner-name">{{ p.name }}</td>
      <td class="partner-phone">{{ p.phone_number or '—' }}</td>
      <td data-sort-value="{{ balance }}">
        <span class="badge {% if balance < 0 %}bg-danger{% elif balance == 0 %}bg-secondary{% else %}bg-success{% endif %}" data-balance-partner="{{ p.id }}">
          {{ '%.2f'|format(balance) }} ₪
        </span>
        {% if p.current_balance_source is defined and p.current_balance_source == 'smart' %}
          <small class="text-muted d-block">ذكّي</small>
        {% endif %}
      </td>
      <td>
        <div class="d-flex partner-actions">
          <a href="{{ url_for('partner_settlements_bp.partner_settlement', partner_id=p.id) }}"
             class="btn btn-sm btn-success" title="التسوية الذكية الشاملة">
            <i class="fas fa-calculator"></i><span class="d-none d-xl-inline">تسوية</span>
          </a>
          <a href="{{ url_for('payments.index') }}?entity_type=PARTNER&entity_id={{ p.id }}"
             class="btn btn-sm btn-warning text-white" title="كشف الحساب المالي">
            <i class="fas fa-file-invoice-dollar"></i><span class="d-none d-xl-inline">كشف حساب</span>
          </a>
          <a href="{{ url_for('expenses_bp.create_expense', partner_id=p.id, mode='partner_service') }}"
             class="btn btn-sm btn-info text-white js-partner-service"
             data-partner-id="{{ p.id }}"
             data-partner-name="{{ p.name }}"
             title="توريد خدمات للشريك">
            <i class="fas fa-file-signature"></i><span class="d-none d-xl-inline">توريد خدمات</span>
          </a>
          <a href="{{ url_for('payments.create_payment') }}?entity_type=PARTNER&entity_id={{ p.id }}&entity_name={{ p.name|urlencode }}"
             class="btn btn-sm btn-primary" title="إضافة دفعة">
            <i class="fas fa-money-bill-wave"></i><span class="d-none d-xl-inline">دفع</span>
          </a>
          {% if current_user.has_permission(SystemPermissions.MANAGE_VENDORS) %}
            <a href="{{ url_for('vendors_bp.partners_edit', id=p.id) }}"
               class="btn btn-sm btn-secondary" title="تعديل بيانات الشريك">
              <i class="fas fa-edit"></i><span class="d-none d-xl-inline">تعديل</span>
            </a>
            {% if p.is_archived %}
              <button type="button" class="btn btn-sm btn-success" title="استعادة الشريك" onclick="restorePartner({{ p.id }})">
                <i class="fas fa-undo"></i><span class="d-none d-xl-inline">استعادة</span>
              </button>
            {% else %}
              <button type="button" class="btn btn-sm btn-outline-warning" title="أرشفة الشريك" onclick="archivePartner({{ p.id }})">
                <i class="fas fa-archive"></i><span class="d-none d-xl-inline">أرشفة</span>
              </button>
            {% endif %}
            <form method="post"
                  action="{{ url_for('vendors_bp.partners_delete', id=p.id) }}"
                  onsubmit="return confirm('حذف الشريك؟');"
                  class="d-inline">
              <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
              <button type="submit" class="btn btn-sm btn-outline-danger" title="حذف عادي">
                <i class="fas fa-trash"></i><span class="d-none d-xl-inline">حذف</span>
              </button>
            </form>
            
          {% endif %}
        </div>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5" class="text-center py-4">لا توجد بيانات</td></tr>
    {% endfor %}
  </tbody>
</table>
            """,
            partners=partners,
            csrf_token=csrf_value,
        )
        return jsonify(
            {
                "table_html": table_html,
                "total_partners": summary["total_partners"],
                "total_balance": summary["total_balance"],
                "average_balance": summary["average_balance"],
                "partners_with_debt": summary["partners_with_debt"],
                "partners_with_credit": summary["partners_with_credit"],
                "total_filtered": int(pagination.total or 0),
                "page": int(pagination.page or 1),
                "pages": int(pagination.pages or 1),
                "per_page": int(per_page),
            }
        )

    query_args = request.args.to_dict()
    query_args.pop("page", None)
    query_args.pop("per_page", None)
    return render_template(
        "vendors/partners/list.html",
        partners=partners,
        search=search_term,
        form=form,
        pay_url=url_for("payments.create_payment"),
        summary=summary,
        partner_quick_service=partner_quick_service,
        pagination=pagination,
        per_page=per_page,
        query_args=query_args,
    )


@vendors_bp.post("/partners/balances/recalculate", endpoint="partners_recalculate_balances")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_VENDORS)
def partners_recalculate_balances():
    payload = request.get_json(silent=True) or {}
    ids_raw = (
        request.form.get("partner_ids")
        or request.form.get("ids")
        or payload.get("partner_ids")
        or payload.get("ids")
        or ""
    )
    if isinstance(ids_raw, list):
        raw_list = ids_raw
    else:
        raw_list = [s.strip() for s in str(ids_raw).replace(";", ",").split(",") if s.strip()]
    partner_ids = []
    for x in raw_list:
        try:
            partner_ids.append(int(x))
        except Exception:
            continue
    partner_ids = [pid for pid in partner_ids if pid > 0]
    partner_ids = list(dict.fromkeys(partner_ids))
    if not partner_ids:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"success": False, "message": "no_partner_ids"}), 400
        flash("أدخل أرقام الشركاء لتحديث الأرصدة.", "warning")
        return redirect(url_for("vendors_bp.partners_list"))

    try:
        from utils.partner_balance_updater import update_partner_balance_components
        from sqlalchemy.orm import sessionmaker
        SessionFactory = sessionmaker(bind=db.engine)
        session = SessionFactory()
        updated = 0
        try:
            for pid in partner_ids:
                try:
                    update_partner_balance_components(pid, session)
                    updated += 1
                except Exception:
                    continue
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"success": True, "updated": updated})
        flash(f"تم تحديث أرصدة {updated} شريك.", "success")
        return redirect(url_for("vendors_bp.partners_list"))
    except Exception as e:
        if request.accept_mimetypes.best == "application/json":
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
        flash("حدث خطأ أثناء تحديث أرصدة الشركاء.", "danger")
        return redirect(url_for("vendors_bp.partners_list"))

# ⚠️ قبل التعديل: اقرأ ACCOUNTING_RULES.md - قواعد المحاسبة الأساسية
@vendors_bp.get("/partners/<int:partner_id>/statement", endpoint="partners_statement")
@login_required
def partners_statement(partner_id: int):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("ajax") == "1"
    partner = db.session.get(Partner, partner_id)
    if not partner:
        if is_ajax:
            return jsonify({"success": False, "message": "not_found"}), 404
        abort(404)

    date_from_s = (request.args.get("from") or "").strip()
    date_to_s = (request.args.get("to") or "").strip()
    try:
        df = datetime.strptime(date_from_s, "%Y-%m-%d") if date_from_s else None
        dt = datetime.strptime(date_to_s, "%Y-%m-%d") if date_to_s else None
    except Exception:
        df, dt = None, None
    if dt:
        dt = dt + timedelta(days=1)
    from models import Expense, ExpenseType

    entries = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    
    if partner.customer_id:
        from models import Sale, SaleStatus, _find_partner_share_percentage
        sale_q = (
            db.session.query(Sale)
            .options(joinedload(Sale.lines))
            .filter(
                Sale.customer_id == partner.customer_id,
                Sale.status == SaleStatus.CONFIRMED.value,
            )
        )
        if df:
            sale_q = sale_q.filter(Sale.sale_date >= df)
        if dt:
            sale_q = sale_q.filter(Sale.sale_date < dt)
        
        for sale in sale_q.all():
            d = sale.sale_date
            amt = q2(sale.total_amount or 0)
            ref = sale.sale_number or f"فاتورة #{sale.id}"
            
            items = []
            for line in (sale.lines or []):
                product_id = line.product_id if hasattr(line, 'product_id') else None
                warehouse_id = line.warehouse_id if hasattr(line, 'warehouse_id') else None
                share_pct = _find_partner_share_percentage(partner.id, product_id, warehouse_id) if product_id else 0.0
                line_total = float(q2(line.net_amount or 0))
                share_amount = line_total * (share_pct / 100.0) if share_pct else 0.0
                
                items.append({
                    "type": "قطعة",
                    "name": line.product.name if line.product else "منتج",
                    "qty": line.quantity or 0,
                    "price": float(q2(line.unit_price or 0)),
                    "total": line_total,
                    "share_pct": share_pct,
                    "share_amount": share_amount
                })
            
            # ✅ حساب إجمالي نسبة الربح للشريك (حسب سعر البيع)
            total_partner_share = sum(item.get("share_amount", 0) for item in items)
            total_partner_share_decimal = q2(total_partner_share)
            
            if total_partner_share_decimal > 0:
                statement = f"نسبة ربح من مبيعات - {ref}"
                entries.append({
                    "id": sale.id,
                    "model": "sale",
                    "date": d, 
                    "type": "PARTNER_SALE_SHARE", 
                    "ref": ref, 
                    "statement": statement, 
                    "debit": Decimal("0.00"), 
                    "credit": total_partner_share_decimal,  # ✓ نسبة الربح فقط (حسب سعر البيع)
                    "details": items,
                    "has_details": len(items) > 0
                })
                total_credit += total_partner_share_decimal
    
    if partner.customer_id:
        from models import SaleReturn, SaleReturnLine, Sale, _find_partner_share_percentage
        from routes.partner_settlements import _get_partner_sales_returns
        
        returns_data = _get_partner_sales_returns(
            partner.id,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if returns_data and isinstance(returns_data, dict) and returns_data.get("items"):
            for return_item in returns_data.get("items", []):
                return_date_str = return_item.get("date", "")
                try:
                    if return_date_str:
                        return_date = datetime.strptime(return_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and return_date < df:
                    continue
                if dt and return_date >= dt:
                    continue
                
                return_amount = Decimal(str(return_item.get("partner_return_share_ils", 0) or 0))
                if return_amount > 0:
                    ref_return = f"مرتجع #{return_item.get('reference_number', '')}"
                    statement_return = f"خصم مرتجع مبيعات - {return_item.get('product_name', 'منتج')}"
                    
                    items_return = [{
                        "type": "مرتجع",
                        "name": return_item.get('product_name', 'منتج'),
                        "qty": return_item.get('quantity', 0),
                        "price": return_item.get('unit_price', 0),
                        "total": return_item.get('return_amount', 0),
                        "share_pct": return_item.get('share_percentage', 0),
                        "share_amount": return_item.get('partner_return_share', 0)
                    }]
                    
                    entries.append({
                        "id": return_item.get('reference_number'),
                        "model": "sale_return",
                        "date": return_date,
                        "type": "PARTNER_SALE_RETURN",
                        "ref": ref_return,
                        "statement": statement_return,
                        "debit": return_amount,  # ✓ خصم من نصيب المبيعات
                        "credit": Decimal("0.00"),
                        "details": items_return,
                        "has_details": len(items_return) > 0
                    })
                    total_debit += return_amount
    
    if partner.customer_id:
        from models import ServiceRequest, _find_partner_share_percentage
        service_q = (
            db.session.query(ServiceRequest)
            .options(joinedload(ServiceRequest.parts), joinedload(ServiceRequest.tasks))
            .filter(
                ServiceRequest.customer_id == partner.customer_id,
                ServiceRequest.status == ServiceStatus.COMPLETED.value,
            )
        )
        if df:
            service_q = service_q.filter(ServiceRequest.received_at >= df)
        if dt:
            service_q = service_q.filter(ServiceRequest.received_at < dt)
        
        for service in service_q.all():
            d = service.received_at
            # استخدام total (hybrid property) الذي يحتوي على الضريبة بدلاً من total_amount
            service_total = getattr(service, 'total', None)
            if service_total is None:
                # إذا لم يكن total موجوداً، نحسبه يدوياً مع الضريبة
                parts_total = q2(service.parts_total or 0)
                labor_total = q2(service.labor_total or 0)
                discount_total = q2(service.discount_total or 0)
                tax_rate = q2(service.tax_rate or 0)
                subtotal = parts_total + labor_total - discount_total
                if subtotal < 0:
                    subtotal = Decimal("0.00")
                tax_amount = subtotal * (tax_rate / 100.0)
                service_total = subtotal + tax_amount
            else:
                service_total = q2(service_total)
            amt = service_total
            ref = service.service_number or f"صيانة #{service.id}"
            
            items = []
            for part in (service.parts or []):
                product_id = part.part_id if hasattr(part, 'part_id') else None
                warehouse_id = part.warehouse_id if hasattr(part, 'warehouse_id') else None
                share_pct = float(part.share_percentage or 0) if part.partner_id == partner.id else _find_partner_share_percentage(partner.id, product_id, warehouse_id) if product_id else 0.0
                part_total = float(q2(part.quantity * part.unit_price))
                share_amount = part_total * (share_pct / 100.0) if share_pct else 0.0
                
                items.append({
                    "type": "قطعة",
                    "name": part.part.name if part.part else "قطعة غيار",
                    "qty": part.quantity,
                    "price": float(part.unit_price or 0),
                    "total": part_total,
                    "share_pct": share_pct,
                    "share_amount": share_amount
                })
            for task in (service.tasks or []):
                items.append({
                    "type": "خدمة",
                    "name": task.description or "خدمة",
                    "qty": task.quantity or 1,
                    "price": float(task.unit_price or 0),
                    "total": float(q2((task.quantity or 1) * task.unit_price)),
                    "share_pct": 0,
                    "share_amount": 0
                })
            
            statement = f"صيانة للشريك - {ref}"
            entries.append({
                "id": service.id,
                "model": "service",
                "date": d, 
                "type": "SERVICE", 
                "ref": ref, 
                "statement": statement, 
                "debit": Decimal("0.00"), 
                "credit": amt,
                "details": items,
                "has_details": len(items) > 0
            })
            total_credit += amt

    pay_q = (
        db.session.query(Payment)
        .options(joinedload(Payment.splits))
        .filter(
            Payment.partner_id == partner.id,
            Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.REFUNDED.value]),
        )
    )
    if df:
        pay_q = pay_q.filter(Payment.payment_date >= df)
    if dt:
        pay_q = pay_q.filter(Payment.payment_date < dt)
    direct_payments = pay_q.all()
    
    expense_pay_q = (
        db.session.query(Payment)
        .options(joinedload(Payment.splits))
        .join(Expense, Payment.expense_id == Expense.id)
        .filter(
            or_(
                Expense.partner_id == partner.id,
                and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner.id)
            ),
            Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.REFUNDED.value]),
        )
    )
    if df:
        expense_pay_q = expense_pay_q.filter(Payment.payment_date >= df)
    if dt:
        expense_pay_q = expense_pay_q.filter(Payment.payment_date < dt)
    expense_payments = expense_pay_q.all()
    
    customer_payments = []
    if partner.customer_id:
        from models import Sale, Invoice, ServiceRequest, PreOrder
        customer_pay_q = (
            db.session.query(Payment)
            .outerjoin(Sale, Payment.sale_id == Sale.id)
            .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
            .outerjoin(ServiceRequest, Payment.service_id == ServiceRequest.id)
            .outerjoin(PreOrder, Payment.preorder_id == PreOrder.id)
            .outerjoin(Expense, Payment.expense_id == Expense.id)
            .options(joinedload(Payment.splits))
            .filter(
                Payment.status.in_([PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.REFUNDED.value]),
                or_(
                    Payment.customer_id == partner.customer_id,
                    Sale.customer_id == partner.customer_id,
                    Invoice.customer_id == partner.customer_id,
                    ServiceRequest.customer_id == partner.customer_id,
                    PreOrder.customer_id == partner.customer_id,
                    Expense.customer_id == partner.customer_id,
                ),
                or_(
                    Payment.preorder_id.is_(None),
                    Payment.sale_id.isnot(None),
                    PreOrder.status == 'FULFILLED',
                ),
            )
        )
        if df:
            customer_pay_q = customer_pay_q.filter(Payment.payment_date >= df)
        if dt:
            customer_pay_q = customer_pay_q.filter(Payment.payment_date < dt)
        customer_payments = customer_pay_q.distinct().all()
    
    payment_ids = set()
    all_payments = []
    for p in direct_payments + expense_payments + customer_payments:
        if p.id not in payment_ids:
            payment_ids.add(p.id)
            all_payments.append(p)

    for p in all_payments:
        d = p.payment_date
        amt = q2(p.total_amount or 0)
        ref = p.reference or f"سند #{p.id}"
        dirv = getattr(p, "direction", None)
        
        payment_status = getattr(p, 'status', 'COMPLETED')
        is_bounced = payment_status in ['BOUNCED', 'FAILED', 'REJECTED', 'RETURNED']
        is_pending = payment_status == 'PENDING'
        
        method_map = {
            'cash': 'نقداً',
            'card': 'بطاقة',
            'cheque': 'شيك',
            'bank': 'تحويل بنكي',
            'online': 'إلكتروني',
        }
        method_value = getattr(p, 'method', 'cash')
        if hasattr(method_value, 'value'):
            method_value = method_value.value
        method_raw = str(method_value).lower()
        
        split_details = []
        splits = list(getattr(p, 'splits', []) or [])
        if splits:
            unique_methods = set()
            for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                split_method_val = getattr(split, "method", None)
                if hasattr(split_method_val, "value"):
                    split_method_val = split_method_val.value
                split_method_raw = str(split_method_val or "").lower()
                if not split_method_raw:
                    split_method_raw = method_raw or "cash"
                unique_methods.add(split_method_raw)
                split_currency = (getattr(split, "currency", None) or getattr(p, "currency", "ILS") or "ILS").upper()
                converted_currency = (getattr(split, "converted_currency", None) or getattr(p, "currency", "ILS") or "ILS").upper()
                split_details.append({
                    "method": method_map.get(split_method_raw, split_method_raw),
                    "method_raw": split_method_raw,
                    "amount": D(getattr(split, "amount", 0) or 0),
                    "currency": split_currency,
                    "fx_rate": getattr(split, "fx_rate_used", None),
                    "fx_rate_source": getattr(split, "fx_rate_source", None),
                    "converted_amount": D(getattr(split, "converted_amount", 0) or 0),
                    "converted_currency": converted_currency,
                })
            if unique_methods:
                if len(unique_methods) == 1:
                    method_raw = next(iter(unique_methods))
                else:
                    method_raw = "mixed"
        
        method_arabic = method_map.get(method_raw, "طرق متعددة" if method_raw == "mixed" else method_raw)
        method_display = "طرق متعددة" if method_raw == "mixed" else method_arabic
        
        payment_details = {
            'method': method_display,
            'method_raw': method_raw,
            'check_number': getattr(p, 'check_number', None) if method_raw == 'cheque' else None,
            'check_bank': getattr(p, 'check_bank', None),
            'check_due_date': getattr(p, 'check_due_date', None) if method_raw == 'cheque' else None,
            'receiver_name': getattr(p, 'receiver_name', None) or '',
            'status': payment_status,
            'is_bounced': is_bounced,
            'is_pending': is_pending,
            'is_refunded': (payment_status == 'REFUNDED'),
            'splits': split_details,
        }
        
        notes = getattr(p, 'notes', '') or ''
        is_out = dirv == PaymentDirection.OUT.value
        
        # ✅ إذا كانت الدفعة لديها splits، نعرض كل split كدفعة منفصلة
        if splits and len(splits) > 0:
                # عرض كل split كدفعة منفصلة
                for split in sorted(splits, key=lambda s: getattr(s, "id", 0)):
                    split_method_val = getattr(split, "method", None)
                    if hasattr(split_method_val, "value"):
                        split_method_val = split_method_val.value
                    split_method_raw = str(split_method_val or "").lower()
                    if not split_method_raw:
                        split_method_raw = method_raw or "cash"
                    
                    split_currency = (getattr(split, "currency", None) or getattr(p, "currency", "ILS") or "ILS").upper()
                    converted_currency = (getattr(split, "converted_currency", None) or getattr(p, "currency", "ILS") or "ILS").upper()
                    
                    # حساب المبلغ بالـ ILS
                    split_amount = D(getattr(split, "amount", 0) or 0)
                    split_converted_amount = D(getattr(split, "converted_amount", 0) or 0)
                    
                    # استخدام المبلغ المحول إذا كان موجوداً
                    if split_converted_amount > 0 and converted_currency == "ILS":
                        split_amount_ils = split_converted_amount
                    else:
                        split_amount_ils = split_amount
                        if split_currency != "ILS":
                            try:
                                from models import convert_amount
                                split_amount_ils = convert_amount(split_amount, split_currency, "ILS", p.payment_date or df)
                            except:
                                pass
                    
                    # تحديد طريقة الدفع للـ split
                    split_method_arabic = method_map.get(split_method_raw, split_method_raw)
                    
                    # فحص إذا كان Split لديها شيك مرتبط
                    split_check = None
                    if 'check' in split_method_raw or 'cheque' in split_method_raw:
                        from models import Check
                        split_checks = Check.query.filter(
                            or_(
                                Check.reference_number == f"PMT-SPLIT-{split.id}",
                                Check.reference_number.like(f"PMT-SPLIT-{split.id}-%")
                            )
                        ).all()
                        if split_checks:
                            split_check = split_checks[0]
                    
                    # تحديد حالة Split
                    split_is_bounced = False
                    split_is_pending = False
                    split_has_cashed = False
                    split_has_returned = False
                    split_check_status = None
                    
                    if split_check:
                        split_check_status = str(getattr(split_check, 'status', 'PENDING') or 'PENDING').upper()
                        split_is_bounced = split_check_status in ['RETURNED', 'BOUNCED']
                        split_is_pending = split_check_status == 'PENDING' and not split_is_bounced
                        split_has_cashed = split_check_status == 'CASHED'
                        split_has_returned = split_check_status in ['RETURNED', 'BOUNCED']
                    
                    # إنشاء البيان للـ split
                    is_out = dirv == PaymentDirection.OUT.value
                    if split_has_returned:
                        split_statement = f"إرجاع شيك"
                        if split_check and split_check.check_number:
                            split_statement += f" #{split_check.check_number}"
                        if split_check and split_check.check_bank:
                            split_statement += f" - {split_check.check_bank}"
                        split_entry_type = "CHECK_RETURNED"
                    elif split_is_pending and ('check' in split_method_raw or 'cheque' in split_method_raw):
                        split_statement = f"⏳ شيك معلق - {split_method_arabic} {'للشريك' if is_out else 'من الشريك'}"
                        if split_check and split_check.check_number:
                            split_statement += f" #{split_check.check_number}"
                        split_entry_type = "CHECK_PENDING"
                    elif split_has_cashed:
                        split_statement = f"✅ شيك مسحوب - {split_method_arabic} {'للشريك' if is_out else 'من الشريك'}"
                        if split_check and split_check.check_number:
                            split_statement += f" #{split_check.check_number}"
                        split_entry_type = "CHECK_CASHED"
                    else:
                        split_statement = f"{'سداد' if is_out else 'قبض'} {split_method_arabic} {'للشريك' if is_out else 'من الشريك'}"
                        split_entry_type = "PAYMENT_OUT" if is_out else "PAYMENT_IN"
                    
                    if notes:
                        split_statement += f" - {notes[:30]}"
                    
                    # حساب debit/credit للـ split
                    split_is_in = not is_out
                    if split_has_returned:
                        # للشيك المرتد، نعكس القيد
                        # إذا كان is_in (قبضنا من الشريك) وكان الشيك مرتد → نعكس credit → نضع debit
                        # إذا كان is_out (دفعنا للشريك) وكان الشيك مرتد → نعكس debit → نضع credit
                        split_debit = split_amount_ils if split_is_in else D(0)
                        split_credit = split_amount_ils if is_out else D(0)
                    else:
                        # للدفعة العادية
                        split_debit = split_amount_ils if is_out else D(0)
                        split_credit = split_amount_ils if split_is_in else D(0)
                    
                    # إنشاء payment_details للـ split
                    split_payment_details = {
                        'method': split_method_arabic,
                        'method_raw': split_method_raw,
                        'check_number': split_check.check_number if split_check else None,
                        'check_bank': split_check.check_bank if split_check else None,
                        'check_due_date': split_check.check_due_date if split_check else None,
                        'receiver_name': getattr(p, 'receiver_name', None) or '',
                        'status': split_check_status if split_check_status else payment_status,
                        'is_bounced': split_is_bounced,
                        'is_pending': split_is_pending,
                        'is_cashed': split_has_cashed,
                        'is_returned': split_has_returned,
                        'is_refunded': (payment_status == 'REFUNDED'),
                        'splits': [],
                        'all_checks': [{
                            'check_number': split_check.check_number,
                            'check_bank': split_check.check_bank,
                            'check_due_date': split_check.check_due_date,
                            'status': split_check_status,
                            'amount': float(split_check.amount or 0),
                            'currency': split_check.currency or 'ILS',
                        }] if split_check else [],
                    }
                    
                    # إضافة الـ split كدفعة منفصلة
                    entries.append({
                        "id": p.id,
                        "model": "payment",
                        "date": d,
                        "type": split_entry_type,
                        "ref": f"SPLIT-{split.id}-PMT-{p.id}",
                        "statement": split_statement,
                        "debit": split_debit,
                        "credit": split_credit,
                        "payment_details": split_payment_details,
                        "notes": notes
                    })
                    
                    total_debit += split_debit
                    total_credit += split_credit
        else:
            # ✅ الدفعة بدون splits - نعرضها كالمعتاد
            if is_out:
                entry_type = "CHECK_BOUNCED" if is_bounced else ("CHECK_PENDING" if is_pending and method_raw == 'cheque' else "PAYMENT_OUT")
                entries.append({
                    "id": p.id,
                    "model": "payment",
                    "date": d,
                    "type": entry_type,
                    "ref": ref,
                    "statement": statement,
                    "debit": Decimal("0.00") if is_bounced else amt,
                    "credit": amt if is_bounced else Decimal("0.00"),
                    "payment_details": payment_details,
                    "notes": notes
                })
                if is_bounced:
                    total_credit += amt
                else:
                    total_debit += amt
            else:
                entry_type = "CHECK_BOUNCED" if is_bounced else ("CHECK_PENDING" if is_pending and method_raw == 'cheque' else "PAYMENT_IN")
                entries.append({
                    "id": p.id,
                    "model": "payment",
                    "date": d,
                    "type": entry_type,
                    "ref": ref,
                    "statement": statement,
                    "debit": amt if is_bounced else Decimal("0.00"),
                    "credit": Decimal("0.00") if is_bounced else amt,
                    "payment_details": payment_details,
                    "notes": notes
                })
                if is_bounced:
                    total_debit += amt
                else:
                    total_credit += amt

    from models import ExpenseType
    expense_q = Expense.query.join(ExpenseType).filter(
        or_(
            Expense.partner_id == partner.id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner.id)
        ),
        func.upper(ExpenseType.code) != "PARTNER_EXPENSE"
    )
    if df:
        expense_q = expense_q.filter(Expense.date >= df)
    if dt:
        expense_q = expense_q.filter(Expense.date < dt)
    
    for exp in expense_q.all():
        d = exp.date
        amt = q2(exp.amount or 0)
        
        if exp.currency and exp.currency != "ILS" and amt > 0:
            try:
                from models import convert_amount
                convert_date = d if d else (df if df else partner.created_at)
                amt = convert_amount(amt, exp.currency, "ILS", convert_date)
            except Exception as e:
                try:
                    from flask import current_app
                    current_app.logger.error(f"Error converting expense #{exp.id} amount: {e}")
                except Exception:
                    pass
        
        exp_type_name = getattr(getattr(exp, 'type', None), 'name', 'مصروف')
        ref = f"مصروف #{exp.id}"
        statement = f"مصروف: {exp_type_name}"
        if exp.description:
            statement += f" - {exp.description}"
        
        entries.append({
            "id": exp.id,
            "model": "expense",
            "date": d,
            "type": "EXPENSE",
            "ref": ref,
            "statement": statement,
            "debit": amt,
            "credit": Decimal("0.00")
        })
        total_debit += amt

    if partner.customer_id:
        from models import PreOrder
        from routes.partner_settlements import _get_partner_preorders_prepaid, _get_partner_preorders_as_customer, _get_partner_sales_as_customer, _get_partner_service_fees, _get_partner_damaged_items
        from models import Expense, ExpenseType
        
        preorders_prepaid_data = _get_partner_preorders_prepaid(
            partner.id,
            partner,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if preorders_prepaid_data and isinstance(preorders_prepaid_data, dict) and preorders_prepaid_data.get("items"):
            for prepaid_item in preorders_prepaid_data.get("items", []):
                prepaid_date_str = prepaid_item.get("date", "")
                try:
                    if prepaid_date_str:
                        prepaid_date = datetime.strptime(prepaid_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and prepaid_date < df:
                    continue
                if dt and prepaid_date >= dt:
                    continue
                
                prepaid_amount = Decimal(str(prepaid_item.get("amount_ils", 0) or 0))
                if prepaid_amount > 0:
                    ref_prepaid = f"عربون حجز #{prepaid_item.get('preorder_id', '')}"
                    statement_prepaid = f"عربون حجز مسبق - {prepaid_item.get('product', 'منتج')}"
                    
                    entries.append({
                        "date": prepaid_date,
                        "type": "PREPAID",
                        "ref": ref_prepaid,
                        "statement": statement_prepaid,
                        "debit": Decimal("0.00"),
                        "credit": prepaid_amount,
                        "notes": f"حالة الحجز: {prepaid_item.get('status', '')}"
                    })
                    total_credit += prepaid_amount
        
        preorders_to_partner_data = _get_partner_preorders_as_customer(
            partner.id,
            partner,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if preorders_to_partner_data and isinstance(preorders_to_partner_data, dict) and preorders_to_partner_data.get("items"):
            for preorder_item in preorders_to_partner_data.get("items", []):
                preorder_date_str = preorder_item.get("date", "")
                try:
                    if preorder_date_str:
                        preorder_date = datetime.strptime(preorder_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and preorder_date < df:
                    continue
                if dt and preorder_date >= dt:
                    continue
                
                preorder_amount = Decimal(str(preorder_item.get("amount_ils", 0) or 0))
                if preorder_amount > 0:
                    ref_preorder = preorder_item.get('preorder_number', f"حجز #{preorder_item.get('preorder_id', '')}")
                    statement_preorder = f"حجز مسبق للشريك - {ref_preorder}"
                    
                    entries.append({
                        "date": preorder_date,
                        "type": "PREORDER",
                        "ref": ref_preorder,
                        "statement": statement_preorder,
                        "debit": preorder_amount,
                        "credit": Decimal("0.00"),
                        "notes": f"حالة الحجز: {preorder_item.get('status', '')}"
                    })
                    total_debit += preorder_amount
        
        sales_to_partner_data = _get_partner_sales_as_customer(
            partner.id,
            partner,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if sales_to_partner_data and isinstance(sales_to_partner_data, dict) and sales_to_partner_data.get("items"):
            for sale_item in sales_to_partner_data.get("items", []):
                sale_date_str = sale_item.get("date", "")
                try:
                    if sale_date_str:
                        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and sale_date < df:
                    continue
                if dt and sale_date >= dt:
                    continue
                
                sale_amount = Decimal(str(sale_item.get("amount_ils", 0) or 0))
                if sale_amount > 0:
                    ref_sale = sale_item.get('reference', f"مبيعة #{sale_item.get('sale_id', '')}")
                    statement_sale = f"مبيعات للشريك - {ref_sale}"
                    
                    entries.append({
                        "date": sale_date,
                        "type": "SALE_TO_PARTNER",
                        "ref": ref_sale,
                        "statement": statement_sale,
                        "debit": sale_amount,
                        "credit": Decimal("0.00"),
                        "notes": sale_item.get('notes', '')
                    })
                    total_debit += sale_amount
        
        service_fees_data = _get_partner_service_fees(
            partner.id,
            partner,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if service_fees_data and isinstance(service_fees_data, dict) and service_fees_data.get("items"):
            for service_item in service_fees_data.get("items", []):
                service_date_str = service_item.get("date", "")
                try:
                    if service_date_str:
                        service_date = datetime.strptime(service_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and service_date < df:
                    continue
                if dt and service_date >= dt:
                    continue
                
                service_amount = Decimal(str(service_item.get("amount_ils", 0) or 0))
                if service_amount > 0:
                    ref_service = service_item.get('reference', f"صيانة #{service_item.get('service_id', '')}")
                    statement_service = f"رسوم صيانة للشريك - {ref_service}"
                    
                    entries.append({
                        "date": service_date,
                        "type": "SERVICE_FEE",
                        "ref": ref_service,
                        "statement": statement_service,
                        "debit": service_amount,
                        "credit": Decimal("0.00"),
                        "notes": service_item.get('notes', '')
                    })
                    total_debit += service_amount
        
        damaged_items_data = _get_partner_damaged_items(
            partner.id,
            df if df else datetime(2024, 1, 1),
            (dt - timedelta(days=1)) if dt else _utcnow_naive()
        )
        
        if damaged_items_data and isinstance(damaged_items_data, dict) and damaged_items_data.get("items"):
            for damaged_item in damaged_items_data.get("items", []):
                damaged_date_str = damaged_item.get("date", "")
                try:
                    if damaged_date_str:
                        damaged_date = datetime.strptime(damaged_date_str, "%Y-%m-%d")
                    else:
                        continue
                except Exception:
                    continue
                
                if df and damaged_date < df:
                    continue
                if dt and damaged_date >= dt:
                    continue
                
                damaged_amount = Decimal(str(damaged_item.get("amount_ils", 0) or 0))
                if damaged_amount > 0:
                    ref_damaged = f"تالف #{damaged_item.get('return_line_id', '')}"
                    statement_damaged = f"قطع تالفة - {damaged_item.get('product_name', 'منتج')}"
                    
                    entries.append({
                        "date": damaged_date,
                        "type": "DAMAGED_ITEM",
                        "ref": ref_damaged,
                        "statement": statement_damaged,
                        "debit": damaged_amount,
                        "credit": Decimal("0.00"),
                        "notes": f"حالة: {damaged_item.get('condition', '')}"
                    })
                    total_debit += damaged_amount
        
        service_expenses = Expense.query.join(ExpenseType).filter(
            or_(
                Expense.partner_id == partner.id,
                and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner.id)
            ),
            Expense.date >= (df if df else datetime(2024, 1, 1)),
            Expense.date <= ((dt - timedelta(days=1)) if dt else _utcnow_naive()),
            func.upper(ExpenseType.code) == "PARTNER_EXPENSE"
        ).all()
        
        for exp in service_expenses:
            d = exp.date
            if df and d < df:
                continue
            if dt and d >= dt:
                continue
            
            amt = q2(exp.amount or 0)
            if exp.currency and exp.currency != "ILS" and amt > 0:
                try:
                    from models import convert_amount
                    convert_date = d if d else (df if df else partner.created_at)
                    amt = convert_amount(amt, exp.currency, "ILS", convert_date)
                except Exception as e:
                    try:
                        from flask import current_app
                        current_app.logger.error(f"Error converting service expense #{exp.id} amount: {e}")
                    except Exception:
                        pass
            
            exp_type_name = getattr(getattr(exp, 'type', None), 'name', 'توريد خدمة')
            ref = f"توريد خدمة #{exp.id}"
            statement = f"توريد خدمة: {exp_type_name}"
            if exp.description:
                statement += f" - {exp.description}"
            
            entries.append({
                "date": d,
                "type": "SERVICE_EXPENSE",
                "ref": ref,
                "statement": statement,
                "debit": Decimal("0.00"),
                "credit": amt,
                "notes": exp.notes or ''
            })
            total_credit += amt

    opening_balance = Decimal(getattr(partner, 'opening_balance', 0) or 0)
    if opening_balance != 0 and partner.currency and partner.currency != "ILS":
        try:
            from models import convert_amount
            convert_date = df if df else partner.created_at
            opening_balance = convert_amount(opening_balance, partner.currency, "ILS", convert_date)
        except Exception as e:
            try:
                from flask import current_app
                current_app.logger.error(f"Error converting partner #{partner.id} opening balance: {e}")
            except Exception:
                pass
    
    if opening_balance != 0:
        opening_date = partner.created_at
        if entries:
            first_entry_date = min((e["date"] for e in entries if e["date"]), default=partner.created_at)
            if first_entry_date and first_entry_date < partner.created_at:
                opening_date = first_entry_date
        
        opening_entry = {
            "date": opening_date,
            "type": "OPENING_BALANCE",
            "ref": "OB-PARTNER",
            "statement": "الرصيد الافتتاحي",
            "debit": abs(opening_balance) if opening_balance < 0 else Decimal("0.00"),
            "credit": abs(opening_balance) if opening_balance > 0 else Decimal("0.00"),
        }
        entries.insert(0, opening_entry)
        if opening_balance > 0:
            total_credit += abs(opening_balance)
        else:
            total_debit += abs(opening_balance)

    def sort_key(entry):
        if entry.get("type") == "OPENING_BALANCE":
            return (datetime.min, "", "")  # الرصيد الافتتاحي دائماً أولاً
        return (entry.get("date") or datetime.min, entry.get("type", ""), entry.get("ref", ""))
    
    entries.sort(key=sort_key)

    balance = D(0)
    out = []
    for e in entries:
        # الرصيد التراكمي = دائن - مدين (ما له - ما عليه)
        # credit (دائن = ما له) يزيد الرصيد، debit (مدين = ما عليه) يقلل الرصيد
        d = q2(e["debit"])
        c = q2(e["credit"])
        balance = balance + c - d
        out.append({**e, "debit": d, "credit": c, "balance": balance})
    
    balance = total_credit - total_debit
    
    from routes.partner_settlements import _calculate_smart_partner_balance
    balance_data = _calculate_smart_partner_balance(
        partner_id,
        df if df else datetime(2024, 1, 1),
        (dt - timedelta(days=1)) if dt else _utcnow_naive()
    )
    
    balance_unified = balance_data.get('balance', {}).get('amount', 0) if balance_data.get('success') else partner.balance_in_ils
    
    db.session.refresh(partner)
    current_balance = float(partner.current_balance or 0)
    diff_val = abs(float(balance_unified) - current_balance)
    if diff_val > 0.01:
        try:
            from utils.partner_balance_updater import update_partner_balance_components
            from sqlalchemy.orm import sessionmaker
            SessionFactory = sessionmaker(bind=db.engine)
            session = SessionFactory()
            try:
                update_partner_balance_components(partner_id, session)
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            pass
        
        db.session.refresh(partner)
        current_balance = float(partner.current_balance or 0)
        diff_val2 = abs(float(balance_unified) - current_balance)
        if diff_val2 > 0.01:
            from flask import current_app
            current_app.logger.warning(
                f"⚠️ عدم تطابق الرصيد في كشف حساب الشريك {partner_id}: "
                f"current_balance={current_balance}, calculated_balance={float(balance_unified)}, "
                f"difference={diff_val2}"
            )
        else:
            balance_unified = current_balance
    
    balance_breakdown = None
    if balance_data and balance_data.get("success"):
        rights_info = balance_data.get("rights") or {}
        obligations_info = balance_data.get("obligations") or {}
        
        def _section_total(section):
            if isinstance(section, dict):
                for key in ("total_ils", "total_share_ils", "total", "amount"):
                    val = section.get(key)
                    if val not in (None, ""):
                        return float(val)
            return float(section or 0.0)
        
        rights_items = []
        inventory_total = _section_total(rights_info.get("inventory"))
        if inventory_total:
            rights_items.append({"label": "نصيب المخزون", "amount": inventory_total})
        sales_share_total = _section_total(rights_info.get("sales_share"))
        if sales_share_total:
            rights_items.append({"label": "نصيب المبيعات", "amount": sales_share_total})
        
        obligations_items = []
        sales_to_partner_total = _section_total(obligations_info.get("sales_to_partner"))
        if sales_to_partner_total:
            obligations_items.append({"label": "مبيعات له", "amount": sales_to_partner_total})
        service_fees_total = _section_total(obligations_info.get("service_fees"))
        if service_fees_total:
            obligations_items.append({"label": "رسوم صيانة", "amount": service_fees_total})
        preorders_to_partner_total = _section_total(obligations_info.get("preorders_to_partner"))
        if preorders_to_partner_total:
            obligations_items.append({"label": "حجوزات له", "amount": preorders_to_partner_total})
        damaged_items_total = _section_total(obligations_info.get("damaged_items"))
        if damaged_items_total:
            obligations_items.append({"label": "قطع تالفة", "amount": damaged_items_total})
        
        balance_breakdown = {
            **balance_data,
            "rights": {**rights_info, "items": rights_items},
            "obligations": {**obligations_info, "items": obligations_items},
        }
    else:
        try:
            from utils.partner_balance_updater import build_partner_balance_view
            balance_breakdown = build_partner_balance_view(partner_id, db.session)
            if balance_breakdown and balance_breakdown.get("success"):
                model_balance = float(partner.current_balance or 0)
                calculated_balance = balance_breakdown.get("balance", {}).get("amount", 0)
                if abs(model_balance - calculated_balance) > 0.01:
                    current_app.logger.warning(
                        f"Partner {partner_id} balance mismatch: model={model_balance}, calculated={calculated_balance}"
                    )
        except Exception as exc:
            current_app.logger.warning("partner_balance_breakdown_statement_failed: %s", exc)
    
    inventory_items = []
    try:
        from models import WarehousePartnerShare, StockLevel, Product, Warehouse, _find_partner_share_percentage
        
        shares_q = db.session.query(WarehousePartnerShare).filter(
            WarehousePartnerShare.partner_id == partner.id
        ).all()
        
        for share in shares_q:
            warehouse_id = share.warehouse_id
            product_id = share.product_id
            
            if warehouse_id and product_id:
                stock = db.session.query(StockLevel).filter(
                    StockLevel.warehouse_id == warehouse_id,
                    StockLevel.product_id == product_id,
                    StockLevel.quantity > 0
                ).first()
                
                if stock:
                    product = db.session.get(Product, product_id)
                    warehouse = db.session.get(Warehouse, warehouse_id)
                    
                    if product and warehouse:
                        share_pct = float(share.share_percentage or 0)
                        product_value = float(stock.quantity) * float(product.purchase_price or 0)
                        partner_share_value = product_value * (share_pct / 100.0) if share_pct else 0.0
                        
                        inventory_items.append({
                            'product_name': product.name,
                            'sku': product.sku or '—',
                            'warehouse_name': warehouse.name,
                            'quantity': stock.quantity,
                            'purchase_price': float(product.purchase_price or 0),
                            'product_value': product_value,
                            'share_pct': share_pct,
                            'partner_share_value': partner_share_value
                        })
            elif warehouse_id:
                warehouse = db.session.get(Warehouse, warehouse_id)
                if warehouse:
                    stocks = db.session.query(StockLevel, Product).join(
                        Product, Product.id == StockLevel.product_id
                    ).filter(
                        StockLevel.warehouse_id == warehouse_id,
                        StockLevel.quantity > 0
                    ).all()
                    
                    for stock, product in stocks:
                        share_pct = _find_partner_share_percentage(partner.id, product.id, warehouse_id)
                        product_value = float(stock.quantity) * float(product.purchase_price or 0)
                        partner_share_value = product_value * (share_pct / 100.0) if share_pct else 0.0
                        
                        inventory_items.append({
                            'product_name': product.name,
                            'sku': product.sku or '—',
                            'warehouse_name': warehouse.name,
                            'quantity': stock.quantity,
                            'purchase_price': float(product.purchase_price or 0),
                            'product_value': product_value,
                            'share_pct': share_pct,
                            'partner_share_value': partner_share_value
                        })
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"Error fetching partner inventory: {e}")
        except Exception:
            pass
    
    all_partner_products = []
    try:
        from models import ProductPartner, WarehousePartnerShare, Product, Warehouse, StockLevel, SaleLine, Sale, SaleStatus
        
        product_shares = db.session.query(
            ProductPartner.product_id,
            ProductPartner.share_percent,
            db.null().label('warehouse_id')
        ).filter(
            ProductPartner.partner_id == partner.id,
            ProductPartner.share_percent > 0
        ).all()
        
        warehouse_shares = db.session.query(
            WarehousePartnerShare.product_id,
            WarehousePartnerShare.share_percentage.label('share_percent'),
            WarehousePartnerShare.warehouse_id
        ).filter(
            WarehousePartnerShare.partner_id == partner.id,
            WarehousePartnerShare.share_percentage > 0
        ).all()
        
        all_shares = {}
        for ps in product_shares:
            key = (ps.product_id, None)
            if key not in all_shares or (ps.share_percent or 0) > (all_shares[key].get('share_percent', 0) or 0):
                all_shares[key] = {
                    'product_id': ps.product_id,
                    'warehouse_id': None,
                    'share_percent': float(ps.share_percent or 0)
                }
        
        for ws in warehouse_shares:
            key = (ws.product_id, ws.warehouse_id)
            if key not in all_shares or (ws.share_percent or 0) > (all_shares[key].get('share_percent', 0) or 0):
                all_shares[key] = {
                    'product_id': ws.product_id,
                    'warehouse_id': ws.warehouse_id,
                    'share_percent': float(ws.share_percent or 0)
                }
        
        for key, share_info in all_shares.items():
            product_id = share_info['product_id']
            warehouse_id = share_info['warehouse_id']
            share_pct = share_info['share_percent']
            
            product = db.session.get(Product, product_id)
            if not product:
                continue
            
            warehouse = db.session.get(Warehouse, warehouse_id) if warehouse_id else None
            
            stock_qty = 0
            if warehouse_id:
                stock = db.session.query(StockLevel).filter(
                    StockLevel.warehouse_id == warehouse_id,
                    StockLevel.product_id == product_id
                ).first()
                if stock:
                    stock_qty = stock.quantity or 0
            else:
                total_stock = db.session.query(func.sum(StockLevel.quantity)).filter(
                    StockLevel.product_id == product_id,
                    StockLevel.quantity > 0
                ).scalar() or 0
                stock_qty = total_stock
            
            sold_qty = 0
            if df or dt:
                sale_filter = SaleLine.product_id == product_id
                if warehouse_id:
                    sale_filter = and_(sale_filter, SaleLine.warehouse_id == warehouse_id)
                if df:
                    sale_filter = and_(sale_filter, Sale.sale_date >= df)
                if dt:
                    sale_filter = and_(sale_filter, Sale.sale_date < dt)
                
                sold_result = db.session.query(func.sum(SaleLine.quantity)).join(
                    Sale, Sale.id == SaleLine.sale_id
                ).filter(
                    sale_filter,
                    Sale.status == SaleStatus.CONFIRMED.value
                ).scalar() or 0
                sold_qty = sold_result
            else:
                sale_filter = SaleLine.product_id == product_id
                if warehouse_id:
                    sale_filter = and_(sale_filter, SaleLine.warehouse_id == warehouse_id)
                
                sold_result = db.session.query(func.sum(SaleLine.quantity)).join(
                    Sale, Sale.id == SaleLine.sale_id
                ).filter(
                    sale_filter,
                    Sale.status == SaleStatus.CONFIRMED.value
                ).scalar() or 0
                sold_qty = sold_result
            
            status = "غير مباع" if stock_qty > 0 else ("مباع" if sold_qty > 0 else "لا يوجد")
            
            all_partner_products.append({
                'product_id': product_id,
                'product_name': product.name,
                'sku': product.sku or '—',
                'warehouse_id': warehouse_id,
                'warehouse_name': warehouse.name if warehouse else 'كل المستودعات',
                'share_pct': share_pct,
                'stock_qty': stock_qty,
                'sold_qty': sold_qty,
                'status': status,
                'purchase_price': float(product.purchase_price or 0),
                'selling_price': float(product.selling_price or 0)
            })
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"Error fetching all partner products: {e}")
        except Exception:
            pass
    
    # ✅ إضافة نسبة الشريك في المخزون غير المباع (حسب سعر التكلفة)
    if inventory_items:
        total_inventory_share = sum(item.get('partner_share_value', 0) for item in inventory_items)
        total_inventory_share_decimal = q2(total_inventory_share)
        
        if total_inventory_share_decimal > 0:
            # استخدام تاريخ آخر معاملة أو تاريخ الشريك
            inventory_date = entries[-1]["date"] if entries else (df if df else partner.created_at)
            
            entries.append({
                "date": inventory_date,
                "type": "PARTNER_INVENTORY_SHARE",
                "ref": "INV-SHARE",
                "statement": f"نسبة في المخزون غير المباع ({len(inventory_items)} منتج)",
                "debit": Decimal("0.00"),
                "credit": total_inventory_share_decimal,  # ✓ نسبة من سعر التكلفة (له علينا)
                "notes": f"حسب سعر التكلفة - إجمالي {len(inventory_items)} منتج"
            })
            total_credit += total_inventory_share_decimal

    if is_ajax:
        entries_json = []
        for e in out[:50]:
            d = e.get("date")
            ds = d.strftime("%Y-%m-%d") if isinstance(d, datetime) else (d or "")
            entries_json.append({
                "date": ds,
                "type": e.get("type"),
                "ref": e.get("ref"),
                "debit": float(e.get("debit", 0)),
                "credit": float(e.get("credit", 0)),
                "balance": float(e.get("balance", 0)),
            })
        return jsonify({
            "success": True,
            "entries": entries_json,
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "balance": float(balance_unified),
            "date_from": (df.strftime("%Y-%m-%d") if df else None),
            "date_to": ((dt - timedelta(days=1)).strftime("%Y-%m-%d") if dt else None),
        })
    return render_template(
        "vendors/partners/statement.html",
        partner=partner,
        ledger_entries=out,
        total_debit=total_debit,
        total_credit=total_credit,
        balance=float(balance_unified),
        balance_data=balance_data,
        balance_breakdown=balance_breakdown,
        inventory_items=inventory_items,
        all_partner_products=all_partner_products,
        date_from=df if df else None,
        date_to=(dt - timedelta(days=1)) if dt else None,
    )

@vendors_bp.route("/partners/new", methods=["GET", "POST"], endpoint="partners_create")
@login_required
def partners_create():
    form = PartnerForm()
    if form.validate_on_submit():
        partner = Partner()
        form.apply_to(partner)
        db.session.add(partner)
        try:
            db.session.commit()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
                return jsonify({"success": True, "id": partner.id, "name": partner.name})
            flash("✅ تم إضافة الشريك بنجاح", "success")
            return redirect(url_for("vendors_bp.partners_list"))
        except SQLAlchemyError as e:
            db.session.rollback()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
                current_app.logger.exception('API error')
                return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
            flash(f"❌ خطأ أثناء إضافة الشريك: {e}", "danger")
    else:
        if request.method == "POST":
            current_app.logger.warning(f"[WARNING] Partner Form validation errors: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"خطأ في {field}: {error}", "danger")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1":
        html = render_template("vendors/partners/form.html", form=form, partner=None)
        return jsonify({"success": True, "html": html})
    return render_template("vendors/partners/form.html", form=form, partner=None)

@vendors_bp.route("/partners/<int:id>/edit", methods=["GET", "POST"], endpoint="partners_edit")
@login_required
def partners_edit(id):
    partner = _get_or_404(Partner, id)
    form = PartnerForm(obj=partner)
    form.obj_id = partner.id
    if form.validate_on_submit():
        form.apply_to(partner)
        try:
            db.session.commit()
            flash("✅ تم تحديث الشريك بنجاح", "success")
            return redirect(url_for("vendors_bp.partners_list"))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(f"❌ خطأ أثناء تحديث الشريك: {e}", "danger")
    return render_template("vendors/partners/form.html", form=form, partner=partner)

@vendors_bp.route("/partners/<int:id>/delete", methods=["POST"], endpoint="partners_delete")
@login_required
def partners_delete(id):
    partner = _get_or_404(Partner, id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal") == "1"
    try:
        linked_wh = (
            db.session.query(Warehouse)
            .filter(Warehouse.partner_id == partner.id)
            .all()
        )
        bad_wh = [
            w for w in linked_wh
            if getattr(w.warehouse_type, "value", w.warehouse_type) == WarehouseType.PARTNER.value
        ]
        if bad_wh:
            msg = "لا يمكن حذف الشريك لوجود مستودعات نوع PARTNER مرتبطة به."
            details = [{"id": w.id, "name": w.name} for w in bad_wh]
            if is_ajax:
                return jsonify({"success": False, "error": "has_partner_warehouses", "detail": msg, "warehouses": details}), 400
            else:
                names = "، ".join(f"#{w['id']} - {w['name']}" for w in details)
                flash(f"❌ {msg} المستودعات: {names}", "danger")
                return redirect(url_for("vendors_bp.partners_list"))
        db.session.delete(partner)
        db.session.commit()
        if is_ajax:
            return jsonify({"success": True}), 200
        flash("✅ تم حذف الشريك بنجاح", "success")
        return redirect(url_for("vendors_bp.partners_list"))
    except Exception as e:
        db.session.rollback()
        if is_ajax:
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 400
        flash(f"❌ خطأ أثناء حذف الشريك: {e}", "danger")
        return redirect(url_for("vendors_bp.partners_list"))


@vendors_bp.route("/suppliers/<int:supplier_id>/smart-settlement", methods=["GET"], endpoint="supplier_smart_settlement")
@login_required
def supplier_smart_settlement(supplier_id):
    params = {}
    if request.args.get('date_from'):
        params['date_from'] = request.args.get('date_from')
    if request.args.get('date_to'):
        params['date_to'] = request.args.get('date_to')
    
    return redirect(url_for('supplier_settlements_bp.supplier_settlement', 
                           supplier_id=supplier_id, **params))


@vendors_bp.route("/partners/<int:partner_id>/smart-settlement", methods=["GET"], endpoint="partner_smart_settlement")
@login_required
def partner_smart_settlement(partner_id):
    """التسوية الذكية للشريك"""
    partner = _get_or_404(Partner, partner_id)
    
    # الحصول على الفترة الزمنية
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    if date_from:
        date_from = datetime.fromisoformat(date_from)
    else:
        date_from = datetime(2024, 1, 1)
    
    if date_to:
        date_to = datetime.fromisoformat(date_to)
    else:
        date_to = _utcnow_naive()
    
    # حساب الرصيد الذكي
    from routes.partner_settlements import _calculate_smart_partner_balance
    balance_data = _calculate_smart_partner_balance(partner_id, date_from, date_to)
    
    # إنشاء object بسيط للتوافق مع القالب
    from types import SimpleNamespace
    ps = SimpleNamespace(
        id=None,  # لا يوجد id لأنها تسوية ذكية (غير محفوظة)
        partner=partner,
        from_date=date_from,
        to_date=date_to,
        currency=partner.currency,
        total_gross=balance_data.get("incoming", {}).get("total", 0) if isinstance(balance_data, dict) else 0,
        total_due=balance_data.get("balance", {}).get("amount", 0) if isinstance(balance_data, dict) else 0,
        status="DRAFT",
        code=f"PS-SMART-{partner_id}-{date_from.strftime('%Y%m%d')}",
        lines=[],
        created_at=date_from,
        updated_at=_utcnow_naive()
    )
    
    # توجيه للـ endpoint الجديد
    params = {}
    if request.args.get('date_from'):
        params['date_from'] = request.args.get('date_from')
    if request.args.get('date_to'):
        params['date_to'] = request.args.get('date_to')
    
    return redirect(url_for('partner_settlements_bp.partner_settlement', 
                           partner_id=partner_id, **params))


def _calculate_supplier_incoming(supplier_id: int, date_from: datetime, date_to: datetime):
    """حساب الوارد من المورد مع تحويل العملات"""
    from decimal import Decimal
    from models import convert_amount
    
    # المشتريات (النفقات من نوع مشتريات) - مع تحويل العملات
    expenses = Expense.query.filter(
        or_(
            Expense.supplier_id == supplier_id,
            and_(Expense.payee_type == "SUPPLIER", Expense.payee_entity_id == supplier_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).all()
    
    purchases = Decimal('0.00')
    for exp in expenses:
        amt = Decimal(str(exp.amount or 0))
        if exp.currency == "ILS":
            purchases += amt
        else:
            try:
                purchases += convert_amount(amt, exp.currency, "ILS", exp.date)
            except Exception:
                pass
    
    # القطع المعطاة للمورد (ExchangeTransaction مع اتجاه OUT)
    exchanges = ExchangeTransaction.query.filter(
        ExchangeTransaction.supplier_id == supplier_id,
        ExchangeTransaction.direction == "OUT",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).all()
    
    products_given = Decimal('0.00')
    for ex in exchanges:
        amt = Decimal(str(ex.quantity or 0)) * Decimal(str(ex.unit_cost or 0))
        ex_currency = getattr(ex, 'currency', 'ILS')
        if ex_currency == "ILS":
            products_given += amt
        else:
            try:
                products_given += convert_amount(amt, ex_currency, "ILS", ex.created_at)
            except Exception:
                pass
    
    return {
        "purchases": float(purchases),
        "products_given": float(products_given),
        "total": float(purchases + products_given)
    }


def _calculate_supplier_outgoing(supplier_id: int, date_from: datetime, date_to: datetime):
    from routes.supplier_settlements import _get_sales_to_supplier
    return _get_sales_to_supplier(supplier_id, date_from, date_to)


def _calculate_partner_incoming(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الوارد من الشريك مع تحويل العملات"""
    from decimal import Decimal
    from models import convert_amount
    
    # حصة الشريك من المبيعات (من خلال ServicePart)
    service_parts = db.session.query(ServicePart, ServiceRequest).join(
        ServiceRequest, ServiceRequest.id == ServicePart.service_id
    ).filter(
        ServicePart.partner_id == partner_id,
        ServiceRequest.received_at >= date_from,
        ServiceRequest.received_at <= date_to
    ).all()
    
    sales_share = Decimal('0.00')
    for sp, sr in service_parts:
        amt = Decimal(str(sp.quantity or 0)) * Decimal(str(sp.unit_price or 0))
        sr_currency = getattr(sr, 'currency', 'ILS')
        if sr_currency == "ILS":
            sales_share += amt
        else:
            try:
                sales_share += convert_amount(amt, sr_currency, "ILS", sr.received_at)
            except Exception:
                pass
    
    # القطع المعطاة للشريك
    exchanges = ExchangeTransaction.query.filter(
        ExchangeTransaction.partner_id == partner_id,
        ExchangeTransaction.direction == "OUT",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).all()
    
    products_given = Decimal('0.00')
    for ex in exchanges:
        amt = Decimal(str(ex.quantity or 0)) * Decimal(str(ex.unit_cost or 0))
        ex_currency = getattr(ex, 'currency', 'ILS')
        if ex_currency == "ILS":
            products_given += amt
        else:
            try:
                products_given += convert_amount(amt, ex_currency, "ILS", ex.created_at)
            except Exception:
                pass
    
    return {
        "sales_share": float(sales_share),
        "products_given": float(products_given),
        "total": float(sales_share + products_given)
    }


def _calculate_partner_outgoing(partner_id: int, date_from: datetime, date_to: datetime):
    """حساب الصادر للشريك مع تحويل العملات"""
    from decimal import Decimal
    from models import convert_amount
    
    # حصة الشريك من المشتريات - مع تحويل العملات
    expenses = Expense.query.filter(
        or_(
            Expense.partner_id == partner_id,
            and_(Expense.payee_type == "PARTNER", Expense.payee_entity_id == partner_id)
        ),
        Expense.date >= date_from,
        Expense.date <= date_to
    ).all()
    
    purchases_share = Decimal('0.00')
    for exp in expenses:
        amt = Decimal(str(exp.amount or 0))
        if exp.currency == "ILS":
            purchases_share += amt
        else:
            try:
                purchases_share += convert_amount(amt, exp.currency, "ILS", exp.date)
            except Exception:
                pass
    
    # القطع المأخوذة من الشريك
    exchanges = ExchangeTransaction.query.filter(
        ExchangeTransaction.partner_id == partner_id,
        ExchangeTransaction.direction == "IN",
        ExchangeTransaction.created_at >= date_from,
        ExchangeTransaction.created_at <= date_to
    ).all()
    
    products_taken = Decimal('0.00')
    for ex in exchanges:
        amt = Decimal(str(ex.quantity or 0)) * Decimal(str(ex.unit_cost or 0))
        ex_currency = getattr(ex, 'currency', 'ILS')
        if ex_currency == "ILS":
            products_taken += amt
        else:
            try:
                products_taken += convert_amount(amt, ex_currency, "ILS", ex.created_at)
            except Exception:
                pass
    
    return {
        "purchases_share": float(purchases_share),
        "products_taken": float(products_taken),
        "total": float(purchases_share + products_taken)
    }


def _calculate_payments_to_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    from routes.supplier_settlements import _get_payments_to_supplier
    supplier = db.session.get(Supplier, supplier_id)
    result = _get_payments_to_supplier(supplier_id, supplier, date_from, date_to)
    return result.get("total_ils", 0.0)


def _calculate_payments_from_supplier(supplier_id: int, date_from: datetime, date_to: datetime):
    from routes.supplier_settlements import _get_payments_from_supplier
    supplier = db.session.get(Supplier, supplier_id)
    result = _get_payments_from_supplier(supplier_id, supplier, date_from, date_to)
    return result.get("total_ils", 0.0)


def _calculate_payments_to_partner(partner_id: int, date_from: datetime, date_to: datetime):
    from routes.partner_settlements import _get_payments_to_partner
    partner = db.session.get(Partner, partner_id)
    result = _get_payments_to_partner(partner_id, partner, date_from, date_to)
    return result.get("total_ils", 0.0)


def _calculate_payments_from_partner(partner_id: int, date_from: datetime, date_to: datetime):
    from routes.partner_settlements import _get_partner_payments_received
    partner = db.session.get(Partner, partner_id)
    result = _get_partner_payments_received(partner_id, partner, date_from, date_to)
    return result.get("total_ils", 0.0)


def _get_settlement_recommendation(balance: float, currency: str):
    """اقتراح التسوية"""
    balance_view = classify_entity_balance(balance)
    if balance_view["is_settled"]:
        return {
            "action": "متوازن",
            "message": "لا توجد تسوية مطلوبة",
            "amount": 0
        }
    elif balance_view["balance"] > 0:  # الباقي له
        return {
            "action": "دفع",
            "message": f"يجب دفع {balance_view['owed_by_us']:.2f} {currency} للمورد/الشريك",
            "amount": balance_view["owed_by_us"],
            "direction": "OUTGOING"
        }
    else:  # الباقي عليه
        return {
            "action": "قبض",
            "message": f"يجب قبض {balance_view['owed_to_us']:.2f} {currency} من المورد/الشريك",
            "amount": balance_view["owed_to_us"],
            "direction": "INCOMING"
        }

@vendors_bp.route("/suppliers/archive/<int:supplier_id>", methods=["POST"])
@login_required
def archive_supplier(supplier_id):
    
    try:
        from models import Archive
        
        supplier = db.get_or_404(Supplier, supplier_id)
        
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        utils.archive_record(supplier, reason, current_user.id)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'تم أرشفة المورد {supplier.name} بنجاح'})
            
        flash(f'تم أرشفة المورد {supplier.name} بنجاح', 'success')
        return redirect(url_for('vendors_bp.suppliers_list'))
        
    except Exception as e:
        
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
            
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('vendors_bp.suppliers_list'))

@vendors_bp.route("/partners/archive/<int:partner_id>", methods=["POST"])
@login_required
def archive_partner(partner_id):
    """أرشفة شريك"""
    
    try:
        from models import Archive
        
        partner = db.get_or_404(Partner, partner_id)
        
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        utils.archive_record(partner, reason, current_user.id)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'تم أرشفة الشريك {partner.name} بنجاح'})
            
        flash(f'تم أرشفة الشريك {partner.name} بنجاح', 'success')
        return redirect(url_for('vendors_bp.partners_list'))
        
    except Exception as e:
        
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
            
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('vendors_bp.partners_list'))

@vendors_bp.route("/suppliers/restore/<int:supplier_id>", methods=["POST"])
@login_required
def restore_supplier(supplier_id):
    """استعادة مورد"""
    
    try:
        supplier = db.get_or_404(Supplier, supplier_id)
        
        if not supplier.is_archived:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'المورد غير مؤرشف'}), 400
            flash('المورد غير مؤرشف', 'warning')
            return redirect(url_for('vendors_bp.suppliers_list'))
        
        # البحث عن الأرشيف
        from models import Archive
        archive = Archive.query.filter_by(
            record_type='suppliers',
            record_id=supplier_id
        ).first()
        
        if archive:
            utils.restore_record(archive.id)
        else:
            # Fallback if archive record missing
            supplier.is_archived = False
            supplier.archived_at = None
            db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'تم استعادة المورد {supplier.name} بنجاح'})
            
        flash(f'تم استعادة المورد {supplier.name} بنجاح', 'success')
        return redirect(url_for('vendors_bp.suppliers_list'))
        
    except Exception as e:
        
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
            
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('vendors_bp.suppliers_list'))

@vendors_bp.route("/partners/restore/<int:partner_id>", methods=["POST"])
@login_required
def restore_partner(partner_id):
    """استعادة شريك"""
    
    try:
        partner = db.get_or_404(Partner, partner_id)
        
        if not partner.is_archived:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'الشريك غير مؤرشف'}), 400
            flash('الشريك غير مؤرشف', 'warning')
            return redirect(url_for('vendors_bp.partners_list'))
        
        # البحث عن الأرشيف
        from models import Archive
        archive = Archive.query.filter_by(
            record_type='partners',
            record_id=partner_id
        ).first()
        
        if archive:
            utils.restore_record(archive.id)
        else:
            # Fallback if archive record missing
            partner.is_archived = False
            partner.archived_at = None
            db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'تم استعادة الشريك {partner.name} بنجاح'})
            
        flash(f'تم استعادة الشريك {partner.name} بنجاح', 'success')
        return redirect(url_for('vendors_bp.partners_list'))
        
    except Exception as e:
        
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500
            
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('vendors_bp.partners_list'))
def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)
