
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from permissions_config.enums import SystemPermissions
from flask import Blueprint, request, jsonify, render_template, current_app, abort
from flask_login import login_required, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func, and_, or_, desc, case
from extensions import db, perform_backup_db, cache
import utils
from models import (
    Sale, SaleReturn, Expense, Payment, ServiceRequest,
    Customer, Supplier, Partner,
    Product, StockLevel, GLBatch, GLEntry, Account,
    Invoice, PreOrder, Shipment, Employee,
    PaymentSplit, PaymentEntityType, GL_ACCOUNTS, AuditLog,
    SaleLine, ServicePart
)
from services.ledger_service import (
    SmartEntityExtractor, LedgerQueryOptimizer, CurrencyConverter,
    LedgerStatisticsCalculator, LedgerCache
)

csrf = CSRFProtect()

ledger_bp = Blueprint("ledger", __name__, url_prefix="/ledger")


@ledger_bp.before_request
def _restrict_super_admin():
    # تمت إزالة القيد للسماح للسوبر أدمن بالوصول
    pass

def extract_entity_from_batch(batch: GLBatch):
    return SmartEntityExtractor.extract_from_batch(batch)

def _parse_ledger_date_range(from_date_str: str | None, to_date_str: str | None):
    from_date = datetime.strptime(from_date_str, "%Y-%m-%d") if from_date_str else None
    to_date = (
        datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        if to_date_str
        else None
    )
    return from_date, to_date

