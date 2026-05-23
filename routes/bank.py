from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from extensions import db
from models import (BankAccount, BankStatement, BankTransaction, BankReconciliation, 
                   Account, Branch, Payment, Expense, Sale, SystemSettings, _gl_upsert_batch_and_entries)
from sqlalchemy import func, and_, or_, desc, asc
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
import csv
import io
from werkzeug.utils import secure_filename
from utils import permission_required

bank_bp = Blueprint('bank', __name__, url_prefix='/bank')

@bank_bp.before_request
@login_required
def restrict_bank_access():
    # الحماية: فقط للمالك والمطور (Level 0)
    from permissions_config.role_policy import is_platform_owner_role

    if not is_platform_owner_role(current_user):
        utils.flash_error('غير مصرح لك بالوصول لإدارة البنوك (تتطلب صلاحيات المالك)', 'danger')
        return redirect(url_for('main.dashboard'))


@bank_bp.route('/accounts')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def accounts():
    bank_accounts = BankAccount.query.order_by(BankAccount.code).all()
    
    accounts_data = []
    for account in bank_accounts:
        unreconciled = account.get_unreconciled_balance()
        last_statement = BankStatement.query.filter_by(
            bank_account_id=account.id
        ).order_by(BankStatement.statement_date.desc()).first()
        
        total_deposits = db.session.query(func.sum(BankTransaction.debit)).filter_by(
            bank_account_id=account.id
        ).scalar() or 0
        
        total_withdrawals = db.session.query(func.sum(BankTransaction.credit)).filter_by(
            bank_account_id=account.id
        ).scalar() or 0
        
        accounts_data.append({
            'account': account,
            'unreconciled': unreconciled,
            'last_statement_date': last_statement.statement_date if last_statement else None,
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'net_balance': float(account.current_balance)
        })
    
    return render_template('bank/accounts.html', accounts=accounts_data)


