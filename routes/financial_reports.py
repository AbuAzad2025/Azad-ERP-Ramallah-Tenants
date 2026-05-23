from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import func, and_, or_
import json

from models import (
    db, Account, GLBatch, GLEntry, Customer, Supplier, Partner,
    Sale, Payment, Expense, Invoice, ServiceRequest,
    GL_ACCOUNTS, _gl_upsert_batch_and_entries, _ensure_account_exists,
)
from utils import permission_required, get_income_tax_rate, classify_entity_balance
from permissions_config.enums import SystemPermissions

# إنشاء Blueprint
financial_reports_bp = Blueprint('financial_reports', __name__, url_prefix='/reports/financial')

@financial_reports_bp.route('/')
@permission_required(SystemPermissions.VIEW_REPORTS)
def index():
    return render_template('reports/financial/index.html')


@financial_reports_bp.route('/accrue-income-tax', methods=['POST'])
@permission_required(SystemPermissions.VIEW_REPORTS)
def accrue_income_tax():
    """استحقاق ضريبة الدخل على الربح: قيد من مدين 6200 (مصروف ضريبة) دائن 2200 (ضريبة مستحقة)."""
    try:
        start_date = request.form.get('start_date') or request.json.get('start_date') if request.is_json else None
        end_date = request.form.get('end_date') or request.json.get('end_date') if request.is_json else None
        if not start_date or not end_date:
            return jsonify({'success': False, 'error': 'start_date و end_date مطلوبان'}), 400
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date()
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date()
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        revenue = db.session.query(
            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0)
        ).join(GLBatch).join(Account, Account.code == GLEntry.account).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            Account.type == 'REVENUE'
        ).scalar() or 0

        expenses = db.session.query(
            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0)
        ).join(GLBatch).join(Account, Account.code == GLEntry.account).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            Account.type == 'EXPENSE'
        ).scalar() or 0

        profit_before_tax = float(revenue) - float(expenses)
        if profit_before_tax <= 0:
            return jsonify({
                'success': True,
                'posted': False,
                'reason': 'no_profit',
                'profit_before_tax': round(profit_before_tax, 2),
                'message': 'لا يوجد ربح موجب للفترة؛ لم يُنشأ قيد ضريبة.'
            })

        tax_rate = get_income_tax_rate()
        tax_amount = round(profit_before_tax * (tax_rate / 100.0), 2)
        if tax_amount <= 0:
            return jsonify({
                'success': True,
                'posted': False,
                'reason': 'zero_tax',
                'profit_before_tax': round(profit_before_tax, 2),
                'message': 'مبلغ الضريبة صفر.'
            })

        period_key = start_date.strftime('%Y-%m')
        acc_exp = GL_ACCOUNTS.get('INCOME_TAX_EXP', '6200_INCOME_TAX_EXPENSE')
        acc_pay = GL_ACCOUNTS.get('INCOME_TAX_PAYABLE', '2200_INCOME_TAX_PAYABLE')
        conn = db.session.connection()
        _ensure_account_exists(conn, acc_exp)
        _ensure_account_exists(conn, acc_pay)
        memo = f"استحقاق ضريبة الدخل عن الفترة {start_date} إلى {end_date} (الربح قبل الضريبة: {profit_before_tax:.2f}، النسبة: {tax_rate}%)"
        _gl_upsert_batch_and_entries(
            conn,
            source_type='TAX_ACCRUAL',
            source_id=0,
            purpose=f'INCOME_TAX_{period_key}',
            currency='ILS',
            memo=memo,
            entries=[
                (acc_exp, tax_amount, 0.0),
                (acc_pay, 0.0, tax_amount),
            ],
            ref=f'TAX-{period_key}',
            entity_type=None,
            entity_id=None,
        )
        db.session.commit()
        return jsonify({
            'success': True,
            'posted': True,
            'profit_before_tax': round(profit_before_tax, 2),
            'tax_rate': tax_rate,
            'tax_amount': tax_amount,
            'period_key': period_key,
            'message': f'تم ترحيل استحقاق ضريبة الدخل: {tax_amount} (مدين 6200، دائن 2200).'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('accrue_income_tax failed')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@financial_reports_bp.route('/income-statement')
@permission_required(SystemPermissions.VIEW_REPORTS)
def income_statement():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
        
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date).date()
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date).date()

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        
        start_date_dt = datetime.combine(start_date, datetime.min.time())
        end_date_dt = datetime.combine(end_date, datetime.max.time())
        
        revenue_query = db.session.query(
            func.sum(GLEntry.credit - GLEntry.debit).label('total_revenue')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'REVENUE'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        # تكلفة البضاعة المباعة (COGS)
        # عادة ما تكون حسابات المصاريف التي تبدأ بـ 51
        cogs_query = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit).label('total_cogs')
        ).join(GLBatch).join(Account, Account.code == GLEntry.account).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'EXPENSE',
            or_(
                GLEntry.account.like('51%'),
                GLEntry.account == '5105_COGS_EXCHANGE'
            )
        ).scalar() or 0
        
        # المصاريف التشغيلية (كل المصاريف ما عدا COGS والضرائب)
        expenses_query = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit).label('total_expenses')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'EXPENSE',
            ~GLEntry.account.like('51%'),
            GLEntry.account != '5105_COGS_EXCHANGE'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        

        taxes_query = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit).label('total_taxes')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'EXPENSE',
            or_(
                Account.name.ilike('%tax%'),
                Account.name.ilike('%ضريبة%')
            )
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        total_revenue = float(revenue_query)
        total_cogs = float(cogs_query)
        gross_profit = total_revenue - total_cogs
        
        # المصاريف التشغيلية يجب أن تستثني الضرائب المحسوبة منفصلاً لتجنب الازدواجية
        operating_expenses = float(expenses_query) - float(taxes_query)
        operating_profit = gross_profit - operating_expenses
        
        total_taxes = float(taxes_query)
        net_profit = operating_profit - total_taxes
        
        revenue_details = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.credit - GLEntry.debit).label('amount')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'REVENUE'
        ).group_by(GLEntry.account, Account.name).having(func.sum(GLEntry.credit - GLEntry.debit) != 0).order_by(func.sum(GLEntry.credit).desc()).all()
        
        expense_details = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.debit - GLEntry.credit).label('amount')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'EXPENSE',
            ~GLEntry.account.like('51%'),
            GLEntry.account != '5105_COGS_EXCHANGE',
            ~or_(
                Account.name.ilike('%tax%'),
                Account.name.ilike('%ضريبة%')
            )
        ).group_by(GLEntry.account, Account.name).having(func.sum(GLEntry.debit - GLEntry.credit) != 0).order_by(func.sum(GLEntry.debit).desc()).all()
        
        cogs_details = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.debit - GLEntry.credit).label('amount')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_date_dt,
            GLBatch.posted_at <= end_date_dt,
            Account.type == 'EXPENSE',
            or_(
                GLEntry.account.like('51%'),
                GLEntry.account == '5105_COGS_EXCHANGE'
            )
        ).group_by(GLEntry.account, Account.name).having(func.sum(GLEntry.debit - GLEntry.credit) != 0).order_by(func.sum(GLEntry.debit).desc()).all()
        
        data = {
            'start_date': start_date,
            'end_date': end_date,
            'from_date': start_date,
            'to_date': end_date,
            'total_revenue': total_revenue,
            'total_cogs': total_cogs,
            'gross_profit': gross_profit,
            'gross_margin': (gross_profit / total_revenue * 100) if total_revenue > 0 else 0,
            'operating_expenses': operating_expenses,
            'operating_profit': operating_profit,
            'profit_before_tax': operating_profit,
            'operating_margin': (operating_profit / total_revenue * 100) if total_revenue > 0 else 0,
            'total_taxes': total_taxes,
            'income_tax_expense': total_taxes,
            'net_profit': net_profit,
            'net_margin': (net_profit / total_revenue * 100) if total_revenue > 0 else 0,
            'is_profit': net_profit >= 0,
            'revenues': revenue_details,
            'expenses': expense_details,
            'cogs_details': cogs_details,
            'revenue_details': revenue_details,
            'expense_details': expense_details
        }
        
        if request.args.get('format') == 'json' or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'report_type': 'income_statement',
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat()
                },
                'summary': {
                    'total_revenue': total_revenue,
                    'total_cogs': total_cogs,
                    'gross_profit': gross_profit,
                    'gross_margin': (gross_profit / total_revenue * 100) if total_revenue > 0 else 0,
                    'operating_expenses': operating_expenses,
                    'operating_profit': operating_profit,
                    'operating_margin': (operating_profit / total_revenue * 100) if total_revenue > 0 else 0,
                    'total_taxes': total_taxes,
                    'net_profit': net_profit,
                    'net_margin': (net_profit / total_revenue * 100) if total_revenue > 0 else 0
                },
                'details': {
                    'revenue': [{'account': r.account, 'name': r.name, 'amount': float(r.amount)} for r in revenue_details],
                    'cogs': [{'account': c.account, 'name': c.name, 'amount': float(c.amount)} for c in cogs_details],
                    'expenses': [{'account': e.account, 'name': e.name, 'amount': float(e.amount)} for e in expense_details]
                }
            })
        
        return render_template('reports/financial/income_statement.html', **data)
        
    except Exception as e:
        current_app.logger.error(f"خطأ في قائمة الدخل: {str(e)}")
        if request.args.get('format') == 'json':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
        return render_template('errors/500.html', error="تعذر تنفيذ العملية. حاول مرة أخرى."), 500