def _calculate_ledger_statistics(from_date: datetime | None, to_date: datetime | None):
    cache_key = f"ledger_statistics_{from_date.strftime('%Y%m%d') if from_date else 'all'}_{to_date.strftime('%Y%m%d') if to_date else 'all'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    base_gl = db.session.query(GLEntry).join(GLBatch).filter(GLBatch.status == "POSTED")
    if from_date:
        base_gl = base_gl.filter(GLBatch.posted_at >= from_date)
    if to_date:
        base_gl = base_gl.filter(GLBatch.posted_at <= to_date)

    sales_accounts = {GL_ACCOUNTS.get("SALES", "4000_SALES"), GL_ACCOUNTS.get("REV", "4000_SALES")}
    sales_accounts = [acc for acc in sales_accounts if acc]
    service_rev_account = GL_ACCOUNTS.get("SERVICE_REV", "4100_SERVICE_REVENUE")
    discount_account = GL_ACCOUNTS.get("DISCOUNT_ALLOWED", "4050_SALES_DISCOUNT")
    shipping_income_account = GL_ACCOUNTS.get("SHIPPING_INCOME", "4200_SHIPPING_INCOME")

    total_sales = float(
        (base_gl.filter(GLEntry.account.in_(sales_accounts)).with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0)
    )
    total_services = float(
        (base_gl.filter(GLEntry.account == service_rev_account).with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0)
    )
    total_discounts = float(
        (base_gl.filter(GLEntry.account == discount_account).with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0)
    )
    total_shipping_income = float(
        (base_gl.filter(GLEntry.account == shipping_income_account).with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0)
    )

    revenue_base = base_gl.join(Account, Account.code == GLEntry.account).filter(Account.type == "REVENUE")
    total_revenue = float(
        (revenue_base.with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0)
    )
    other_revenue = total_revenue - total_sales - total_services - total_discounts - total_shipping_income

    cogs_exchange_account = GL_ACCOUNTS.get("COGS_EXCHANGE", "5105_COGS_EXCHANGE")

    expense_base = base_gl.join(Account, Account.code == GLEntry.account).filter(Account.type == "EXPENSE")
    total_cogs = float(
        (
            expense_base.filter(or_(GLEntry.account.like("51%"), GLEntry.account == cogs_exchange_account))
            .with_entities(func.sum(GLEntry.debit - GLEntry.credit))
            .scalar()
            or 0
        )
    )
    if total_cogs < 0:
        total_cogs = abs(total_cogs)
    tax_expense_account = GL_ACCOUNTS.get("INCOME_TAX_EXP", "6200_INCOME_TAX_EXPENSE")
    total_taxes = float(
        (
            expense_base.filter(
                or_(
                    Account.name.ilike("%tax%"),
                    Account.name.ilike("%ضريبة%"),
                    GLEntry.account == tax_expense_account,
                )
            )
            .with_entities(func.sum(GLEntry.debit - GLEntry.credit))
            .scalar()
            or 0
        )
    )
    if total_taxes < 0:
        total_taxes = abs(total_taxes)
    operating_expenses = float(
        (
            expense_base.filter(
                ~GLEntry.account.like("51%"),
                GLEntry.account != cogs_exchange_account,
                ~or_(
                    Account.name.ilike("%tax%"),
                    Account.name.ilike("%ضريبة%"),
                    GLEntry.account == tax_expense_account,
                ),
            )
            .with_entities(func.sum(GLEntry.debit - GLEntry.credit))
            .scalar()
            or 0
        )
    )
    if operating_expenses < 0:
        operating_expenses = abs(operating_expenses)

    cogs_details_rows = (
        expense_base.filter(or_(GLEntry.account.like("51%"), GLEntry.account == cogs_exchange_account))
        .with_entities(
            GLEntry.account.label("account"),
            Account.name.label("name"),
            func.sum(GLEntry.debit - GLEntry.credit).label("amount"),
        )
        .group_by(GLEntry.account, Account.name)
        .having(func.sum(GLEntry.debit - GLEntry.credit) != 0)
        .order_by(func.sum(GLEntry.debit - GLEntry.credit).desc())
        .limit(10)
        .all()
    )
    cogs_details = [{"account": r.account, "name": r.name, "amount": float(r.amount or 0)} for r in cogs_details_rows]

    fx_anchor_date = (to_date or from_date or datetime.now(timezone.utc).replace(tzinfo=None))

    total_service_costs = 0.0
    unit_cost_expr = case(
        (func.coalesce(Product.purchase_price, 0) > 0, Product.purchase_price),
        (func.coalesce(Product.cost_after_shipping, 0) > 0, Product.cost_after_shipping),
        (func.coalesce(Product.cost_before_shipping, 0) > 0, Product.cost_before_shipping),
        (func.coalesce(Product.price, 0) > 0, Product.price * 0.70),
        else_=0,
    )
    service_parts_base = (
        db.session.query(
            func.coalesce(Product.currency, "ILS").label("currency"),
            func.sum(ServicePart.quantity * unit_cost_expr).label("value"),
        )
        .join(Product, Product.id == ServicePart.part_id)
        .join(ServiceRequest, ServiceRequest.id == ServicePart.service_id)
    )
    service_date_expr = func.coalesce(ServiceRequest.completed_at, ServiceRequest.created_at)
    service_parts_base = service_parts_base.filter(ServiceRequest.status == "COMPLETED")
    if from_date:
        service_parts_base = service_parts_base.filter(service_date_expr >= from_date)
    if to_date:
        service_parts_base = service_parts_base.filter(service_date_expr <= to_date)
    service_parts_groups = service_parts_base.group_by(func.coalesce(Product.currency, "ILS")).all()
    for row in service_parts_groups:
        value = float(row.value or 0)
        currency = (row.currency or "ILS").upper()
        if currency == "ILS":
            total_service_costs += value
        else:
            rate = LedgerCache.get_fx_rate(currency, "ILS", fx_anchor_date) or 1.0
            total_service_costs += float(value * float(rate))

    total_preorders = 0.0
    preorder_group_q = db.session.query(
        func.coalesce(PreOrder.currency, "ILS").label("currency"),
        func.sum(PreOrder.total_amount).label("total_amount"),
    )
    if from_date:
        preorder_group_q = preorder_group_q.filter(PreOrder.created_at >= from_date)
    if to_date:
        preorder_group_q = preorder_group_q.filter(PreOrder.created_at <= to_date)
    preorder_groups = preorder_group_q.group_by(func.coalesce(PreOrder.currency, "ILS")).all()
    for row in preorder_groups:
        amount = float(row.total_amount or 0)
        currency = (row.currency or "ILS").upper()
        if currency == "ILS":
            total_preorders += amount
        else:
            rate = LedgerCache.get_fx_rate(currency, "ILS", fx_anchor_date) or 1.0
            total_preorders += float(amount * float(rate))

    total_stock_value_stats = 0.0
    total_stock_qty_stats = 0
    stock_groups = (
        db.session.query(
            func.coalesce(Product.currency, "ILS").label("currency"),
            func.sum(StockLevel.quantity).label("qty"),
            func.sum(StockLevel.quantity * func.coalesce(Product.purchase_price, 0)).label("value"),
        )
        .join(StockLevel, StockLevel.product_id == Product.id)
        .filter(StockLevel.quantity > 0)
        .group_by(func.coalesce(Product.currency, "ILS"))
        .all()
    )
    for row in stock_groups:
        qty = float(row.qty or 0)
        value = float(row.value or 0)
        currency = (row.currency or "ILS").upper()
        total_stock_qty_stats += int(qty)
        if currency == "ILS":
            total_stock_value_stats += value
        else:
            rate = LedgerCache.get_fx_rate(currency, "ILS", fx_anchor_date) or 1.0
            total_stock_value_stats += float(value * float(rate))

    has_any_cost_expr = or_(
        func.coalesce(Product.purchase_price, 0) > 0,
        func.coalesce(Product.cost_after_shipping, 0) > 0,
        func.coalesce(Product.cost_before_shipping, 0) > 0,
    )
    has_price_expr = func.coalesce(Product.price, 0) > 0

    sale_lines_base = (
        db.session.query(SaleLine)
        .join(Product, Product.id == SaleLine.product_id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .filter(Sale.status == "CONFIRMED")
    )
    if from_date:
        sale_lines_base = sale_lines_base.filter(Sale.sale_date >= from_date)
    if to_date:
        sale_lines_base = sale_lines_base.filter(Sale.sale_date <= to_date)

    estimated_count = int(
        (sale_lines_base.filter(~has_any_cost_expr, has_price_expr).with_entities(func.count(SaleLine.id)).scalar() or 0)
    )
    no_cost_count = int(
        (sale_lines_base.filter(~has_any_cost_expr, ~has_price_expr).with_entities(func.count(SaleLine.id)).scalar() or 0)
    )

    estimated_products_rows = (
        sale_lines_base.filter(~has_any_cost_expr, has_price_expr)
        .with_entities(
            Product.id.label("id"),
            Product.name.label("name"),
            Product.price.label("selling_price"),
            Product.currency.label("currency"),
            func.sum(SaleLine.quantity).label("qty_sold"),
        )
        .group_by(Product.id, Product.name, Product.price, Product.currency)
        .order_by(func.sum(SaleLine.quantity).desc())
        .limit(200)
        .all()
    )
    estimated_products = [
        {
            "id": int(r.id),
            "name": r.name,
            "selling_price": (
                float(r.selling_price or 0)
                if (r.currency or "ILS").upper() == "ILS"
                else float(float(r.selling_price or 0) * float(LedgerCache.get_fx_rate((r.currency or "ILS").upper(), "ILS", fx_anchor_date) or 1.0))
            ),
            "estimated_cost": (
                float(float(r.selling_price or 0) * 0.70)
                if (r.currency or "ILS").upper() == "ILS"
                else float(float(r.selling_price or 0) * 0.70 * float(LedgerCache.get_fx_rate((r.currency or "ILS").upper(), "ILS", fx_anchor_date) or 1.0))
            ),
            "qty_sold": float(r.qty_sold or 0),
        }
        for r in estimated_products_rows
    ]

    products_without_cost_rows = (
        sale_lines_base.filter(~has_any_cost_expr, ~has_price_expr)
        .with_entities(
            Product.id.label("id"),
            Product.name.label("name"),
            func.sum(SaleLine.quantity).label("qty_sold"),
        )
        .group_by(Product.id, Product.name)
        .order_by(func.sum(SaleLine.quantity).desc())
        .limit(200)
        .all()
    )
    products_without_cost = [
        {"id": int(r.id), "name": r.name, "qty_sold": float(r.qty_sold or 0)} for r in products_without_cost_rows
    ]

    gross_profit_sales = total_sales - total_cogs
    gross_profit_services = total_services - total_service_costs
    total_gross_profit = total_revenue - total_cogs - total_service_costs
    operating_profit = total_gross_profit - operating_expenses
    net_profit = operating_profit - total_taxes
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

    statistics = {
        "total_sales": total_sales,
        "total_cogs": total_cogs,
        "gross_profit_sales": gross_profit_sales,
        "total_services": total_services,
        "total_service_costs": total_service_costs,
        "gross_profit_services": gross_profit_services,
        "total_gross_profit": total_gross_profit,
        "total_revenue": total_revenue,
        "other_revenue": other_revenue,
        "total_discounts": total_discounts,
        "total_shipping_income": total_shipping_income,
        "operating_expenses": operating_expenses,
        "total_taxes": total_taxes,
        "operating_profit": operating_profit,
        "total_expenses": operating_expenses,
        "net_profit": net_profit,
        "profit_margin": profit_margin,
        "total_preorders": total_preorders,
        "total_stock_value": total_stock_value_stats,
        "total_stock_qty": total_stock_qty_stats,
        "cogs_details": cogs_details,
        "estimated_products_count": estimated_count,
        "estimated_products": estimated_products,
        "products_without_cost_count": no_cost_count,
        "products_without_cost": products_without_cost,
    }

    cache.set(cache_key, statistics, timeout=600)
    return statistics

@ledger_bp.route("/", methods=["GET"], endpoint="index")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def ledger_index():
    """صفحة الدفتر الرئيسية"""
    return render_template("ledger/index.html")

@ledger_bp.route("/chart-of-accounts", methods=["GET"], endpoint="chart_of_accounts")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def chart_of_accounts():
    """دليل الحسابات المحاسبية - واجهة مبسطة"""
    return render_template("ledger/chart_of_accounts.html")

@ledger_bp.route("/accounts", methods=["GET"], endpoint="get_accounts")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_accounts():
    """API: جلب جميع الحسابات المحاسبية"""
    try:
        accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
        
        accounts_list = []
        for acc in accounts:
            accounts_list.append({
                'id': acc.id,
                'code': acc.code,
                'name': acc.name,
                'type': acc.type,
                'is_active': acc.is_active
            })
        
        return jsonify({
            'success': True,
            'accounts': accounts_list,
            'total': len(accounts_list)
        })
    except Exception as e:
        current_app.logger.error(f"خطأ في جلب الحسابات: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/manual-entry", methods=["POST"], endpoint="create_manual_entry")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def create_manual_entry():
    """إنشاء قيد يدوي (Manual Journal Entry)"""
    try:
        from flask_login import current_user
        from decimal import Decimal
        
        data = request.get_json()
        
        # استخراج البيانات
        entry_date = data.get('date')
        amount = Decimal(str(data.get('amount', 0)))
        description = data.get('description', '').strip()
        debit_account = data.get('debit_account', '').strip()
        credit_account = data.get('credit_account', '').strip()
        
        # التحقق
        if not all([entry_date, amount, description, debit_account, credit_account]):
            return jsonify({'success': False, 'error': 'جميع الحقول مطلوبة'}), 400
        
        if amount <= 0:
            return jsonify({'success': False, 'error': 'المبلغ يجب أن يكون أكبر من صفر'}), 400
        
        if debit_account == credit_account:
            return jsonify({'success': False, 'error': 'لا يمكن أن يكون الحساب نفسه في الطرفين'}), 400
        
        # التحقق من وجود الحسابات
        debit_acc = Account.query.filter_by(code=debit_account, is_active=True).first()
        credit_acc = Account.query.filter_by(code=credit_account, is_active=True).first()
        
        if not debit_acc or not credit_acc:
            return jsonify({'success': False, 'error': 'حساب غير صحيح أو غير نشط'}), 400
        
        # إنشاء GLBatch
        from datetime import datetime
        posted_at = datetime.strptime(entry_date, '%Y-%m-%d')
        
        ref_number = f"MAN-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # استخدام timestamp كـ source_id فريد لكل قيد يدوي
        unique_source_id = int(datetime.now().timestamp() * 1000)
        
        batch = GLBatch(
            source_type='MANUAL',
            source_id=unique_source_id,
            purpose='MANUAL_ENTRY',
            posted_at=posted_at,
            currency='ILS',
            memo=description,
            status='POSTED',
            entity_type=None,
            entity_id=None
        )
        db.session.add(batch)
        db.session.flush()
        
        # إنشاء GLEntry - المدين
        entry_debit = GLEntry(
            batch_id=batch.id,
            account=debit_account,
            debit=amount,
            credit=0,
            currency='ILS',
            ref=ref_number
        )
        db.session.add(entry_debit)
        
        # إنشاء GLEntry - الدائن
        entry_credit = GLEntry(
            batch_id=batch.id,
            account=credit_account,
            debit=0,
            credit=amount,
            currency='ILS',
            ref=ref_number
        )
        db.session.add(entry_credit)
        
        db.session.commit()
        
        current_app.logger.info(f"✅ تم إنشاء قيد يدوي: {description} - {amount} ₪")
        
        return jsonify({
            'success': True,
            'message': 'تم حفظ القيد اليدوي بنجاح',
            'batch_id': batch.id,
            'batch_code': batch.code
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"❌ خطأ في إنشاء قيد يدوي: {str(e)}")
        
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/data", methods=["GET"], endpoint="get_ledger_data")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_ledger_data():
    """جلب بيانات دفتر الأستاذ من قاعدة البيانات الحقيقية"""
    try:
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        transaction_type = request.args.get('transaction_type', '').strip()
        
        # تحليل التواريخ
        from_date, to_date = _parse_ledger_date_range(from_date_str, to_date_str)
        
        ledger_entries = []
        running_balance = 0.0
        
        # --- بداية منطق القيد المزدوج (Double Entry Journal) ---
        # بدلاً من تجميع البيانات يدوياً من جداول المبيعات والمصاريف، نقوم بجلب القيود مباشرة من GLEntry
        # هذا يضمن دقة محاسبية (Debit = Credit) وعدم ازدواجية، ويعكس دفتر اليومية العام.

        query = (
            db.session.query(GLEntry, GLBatch, Account)
            .join(GLBatch, GLEntry.batch_id == GLBatch.id)
            .outerjoin(Account, GLEntry.account == Account.code)
            .filter(GLBatch.status == "POSTED")
        )
        
        if from_date:
            query = query.filter(GLBatch.posted_at >= from_date)
        if to_date:
            query = query.filter(GLBatch.posted_at <= to_date)
            
        if transaction_type:
            tt_upper = transaction_type.strip().upper()
            if tt_upper == 'SALE':
                query = query.filter(GLBatch.source_type == 'SALE')
            elif tt_upper == 'SALE_PARTNER_SHARE':
                query = query.filter(GLBatch.source_type == 'SALE_PARTNER_SHARE')
            elif tt_upper in ['SALE_RETURN', 'RETURN']:
                query = query.filter(GLBatch.source_type == 'SALE_RETURN')
            elif tt_upper in ['PURCHASE', 'EXPENSE']:
                query = query.filter(GLBatch.source_type.in_(['EXPENSE', 'PURCHASE']))
            elif tt_upper == 'PAYMENT':
                query = query.filter(GLBatch.source_type == 'PAYMENT')
            elif tt_upper == 'PAYMENT_SPLIT':
                query = query.filter(GLBatch.source_type == 'PAYMENT_SPLIT')
            elif tt_upper == 'OPENING':
                query = query.filter(GLBatch.purpose == 'OPENING_BALANCE')
            elif tt_upper in ['MANUAL', 'JOURNAL']:
                query = query.filter(GLBatch.source_type == 'MANUAL')
            elif tt_upper == 'SERVICE':
                query = query.filter(GLBatch.source_type == 'SERVICE')
            elif tt_upper == 'SERVICE_PARTNER_SHARE':
                query = query.filter(GLBatch.source_type == 'SERVICE_PARTNER_SHARE')
            elif tt_upper == 'INVOICE':
                query = query.filter(GLBatch.source_type == 'INVOICE')
            elif tt_upper == 'PREORDER':
                query = query.filter(GLBatch.source_type == 'PREORDER')
            elif tt_upper == 'SHIPMENT':
                query = query.filter(GLBatch.source_type == 'SHIPMENT')
            elif tt_upper == 'EXCHANGE':
                query = query.filter(GLBatch.source_type == 'EXCHANGE')
            elif tt_upper == 'CHECK':
                query = query.filter(GLBatch.source_type.in_([
                    'CHECK', 'CHECK_REVERSAL',
                    'check_manual', 'check_payment', 'check_payment_split'
                ]))
            elif tt_upper == 'CLOSING':
                query = query.filter(GLBatch.source_type == 'CLOSING_ENTRY')
            elif tt_upper == 'TAX_ACCRUAL':
                query = query.filter(GLBatch.source_type == 'TAX_ACCRUAL')
            elif tt_upper == 'REVERSAL':
                query = query.filter(
                    GLBatch.source_type.in_([
                        'REVERSAL', 'SALE_REVERSAL', 'PAYMENT_REVERSAL', 'EXPENSE_REVERSAL',
                        'SERVICE_REVERSAL', 'SHIPMENT_REVERSAL', 'INVOICE_REVERSAL',
                        'PREORDER_REVERSAL', 'ONLINE_ORDER_REVERSAL'
                    ])
                )
            elif tt_upper == 'ONLINE_PREORDER':
                query = query.filter(GLBatch.source_type.in_(['ONLINE_PREORDER', 'ONLINE_ORDER']))

        # ترتيب حسب التاريخ، ثم رقم القيد، ثم المدين أولاً (المتعارف عليه في اليومية)
        entries = query.order_by(GLBatch.posted_at, GLBatch.id, desc(GLEntry.debit)).limit(5000).all()
        
        # قاموس لترجمة أنواع العمليات — يشمل كل source_type المستخدمة لعدم إخفاء أي قيد
        type_map = {
            'SALE': 'مبيعات',
            'SALE_PARTNER_SHARE': 'حصة شريك من مبيعة',
            'SALE_RETURN': 'مرتجع مبيعات',
            'SALE_REVERSAL': 'عكس مبيعة',
            'EXPENSE': 'مصروف',
            'EXPENSE_REVERSAL': 'عكس مصروف',
            'PURCHASE': 'مشتريات',
            'PAYMENT': 'دفعة',
            'PAYMENT_REVERSAL': 'عكس دفعة',
            'PAYMENT_CANCELLATION': 'إلغاء دفعة',
            'PAYMENT_SPLIT': 'توزيع دفعة',
            'MANUAL': 'قيد يدوي',
            'OPENING_BALANCE': 'رصيد افتتاحي',
            'SERVICE': 'صيانة',
            'SERVICE_PARTNER_SHARE': 'حصة شريك من صيانة',
            'SERVICE_REVERSAL': 'عكس صيانة',
            'PREORDER': 'حجز مسبق',
            'PREORDER_REVERSAL': 'عكس حجز',
            'INVOICE': 'فاتورة',
            'INVOICE_REVERSAL': 'عكس فاتورة',
            'ONLINE_PREORDER': 'حجز أونلاين',
            'ONLINE_ORDER': 'طلب أونلاين',
            'ONLINE_ORDER_REVERSAL': 'عكس طلب أونلاين',
            'EXCHANGE': 'توريد/صرف',
            'EXCHANGE_PURCHASE': 'شراء توريد',
            'EXCHANGE_RETURN': 'مرتجع توريد',
            'EXCHANGE_ADJUST': 'تسوية توريد',
            'SHIPMENT': 'شحنة',
            'SHIPMENT_REVERSAL': 'عكس شحنة',
            'CHECK': 'شيك',
            'CHECK_REVERSAL': 'عكس شيك',
            'TAX_ACCRUAL': 'استحقاق ضريبة الدخل',
            'check_manual': 'شيك يدوي',
            'check_payment': 'شيك دفعة',
            'check_payment_split': 'شيك توزيع دفعة',
            'CLOSING_ENTRY': 'قيد إقفال',
            'REVERSAL': 'قيد عكسي',
            'CONSUME_SALE': 'استهلاك مبيعة',
            'CONSUME_SERVICE': 'استهلاك خدمة',
            'LOAN_SETTLEMENT': 'تسوية قرض',
            'SUPPLIER_INVOICE': 'فاتورة مورد',
            'PROJECT_COST': 'تكلفة مشروع',
            'PROJECT_REVENUE': 'إيراد مشروع',
        }

        payment_split_cache = {}

        for entry, batch, account in entries:
            # استخراج اسم الجهة (عميل، مورد، الخ)
            entity_name, entity_type_ar, entity_id, entity_type_code = SmartEntityExtractor.extract_from_batch(batch)
            if not entity_name:
                entity_name = "—"
            
            # بناء الوصف: البيان من القيد + اسم الحساب
            desc_parts = []
            if batch.memo:
                desc_parts.append(batch.memo)
            
            account_display = f"{entry.account}"
            if account:
                account_display = f"{account.name} ({entry.account})"
            
            # الوصف النهائي: الحساب | البيان
            description = f"{account_display}"
            if batch.memo:
                 description += f" | {batch.memo}"

            # نوع العملية بالعربي
            source_type = (batch.source_type or '').upper()
            type_ar = type_map.get(source_type, source_type)
            if batch.purpose == 'OPENING_BALANCE':
                type_ar = 'رصيد افتتاحي'

            debit = float(entry.debit or 0)
            credit = float(entry.credit or 0)
            
            # الرصيد المتراكم في العرض (الفرق بين المدين والدائن)
            # في دفتر اليومية، الرصيد التراكمي للشركة ككل هو صفر دائماً (نظرياً)
            # لكن سنعرض التراكمي للفترة المحددة
            running_balance += (debit - credit)

            payment_id = None
            split_id = None
            if source_type == "PAYMENT_SPLIT" and batch.source_id:
                cached = payment_split_cache.get(int(batch.source_id))
                if cached is None:
                    try:
                        split = db.session.get(PaymentSplit, int(batch.source_id))
                        cached = (int(split.payment_id) if split and getattr(split, "payment_id", None) else None, int(split.id) if split else None)
                    except Exception:
                        cached = (None, None)
                    payment_split_cache[int(batch.source_id)] = cached
                payment_id, split_id = cached
            
            ledger_entries.append({
                "id": entry.id,
                "date": batch.posted_at.strftime('%Y-%m-%d'),
                "transaction_number": (batch.code or f"BATCH-{batch.id}"),
                "type": (batch.source_type or "").lower(),
                "type_ar": type_ar,
                "description": description,
                "debit": debit,
                "credit": credit,
                "balance": running_balance, 
                "entity_name": entity_name,
                "entity_type": entity_type_ar or "",
                "batch_id": batch.id,
                "source_id": batch.source_id,
                "payment_id": payment_id,
                "split_id": split_id,
            })

        # --- نهاية منطق القيد المزدوج ---
        
        # ترتيب حسب التاريخ
        sort = request.args.get('sort', 'date')
        order = request.args.get('order', 'asc')
        
        if sort == 'date':
            if order == 'asc':
                ledger_entries.sort(key=lambda x: (x['date'], x.get('id', 0)))
            else:
                ledger_entries.sort(key=lambda x: (x['date'], x.get('id', 0)), reverse=True)
        elif sort == 'debit':
            if order == 'asc':
                ledger_entries.sort(key=lambda x: (x['debit'], x.get('id', 0)))
            else:
                ledger_entries.sort(key=lambda x: (x['debit'], x.get('id', 0)), reverse=True)
        elif sort == 'credit':
            if order == 'asc':
                ledger_entries.sort(key=lambda x: (x['credit'], x.get('id', 0)))
            else:
                ledger_entries.sort(key=lambda x: (x['credit'], x.get('id', 0)), reverse=True)
        elif sort == 'balance':
            if order == 'asc':
                ledger_entries.sort(key=lambda x: (x.get('balance', 0), x.get('id', 0)))
            else:
                ledger_entries.sort(key=lambda x: (x.get('balance', 0), x.get('id', 0)), reverse=True)
        elif sort == 'type':
            if order == 'asc':
                ledger_entries.sort(key=lambda x: (x.get('type_ar', ''), x.get('id', 0)))
            else:
                ledger_entries.sort(key=lambda x: (x.get('type_ar', ''), x.get('id', 0)), reverse=True)
        else:
            ledger_entries.sort(key=lambda x: (x['date'], x.get('id', 0)))
        
        # إعادة حساب الرصيد المتراكم
        running_balance = 0.0
        for entry in ledger_entries:
            running_balance += entry['debit'] - entry['credit']
            entry['balance'] = running_balance
        
        include_stats_raw = (request.args.get("include_stats") or "").strip().lower()
        include_stats = include_stats_raw in {"1", "true", "yes", "y", "on"}
        statistics = _calculate_ledger_statistics(from_date, to_date) if include_stats else {}
        
        search_term = (request.args.get('q') or '').strip()
        filtered_entries = ledger_entries
        if search_term:
            search_lower = search_term.lower()

            def _entry_matches(entry):
                fields = [
                    entry.get("transaction_number"),
                    entry.get("type"),
                    entry.get("type_ar"),
                    entry.get("description"),
                    entry.get("entity_name"),
                    entry.get("entity_type"),
                    entry.get("date"),
                ]
                for field in fields:
                    if field and search_lower in str(field).lower():
                        return True
                for numeric in (entry.get("debit"), entry.get("credit"), entry.get("balance")):
                    if numeric is not None and search_lower in f"{numeric}".lower():
                        return True
                payment_details = entry.get("payment_details")
                if isinstance(payment_details, dict):
                    for value in payment_details.values():
                        if value and search_lower in str(value).lower():
                            return True
                return False

            filtered_entries = [entry for entry in ledger_entries if _entry_matches(entry)]

        page = request.args.get('page', 1, type=int) or 1
        total_entries = len(filtered_entries)
        per_page_param = (request.args.get('per_page') or '').strip().lower()
        if per_page_param in {'all', 'max', '*', '0', '-1'}:
            per_page = total_entries if total_entries > 0 else 1
        else:
            try:
                per_page_value = int(per_page_param) if per_page_param else 25
            except ValueError:
                per_page_value = 25
            per_page = max(10, min(per_page_value, 500))
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_entries = filtered_entries[start_idx:end_idx]
        
        # حساب إجماليات البيانات (لدفتر الأستاذ)
        ledger_totals = {
            'total_debit': sum(entry['debit'] for entry in filtered_entries),
            'total_credit': sum(entry['credit'] for entry in filtered_entries),
            'final_balance': filtered_entries[-1]['balance'] if filtered_entries else 0
        }
        
        return jsonify({
            "data": paginated_entries,
            "statistics": statistics,
            "totals": ledger_totals,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_entries,
                "pages": (total_entries + per_page - 1) // per_page if total_entries > 0 else 1
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in get_ledger_data: {str(e)}")
        return jsonify({"error": "حدث خطأ داخلي", "data": [], "statistics": {}}), 500

@ledger_bp.route("/statistics", methods=["GET"], endpoint="get_ledger_statistics")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_ledger_statistics():
    try:
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        from_date, to_date = _parse_ledger_date_range(from_date_str, to_date_str)
        statistics = _calculate_ledger_statistics(from_date, to_date)
        return jsonify({"statistics": statistics})
    except Exception as e:
        current_app.logger.error(f"Error in get_ledger_statistics: {str(e)}")
        return jsonify({"error": "حدث خطأ داخلي", "statistics": {}}), 500

@ledger_bp.route("/cogs-audit", methods=["GET"], endpoint="cogs_audit_report")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def cogs_audit_report():
    """تقرير شامل لفحص تكلفة البضاعة المباعة (COGS) بدقة"""
    try:
        from models import SaleLine, fx_rate, convert_amount
        
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d') if from_date_str else None
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if to_date_str else None
        
        sale_lines_query = (
            db.session.query(SaleLine)
            .join(Sale, Sale.id == SaleLine.sale_id)
            .filter(Sale.status == 'CONFIRMED')
        )
        if from_date:
            sale_lines_query = sale_lines_query.filter(Sale.sale_date >= from_date)
        if to_date:
            sale_lines_query = sale_lines_query.filter(Sale.sale_date <= to_date)
        
        products_audit = []
        total_cogs_actual = 0.0
        total_cogs_estimated = 0.0
        total_cogs_missing = 0.0
        total_sales_value = 0.0
        
        estimated_count = 0
        missing_count = 0
        actual_count = 0
        
        def _to_ils(value, currency, ref_date):
            val = Decimal(str(value or 0))
            if not val:
                return 0.0
            code = (currency or "ILS").upper()
            if code == "ILS":
                return float(val)
            try:
                return float(convert_amount(val, code, "ILS", ref_date))
            except Exception:
                try:
                    rate = fx_rate(code, "ILS", ref_date, raise_on_missing=False)
                except Exception:
                    rate = None
                if rate and rate > 0:
                    return float(val * Decimal(str(rate)))
            return float(val)

        for line in sale_lines_query.limit(100000).all():
            if not line.product:
                continue
                
            product = line.product
            qty_sold = float(line.quantity or 0)
            unit_price = float(line.unit_price or 0)
            line_total = qty_sold * unit_price
            
            sale_currency = (line.sale.currency or "ILS").upper()
            if sale_currency != "ILS":
                used_rate = getattr(line.sale, "fx_rate_used", None)
                if used_rate and float(used_rate) > 0:
                    line_total = float(Decimal(str(line_total)) * Decimal(str(used_rate)))
                else:
                    try:
                        rate = fx_rate(sale_currency, "ILS", line.sale.sale_date, raise_on_missing=False)
                        if rate and rate > 0:
                            line_total = float(Decimal(str(line_total)) * Decimal(str(rate)))
                    except Exception:
                        current_app.logger.warning('currency conversion failed silently in ledger_blueprint.py', exc_info=True)
            
            total_sales_value += line_total
            
            unit_cost = None
            cost_source = None
            cost_status = None
            
            product_currency = getattr(product, "currency", None) or "ILS"
            if product.purchase_price and product.purchase_price > 0:
                unit_cost = _to_ils(product.purchase_price, product_currency, line.sale.sale_date)
                cost_source = "purchase_price"
                cost_status = "actual"
                actual_count += 1
            elif product.cost_after_shipping and product.cost_after_shipping > 0:
                unit_cost = _to_ils(product.cost_after_shipping, product_currency, line.sale.sale_date)
                cost_source = "cost_after_shipping"
                cost_status = "actual"
                actual_count += 1
            elif product.cost_before_shipping and product.cost_before_shipping > 0:
                unit_cost = _to_ils(product.cost_before_shipping, product_currency, line.sale.sale_date)
                cost_source = "cost_before_shipping"
                cost_status = "actual"
                actual_count += 1
            elif product.price and product.price > 0:
                unit_cost = _to_ils(product.price, product_currency, line.sale.sale_date) * 0.70
                cost_source = "estimated_70%"
                cost_status = "estimated"
                estimated_count += 1
            else:
                unit_cost = 0.0
                cost_source = "missing"
                cost_status = "missing"
                missing_count += 1
            
            line_cogs = qty_sold * unit_cost
            
            if cost_status == "actual":
                total_cogs_actual += line_cogs
            elif cost_status == "estimated":
                total_cogs_estimated += line_cogs
            else:
                total_cogs_missing += line_cogs
            
            products_audit.append({
                'product_id': product.id,
                'product_name': product.name,
                'product_sku': product.sku or 'N/A',
                'sale_id': line.sale_id,
                'sale_number': line.sale.sale_number or f'SAL-{line.sale_id}',
                'sale_date': line.sale.sale_date.strftime('%Y-%m-%d') if line.sale.sale_date else 'N/A',
                'qty_sold': qty_sold,
                'unit_price': unit_price,
                'line_total': line_total,
                'unit_cost': unit_cost,
                'cost_source': cost_source,
                'cost_status': cost_status,
                'line_cogs': line_cogs,
                'gross_profit': line_total - line_cogs,
                'profit_margin': ((line_total - line_cogs) / line_total * 100) if line_total > 0 else 0,
                'purchase_price': float(product.purchase_price) if product.purchase_price else None,
                'cost_after_shipping': float(product.cost_after_shipping) if product.cost_after_shipping else None,
                'cost_before_shipping': float(product.cost_before_shipping) if product.cost_before_shipping else None,
                'selling_price': float(product.price) if product.price else None
            })
        
        total_cogs = total_cogs_actual + total_cogs_estimated + total_cogs_missing
        total_gross_profit = total_sales_value - total_cogs
        overall_margin = (total_gross_profit / total_sales_value * 100) if total_sales_value > 0 else 0
        
        summary = {
            'total_products_sold': len(products_audit),
            'total_sales_value': total_sales_value,
            'total_cogs': total_cogs,
            'total_cogs_actual': total_cogs_actual,
            'total_cogs_estimated': total_cogs_estimated,
            'total_cogs_missing': total_cogs_missing,
            'total_gross_profit': total_gross_profit,
            'overall_margin': overall_margin,
            'actual_count': actual_count,
            'estimated_count': estimated_count,
            'missing_count': missing_count,
            'actual_percentage': (actual_count / len(products_audit) * 100) if products_audit else 0,
            'estimated_percentage': (estimated_count / len(products_audit) * 100) if products_audit else 0,
            'missing_percentage': (missing_count / len(products_audit) * 100) if products_audit else 0,
            'estimated_impact': (total_cogs_estimated / total_cogs * 100) if total_cogs > 0 else 0,
            'missing_impact': (total_cogs_missing / total_cogs * 100) if total_cogs > 0 else 0
        }
        
        return jsonify({
            'success': True,
            'summary': summary,
            'products': products_audit,
            'from_date': from_date_str,
            'to_date': to_date_str
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in cogs_audit_report: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/entity-balance-audit", methods=["GET"], endpoint="entity_balance_audit")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def entity_balance_audit():
    try:
        as_of_date_str = request.args.get("as_of_date")
        tolerance = float(request.args.get("tolerance", 0.01) or 0.01)
        limit = int(request.args.get("limit", 200) or 200)
        include_archived = (request.args.get("include_archived", "false") or "").lower() == "true"

        if as_of_date_str:
            as_of_date = datetime.fromisoformat(str(as_of_date_str).replace("Z", "+00:00")).date()
        else:
            as_of_date = datetime.now(timezone.utc).date()
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())

        ar_account = (GL_ACCOUNTS.get("AR") or "1100_AR").upper()
        ap_account = (GL_ACCOUNTS.get("AP") or "2000_AP").upper()

        customer_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )

        supplier_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "SUPPLIER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )

        partner_ap_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "PARTNER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        partner_ar_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLBatch, GLBatch.entity_id == Partner.customer_id)
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
                Partner.customer_id.isnot(None),
            )
            .group_by(Partner.id)
            .subquery()
        )
        partner_gl_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                (
                    func.coalesce(partner_ap_sq.c.gl_balance, 0)
                    - func.coalesce(partner_ar_sq.c.gl_balance, 0)
                ).label("gl_balance"),
            )
            .outerjoin(partner_ap_sq, partner_ap_sq.c.entity_id == Partner.id)
            .outerjoin(partner_ar_sq, partner_ar_sq.c.entity_id == Partner.id)
            .subquery()
        )

        cust_stored = func.coalesce(Customer.current_balance, 0)
        cust_gl = func.coalesce(customer_gl_sq.c.gl_balance, 0)
        cust_expected_gl = -cust_stored
        cust_diff = cust_gl - cust_expected_gl

        customers_base = (
            db.session.query(
                Customer.id.label("id"),
                Customer.name.label("name"),
                Customer.currency.label("currency"),
                cust_stored.label("stored_balance"),
                cust_expected_gl.label("expected_gl_balance"),
                cust_gl.label("gl_balance"),
                cust_diff.label("diff"),
            )
            .outerjoin(customer_gl_sq, customer_gl_sq.c.entity_id == Customer.id)
        )
        if hasattr(Customer, "is_archived") and not include_archived:
            customers_base = customers_base.filter(Customer.is_archived.is_(False))

        customers_filter = func.abs(cust_diff) > tolerance
        customers_mismatch_count = customers_base.with_entities(func.count()).filter(customers_filter).scalar() or 0
        customers_mismatch_total_abs = (
            customers_base.with_entities(func.coalesce(func.sum(func.abs(cust_diff)), 0)).filter(customers_filter).scalar()
            or 0
        )
        customers_rows = (
            customers_base.filter(customers_filter).order_by(func.abs(cust_diff).desc()).limit(limit).all()
        )
        customers = [
            {
                "id": int(r.id),
                "name": r.name,
                "currency": r.currency or "ILS",
                "stored_balance": float(r.stored_balance or 0),
                "expected_gl_balance": float(r.expected_gl_balance or 0),
                "gl_balance": float(r.gl_balance or 0),
                "diff": float(r.diff or 0),
            }
            for r in customers_rows
        ]

        supp_stored = func.coalesce(Supplier.current_balance, 0)
        supp_gl = func.coalesce(supplier_gl_sq.c.gl_balance, 0)
        supp_expected_gl = supp_stored
        supp_diff = supp_gl - supp_expected_gl

        suppliers_base = (
            db.session.query(
                Supplier.id.label("id"),
                Supplier.name.label("name"),
                Supplier.currency.label("currency"),
                supp_stored.label("stored_balance"),
                supp_expected_gl.label("expected_gl_balance"),
                supp_gl.label("gl_balance"),
                supp_diff.label("diff"),
            )
            .outerjoin(supplier_gl_sq, supplier_gl_sq.c.entity_id == Supplier.id)
        )
        if hasattr(Supplier, "is_archived") and not include_archived:
            suppliers_base = suppliers_base.filter(Supplier.is_archived.is_(False))

        suppliers_filter = func.abs(supp_diff) > tolerance
        suppliers_mismatch_count = suppliers_base.with_entities(func.count()).filter(suppliers_filter).scalar() or 0
        suppliers_mismatch_total_abs = (
            suppliers_base.with_entities(func.coalesce(func.sum(func.abs(supp_diff)), 0)).filter(suppliers_filter).scalar()
            or 0
        )
        suppliers_rows = (
            suppliers_base.filter(suppliers_filter).order_by(func.abs(supp_diff).desc()).limit(limit).all()
        )
        suppliers = [
            {
                "id": int(r.id),
                "name": r.name,
                "currency": r.currency or "ILS",
                "stored_balance": float(r.stored_balance or 0),
                "expected_gl_balance": float(r.expected_gl_balance or 0),
                "gl_balance": float(r.gl_balance or 0),
                "diff": float(r.diff or 0),
            }
            for r in suppliers_rows
        ]

        part_stored = func.coalesce(Partner.current_balance, 0)
        part_gl = func.coalesce(partner_gl_sq.c.gl_balance, 0)
        part_expected_gl = part_stored
        part_diff = part_gl - part_expected_gl

        partners_base = (
            db.session.query(
                Partner.id.label("id"),
                Partner.name.label("name"),
                Partner.currency.label("currency"),
                part_stored.label("stored_balance"),
                part_expected_gl.label("expected_gl_balance"),
                part_gl.label("gl_balance"),
                part_diff.label("diff"),
            )
            .outerjoin(partner_gl_sq, partner_gl_sq.c.entity_id == Partner.id)
        )
        if hasattr(Partner, "is_archived") and not include_archived:
            partners_base = partners_base.filter(Partner.is_archived.is_(False))

        partners_filter = func.abs(part_diff) > tolerance
        partners_mismatch_count = partners_base.with_entities(func.count()).filter(partners_filter).scalar() or 0
        partners_mismatch_total_abs = (
            partners_base.with_entities(func.coalesce(func.sum(func.abs(part_diff)), 0)).filter(partners_filter).scalar()
            or 0
        )
        partners_rows = (
            partners_base.filter(partners_filter).order_by(func.abs(part_diff).desc()).limit(limit).all()
        )
        partners = [
            {
                "id": int(r.id),
                "name": r.name,
                "currency": r.currency or "ILS",
                "stored_balance": float(r.stored_balance or 0),
                "expected_gl_balance": float(r.expected_gl_balance or 0),
                "gl_balance": float(r.gl_balance or 0),
                "diff": float(r.diff or 0),
            }
            for r in partners_rows
        ]

        customer_orphans_q = (
            db.session.query(
                customer_gl_sq.c.entity_id.label("id"),
                customer_gl_sq.c.gl_balance.label("gl_balance"),
            )
            .outerjoin(Customer, Customer.id == customer_gl_sq.c.entity_id)
            .filter(Customer.id.is_(None))
            .order_by(func.abs(customer_gl_sq.c.gl_balance).desc())
        )
        supplier_orphans_q = (
            db.session.query(
                supplier_gl_sq.c.entity_id.label("id"),
                supplier_gl_sq.c.gl_balance.label("gl_balance"),
            )
            .outerjoin(Supplier, Supplier.id == supplier_gl_sq.c.entity_id)
            .filter(Supplier.id.is_(None))
            .order_by(func.abs(supplier_gl_sq.c.gl_balance).desc())
        )
        partner_orphans_q = (
            db.session.query(
                partner_gl_sq.c.entity_id.label("id"),
                partner_gl_sq.c.gl_balance.label("gl_balance"),
            )
            .outerjoin(Partner, Partner.id == partner_gl_sq.c.entity_id)
            .filter(Partner.id.is_(None))
            .order_by(func.abs(partner_gl_sq.c.gl_balance).desc())
        )

        customer_orphan_count = customer_orphans_q.order_by(None).with_entities(func.count()).scalar() or 0
        supplier_orphan_count = supplier_orphans_q.order_by(None).with_entities(func.count()).scalar() or 0
        partner_orphan_count = partner_orphans_q.order_by(None).with_entities(func.count()).scalar() or 0

        customer_orphans = customer_orphans_q.limit(limit).all()
        supplier_orphans = supplier_orphans_q.limit(limit).all()
        partner_orphans = partner_orphans_q.limit(limit).all()

        posted_batches_missing_entity = (
            db.session.query(func.count(GLBatch.id))
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                or_(GLBatch.entity_type.is_(None), GLBatch.entity_id.is_(None)),
            )
            .scalar()
            or 0
        )

        ar_unassigned = (
            db.session.query(func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0))
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLEntry.account == ar_account,
                or_(
                    GLBatch.entity_type.is_(None),
                    GLBatch.entity_id.is_(None),
                    GLBatch.entity_type != "CUSTOMER",
                ),
            )
            .scalar()
            or 0
        )

        ap_unassigned = (
            db.session.query(func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0))
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLEntry.account == ap_account,
                or_(
                    GLBatch.entity_type.is_(None),
                    GLBatch.entity_id.is_(None),
                ),
            )
            .scalar()
            or 0
        )

        return jsonify(
            {
                "success": True,
                "report_type": "entity_balance_audit",
                "as_of_date": as_of_date.isoformat(),
                "tolerance": tolerance,
                "accounts": {"ar": ar_account, "ap": ap_account},
                "summary": {
                    "customers_mismatch_count": int(customers_mismatch_count),
                    "suppliers_mismatch_count": int(suppliers_mismatch_count),
                    "partners_mismatch_count": int(partners_mismatch_count),
                    "customers_mismatch_total_abs": float(customers_mismatch_total_abs),
                    "suppliers_mismatch_total_abs": float(suppliers_mismatch_total_abs),
                    "partners_mismatch_total_abs": float(partners_mismatch_total_abs),
                    "customer_orphan_gl_count": int(customer_orphan_count),
                    "supplier_orphan_gl_count": int(supplier_orphan_count),
                    "partner_orphan_gl_count": int(partner_orphan_count),
                    "posted_batches_missing_entity": int(posted_batches_missing_entity),
                    "ar_unassigned_balance": float(ar_unassigned),
                    "ap_unassigned_balance": float(ap_unassigned),
                },
                "details": {
                    "customers": customers,
                    "suppliers": suppliers,
                    "partners": partners,
                    "orphans": {
                        "customers": [{"id": int(r.id), "gl_balance": float(r.gl_balance)} for r in customer_orphans],
                        "suppliers": [{"id": int(r.id), "gl_balance": float(r.gl_balance)} for r in supplier_orphans],
                        "partners": [{"id": int(r.id), "gl_balance": float(r.gl_balance)} for r in partner_orphans],
                    },
                },
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error in entity_balance_audit: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/entity-balance-audit/fix-gl-entities", methods=["POST"], endpoint="fix_gl_entities_for_entity_audit")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def fix_gl_entities_for_entity_audit():
    try:
        payload = request.get_json(silent=True) or {}

        dry_run = bool(payload.get("dry_run", True))
        override = bool(payload.get("override", False))
        max_batches = int(payload.get("max_batches", 5000) or 5000)
        require_backup = bool(payload.get("require_backup", True))
        allow_without_backup = bool(payload.get("allow_without_backup", False))
        as_of_date_str = payload.get("as_of_date") or request.args.get("as_of_date")

        if as_of_date_str:
            as_of_date = datetime.fromisoformat(str(as_of_date_str).replace("Z", "+00:00")).date()
        else:
            as_of_date = datetime.now(timezone.utc).date()
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())

        backup_info = {"attempted": False, "success": None, "message": None, "path": None}
        if not dry_run and require_backup:
            try:
                backup_info["attempted"] = True
                ok, msg, path = perform_backup_db(current_app)
                backup_info["success"] = bool(ok)
                backup_info["message"] = msg
                backup_info["path"] = path
                if not ok and not allow_without_backup:
                    return jsonify({"success": False, "error": msg or "backup_failed", "backup": backup_info}), 500
            except Exception as exc:
                backup_info["attempted"] = True
                backup_info["success"] = False
                backup_info["message"] = str(exc)
                if not allow_without_backup:
                    return jsonify({"success": False, "error": str(exc), "backup": backup_info}), 500

        q = GLBatch.query.filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at <= as_of_dt,
        )

        supported_source_types = {
            "PAYMENT", "PAYMENT_SPLIT", "SALE", "INVOICE", "EXPENSE", "SERVICE", "PREORDER", "SHIPMENT",
            "CHECK", "CHECK_REVERSAL", "check_manual", "check_payment", "check_payment_split",
            "EXCHANGE", "MANUAL", "CLOSING_ENTRY", "REVERSAL",
            "SALE_REVERSAL", "PAYMENT_REVERSAL", "EXPENSE_REVERSAL", "SERVICE_REVERSAL",
            "SHIPMENT_REVERSAL", "INVOICE_REVERSAL", "PREORDER_REVERSAL", "ONLINE_ORDER_REVERSAL",
            "ONLINE_PREORDER", "ONLINE_ORDER", "EXCHANGE_PURCHASE", "EXCHANGE_RETURN", "EXCHANGE_ADJUST",
            "CONSUME_SALE", "CONSUME_SERVICE", "LOAN_SETTLEMENT", "SUPPLIER_INVOICE",
            "PROJECT_COST", "PROJECT_REVENUE", "SALE_PARTNER_SHARE", "SERVICE_PARTNER_SHARE",
            "TAX_ACCRUAL",
        }
        if override:
            q = q.filter(
                GLBatch.source_type.isnot(None),
                GLBatch.source_id.isnot(None),
                func.upper(GLBatch.source_type).in_(supported_source_types),
            )
        else:
            q = q.filter(or_(GLBatch.entity_type.is_(None), GLBatch.entity_id.is_(None)))

        batches = q.order_by(GLBatch.id.desc()).limit(max_batches).all()

        changes = []
        updated = 0
        skipped = 0

        for b in batches:
            old_type = b.entity_type
            old_id = b.entity_id

            if override:
                name, type_ar, entity_id, entity_type = SmartEntityExtractor.extract_from_source(b)
            else:
                name, type_ar, entity_id, entity_type = SmartEntityExtractor.extract_from_batch(b)

            if not entity_type or not entity_id:
                skipped += 1
                continue

            entity_type = str(entity_type).upper()
            if entity_type not in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"}:
                skipped += 1
                continue

            if (old_type or "").upper() == entity_type and int(old_id or 0) == int(entity_id or 0):
                skipped += 1
                continue

            changes.append(
                {
                    "batch_id": int(b.id),
                    "source_type": b.source_type,
                    "source_id": b.source_id,
                    "posted_at": b.posted_at.isoformat() if b.posted_at else None,
                    "old_entity": {"type": old_type, "id": old_id},
                    "new_entity": {"type": entity_type, "id": int(entity_id)},
                    "entity_name": name,
                    "entity_type_ar": type_ar,
                }
            )

            if not dry_run:
                b.entity_type = entity_type
                b.entity_id = int(entity_id)
                updated += 1

        if not dry_run and updated:
            db.session.commit()

        try:
            if not dry_run:
                db.session.add(
                    AuditLog(
                        model_name="Ledger",
                        record_id=None,
                        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
                        action="FIX_GL_ENTITIES",
                        old_data=None,
                        new_data=json.dumps(
                            {
                                "override": override,
                                "as_of_date": as_of_date.isoformat(),
                                "found_batches": len(batches),
                                "updated_batches": int(updated),
                                "proposed_updates": int(len(changes)),
                                "skipped": int(skipped),
                                "backup": backup_info,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                current_app.logger.warning('DB commit failed silently')

        return jsonify(
            {
                "success": True,
                "action": "fix_gl_entities",
                "dry_run": dry_run,
                "override": override,
                "as_of_date": as_of_date.isoformat(),
                "backup": backup_info,
                "found_batches": len(batches),
                "updated_batches": updated if not dry_run else 0,
                "proposed_updates": len(changes),
                "skipped": skipped,
                "changes": changes[:200],
            }
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in fix_gl_entities_for_entity_audit: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/entity-balance-audit/recalculate-entities", methods=["POST"], endpoint="recalculate_entities_for_entity_audit")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def recalculate_entities_for_entity_audit():
    try:
        payload = request.get_json(silent=True) or {}

        dry_run = bool(payload.get("dry_run", True))
        tolerance = float(payload.get("tolerance", request.args.get("tolerance", 0.01)) or 0.01)
        max_customers = int(payload.get("max_customers", 500) or 500)
        max_suppliers = int(payload.get("max_suppliers", 500) or 500)
        max_partners = int(payload.get("max_partners", 500) or 500)
        include_archived = (payload.get("include_archived", request.args.get("include_archived", "false")) or "").lower() == "true"
        require_backup = bool(payload.get("require_backup", True))
        allow_without_backup = bool(payload.get("allow_without_backup", False))
        require_backup = bool(payload.get("require_backup", True))
        allow_without_backup = bool(payload.get("allow_without_backup", False))

        as_of_date_str = payload.get("as_of_date") or request.args.get("as_of_date")
        if as_of_date_str:
            as_of_date = datetime.fromisoformat(str(as_of_date_str).replace("Z", "+00:00")).date()
        else:
            as_of_date = datetime.now(timezone.utc).date()
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())

        backup_info = {"attempted": False, "success": None, "message": None, "path": None}
        if not dry_run and require_backup:
            try:
                backup_info["attempted"] = True
                ok, msg, path = perform_backup_db(current_app)
                backup_info["success"] = bool(ok)
                backup_info["message"] = msg
                backup_info["path"] = path
                if not ok and not allow_without_backup:
                    return jsonify({"success": False, "error": msg or "backup_failed", "backup": backup_info}), 500
            except Exception as exc:
                backup_info["attempted"] = True
                backup_info["success"] = False
                backup_info["message"] = str(exc)
                if not allow_without_backup:
                    return jsonify({"success": False, "error": str(exc), "backup": backup_info}), 500

        backup_info = {"attempted": False, "success": None, "message": None, "path": None}
        if not dry_run and require_backup:
            try:
                backup_info["attempted"] = True
                ok, msg, path = perform_backup_db(current_app)
                backup_info["success"] = bool(ok)
                backup_info["message"] = msg
                backup_info["path"] = path
                if not ok and not allow_without_backup:
                    return jsonify({"success": False, "error": msg or "backup_failed", "backup": backup_info}), 500
            except Exception as exc:
                backup_info["attempted"] = True
                backup_info["success"] = False
                backup_info["message"] = str(exc)
                if not allow_without_backup:
                    return jsonify({"success": False, "error": str(exc), "backup": backup_info}), 500

        ar_account = (GL_ACCOUNTS.get("AR") or "1100_AR").upper()
        ap_account = (GL_ACCOUNTS.get("AP") or "2000_AP").upper()

        customer_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        supplier_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "SUPPLIER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        partner_ap_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "PARTNER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        partner_ar_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLBatch, GLBatch.entity_id == Partner.customer_id)
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
                Partner.customer_id.isnot(None),
            )
            .group_by(Partner.id)
            .subquery()
        )
        partner_gl_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                (
                    func.coalesce(partner_ap_sq.c.gl_balance, 0)
                    - func.coalesce(partner_ar_sq.c.gl_balance, 0)
                ).label("gl_balance"),
            )
            .outerjoin(partner_ap_sq, partner_ap_sq.c.entity_id == Partner.id)
            .outerjoin(partner_ar_sq, partner_ar_sq.c.entity_id == Partner.id)
            .subquery()
        )

        cust_stored = func.coalesce(Customer.current_balance, 0)
        cust_gl = func.coalesce(customer_gl_sq.c.gl_balance, 0)
        cust_diff = cust_gl - (-cust_stored)

        customers_q = db.session.query(Customer.id).outerjoin(customer_gl_sq, customer_gl_sq.c.entity_id == Customer.id)
        if hasattr(Customer, "is_archived") and not include_archived:
            customers_q = customers_q.filter(Customer.is_archived.is_(False))
        customers_ids = [
            int(r.id)
            for r in customers_q.filter(func.abs(cust_diff) > tolerance).order_by(func.abs(cust_diff).desc()).limit(max_customers).all()
        ]

        supp_stored = func.coalesce(Supplier.current_balance, 0)
        supp_gl = func.coalesce(supplier_gl_sq.c.gl_balance, 0)
        supp_diff = supp_gl - supp_stored

        suppliers_q = db.session.query(Supplier.id).outerjoin(supplier_gl_sq, supplier_gl_sq.c.entity_id == Supplier.id)
        if hasattr(Supplier, "is_archived") and not include_archived:
            suppliers_q = suppliers_q.filter(Supplier.is_archived.is_(False))
        suppliers_ids = [
            int(r.id)
            for r in suppliers_q.filter(func.abs(supp_diff) > tolerance).order_by(func.abs(supp_diff).desc()).limit(max_suppliers).all()
        ]

        part_stored = func.coalesce(Partner.current_balance, 0)
        part_gl = func.coalesce(partner_gl_sq.c.gl_balance, 0)
        part_diff = part_gl - part_stored

        partners_q = db.session.query(Partner.id).outerjoin(partner_gl_sq, partner_gl_sq.c.entity_id == Partner.id)
        if hasattr(Partner, "is_archived") and not include_archived:
            partners_q = partners_q.filter(Partner.is_archived.is_(False))
        partners_ids = [
            int(r.id)
            for r in partners_q.filter(func.abs(part_diff) > tolerance).order_by(func.abs(part_diff).desc()).limit(max_partners).all()
        ]

        recalculated = {"customers": 0, "suppliers": 0, "partners": 0}
        failures = {"customers": [], "suppliers": [], "partners": []}

        if not dry_run:
            from utils.customer_balance_updater import update_customer_balance_components
            from utils.supplier_balance_updater import update_supplier_balance_components
            from models import update_partner_balance

            for cid in customers_ids:
                try:
                    update_customer_balance_components(cid, db.session)
                    recalculated["customers"] += 1
                except Exception as exc:
                    if len(failures["customers"]) < 50:
                        failures["customers"].append({"id": int(cid), "error": str(exc)[:300]})

            for sid in suppliers_ids:
                try:
                    update_supplier_balance_components(sid, db.session)
                    recalculated["suppliers"] += 1
                except Exception as exc:
                    if len(failures["suppliers"]) < 50:
                        failures["suppliers"].append({"id": int(sid), "error": str(exc)[:300]})

            for pid in partners_ids:
                try:
                    update_partner_balance(pid, db.session)
                    recalculated["partners"] += 1
                except Exception as exc:
                    if len(failures["partners"]) < 50:
                        failures["partners"].append({"id": int(pid), "error": str(exc)[:300]})

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        result = {
            "success": True,
            "action": "recalculate_entities",
            "dry_run": dry_run,
            "as_of_date": as_of_date.isoformat(),
            "tolerance": tolerance,
            "backup": backup_info,
            "target_ids": {
                "customers": customers_ids,
                "suppliers": suppliers_ids,
                "partners": partners_ids,
            },
            "recalculated": recalculated,
            "failures": failures,
        }

        if not dry_run:
            try:
                db.session.add(
                    AuditLog(
                        model_name="Ledger",
                        record_id=None,
                        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
                        action="RECALCULATE_ENTITIES",
                        old_data=None,
                        new_data=json.dumps(result, ensure_ascii=False, default=str),
                    )
                )
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    current_app.logger.warning('DB commit failed silently')

            resp = entity_balance_audit()
            try:
                base = resp.get_json() if hasattr(resp, "get_json") else None
            except Exception:
                base = None
            if isinstance(base, dict) and base.get("success") is True:
                base["recalculate"] = result
                return jsonify(base)
            return resp

        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in recalculate_entities_for_entity_audit: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/entity-balance-audit/auto-fix", methods=["POST"], endpoint="auto_fix_entity_balance_audit")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def auto_fix_entity_balance_audit():
    try:
        payload = request.get_json(silent=True) or {}
        dry_run = bool(payload.get("dry_run", False))
        override = bool(payload.get("override", False))
        max_batches = int(payload.get("max_batches", 5000) or 5000)

        tolerance = float(payload.get("tolerance", request.args.get("tolerance", 0.01)) or 0.01)
        max_customers = int(payload.get("max_customers", 500) or 500)
        max_suppliers = int(payload.get("max_suppliers", 500) or 500)
        max_partners = int(payload.get("max_partners", 500) or 500)
        include_archived = (payload.get("include_archived", request.args.get("include_archived", "false")) or "").lower() == "true"

        as_of_date_str = payload.get("as_of_date") or request.args.get("as_of_date")
        if as_of_date_str:
            as_of_date = datetime.fromisoformat(str(as_of_date_str).replace("Z", "+00:00")).date()
        else:
            as_of_date = datetime.now(timezone.utc).date()
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())

        q = GLBatch.query.filter(
            GLBatch.status == "POSTED",
            GLBatch.posted_at <= as_of_dt,
        )
        supported_source_types = {"PAYMENT", "PAYMENT_SPLIT", "SALE", "SALE_PARTNER_SHARE", "SERVICE", "SERVICE_PARTNER_SHARE", "INVOICE", "EXPENSE", "PREORDER", "SHIPMENT"}
        if override:
            q = q.filter(
                GLBatch.source_type.isnot(None),
                GLBatch.source_id.isnot(None),
                func.upper(GLBatch.source_type).in_(supported_source_types),
            )
        else:
            q = q.filter(or_(GLBatch.entity_type.is_(None), GLBatch.entity_id.is_(None)))

        batches = q.order_by(GLBatch.id.desc()).limit(max_batches).all()

        changes = []
        updated = 0
        skipped = 0

        for b in batches:
            old_type = b.entity_type
            old_id = b.entity_id

            if override:
                name, type_ar, entity_id, entity_type = SmartEntityExtractor.extract_from_source(b)
            else:
                name, type_ar, entity_id, entity_type = SmartEntityExtractor.extract_from_batch(b)
            if not entity_type or not entity_id:
                skipped += 1
                continue

            entity_type = str(entity_type).upper()
            if entity_type not in {"CUSTOMER", "SUPPLIER", "PARTNER", "EMPLOYEE"}:
                skipped += 1
                continue

            if (old_type or "").upper() == entity_type and int(old_id or 0) == int(entity_id or 0):
                skipped += 1
                continue

            changes.append(
                {
                    "batch_id": int(b.id),
                    "source_type": b.source_type,
                    "source_id": b.source_id,
                    "posted_at": b.posted_at.isoformat() if b.posted_at else None,
                    "old_entity": {"type": old_type, "id": old_id},
                    "new_entity": {"type": entity_type, "id": int(entity_id)},
                    "entity_name": name,
                    "entity_type_ar": type_ar,
                }
            )

            if not dry_run:
                b.entity_type = entity_type
                b.entity_id = int(entity_id)
                updated += 1

        if dry_run:
            return jsonify(
                {
                    "success": True,
                    "action": "auto_fix",
                    "dry_run": True,
                    "as_of_date": as_of_date.isoformat(),
                    "backup": backup_info,
                    "found_batches": len(batches),
                    "skipped_batches": int(skipped),
                    "proposed_gl_entity_updates": len(changes),
                    "changes": changes[:200],
                }
            )

        if updated:
            db.session.commit()

        ar_account = (GL_ACCOUNTS.get("AR") or "1100_AR").upper()
        ap_account = (GL_ACCOUNTS.get("AP") or "2000_AP").upper()

        customer_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        supplier_gl_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "SUPPLIER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        partner_ap_sq = (
            db.session.query(
                GLBatch.entity_id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0).label("gl_balance"),
            )
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "PARTNER",
                GLEntry.account == ap_account,
            )
            .group_by(GLBatch.entity_id)
            .subquery()
        )
        partner_ar_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0).label("gl_balance"),
            )
            .join(GLBatch, GLBatch.entity_id == Partner.customer_id)
            .join(GLEntry, GLEntry.batch_id == GLBatch.id)
            .filter(
                GLBatch.status == "POSTED",
                GLBatch.posted_at <= as_of_dt,
                GLBatch.entity_type == "CUSTOMER",
                GLEntry.account == ar_account,
                Partner.customer_id.isnot(None),
            )
            .group_by(Partner.id)
            .subquery()
        )
        partner_gl_sq = (
            db.session.query(
                Partner.id.label("entity_id"),
                (
                    func.coalesce(partner_ap_sq.c.gl_balance, 0)
                    - func.coalesce(partner_ar_sq.c.gl_balance, 0)
                ).label("gl_balance"),
            )
            .outerjoin(partner_ap_sq, partner_ap_sq.c.entity_id == Partner.id)
            .outerjoin(partner_ar_sq, partner_ar_sq.c.entity_id == Partner.id)
            .subquery()
        )

        cust_stored = func.coalesce(Customer.current_balance, 0)
        cust_gl = func.coalesce(customer_gl_sq.c.gl_balance, 0)
        cust_diff = cust_gl - (-cust_stored)
        customers_q = db.session.query(Customer.id).outerjoin(customer_gl_sq, customer_gl_sq.c.entity_id == Customer.id)
        if hasattr(Customer, "is_archived") and not include_archived:
            customers_q = customers_q.filter(Customer.is_archived.is_(False))
        customers_ids = [
            int(r.id)
            for r in customers_q.filter(func.abs(cust_diff) > tolerance).order_by(func.abs(cust_diff).desc()).limit(max_customers).all()
        ]

        supp_stored = func.coalesce(Supplier.current_balance, 0)
        supp_gl = func.coalesce(supplier_gl_sq.c.gl_balance, 0)
        supp_diff = supp_gl - supp_stored
        suppliers_q = db.session.query(Supplier.id).outerjoin(supplier_gl_sq, supplier_gl_sq.c.entity_id == Supplier.id)
        if hasattr(Supplier, "is_archived") and not include_archived:
            suppliers_q = suppliers_q.filter(Supplier.is_archived.is_(False))
        suppliers_ids = [
            int(r.id)
            for r in suppliers_q.filter(func.abs(supp_diff) > tolerance).order_by(func.abs(supp_diff).desc()).limit(max_suppliers).all()
        ]

        part_stored = func.coalesce(Partner.current_balance, 0)
        part_gl = func.coalesce(partner_gl_sq.c.gl_balance, 0)
        part_diff = part_gl - part_stored
        partners_q = db.session.query(Partner.id).outerjoin(partner_gl_sq, partner_gl_sq.c.entity_id == Partner.id)
        if hasattr(Partner, "is_archived") and not include_archived:
            partners_q = partners_q.filter(Partner.is_archived.is_(False))
        partners_ids = [
            int(r.id)
            for r in partners_q.filter(func.abs(part_diff) > tolerance).order_by(func.abs(part_diff).desc()).limit(max_partners).all()
        ]

        from utils.customer_balance_updater import update_customer_balance_components
        from utils.supplier_balance_updater import update_supplier_balance_components
        from models import update_partner_balance

        recalculated = {"customers": 0, "suppliers": 0, "partners": 0}
        failures = {"customers": [], "suppliers": [], "partners": []}

        for cid in customers_ids:
            try:
                update_customer_balance_components(cid, db.session)
                recalculated["customers"] += 1
            except Exception as exc:
                if len(failures["customers"]) < 50:
                    failures["customers"].append({"id": int(cid), "error": str(exc)[:300]})

        for sid in suppliers_ids:
            try:
                update_supplier_balance_components(sid, db.session)
                recalculated["suppliers"] += 1
            except Exception as exc:
                if len(failures["suppliers"]) < 50:
                    failures["suppliers"].append({"id": int(sid), "error": str(exc)[:300]})

        for pid in partners_ids:
            try:
                update_partner_balance(pid, db.session)
                recalculated["partners"] += 1
            except Exception as exc:
                if len(failures["partners"]) < 50:
                    failures["partners"].append({"id": int(pid), "error": str(exc)[:300]})

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        response = entity_balance_audit()
        try:
            base = response.get_json() if hasattr(response, "get_json") else None
        except Exception:
            base = None

        if isinstance(base, dict) and base.get("success") is True:
            base.setdefault("auto_fix", {})
            base["auto_fix"] = {
                "backup": backup_info,
                "updated_batches": int(updated),
                "proposed_updates": int(len(changes)),
                "found_batches": int(len(batches)),
                "skipped_batches": int(skipped),
                "recalculated": recalculated,
                "failures": failures,
                "target_ids": {
                    "customers": customers_ids,
                    "suppliers": suppliers_ids,
                    "partners": partners_ids,
                },
            }
            try:
                db.session.add(
                    AuditLog(
                        model_name="Ledger",
                        record_id=None,
                        user_id=(current_user.id if getattr(current_user, "is_authenticated", False) else None),
                        action="AUTO_FIX",
                        old_data=None,
                        new_data=json.dumps(base["auto_fix"], ensure_ascii=False, default=str),
                    )
                )
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    current_app.logger.warning('DB commit failed silently')
            return jsonify(base)

        return response
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in auto_fix_entity_balance_audit: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/accounts-summary", methods=["GET"], endpoint="get_accounts_summary")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_accounts_summary():
    """جلب ملخص الحسابات (ميزان مراجعة مبسط) من قيود GL مباشرة"""
    try:
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d") if from_date_str else None
        to_date = (
            datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            if to_date_str
            else None
        )

        base_q = (
            db.session.query(
                GLEntry.account,
                Account.name,
                Account.type,
                func.sum(GLEntry.debit).label("td"),
                func.sum(GLEntry.credit).label("tc"),
            )
            .join(Account, Account.code == GLEntry.account)
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .filter(GLBatch.status == "POSTED")
        )
        if from_date:
            base_q = base_q.filter(GLBatch.posted_at >= from_date)
        if to_date:
            base_q = base_q.filter(GLBatch.posted_at <= to_date)

        rows = base_q.group_by(GLEntry.account, Account.name, Account.type).all()

        type_labels = {
            "ASSET": "أصول",
            "LIABILITY": "خصوم",
            "EQUITY": "حقوق ملكية",
            "REVENUE": "إيرادات",
            "EXPENSE": "مصروفات",
            "OTHER": "أخرى",
        }
        type_order = ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE", "OTHER"]
        group_rows = {t: [] for t in type_order}
        group_totals = {
            t: {"type": t, "type_ar": type_labels[t], "total_debit": 0.0, "total_credit": 0.0}
            for t in type_order
        }

        accounts = []
        total_debit = 0.0
        total_credit = 0.0
        for r in rows:
            acc_type = (str(r.type or "").strip()).upper() or "OTHER"
            if acc_type not in group_rows:
                acc_type = "OTHER"
            debit = round(float(r.td or 0), 2)
            credit = round(float(r.tc or 0), 2)
            net = round(debit - credit, 2)
            side = "DR" if net >= 0 else "CR"
            row = {
                "account": (r.account or "").upper(),
                "name": r.name or "",
                "type": acc_type,
                "type_ar": type_labels.get(acc_type, "أخرى"),
                "debit": debit,
                "credit": credit,
                "net": abs(net),
                "side": side,
            }
            accounts.append(row)
            group_rows[acc_type].append(row)
            group_totals[acc_type]["total_debit"] += debit
            group_totals[acc_type]["total_credit"] += credit
            total_debit += debit
            total_credit += credit

        def _type_rank(t):
            return type_order.index(t) if t in type_order else len(type_order)

        accounts.sort(key=lambda r: (_type_rank(r["type"]), r["account"]))
        grouped = []
        for t in type_order:
            rows_for_type = group_rows.get(t) or []
            if not rows_for_type:
                continue
            gt = group_totals[t]
            gt["total_debit"] = round(gt["total_debit"], 2)
            gt["total_credit"] = round(gt["total_credit"], 2)
            gt_net = round(gt["total_debit"] - gt["total_credit"], 2)
            gt["net"] = abs(gt_net)
            gt["side"] = "DR" if gt_net >= 0 else "CR"
            grouped.append({"type": t, "type_ar": gt["type_ar"], "rows": rows_for_type, "totals": gt})

        total_debit = round(total_debit, 2)
        total_credit = round(total_credit, 2)
        diff = round(total_debit - total_credit, 2)
        balanced = abs(diff) < 0.02
        if not balanced:
            current_app.logger.warning("Trial balance unbalanced: debit=%s credit=%s diff=%s", total_debit, total_credit, diff)

        accounts_totals = {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "net_balance": diff,
            "balanced": balanced,
        }

        return jsonify({"rows": accounts, "groups": grouped, "totals": accounts_totals})

    except Exception as e:
        error_msg = f"Error in get_accounts_summary: {str(e)}"
        current_app.logger.error(error_msg)
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/receivables-detailed-summary", methods=["GET"], endpoint="get_receivables_detailed_summary")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_receivables_detailed_summary():
    try:
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d') if from_date_str else None
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if to_date_str else datetime.now(timezone.utc).replace(tzinfo=None)
        receivables = []
        today = datetime.now(timezone.utc).replace(tzinfo=None)

        cust_rows = db.session.query(Customer.id, Customer.current_balance).filter(
            Customer.current_balance.isnot(None),
            func.abs(Customer.current_balance) >= 0.01,
        ).all()
        cust_balances = {int(r.id): float(r.current_balance or 0) for r in cust_rows}

        supp_rows = db.session.query(Supplier.id, Supplier.current_balance).filter(
            Supplier.current_balance.isnot(None),
            func.abs(Supplier.current_balance) >= 0.01,
        ).all()
        supp_balances = {int(r.id): float(r.current_balance or 0) for r in supp_rows}

        part_rows = db.session.query(Partner.id, Partner.current_balance).filter(
            Partner.current_balance.isnot(None),
            func.abs(Partner.current_balance) >= 0.01,
        ).all()
        part_balances = {int(r.id): float(r.current_balance or 0) for r in part_rows}

        for cid, balance in cust_balances.items():
            if not cid:
                continue
            if abs(balance) < 0.01:
                continue
            customer = db.session.get(Customer, cid)
            name = customer.name if customer else f"عميل #{cid}"
            oldest_date = None
            last_payment_date = None
            oldest_sale = Sale.query.filter(Sale.customer_id == cid, Sale.status == 'CONFIRMED').order_by(Sale.sale_date.asc()).first()
            if oldest_sale and oldest_sale.sale_date:
                oldest_date = oldest_sale.sale_date
            oldest_invoice = Invoice.query.filter(Invoice.customer_id == cid, Invoice.cancelled_at.is_(None)).order_by(Invoice.invoice_date.asc()).first()
            if oldest_invoice:
                ref_dt = oldest_invoice.invoice_date or oldest_invoice.created_at
                if ref_dt and (oldest_date is None or ref_dt < oldest_date):
                    oldest_date = ref_dt
            oldest_service = ServiceRequest.query.filter(ServiceRequest.customer_id == cid).order_by(ServiceRequest.received_at.asc()).first()
            if oldest_service:
                ref_dt = oldest_service.received_at or oldest_service.created_at
                if ref_dt and (oldest_date is None or ref_dt < oldest_date):
                    oldest_date = ref_dt
            last_payment = Payment.query.filter(Payment.customer_id == cid).order_by(Payment.payment_date.desc()).first()
            if last_payment and last_payment.payment_date:
                last_payment_date = last_payment.payment_date
            days_overdue = (today - oldest_date).days if balance < 0 and oldest_date else 0
            last_transaction = last_payment_date or oldest_date
            last_transaction_str = last_transaction.strftime('%Y-%m-%d') if last_transaction else None
            receivables.append({
                "name": name,
                "type": "customer",
                "type_ar": "عميل",
                "balance": balance,
                "debit": abs(balance) if balance < 0 else 0.0,
                "credit": balance if balance > 0 else 0.0,
                "days_overdue": days_overdue,
                "last_transaction": last_transaction_str
            })
        
        for sid, balance in supp_balances.items():
            if abs(balance) < 0.01:
                continue
            supplier = db.session.get(Supplier, sid)
            name = supplier.name if supplier else f"مورد #{sid}"
            oldest_exp = Expense.query.filter(Expense.payee_type == 'SUPPLIER', Expense.payee_entity_id == sid).order_by(Expense.date.asc()).first()
            last_pay = Payment.query.filter(Payment.supplier_id == sid).order_by(Payment.payment_date.desc()).first()
            oldest_date = oldest_exp.date if oldest_exp else None
            last_transaction = last_pay.payment_date if last_pay and last_pay.payment_date else oldest_date
            last_transaction_str = last_transaction.strftime('%Y-%m-%d') if last_transaction else None
            days_overdue = (today - oldest_date).days if balance > 0 and oldest_date else 0
            receivables.append({
                "name": name,
                "type": "supplier",
                "type_ar": "مورد",
                "debit": balance if balance < 0 else 0.0,
                "credit": balance if balance > 0 else 0.0,
                "balance": balance,
                "days_overdue": days_overdue,
                "last_transaction": last_transaction_str
            })

        for pid, balance in part_balances.items():
            if abs(balance) < 0.01:
                continue
            partner = db.session.get(Partner, pid)
            name = partner.name if partner else f"شريك #{pid}"
            oldest_exp = Expense.query.filter(Expense.payee_type == 'PARTNER', Expense.payee_entity_id == pid).order_by(Expense.date.asc()).first()
            last_pay = Payment.query.filter(Payment.partner_id == pid).order_by(Payment.payment_date.desc()).first()
            oldest_date = oldest_exp.date if oldest_exp else None
            last_transaction = last_pay.payment_date if last_pay and last_pay.payment_date else oldest_date
            last_transaction_str = last_transaction.strftime('%Y-%m-%d') if last_transaction else None
            days_overdue = (today - oldest_date).days if balance > 0 and oldest_date else 0
            receivables.append({
                "name": name,
                "type": "partner",
                "type_ar": "شريك",
                "debit": balance if balance < 0 else 0.0,
                "credit": balance if balance > 0 else 0.0,
                "balance": balance,
                "days_overdue": days_overdue,
                "last_transaction": last_transaction_str
            })

        total_debit = sum(r["debit"] for r in receivables)
        total_credit = sum(r["credit"] for r in receivables)
        receivables_totals = {
            'total_debit': total_debit,
            'total_credit': total_credit,
            'net_balance': total_credit - total_debit
        }
        
        return jsonify({
            'receivables': receivables,
            'totals': receivables_totals
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in get_receivables_detailed_summary: {str(e)}")
        return jsonify([]), 500

@ledger_bp.route("/receivables-summary", methods=["GET"], endpoint="get_receivables_summary")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_receivables_summary():
    """جلب ملخص الذمم (العملاء، الموردين، الشركاء)"""
    try:
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d') if from_date_str else None
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if to_date_str else None
        
        receivables = []
        
        # 1. العملاء (Customers) - من دفتر الأستاذ
        cust_query = db.session.query(
            GLBatch.entity_id,
            func.sum(GLEntry.debit).label('debit'),
            func.sum(GLEntry.credit).label('credit')
        ).join(GLEntry, GLBatch.id == GLEntry.batch_id).filter(
            GLBatch.entity_type == 'CUSTOMER',
            GLEntry.account == '1100_AR'
        )
        
        if from_date:
            cust_query = cust_query.filter(GLBatch.posted_at >= from_date)
        if to_date:
            cust_query = cust_query.filter(GLBatch.posted_at <= to_date)
            
        cust_rows = cust_query.group_by(GLBatch.entity_id).all()
        
        if cust_rows:
            c_ids = [r.entity_id for r in cust_rows]
            c_map = {c.id: c.name for c in Customer.query.filter(Customer.id.in_(c_ids)).all()}
            
            for r in cust_rows:
                if (r.debit or 0) > 0 or (r.credit or 0) > 0:
                    receivables.append({
                        "name": c_map.get(r.entity_id, f"Client #{r.entity_id}"),
                        "type": "customer",
                        "type_ar": "عميل",
                        "debit": float(r.debit or 0),
                        "credit": float(r.credit or 0)
                    })

        # 2. الموردين (Suppliers) - من دفتر الأستاذ
        supp_query = db.session.query(
            GLBatch.entity_id,
            func.sum(GLEntry.debit).label('debit'),
            func.sum(GLEntry.credit).label('credit')
        ).join(GLEntry, GLBatch.id == GLEntry.batch_id).filter(
            GLBatch.entity_type == 'SUPPLIER',
            GLEntry.account == '2000_AP'
        )
        
        if from_date:
            supp_query = supp_query.filter(GLBatch.posted_at >= from_date)
        if to_date:
            supp_query = supp_query.filter(GLBatch.posted_at <= to_date)
            
        supp_rows = supp_query.group_by(GLBatch.entity_id).all()
        
        if supp_rows:
            s_ids = [r.entity_id for r in supp_rows]
            s_map = {s.id: s.name for s in Supplier.query.filter(Supplier.id.in_(s_ids)).all()}
            
            for r in supp_rows:
                if (r.debit or 0) > 0 or (r.credit or 0) > 0:
                    receivables.append({
                        "name": s_map.get(r.entity_id, f"Supplier #{r.entity_id}"),
                        "type": "supplier",
                        "type_ar": "مورد",
                        "debit": float(r.debit or 0),
                        "credit": float(r.credit or 0)
                    })
        
        # 3. الشركاء (Partners) - من دفتر الأستاذ
        partner_query = db.session.query(
            GLBatch.entity_id,
            func.sum(GLEntry.debit).label('debit'),
            func.sum(GLEntry.credit).label('credit')
        ).join(GLEntry, GLBatch.id == GLEntry.batch_id).filter(
            GLBatch.entity_type == 'PARTNER',
            GLEntry.account == '2000_AP'
        )
        
        if from_date:
            partner_query = partner_query.filter(GLBatch.posted_at >= from_date)
        if to_date:
            partner_query = partner_query.filter(GLBatch.posted_at <= to_date)
        
        partner_rows = partner_query.group_by(GLBatch.entity_id).all()
        
        if partner_rows:
            p_ids = [r.entity_id for r in partner_rows]
            p_map = {p.id: p.name for p in Partner.query.filter(Partner.id.in_(p_ids)).all()}
            
            for r in partner_rows:
                if (r.debit or 0) > 0 or (r.credit or 0) > 0:
                    receivables.append({
                        "name": p_map.get(r.entity_id, f"Partner #{r.entity_id}"),
                        "type": "partner",
                        "type_ar": "شريك",
                        "debit": float(r.debit or 0),
                        "credit": float(r.credit or 0)
                    })
        
        return jsonify(receivables)
        
    except Exception as e:
        current_app.logger.error(f"Error in get_receivables_summary: {str(e)}")
        return jsonify([]), 500

@ledger_bp.route("/export", methods=["GET"], endpoint="export_ledger")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def export_ledger():
    """تصدير دفتر الأستاذ"""
    # يمكن إضافة منطق التصدير هنا
    return "تصدير دفتر الأستاذ - قريباً"

@ledger_bp.route("/transaction/<int:id>", methods=["GET"], endpoint="view_transaction")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def view_transaction(id):
    """عرض تفاصيل العملية"""
    # يمكن إضافة منطق عرض التفاصيل هنا
    return f"تفاصيل العملية رقم {id} - قريباً"

def _parse_dates():
    s_from = request.args.get("from", "").strip()
    s_to = request.args.get("to", "").strip()
    def _parse_one(s, end=False):
        if not s:
            return None
        try:
            if len(s) == 10:
                dt = datetime.strptime(s, "%Y-%m-%d")
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999) if end else dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return datetime.fromisoformat(s)
        except Exception:
            return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not s_from:
        dfrom = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        dfrom = _parse_one(s_from, end=False) or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if not s_to:
        dto = now
    else:
        dto = _parse_one(s_to, end=True) or now
    dto_excl = dto + timedelta(microseconds=1)
    return dfrom, dto_excl

def _entity_filter(q):
    et = (request.args.get("entity_type") or "").strip()
    eid = request.args.get("entity_id", type=int)
    if et and eid:
        q = q.filter(GLBatch.entity_type == et.upper(), GLBatch.entity_id == eid)
    return q

def _get_pagination():
    page = request.args.get("page", type=int)
    per_page = request.args.get("per_page", type=int)
    if page and page > 0:
        pp = 10 if not per_page else max(1, min(per_page, 200))
        return page, pp
    return None, None

@ledger_bp.get("/trial-balance")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def trial_balance():
    dfrom, dto = _parse_dates()
    q = (db.session.query(
            GLEntry.account.label("account"),
            func.coalesce(func.sum(GLEntry.debit), 0.0).label("debit"),
            func.coalesce(func.sum(GLEntry.credit), 0.0).label("credit")
        )
        .join(GLBatch, GLBatch.id == GLEntry.batch_id)
        .filter(GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto)
    )
    q = _entity_filter(q)
    rows = q.group_by(GLEntry.account).order_by(GLEntry.account.asc()).all()
    data = []
    for r in rows:
        dr = float(r.debit or 0.0)
        cr = float(r.credit or 0.0)
        net = dr - cr
        side = "DR" if net >= 0 else "CR"
        data.append({"account": r.account, "debit": dr, "credit": cr, "net": abs(net), "side": side})
    return jsonify({"from": dfrom.isoformat(), "to": (dto - timedelta(microseconds=1)).isoformat(), "rows": data})

@ledger_bp.get("/account/<account>")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def account_ledger(account):
    dfrom, dto = _parse_dates()
    
    account_obj = Account.query.filter_by(code=account).first()
    is_asset_or_expense = True
    if account_obj:
        acc_type = (account_obj.type or "").upper()
        is_asset_or_expense = acc_type in ["ASSET", "EXPENSE"]
    
    if is_asset_or_expense:
        q_open = (db.session.query(func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0.0))
                  .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                  .filter(GLEntry.account == account, GLBatch.posted_at < dfrom))
    else:
        q_open = (db.session.query(func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0.0))
                  .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                  .filter(GLEntry.account == account, GLBatch.posted_at < dfrom))
    q_open = _entity_filter(q_open)
    opening = float(q_open.scalar() or 0.0)
    base = (db.session.query(
                GLBatch.posted_at.label("posted_at"),
                GLBatch.source_type.label("source_type"),
                GLBatch.source_id.label("source_id"),
                GLBatch.purpose.label("purpose"),
                GLBatch.memo.label("memo"),
                GLBatch.entity_type.label("entity_type"),
                GLBatch.entity_id.label("entity_id"),
                GLEntry.debit.label("debit"),
                GLEntry.credit.label("credit"),
                GLEntry.ref.label("ref"),
                GLEntry.id.label("entry_id")
            )
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .filter(GLEntry.account == account, GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto)
            .order_by(GLBatch.posted_at.asc(), GLEntry.id.asc()))
    base = _entity_filter(base)
    page, per_page = _get_pagination()
    if page:
        total = base.count()
        offset = (page - 1) * per_page
        rows = base.limit(per_page).offset(offset).all()
        running_start = opening
        if rows:
            first = rows[0]
            if is_asset_or_expense:
                q_prefix = (db.session.query(func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0.0))
                            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                            .filter(GLEntry.account == account,
                                    or_(GLBatch.posted_at < first.posted_at,
                                        and_(GLBatch.posted_at == first.posted_at, GLEntry.id < first.entry_id))))
            else:
                q_prefix = (db.session.query(func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0.0))
                            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                            .filter(GLEntry.account == account,
                                    or_(GLBatch.posted_at < first.posted_at,
                                        and_(GLBatch.posted_at == first.posted_at, GLEntry.id < first.entry_id))))
            q_prefix = _entity_filter(q_prefix).filter(GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto)
            running_start += float(q_prefix.scalar() or 0.0)
        running = running_start
        lines = []
        for r in rows:
            dr = float(r.debit or 0.0)
            cr = float(r.credit or 0.0)
            if is_asset_or_expense:
                running += (dr - cr)
            else:
                running += (cr - dr)
            
            # 🧠 استخراج الجهة بذكاء من batch
            batch_obj = GLBatch(
                source_type=r.source_type,
                source_id=r.source_id,
                entity_type=r.entity_type,
                entity_id=r.entity_id
            )
            entity_name, entity_type_ar, _, _ = extract_entity_from_batch(batch_obj)
            
            lines.append({
                "date": r.posted_at.isoformat(),
                "source": f"{r.source_type}:{r.source_id}",
                "purpose": r.purpose,
                "memo": r.memo,
                "ref": r.ref,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "entity_name": entity_name,  # ✅ إضافة اسم الجهة
                "entity_type_ar": entity_type_ar,  # ✅ إضافة نوع الجهة بالعربي
                "debit": dr,
                "credit": cr,
                "balance": running
            })
        closing = None
        return jsonify({
            "account": account,
            "from": dfrom.isoformat(),
            "to": (dto - timedelta(microseconds=1)).isoformat(),
            "opening_balance": opening,
            "closing_balance": closing,
            "page": page,
            "per_page": per_page,
            "total": total,
            "lines": lines
        })
    rows = base.all()
    running = opening
    lines = []
    for r in rows:
        dr = float(r.debit or 0.0)
        cr = float(r.credit or 0.0)
        if is_asset_or_expense:
            running += (dr - cr)
        else:
            running += (cr - dr)
        
        # 🧠 استخراج الجهة بذكاء من batch
        batch_obj = GLBatch(
            source_type=r.source_type,
            source_id=r.source_id,
            entity_type=r.entity_type,
            entity_id=r.entity_id
        )
        entity_name, entity_type_ar, _, _ = extract_entity_from_batch(batch_obj)
        
        lines.append({
            "date": r.posted_at.isoformat(),
            "source": f"{r.source_type}:{r.source_id}",
            "purpose": r.purpose,
            "memo": r.memo,
            "ref": r.ref,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "entity_name": entity_name,  # ✅ إضافة اسم الجهة
            "entity_type_ar": entity_type_ar,  # ✅ إضافة نوع الجهة بالعربي
            "debit": dr,
            "credit": cr,
            "balance": running
        })
    return jsonify({
        "account": account,
        "from": dfrom.isoformat(),
        "to": (dto - timedelta(microseconds=1)).isoformat(),
        "opening_balance": opening,
        "closing_balance": running,
        "lines": lines
    })

