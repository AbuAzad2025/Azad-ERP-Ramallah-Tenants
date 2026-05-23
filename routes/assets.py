from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import FixedAsset, FixedAssetCategory, AssetDepreciation, AssetMaintenance, Branch, Site, Partner, SystemSettings, Account
from sqlalchemy import func
from datetime import datetime, date
from decimal import Decimal
import utils

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')


def check_assets_enabled():
    if not SystemSettings.get_setting('enable_fixed_assets', False):
        flash('وحدة الأصول الثابتة غير مفعلة. يرجى تفعيلها من لوحة التحكم المالي', 'warning')
        return False
    return True


@assets_bp.route('/')
@login_required
def index():
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    status_filter = request.args.get('status', 'ACTIVE')
    category_id = request.args.get('category', None, type=int)
    branch_id = request.args.get('branch', None, type=int)
    
    query = FixedAsset.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if category_id:
        query = query.filter_by(category_id=category_id)
    if branch_id:
        query = query.filter_by(branch_id=branch_id)
    
    assets = query.order_by(FixedAsset.purchase_date.desc()).all()
    
    assets_data = []
    for asset in assets:
        book_value = asset.get_current_book_value()
        total_depreciation = float(asset.purchase_price) - book_value
        
        assets_data.append({
            'asset': asset,
            'book_value': book_value,
            'total_depreciation': total_depreciation
        })
    
    categories = FixedAssetCategory.query.filter_by(is_active=True).all()
    branches = Branch.query.filter_by(is_active=True).all()
    
    return render_template('assets/index.html',
                         assets=assets_data,
                         categories=categories,
                         branches=branches,
                         status_filter=status_filter)


@assets_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        try:
            category_id = request.form.get('category_id', type=int) or 0
            if category_id <= 0:
                flash('فئة الأصل مطلوبة', 'danger')
                return redirect(request.url)
            name = request.form.get('name')
            purchase_date = datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date()
            purchase_price_raw = (request.form.get('purchase_price') or '').strip()
            if not purchase_price_raw:
                flash('سعر الشراء مطلوب', 'danger')
                return redirect(request.url)
            try:
                purchase_price = Decimal(purchase_price_raw)
            except Exception:
                flash('قيمة سعر الشراء غير صالحة', 'danger')
                return redirect(request.url)
            branch_id = request.form.get('branch_id', type=int)
            site_id = request.form.get('site_id', type=int)
            supplier_id = request.form.get('supplier_id', type=int)
            serial_number = request.form.get('serial_number', '')
            barcode = request.form.get('barcode', '')
            location = request.form.get('location', '')
            notes = request.form.get('notes', '')
            
            last_asset = FixedAsset.query.order_by(FixedAsset.id.desc()).first()
            next_num = (last_asset.id + 1) if last_asset else 1
            asset_number = f"AST-{datetime.now().year}{next_num:05d}"
            
            asset = FixedAsset(
                asset_number=asset_number,
                name=name,
                category_id=category_id,
                branch_id=branch_id,
                site_id=site_id,
                purchase_date=purchase_date,
                purchase_price=purchase_price,
                supplier_id=supplier_id,
                serial_number=serial_number,
                barcode=barcode,
                location=location,
                status='ACTIVE',
                notes=notes
            )
            
            db.session.add(asset)
            db.session.commit()
            
            flash(f'تم إضافة الأصل {asset_number} بنجاح', 'success')
            return redirect(url_for('assets.index'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            utils.flash_error()
    
    categories = FixedAssetCategory.query.filter_by(is_active=True).all()
    branches = Branch.query.filter_by(is_active=True).all()
    sites = Site.query.filter_by(is_active=True).all()
    suppliers = Partner.query.filter(Partner.is_archived.is_(False)).order_by(Partner.id.asc()).all()
    
    return render_template('assets/form.html',
                         categories=categories,
                         branches=branches,
                         sites=sites,
                         suppliers=suppliers,
                         asset=None)


@assets_bp.route('/view/<int:id>')
@login_required
def view(id):
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    asset = db.get_or_404(FixedAsset, id)
    
    book_value = asset.get_current_book_value()
    total_depreciation = float(asset.purchase_price) - book_value
    
    depreciations = AssetDepreciation.query.filter_by(asset_id=id).order_by(
        AssetDepreciation.fiscal_year.desc(),
        AssetDepreciation.fiscal_month.desc()
    ).all()
    
    maintenance_records = AssetMaintenance.query.filter_by(asset_id=id).order_by(
        AssetMaintenance.maintenance_date.desc()
    ).all()
    
    return render_template('assets/view.html',
                         asset=asset,
                         book_value=book_value,
                         total_depreciation=total_depreciation,
                         depreciations=depreciations,
                         maintenance_records=maintenance_records)


@assets_bp.route('/categories')
@login_required
def categories():
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    categories = FixedAssetCategory.query.all()
    
    categories_data = []
    for cat in categories:
        asset_count = FixedAsset.query.filter_by(category_id=cat.id).count()
        active_count = FixedAsset.query.filter_by(category_id=cat.id, status='ACTIVE').count()
        
        categories_data.append({
            'category': cat,
            'asset_count': asset_count,
            'active_count': active_count
        })
    
    return render_template('assets/categories.html',
                         categories=categories_data)


@assets_bp.route('/report/register')
@login_required
def asset_register():
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    category_id = request.args.get('category', None, type=int)
    branch_id = request.args.get('branch', None, type=int)
    
    query = FixedAsset.query.filter_by(status='ACTIVE')
    if category_id:
        query = query.filter_by(category_id=category_id)
    if branch_id:
        query = query.filter_by(branch_id=branch_id)
    
    assets = query.order_by(FixedAsset.category_id, FixedAsset.purchase_date).all()
    
    register_data = []
    for asset in assets:
        book_value = asset.get_current_book_value()
        total_depreciation = float(asset.purchase_price) - book_value
        
        register_data.append({
            'asset': asset,
            'book_value': book_value,
            'total_depreciation': total_depreciation
        })
    
    categories = FixedAssetCategory.query.filter_by(is_active=True).all()
    branches = Branch.query.filter_by(is_active=True).all()
    
    return render_template('assets/report_register.html',
                         data=register_data,
                         categories=categories,
                         branches=branches)


@assets_bp.route('/report/depreciation')
@login_required
def depreciation_schedule():
    if not check_assets_enabled():
        return redirect(url_for('main.dashboard'))
    
    fiscal_year = request.args.get('year', datetime.now().year, type=int)
    
    depreciations = AssetDepreciation.query.filter_by(fiscal_year=fiscal_year).order_by(
        AssetDepreciation.fiscal_month,
        AssetDepreciation.asset_id
    ).all()
    
    return render_template('assets/report_depreciation.html',
                         depreciations=depreciations,
                         fiscal_year=fiscal_year)

