from flask import Blueprint, jsonify, request, render_template, current_app
from flask_login import login_required
from datetime import datetime, timezone
from models import Supplier, Partner, Customer
from extensions import cache, db
from utils.balance_calculator import build_customer_balance_view
from utils.supplier_balance_updater import build_supplier_balance_view
from utils.partner_balance_updater import build_partner_balance_view
from utils import classify_entity_balance
balances_api_bp = Blueprint('balances_api', __name__, url_prefix='/api/balances')

@balances_api_bp.route('/dashboard', methods=['GET'])
@login_required
def balances_dashboard():
    from utils.company_scope import (
        filter_customers_query,
        filter_partners_query,
        filter_suppliers_query,
    )

    suppliers = filter_suppliers_query(
        Supplier.query.filter_by(is_archived=False)
    ).limit(10000).all()
    partners = filter_partners_query(
        Partner.query.filter_by(is_archived=False)
    ).limit(10000).all()
    customers = filter_customers_query(
        Customer.query.filter_by(is_archived=False)
    ).limit(10000).all()
    
    for supplier in suppliers:
        db.session.refresh(supplier)
    for partner in partners:
        db.session.refresh(partner)
    for customer in customers:
        db.session.refresh(customer)
    
    suppliers_total = sum(float(s.current_balance or 0) for s in suppliers)
    partners_total = sum(float(p.current_balance or 0) for p in partners)
    customers_total = sum(float(c.current_balance or 0) for c in customers)
    
    supplier_views = [classify_entity_balance(s.current_balance) for s in suppliers]
    partner_views = [classify_entity_balance(p.current_balance) for p in partners]
    customer_views = [classify_entity_balance(c.current_balance) for c in customers]

    summary = {
        'suppliers': {
            'count': len(suppliers),
            'total_balance': suppliers_total,
            'positive': len([v for v in supplier_views if v['balance'] > 0]),
            'negative': len([v for v in supplier_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in supplier_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in supplier_views),
        },
        'partners': {
            'count': len(partners),
            'total_balance': partners_total,
            'positive': len([v for v in partner_views if v['balance'] > 0]),
            'negative': len([v for v in partner_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in partner_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in partner_views),
        },
        'customers': {
            'count': len(customers),
            'total_balance': customers_total,
            'positive': len([v for v in customer_views if v['balance'] > 0]),
            'negative': len([v for v in customer_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in customer_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in customer_views),
        }
    }
    
    top_suppliers = sorted(
        [s for s in suppliers if float(s.current_balance or 0) > 0],
        key=lambda x: float(x.current_balance or 0),
        reverse=True,
    )[:10]
    for supplier in top_suppliers:
        db.session.refresh(supplier)
    top_customers = sorted(
        [c for c in customers if float(c.current_balance or 0) < 0],
        key=lambda x: float(x.current_balance or 0),
    )[:10]
    
    return render_template('reports/balances_dashboard.html',
                         summary=summary,
                         top_suppliers=top_suppliers,
                         top_customers=top_customers)

@balances_api_bp.route('/supplier/<int:supplier_id>', methods=['GET'])
@login_required
def get_supplier_balance(supplier_id):
    from utils.company_scope import assert_supplier_access

    assert_supplier_access(supplier_id)
    supplier = db.get_or_404(Supplier, supplier_id)
    db.session.refresh(supplier)
    breakdown = None
    try:
        breakdown = build_supplier_balance_view(supplier_id, db.session)
    except Exception as exc:
        current_app.logger.warning("supplier_balance_breakdown_api_failed: %s", exc)
    response = {
        'success': True,
        'entity_id': supplier.id,
        'entity_type': 'supplier',
        'name': supplier.name,
        'balance': float(supplier.current_balance or 0),
        'balance_in_ils': supplier.balance_in_ils,
        'currency': supplier.currency,
        'opening_balance': float(supplier.opening_balance or 0)
    }
    response.update(classify_entity_balance(supplier.current_balance))
    if breakdown and breakdown.get('success'):
        response['rights'] = breakdown.get('rights')
        response['obligations'] = breakdown.get('obligations')
        response['balance_details'] = breakdown.get('balance')
        response['payments_breakdown'] = breakdown.get('payments')
        response['checks'] = breakdown.get('checks')
        response['components'] = breakdown.get('components')
        response['balance'] = breakdown.get('balance', {}).get('amount', response['balance'])
    return jsonify(response)

@balances_api_bp.route('/partner/<int:partner_id>', methods=['GET'])
@login_required
def get_partner_balance(partner_id):
    from utils.company_scope import assert_partner_access

    assert_partner_access(partner_id)
    partner = db.get_or_404(Partner, partner_id)
    breakdown = None
    try:
        breakdown = build_partner_balance_view(partner_id, db.session)
    except Exception as exc:
        current_app.logger.warning("partner_balance_breakdown_api_failed: %s", exc)
    response = {
        'success': True,
        'entity_id': partner.id,
        'entity_type': 'partner',
        'name': partner.name,
        'balance': float(partner.current_balance or 0),
        'balance_in_ils': partner.balance_in_ils,
        'currency': partner.currency,
        'opening_balance': float(partner.opening_balance or 0),
        'share_percentage': float(partner.share_percentage or 0)
    }
    response.update(classify_entity_balance(partner.current_balance))
    if breakdown and breakdown.get('success'):
        response['rights'] = breakdown.get('rights')
        response['obligations'] = breakdown.get('obligations')
        response['balance_details'] = breakdown.get('balance')
        response['payments_breakdown'] = breakdown.get('payments')
        response['checks'] = breakdown.get('checks')
        response['components'] = breakdown.get('components')
        response['balance'] = breakdown.get('balance', {}).get('amount', response['balance'])
    return jsonify(response)

@balances_api_bp.route('/customer/<int:customer_id>', methods=['GET'])
@login_required
def get_customer_balance(customer_id):
    from utils.company_scope import assert_customer_access

    assert_customer_access(customer_id)
    customer = db.get_or_404(Customer, customer_id)
    breakdown = None
    try:
        breakdown = build_customer_balance_view(customer_id, db.session)
    except Exception as exc:
        current_app.logger.warning("customer_balance_breakdown_api_failed: %s", exc)
    response = {
        'success': True,
        'entity_id': customer.id,
        'entity_type': 'customer',
        'name': customer.name,
        'balance': float(customer.current_balance or 0),
        'currency': customer.currency,
        'opening_balance': float(customer.opening_balance or 0),
        'credit_limit': float(customer.credit_limit or 0)
    }
    response.update(classify_entity_balance(customer.current_balance))
    if breakdown and breakdown.get('success'):
        response['rights'] = breakdown.get('rights')
        response['obligations'] = breakdown.get('obligations')
        response['balance_details'] = breakdown.get('balance')
        response['checks'] = breakdown.get('checks')
    return jsonify(response)

@balances_api_bp.route('/summary', methods=['GET'])
@login_required
def get_balances_summary():
    no_cache = request.args.get('no_cache', '').lower() == '1'
    cache_key = 'balances_summary_v1'
    cached = cache.get(cache_key) if not no_cache else None
    if cached:
        return jsonify(cached)
    
    from utils.company_scope import (
        filter_customers_query,
        filter_partners_query,
        filter_suppliers_query,
    )

    suppliers = filter_suppliers_query(
        Supplier.query.filter_by(is_archived=False)
    ).limit(10000).all()
    partners = filter_partners_query(
        Partner.query.filter_by(is_archived=False)
    ).limit(10000).all()
    customers = filter_customers_query(
        Customer.query.filter_by(is_archived=False)
    ).limit(10000).all()
    
    for supplier in suppliers:
        db.session.refresh(supplier)
    for partner in partners:
        db.session.refresh(partner)
    for customer in customers:
        db.session.refresh(customer)
    
    suppliers_total = sum(float(s.current_balance or 0) for s in suppliers)
    partners_total = sum(float(p.current_balance or 0) for p in partners)
    customers_total = sum(float(c.current_balance or 0) for c in customers)
    
    supplier_views = [classify_entity_balance(s.current_balance) for s in suppliers]
    partner_views = [classify_entity_balance(p.current_balance) for p in partners]
    customer_views = [classify_entity_balance(c.current_balance) for c in customers]

    summary = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'suppliers': {
            'count': len(suppliers),
            'total_balance': suppliers_total,
            'positive': len([v for v in supplier_views if v['balance'] > 0]),
            'negative': len([v for v in supplier_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in supplier_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in supplier_views),
        },
        'partners': {
            'count': len(partners),
            'total_balance': partners_total,
            'positive': len([v for v in partner_views if v['balance'] > 0]),
            'negative': len([v for v in partner_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in partner_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in partner_views),
        },
        'customers': {
            'count': len(customers),
            'total_balance': customers_total,
            'positive': len([v for v in customer_views if v['balance'] > 0]),
            'negative': len([v for v in customer_views if v['balance'] < 0]),
            'owed_to_us_total': sum(v['owed_to_us'] for v in customer_views),
            'owed_by_us_total': sum(v['owed_by_us'] for v in customer_views),
        },
        'net_position': customers_total - suppliers_total - partners_total
    }
    
    cache.set(cache_key, summary, timeout=180)
    return jsonify(summary)

@balances_api_bp.route('/clear-cache', methods=['POST'])
@login_required
def clear_balance_cache():
    entity_type = request.json.get('entity_type')
    entity_id = request.json.get('entity_id')
    
    if entity_type and entity_id:
        cache_key = f'{entity_type}_balance_{entity_id}'
        cache.delete(cache_key)
    else:
        cache.delete('balances_summary_v1')
        cache.delete('suppliers_summary_v2')
        cache.delete('partners_summary_v2')
    
    return jsonify({'success': True, 'message': 'تم مسح الكاش'})