@ledger_bp.get("/entity")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def entity_ledger():
    dfrom, dto = _parse_dates()
    et = (request.args.get("entity_type") or "").upper().strip()
    eid = request.args.get("entity_id", type=int)
    if not (et and eid):
        return jsonify({"error": "entity_type & entity_id مطلوبان"}), 400
    
    # 🧠 الحصول على اسم الجهة
    entity_name = "—"
    if et == 'CUSTOMER':
        customer = db.session.get(Customer, eid)
        entity_name = customer.name if customer else f"عميل #{eid}"
    elif et == 'SUPPLIER':
        supplier = db.session.get(Supplier, eid)
        if supplier:
            db.session.refresh(supplier)
        entity_name = supplier.name if supplier else f"مورد #{eid}"
    elif et == 'PARTNER':
        partner = db.session.get(Partner, eid)
        entity_name = partner.name if partner else f"شريك #{eid}"
    elif et == 'EMPLOYEE':
        employee = db.session.get(Employee, eid)
        entity_name = employee.name if employee else f"موظف #{eid}"
    base = (db.session.query(
                GLBatch.posted_at.label("posted_at"),
                GLBatch.source_type.label("source_type"),
                GLBatch.source_id.label("source_id"),
                GLBatch.purpose.label("purpose"),
                GLBatch.memo.label("memo"),
                GLEntry.account.label("account"),
                GLEntry.debit.label("debit"),
                GLEntry.credit.label("credit"),
                GLEntry.ref.label("ref"),
                GLEntry.id.label("entry_id")
            )
            .join(GLBatch, GLBatch.id == GLEntry.batch_id)
            .filter(GLBatch.entity_type == et, GLBatch.entity_id == eid,
                    GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto)
            .order_by(GLBatch.posted_at.asc(), GLEntry.id.asc()))
    total_dr_q = (db.session.query(func.coalesce(func.sum(GLEntry.debit), 0.0))
                  .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                  .filter(GLBatch.entity_type == et, GLBatch.entity_id == eid,
                          GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto))
    total_cr_q = (db.session.query(func.coalesce(func.sum(GLEntry.credit), 0.0))
                  .join(GLBatch, GLBatch.id == GLEntry.batch_id)
                  .filter(GLBatch.entity_type == et, GLBatch.entity_id == eid,
                          GLBatch.posted_at >= dfrom, GLBatch.posted_at < dto))
    page, per_page = _get_pagination()
    if page:
        total = base.count()
        rows = base.limit(per_page).offset((page - 1) * per_page).all()
        items = []
        for r in rows:
            dr = float(r.debit or 0.0)
            cr = float(r.credit or 0.0)
            items.append({
                "date": r.posted_at.isoformat(),
                "source": f"{r.source_type}:{r.source_id}",
                "purpose": r.purpose,
                "memo": r.memo,
                "account": r.account,
                "debit": dr,
                "credit": cr,
                "ref": r.ref
            })
        return jsonify({
            "entity_type": et,
            "entity_id": eid,
            "entity_name": entity_name,  # ✅ إضافة اسم الجهة
            "from": dfrom.isoformat(),
            "to": (dto - timedelta(microseconds=1)).isoformat(),
            "total_debit": float(total_dr_q.scalar() or 0.0),
            "total_credit": float(total_cr_q.scalar() or 0.0),
            "page": page,
            "per_page": per_page,
            "total": total,
            "lines": items
        })
    rows = base.all()
    total_dr = float(total_dr_q.scalar() or 0.0)
    total_cr = float(total_cr_q.scalar() or 0.0)
    items = []
    for r in rows:
        dr = float(r.debit or 0.0)
        cr = float(r.credit or 0.0)
        items.append({
            "date": r.posted_at.isoformat(),
            "source": f"{r.source_type}:{r.source_id}",
            "purpose": r.purpose,
            "memo": r.memo,
            "account": r.account,
            "debit": dr,
            "credit": cr,
            "ref": r.ref
        })
    return jsonify({
        "entity_type": et,
        "entity_id": eid,
        "entity_name": entity_name,  # ✅ إضافة اسم الجهة
        "from": dfrom.isoformat(),
        "to": (dto - timedelta(microseconds=1)).isoformat(),
        "total_debit": total_dr,
        "total_credit": total_cr,
        "lines": items
    })