@bank_bp.route('/accounts/add', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def add_account():
    if request.method == 'POST':
        try:
            code = request.form.get('code')
            name = request.form.get('name')
            bank_name = request.form.get('bank_name')
            account_number = request.form.get('account_number')
            iban = request.form.get('iban', '')
            swift_code = request.form.get('swift_code', '')
            currency = request.form.get('currency', 'ILS')
            branch_id = request.form.get('branch_id', type=int)
            gl_account_code = request.form.get('gl_account_code')
            try:
                opening_balance = Decimal(request.form.get('opening_balance') or 0)
            except Exception:
                opening_balance = Decimal(0)
            notes = request.form.get('notes', '')
            
            if BankAccount.query.filter_by(code=code).first():
                flash(f'رمز الحساب {code} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            if BankAccount.query.filter_by(account_number=account_number).first():
                flash(f'رقم الحساب {account_number} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            bank_account = BankAccount(
                code=code,
                name=name,
                bank_name=bank_name,
                account_number=account_number,
                iban=iban,
                swift_code=swift_code,
                currency=currency,
                branch_id=branch_id,
                gl_account_code=gl_account_code,
                opening_balance=opening_balance,
                current_balance=opening_balance,
                notes=notes,
                is_active=True,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(bank_account)
            db.session.flush()
            
            if opening_balance != 0:
                amount = float(abs(opening_balance))
                if opening_balance > 0:
                    entries = [
                        (gl_account_code, amount, 0),
                        ("3000_EQUITY", 0, amount),
                    ]
                else:
                    entries = [
                        (gl_account_code, 0, amount),
                        ("3000_EQUITY", amount, 0),
                    ]
                _gl_upsert_batch_and_entries(
                    db.session.connection(),
                    source_type="BANK_ACCOUNT",
                    source_id=bank_account.id,
                    purpose="OPENING_BALANCE",
                    currency=currency or "ILS",
                    memo=f"رصيد افتتاحي للحساب البنكي: {name}",
                    entries=entries,
                    ref=f"OB-BANK-{bank_account.id}",
                    entity_type="BANK_ACCOUNT",
                    entity_id=bank_account.id
                )
            
            db.session.commit()
            
            utils.flash_success(f'تم إضافة الحساب البنكي {code} - {name} بنجاح', 'success')
            return redirect(url_for('bank.accounts'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    gl_accounts = Account.query.filter_by(type='ASSET', is_active=True).filter(
        Account.code.like('101%')
    ).order_by(Account.code).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    
    return render_template('bank/account_form.html',
                         gl_accounts=gl_accounts,
                         branches=branches,
                         account=None)


@bank_bp.route('/accounts/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def edit_account(id):
    account = db.get_or_404(BankAccount, id)
    
    if request.method == 'POST':
        try:
            account.name = request.form.get('name')
            account.bank_name = request.form.get('bank_name')
            account.iban = request.form.get('iban', '')
            account.swift_code = request.form.get('swift_code', '')
            account.branch_id = request.form.get('branch_id', type=int)
            account.notes = request.form.get('notes', '')
            account.is_active = request.form.get('is_active') == 'on'
            account.updated_by = current_user.id
            account.updated_at = datetime.now()
            
            db.session.commit()
            
            utils.flash_success(f'تم تحديث الحساب البنكي بنجاح', 'success')
            return redirect(url_for('bank.view_account', id=id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    gl_accounts = Account.query.filter_by(type='ASSET', is_active=True).filter(
        Account.code.like('101%')
    ).order_by(Account.code).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    
    return render_template('bank/account_form.html',
                         gl_accounts=gl_accounts,
                         branches=branches,
                         account=account)


@bank_bp.route('/accounts/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def view_account(id):
    account = db.get_or_404(BankAccount, id)
    
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    transactions = BankTransaction.query.filter_by(bank_account_id=id).order_by(
        BankTransaction.transaction_date.desc(),
        BankTransaction.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    reconciliations = BankReconciliation.query.filter_by(bank_account_id=id).order_by(
        BankReconciliation.period_end.desc()
    ).limit(10).all()
    
    unmatched_count = BankTransaction.query.filter_by(bank_account_id=id, matched=False).count()
    
    total_debit = db.session.query(func.sum(BankTransaction.debit)).filter_by(
        bank_account_id=id
    ).scalar() or 0
    
    total_credit = db.session.query(func.sum(BankTransaction.credit)).filter_by(
        bank_account_id=id
    ).scalar() or 0
    
    stats = {
        'total_transactions': BankTransaction.query.filter_by(bank_account_id=id).count(),
        'matched': BankTransaction.query.filter_by(bank_account_id=id, matched=True).count(),
        'unmatched': unmatched_count,
        'total_deposits': float(total_debit),
        'total_withdrawals': float(total_credit),
        'net_movement': float(total_debit - total_credit),
        'total_reconciliations': len(reconciliations),
        'unreconciled_balance': account.get_unreconciled_balance(),
        'current_balance': float(account.current_balance)
    }
    
    return render_template('bank/account_view.html',
                         account=account,
                         transactions=transactions,
                         reconciliations=reconciliations,
                         stats=stats)


@bank_bp.route('/statements')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def statements():
    bank_account_id = request.args.get('account', type=int)
    
    query = BankStatement.query
    if bank_account_id:
        query = query.filter_by(bank_account_id=bank_account_id)
    
    statements = query.order_by(BankStatement.statement_date.desc()).all()
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/statements.html',
                         statements=statements,
                         bank_accounts=bank_accounts,
                         selected_account=bank_account_id)


@bank_bp.route('/statements/upload', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def upload_statement():
    if request.method == 'POST':
        try:
            bank_account_id = int(request.form.get('bank_account_id'))
            
            statement_date_raw = request.form.get('statement_date')
            if not statement_date_raw:
                flash('الرجاء إدخال تاريخ الكشف', 'danger')
                return redirect(request.url)
            
            statement_date = datetime.strptime(statement_date_raw, '%Y-%m-%d').date()
            statement_number = (request.form.get('statement_number') or '').strip() or f"STMT-{statement_date.strftime('%Y%m%d')}"
            
            period_start_raw = request.form.get('period_start') or statement_date_raw
            period_end_raw = request.form.get('period_end') or statement_date_raw
            
            try:
                period_start = datetime.strptime(period_start_raw, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                period_start = None
            try:
                period_end = datetime.strptime(period_end_raw, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                period_end = None
            
            if period_end < period_start:
                flash('تاريخ نهاية الفترة يجب أن يكون بعد أو مساوي لتاريخ البداية', 'danger')
                return redirect(request.url)
            
            def _to_decimal(value):
                try:
                    return Decimal(str(value or 0))
                except Exception:
                    return Decimal('0')
            
            opening_balance = _to_decimal(request.form.get('opening_balance'))
            closing_balance = _to_decimal(request.form.get('closing_balance'))
            
            bank_account = db.get_or_404(BankAccount, bank_account_id)
            
            if BankStatement.query.filter_by(
                bank_account_id=bank_account_id,
                statement_number=statement_number
            ).first():
                flash(f'كشف بنفس الرقم {statement_number} موجود مسبقاً', 'danger')
                return redirect(request.url)
            
            file = request.files.get('statement_file') or request.files.get('csv_file')
            if not file or not file.filename:
                flash('الرجاء اختيار ملف كشف بصيغة CSV', 'danger')
                return redirect(request.url)
            
            filename = secure_filename(file.filename)
            if not filename.lower().endswith('.csv'):
                flash('صيغة الملف يجب أن تكون CSV', 'danger')
                return redirect(request.url)
            
            content = file.read().decode('utf-8-sig')
            if content:
                csv_reader = csv.DictReader(io.StringIO(content))
                
                transactions_buffer = []
                transaction_count = 0
                total_debit_amount = Decimal('0')
                total_credit_amount = Decimal('0')
                
                for idx, row in enumerate(csv_reader, start=1):
                    if not row:
                        continue
                    
                    normalized = {}
                    for key, value in (row or {}).items():
                        if key is None:
                            continue
                        clean_key = key.strip().lower()
                        normalized[clean_key] = value.strip() if isinstance(value, str) else value
                    
                    raw_date = normalized.get('date')
                    if not raw_date:
                        flash(f'صف {idx}: التاريخ مفقود، تم تجاهل السطر', 'warning')
                        continue
                    
                    try:
                        trans_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
                    except Exception:
                        flash(f'صف {idx}: تنسيق التاريخ غير صالح ({raw_date})، تم تجاهل السطر', 'warning')
                        continue
                    
                    description = normalized.get('description', '')
                    
                    def _to_decimal(val):
                        try:
                            return Decimal(str(val or 0))
                        except Exception:
                            return Decimal('0')
                    
                    debit = _to_decimal(normalized.get('debit'))
                    credit = _to_decimal(normalized.get('credit'))
                    reference = normalized.get('reference', '')
                    
                    total_debit_amount += debit
                    total_credit_amount += credit
                    
                    transactions_buffer.append({
                        'transaction_date': trans_date,
                        'description': description,
                        'reference': reference,
                        'debit': debit,
                        'credit': credit
                    })
                    
                    transaction_count += 1
                
                utils.flash_success(f'تم رفع {transaction_count} معاملة من الكشف', 'info')
            else:
                flash('الملف فارغ أو غير صالح', 'danger')
                return redirect(request.url)
            
            expected_closing = opening_balance + total_debit_amount - total_credit_amount
            if round(expected_closing, 2) != round(closing_balance, 2):
                diff = float(expected_closing - closing_balance)
                utils.flash_error(f'الرصيد الختامي المدخل لا يطابق الحركة المحسوبة. الفارق: {diff:.2f} ₪', 'danger')
                return redirect(request.url)
            
            statement = BankStatement(
                bank_account_id=bank_account_id,
                statement_number=statement_number,
                statement_date=statement_date,
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                total_deposits=total_debit_amount.quantize(Decimal('0.01')),
                total_withdrawals=total_credit_amount.quantize(Decimal('0.01')),
                status='IMPORTED',
                imported_by=current_user.id,
                imported_at=datetime.now(),
                created_by=current_user.id,
                updated_by=current_user.id
            )
            
            db.session.add(statement)
            db.session.flush()
            
            for tx in transactions_buffer:
                transaction = BankTransaction(
                    bank_account_id=bank_account_id,
                    statement_id=statement.id,
                    transaction_date=tx['transaction_date'],
                    description=tx['description'],
                    reference=tx['reference'],
                    debit=tx['debit'],
                    credit=tx['credit'],
                    matched=False
                )
                db.session.add(transaction)
            
            db.session.commit()
            
            utils.flash_success(f'تم رفع كشف الحساب بنجاح', 'success')
            return redirect(url_for('bank.view_statement', id=statement.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/statement_upload.html',
                         bank_accounts=bank_accounts)


@bank_bp.route('/statements/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def view_statement(id):
    statement = db.get_or_404(BankStatement, id)
    
    transactions = BankTransaction.query.filter_by(statement_id=id).order_by(
        BankTransaction.transaction_date,
        BankTransaction.id
    ).all()
    
    matched_count = sum(1 for t in transactions if t.matched)
    total_debit = sum(float(t.debit or 0) for t in transactions)
    total_credit = sum(float(t.credit or 0) for t in transactions)
    
    stats = {
        'total_transactions': len(transactions),
        'matched': matched_count,
        'unmatched': len(transactions) - matched_count,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'net_movement': total_debit - total_credit,
        'calculated_closing': float(statement.opening_balance) + (total_debit - total_credit),
        'difference': float(statement.closing_balance) - (float(statement.opening_balance) + (total_debit - total_credit))
    }
    
    return render_template('bank/statement_view.html',
                         statement=statement,
                         transactions=transactions,
                         stats=stats)


@bank_bp.route('/reconciliation')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def reconciliations():
    bank_account_id = request.args.get('account', type=int)
    status = request.args.get('status')
    
    query = BankReconciliation.query
    if bank_account_id:
        query = query.filter_by(bank_account_id=bank_account_id)
    if status:
        query = query.filter_by(status=status)
    
    reconciliations = query.order_by(BankReconciliation.period_end.desc()).all()
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/reconciliations.html',
                         reconciliations=reconciliations,
                         bank_accounts=bank_accounts,
                         selected_status=status)


@bank_bp.route('/reconciliation/new', methods=['GET', 'POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def new_reconciliation():
    if request.method == 'POST':
        try:
            bank_account_id = request.form.get('bank_account_id', type=int)
            if not bank_account_id:
                flash('حساب البنك مطلوب', 'danger')
                return redirect(request.url)
            period_start = datetime.strptime(request.form.get('period_start'), '%Y-%m-%d').date()
            period_end = datetime.strptime(request.form.get('period_end'), '%Y-%m-%d').date()
            bank_balance_raw = (request.form.get('bank_balance') or '').strip()
            if not bank_balance_raw:
                flash('رصيد البنك مطلوب', 'danger')
                return redirect(request.url)
            try:
                bank_balance = Decimal(bank_balance_raw)
            except Exception:
                flash('قيمة رصيد البنك غير صالحة', 'danger')
                return redirect(request.url)
            
            bank_account = db.get_or_404(BankAccount, bank_account_id)
            
            book_balance = float(bank_account.current_balance)
            
            last_recon = BankReconciliation.query.order_by(BankReconciliation.id.desc()).first()
            next_num = (last_recon.id + 1) if last_recon else 1
            recon_number = f"RECON-{datetime.now().year}{next_num:05d}"
            
            reconciliation = BankReconciliation(
                bank_account_id=bank_account_id,
                reconciliation_number=recon_number,
                period_start=period_start,
                period_end=period_end,
                book_balance=book_balance,
                bank_balance=float(bank_balance),
                reconciled_by=current_user.id,
                reconciled_at=datetime.now(),
                status='DRAFT'
            )
            
            db.session.add(reconciliation)
            db.session.commit()
            
            utils.flash_success(f'تم إنشاء التسوية {recon_number}', 'success')
            return redirect(url_for('bank.view_reconciliation', id=reconciliation.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/reconciliation_form.html',
                         bank_accounts=bank_accounts,
                         reconciliation=None)


@bank_bp.route('/reconciliation/<int:id>')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def view_reconciliation(id):
    reconciliation = db.get_or_404(BankReconciliation, id)
    
    book_transactions = Payment.query.filter(
        Payment.method.in_(["bank", "cheque"]),
        Payment.payment_date.between(reconciliation.period_start, reconciliation.period_end)
    ).all()
    
    bank_transactions = BankTransaction.query.filter(
        BankTransaction.bank_account_id == reconciliation.bank_account_id,
        BankTransaction.transaction_date.between(reconciliation.period_start, reconciliation.period_end),
        BankTransaction.matched == False
    ).all()
    
    total_book_in = sum(float(p.total_amount or 0) for p in book_transactions if p.direction == 'IN')
    total_book_out = sum(float(p.total_amount or 0) for p in book_transactions if p.direction == 'OUT')
    total_bank_in = sum(float(t.credit or 0) for t in bank_transactions)
    total_bank_out = sum(float(t.debit or 0) for t in bank_transactions)
    
    stats = {
        'book_count': len(book_transactions),
        'bank_count': len(bank_transactions),
        'total_book_in': total_book_in,
        'total_book_out': total_book_out,
        'total_bank_in': total_bank_in,
        'total_bank_out': total_bank_out,
        'book_net': total_book_in - total_book_out,
        'bank_net': total_bank_in - total_bank_out,
        'difference': reconciliation.bank_balance - reconciliation.book_balance
    }
    
    return render_template('bank/reconciliation_view.html',
                         reconciliation=reconciliation,
                         book_transactions=book_transactions,
                         bank_transactions=bank_transactions,
                         stats=stats)


@bank_bp.route('/reconciliation/<int:id>/complete', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def complete_reconciliation(id):
    try:
        reconciliation = db.get_or_404(BankReconciliation, id)
        
        if reconciliation.status == 'COMPLETED':
            flash('التسوية مكتملة بالفعل', 'warning')
            return redirect(url_for('bank.view_reconciliation', id=id))
        
        matched_ids = request.form.getlist('matched_transactions[]', type=int)
        
        for trans_id in matched_ids:
            transaction = db.session.get(BankTransaction, trans_id)
            if transaction:
                transaction.matched = True
                transaction.reconciliation_id = id
        
        reconciliation.status = 'COMPLETED'
        reconciliation.completed_at = datetime.now()
        reconciliation.notes = request.form.get('notes', '')
        
        db.session.commit()
        
        utils.flash_success(f'تم إكمال التسوية {reconciliation.reconciliation_number}', 'success')
        return redirect(url_for('bank.view_reconciliation', id=id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error()
        return redirect(url_for('bank.view_reconciliation', id=id))


@bank_bp.route('/reports/unmatched')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def report_unmatched():
    bank_account_id = request.args.get('account', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = BankTransaction.query.filter_by(matched=False)
    
    if bank_account_id:
        query = query.filter_by(bank_account_id=bank_account_id)
    
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
        query = query.filter(BankTransaction.transaction_date >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
        query = query.filter(BankTransaction.transaction_date <= date_to_obj)
    
    unmatched_transactions = query.order_by(
        BankTransaction.transaction_date.desc(),
        BankTransaction.id.desc()
    ).all()
    
    total_debit = sum(float(t.debit or 0) for t in unmatched_transactions)
    total_credit = sum(float(t.credit or 0) for t in unmatched_transactions)
    
    stats = {
        'total_count': len(unmatched_transactions),
        'total_debit': total_debit,
        'total_credit': total_credit,
        'net_unmatched': total_debit - total_credit
    }
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/report_unmatched.html',
                         transactions=unmatched_transactions,
                         bank_accounts=bank_accounts,
                         stats=stats,
                         selected_account=bank_account_id,
                         date_from=date_from,
                         date_to=date_to)


@bank_bp.route('/reports/aged')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def report_aged():
    bank_account_id = request.args.get('account', type=int)
    
    query = BankTransaction.query.filter_by(matched=False)
    
    if bank_account_id:
        query = query.filter_by(bank_account_id=bank_account_id)
    
    all_unmatched = query.all()
    
    today = date.today()
    
    aged_data = {
        'current': [],
        '30_days': [],
        '60_days': [],
        '90_days': [],
        'over_90': []
    }
    
    for trans in all_unmatched:
        days_old = (today - trans.transaction_date).days
        
        if days_old <= 30:
            aged_data['current'].append(trans)
        elif days_old <= 60:
            aged_data['30_days'].append(trans)
        elif days_old <= 90:
            aged_data['60_days'].append(trans)
        elif days_old <= 120:
            aged_data['90_days'].append(trans)
        else:
            aged_data['over_90'].append(trans)
    
    totals = {
        'current': sum(float(t.debit or 0) - float(t.credit or 0) for t in aged_data['current']),
        '30_days': sum(float(t.debit or 0) - float(t.credit or 0) for t in aged_data['30_days']),
        '60_days': sum(float(t.debit or 0) - float(t.credit or 0) for t in aged_data['60_days']),
        '90_days': sum(float(t.debit or 0) - float(t.credit or 0) for t in aged_data['90_days']),
        'over_90': sum(float(t.debit or 0) - float(t.credit or 0) for t in aged_data['over_90'])
    }
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    return render_template('bank/report_aged.html',
                         aged_data=aged_data,
                         totals=totals,
                         bank_accounts=bank_accounts,
                         selected_account=bank_account_id)


@bank_bp.route('/reports/summary')
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def report_summary():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()
    
    summary_data = []
    
    for account in bank_accounts:
        query = BankTransaction.query.filter_by(bank_account_id=account.id)
        
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(BankTransaction.transaction_date >= date_from_obj)
        
        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(BankTransaction.transaction_date <= date_to_obj)
        
        transactions = query.all()
        
        total_debit = sum(float(t.debit or 0) for t in transactions)
        total_credit = sum(float(t.credit or 0) for t in transactions)
        unmatched_count = sum(1 for t in transactions if not t.matched)
        
        summary_data.append({
            'account': account,
            'transaction_count': len(transactions),
            'total_debit': total_debit,
            'total_credit': total_credit,
            'net_movement': total_debit - total_credit,
            'current_balance': float(account.current_balance),
            'unmatched_count': unmatched_count
        })
    
    grand_totals = {
        'total_debit': sum(d['total_debit'] for d in summary_data),
        'total_credit': sum(d['total_credit'] for d in summary_data),
        'total_balance': sum(d['current_balance'] for d in summary_data),
        'total_unmatched': sum(d['unmatched_count'] for d in summary_data)
    }
    
    return render_template('bank/report_summary.html',
                         summary_data=summary_data,
                         grand_totals=grand_totals,
                         date_from=date_from,
                         date_to=date_to)


@bank_bp.route('/api/auto-match/<int:bank_account_id>', methods=['POST'])
@login_required
@permission_required(SystemPermissions.MANAGE_BANK)
def auto_match(bank_account_id):
    try:
        bank_account = db.get_or_404(BankAccount, bank_account_id)
        
        unmatched_bank = BankTransaction.query.filter_by(
            bank_account_id=bank_account_id,
            matched=False
        ).all()
        
        unmatched_book = Payment.query.filter(
            Payment.payment_method.in_(['bank_transfer', 'check']),
            Payment.bank_account_id == bank_account_id
        ).all()
        
        matched_count = 0
        
        for bank_trans in unmatched_bank:
            if bank_trans.matched:
                continue
            
            for book_trans in unmatched_book:
                amount_match = False
                
                if bank_trans.debit and bank_trans.debit > 0:
                    if book_trans.payment_type == 'IN' and abs(float(bank_trans.debit) - float(book_trans.amount_received or 0)) < 0.01:
                        amount_match = True
                
                if bank_trans.credit and bank_trans.credit > 0:
                    if book_trans.payment_type == 'OUT' and abs(float(bank_trans.credit) - float(book_trans.amount_paid or 0)) < 0.01:
                        amount_match = True
                
                date_diff = abs((bank_trans.transaction_date - book_trans.payment_date).days)
                
                if amount_match and date_diff <= 3:
                    bank_trans.matched = True
                    bank_trans.matched_payment_id = book_trans.id
                    matched_count += 1
                    break
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'matched_count': matched_count,
            'message': f'تم مطابقة {matched_count} معاملة تلقائياً'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('API error')
        return jsonify({
            'success': False,
            'error': 'تعذر تنفيذ العملية. حاول مرة أخرى.'
        }), 500