@financial_reports_bp.route('/balance-sheet')
@permission_required(SystemPermissions.VIEW_REPORTS)
def balance_sheet():
    """الميزانية العمومية (Balance Sheet) - يدعم HTML وJSON"""
    try:
        # تاريخ الميزانية
        balance_date = request.args.get('date')
        if not balance_date:
            balance_date = date.today()
        else:
            balance_date = datetime.fromisoformat(balance_date).date()

        balance_dt = datetime.combine(balance_date, datetime.max.time())
        
        # الأصول المتداولة
        # استخدام Account.type بدلاً من الكود
        current_assets = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'ASSET',
            GLEntry.account.like('1%'),
            ~GLEntry.account.like('15%') # استبعاد الأصول الثابتة افتراضاً بناءً على الكود
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        # الأصول الثابتة
        fixed_assets = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'ASSET',
            GLEntry.account.like('15%')
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        # الخصوم المتداولة
        current_liabilities = db.session.query(
            func.sum(GLEntry.credit - GLEntry.debit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'LIABILITY'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        # حقوق الملكية (رأس المال والاحتياطيات)
        equity = db.session.query(
            func.sum(GLEntry.credit - GLEntry.debit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'EQUITY'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        # --- حساب الأرباح المحتجزة (Retained Earnings) ---
        # هي مجموع الإيرادات - مجموع المصاريف لكل الفترات السابقة حتى تاريخ الميزانية
        total_revenue_accumulated = db.session.query(
            func.sum(GLEntry.credit - GLEntry.debit)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'REVENUE'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        total_expenses_accumulated = db.session.query(
            func.sum(GLEntry.debit - GLEntry.credit)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'EXPENSE'
        ).join(Account, Account.code == GLEntry.account).scalar() or 0
        
        retained_earnings = float(total_revenue_accumulated) - float(total_expenses_accumulated)
        
        # إضافة الأرباح المحتجزة إلى حقوق الملكية
        equity = float(equity) + retained_earnings
        
        # تفاصيل الأصول مع أسماء
        assets_details = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.debit - GLEntry.credit).label('balance')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            Account.type == 'ASSET'
        ).group_by(GLEntry.account, Account.name).having(func.sum(GLEntry.debit - GLEntry.credit) != 0).all()
        
        # تفاصيل الخصوم وحقوق الملكية مع أسماء
        liabilities_equity_details = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.credit - GLEntry.debit).label('balance')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= balance_dt,
            or_(Account.type == 'LIABILITY', Account.type == 'EQUITY')
        ).group_by(GLEntry.account, Account.name).having(func.sum(GLEntry.credit - GLEntry.debit) != 0).all()
        
        # إضافة سطر الأرباح المحتجزة إلى تفاصيل الخصوم وحقوق الملكية
        from types import SimpleNamespace
        liabilities_equity_list = list(liabilities_equity_details)
        if abs(retained_earnings) > 0.001:
            liabilities_equity_list.append(SimpleNamespace(
                account='3900_RETAINED_EARNINGS',
                name='أرباح محتجزة (إيرادات − مصاريف تراكمية)',
                balance=float(retained_earnings)
            ))
        
        total_assets = float(current_assets) + float(fixed_assets)
        total_liabilities_equity = float(current_liabilities) + float(equity)
        is_balanced = abs(total_assets - total_liabilities_equity) < 0.01
        
        data = {
            'balance_date': balance_date,
            'current_assets': float(current_assets),
            'fixed_assets': float(fixed_assets),
            'total_assets': total_assets,
            'current_liabilities': float(current_liabilities),
            'equity': float(equity),
            'retained_earnings': float(retained_earnings),
            'total_liabilities_equity': total_liabilities_equity,
            'is_balanced': is_balanced,
            'assets_details': assets_details,
            'liabilities_equity_details': liabilities_equity_list
        }
        
        # إذا طلب JSON
        if request.args.get('format') == 'json' or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'report_type': 'balance_sheet',
                'balance_date': balance_date.isoformat(),
                'summary': {
                    'current_assets': float(current_assets),
                    'fixed_assets': float(fixed_assets),
                    'total_assets': total_assets,
                    'current_liabilities': float(current_liabilities),
                    'equity': float(equity),
                    'retained_earnings': float(retained_earnings),
                    'total_liabilities_equity': total_liabilities_equity,
                    'is_balanced': is_balanced
                },
                'details': {
                    'assets': [{'account': a.account, 'name': a.name, 'balance': float(a.balance)} for a in assets_details],
                    'liabilities_equity': [{'account': l.account, 'name': l.name, 'balance': float(l.balance)} for l in liabilities_equity_list]
                }
            })
        
        # إرجاع HTML template
        return render_template('reports/financial/balance_sheet.html', **data)
        
    except Exception as e:
        current_app.logger.error(f"خطأ في الميزانية العمومية: {str(e)}")
        if request.args.get('format') == 'json':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
        return render_template('errors/500.html', error="تعذر تنفيذ العملية. حاول مرة أخرى."), 500