@ledger_bp.route("/batch/<int:batch_id>", methods=["GET"], endpoint="get_batch_details")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_batch_details(batch_id):
    """جلب تفاصيل قيد محاسبي (GLBatch + Entries)"""
    try:
        # جلب القيد
        batch = db.session.get(GLBatch, batch_id)
        if not batch:
            return jsonify({"success": False, "error": "القيد غير موجود"}), 404
        
        # 🧠 استخراج الجهة المرتبطة بذكاء
        entity_name, entity_type_ar, entity_id_extracted, entity_type_code = extract_entity_from_batch(batch)
        
        # جلب القيود الفرعية
        entries = GLEntry.query.filter_by(batch_id=batch_id).all()
        
        entries_list = []
        for entry in entries:
            account = Account.query.filter_by(code=entry.account).first()
            entries_list.append({
                "account_code": entry.account,
                "account_name": account.name if account else entry.account,
                "debit": float(entry.debit or 0),
                "credit": float(entry.credit or 0),
                "ref": entry.ref
            })
        
        return jsonify({
            "success": True,
            "batch": {
                "id": batch.id,
                "code": batch.code,
                "source_type": batch.source_type,
                "source_id": batch.source_id,
                "purpose": batch.purpose,
                "memo": batch.memo,
                "posted_at": batch.posted_at.isoformat() if batch.posted_at else None,
                "currency": batch.currency,
                "status": batch.status,
                "entity_name": entity_name,  # ✅ إضافة اسم الجهة
                "entity_type": entity_type_ar,  # ✅ إضافة نوع الجهة بالعربي
                "entity_id": entity_id_extracted,  # ✅ إضافة معرف الجهة
                "entity_type_code": entity_type_code  # ✅ إضافة كود نوع الجهة
            },
            "entries": entries_list,
            "total_debit": sum(e["debit"] for e in entries_list),
            "total_credit": sum(e["credit"] for e in entries_list)
        })
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "حدث خطأ داخلي"}), 500

