"""
📚 دليل النظام المحاسبي - Accounting System Documentation
==========================================================

📋 الوصف:
    توثيق شامل للنظام المحاسبي والمعايير المستخدمة
    
📖 المحتويات:
    ✅ دليل الحسابات المحاسبية
    ✅ معايير القيود المحاسبية
    ✅ سياسات المراجعة والفحص
    ✅ إجراءات الإصلاح والتصحيح
    
🔒 الأمان:
    - صلاحيات محددة (manage_accounting_docs)
"""

from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
import json

from models import db, Account, GLBatch, GLEntry
from utils import permission_required

# إنشاء Blueprint
accounting_docs_bp = Blueprint('accounting_docs', __name__, url_prefix='/docs/accounting')

@accounting_docs_bp.route('/')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def index():
    """دليل النظام المحاسبي الرئيسي"""
    return render_template('docs/accounting/index.html')

@accounting_docs_bp.route('/chart-of-accounts')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def chart_of_accounts():
    """دليل الحسابات المحاسبية"""
    try:
        # الحصول على جميع الحسابات
        accounts = Account.query.order_by(Account.code).all()
        
        # تصنيف الحسابات حسب النوع
        accounts_by_type = {}
        for account in accounts:
            account_type = account.type
            if account_type not in accounts_by_type:
                accounts_by_type[account_type] = []
            
            accounts_by_type[account_type].append({
                'id': account.id,
                'code': account.code,
                'name': account.name,
                'is_active': account.is_active,
                'description': getattr(account, 'description', '')
            })
        
        # إحصائيات الحسابات
        stats = {
            'total_accounts': len(accounts),
            'active_accounts': len([a for a in accounts if a.is_active]),
            'inactive_accounts': len([a for a in accounts if not a.is_active]),
            'by_type': {t: len(accs) for t, accs in accounts_by_type.items()}
        }
        
        return jsonify({
            'success': True,
            'document_type': 'chart_of_accounts',
            'stats': stats,
            'accounts_by_type': accounts_by_type,
            'account_structure': {
                '1xxx': 'الأصول (Assets)',
                '2xxx': 'الخصوم (Liabilities)', 
                '3xxx': 'حقوق الملكية (Equity)',
                '4xxx': 'الإيرادات (Revenue)',
                '5xxx': 'المصروفات (Expenses)'
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في دليل الحسابات: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@accounting_docs_bp.route('/accounting-standards')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def accounting_standards():
    """معايير القيود المحاسبية"""
    try:
        standards = {
            'double_entry_principle': {
                'title': 'مبدأ القيد المزدوج',
                'description': 'كل معاملة محاسبية يجب أن تؤثر على حسابين على الأقل، بحيث يكون إجمالي المدين = إجمالي الدائن',
                'example': 'عند بيع بمبلغ 1000 شيكل:\n- مدين: حساب الزبائن (AR) 1000\n- دائن: حساب المبيعات (Revenue) 1000'
            },
            'opening_balance_rules': {
                'title': 'قواعد الرصيد الافتتاحي',
                'customer_positive': 'رصيد موجب للزبون = له علينا → دائن AR + مدين Equity',
                'customer_negative': 'رصيد سالب للزبون = عليه لنا → مدين AR + دائن Equity',
                'supplier_positive': 'رصيد موجب للمورد = له علينا → دائن AP + مدين Equity',
                'supplier_negative': 'رصيد سالب للمورد = عليه لنا → مدين AP + دائن Equity'
            },
            'sale_accounting': {
                'title': 'محاسبة المبيعات',
                'basic_entry': 'مدين: AR (حساب الزبائن) ↔ دائن: Revenue (المبيعات)',
                'with_partners': 'المبيعات تُقسم حسب نسب الشركاء في المنتج',
                'with_exchange': 'مدين: COGS (تكلفة البضاعة) + دائن: AP (حساب الموردين)',
                'trigger': 'تُسجل عند تأكيد البيع (status = CONFIRMED)'
            },
            'payment_accounting': {
                'title': 'محاسبة المدفوعات',
                'incoming': 'مدين: Cash/Bank ↔ دائن: AR (للزبائن) أو AP (للموردين)',
                'outgoing': 'مدين: AP (للموردين) ↔ دائن: Cash/Bank',
                'trigger': 'تُسجل عند اكتمال الدفع (status = COMPLETED)'
            },
            'expense_accounting': {
                'title': 'محاسبة المصروفات',
                'entry': 'مدين: Expenses (المصروفات) ↔ دائن: Cash/Bank (حسب طريقة الدفع)',
                'trigger': 'تُسجل عند إدخال المصروف'
            },
            'check_accounting': {
                'title': 'محاسبة الشيكات',
                'pending': 'مدين: Checks Under Collection ↔ دائن: AR',
                'cashed': 'مدين: Cash/Bank ↔ دائن: Checks Under Collection',
                'bounced': 'مدين: AR ↔ دائن: Checks Under Collection'
            }
        }
        
        return jsonify({
            'success': True,
            'document_type': 'accounting_standards',
            'standards': standards
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في معايير المحاسبة: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@accounting_docs_bp.route('/audit-policies')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def audit_policies():
    """سياسات المراجعة والفحص"""
    try:
        policies = {
            'daily_checks': {
                'title': 'الفحوصات اليومية',
                'checks': [
                    'فحص توازن القيود المحاسبية',
                    'التحقق من المدفوعات المعلقة',
                    'فحص الشيكات المعلقة',
                    'مراجعة المعاملات الجديدة'
                ],
                'frequency': 'يومياً',
                'responsible': 'المحاسب الرئيسي'
            },
            'weekly_checks': {
                'title': 'الفحوصات الأسبوعية',
                'checks': [
                    'مراجعة أرصدة الزبائن والموردين',
                    'فحص اتساق الحسابات',
                    'مراجعة المعاملات غير المكتملة',
                    'فحص تكامل البيانات'
                ],
                'frequency': 'أسبوعياً',
                'responsible': 'مدير المحاسبة'
            },
            'monthly_checks': {
                'title': 'الفحوصات الشهرية',
                'checks': [
                    'إعداد التقارير المالية الشهرية',
                    'مراجعة شاملة للنظام المحاسبي',
                    'فحص الأرصدة المجمعة',
                    'مراجعة السياسات والإجراءات'
                ],
                'frequency': 'شهرياً',
                'responsible': 'المالك'
            },
            'quarterly_checks': {
                'title': 'الفحوصات الربعية',
                'checks': [
                    'مراجعة خارجية للنظام',
                    'فحص الامتثال للمعايير المحاسبية',
                    'مراجعة السياسات والتحديثات',
                    'تدريب الموظفين على التحديثات'
                ],
                'frequency': 'ربعياً',
                'responsible': 'مراجع خارجي'
            },
            'error_handling': {
                'title': 'معالجة الأخطاء',
                'procedures': [
                    'تسجيل جميع الأخطاء المكتشفة',
                    'تحليل سبب الخطأ',
                    'تطبيق الإصلاح المناسب',
                    'توثيق الإجراءات المتخذة',
                    'منع تكرار الخطأ'
                ]
            },
            'backup_policies': {
                'title': 'سياسات النسخ الاحتياطي',
                'frequency': 'يومياً',
                'retention': '30 يوم للنسخ اليومية، 12 شهر للنسخ الشهرية',
                'verification': 'فحص سلامة النسخ أسبوعياً'
            }
        }
        
        return jsonify({
            'success': True,
            'document_type': 'audit_policies',
            'policies': policies
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في سياسات المراجعة: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@accounting_docs_bp.route('/correction-procedures')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def correction_procedures():
    """إجراءات الإصلاح والتصحيح"""
    try:
        procedures = {
            'unbalanced_entries': {
                'title': 'إصلاح القيود غير المتوازنة',
                'steps': [
                    'تحديد القيود غير المتوازنة',
                    'تحليل سبب عدم التوازن',
                    'إضافة قيود التصحيح المناسبة',
                    'التحقق من التوازن مرة أخرى',
                    'توثيق الإصلاح'
                ],
                'auto_fix': 'متاح للقيود البسيطة',
                'manual_fix': 'مطلوب للقيود المعقدة'
            },
            'missing_entries': {
                'title': 'إصلاح القيود المفقودة',
                'steps': [
                    'تحديد المعاملات بدون قيود محاسبية',
                    'إنشاء القيود المحاسبية المناسبة',
                    'التحقق من صحة القيود',
                    'تأكيد القيود',
                    'توثيق الإصلاح'
                ]
            },
            'incorrect_entries': {
                'title': 'إصلاح القيود الخاطئة',
                'steps': [
                    'إلغاء القيد الخاطئ',
                    'إنشاء قيد التصحيح',
                    'إنشاء القيد الصحيح',
                    'التحقق من التوازن',
                    'توثيق الإصلاح'
                ]
            },
            'account_issues': {
                'title': 'إصلاح مشاكل الحسابات',
                'missing_accounts': 'إنشاء الحسابات المفقودة',
                'inactive_accounts': 'تفعيل الحسابات المستخدمة',
                'duplicate_accounts': 'دمج الحسابات المكررة'
            },
            'data_integrity': {
                'title': 'إصلاح مشاكل تكامل البيانات',
                'orphaned_records': 'حذف السجلات اليتيمة',
                'inconsistent_data': 'تصحيح البيانات غير المتسقة',
                'missing_relationships': 'إصلاح العلاقات المفقودة'
            }
        }
        
        return jsonify({
            'success': True,
            'document_type': 'correction_procedures',
            'procedures': procedures
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في إجراءات التصحيح: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@accounting_docs_bp.route('/gl-accounts-reference')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def gl_accounts_reference():
    """مرجع حسابات دفتر الأستاذ"""
    try:
        # الحصول على حسابات GL المستخدمة
        gl_accounts = db.session.query(GLEntry.account).distinct().all()
        used_accounts = [acc.account for acc in gl_accounts]
        
        # الحصول على تفاصيل الحسابات المستخدمة
        accounts_details = db.session.query(Account).filter(
            Account.code.in_(used_accounts)
        ).all()
        
        # تصنيف الحسابات
        accounts_by_category = {
            'assets': [],
            'liabilities': [],
            'equity': [],
            'revenue': [],
            'expenses': []
        }
        
        for account in accounts_details:
            category = account.type.lower()
            if category in accounts_by_category:
                accounts_by_category[category].append({
                    'code': account.code,
                    'name': account.name,
                    'is_active': account.is_active,
                    'usage_count': len([acc for acc in used_accounts if acc == account.code])
                })
        
        # حسابات GL الأساسية
        basic_gl_accounts = {
            'AR': '1100_AR - حساب الزبائن (Accounts Receivable)',
            'AP': '2000_AP - حساب الموردين (Accounts Payable)',
            'REV': '4000_SALES - حساب المبيعات (Revenue)',
            'CASH': '1000_CASH - النقدية (Cash)',
            'BANK': '1010_BANK - البنك (Bank)',
            'CARD': '1020_CARD_CLEARING - البطاقات (Card Clearing)',
            'VAT': '2100_VAT_PAYABLE - ضريبة القيمة المضافة (VAT Payable)',
            'EXP': '5000_EXPENSES - المصروفات (Expenses)',
            'INV_EXCHANGE': '1205_INV_EXCHANGE - مخزون التبادل (Exchange Inventory)',
            'COGS_EXCHANGE': '5105_COGS_EXCHANGE - تكلفة التبادل (Exchange COGS)'
        }
        
        return jsonify({
            'success': True,
            'document_type': 'gl_accounts_reference',
            'accounts_by_category': accounts_by_category,
            'basic_gl_accounts': basic_gl_accounts,
            'total_used_accounts': len(used_accounts)
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في مرجع حسابات GL: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

@accounting_docs_bp.route('/system-health-guide')
@permission_required(SystemPermissions.MANAGE_ACCOUNTING_DOCS)
def system_health_guide():
    """دليل صحة النظام المحاسبي"""
    try:
        health_guide = {
            'indicators': {
                'green': {
                    'description': 'النظام سليم',
                    'conditions': [
                        'جميع القيود متوازنة',
                        'لا توجد حسابات مفقودة',
                        'الأرصدة متسقة',
                        'لا توجد معاملات بدون قيود'
                    ]
                },
                'yellow': {
                    'description': 'النظام يحتاج مراجعة',
                    'conditions': [
                        'بعض القيود غير متوازنة',
                        'حسابات غير نشطة',
                        'مدفوعات معلقة',
                        'شيكات معلقة'
                    ]
                },
                'red': {
                    'description': 'النظام يحتاج إصلاح فوري',
                    'conditions': [
                        'قيود غير متوازنة كثيرة',
                        'حسابات مفقودة',
                        'أرصدة غير متسقة',
                        'معاملات بدون قيود'
                    ]
                }
            },
            'maintenance_tasks': {
                'daily': [
                    'فحص توازن القيود',
                    'مراجعة المدفوعات المعلقة',
                    'فحص الشيكات المعلقة'
                ],
                'weekly': [
                    'مراجعة أرصدة الكيانات',
                    'فحص اتساق الحسابات',
                    'مراجعة المعاملات غير المكتملة'
                ],
                'monthly': [
                    'إعداد التقارير المالية',
                    'مراجعة شاملة للنظام',
                    'فحص الأرصدة المجمعة'
                ]
            },
            'troubleshooting': {
                'unbalanced_entries': 'استخدام أداة إصلاح القيود غير المتوازنة',
                'missing_accounts': 'إنشاء الحسابات المفقودة من دليل الحسابات',
                'inconsistent_balances': 'مراجعة منطق حساب الأرصدة',
                'missing_gl_entries': 'إنشاء القيود المحاسبية للمعاملات المفقودة'
            }
        }
        
        return jsonify({
            'success': True,
            'document_type': 'system_health_guide',
            'health_guide': health_guide
        })
        
    except Exception as e:
        current_app.logger.error(f"خطأ في دليل صحة النظام: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