@financial_reports_bp.route('/cash-flow')
@permission_required(SystemPermissions.VIEW_REPORTS)
def cash_flow():
    """قائمة التدفق النقدي (Cash Flow Statement)"""
    try:
        # معاملات التاريخ
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            # افتراضي: الشهر الحالي
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
        
        # تحويل التواريخ
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date).date()
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date).date()

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        
        # التدفق النقدي من العمليات
        operating_cash_in = db.session.query(
            func.sum(GLEntry.debit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),  # النقدية
                GLEntry.account.like('1010%'),  # البنك
                GLEntry.account.like('1020%')   # البطاقات
            ),
            GLBatch.source_type.in_(['PAYMENT', 'SALE'])
        ).scalar() or 0
        
        operating_cash_out = db.session.query(
            func.sum(GLEntry.credit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),  # النقدية
                GLEntry.account.like('1010%'),  # البنك
                GLEntry.account.like('1020%')   # البطاقات
            ),
            GLBatch.source_type.in_(['EXPENSE', 'PAYMENT'])
        ).scalar() or 0
        
        # التدفق النقدي من الاستثمارات
        investing_cash_in = db.session.query(
            func.sum(GLEntry.debit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),
                GLEntry.account.like('1010%'),
                GLEntry.account.like('1020%')
            ),
            GLBatch.source_type.in_(['ASSET_SALE', 'INVESTMENT'])
        ).scalar() or 0
        
        investing_cash_out = db.session.query(
            func.sum(GLEntry.credit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),
                GLEntry.account.like('1010%'),
                GLEntry.account.like('1020%')
            ),
            GLBatch.source_type.in_(['ASSET_PURCHASE', 'INVESTMENT'])
        ).scalar() or 0
        
        # التدفق النقدي من التمويل
        financing_cash_in = db.session.query(
            func.sum(GLEntry.debit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),
                GLEntry.account.like('1010%'),
                GLEntry.account.like('1020%')
            ),
            GLBatch.source_type.in_(['LOAN', 'CAPITAL'])
        ).scalar() or 0
        
        financing_cash_out = db.session.query(
            func.sum(GLEntry.credit).label('total')
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            or_(
                GLEntry.account.like('1000%'),
                GLEntry.account.like('1010%'),
                GLEntry.account.like('1020%')
            ),
            GLBatch.source_type.in_(['LOAN_PAYMENT', 'DIVIDEND'])
        ).scalar() or 0
        
        # الحسابات
        net_operating_cash = float(operating_cash_in) - float(operating_cash_out)
        net_investing_cash = float(investing_cash_in) - float(investing_cash_out)
        net_financing_cash = float(financing_cash_in) - float(financing_cash_out)
        net_cash_flow = net_operating_cash + net_investing_cash + net_financing_cash
        
        data = {
            'start_date': start_date,
            'end_date': end_date,
            'from_date': start_date,
            'to_date': end_date,
            'operating': {
                'inflows': float(operating_cash_in),
                'outflows': float(operating_cash_out),
                'net': net_operating_cash
            },
            'investing': {
                'inflows': float(investing_cash_in),
                'outflows': float(investing_cash_out),
                'net': net_investing_cash
            },
            'financing': {
                'inflows': float(financing_cash_in),
                'outflows': float(financing_cash_out),
                'net': net_financing_cash
            },
            'total_net_cash_flow': net_cash_flow
        }
        
        if request.args.get('format') == 'json' or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'report_type': 'cash_flow',
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat()
                },
                'summary': {
                    'operating_cash_in': float(operating_cash_in),
                    'operating_cash_out': float(operating_cash_out),
                    'net_operating_cash': net_operating_cash,
                    'investing_cash_in': float(investing_cash_in),
                    'investing_cash_out': float(investing_cash_out),
                    'net_investing_cash': net_investing_cash,
                    'financing_cash_in': float(financing_cash_in),
                    'financing_cash_out': float(financing_cash_out),
                    'net_financing_cash': net_financing_cash,
                    'net_cash_flow': net_cash_flow
                }
            })
        
        return render_template('reports/financial/cash_flow.html', **data)
        
    except Exception as e:
        current_app.logger.error(f"خطأ في التدفق النقدي: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@financial_reports_bp.route('/balances-summary')
@permission_required(SystemPermissions.VIEW_REPORTS)
def balances_summary():
    """تقرير الأرصدة المجمعة"""
    try:
        # أرصدة العملاء
        customers = Customer.query.all()
        customer_balances = []
        total_customer_balance = 0
        
        for customer in customers:
            balance = customer.current_balance
            customer_balances.append({
                'id': customer.id,
                'name': customer.name or '',
                'balance': float(balance),
                'currency': customer.currency or 'ILS'
            })
            total_customer_balance += float(balance)
        
        # أرصدة الموردين
        suppliers = Supplier.query.all()
        supplier_balances = []
        total_supplier_balance = 0
        
        for supplier in suppliers:
            balance = supplier.current_balance
            supplier_balances.append({
                'id': supplier.id,
                'name': supplier.name or '',
                'balance': float(balance),
                'currency': supplier.currency or 'ILS'
            })
            total_supplier_balance += float(balance)
        
        # أرصدة الشركاء
        partners = Partner.query.all()
        partner_balances = []
        total_partner_balance = 0
        
        for partner in partners:
            balance = partner.current_balance
            partner_balances.append({
                'id': partner.id,
                'name': partner.name or '',
                'balance': float(balance),
                'currency': partner.currency or 'ILS'
            })
            total_partner_balance += float(balance)
        
        return jsonify({
            'success': True,
            'report_type': 'balances_summary',
            'summary': {
                'total_customer_balance': total_customer_balance,
                'total_supplier_balance': total_supplier_balance,
                'total_partner_balance': total_partner_balance,
                'net_position': total_customer_balance - total_supplier_balance - total_partner_balance
            },
            'details': {
                'customers': customer_balances,
                'suppliers': supplier_balances,
                'partners': partner_balances
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تقرير الأرصدة: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@financial_reports_bp.route('/validation')
@permission_required(SystemPermissions.VIEW_REPORTS)
def validation_report():
    """تقرير التحقق من صحة النظام المحاسبي"""
    try:
        validation_results = []
        
        # فحص توازن القيود
        unbalanced_batches = db.session.query(GLBatch).filter(
            GLBatch.status == 'POSTED'
        ).all()
        
        unbalanced_count = 0
        for batch in unbalanced_batches:
            total_debit = sum(entry.debit for entry in batch.entries)
            total_credit = sum(entry.credit for entry in batch.entries)
            if abs(total_debit - total_credit) > 0.01:
                unbalanced_count += 1
        
        validation_results.append({
            'check': 'توازن القيود المحاسبية',
            'status': 'PASS' if unbalanced_count == 0 else 'FAIL',
            'details': f'عدد القيود غير المتوازنة: {unbalanced_count}',
            'count': unbalanced_count
        })
        
        # فحص الحسابات النشطة
        inactive_accounts = Account.query.filter_by(is_active=False).count()
        validation_results.append({
            'check': 'الحسابات النشطة',
            'status': 'PASS' if inactive_accounts == 0 else 'WARNING',
            'details': f'عدد الحسابات غير النشطة: {inactive_accounts}',
            'count': inactive_accounts
        })
        
        # فحص المدفوعات المعلقة
        pending_payments = Payment.query.filter_by(status='PENDING').count()
        validation_results.append({
            'check': 'المدفوعات المعلقة',
            'status': 'INFO',
            'details': f'عدد المدفوعات المعلقة: {pending_payments}',
            'count': pending_payments
        })
        
        # فحص الشيكات المعلقة
        from models import Check
        pending_checks = Check.query.filter_by(status='PENDING').count()
        validation_results.append({
            'check': 'الشيكات المعلقة',
            'status': 'INFO',
            'details': f'عدد الشيكات المعلقة: {pending_checks}',
            'count': pending_checks
        })
        
        return jsonify({
            'success': True,
            'report_type': 'validation',
            'validation_results': validation_results,
            'overall_status': 'HEALTHY' if all(r['status'] in ['PASS', 'INFO'] for r in validation_results) else 'NEEDS_ATTENTION'
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تقرير التحقق: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


# ========== تبويبات جديدة ==========

@financial_reports_bp.route('/trial-balance')
@permission_required(SystemPermissions.VIEW_REPORTS)
def trial_balance():
    try:
        as_of_date = request.args.get('date')
        if not as_of_date:
            as_of_date = date.today()
        else:
            as_of_date = datetime.fromisoformat(as_of_date).date()
        
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())
        
        accounts_balance = db.session.query(
            GLEntry.account,
            Account.name,
            Account.type,
            func.sum(GLEntry.debit).label('total_debit'),
            func.sum(GLEntry.credit).label('total_credit')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at <= as_of_dt
        ).group_by(GLEntry.account, Account.name, Account.type).all()
        
        trial_balance_data = []
        total_debits = 0
        total_credits = 0
        
        account_descriptions = {
            'ASSET': 'ما تملكه الشركة من موارد',
            'LIABILITY': 'ما على الشركة من التزامات',
            'EQUITY': 'حقوق المالك في الشركة',
            'REVENUE': 'الدخل من العمليات',
            'EXPENSE': 'التكاليف والمصروفات'
        }
        
        for acc in accounts_balance:
            debit = float(acc.total_debit or 0)
            credit = float(acc.total_credit or 0)
            
            acc_type = acc.type or 'ASSET'
            if acc_type in ['ASSET', 'EXPENSE']:
                net = debit - credit
                normal_side = 'DR'
            else:
                net = credit - debit
                normal_side = 'CR'
            
            row = {
                'account': acc.account,
                'name': acc.name,
                'type': acc_type,
                'description': account_descriptions.get(acc_type, ''),
                'debit': debit,
                'credit': credit,
                'net': net,
                'side': 'DR' if net > 0 else 'CR',
                'normal_side': normal_side,
                'is_normal': (net > 0 and normal_side == 'DR') or (net < 0 and normal_side == 'CR')
            }
            trial_balance_data.append(row)
            total_debits += debit
            total_credits += credit
        
        trial_balance_data.sort(key=lambda r: (
            {'ASSET': 1, 'LIABILITY': 2, 'EQUITY': 3, 'REVENUE': 4, 'EXPENSE': 5}.get(r['type'], 6),
            r['account']
        ))
        
        grouped_trial_balance = {}
        for row in trial_balance_data:
            t = row['type'] or 'OTHER'
            if t not in grouped_trial_balance:
                grouped_trial_balance[t] = {
                    'rows': [],
                    'total_debit': 0.0,
                    'total_credit': 0.0,
                    'total_net': 0.0,
                }
            g = grouped_trial_balance[t]
            g['rows'].append(row)
            g['total_debit'] += row['debit']
            g['total_credit'] += row['credit']
            g['total_net'] += row['net']
        
        is_balanced = abs(total_debits - total_credits) < 0.01
        
        ar_gl_balance = 0.0
        ar_model_balance = 0.0
        ap_gl_balance = 0.0
        ap_model_balance = 0.0
        
        for row in trial_balance_data:
            if row['account'] == '1100_AR':
                ar_gl_net = row['debit'] - row['credit']
                ar_gl_balance = ar_gl_net
            elif row['account'] == '2000_AP':
                ap_gl_net = row['credit'] - row['debit']
                ap_gl_balance = ap_gl_net
        
        customers_total = db.session.query(
            func.coalesce(func.sum(Customer.current_balance), 0)
        ).scalar() or 0
        # الرصيد في المودل موجب يعني أن العميل مدين لنا (أصل)
        # ولكن في قاعدة البيانات (customers table) الرصيد الموجب يعني أن العميل له رصيد عندنا (التزام)
        # والسالب يعني أن العميل عليه رصيد لنا (أصل)
        # بينما في GL (1100_AR) الرصيد المدين (الأصل) موجب
        # لذلك يجب عكس إشارة رصيد المودل ليتطابق مع GL
        ar_model_balance = -float(customers_total)
        
        suppliers_total = db.session.query(
            func.coalesce(func.sum(Supplier.current_balance), 0)
        ).scalar() or 0
        
        partners_total = db.session.query(
            func.coalesce(func.sum(Partner.current_balance), 0)
        ).scalar() or 0
        
        ap_model_balance = float(suppliers_total) + float(partners_total)
        
        # حساب التسويات اليدوية (Manual Adjustments) لحسابات الذمم
        # هذا ضروري لأن القيود اليدوية لا تحدث أرصدة العملاء/الموردين في المودل
        manual_ar_adjustments = db.session.query(
            func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.source_type == 'MANUAL',
            GLEntry.account == '1100_AR',
            GLBatch.posted_at <= as_of_dt
        ).scalar() or 0

        manual_ap_adjustments = db.session.query(
            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.source_type == 'MANUAL',
            GLEntry.account == '2000_AP',
            GLBatch.posted_at <= as_of_dt
        ).scalar() or 0
        
        reconciliation = {
            'ar': {
                'gl_balance': ar_gl_balance,
                'model_balance': ar_model_balance,
                'manual_adjustments': float(manual_ar_adjustments),
                'difference': abs(ar_gl_balance - ar_model_balance),
                'explained_difference': abs(ar_gl_balance - (ar_model_balance + float(manual_ar_adjustments))),
                'is_matched': abs(ar_gl_balance - ar_model_balance) < 0.01,
                'is_fully_explained': abs(ar_gl_balance - (ar_model_balance + float(manual_ar_adjustments))) < 0.01
            },
            'ap': {
                'gl_balance': ap_gl_balance,
                'model_balance': ap_model_balance,
                'manual_adjustments': float(manual_ap_adjustments),
                'difference': abs(ap_gl_balance - ap_model_balance),
                'explained_difference': abs(ap_gl_balance - (ap_model_balance + float(manual_ap_adjustments))),
                'is_matched': abs(ap_gl_balance - ap_model_balance) < 0.01,
                'is_fully_explained': abs(ap_gl_balance - (ap_model_balance + float(manual_ap_adjustments))) < 0.01
            }
        }
        
        data = {
            'as_of_date': as_of_date,
            'trial_balance_data': trial_balance_data,
            'grouped_trial_balance': grouped_trial_balance,
            'total_debits': total_debits,
            'total_credits': total_credits,
            'is_balanced': is_balanced,
            'reconciliation': reconciliation
        }
        
        # إذا طلب JSON
        if request.args.get('format') == 'json' or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'report_type': 'trial_balance',
                'as_of_date': as_of_date.isoformat(),
                'rows': trial_balance_data,
                'totals': {
                    'debit': total_debits,
                    'credit': total_credits,
                    'is_balanced': is_balanced
                },
                'reconciliation': reconciliation
            })
        
        return render_template('reports/financial/trial_balance.html', **data)
        
    except Exception as e:
        current_app.logger.error(f"خطأ في ميزان المراجعة: {str(e)}")
        if request.args.get('format') == 'json':
            current_app.logger.exception('API error')
            return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
        return render_template('errors/500.html', error="تعذر تنفيذ العملية. حاول مرة أخرى."), 500


@financial_reports_bp.route('/aging-report')
@permission_required(SystemPermissions.VIEW_REPORTS)
def aging_report():
    try:
        report_type = request.args.get('type', 'ar')
        as_of_date = request.args.get('as_of_date')
        if as_of_date:
            today = datetime.fromisoformat(as_of_date).date()
        else:
            today = date.today()
        
        aging_data = []
        
        if report_type == 'ar':
            customers = Customer.query.all()
            for customer in customers:
                db.session.refresh(customer)
                balance = float(customer.current_balance or 0)
                if balance < -0.01:
                    oldest_date = None
                    
                    oldest_sale = db.session.query(Sale).filter(
                        Sale.customer_id == customer.id,
                        Sale.status == 'CONFIRMED'
                    ).order_by(Sale.sale_date.asc()).first()
                    if oldest_sale and oldest_sale.sale_date:
                        sale_dt = oldest_sale.sale_date
                        if isinstance(sale_dt, datetime):
                            sale_dt = sale_dt.date()
                        if oldest_date is None or sale_dt < oldest_date:
                            oldest_date = sale_dt
                    
                    oldest_invoice = db.session.query(Invoice).filter(
                        Invoice.customer_id == customer.id,
                        Invoice.cancelled_at.is_(None)
                    ).order_by(Invoice.invoice_date.asc()).first()
                    if oldest_invoice and oldest_invoice.invoice_date:
                        inv_dt = oldest_invoice.invoice_date
                        if isinstance(inv_dt, datetime):
                            inv_dt = inv_dt.date()
                        if oldest_date is None or inv_dt < oldest_date:
                            oldest_date = inv_dt
                    
                    oldest_service = db.session.query(ServiceRequest).filter(
                        ServiceRequest.customer_id == customer.id
                    ).order_by(ServiceRequest.received_at.asc()).first()
                    if oldest_service and oldest_service.received_at:
                        svc_dt = oldest_service.received_at
                        if isinstance(svc_dt, datetime):
                            svc_dt = svc_dt.date()
                        if oldest_date is None or svc_dt < oldest_date:
                            oldest_date = svc_dt
                    
                    age_days = 0
                    if oldest_date:
                        age_days = max((today - oldest_date).days, 0)
                    
                    if age_days <= 30:
                        category = '0-30'
                    elif age_days <= 60:
                        category = '31-60'
                    elif age_days <= 90:
                        category = '61-90'
                    else:
                        category = '>90'
                    
                    aging_data.append({
                        'id': customer.id,
                        'name': customer.name or '',
                        'balance': abs(balance),
                        'balance_display': f"{abs(balance):,.2f}",
                        'age_days': age_days,
                        'oldest_date': oldest_date.isoformat() if oldest_date else None,
                        'category': category,
                        'phone': customer.phone or '',
                        'currency': customer.currency or 'ILS'
                    })
        else:
            suppliers = Supplier.query.all()
            for supplier in suppliers:
                db.session.refresh(supplier)
                balance = float(supplier.current_balance or 0)
                if balance > 0.01:
                    oldest_date = None
                    
                    oldest_invoice = db.session.query(Invoice).filter(
                        Invoice.supplier_id == supplier.id,
                        Invoice.cancelled_at.is_(None)
                    ).order_by(Invoice.invoice_date.asc()).first()
                    if oldest_invoice and oldest_invoice.invoice_date:
                        inv_dt = oldest_invoice.invoice_date
                        if isinstance(inv_dt, datetime):
                            inv_dt = inv_dt.date()
                        if oldest_date is None or inv_dt < oldest_date:
                            oldest_date = inv_dt
                    
                    age_days = 0
                    if oldest_date:
                        age_days = max((today - oldest_date).days, 0)
                    
                    if age_days <= 30:
                        category = '0-30'
                    elif age_days <= 60:
                        category = '31-60'
                    elif age_days <= 90:
                        category = '61-90'
                    else:
                        category = '>90'
                    
                    aging_data.append({
                        'id': supplier.id,
                        'name': supplier.name or '',
                        'balance': balance,
                        'balance_display': f"{balance:,.2f}",
                        'age_days': age_days,
                        'oldest_date': oldest_date.isoformat() if oldest_date else None,
                        'category': category,
                        'phone': supplier.phone or '',
                        'currency': supplier.currency or 'ILS',
                        'type': 'supplier'
                    })
            
            include_partners = request.args.get('include_partners', 'false').lower() == 'true'
            if include_partners or report_type == 'partners':
                partners = Partner.query.all()
                for partner in partners:
                    db.session.refresh(partner)
                    balance = float(partner.current_balance or 0)
                    if balance > 0.01:
                        oldest_date = None
                        
                        oldest_invoice = db.session.query(Invoice).filter(
                            Invoice.partner_id == partner.id,
                            Invoice.cancelled_at.is_(None)
                        ).order_by(Invoice.invoice_date.asc()).first()
                        if oldest_invoice and oldest_invoice.invoice_date:
                            inv_dt = oldest_invoice.invoice_date
                            if isinstance(inv_dt, datetime):
                                inv_dt = inv_dt.date()
                            if oldest_date is None or inv_dt < oldest_date:
                                oldest_date = inv_dt
                        
                        oldest_payment = db.session.query(Payment).filter(
                            Payment.partner_id == partner.id,
                            Payment.direction == 'OUT',
                            Payment.status == 'COMPLETED'
                        ).order_by(Payment.payment_date.asc()).first()
                        if oldest_payment and oldest_payment.payment_date:
                            pay_dt = oldest_payment.payment_date
                            if isinstance(pay_dt, datetime):
                                pay_dt = pay_dt.date()
                            if oldest_date is None or pay_dt < oldest_date:
                                oldest_date = pay_dt
                        
                        age_days = 0
                        if oldest_date:
                            age_days = max((today - oldest_date).days, 0)
                        
                        if age_days <= 30:
                            category = '0-30'
                        elif age_days <= 60:
                            category = '31-60'
                        elif age_days <= 90:
                            category = '61-90'
                        else:
                            category = '>90'
                        
                        aging_data.append({
                            'id': partner.id,
                            'name': partner.name or '',
                            'balance': balance,
                            'balance_display': f"{balance:,.2f}",
                            'age_days': age_days,
                            'oldest_date': oldest_date.isoformat() if oldest_date else None,
                            'category': category,
                            'phone': partner.phone_number or '',
                            'currency': partner.currency or 'ILS',
                            'type': 'partner',
                            'share_percentage': float(partner.share_percentage or 0)
                        })
        
        aging_summary = {
            '0-30': sum(item['balance'] for item in aging_data if item['category'] == '0-30'),
            '31-60': sum(item['balance'] for item in aging_data if item['category'] == '31-60'),
            '61-90': sum(item['balance'] for item in aging_data if item['category'] == '61-90'),
            '>90': sum(item['balance'] for item in aging_data if item['category'] == '>90')
        }
        
        total = sum(aging_summary.values())
        
        return jsonify({
            'success': True,
            'report_type': 'aging_report',
            'aging_type': report_type,
            'as_of_date': today.isoformat(),
            'summary': {k: float(v) for k, v in aging_summary.items()},
            'total': float(total),
            'details': aging_data,
            'count': len(aging_data)
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تقرير الذمم المعمرة: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@financial_reports_bp.route('/profit-trends')
@permission_required(SystemPermissions.VIEW_REPORTS)
def profit_trends():
    """📈 اتجاهات الربحية - مقارنة شهرية"""
    try:
        months = int(request.args.get('months', 6))  # آخر 6 أشهر افتراضياً
        today = date.today()
        
        monthly_data = []
        for i in range(months):
            # حساب بداية ونهاية الشهر
            target_date = today - timedelta(days=30 * i)
            month_start = target_date.replace(day=1)
            if target_date.month == 12:
                month_end = date(target_date.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(target_date.year, target_date.month + 1, 1) - timedelta(days=1)
            
            month_start_dt = datetime.combine(month_start, datetime.min.time())
            month_end_dt = datetime.combine(month_end, datetime.max.time())

            # حساب الإيرادات
            revenue = db.session.query(
                func.sum(GLEntry.credit)
            ).join(GLBatch).filter(
                GLBatch.status == 'POSTED',
                GLBatch.posted_at >= month_start_dt,
                GLBatch.posted_at <= month_end_dt,
                GLEntry.account.like('4%')
            ).scalar() or 0
            
            # حساب المصروفات
            expenses = db.session.query(
                func.sum(GLEntry.debit)
            ).join(GLBatch).filter(
                GLBatch.status == 'POSTED',
                GLBatch.posted_at >= month_start_dt,
                GLBatch.posted_at <= month_end_dt,
                GLEntry.account.like('5%')
            ).scalar() or 0
            
            profit = float(revenue) - float(expenses)
            
            monthly_data.append({
                'month': month_start.strftime('%Y-%m'),
                'month_name': month_start.strftime('%B %Y'),
                'revenue': float(revenue),
                'expenses': float(expenses),
                'profit': profit,
                'margin': (profit / float(revenue) * 100) if float(revenue) > 0 else 0
            })
        
        return jsonify({
            'success': True,
            'report_type': 'profit_trends',
            'months': months,
            'data': list(reversed(monthly_data))  # من الأقدم للأحدث
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في اتجاهات الربحية: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@financial_reports_bp.route('/expense-breakdown')
@permission_required(SystemPermissions.VIEW_REPORTS)
def expense_breakdown():
    """📊 تحليل المصروفات حسب النوع"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
        else:
            start_date = datetime.fromisoformat(start_date).date()
            end_date = datetime.fromisoformat(end_date).date()

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        
        # تحليل المصروفات حسب الحساب
        expense_breakdown = db.session.query(
            GLEntry.account,
            Account.name,
            func.sum(GLEntry.debit).label('amount')
        ).join(Account, Account.code == GLEntry.account).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account.like('5%')
        ).group_by(GLEntry.account, Account.name).order_by(func.sum(GLEntry.debit).desc()).all()
        
        total_expenses = sum(float(exp.amount) for exp in expense_breakdown)
        
        breakdown_data = [{
            'account': exp.account,
            'name': exp.name or '',
            'amount': float(exp.amount),
            'percentage': (float(exp.amount) / total_expenses * 100) if total_expenses > 0 else 0
        } for exp in expense_breakdown]
        
        return jsonify({
            'success': True,
            'report_type': 'expense_breakdown',
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'total_expenses': total_expenses,
            'breakdown': breakdown_data
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تحليل المصروفات: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@financial_reports_bp.route('/receivables-payables')
@permission_required(SystemPermissions.VIEW_REPORTS)
def receivables_payables():
    try:
        report_type = request.args.get('type', 'receivables')
        include_partners = request.args.get('include_partners', 'false').lower() == 'true'
        as_of_date = request.args.get('as_of_date')
        if as_of_date:
            as_of_date = datetime.fromisoformat(as_of_date).date()
        else:
            as_of_date = date.today()
        
        data = []
        total_balance = 0.0
        
        as_of_dt = datetime.combine(as_of_date, datetime.max.time())
        
        if report_type == 'receivables':
            customers = Customer.query.all()
            for customer in customers:
                db.session.refresh(customer)
                balance = float(customer.current_balance or 0)
                if abs(balance) > 0.01:
                    gl_balance = db.session.query(
                        func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0)
                    ).join(GLBatch).join(Account).filter(
                        GLBatch.status == 'POSTED',
                        GLBatch.posted_at <= as_of_dt,
                        GLBatch.entity_type == 'CUSTOMER',
                        GLBatch.entity_id == customer.id,
                        Account.code == '1100_AR'
                    ).scalar() or 0
                    
                    balance_view = classify_entity_balance(balance)
                    
                    data.append({
                        'id': customer.id,
                        'name': customer.name,
                        'phone': customer.phone or '',
                        'currency': customer.currency or 'ILS',
                        'balance': balance_view['balance'],
                        'gl_balance': float(gl_balance),
                        'balance_display': f"{balance_view['abs_balance']:,.2f}",
                        'owed_to_us': balance_view['owed_to_us'],
                        'owed_by_us': balance_view['owed_by_us'],
                        'status': balance_view['status'],
                        'status_ar': balance_view['status_ar'],
                        'type': 'customer'
                    })
                    total_balance += balance
        else:
            suppliers = Supplier.query.all()
            for supplier in suppliers:
                db.session.refresh(supplier)
                balance = float(supplier.current_balance or 0)
                if abs(balance) > 0.01:
                    gl_balance = db.session.query(
                        func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0)
                    ).join(GLBatch).join(Account).filter(
                        GLBatch.status == 'POSTED',
                        GLBatch.posted_at <= as_of_dt,
                        GLBatch.entity_type == 'SUPPLIER',
                        GLBatch.entity_id == supplier.id,
                        Account.code == '2000_AP'
                    ).scalar() or 0
                    
                    balance_view = classify_entity_balance(balance)
                    
                    data.append({
                        'id': supplier.id,
                        'name': supplier.name,
                        'phone': supplier.phone or '',
                        'currency': supplier.currency or 'ILS',
                        'balance': balance_view['balance'],
                        'gl_balance': float(gl_balance),
                        'balance_display': f"{balance_view['abs_balance']:,.2f}",
                        'owed_to_us': balance_view['owed_to_us'],
                        'owed_by_us': balance_view['owed_by_us'],
                        'status': balance_view['status'],
                        'status_ar': balance_view['status_ar'],
                        'type': 'supplier'
                    })
                    total_balance += balance
            
            if include_partners or report_type == 'partners':
                partners = Partner.query.all()
                for partner in partners:
                    db.session.refresh(partner)
                    balance = float(partner.current_balance or 0)
                    if abs(balance) > 0.01:
                        gl_balance = db.session.query(
                            func.coalesce(func.sum(GLEntry.credit - GLEntry.debit), 0)
                        ).join(GLBatch).join(Account).filter(
                            GLBatch.status == 'POSTED',
                            GLBatch.posted_at <= as_of_dt,
                            GLBatch.entity_type == 'PARTNER',
                            GLBatch.entity_id == partner.id,
                            Account.code == '2000_AP'
                        ).scalar() or 0
                        ar_balance = 0
                        if partner.customer_id:
                            ar_balance = db.session.query(
                                func.coalesce(func.sum(GLEntry.debit - GLEntry.credit), 0)
                            ).join(GLBatch).join(Account).filter(
                                GLBatch.status == 'POSTED',
                                GLBatch.posted_at <= as_of_dt,
                                GLBatch.entity_type == 'CUSTOMER',
                                GLBatch.entity_id == partner.customer_id,
                                Account.code == '1100_AR'
                            ).scalar() or 0
                        gl_balance = float(gl_balance) - float(ar_balance)
                        
                        balance_view = classify_entity_balance(balance)
                        
                        data.append({
                            'id': partner.id,
                            'name': partner.name,
                            'phone': partner.phone_number or '',
                            'currency': partner.currency or 'ILS',
                            'balance': balance_view['balance'],
                            'gl_balance': float(gl_balance),
                            'balance_display': f"{balance_view['abs_balance']:,.2f}",
                            'owed_to_us': balance_view['owed_to_us'],
                            'owed_by_us': balance_view['owed_by_us'],
                            'status': balance_view['status'],
                            'status_ar': balance_view['status_ar'],
                            'type': 'partner',
                            'share_percentage': float(partner.share_percentage or 0)
                        })
                        total_balance += balance
        
        data.sort(key=lambda x: abs(x['balance']), reverse=True)
        
        return jsonify({
            'success': True,
            'report_type': 'receivables_payables',
            'detail_type': report_type,
            'as_of_date': as_of_date.isoformat(),
            'total_balance': float(total_balance),
            'count': len(data),
            'details': data
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تقرير الذمم: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@financial_reports_bp.route('/revenue-by-source')
@permission_required(SystemPermissions.VIEW_REPORTS)
def revenue_by_source():
    """📊 تحليل مصادر الإيرادات"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
        else:
            start_date = datetime.fromisoformat(start_date).date()
            end_date = datetime.fromisoformat(end_date).date()

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        
        # إيرادات المبيعات
        sales_revenue = db.session.query(
            func.sum(GLEntry.credit)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account == '4000_SALES'
        ).scalar() or 0
        
        # إيرادات الخدمات
        service_revenue = db.session.query(
            func.sum(GLEntry.credit)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account == '4100_SERVICE_REVENUE'
        ).scalar() or 0
        
        # إيرادات أخرى
        other_revenue = db.session.query(
            func.sum(GLEntry.credit)
        ).join(GLBatch).filter(
            GLBatch.status == 'POSTED',
            GLBatch.posted_at >= start_dt,
            GLBatch.posted_at <= end_dt,
            GLEntry.account.like('4%'),
            GLEntry.account.notin_(['4000_SALES', '4100_SERVICE_REVENUE'])
        ).scalar() or 0
        
        total_revenue = float(sales_revenue) + float(service_revenue) + float(other_revenue)
        
        return jsonify({
            'success': True,
            'report_type': 'revenue_by_source',
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'total_revenue': total_revenue,
            'breakdown': {
                'sales': {
                    'amount': float(sales_revenue),
                    'percentage': (float(sales_revenue) / total_revenue * 100) if total_revenue > 0 else 0
                },
                'services': {
                    'amount': float(service_revenue),
                    'percentage': (float(service_revenue) / total_revenue * 100) if total_revenue > 0 else 0
                },
                'other': {
                    'amount': float(other_revenue),
                    'percentage': (float(other_revenue) / total_revenue * 100) if total_revenue > 0 else 0
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في تحليل مصادر الإيرادات: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
