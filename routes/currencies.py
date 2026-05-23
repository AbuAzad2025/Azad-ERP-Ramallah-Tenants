
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Currency, ExchangeRate, SystemSettings
import utils
from forms import ExchangeRateForm

currencies_bp = Blueprint("currencies", __name__, url_prefix="/currencies")


@currencies_bp.route("/", endpoint="list")
@login_required
def list_currencies():
    """قائمة العملات"""
    page = request.args.get("page", 1, type=int)
    per_page = 20
    
    currencies = Currency.query.filter_by(is_active=True).order_by(Currency.code).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template("currencies/list.html", currencies=currencies)


@currencies_bp.route("/new", methods=["GET", "POST"], endpoint="new_currency")
@login_required
def new_currency():
    """إضافة عملة جديدة"""
    if request.method == "POST":
        try:
            code = request.form.get("code", "").strip().upper()
            name = request.form.get("name", "").strip()
            symbol = request.form.get("symbol", "").strip()
            decimals = int(request.form.get("decimals", 2))
            
            if not code or not name:
                utils.flash_error("الرمز والاسم مطلوبان")
                return render_template("currencies/currency_form.html")
            
            # التحقق من عدم وجود العملة
            existing = Currency.query.filter_by(code=code).first()
            if existing:
                utils.flash_error(f"العملة {code} موجودة بالفعل")
                return render_template("currencies/currency_form.html")
            
            # إنشاء العملة الجديدة
            currency = Currency(
                code=code,
                name=name,
                symbol=symbol,
                decimals=decimals,
                is_active=True
            )
            
            db.session.add(currency)
            db.session.commit()
            
            flash(f"تم إضافة العملة {name} ({code}) بنجاح", "success")
            return redirect(url_for("currencies.list"))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
            return render_template("currencies/currency_form.html")
    
    return render_template("currencies/currency_form.html")