@ledger_bp.route('/api/ar_ap_summary', methods=['GET'])
@login_required
def get_ar_ap_summary():
    """
    تقرير الذمم التفصيلي الحقيقي المعتمد على قيود دفتر الأستاذ فقط.
    يجمع الأرصدة لكل كيان (عميل، مورد، شريك، موظف).
    """
    try:
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        from_date, to_date = _parse_ledger_date_range(from_date_str, to_date_str)

        query = db.session.query(
            GLBatch.entity_type,
            GLBatch.entity_id,
            func.sum(GLEntry.debit).label('total_debit'),
            func.sum(GLEntry.credit).label('total_credit'),
            func.max(GLBatch.posted_at).label('last_transaction_date')
        ).join(GLEntry, GLEntry.batch_id == GLBatch.id)\
         .filter(GLBatch.status == 'POSTED')\
         .filter(GLBatch.entity_type.isnot(None))\
         .filter(
             or_(
                 GLEntry.account.like('11%'), # AR & Receivables
                 GLEntry.account.like('20%'), # AP & Payables
                 GLEntry.account.like('1050%') # Employee Receivables
             )
         )
         
        if to_date:
            query = query.filter(GLBatch.posted_at <= to_date)
            
        results = query.group_by(GLBatch.entity_type, GLBatch.entity_id).all()
        
        summary_data = []
        total_ar = Decimal(0)
        total_ap = Decimal(0)
        
        entity_ids = {
            'CUSTOMER': [],
            'SUPPLIER': [],
            'PARTNER': [],
            'EMPLOYEE': []
        }
        
        for r in results:
            etype = (r.entity_type or '').upper()
            if etype in entity_ids:
                entity_ids[etype].append(r.entity_id)
                
        names_map = {}
        
        if entity_ids['CUSTOMER']:
            customers = db.session.query(Customer.id, Customer.name).filter(Customer.id.in_(entity_ids['CUSTOMER'])).all()
            for c in customers: names_map[('CUSTOMER', c.id)] = c.name
            
        if entity_ids['SUPPLIER']:
            suppliers = db.session.query(Supplier.id, Supplier.name).filter(Supplier.id.in_(entity_ids['SUPPLIER'])).all()
            for s in suppliers: names_map[('SUPPLIER', s.id)] = s.name
            
        if entity_ids['PARTNER']:
            partners = db.session.query(Partner.id, Partner.name).filter(Partner.id.in_(entity_ids['PARTNER'])).all()
            for p in partners: names_map[('PARTNER', p.id)] = p.name

        if entity_ids['EMPLOYEE']:
            employees = db.session.query(Employee.id, Employee.name).filter(Employee.id.in_(entity_ids['EMPLOYEE'])).all()
            for e in employees: names_map[('EMPLOYEE', e.id)] = e.name
            
        for r in results:
            etype = (r.entity_type or '').upper()
            eid = r.entity_id
            debit = Decimal(str(r.total_debit or 0))
            credit = Decimal(str(r.total_credit or 0))
            balance = debit - credit
            
            if abs(balance) < Decimal('0.01'):
                continue
                
            if not eid:
                name = f"غير محدد ({etype})"
            else:
                name = names_map.get((etype, eid), f"{etype} #{eid}")
            
            if balance > 0:
                total_ar += balance
            else:
                total_ap += abs(balance)
                
            summary_data.append({
                'entity_type': etype,
                'entity_id': eid,
                'entity_name': name,
                'total_debit': float(debit),
                'total_credit': float(credit),
                'balance': float(balance),
                'last_transaction': r.last_transaction_date.strftime('%Y-%m-%d') if r.last_transaction_date else None
            })
            
        summary_data.sort(key=lambda x: abs(x['balance']), reverse=True)
            
        return jsonify({
            'data': summary_data,
            'totals': {
                'total_ar': float(total_ar),
                'total_ap': float(total_ap),
                'net_position': float(total_ar - total_ap)
            }
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500

@ledger_bp.route("/stats", methods=["GET"], endpoint="get_dashboard_stats")
@login_required
@utils.permission_required(SystemPermissions.MANAGE_LEDGER)
def get_dashboard_stats():
    """إحصائيات سريعة للوحة القيادة: النقد، الذمم المدينة، الذمم الدائنة، الأرباح"""
    try:
        base_gl = db.session.query(GLEntry).join(GLBatch).filter(GLBatch.status == "POSTED")

        cash_accounts = db.session.query(Account.code).filter(
            or_(Account.type == "ASSET", Account.code.like("1%")),
            or_(Account.name.ilike("%cash%"), Account.name.ilike("%نقد%"), Account.name.ilike("%صندوق%"))
        ).all()
        cash_codes = [c[0] for c in cash_accounts] if cash_accounts else []
        cash = 0.0
        if cash_codes:
            cash = float(
                base_gl.filter(GLEntry.account.in_(cash_codes))
                .with_entities(func.sum(GLEntry.debit - GLEntry.credit)).scalar() or 0
            )

        ar_account = GL_ACCOUNTS.get("AR", "1200_AR")
        ar = float(
            base_gl.filter(GLEntry.account == ar_account)
            .with_entities(func.sum(GLEntry.debit - GLEntry.credit)).scalar() or 0
        )

        ap_account = GL_ACCOUNTS.get("AP", "2100_AP")
        ap = float(
            base_gl.filter(GLEntry.account == ap_account)
            .with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0
        )

        total_revenue = float(
            base_gl.join(Account, Account.code == GLEntry.account)
            .filter(Account.type == "REVENUE")
            .with_entities(func.sum(GLEntry.credit - GLEntry.debit)).scalar() or 0
        )
        total_expenses = float(
            base_gl.join(Account, Account.code == GLEntry.account)
            .filter(Account.type == "EXPENSE")
            .with_entities(func.sum(GLEntry.debit - GLEntry.credit)).scalar() or 0
        )
        profit = total_revenue - total_expenses

        return jsonify({"cash": cash, "ar": ar, "ap": ap, "profit": profit})
    except Exception as e:
        current_app.logger.error(f"Error in get_dashboard_stats: {str(e)}")
        return jsonify({"cash": 0, "ar": 0, "ap": 0, "profit": 0, "error": "حدث خطأ داخلي"}), 500


@ledger_bp.route('/api/inventory_breakdown', methods=['GET'])
@login_required
def get_inventory_breakdown():
    """تحليل قيمة المخزون الفعلي (المملوك vs الأمانة) ومقارنته بالدفتر"""
    try:
        from models import Warehouse, WarehouseType
        
        ledger_inventory = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit)
        ).join(GLBatch, GLBatch.id == GLEntry.batch_id)\
         .filter(GLEntry.account == '1200_INVENTORY')\
         .filter(GLBatch.status == 'POSTED').scalar() or 0
        
        inventory_query = db.session.query(
            Warehouse.warehouse_type,
            func.sum(StockLevel.quantity * Product.purchase_price)
        ).join(StockLevel, StockLevel.warehouse_id == Warehouse.id)\
         .join(Product, Product.id == StockLevel.product_id)\
         .group_by(Warehouse.warehouse_type).all()
         
        breakdown = {
            'NORMAL': 0.0,
            'EXCHANGE': 0.0,
            'PARTNER': 0.0,
            'TOTAL_PHYSICAL': 0.0
        }
        
        for w_type, value in inventory_query:
            val = float(value or 0)
            w_type_str = str(w_type.value if hasattr(w_type, 'value') else w_type)
            
            if w_type_str == 'NORMAL' or w_type_str == 'MAIN':
                breakdown['NORMAL'] += val
            elif w_type_str == 'EXCHANGE':
                breakdown['EXCHANGE'] += val
            elif w_type_str == 'PARTNER':
                breakdown['PARTNER'] += val
            
            breakdown['TOTAL_PHYSICAL'] += val
            
        return jsonify({
            'ledger_value': float(ledger_inventory),
            'physical_breakdown': breakdown,
            'diff': float(ledger_inventory) - breakdown['NORMAL']
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "حدث خطأ داخلي"}), 500