@currencies_bp.route("/exchange-rates", endpoint="exchange_rates")
@login_required
def list_exchange_rates():
    """قائمة أسعار الصرف"""
    page = request.args.get("page", 1, type=int)
    per_page = 20
    
    exchange_rates = ExchangeRate.query.order_by(
        desc(ExchangeRate.valid_from), 
        ExchangeRate.base_code, 
        ExchangeRate.quote_code
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    # إضافة أسعار السوق الحالية لكل سعر
    market_rates = {}
    for rate in exchange_rates.items:
        try:
            from models import _fetch_external_fx_rate
            from datetime import datetime
            
            # محاولة جلب السعر من السيرفرات العالمية مباشرة
            external_rate = _fetch_external_fx_rate(rate.base_code, rate.quote_code, datetime.now(timezone.utc))
            
            if external_rate and external_rate > 0:
                market_rates[rate.id] = {
                    'success': True,
                    'rate': float(external_rate),
                    'source': 'external',
                    'base': rate.base_code,
                    'quote': rate.quote_code,
                    'timestamp': datetime.now(timezone.utc)
                }
            else:
                market_rates[rate.id] = {'success': False, 'rate': 0, 'source': 'failed'}
        except Exception as e:
            market_rates[rate.id] = {'success': False, 'rate': 0, 'source': 'error', 'error': 'تعذر تنفيذ العملية. حاول مرة أخرى.'}
    
    # دالة للحصول على اسم العملة بالعربي
    def get_currency_name(code):
        currency_names = {
            'ILS': 'شيكل إسرائيلي',
            'USD': 'دولار أمريكي',
            'EUR': 'يورو',
            'JOD': 'دينار أردني',
            'AED': 'درهم إماراتي',
            'SAR': 'ريال سعودي',
            'EGP': 'جنيه مصري',
            'GBP': 'جنيه إسترليني'
        }
        return currency_names.get(code, code)
    
    return render_template("currencies/exchange_rates.html", 
                         exchange_rates=exchange_rates, 
                         market_rates=market_rates,
                         get_currency_name=get_currency_name)


@currencies_bp.route("/exchange-rates/new", methods=["GET", "POST"], endpoint="new_exchange_rate")
@login_required
def new_exchange_rate():
    """إضافة سعر صرف جديد"""
    form = ExchangeRateForm()
    
    if form.validate_on_submit():
        try:
            # إنشاء سعر الصرف الجديد
            exchange_rate = ExchangeRate(
                base_code=form.base_code.data,
                quote_code=form.quote_code.data,
                rate=form.rate.data,
                valid_from=form.valid_from.data or datetime.now(timezone.utc).date(),
                source=form.source.data or "Manual",
                is_active=form.is_active.data
            )
            
            db.session.add(exchange_rate)
            db.session.commit()
            
            flash(f"تم إضافة سعر الصرف {form.base_code.data}/{form.quote_code.data} بنجاح", "success")
            return redirect(url_for("currencies.exchange_rates"))
            
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("سعر الصرف موجود مسبقاً لهذا التاريخ")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    return render_template("currencies/exchange_rate_form.html", form=form)


@currencies_bp.route("/exchange-rates/<int:rate_id>/edit", methods=["GET", "POST"], endpoint="edit_exchange_rate")
@login_required
def edit_exchange_rate(rate_id):
    """تعديل سعر صرف"""
    exchange_rate = db.get_or_404(ExchangeRate, rate_id)
    form = ExchangeRateForm(obj=exchange_rate)
    
    if form.validate_on_submit():
        try:
            # تحديث البيانات
            exchange_rate.rate = form.rate.data
            exchange_rate.valid_from = form.valid_from.data or exchange_rate.valid_from
            exchange_rate.source = form.source.data or "Manual"
            exchange_rate.is_active = form.is_active.data
            
            db.session.commit()
            
            flash(f"تم تحديث سعر الصرف {exchange_rate.base_code}/{exchange_rate.quote_code} بنجاح", "success")
            return redirect(url_for("currencies.exchange_rates"))
            
        except IntegrityError:
            db.session.rollback()
            utils.flash_error("سعر الصرف موجود مسبقاً لهذا التاريخ")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    return render_template("currencies/exchange_rate_form.html", form=form, exchange_rate=exchange_rate)


@currencies_bp.route("/exchange-rates/<int:rate_id>/delete", methods=["POST"], endpoint="delete_exchange_rate")
@login_required
def delete_exchange_rate(rate_id):
    """حذف سعر صرف"""
    exchange_rate = db.get_or_404(ExchangeRate, rate_id)
    
    try:
        db.session.delete(exchange_rate)
        db.session.commit()
        flash(f"تم حذف سعر الصرف {exchange_rate.base_code}/{exchange_rate.quote_code} بنجاح", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error()
    
    return redirect(url_for("currencies.exchange_rates"))


@currencies_bp.route("/exchange-rates/<int:rate_id>/toggle", methods=["POST"], endpoint="toggle_exchange_rate")
@login_required
def toggle_exchange_rate(rate_id):
    """تفعيل/إلغاء تفعيل سعر صرف"""
    exchange_rate = db.get_or_404(ExchangeRate, rate_id)
    
    try:
        exchange_rate.is_active = not exchange_rate.is_active
        db.session.commit()
        
        status = "تم تفعيل" if exchange_rate.is_active else "تم إلغاء تفعيل"
        flash(f"{status} سعر الصرف {exchange_rate.base_code}/{exchange_rate.quote_code}", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        utils.flash_error()
    
    return redirect(url_for("currencies.exchange_rates"))


@currencies_bp.route("/reports", endpoint="reports")
@login_required
def currency_reports():
    """تقارير العملات"""
    from reports import customer_balance_report_ils, supplier_balance_report_ils, partner_balance_report_ils
    
    # الحصول على التقارير
    customer_report = customer_balance_report_ils()
    supplier_report = supplier_balance_report_ils()
    partner_report = partner_balance_report_ils()
    
    # إحصائيات أسعار الصرف
    total_rates = ExchangeRate.query.count()
    active_rates = ExchangeRate.query.filter_by(is_active=True).count()
    inactive_rates = total_rates - active_rates
    
    # العملات المستخدمة
    used_currencies = db.session.query(
        ExchangeRate.base_code, 
        func.count(ExchangeRate.id).label('count')
    ).group_by(ExchangeRate.base_code).all()
    
    return render_template("currencies/reports.html", 
                         customer_report=customer_report,
                         supplier_report=supplier_report,
                         partner_report=partner_report,
                         total_rates=total_rates,
                         active_rates=active_rates,
                         inactive_rates=inactive_rates,
                         used_currencies=used_currencies)

@currencies_bp.route("/update-rates", methods=["GET", "POST"], endpoint="update_rates")
@login_required
def update_exchange_rates():
    """تحديث أسعار الصرف من السيرفرات العالمية"""
    if request.method == "GET":
        # إعادة توجيه GET requests إلى صفحة أسعار الصرف
        return redirect(url_for("currencies.exchange_rates"))
    
    try:
        from models import auto_update_missing_rates
        
        result = auto_update_missing_rates()
        
        if result['success']:
            flash(f"تم تحديث {result['updated_rates']} سعر صرف بنجاح", "success")
        else:
            utils.flash_error(f"فشل في التحديث: {result['message']}")
            
        return redirect(url_for("currencies.exchange_rates"))
        
    except Exception as e:
        current_app.logger.exception('internal error')
        utils.flash_error()
        return redirect(url_for("currencies.exchange_rates"))

@currencies_bp.route("/test-rate", methods=["POST"], endpoint="test_rate")
@login_required
def test_exchange_rate():
    """اختبار سعر الصرف"""
    try:
        from models import get_fx_rate_with_fallback
        from flask import request, jsonify
        
        data = request.get_json()
        base = data.get('base', 'USD')
        quote = data.get('quote', 'ILS')
        
        rate_info = get_fx_rate_with_fallback(base, quote)
        
        return jsonify({
            'success': rate_info['success'],
            'rate': rate_info['rate'],
            'source': rate_info['source'],
            'message': f"السعر: {rate_info['rate']} (مصدر: {'محلي' if rate_info['source'] == 'local' else 'عالمي'})"
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({
            'success': False,
            'error': 'تعذر تنفيذ العملية. حاول مرة أخرى.',
            'message': 'تعذر تنفيذ العملية. حاول مرة أخرى.'
        })

@currencies_bp.route("/settings", endpoint="settings")
@login_required
def currency_settings():
    """إعدادات أسعار الصرف"""
    # إعدادات العملات
    online_fx_enabled = SystemSettings.get_setting('online_fx_enabled', True)
    fx_update_interval = SystemSettings.get_setting('fx_update_interval', 3600)  # ساعة
    
    return render_template('currencies/settings.html', 
                         online_fx_enabled=online_fx_enabled,
                         fx_update_interval=fx_update_interval)

@currencies_bp.route("/settings/toggle-online", methods=['POST'], endpoint="toggle_online")
@login_required
def toggle_online_fx():
    """تشغيل/إيقاف جلب أسعار الصرف الأونلاين"""
    try:
        current_value = SystemSettings.get_setting('online_fx_enabled', True)
        new_value = not current_value
        
        SystemSettings.set_setting(
            'online_fx_enabled', 
            new_value,
            'تشغيل/إيقاف جلب أسعار الصرف من السيرفرات الأونلاين',
            'boolean'
        )
        
        flash(f"تم {'تشغيل' if new_value else 'إيقاف'} جلب أسعار الصرف الأونلاين", 'success')
        return redirect(url_for('currencies.settings'))
    except Exception as e:
        current_app.logger.exception('internal error')
        utils.flash_error()
        return redirect(url_for('currencies.settings'))

@currencies_bp.route("/settings/update-interval", methods=['POST'], endpoint="update_interval")
@login_required
def update_fx_interval():
    """تحديث فترة تحديث أسعار الصرف"""
    try:
        interval = request.form.get('interval', type=int)
        
        if not interval or interval < 300:  # أقل من 5 دقائق
            utils.flash_error('فترة التحديث يجب أن تكون 5 دقائق على الأقل')
            return redirect(url_for('currencies.settings'))
        
        SystemSettings.set_setting(
            'fx_update_interval',
            interval,
            'فترة تحديث أسعار الصرف بالثواني',
            'number'
        )
        
        flash('تم تحديث فترة التحديث بنجاح', 'success')
        return redirect(url_for('currencies.settings'))
    except Exception as e:
        current_app.logger.exception('internal error')
        utils.flash_error()
        return redirect(url_for('currencies.settings'))

@currencies_bp.route("/settings/test-online", methods=['POST'], endpoint="test_online")
@login_required
def test_online_fx():
    """اختبار جلب أسعار الصرف الأونلاين"""
    try:
        from models import _fetch_external_fx_rate
        
        # اختبار سعر USD إلى ILS
        rate = _fetch_external_fx_rate('USD', 'ILS', datetime.now(timezone.utc))
        
        if rate and rate > 0:
            flash(f'تم جلب السعر بنجاح: 1 USD = {rate} ILS', 'success')
        else:
            utils.flash_error('فشل في جلب السعر من السيرفرات الأونلاين')
    except Exception as e:
        current_app.logger.exception('internal error')
        utils.flash_error()
    
    return redirect(url_for('currencies.settings'))
